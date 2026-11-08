"""`stacs.receipt`'s own behaviour: the frozen canonical form, and what it refuses.

The vectors (`test_receipt_vectors.py`) prove agreement with crate. This file pins the things
the vectors cannot see: that the receipt canonical form is kept apart from `stacs.verify`'s,
that the frozen URLs say what they claim, and that a Python value with no place in the
contract is refused by name rather than hashed into something plausible.
"""

import copy
import datetime
import hashlib
import os
import stat
from pathlib import Path

import pytest

from stacs import receipt as r
from stacs import verify as v


# =============================================================================
# Two canonical forms, kept apart on purpose
# =============================================================================

def test_the_receipt_canonical_form_is_not_the_stac_body_digest_form():
    """THE separation. `verify.canonical_json` drops `links` and null members because pgstac
    does; a receipt's applies no STAC rules, because its bytes are published inside a
    `recipe_id` that nothing can migrate. If these two ever agreed on this body, one of them
    had been "simplified" into the other and every stored id would be wrong.
    """
    body = {"id": "a", "links": [{"rel": "self"}], "proj:epsg": None, "n": 1}
    assert v.canonical_json(body) == b'{"id":"a","n":1}'
    assert r.canonical(body) == \
        b'{"id":"a","links":[{"rel":"self"}],"n":1,"proj:epsg":null}'
    assert r.canonical(body) != v.canonical_json(body)


def test_the_receipt_form_keeps_a_null_member_the_stac_form_drops():
    """`seed: null` and no seed at all are two different recipes to read, and one of them is
    not even valid against the schema -- `seed` is required. Dropping it would make them one
    `recipe_id`."""
    assert r.canonical({"seed": None}) == b'{"seed":null}'
    assert r.recipe_id({"seed": None}) != r.recipe_id({})


def test_the_receipt_form_keeps_links():
    assert b"links" in r.canonical({"links": []})


def test_both_forms_still_write_a_number_as_jcs_does():
    """What the two DO share: JCS's number model. `-0.0` is `0` and `1.0` is `1` in both, so a
    divergence here would be a bug in one of them rather than the intended difference."""
    assert r.canonical({"a": -0.0, "b": 1.0}) == b'{"a":0,"b":1}'
    assert v.canonical_json({"a": -0.0, "b": 1.0}) == b'{"a":0,"b":1}'


# =============================================================================
# The frozen URLs and the version they claim
# =============================================================================

def test_each_frozen_url_carries_the_receipt_version_it_claims():
    """The URLs are written out in full, so nothing but a test stops them drifting from
    RECEIPT_VERSION -- and a receipt validated against one version while declaring another is
    the failure nobody would look for."""
    assert f"/v{r.RECEIPT_VERSION}/schema.json" in r.SCHEMA_URL
    assert f"/v{r.RECEIPT_VERSION}/schema.json" in r.EXTENSION_URL
    assert r.SCHEMA_URL != r.EXTENSION_URL
    assert "/stac/receipt/" in r.EXTENSION_URL


def test_the_vendored_schemas_are_the_ones_the_urls_name():
    """The package reads its schemas from disk because the suite is offline. Their `$id` is
    the URL the module writes into records, so a mismatch would validate against one schema
    and advertise another."""
    import json
    from pathlib import Path
    data = Path(r.__file__).parent / "data" / "receipt" / f"v{r.RECEIPT_VERSION}"
    assert json.loads((data / "schema.json").read_text(encoding="utf-8"))["$id"] == r.SCHEMA_URL
    assert json.loads(
        (data / "stac_schema.json").read_text(encoding="utf-8"))["$id"] == r.EXTENSION_URL


# =============================================================================
# What has no canonical form, and what has no place in the contract
# =============================================================================

@pytest.mark.parametrize("value,match", [
    ({"n": float("nan")}, "no canonical form at n"),
    ({"n": float("inf")}, "no canonical form at n"),
    ({"a": {"b": [1, float("-inf")]}}, r"no canonical form at a\.b\[1\]"),
    ({"n": 10**400}, "beyond a double"),
], ids=["nan", "inf", "nested -inf", "huge int"])
def test_a_value_with_no_canonical_form_raises_a_named_error_naming_where(value, match):
    with pytest.raises(r.ReceiptError, match=match):
        r.canonical(value)


@pytest.mark.parametrize("value", [
    {"d": datetime.date(2026, 11, 8)},
    {"t": datetime.datetime(2026, 11, 8, tzinfo=datetime.timezone.utc)},
    {"n": __import__("decimal").Decimal("1.5")},
    {"b": b"bytes"},
    {"s": {1, 2}},
], ids=["date", "datetime", "Decimal", "bytes", "set"])
def test_a_python_value_with_no_json_spelling_is_refused_by_name(value):
    """JSON has no date, no decimal and no set. crate refuses the R equivalents of each with
    its own named errors; this is the Python list, and the message names the member and the
    type rather than leaving `rfc8785` to report a type nobody passed deliberately."""
    with pytest.raises(r.ReceiptError, match="has no JSON spelling"):
        r.canonical(value)


def test_a_non_string_object_key_is_refused():
    with pytest.raises(r.ReceiptError, match="is not a string"):
        r.canonical({1: "a"})


def test_load_json_refuses_text_that_is_not_json():
    with pytest.raises(r.ReceiptError, match="not valid JSON"):
        r.load_json("{")
    with pytest.raises(r.ReceiptError, match="expected JSON text"):
        r.load_json({"already": "parsed"})


# =============================================================================
# recipe_id
# =============================================================================

EMPTY = {"code": {}, "config": {"files": {}, "settings": {}}, "inputs": {}, "seed": None}


def test_an_empty_recipe_hashes_crates_published_value():
    assert r.recipe_id(EMPTY) == \
        "ecb53cd4e03b09490f6c581b1195aa9635e5fff51790d64e19d2a2a79f8a0493"


def test_an_empty_keyed_collection_is_an_object_not_an_array():
    """The one R-ism baked into the contract: `{}`, never `[]`. A Python writer using `[]` for
    "no inputs" produces a different id and a schema failure, and the id still looks fine."""
    assert r.canonical(EMPTY) == \
        b'{"code":{},"config":{"files":{},"settings":{}},"inputs":{},"seed":null}'
    assert r.recipe_id({**EMPTY, "inputs": {}}) != r.recipe_id({**EMPTY, "inputs": {"x": {}}})


@pytest.mark.parametrize("path,recipe", [
    ("recipe.code", {**EMPTY, "code": [{"commit": "a" * 40}]}),
    ("recipe.inputs", {**EMPTY, "inputs": ["network"]}),
    ("recipe.config.files", {**EMPTY, "config": {"files": ["settings.csv"], "settings": {}}}),
    ("recipe.config.settings", {**EMPTY, "config": {"files": {}, "settings": [1, 2]}}),
])
def test_a_keyed_collection_written_as_a_list_is_refused(path, recipe):
    """A list canonicalises happily, in the order it was written, and yields a plausible wrong
    id -- two writers naming the same inputs in another order would disagree forever. This is
    the one shape that must not reach the hash."""
    with pytest.raises(r.ReceiptError, match=f"{path} must be an object keyed by name"):
        r.recipe_id(recipe)


def test_a_setting_may_still_be_an_array():
    """Order inside a setting's VALUE is significant and preserved; only the collections are
    keyed."""
    recipe = {**EMPTY, "config": {"files": {}, "settings": {"species": ["CO", "CH"]}}}
    assert r.recipe_id(recipe) != r.recipe_id(
        {**EMPTY, "config": {"files": {}, "settings": {"species": ["CH", "CO"]}}})


def test_a_recipe_that_is_not_an_object_is_refused():
    with pytest.raises(r.ReceiptError, match="a recipe is a JSON object"):
        r.recipe_id([1, 2])


# =============================================================================
# Table cells: the type rules a vector would only catch by accident
# =============================================================================

def _table(col_type, values, name="x"):
    return {"columns": {name: {"type": col_type, "values": values}}}


def test_a_logical_cell_is_true_or_false_and_never_one_or_zero():
    """`bool` is an `int` subclass in Python, so an integer branch reached first would write
    "1". The vectors carry logicals, but a reordering of the branches would still pass them if
    the logical branch were simply missing for a column typed `integer`."""
    assert r.table_canonical(_table("logical", [True, False])) == \
        b'{"columns":["x"],"rows":[["false"],["true"]]}'
    with pytest.raises(r.ReceiptError, match="a logical cell is True or False"):
        r.table_canonical(_table("logical", [1]))


def test_an_integer_cell_refuses_a_bool_and_a_fraction():
    with pytest.raises(r.ReceiptError, match="an integer cell is a whole number"):
        r.table_canonical(_table("integer", [True]))
    with pytest.raises(r.ReceiptError, match="is not whole"):
        r.table_canonical(_table("integer", [1.5]))


def test_a_double_rounded_to_zero_loses_its_sign():
    """printf keeps it ("-0.00"), and one zero must have one spelling or two tables that agree
    fingerprint differently."""
    assert r.table_canonical(_table("double", [-0.001, 0.001]), {"x": 1}) == \
        b'{"columns":["x"],"rows":[["0"],["0"]]}'


def test_a_double_cell_refuses_nan_and_infinity():
    for bad in (float("nan"), float("inf")):
        with pytest.raises(r.ReceiptError, match="no canonical form"):
            r.table_canonical(_table("double", [bad]))


def test_a_datetime_with_no_time_zone_is_refused_rather_than_guessed():
    """A naive datetime's zone is the machine's, so the same input would fingerprint
    differently on two hosts."""
    with pytest.raises(r.ReceiptError, match="no time zone is a guess"):
        r.table_canonical(_table("datetime", [datetime.datetime(2026, 11, 8, 12, 0, 0)]))


def test_a_datetime_is_converted_to_utc():
    east = datetime.timezone(datetime.timedelta(hours=2))
    got = r.table_canonical(_table("datetime", [datetime.datetime(2026, 11, 8, 12, 0, 0,
                                                                  tzinfo=east)]))
    assert got == b'{"columns":["x"],"rows":[["2026-11-08T10:00:00Z"]]}'


def test_fractional_seconds_are_refused():
    t = datetime.datetime(2026, 11, 8, 12, 0, 0, 500000, tzinfo=datetime.timezone.utc)
    with pytest.raises(r.ReceiptError, match="fractional seconds"):
        r.table_canonical(_table("datetime", [t]))


def test_a_date_cell_refuses_a_datetime():
    with pytest.raises(r.ReceiptError, match="a date cell is a date, not a datetime"):
        r.table_canonical(_table("date",
                                 [datetime.datetime(2026, 11, 8,
                                                    tzinfo=datetime.timezone.utc)]))


def test_a_year_outside_1_to_9999_is_refused():
    with pytest.raises(r.ReceiptError, match="outside 1-9999"):
        r.table_canonical(_table("date", ["12026-11-08"]))


def test_an_unknown_column_type_is_refused():
    with pytest.raises(r.ReceiptError, match="unknown column type"):
        r.table_canonical(_table("factor", ["a"]))


def test_ragged_columns_are_refused():
    """Pairing cell i of one column with nothing in another would fingerprint a table that
    does not exist."""
    table = {"columns": {"a": {"type": "integer", "values": [1, 2]},
                         "b": {"type": "integer", "values": [1]}}}
    with pytest.raises(r.ReceiptError, match="has 1 value"):
        r.table_canonical(table)


def test_a_tolerance_for_a_column_that_is_not_there_is_refused():
    """It rounds nothing while reading as though that column had been checked."""
    with pytest.raises(r.ReceiptError, match="does not have"):
        r.table_canonical(_table("double", [1.0]), {"km": 1e-9})


def test_a_tolerance_must_be_a_power_of_ten():
    for bad in (0.5, 0, -1e-9, 1e-16, True):
        with pytest.raises(r.ReceiptError):
            r.tolerance_decimals(bad)


def test_double_from_bits_refuses_anything_but_sixteen_hex_digits():
    for bad in ("3e7", "zzzzzzzzzzzzzzzz", 1.0, None):
        with pytest.raises(r.ReceiptError, match="16 hex digits"):
            r.double_from_bits(bad)


# =============================================================================
# The file on disk -- the one thing only crate's own receipts can pin
# =============================================================================

WORKED = (Path(__file__).resolve().parent / "vectors" / "receipt" / "examples"
          / "worked_case")


@pytest.mark.parametrize("build", ["build_1", "build_2"])
def test_a_receipt_read_and_rewritten_is_byte_identical_to_crates_own(build, tmp_path):
    """THE acceptance test for the file format, and the reason crate's worked-case receipts are
    vendored rather than a fixture built here: a fixture made by pretty-printing with Python
    would agree with whatever this module does.

    It pins three things at once. The indentation and the collapsed empty containers; the
    canonical *number spellings* (this file carries `"km_total": 0.000001` and `"km": 1e-9`,
    which `json.dumps` writes as `1e-06` and `1e-09`); and `recipe_id`, which `write`
    recomputes from the recipe -- so agreement here says this module's id matches crate's for a
    real receipt and not only for the vectors.
    """
    src = WORKED / build / "receipt.json"
    want = src.read_bytes()
    out = tmp_path / "receipt.json"
    digest = r.write(r.read(src), out)
    assert out.read_bytes() == want
    assert digest == hashlib.sha256(want).hexdigest()


def test_the_round_trip_survives_every_number_coming_back_as_a_float():
    """`load_json` reads every number as a double, so a receipt read back holds `3.0` where the
    file said `3`. The bytes are identical anyway, because JCS spells a whole float and an int
    alike -- which is why `write` has no whole-number coercion. If that ever stopped being
    true, the test above would fail and this one says why."""
    doc = r.read(WORKED / "build_1" / "receipt.json")
    rows = doc["result"]["fingerprint"]["access_check"]["rows"]
    assert isinstance(rows, float), "load_json should have made this a float"
    assert r.canonical({"n": rows}) == r.canonical({"n": int(rows)})


def test_the_digest_write_returns_is_the_digest_of_the_file(tmp_path):
    """It becomes the receipt asset's `file:checksum`, and nothing else can compute it."""
    out = tmp_path / "receipt.json"
    digest = r.write(r.read(WORKED / "build_1" / "receipt.json"), out)
    assert digest == hashlib.sha256(out.read_bytes()).hexdigest()


def test_write_leaves_no_temp_file_behind(tmp_path):
    r.write(r.read(WORKED / "build_1" / "receipt.json"), tmp_path / "receipt.json")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["receipt.json"]


def test_a_new_receipt_is_not_left_at_mode_0600(tmp_path):
    """`mkstemp` creates 0600 and `os.replace` carries the mode onto the target, so a receipt
    published beside its item would be unreadable to everyone else."""
    out = tmp_path / "receipt.json"
    r.write(r.read(WORKED / "build_1" / "receipt.json"), out)
    umask = os.umask(0)
    os.umask(umask)
    assert stat.S_IMODE(out.stat().st_mode) == 0o666 & ~umask


def test_overwriting_keeps_the_targets_own_mode(tmp_path):
    out = tmp_path / "receipt.json"
    out.write_text("{}")
    out.chmod(0o640)
    r.write(r.read(WORKED / "build_1" / "receipt.json"), out)
    assert stat.S_IMODE(out.stat().st_mode) == 0o640


def test_write_does_not_modify_the_callers_receipt(tmp_path):
    doc = r.read(WORKED / "build_1" / "receipt.json")
    doc["recipe"]["recipe_id"] = "0" * 64
    before = copy.deepcopy(doc)
    r.write(doc, tmp_path / "receipt.json")
    assert doc == before


# =============================================================================
# write computes the identity, and publishes without the host
# =============================================================================

def test_write_recomputes_recipe_id_over_a_wrong_one(tmp_path):
    """A builder that carried a stale id would publish an item whose provenance points at a
    recipe it was not made by, and nothing downstream recomputes it."""
    doc = r.read(WORKED / "build_1" / "receipt.json")
    right = doc["recipe"]["recipe_id"]
    doc["recipe"]["recipe_id"] = "0" * 64
    out = tmp_path / "receipt.json"
    r.write(doc, out)
    assert r.read(out)["recipe"]["recipe_id"] == right


def test_publishing_drops_the_host_rather_than_nulling_it(tmp_path):
    doc = r.read(WORKED / "build_1" / "receipt.json")
    doc["context"]["host"] = "a-build-machine"
    out = tmp_path / "receipt.json"
    r.write(doc, out)
    assert "host" not in r.read(out)["context"]
    r.write(doc, out, publish=False)
    assert r.read(out)["context"]["host"] == "a-build-machine"


def test_a_migrated_receipt_is_written_with_a_null_recipe_id(tmp_path):
    """`migrated_from` is what switches the schema branch, and a migrated recipe holds no
    identity: computing one would invent provenance for a record that never had it."""
    doc = r.read(WORKED / "build_1" / "receipt.json")
    doc["output"]["migrated_from"] = "manifest.json"
    doc["recipe"] = {"code": {"link": {"commit": "a9b8c7d"}}, "recipe_id": None}
    out = tmp_path / "receipt.json"
    r.write(doc, out)
    written = r.read(out)
    assert written["recipe"]["recipe_id"] is None
    assert written["output"]["migrated_from"] == "manifest.json"


# =============================================================================
# read and validate
# =============================================================================

def test_read_refuses_another_receipt_version(tmp_path):
    """Refused, not warned about: a later version may spell a field the same way and mean
    something else, and a comparison across versions would report agreeing fields as
    differing."""
    doc = r.read(WORKED / "build_1" / "receipt.json")
    doc["output"]["receipt_version"] = "2.0.0"
    out = tmp_path / "receipt.json"
    out.write_text(r.reindent(r.canonical(doc)) + "\n")
    with pytest.raises(r.ReceiptError, match="is receipt version '2.0.0'"):
        r.read(out)


@pytest.mark.parametrize("break_it,match", [
    (lambda d: d["output"].pop("scope"), "output"),
    (lambda d: d["recipe"].update(recipe_id="nothex"), "recipe"),
    (lambda d: d["output"].update(extra=1), "output"),
    (lambda d: d["result"].pop("tolerance"), "result"),
    (lambda d: d["context"].update(time="2026-11-04 18:22:05"), "context"),
], ids=["required member gone", "bad sha", "unknown member", "block member gone", "bad time"])
def test_validate_refuses_a_receipt_the_schema_does_not_accept(break_it, match):
    doc = r.read(WORKED / "build_1" / "receipt.json")
    break_it(doc)
    with pytest.raises(r.ReceiptError, match="not a valid receipt"):
        r.validate(doc)
    try:
        r.validate(doc)
    except r.ReceiptError as e:
        assert match in str(e), str(e)


def test_validate_accepts_both_of_crates_worked_receipts():
    """A validator that refused everything would pass every test above."""
    for build in ("build_1", "build_2"):
        r.validate(r.read(WORKED / build / "receipt.json"))


def test_write_validates_before_it_writes_anything(tmp_path):
    out = tmp_path / "receipt.json"
    doc = r.read(WORKED / "build_1" / "receipt.json")
    doc["result"].pop("parts")
    with pytest.raises(r.ReceiptError, match="not a valid receipt"):
        r.write(doc, out)
    assert not out.exists(), "a refused receipt must leave no file"


def test_read_names_the_file_it_could_not_read(tmp_path):
    with pytest.raises(r.ReceiptError, match="cannot read"):
        r.read(tmp_path / "nope.json")


# =============================================================================
# reindent
# =============================================================================

@pytest.mark.parametrize("data,want", [
    (b"{}", "{}"),
    (b"[]", "[]"),
    (b'{"a":{}}', '{\n  "a": {}\n}'),
    (b'{"a":[]}', '{\n  "a": []\n}'),
    # A brace, a bracket, a comma and a colon inside a string must not be re-indented, and an
    # escaped quote must not end the string.
    (b'{"a":"{[,:}"}', '{\n  "a": "{[,:}"\n}'),
    (b'{"a":"say \\"x\\", then"}', '{\n  "a": "say \\"x\\", then"\n}'),
    (b'{"a":"ends with a backslash \\\\"}', '{\n  "a": "ends with a backslash \\\\"\n}'),
])
def test_reindent_leaves_string_contents_alone(data, want):
    assert r.reindent(data) == want


def test_reindent_is_the_same_document():
    """A re-indenter that changed a value would be caught by the byte-identical test only for
    the documents crate ships."""
    doc = r.read(WORKED / "build_1" / "receipt.json")
    assert r.load_json(r.reindent(r.canonical(doc))) == doc


def test_reindent_round_trips_a_nested_document():
    doc = {"a": {"b": [1, [2, {"c": None}], {}], "d": "x"}, "e": []}
    assert r.load_json(r.reindent(r.canonical(doc))) == doc


# =============================================================================
# The STAC side, against crate's own example item
# =============================================================================

EXAMPLE = Path(__file__).resolve().parent / "vectors" / "receipt" / "examples" / "item.json"


def test_crates_example_item_has_nothing_wrong_with_it():
    """The oracle for `item_problems`. A checker that refused everything would pass every
    negative test below, and this is the only item in existence written by the other
    implementation of this contract."""
    assert r.item_problems(r.load_json(EXAMPLE.read_text(encoding="utf-8"))) == []


def test_the_example_items_receipt_asset_is_the_one_found():
    item = r.load_json(EXAMPLE.read_text(encoding="utf-8"))
    assert r.receipt_href(item) == "receipt.json"


def test_stac_fields_produces_the_property_names_and_extensions_the_example_carries():
    """Shapes, not values: the example illustrates a floodplains build whose receipt crate does
    not ship, so it pins the field names, the extension list and the multihash form."""
    item = r.load_json(EXAMPLE.read_text(encoding="utf-8"))
    receipt = {
        "output": {}, "context": {"time": item["properties"]["processing:datetime"]},
        "recipe": {"recipe_id": item["properties"]["receipt:recipe_id"],
                   "code": {"flooded": {"version": "0.7.0"}}},
        "result": {"parts": {"floodplain_all_ff02.tif": {
            "sha256": item["assets"]["floodplain"]["file:checksum"][4:],
            "bytes": item["assets"]["floodplain"]["file:size"]}}},
    }
    fields = r.stac_fields(receipt, assets={"floodplain": "floodplain_all_ff02.tif"},
                           receipt_asset="receipt",
                           receipt_sha256=item["assets"]["receipt"]["file:checksum"][4:])
    # Minus `datetime`, which is core STAC and the item's own: a receipt says when the build
    # ran (`processing:datetime`), never what the item is about.
    assert fields["properties"] == {k: v for k, v in item["properties"].items()
                                    if k != "datetime"}
    assert fields["stac_extensions"] == item["stac_extensions"]
    assert fields["assets"]["floodplain"] == {
        "file:checksum": item["assets"]["floodplain"]["file:checksum"],
        "file:size": item["assets"]["floodplain"]["file:size"]}
    assert fields["assets"]["receipt"]["file:checksum"] == \
        item["assets"]["receipt"]["file:checksum"]


def test_stac_fields_lists_all_three_extensions_not_just_the_receipt_one():
    """An item emitting `file:*` or `processing:*` without their URLs is non-conformant, and
    the receipt field schema cannot notice: it constrains only `receipt:`-prefixed keys."""
    receipt = {"output": {}, "context": {"time": "2026-11-08T00:00:00Z"},
               "recipe": {"recipe_id": "a" * 64, "code": {"stacs": {"version": "0.2.0"}}},
               "result": {"parts": {"x.tif": {"sha256": "b" * 64, "bytes": 1}}}}
    assert r.stac_fields(receipt, assets={"data": "x.tif"})["stac_extensions"] == [
        r.FILE_EXTENSION_URL, r.PROCESSING_EXTENSION_URL, r.EXTENSION_URL]


def test_a_migrated_receipt_leaves_the_field_out_rather_than_publishing_a_null():
    """The schema types it `string`, so a null would be refused -- and a null recipe_id in a
    queryable reads as "made this way" for every migrated item at once."""
    receipt = {"output": {"migrated_from": "manifest.json"},
               "recipe": {"recipe_id": None}, "result": {}, "context": {}}
    fields = r.stac_fields(receipt)
    assert "receipt:recipe_id" not in fields["properties"]
    assert r.EXTENSION_URL not in fields["stac_extensions"]


def test_stac_fields_refuses_an_asset_href_that_is_not_a_part():
    """Guessing would publish another file's digest under this asset."""
    receipt = {"output": {}, "recipe": {}, "context": {},
               "result": {"parts": {"x.tif": {"sha256": "b" * 64, "bytes": 1}}}}
    with pytest.raises(r.ReceiptError, match="not a part of this receipt"):
        r.stac_fields(receipt, assets={"data": "y.tif"})


def test_stac_fields_needs_the_digest_for_the_receipt_asset():
    receipt = {"output": {}, "recipe": {}, "result": {}, "context": {}}
    with pytest.raises(r.ReceiptError, match="needs receipt_sha256"):
        r.stac_fields(receipt, receipt_asset="receipt")


def test_the_receipt_asset_checksum_is_the_digest_write_returned(tmp_path):
    """The round trip that makes an item self-verifying: the digest `write` returns becomes the
    asset's `file:checksum`, and a reader can hash the receipt it fetched and compare."""
    out = tmp_path / "receipt.json"
    digest = r.write(r.read(WORKED / "build_1" / "receipt.json"), out)
    fields = r.stac_fields(r.read(out), receipt_asset="receipt", receipt_sha256=digest)
    assert fields["assets"]["receipt"]["file:checksum"] == r.multihash(
        hashlib.sha256(out.read_bytes()).hexdigest())


def test_multihash_refuses_anything_but_a_sha256():
    for bad in ("1220" + "a" * 64, "A" * 64, "abc", None, 1):
        with pytest.raises(r.ReceiptError, match="64 lowercase hex"):
            r.multihash(bad)


def _example_item(**changes):
    item = r.load_json(EXAMPLE.read_text(encoding="utf-8"))
    for path, value in changes.items():
        where, _, key = path.rpartition(".")
        node = item
        for part in where.split(".") if where else []:
            node = node[part]
        if value is None:
            node.pop(key, None)
        else:
            node[key] = value
    return item


@pytest.mark.parametrize("changes,match", [
    ({"properties.receipt:recipe_id": None}, "no receipt:recipe_id"),
    ({"properties.receipt:recipe_id": "A" * 64}, "not 64 lowercase hex"),
    ({"properties.receipt:recipe_id": "abc"}, "not 64 lowercase hex"),
    ({"stac_extensions": ["https://stac-extensions.github.io/file/v2.1.0/schema.json"]},
     "processing"),
    # The field schema allows exactly one `receipt:` key, via
    # `patternProperties: {"^(?!receipt:)": {}}` plus `additionalProperties: false`.
    ({"properties.receipt:other": "x"}, "'receipt:other' does not match"),
    ({"properties.processing:datetime": "2026-10-14 12:42:04"}, "ISO 8601"),
    ({"assets.floodplain.file:checksum": "deadbeef"}, "multihash"),
    ({"assets.receipt.roles": ["data"]}, "no asset links the receipt"),
    ({"assets.receipt.type": "text/plain"}, "no asset links the receipt"),
    ({"assets.floodplain.file:size": 1.5}, "not whole"),
], ids=["no id", "uppercase id", "short id", "extension missing", "rogue receipt key",
        "bad datetime", "bad multihash", "wrong role", "wrong type", "fractional size"])
def test_item_problems_catches_each_way_an_item_can_be_wrong(changes, match):
    problems = r.item_problems(_example_item(**changes))
    assert problems, changes
    assert any(match in p for p in problems), problems


def test_item_problems_refuses_something_that_is_not_an_item():
    assert r.item_problems("not an item")
    assert r.item_problems(None)


def test_receipt_href_is_none_when_nothing_links_a_receipt():
    assert r.receipt_href({"assets": {}}) is None
    assert r.receipt_href({}) is None
    assert r.receipt_href({"assets": {"x": {"roles": ["metadata"]}}}) is None
