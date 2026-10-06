"""The published side: which items a static catalogue links, and their bodies.

Item ids are read from the collection's item links; bodies are fetched by the
published href, verbatim, never by a URL rebuilt from an id.
"""

import concurrent.futures
import hashlib
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

import requests

from stacs.verify import body_digest


def _href_to_id(href: str) -> str:
    """Item id from a published item-link href.

    The id is the basename minus `.json`, with `%20` decoded to a space and nothing
    else decoded. That is the exact inverse of an encoder that writes a space as `%20`
    and touches nothing else -- the encoder that produced the catalogues this was
    extracted from, where 90 ids carry literal spaces and parentheses.

    urllib.parse.unquote() would decode every escape, which is not that inverse. An id
    containing a literal '%' (never encoded on the way out) would come back decoded into
    a DIFFERENT id -- permanently "missing" and permanently orphaned at the same time.

    A catalogue whose ids are not their hrefs' basenames fails loudly rather than
    silently: `published_digests` and the register path refuse a body whose own `id`
    differs from the one its link implies.
    """
    name = href.rsplit("/", 1)[-1]
    if not name.endswith(".json"):
        raise ValueError(f"item link does not end in .json: {href}")
    stem = name[: -len(".json")]
    return stem.replace("%20", " ")


def collection_item_links(path) -> list[tuple[str, str]]:
    """Read (item_id, href) for every item link in a published collection.json.

    Returns hrefs verbatim — already percent-encoded, so they are usable as fetch URLs
    as-is. Never rebuild a fetch URL from the decoded id.

    Raises rather than returning a list that silently omits items, because register and
    verify both read this list and would agree with each other over the omission:

    - no item links at all: a truncated file, a catalog passed for a collection, or the
      wrong bucket -- never a legitimately empty catalogue. Against a collection that
      was never registered, an empty published set compares equal to an empty
      registered set
    - a `child` link: items behind a sub-catalogue are not read here, so they would be
      neither registered nor reported
    - two links resolving to one id (`…/2018/x.json` and `…/2019/x.json`): an id set
      collapses them, and the id comparison would read in sync
    """
    with open(path, encoding="utf-8") as f:
        collection = json.load(f)
    out = []
    seen: set[str] = set()
    for link in collection.get("links", []):
        rel = link.get("rel")
        if rel == "child":
            raise ValueError(f"{path} has a child link ({link.get('href')}); items behind "
                             f"sub-catalogues are not supported")
        if rel != "item":
            continue
        href = link["href"]
        item_id = _href_to_id(href)
        if item_id in seen:
            raise ValueError(f"{path} links id {item_id!r} more than once")
        seen.add(item_id)
        out.append((item_id, href))
    if not out:
        raise ValueError(f"{path} has no item links")
    return out


def fetch_key(url: str) -> str:
    """The fetch file's basename for a URL -- md5 of the URL, so ids with spaces and
    parentheses need no quoting anywhere downstream."""
    return hashlib.md5(url.encode()).hexdigest()


_local = threading.local()


def _read_url(url: str, timeout: int) -> bytes:
    if url.startswith("file://"):
        # Tests publish a file:// bucket. urllib reads it without any network, so
        # there is one code path rather than a test branch.
        with urllib.request.urlopen(url, timeout=timeout) as fh:
            return fh.read()
    # One Session per worker thread: a shared one caps at 10 pooled connections per
    # host and serialises the rest.
    s = getattr(_local, "session", None)
    if s is None:
        s = _local.session = requests.Session()
    resp = s.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def fetch_bodies(urls, out_dir, workers: int = 32, retries: int = 3,
                 timeout: int = 60, backoff: float = 2.0) -> list[str]:
    """Fetch each URL to `out_dir/<fetch_key(url)>.json`. Returns the URLs that failed
    after `retries` attempts, in input order.

    In-process with a thread pool rather than one `curl` per item: a shell loop took
    ~45 min for a 102k-item catalogue; 32 threads in one process fetched 2,000 in 4.9 s
    (measured 2026-09-28).

    A body counts only if it parses as a JSON object -- a truncated transfer is a failed
    attempt, retried, not a file that counts as present. Written to `.part` and renamed,
    so a failure never leaves a partial file behind.

    `out_dir` must be EMPTY. `published_digests` reads "the file exists" as "this run
    fetched it", which holds only if nothing else wrote there: a body left by an earlier
    run would be digested as current, and an item the publisher rebuilt would read
    unchanged.
    """
    out_dir = Path(out_dir)
    urls = list(urls)
    leftovers = sorted(p.name for p in out_dir.iterdir())
    if leftovers:
        raise ValueError(f"fetch directory {out_dir} is not empty ({len(leftovers)} "
                         f"entries, e.g. {leftovers[:3]}): a body already there would "
                         f"be read as this run's")

    def one(url):
        out = out_dir / f"{fetch_key(url)}.json"
        part = out.with_suffix(".json.part")
        for attempt in range(1, retries + 1):
            try:
                data = _read_url(url, timeout)
                if not isinstance(json.loads(data), dict):
                    raise ValueError("body is not a JSON object")
                part.write_bytes(data)
                os.replace(part, out)
                return None
            except (OSError, ValueError, requests.RequestException) as e:
                part.unlink(missing_ok=True)
                last = e
                if attempt < retries:
                    time.sleep(attempt * backoff)
        print(f"fetch failed after {retries} attempts: {url}: {last}",
              file=sys.stderr)
        return url

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    try:
        results = list(ex.map(one, urls))
    except BaseException:
        # Ctrl-C would otherwise wait for every queued fetch -- ~100k of them.
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    ex.shutdown()
    return [u for u in results if u is not None]


def published_digests(links, fetch_dir) -> dict[str, str]:
    """{id: body_digest} from the fetched bodies of `links` [(id, href)].

    `fetch_dir` must be one populated by a single `fetch_bodies` call (which refuses a
    non-empty directory), so a file present is a body this run read.

    Every way a published digest could be absent raises -- a body not fetched, not
    parseable, or naming a different id than its link (which would compare the wrong
    pair) -- and so does an id with two links, which a dict would otherwise collapse to
    whichever came last.
    """
    fetch_dir = Path(fetch_dir)
    out: dict[str, str] = {}
    for item_id, href in links:
        if item_id in out:
            raise ValueError(f"id {item_id!r} has more than one item link")
        path = fetch_dir / f"{fetch_key(href)}.json"
        if not path.exists():
            raise FileNotFoundError(f"body of {item_id!r} was not fetched ({href})")
        try:
            # Bytes, as `fetch_bodies` parsed them: one predicate for one body.
            doc = json.loads(path.read_bytes())
        except ValueError as e:
            raise ValueError(f"body of {item_id!r} is not JSON ({href}): {e}") from e
        if not isinstance(doc, dict) or doc.get("id") != item_id:
            got = doc.get("id") if isinstance(doc, dict) else doc
            raise ValueError(f"link for {item_id!r} fetched a body that names "
                             f"id {got!r} ({href})")
        out[item_id] = body_digest(doc)
    return out


def read_hrefs(path) -> list[tuple[str, str]]:
    """[(id, href)] from a tab-separated id/href file."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            item_id, href = line.split("\t")
            out.append((item_id, href))
    return out
