"""Contract tests for stacs.catalogue: the published side.

An item id is recoverable from a published href only by decoding exactly what the
encoder encoded; 90 items in the catalogue this was extracted from carry literal spaces
and parentheses. A fetch URL rebuilt from a decoded id cannot be formed, so the href is
always used verbatim.
"""

import hashlib
import json
import os

import pytest

from stacs import catalogue as c
from stacs.catalogue import _href_to_id, collection_item_links
from stacs.verify import body_digest

BASE = "https://bucket.example.invalid"


def _encode(stem):
    """The encoder whose exact inverse `_href_to_id` is: spaces only."""
    return stem.replace(" ", "%20")


# =============================================================================
# href -> id — the percent-decoding contract
# =============================================================================

def test_href_to_id_plain():
    assert _href_to_id(f"{BASE}/082-082e-2017-dem-x.json") == "082-082e-2017-dem-x"


def test_href_to_id_percent_encoded_space_and_parens():
    """The id carries a literal space."""
    assert _href_to_id(f"{BASE}/item_2018%20(2).json") == "item_2018 (2)"


def test_href_to_id_raises_on_non_json():
    with pytest.raises(ValueError, match="does not end in .json"):
        _href_to_id(f"{BASE}/some-item.tif")


def test_href_to_id_is_the_exact_inverse_of_the_encoder():
    """A general unquote() is not the inverse. An id carrying a literal '%' is never
    encoded on the way out, so decoding every escape on the way back yields a
    DIFFERENT id — permanently missing and permanently orphaned at once."""
    for stem in ("plain", "with space", "a (2)", "100%25", "5%_slope"):
        href = f"{BASE}/{_encode(stem)}.json"
        assert _href_to_id(href) == stem, f"round trip broke for {stem!r}"


def test_encoder_is_lossy_for_a_literal_percent_20():
    """A known, unfixable limitation — asserted so it is a decision, not a bug.

    The encoder encodes spaces and nothing else, so a filename containing the literal
    characters "%20" encodes to itself and is indistinguishable from an encoded space.
    The ambiguity is in the encoding; no decoder can separate the two.
    """
    assert _encode("a%20b") == "a%20b"
    assert _encode("a b") == "a%20b"
    assert _href_to_id(f"{BASE}/a%20b.json") == "a b"


def test_href_to_id_does_not_decode_a_literal_percent_escape():
    """`%41` in a filename is the two characters, not 'A'."""
    assert _href_to_id(f"{BASE}/report%41.json") == "report%41"


def test_collection_item_links_keeps_href_encoded(tmp_path):
    """The id is decoded; the href is NOT."""
    coll = tmp_path / "collection.json"
    coll.write_text(json.dumps({
        "id": "any-collection",
        "links": [
            {"rel": "root", "href": f"{BASE}/collection.json"},
            {"rel": "item", "href": f"{BASE}/a%20(2).json"},
            {"rel": "item", "href": f"{BASE}/b.json"},
        ],
    }))
    links = collection_item_links(coll)
    assert links == [("a (2)", f"{BASE}/a%20(2).json"), ("b", f"{BASE}/b.json")]
    assert "%20" in links[0][1]
    assert " " in links[0][0]


def test_collection_item_links_ignores_non_item_rels(tmp_path):
    coll = tmp_path / "collection.json"
    coll.write_text(json.dumps({
        "links": [
            {"rel": "self", "href": f"{BASE}/collection.json"},
            {"rel": "parent", "href": f"{BASE}/catalog.json"},
            {"rel": "item", "href": f"{BASE}/a.json"},
        ],
    }))
    assert collection_item_links(coll) == [("a", f"{BASE}/a.json")]


@pytest.mark.parametrize("links, match", [
    ([], "no item links"),
    ([{"rel": "self", "href": f"{BASE}/collection.json"}], "no item links"),
    ([{"rel": "item", "href": f"{BASE}/a.json"},
      {"rel": "child", "href": f"{BASE}/sub/catalog.json"}], "child link"),
    ([{"rel": "item", "href": f"{BASE}/2018/x.json"},
      {"rel": "item", "href": f"{BASE}/2019/x.json"}], "more than once"),
])
def test_collection_item_links_refuses_a_list_that_would_omit_items(tmp_path, links, match):
    """Register and verify both read this list, so an omission here is one they agree
    on: an empty set compares equal to an empty one, items behind a child link are
    never registered or reported, and two hrefs collapsing to one id read in sync."""
    coll = tmp_path / "collection.json"
    coll.write_text(json.dumps({"links": links}))
    with pytest.raises(ValueError, match=match):
        collection_item_links(coll)


def test_collection_item_links_refuses_a_file_with_no_links_key(tmp_path):
    coll = tmp_path / "collection.json"
    coll.write_text(json.dumps({"type": "Catalog", "id": "x"}))
    with pytest.raises(ValueError, match="no item links"):
        collection_item_links(coll)


# =============================================================================
# Fetching bodies, and their digests
# =============================================================================

def _body(item_id="x"):
    return {"type": "Feature", "stac_version": "1.0.0", "id": item_id,
            "collection": "c", "geometry": None, "properties": {},
            "assets": {}, "links": []}


def _publish(tmp_path, docs):
    """Write docs as a file:// bucket; return [(id, href)]."""
    bucket = tmp_path / "bucket"
    bucket.mkdir(exist_ok=True)
    links = []
    for d in docs:
        p = bucket / f"{d['id']}.json"
        p.write_text(json.dumps(d))
        links.append((d["id"], p.as_uri()))
    return links


def test_fetch_key_matches_the_md5_of_the_url():
    url = f"{BASE}/a b.json"
    assert c.fetch_key(url) == hashlib.md5(url.encode()).hexdigest()


def test_fetch_bodies_writes_one_file_per_url(tmp_path):
    links = _publish(tmp_path, [_body("a"), _body("b c")])
    out = tmp_path / "items"
    out.mkdir()
    failed = c.fetch_bodies([h for _, h in links], out, workers=2, backoff=0)
    assert failed == []
    for item_id, href in links:
        doc = json.loads((out / f"{c.fetch_key(href)}.json").read_text())
        assert doc["id"] == item_id
    assert not list(out.glob("*.part"))


def test_fetch_bodies_reports_what_it_could_not_fetch(tmp_path):
    links = _publish(tmp_path, [_body("a")])
    gone = (tmp_path / "bucket" / "gone.json").as_uri()
    out = tmp_path / "items"
    out.mkdir()
    failed = c.fetch_bodies([links[0][1], gone], out, workers=2, backoff=0)
    assert failed == [gone]
    assert len(list(out.glob("*.json"))) == 1
    assert not list(out.glob("*.part"))


def test_fetch_bodies_refuses_a_body_that_is_not_json(tmp_path):
    """A truncated body is a failed fetch, not a file that counts as present."""
    bad = tmp_path / "bad.json"
    bad.write_text('{"id": "a", "trunc')
    out = tmp_path / "items"
    out.mkdir()
    failed = c.fetch_bodies([bad.as_uri()], out, workers=1, backoff=0)
    assert failed == [bad.as_uri()]
    assert not list(out.glob("*.json"))


def test_published_digests_reads_the_fetched_bodies(tmp_path):
    docs = [_body("a"), _body("b")]
    links = _publish(tmp_path, docs)
    out = tmp_path / "items"
    out.mkdir()
    assert c.fetch_bodies([h for _, h in links], out, backoff=0) == []
    got = c.published_digests(links, out)
    assert got == {d["id"]: body_digest(d) for d in docs}


def test_published_digests_raises_on_a_body_that_was_not_fetched(tmp_path):
    """Absent is an error, never 'unchanged'."""
    links = _publish(tmp_path, [_body("a")])
    out = tmp_path / "items"
    out.mkdir()
    with pytest.raises(FileNotFoundError, match="a"):
        c.published_digests(links, out)


def test_published_digests_raises_on_an_unreadable_body(tmp_path):
    links = _publish(tmp_path, [_body("a")])
    out = tmp_path / "items"
    out.mkdir()
    (out / f"{c.fetch_key(links[0][1])}.json").write_text("{not json")
    with pytest.raises(ValueError, match="a"):
        c.published_digests(links, out)


def test_published_digests_raises_when_a_body_names_another_id(tmp_path):
    """A link whose body is a different item would compare the wrong pair."""
    links = _publish(tmp_path, [_body("a")])
    out = tmp_path / "items"
    out.mkdir()
    (out / f"{c.fetch_key(links[0][1])}.json").write_text(json.dumps(_body("b")))
    with pytest.raises(ValueError, match="names id 'b'"):
        c.published_digests(links, out)


def test_published_digests_raises_on_a_duplicated_id(tmp_path):
    """Two links for one id: a dict keyed by id would keep one silently."""
    links = _publish(tmp_path, [_body("a")])
    out = tmp_path / "items"
    out.mkdir()
    c.fetch_bodies([links[0][1]], out, backoff=0)
    with pytest.raises(ValueError, match="more than one item link"):
        c.published_digests(links + links, out)


def test_read_hrefs_round_trips_ids_with_spaces(tmp_path):
    p = tmp_path / "hrefs.tsv"
    p.write_text(f"a (2)\t{BASE}/a%20(2).json\nb\t{BASE}/b.json\n\n")
    assert c.read_hrefs(p) == [("a (2)", f"{BASE}/a%20(2).json"),
                               ("b", f"{BASE}/b.json")]


@pytest.mark.parametrize("payload", ["null", "[]", '"x"', "3"])
def test_fetch_bodies_refuses_json_that_is_not_an_object(tmp_path, payload):
    src = tmp_path / "b.json"
    src.write_text(payload)
    out = tmp_path / "items"
    out.mkdir()
    assert c.fetch_bodies([src.as_uri()], out, workers=1, backoff=0) == [src.as_uri()]
    assert not list(out.iterdir())


@pytest.mark.parametrize("payload", ["null", "[]"])
def test_published_digests_refuses_json_that_is_not_an_object(tmp_path, payload):
    links = _publish(tmp_path, [_body("a")])
    out = tmp_path / "items"
    out.mkdir()
    (out / f"{c.fetch_key(links[0][1])}.json").write_text(payload)
    with pytest.raises(ValueError, match="names id"):
        c.published_digests(links, out)


def test_a_failure_after_the_part_file_is_written_leaves_nothing(tmp_path, monkeypatch):
    """The .part is written, then the rename fails: neither file may remain."""
    links = _publish(tmp_path, [_body("a")])
    out = tmp_path / "items"
    out.mkdir()

    def boom(src, dst):
        assert str(src).endswith(".part") and os.path.exists(src)   # it really was written
        raise OSError("rename failed")

    monkeypatch.setattr(c.os, "replace", boom)
    assert c.fetch_bodies([links[0][1]], out, workers=1, backoff=0) == [links[0][1]]
    assert not list(out.iterdir())


def test_fetch_bodies_refuses_a_directory_an_earlier_run_wrote_to(tmp_path):
    """A body from an earlier run is not this run's. Left in place, a body this run did
    not fetch -- because it failed, or was not asked for -- would be digested as
    current, and an item the publisher rebuilt would read unchanged."""
    links = _publish(tmp_path, [_body("a"), _body("b")])
    out = tmp_path / "items"
    out.mkdir()
    assert c.fetch_bodies([h for _, h in links], out, backoff=0) == []
    with pytest.raises(ValueError, match="not empty"):
        c.fetch_bodies([links[0][1]], out, backoff=0)


@pytest.mark.parametrize("leftover", ["x.json", "x.json.part", "notes.txt"])
def test_fetch_bodies_refuses_any_leftover(tmp_path, leftover):
    links = _publish(tmp_path, [_body("a")])
    out = tmp_path / "items"
    out.mkdir()
    (out / leftover).write_text("{}")
    with pytest.raises(ValueError, match="not empty"):
        c.fetch_bodies([links[0][1]], out, backoff=0)
    assert sorted(p.name for p in out.iterdir()) == [leftover]


def test_a_body_the_fetch_accepts_is_one_the_digest_can_read(tmp_path):
    """One predicate for one body: the fetch parses bytes (a UTF-8 BOM is accepted),
    so the digest must too, or a fetched body becomes an unreadable one."""
    src = tmp_path / "a.json"
    src.write_bytes(b"\xef\xbb\xbf" + json.dumps(_body("a")).encode())
    out = tmp_path / "items"
    out.mkdir()
    links = [("a", src.as_uri())]
    assert c.fetch_bodies([src.as_uri()], out, backoff=0) == []
    assert c.published_digests(links, out) == {"a": body_digest(_body("a"))}



# =============================================================================
# Over HTTP (loopback), and an interrupted fetch
# =============================================================================

@pytest.fixture
def http_bucket(tmp_path):
    """A plain HTTP server on loopback serving tmp_path/www -- the requests path of
    `_read_url`, which every file:// test above skips."""
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    root = tmp_path / "www"
    root.mkdir()

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            # An error status whose body IS a JSON object -- an API's error document --
            # so only the status check can refuse it.
            if self.path == "/err.json":
                data = b'{"code": "ServerError", "id": "a"}'
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", 0),
                                 functools.partial(Quiet, directory=str(root)))
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    yield root, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_fetch_bodies_over_http(tmp_path, http_bucket):
    root, base = http_bucket
    (root / "a.json").write_text(json.dumps(_body("a")))
    out = tmp_path / "items"
    out.mkdir()
    gone, err = f"{base}/gone.json", f"{base}/err.json"
    failed = c.fetch_bodies([f"{base}/a.json", gone, err], out, workers=2, backoff=0)
    assert failed == [gone, err], "an error status is a failed fetch, whatever the body"
    assert not (out / f"{c.fetch_key(err)}.json").exists()
    doc = json.loads((out / f"{c.fetch_key(base + '/a.json')}.json").read_text())
    assert doc["id"] == "a"


def test_an_interrupted_fetch_returns_without_waiting_for_fetches_in_flight(
        tmp_path, monkeypatch):
    """Ctrl-C arrives in the MAIN thread while it waits on results. `Executor.map`
    cancels the queued fetches by itself; what `fetch_bodies` adds is not waiting for the
    ones already in flight -- here, one held open for 5 s."""
    import _thread
    import signal
    import threading
    import time
    release = threading.Event()
    calls = []

    def slow(url, timeout):
        calls.append(url)
        if url.endswith("/0.json"):
            time.sleep(0.2)                 # let the main thread finish submitting
            _thread.interrupt_main()
        elif url.endswith("/1.json"):
            release.wait(5)                 # in flight when Ctrl-C lands
        time.sleep(0.02)
        # A body, not an error: a failure would print after this test has ended, into
        # the next test's captured stderr.
        return b'{"id": "x"}'

    monkeypatch.setattr(c, "_read_url", slow)
    out = tmp_path / "items"
    out.mkdir()
    urls = [f"file:///x/{i}.json" for i in range(200)]
    # interrupt_main() does nothing while SIGINT is ignored, which a process started in
    # the background inherits; install the default handler for this test only.
    previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    t0 = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            c.fetch_bodies(urls, out, workers=2, retries=1, backoff=0)
        assert time.monotonic() - t0 < 2, "waited for the fetch in flight"
    finally:
        release.set()
        signal.signal(signal.SIGINT, previous)
    assert len(calls) < 20, f"{len(calls)} of {len(urls)} fetched after the interrupt"
