"""Contract tests for stacs.validate.

The audit's property is HOMOGENEITY: every item agrees with the collection it is about to
be registered into, and with the catalogue's declared asset rules. Ported from
stac_dem_bc's tests/test_item_migrate.py (the audit_items tests) and the audit-items CLI
branch of register_manifest.py, with neutral fixtures: NEW and OLD are any two collection
ids, KEEP and RETIRED any two asset keys.
"""

import json
import os

import pytest

from stacs import validate as val

NEW, OLD = "new-collection", "old-collection"
KEEP, RETIRED = "data", "legacy"


def _item(item_id, collection=NEW, assets=(KEEP,), stac_version="1.1.0"):
    return {"type": "Feature", "stac_version": stac_version, "stac_extensions": [],
            "id": item_id, "collection": collection,
            "geometry": {"type": "Point", "coordinates": [-126.0, 54.0]},
            "bbox": [-126.0, 54.0, -126.0, 54.0],
            "properties": {"datetime": "2020-01-01T00:00:00Z"},
            "links": [{"rel": "collection",
                       "href": "https://example.invalid/collection.json"}],
            "assets": {k: {"href": f"https://example.invalid/{item_id}/{k}.tif"}
                       for k in assets}}


def _write(tmp_path, doc, name=None):
    p = tmp_path / f"{name or doc['id']}.json"
    p.write_text(json.dumps(doc))
    return str(p)


# =============================================================================
# audit_items -- the homogeneity gate
# =============================================================================

def test_audit_passes_a_homogeneous_population(tmp_path):
    paths = [_write(tmp_path, _item(f"x{i}")) for i in range(3)]
    r = val.audit_items(paths, NEW, require_asset=KEEP, forbid_assets=[RETIRED])
    assert r.ok, r.failures
    assert r.checked == 3


def test_audit_catches_a_mixed_population(tmp_path):
    """THE failure. One stale item among many, which every other check misses: ids do
    not change in a rename, and pgstac routes each item by its own collection field."""
    paths = [_write(tmp_path, _item(f"good{i}")) for i in range(2)]
    paths.append(_write(tmp_path, _item("stale", collection=OLD, assets=(RETIRED,))))
    r = val.audit_items(paths, NEW, require_asset=KEEP, forbid_assets=[RETIRED])
    assert not r.ok
    assert r.checked == 3
    assert len(r.wrong_collection) == len(r.forbidden_asset) == len(r.missing_asset) == 1
    assert "stale" in r.wrong_collection[0]


def test_audit_reports_paths_not_counts(tmp_path):
    p = _write(tmp_path, _item("stale", collection=OLD))
    assert val.audit_items([p], NEW).wrong_collection == [p]


def test_audit_reports_an_unreadable_item_rather_than_skipping_it(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{not json")
    r = val.audit_items([str(bad)], NEW)
    assert r.checked == 0 and len(r.unreadable) == 1 and not r.ok


@pytest.mark.parametrize("payload", ["null", "[]", '"x"'])
def test_audit_reports_json_that_is_not_an_object(tmp_path, payload):
    bad = tmp_path / "odd.json"
    bad.write_text(payload)
    r = val.audit_items([str(bad)], NEW)
    assert len(r.unreadable) == 1 and not r.ok


@pytest.mark.parametrize("assets", ["data", ["data"], 5])
def test_assets_that_are_not_an_object_cannot_satisfy_a_requirement(tmp_path, assets):
    """`"data" in "data"` is a substring match and `"data" in ["data"]` membership:
    either would satisfy require_asset for an item with no asset at all."""
    doc = _item("odd")
    doc["assets"] = assets
    r = val.audit_items([_write(tmp_path, doc)], NEW, require_asset="data")
    assert not r.ok and len(r.unreadable) == 1 and r.checked == 0


def test_null_assets_read_as_no_assets(tmp_path):
    doc = _item("bare")
    doc["assets"] = None
    r = val.audit_items([_write(tmp_path, doc)], NEW, require_asset=KEEP)
    assert not r.ok and r.missing_asset


@pytest.mark.parametrize("bad", [None, "", "  "])
def test_an_empty_collection_id_is_refused(tmp_path, bad):
    """It would match every item that names no collection."""
    doc = _item("x")
    del doc["collection"]
    with pytest.raises(ValueError, match="collection_id is required"):
        val.audit_items([_write(tmp_path, doc)], bad)


@pytest.mark.parametrize("bad", ["", "  ", 5])
def test_an_empty_require_key_is_refused_not_ignored(tmp_path, bad):
    """`--require-asset "$UNSET"` once failed every item; it must not pass them all."""
    with pytest.raises(ValueError, match="require_asset"):
        val.audit_items([_write(tmp_path, _item("x", assets=()))], NEW, require_asset=bad)


def test_audit_over_nothing_is_a_failure(tmp_path):
    """A loop over an empty set exits without complaint, which reads as "everything
    checked out" -- and would bless an unpublished catalogue."""
    r = val.audit_items([], NEW, require_asset=KEEP)
    assert r.checked == 0
    assert not r.ok
    assert any("no item" in f for f in r.failures)


def test_audit_forbids_every_retired_key_not_just_the_first(tmp_path):
    """A rename can retire more than one key. A single-string parameter once meant a
    comma-joined value matched no real key and the check silently stopped checking."""
    p = _write(tmp_path, _item("legacy", assets=("other_old_key",)))
    r = val.audit_items([p], NEW, forbid_assets=[RETIRED, "other_old_key"])
    assert r.forbidden_asset == [p]


def test_audit_reports_an_item_once_even_when_it_carries_two_retired_keys(tmp_path):
    p = _write(tmp_path, _item("both", assets=(RETIRED, "other_old_key")))
    r = val.audit_items([p], NEW, forbid_assets=[RETIRED, "other_old_key"])
    assert r.forbidden_asset == [p], "one path, not one per matching key"


def test_audit_with_no_forbidden_keys_forbids_nothing(tmp_path):
    """None and an empty list are "no rule"."""
    p = _write(tmp_path, _item("ok"))
    for empty in (None, [], ()):
        r = val.audit_items([p], NEW, require_asset=KEEP, forbid_assets=empty)
        assert r.ok and not r.forbidden_asset


@pytest.mark.parametrize("value, keys", [
    (None, []), ([], []), ((), []),
    ("legacy", ["legacy"]), ("legacy,other", ["legacy", "other"]),
    (" legacy , other ", ["legacy", "other"]), (["legacy", "other", "legacy"],
                                                ["legacy", "other"]),
])
def test_parse_asset_keys(value, keys):
    assert val.parse_asset_keys(value) == keys


@pytest.mark.parametrize("value", ["", " ", ",", " , ", "legacy,", [""], [None],
                                   ["legacy", " "], 5])
def test_forbid_keys_that_parse_to_nothing_are_refused(value):
    """`--forbid-asset "$UNSET"` or a stray comma would otherwise read as "forbid
    nothing", and the item still carrying a retired key would pass."""
    with pytest.raises(ValueError):
        val.parse_asset_keys(value)


def test_rules_are_reported_as_applied_not_as_passed(tmp_path):
    p = _write(tmp_path, _item("ok"))
    assert val.audit_items([p], NEW).rules == "no asset checks"
    assert val.audit_items([p], NEW, require_asset=KEEP,
                           forbid_assets="legacy,other").rules == (
        "require=data forbid=legacy,other")


@pytest.mark.parametrize("value", [None, "s3://x", {}, {"href": ""}, {"href": 5}])
def test_a_required_asset_must_be_an_object_with_an_href(tmp_path, value):
    doc = _item("x")
    doc["assets"] = {KEEP: value}
    r = val.audit_items([_write(tmp_path, doc)], NEW, require_asset=KEEP)
    assert not r.ok and r.missing_asset


@pytest.mark.parametrize("bad_id", [None, "", 5])
def test_an_item_without_a_string_id_is_not_audited_as_present(tmp_path, bad_id):
    doc = _item("x")
    if bad_id is None:
        del doc["id"]
    else:
        doc["id"] = bad_id
    r = val.audit_items([_write(tmp_path, doc, name="noid")], NEW, expect_ids={None})
    assert not r.ok and r.unreadable and r.checked == 0


def test_expect_count_fails_a_subset(tmp_path):
    paths = [_write(tmp_path, _item(f"x{i}")) for i in range(2)]
    assert not val.audit_items(paths, NEW, expect=3).ok
    assert val.audit_items(paths, NEW, expect=2).ok


def test_expect_ids_is_a_set_gate_a_count_cannot_fake(tmp_path):
    """Two items audited, two expected -- and the wrong two. A count passes; the set
    does not."""
    paths = [_write(tmp_path, _item(i)) for i in ("a", "b")]
    assert val.audit_items(paths, NEW, expect=2).ok
    r = val.audit_items(paths, NEW, expect_ids={"a", "c"})
    assert not r.ok
    assert any("1 missing, 1 unexpected" in f for f in r.failures)


def test_expect_ids_catches_a_repeated_item(tmp_path):
    p = _write(tmp_path, _item("a"))
    r = val.audit_items([p, p], NEW, expect_ids={"a"})
    assert not r.ok and any("1 repeated" in f for f in r.failures)


def test_item_paths_in_dir_excludes_the_collection(tmp_path):
    _write(tmp_path, _item("a"))
    _write(tmp_path, _item("b"))
    (tmp_path / "collection.json").write_text("{}")
    (tmp_path / "notes.txt").write_text("")
    got = val.item_paths_in_dir(tmp_path)
    assert [os.path.basename(p) for p in got] == ["a.json", "b.json"]


# =============================================================================
# validate_items -- pystac, offline
# =============================================================================

def test_validate_passes_a_valid_item_offline(tmp_path):
    """STAC 1.1.0 core schemas ship with pystac, so this needs no network -- and the
    suite-wide guard in conftest.py would fail any lookup if it tried."""
    p = _write(tmp_path, _item("ok"))
    assert val.validate_items([p]) == []


def test_validate_collects_every_failure_rather_than_stopping(tmp_path):
    bad1 = _item("bad1")
    del bad1["properties"]["datetime"]
    bad2 = _item("bad2")
    bad2["geometry"] = {"type": "Point", "coordinates": "nowhere"}
    paths = [_write(tmp_path, bad1), _write(tmp_path, _item("ok")),
             _write(tmp_path, bad2)]
    bad = val.validate_items(paths)
    assert [os.path.basename(p) for p, _ in bad] == ["bad1.json", "bad2.json"]


def test_a_schema_that_cannot_be_fetched_is_a_failure_not_a_pass(tmp_path):
    """An extension schema is fetched by URL. Unreachable, the item's validity was never
    established -- so it is reported, not passed."""
    doc = _item("ext")
    doc["stac_extensions"] = ["https://example.invalid/some-extension/v1.0.0/schema.json"]
    p = _write(tmp_path, doc)
    bad = val.validate_items([p])
    assert len(bad) == 1 and bad[0][0] == p
    assert "GetSchemaError" in bad[0][1]
    assert "network disabled in tests" in bad[0][1]   # the fetch, not something else


def test_validate_checks_the_body_as_written_not_pystacs_rewrite(tmp_path):
    """pystac.Item.from_dict rewrites a naive datetime before validating its copy; the
    body that would be registered is the one on disk."""
    doc = _item("naive")
    doc["properties"]["datetime"] = "2020-01-01T00:00:00"
    bad = val.validate_items([_write(tmp_path, doc)])
    assert len(bad) == 1 and "STACValidationError" in bad[0][1]


@pytest.mark.parametrize("paths", [[], ["", "\n"]])
def test_validate_over_nothing_raises(paths):
    """An empty list is this function's success value, so zero items cannot return it."""
    with pytest.raises(ValueError, match="no item JSONs"):
        val.validate_items(paths)


def test_validate_reports_an_unreadable_file(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{not json")
    assert len(val.validate_items([str(bad)])) == 1
