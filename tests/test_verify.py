"""Contract tests for stacs.verify.

Ported from stac_dem_bc's tests/test_register_manifest.py with behaviour unchanged.
The comparison has failure modes that are silent by nature, and these pin them:

1. Verification by returned-count passes vacuously, because /search silently omits ids
   that do not exist. Only set equality, in both directions, works.
2. A /search with no `limit` returns 10 features, and one with no `collections` answers
   about every collection on the endpoint.
3. Equal id sets say nothing about bodies; bodies are compared by digest, and an absent
   digest raises rather than comparing equal.
"""

import pytest

from stacs import verify as v
from stacs.verify import ids_diff, search_body

# Deliberately not any real collection id. search_body must carry through whatever it is
# handed; a fixture naming a real collection would let a hardcoded id pass this file.
COLL = "any-collection"


# =============================================================================
# ids_diff — both directions, and the vacuous-pass guard
# =============================================================================

def test_ids_diff_reports_both_directions():
    missing, orphaned = ids_diff(["a", "b", "c"], ["b", "c", "z"])
    assert missing == ["a"]
    assert orphaned == ["z"]


def test_ids_diff_empty_when_in_sync():
    missing, orphaned = ids_diff(["a", "b"], ["b", "a"])
    assert missing == []
    assert orphaned == []


def test_ids_diff_catches_a_shortfall_that_a_count_would_miss():
    """The vacuous-pass case, stated as a test.

    Both sides have 3 ids, so any check comparing LENGTHS passes. The sets are
    different, and that is the drift.
    """
    published = ["a", "b", "c"]
    registered = ["a", "b", "zzz"]
    assert len(published) == len(registered)          # a count check passes here
    missing, orphaned = ids_diff(published, registered)
    assert missing == ["c"]                            # set equality does not
    assert orphaned == ["zzz"]


# =============================================================================
# search_body — the API's default limit is 10, and an unscoped search answers
# about every collection on the endpoint
# =============================================================================

def test_search_body_always_carries_a_limit():
    """POST /search without a `limit` returns the API's default of 10 features,
    whatever the length of the ids list. Measured against a live API: 600 registered
    ids with no limit returned 10; with limit=600 it returned 600."""
    body = search_body([f"id-{i}" for i in range(600)], COLL)
    assert body["limit"] == 600


def test_search_body_limit_matches_the_id_count_at_every_size():
    for n in (1, 9, 10, 11, 500):
        body = search_body([f"id-{i}" for i in range(n)], COLL)
        assert body["limit"] == n, f"limit must equal the id count at n={n}"


def test_search_body_limit_is_never_zero():
    """limit=0 would return nothing and read as 'everything is missing'."""
    assert search_body([], COLL)["limit"] >= 1


def test_search_body_requests_only_ids():
    body = search_body(["a"], COLL)
    assert body["fields"] == {"include": ["id"]}
    assert body["ids"] == ["a"]


def test_search_body_would_have_caught_the_shipped_bug():
    """A 3-item fixture cannot reach this failure, which is why it once shipped.

    3 < 10, so the unlimited body returned all 3. The assertion has to be on a list
    LONGER than the default limit or it proves nothing.
    """
    small = search_body(["a", "b", "c"], COLL)
    assert small["limit"] == 3
    big = search_body([f"id-{i}" for i in range(11)], COLL)
    assert big["limit"] == 11 and big["limit"] > 10


def test_search_body_scopes_to_the_collection():
    """Without `collections`, /search asks "is this id served ANYWHERE". Two
    collections sharing every id on one endpoint (a rename mid-cutover) make an
    unscoped verification of the new one pass on the old one's rows."""
    body = search_body(["a", "b"], COLL)
    assert body["collections"] == [COLL]


def test_search_body_carries_through_the_id_it_is_given():
    """A body that ignored its argument would pass the assertion above if the fixture
    happened to match a hardcoded default. Two distinct ids, checked."""
    assert search_body(["a"], "one")["collections"] == ["one"]
    assert search_body(["a"], "two")["collections"] == ["two"]


@pytest.mark.parametrize("bad", ["", None])
def test_search_body_refuses_an_empty_collection_id(bad):
    """Fail loudly rather than fall back to an unscoped search."""
    with pytest.raises(ValueError, match="collection_id is required"):
        search_body(["a"], bad)


def test_search_body_for_content_omits_fields():
    b = search_body(["a", "b"], "c", ids_only=False)
    assert "fields" not in b
    assert b["limit"] == 2 and b["collections"] == ["c"]


# =============================================================================
# body_digest — content, canonicalised for pgstac's round trip
# =============================================================================

def _body(item_id="x", **props):
    return {"type": "Feature", "stac_version": "1.0.0", "id": item_id,
            "collection": "c", "bbox": [0.0, 0.0, 1.0, 1.0],
            "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
            "properties": {"datetime": "2020-01-01T00:00:00Z", **props},
            "assets": {"dem": {"href": "https://example.invalid/a.tif"}},
            "links": [{"rel": "collection",
                       "href": "https://example.invalid/collection.json"}]}


def test_body_digest_ignores_links():
    """The API rewrites links (self/root/parent, its own host); nothing else."""
    a = _body()
    b = _body()
    b["links"] = [{"rel": "self", "href": "https://api.example.invalid/items/x"},
                  {"rel": "root", "href": "https://api.example.invalid/"}]
    assert v.body_digest(a) == v.body_digest(b)


def test_body_digest_ignores_key_order():
    a = _body()
    b = dict(reversed(list(_body().items())))
    b["properties"] = dict(reversed(list(b["properties"].items())))
    assert list(a) != list(b)
    assert v.body_digest(a) == v.body_digest(b)


@pytest.mark.parametrize("mutate", [
    lambda d: d["properties"].update({"datetime": "2021-01-01T00:00:00Z"}),
    lambda d: d["properties"].update({"file:checksum": "1220abc"}),
    lambda d: d["assets"].update({"dsm": {"href": "https://example.invalid/b.tif"}}),
    lambda d: d["assets"]["dem"].update({"href": "https://example.invalid/other.tif"}),
    lambda d: d["geometry"].update({"coordinates": [0.5, 0.5000001]}),
    lambda d: d.update({"collection": "d"}),
    lambda d: d["properties"].pop("datetime"),
])
def test_body_digest_changes_on_any_content_change(mutate):
    a = _body()
    b = _body()
    mutate(b)
    assert v.body_digest(a) != v.body_digest(b)


def test_body_digest_treats_a_null_member_as_absent():
    """pgstac strips null members, so the API cannot say `"proj:epsg": null`. The first
    full live verify of a 102k-item catalogue reported 160 items changed on this."""
    a = _body()
    b = _body()
    a["properties"]["proj:epsg"] = None
    a["assets"]["dem"]["title"] = None
    assert v.body_digest(a) == v.body_digest(b)


def test_body_digest_keeps_a_null_array_element():
    """jsonb_strip_nulls leaves arrays alone: a null there is positional."""
    a = _body()
    b = _body()
    a["properties"]["proj:shape"] = [None, 5]
    b["properties"]["proj:shape"] = [5]
    assert v.body_digest(a) != v.body_digest(b)


def test_body_digest_still_sees_null_become_a_value():
    a = _body()
    b = _body()
    a["properties"]["proj:epsg"] = None
    b["properties"]["proj:epsg"] = 26911
    assert v.body_digest(a) != v.body_digest(b)


@pytest.mark.parametrize("published, served", [
    (-126.0, -126),          # PostGIS rebuilds geometry: 29 live items, 2026-09-29
    (-0.0, 0),               # numeric has no negative zero
    (1e16, 10000000000000000),   # numeric emits a large integral float as an int
])
def test_body_digest_treats_an_integral_float_as_the_integer(published, served):
    """JSON has one number type. pgstac's round trip does not keep the spelling, so
    neither can the comparison, or those items never converge."""
    a = _body()
    b = _body()
    a["geometry"]["coordinates"] = [published, 0.5]
    b["geometry"]["coordinates"] = [served, 0.5]
    assert v.body_digest(a) == v.body_digest(b)


def test_body_digest_still_sees_a_fractional_change():
    a = _body()
    b = _body()
    a["geometry"]["coordinates"] = [-126.0, 0.5]
    b["geometry"]["coordinates"] = [-126.5, 0.5]
    assert v.body_digest(a) != v.body_digest(b)


def test_body_digest_does_not_read_a_bool_as_a_number():
    a = _body()
    b = _body()
    a["properties"]["flag"] = True
    b["properties"]["flag"] = 1
    assert v.body_digest(a) != v.body_digest(b)


@pytest.mark.parametrize("bad", [None, [], "x", 0])
def test_body_digest_refuses_a_non_object(bad):
    """None must not hash to something that equals another None."""
    with pytest.raises(TypeError):
        v.body_digest(bad)


# =============================================================================
# content_diff
# =============================================================================

def test_content_diff_reports_changed_ids():
    published = {"a": "1", "b": "2", "c": "3"}
    registered = {"a": "1", "b": "X", "z": "9"}
    missing, orphaned, changed = v.content_diff(published, registered)
    assert missing == ["c"]
    assert orphaned == ["z"]
    assert changed == ["b"]


def test_content_diff_is_empty_when_in_sync():
    d = {"a": "1", "b": "2"}
    assert v.content_diff(d, dict(d)) == ([], [], [])


@pytest.mark.parametrize("side", ["published", "registered"])
@pytest.mark.parametrize("bad", [None, ""])
def test_content_diff_refuses_an_absent_digest(side, bad):
    """Two absent digests must not compare equal -- they must not compare at all."""
    good = {"a": "1"}
    broken = {"a": bad}
    pub, reg = (broken, good) if side == "published" else (good, broken)
    with pytest.raises(ValueError):
        v.content_diff(pub, reg)
    with pytest.raises(ValueError):
        v.content_diff(broken, dict(broken))


# =============================================================================
# Enumeration — keyset paging
# =============================================================================

class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise v.requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


class _PagingSession:
    """Serves `docs` over keyset paging the way stac-fastapi does."""

    def __init__(self, docs, page=2):
        self.docs, self.page, self.bodies = docs, page, []

    def post(self, url, json=None, timeout=None):
        self.bodies.append(json)
        start = int(json.get("token") or 0)
        chunk = self.docs[start:start + self.page]
        links = []
        if start + self.page < len(self.docs):
            links.append({"rel": "next", "body": {"token": str(start + self.page)}})
        return _FakeResponse({"features": chunk, "links": links})


def test_bodies_registered_pages_full_bodies():
    docs = [_body(i) for i in "abcde"]
    s = _PagingSession(docs, page=2)
    got = v.bodies_registered("c", api="http://api.example.invalid", session=s)
    assert got == {d["id"]: v.body_digest(d) for d in docs}
    assert len(s.bodies) == 3
    # Full bodies: a `fields` include of ["id"] would hash an id-only stub.
    assert all("fields" not in b for b in s.bodies)
    assert all(b["collections"] == ["c"] for b in s.bodies)


def test_bodies_registered_raises_on_a_repeated_id():
    """A page overlap would otherwise collapse silently into one dict entry."""
    docs = [_body("a"), _body("b"), _body("b")]
    with pytest.raises(RuntimeError, match="'b'"):
        v.bodies_registered("c", api="http://api.example.invalid",
                            session=_PagingSession(docs, page=2))


def test_ids_registered_still_asks_for_ids_only():
    docs = [{"id": i} for i in "abc"]
    s = _PagingSession(docs, page=2)
    assert v.ids_registered("c", api="http://api.example.invalid", session=s) == [
        "a", "b", "c"]
    assert all(b["fields"] == {"include": ["id"]} for b in s.bodies)


def test_ids_registered_scopes_to_the_collection():
    s = _PagingSession([{"id": "a"}], page=2)
    v.ids_registered("c", api="http://api.example.invalid", session=s)
    assert all(b["collections"] == ["c"] for b in s.bodies)


def test_ids_registered_raises_on_a_repeated_id():
    """An overlap can as easily skip an item, which would hide an orphan."""
    docs = [{"id": "a"}, {"id": "b"}, {"id": "b"}]
    with pytest.raises(RuntimeError, match="'b'"):
        v.ids_registered("c", api="http://api.example.invalid",
                         session=_PagingSession(docs, page=2))


class _ScriptedSession:
    """Answers each POST with the next scripted payload."""

    def __init__(self, *payloads):
        self.payloads, self.bodies = list(payloads), []

    def post(self, url, json=None, timeout=None):
        self.bodies.append(json)
        return _FakeResponse(self.payloads.pop(0))


@pytest.mark.parametrize("payloads, match", [
    ([{"features": [{"id": "a"}], "links": [{"rel": "next", "body": {}}]}],
     "no token"),
    ([{"features": [{"id": "a"}], "links": [{"rel": "next", "body": {"token": "t"}}]},
      {"features": [{"id": "b"}], "links": [{"rel": "next", "body": {"token": "t"}}]}],
     "repeated"),
    ([{"links": []}], "no feature list"),
    ([{"features": [{"id": "a"}]}], "no links"),
    ([{"features": [{"id": "a"}], "links": [{"rel": "next", "body": {"token": "t"}}]},
      {"type": "error"}], "no feature list"),
])
def test_paging_refuses_every_early_exit(payloads, match):
    """Every way out other than "no next link" raises: a short enumeration reads as
    everything after it missing, and hides orphans in the pages never read."""
    with pytest.raises(RuntimeError, match=match):
        v.ids_registered("c", api="http://api.example.invalid",
                         session=_ScriptedSession(*payloads))


class _ServingSession:
    """POST /search by ids within one collection, capped at `cap` per page."""

    def __init__(self, docs, collection="c", cap=10000):
        self.docs = {d["id"]: d for d in docs}
        self.collection, self.cap, self.bodies = collection, cap, []

    def post(self, url, json=None, timeout=None):
        self.bodies.append(json)
        hits = [] if json.get("collections") != [self.collection] else [
            self.docs[i] for i in json["ids"] if i in self.docs]
        if "fields" in json:
            hits = [{"id": d["id"]} for d in hits]
        limit = min(json.get("limit", 10), self.cap)
        links = [{"rel": "next", "body": {"token": "x"}}] if len(hits) > limit else []
        return _FakeResponse({"features": hits[:limit], "links": links})


def test_bodies_serving_reads_full_bodies_across_chunks():
    docs = [_body(f"i{n}") for n in range(12)]
    s = _ServingSession(docs)
    got = v.bodies_serving([d["id"] for d in docs] + ["absent"], "c",
                           api="http://api.example.invalid", chunk=5, session=s)
    assert got == {d["id"]: v.body_digest(d) for d in docs}
    assert len(s.bodies) == 3
    assert all("fields" not in b and b["collections"] == ["c"]
               and b["limit"] == len(b["ids"]) for b in s.bodies)


@pytest.mark.parametrize("payload", [{"links": []}, {"type": "error"}, []])
def test_bodies_serving_refuses_a_response_with_no_feature_list(payload):
    with pytest.raises(RuntimeError, match="no feature list"):
        v.bodies_serving(["a"], "c", api="http://api.example.invalid",
                         session=_ScriptedSession(payload))


def test_bodies_serving_refuses_a_server_that_caps_the_limit():
    """The ids past the cap would otherwise read as "not served"."""
    docs = [_body(f"i{n}") for n in range(5)]
    with pytest.raises(RuntimeError, match="caps limit"):
        v.bodies_serving([d["id"] for d in docs], "c",
                         api="http://api.example.invalid",
                         session=_ServingSession(docs, cap=2))


class _GetSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, timeout=None):
        self.calls.append(url)
        key = "collections" if url.endswith("/collections") else "collections/c"
        status, payload = self.routes[key]
        return _FakeResponse(payload, status)


def _coll_file(tmp_path, doc):
    p = tmp_path / "collection.json"
    p.write_text(__import__("json").dumps(doc))
    return p


COLL_DOC = {"type": "Collection", "id": "c", "description": "d", "links": []}


@pytest.mark.parametrize("served, want", [
    ((200, dict(COLL_DOC, links=[{"rel": "self", "href": "x"}])), "same"),
    ((200, dict(COLL_DOC, description="other")), "changed"),
    ((404, {"code": "NotFoundError"}), "missing"),
])
def test_collection_state(tmp_path, served, want):
    s = _GetSession({"collections/c": served, "collections": (200, {"collections": []})})
    assert v.collection_state(_coll_file(tmp_path, COLL_DOC), "c",
                              api="http://api.example.invalid", session=s) == want


@pytest.mark.parametrize("routes", [
    {"collections/c": (503, {}), "collections": (200, {})},
    # A wrong path prefix: the collection 404s AND so does /collections.
    {"collections/c": (404, {"detail": "Not Found"}), "collections": (404, {})},
])
def test_collection_state_never_reads_an_unreachable_api_as_an_answer(
        tmp_path, monkeypatch, routes):
    monkeypatch.setattr(v.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="failed after"):
        v.collection_state(_coll_file(tmp_path, COLL_DOC), "c",
                           api="http://api.example.invalid", session=_GetSession(routes))


def test_post_raises_on_a_server_error_with_a_json_body(monkeypatch):
    """Without raise_for_status a 5xx JSON error ends paging with no features."""
    monkeypatch.setattr(v.time, "sleep", lambda s: None)

    class S:
        n = 0

        def post(self, url, json=None, timeout=None):
            S.n += 1
            return _FakeResponse({"features": [], "links": []}, status=502)

    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        v.ids_registered("c", api="http://api.example.invalid", session=S())
    assert S.n == v.RETRIES


# =============================================================================
# RFC 8785 (JCS) -- the canonical form, against the RFC's own vector
# =============================================================================
#
# Strings are built from chr() codes: an escape typed into this file is a second
# parser between the RFC and the test.

BS, DQ = chr(92), chr(34)


def test_canonical_json_matches_the_rfc_8785_sample():
    """RFC 8785 section 3.2.3: numbers, string escaping and key order in one object.
    Self-consistency cannot show the form is JCS; the RFC's output can."""
    string = chr(0x20AC) + "$" + chr(0x0F) + chr(0x0A) + "A'B" + DQ + BS + BS + DQ + "/"
    doc = {"numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27],
           "string": string, "literals": [None, True, False]}
    want = ('{"literals":[null,true,false],'
            '"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
            '"string":"' + chr(0x20AC) + "$" + BS + "u000f" + BS + "nA'B"
            + BS + DQ + BS + BS + BS + BS + BS + DQ + '/"}')
    assert v.canonical_json(doc) == want.encode("utf-8")


def test_canonical_json_orders_keys_by_utf16_code_unit():
    """JCS sorts by UTF-16 code units, not code points: a key outside the BMP (a
    surrogate pair, 0xD83D...) sorts BEFORE one at U+FF61. Python's sorted() is the
    other way round, which is what made the old form not JCS."""
    astral, high_bmp = chr(0x1F600), chr(0xFF61)
    assert sorted([astral, high_bmp]) == [high_bmp, astral]
    out = v.canonical_json({high_bmp: 1, astral: 2}).decode("utf-8")
    assert out.index(astral) < out.index(high_bmp)


def test_canonical_json_writes_non_ascii_as_utf8():
    out = v.canonical_json({"title": "Bulkley " + chr(0xE9) + "t" + chr(0xE9)})
    assert out == '{"title":"Bulkley été"}'.encode("utf-8")


def test_canonical_json_drops_links_and_null_members():
    out = v.canonical_json({"id": "a", "links": [{"rel": "self"}], "x": None,
                            "y": [None]})
    assert out == b'{"id":"a","y":[null]}'


@pytest.mark.parametrize("published, served", [
    (-126.0, -126),
    (-0.0, 0),
    (1e16, 10000000000000000),
    (-1e16, -10000000000000000),  # the lower bound of the conversion
    (1.5e300, int(1.5e300)),     # served as a 301-digit integer of the double's value
])
def test_an_integral_float_and_its_served_integer_digest_equal(published, served):
    assert v.body_digest({"n": published}) == v.body_digest({"n": served})


def test_distinct_integers_beyond_2_53_that_round_together_digest_equal():
    """A decision, pinned so it is not rediscovered as a bug: JCS reads every number as
    a double, and 2^53 and 2^53+1 are one double. Below 2^53 nothing collapses."""
    assert v.body_digest({"n": 2**53}) == v.body_digest({"n": 2**53 + 1})
    assert v.body_digest({"n": 2**53 - 1}) != v.body_digest({"n": 2**53 - 2})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"),
                                   10**400, chr(0xD800)])
def test_a_body_with_no_canonical_form_raises_a_named_error(value):
    """json.loads accepts NaN, Infinity, huge integers and lone surrogates. None of them
    has a JCS form; each is reported against its item, never compared."""
    with pytest.raises(v.DigestError, match="'item-7'"):
        v.body_digest({"id": "item-7", "properties": {"x": value}})


def test_a_lone_surrogate_in_a_key_raises_a_named_error():
    """Keys take a different path through rfc8785 (its UTF-16 sort) than values."""
    with pytest.raises(v.DigestError, match="'item-7'"):
        v.body_digest({"id": "item-7", "properties": {chr(0xD800): 1}})


def test_a_digest_error_is_a_value_error():
    """Callers that already refuse an unreadable body (ValueError) refuse this too."""
    assert issubclass(v.DigestError, ValueError)
