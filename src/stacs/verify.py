"""What a STAC API serves, compared with what is published.

Two comparisons, and neither is a count:

- **id sets, in both directions.** A `/search` on a list of ids silently omits the ids
  it does not have, so "asked for N, got N" can be true while the sets differ.
- **bodies, by digest.** A rebuild keeps every id, so equal id sets say nothing about
  whether the API serves the body that was published.

Every way a digest can be absent raises rather than comparing: an unread body is an
error, never "unchanged".

The API base URL and the collection id are always the caller's. Nothing here defaults
to a deployment.
"""

import hashlib
import json
import time
import urllib.parse

import requests

# Transient-failure retries on API reads. The verifier runs AFTER an upsert has already
# succeeded, so an unretried 5xx would turn a completed registration into a traceback.
# A whole-catalogue verify is hundreds of POSTs; at that count "transient" is routine.
RETRIES = 3

# Keyset paging page size. A STAC API without the aggregation extension returns a null
# numberMatched, so enumerating ids is the only way to count anything -- 102,460 ids
# came back in 11 requests at this size.
PAGE_SIZE = 10000


def _post(session, url, body, timeout=180):
    """POST with retries on transient failures. Raises after the last attempt."""
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = session.post(url, json=body, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last = exc
            if attempt < RETRIES:
                time.sleep(attempt * 2)
    raise RuntimeError(f"API request failed after {RETRIES} attempts: {last}") from last


# =============================================================================
# Enumerating what the API serves
# =============================================================================

def _search_pages(session, api: str, body: dict):
    """Yield each page's features from POST /search, following keyset paging.

    stac-fastapi returns the continuation in the next link's BODY, not its href. Every
    way out other than "no next link" raises: a short enumeration makes every
    unenumerated item report as missing and makes a stale body invisible, which would
    send a drift run to re-register a catalogue that was fine.
    """
    url = f"{api.rstrip('/')}/search"
    seen_tokens: set[str] = set()
    n = 0
    while True:
        page = _post(session, url, body)
        feats = page.get("features") if isinstance(page, dict) else None
        if not isinstance(feats, list):
            # A 200 with no feature list is not an empty last page. Read as one, it
            # ends the enumeration early and hides whatever was not yet read.
            raise RuntimeError(f"/search returned no feature list after {n} items")
        n += len(feats)
        yield feats
        links = page.get("links")
        if not isinstance(links, list):
            # "No next link" is the only normal way out, and it can only be read from
            # a page that has links. A STAC API always sends some (self, root).
            raise RuntimeError(f"/search returned no links after {n} items, so "
                               f"whether there are more pages cannot be told")
        nxt = next((l for l in links if l.get("rel") == "next"), None)
        if not nxt:
            # The only NORMAL way out: the server says there is no more.
            return
        token = (nxt.get("body") or {}).get("token")
        if not token:
            raise RuntimeError(
                f"paging stopped early: 'next' link with no token after {n} items"
            )
        if token in seen_tokens:
            raise RuntimeError(f"paging token repeated after {n} items — not advancing")
        seen_tokens.add(token)
        body = {**body, **nxt["body"]}


def ids_registered(collection_id: str, api: str, page_size: int = PAGE_SIZE,
                   session=None) -> list[str]:
    """Every item id the API currently serves for a collection.

    Keyset paging over POST /search with fields:{include:["id"]}.
    """
    session = session or requests.Session()
    body = {
        "collections": [collection_id],
        "limit": page_size,
        "fields": {"include": ["id"]},
    }
    out: list[str] = []
    seen: set[str] = set()
    for feats in _search_pages(session, api, body):
        for f in feats:
            # As in bodies_registered: a repeated id means the paging overlapped,
            # and an overlap can as easily have skipped an item -- an orphan hidden.
            if f["id"] in seen:
                raise RuntimeError(f"id {f['id']!r} returned twice while paging "
                                   f"{collection_id}: the enumeration overlapped")
            seen.add(f["id"])
            out.append(f["id"])
    return out


def bodies_registered(collection_id: str, api: str, page_size: int = PAGE_SIZE,
                      session=None) -> dict[str, str]:
    """{id: body_digest} for every item the API serves in a collection.

    The same enumeration as `ids_registered`, but of FULL bodies -- no `fields`
    include, since a digest of an id-only stub would compare equal to nothing and
    differ from everything. Measured 2026-09-28: a 10,000-item page is 18 MB and 29 s,
    so a 102k-item catalogue is ~5.5 min. Only the digest is kept, so memory is ~100
    bytes an item rather than the body.

    A repeated id raises. The API's primary key makes one impossible, so seeing one
    means the paging overlapped -- and a dict keyed by id would have collapsed it
    silently into a single entry.
    """
    session = session or requests.Session()
    body = {"collections": [collection_id], "limit": page_size}
    out: dict[str, str] = {}
    for feats in _search_pages(session, api, body):
        for f in feats:
            if f["id"] in out:
                raise RuntimeError(f"id {f['id']!r} returned twice while paging "
                                   f"{collection_id}: the enumeration overlapped")
            out[f["id"]] = body_digest(f)
    return out


def search_body(ids, collection_id: str, ids_only: bool = True) -> dict:
    """The POST /search body for an id lookup, scoped to one collection.

    Pure, and separated out so it can be asserted on offline. Two parameters, each of
    which exists because omitting it fails silently.

    `limit`: the API's DEFAULT LIMIT IS 10, so a body without one silently returns the
    first 10 of however many ids were asked for. That reads as "590 of my 600 items are
    missing". Measured against a live API: 600 registered ids, no limit -> 10 features;
    limit=600 -> 600.

    `collections`: without it a /search asks "is this id served ANYWHERE", which is a
    different question from the one every caller means. Two collections sharing ids on
    one endpoint (a rename, mid-cutover) make an unscoped verification pass on the old
    collection's rows while zero items registered into the new one. The collection id
    is required rather than defaulted, because a default is exactly the thing that
    would go unnoticed.

    `ids_only=False` drops the `fields` include, for a caller comparing content: the
    digest of an id-only stub matches no real body.
    """
    ids = list(ids)
    if not collection_id:
        raise ValueError("collection_id is required: an unscoped /search "
                         "answers about every collection on the endpoint")
    body = {
        "collections": [collection_id],
        "ids": ids,
        "limit": max(len(ids), 1),
    }
    if ids_only:
        body["fields"] = {"include": ["id"]}
    return body


def bodies_serving(ids, collection_id: str, api: str, chunk: int = 500,
                   session=None) -> dict[str, str]:
    """{id: body_digest} for those of these ids the API serves IN THIS COLLECTION.

    Batched because a very long id list is a real request-size ceiling. An id the API
    does not serve is simply absent from the result -- a /search omits ids that do not
    exist without erroring -- so the caller compares key SETS, never a count, and then
    the digests.
    """
    session = session or requests.Session()
    url = f"{api.rstrip('/')}/search"
    ids = list(ids)
    got: dict[str, str] = {}
    for i in range(0, len(ids), chunk):
        batch = ids[i:i + chunk]
        page = _post(session, url, search_body(batch, collection_id, ids_only=False))
        feats = page.get("features") if isinstance(page, dict) else None
        if not isinstance(feats, list):
            raise RuntimeError("/search returned no feature list")
        # A server that caps `limit` below the chunk answers with a next link, and the
        # ids past the cap would otherwise read as "not served".
        if any(l.get("rel") == "next" for l in page.get("links", [])):
            raise RuntimeError(f"/search paged a {len(batch)}-id lookup: the server "
                               f"caps limit below the chunk size; lower it")
        for f in feats:
            got[f["id"]] = body_digest(f)
    return got


def ids_diff(published, registered) -> tuple[list[str], list[str]]:
    """(missing, orphaned) — reported in BOTH directions.

    missing  = published but not registered (the API is behind the catalogue)
    orphaned = registered but not published (a delete never propagated)

    Set equality is the only sound check here: a /search on a list of ids returns the
    ones that exist and silently omits the rest, so asserting on the returned *count*
    passes vacuously.
    """
    p, r = set(published), set(registered)
    return sorted(p - r), sorted(r - p)


# =============================================================================
# Content -- the ids match and the bodies do not
# =============================================================================

def _canonical(x):
    """The form both sides of the comparison are reduced to before hashing.

    Two things pgstac's round trip does not preserve, each measured on a live
    catalogue, and each of which would otherwise report items "changed" forever and
    make a drift run re-register them every time without converging:

    - null object members are dropped. pgstac stores jsonb with nulls stripped, so
      `"proj:epsg": null` is served with the key absent. Like Postgres'
      `jsonb_strip_nulls`, this removes object FIELDS and never array elements -- a
      null in an array is positional
    - an integral float comes back as an integer. JSON has one number type, and
      PostGIS rebuilds geometry: `-126.0` is served as `-126`. The same rule covers
      `-0.0` (numeric has no negative zero) and floats of 1e16 and up (numeric emits
      them as integers). `bool` is left alone -- it is an int in Python, not a float,
      and `true` is not `1`.
    """
    if isinstance(x, dict):
        return {k: _canonical(v) for k, v in x.items() if v is not None}
    if isinstance(x, list):
        return [_canonical(v) for v in x]
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x


def body_digest(doc) -> str:
    """sha256 of a STAC object's canonical JSON: `links` removed, null members dropped
    and integral floats written as integers (see `_canonical`), keys sorted.

    `links` is the one member the API rewrites: it replaces the published `collection`
    link with its own self/root/parent/collection set on its own host. Everything else
    round-trips through pgstac apart from the two differences `_canonical` absorbs.

    Refuses anything but an object. A None that hashed would equal every other None.
    """
    if not isinstance(doc, dict):
        raise TypeError(f"expected a JSON object, got {type(doc).__name__}")
    canon = _canonical({k: v for k, v in doc.items() if k != "links"})
    return hashlib.sha256(
        json.dumps(canon, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def content_diff(published: dict, registered: dict) -> tuple[list, list, list]:
    """(missing, orphaned, changed) from two {id: digest} maps.

    `changed` = in both, digests differ. An empty or None digest on EITHER side raises:
    it means a body was never read, and two unread bodies must not compare equal.
    """
    for side, d in (("published", published), ("registered", registered)):
        bad = sorted(k for k, v in d.items() if not isinstance(v, str) or not v)
        if bad:
            raise ValueError(f"{len(bad)} {side} id(s) have no body digest, "
                             f"e.g. {bad[:3]}: a body was not read")
    missing, orphaned = ids_diff(published, registered)
    changed = sorted(k for k in published.keys() & registered.keys()
                     if published[k] != registered[k])
    return missing, orphaned, changed


def collection_state(collection_file, collection_id: str, api: str,
                     session=None) -> str:
    """'same', 'changed' or 'missing': the registered collection vs the file.

    404 is 'missing' (never registered). Any other failure raises after retries, so an
    unreachable API cannot read as 'same'.
    """
    with open(collection_file, encoding="utf-8") as fh:
        published = json.load(fh)
    session = session or requests.Session()
    url = f"{api.rstrip('/')}/collections/{urllib.parse.quote(collection_id)}"
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = session.get(url, timeout=180)
            if resp.status_code == 404:
                # Only a 404 from an API that answers /collections means "not
                # registered". A wrong `api` path prefix 404s here too.
                root = session.get(f"{api.rstrip('/')}/collections", timeout=180)
                root.raise_for_status()
                return "missing"
            resp.raise_for_status()
            registered = resp.json()
            break
        except requests.RequestException as exc:
            last = exc
            if attempt < RETRIES:
                time.sleep(attempt * 2)
    else:
        raise RuntimeError(f"API request failed after {RETRIES} attempts: {last}") from last
    return "same" if body_digest(published) == body_digest(registered) else "changed"
