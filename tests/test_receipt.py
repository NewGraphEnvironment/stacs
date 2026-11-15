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

# What the mapping requires of every receipt before it reads anything else: the form it was
# written to, and when it was built. Functions, so no test can change another's fixture.
WHEN = "2026-11-08T00:00:00Z"


def _form(**more):
    return {"receipt_version": r.RECEIPT_VERSION, **more}


def _when():
    return {"time": WHEN}


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
        "output": _form(), "context": {"time": item["properties"]["processing:datetime"]},
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
    receipt = {"output": _form(), "context": _when(),
               "recipe": {"recipe_id": "a" * 64, "code": {"stacs": {"version": "0.2.0"}}},
               "result": {"parts": {"x.tif": {"sha256": "b" * 64, "bytes": 1}}}}
    assert r.stac_fields(receipt, assets={"data": "x.tif"})["stac_extensions"] == [
        r.FILE_EXTENSION_URL, r.PROCESSING_EXTENSION_URL, r.EXTENSION_URL]


def test_a_migrated_receipt_leaves_the_field_out_rather_than_publishing_a_null():
    """The schema types it `string`, so a null would be refused -- and a null recipe_id in a
    queryable reads as "made this way" for every migrated item at once."""
    receipt = {"output": _form(migrated_from="manifest.json"),
               "recipe": {"recipe_id": None}, "result": {}, "context": _when()}
    fields = r.stac_fields(receipt)
    assert "receipt:recipe_id" not in fields["properties"]
    assert fields["stac_extensions"] == [r.PROCESSING_EXTENSION_URL]


@pytest.mark.parametrize("output,recipe,code", [
    (_form(), {"recipe_id": None}, "recipe_id_missing"),
    (_form(), {}, "recipe_id_missing"),
    (_form(migrated_from="manifest.json"), {"recipe_id": "a" * 64}, "recipe_id_on_migrated"),
], ids=["null, not migrated", "absent, not migrated", "set, migrated"])
def test_only_a_migrated_receipt_may_have_no_recipe_identity(output, recipe, code):
    """The other half of the rule above. A null `recipe_id` used to be left out whatever the
    receipt was, so a receipt that had simply lost its identity produced an item that read as
    migrated -- and one set on a migrated receipt was published as though it were vouched for."""
    with pytest.raises(r.ReceiptError) as e:
        r.stac_fields({"output": output, "recipe": recipe, "result": {}, "context": _when()})
    assert e.value.code == code


def test_stac_fields_refuses_an_asset_href_that_is_not_a_part():
    """Guessing would publish another file's digest under this asset."""
    receipt = {"output": _form(), "recipe": {"recipe_id": "a" * 64}, "context": _when(),
               "result": {"parts": {"x.tif": {"sha256": "b" * 64, "bytes": 1}}}}
    with pytest.raises(r.ReceiptError, match="not a part of this receipt") as e:
        r.stac_fields(receipt, assets={"data": "y.tif"})
    assert e.value.code == "href_not_a_part"


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
    # The last two are what `^[0-9a-f]{64}$` under `re.match` let through: `$` also matches
    # before a trailing newline, and the digest was then published with the newline in it.
    for bad in ("1220" + "a" * 64, "A" * 64, "abc", None, 1, "a" * 64 + "\n", "\n" + "a" * 64):
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
    # What the patterns used to admit: a trailing newline (`$` under `re.match`), any Unicode
    # digit (`\d`), and an instant that does not exist, which the pattern alone cannot see.
    ({"properties.receipt:recipe_id": "a" * 64 + "\n"}, "not 64 lowercase hex"),
    ({"properties.processing:datetime": "2026-10-14T12:42:04Z\n"}, "ISO 8601"),
    ({"properties.processing:datetime": "٢٠٢٦-10-14T12:42:04Z"}, "ISO 8601"),
    ({"properties.processing:datetime": "2026-13-14T12:42:04Z"}, "ISO 8601"),
    ({"properties.processing:datetime": "2026-02-29T12:42:04Z"}, "ISO 8601"),
    ({"properties.processing:datetime": "2026-10-14T24:00:00Z"}, "ISO 8601"),
    ({"assets.floodplain.file:checksum": "1220" + "a" * 64 + "\n"}, "multihash"),
    ({"assets.floodplain.file:size": -1}, "negative"),
], ids=["no id", "uppercase id", "short id", "extension missing", "rogue receipt key",
        "bad datetime", "bad multihash", "wrong role", "wrong type", "fractional size",
        "id with a trailing newline", "datetime with a trailing newline",
        "datetime in other digits", "month 13", "29 February in a common year", "hour 24",
        "multihash with a trailing newline", "negative size"])
def test_item_problems_catches_each_way_an_item_can_be_wrong(changes, match):
    problems = r.item_problems(_example_item(**changes))
    assert problems, changes
    assert any(match in p for p in problems), problems


@pytest.mark.parametrize("time", ["2024-02-29T23:59:59Z", "2026-10-14T12:42:04.5Z",
                                  "2026-12-31T00:00:00Z"])
def test_item_problems_accepts_an_instant_that_exists(time):
    """The other direction of the cases above: a check that refused every datetime would pass
    all of them."""
    assert r.item_problems(_example_item(**{"properties.processing:datetime": time})) == []


@pytest.mark.parametrize("change,code", [
    ({"context": {}}, "time_not_utc"),
    ({"context": {"time": "2026-13-01T00:00:00Z"}}, "time_not_utc"),
    ({"output": {}}, "receipt_version_unknown"),
    ({"output": None}, "block_not_object"),
    ({"output": "1.0.0"}, "block_not_object"),
    ({"recipe": {"recipe_id": None}}, "recipe_id_missing"),
    ({"recipe": None}, "block_not_object"),
    ({"result": None}, "block_not_object"),
    ({"context": None}, "block_not_object"),
    ({"result": {"parts": None}}, "block_not_object"),
    ({"recipe": {"recipe_id": "a" * 64, "code": None}}, "block_not_object"),
    ({"recipe": {"recipe_id": "a" * 64, "code": {"stacs": "0.3.0"}}}, "block_not_object"),
], ids=["no time", "month 13", "no form version", "null output", "output a string",
        "no recipe identity", "null recipe", "null result", "null context", "null parts",
        "null code", "a code entry that is a string"])
def test_a_receipt_the_mapping_refuses_is_inconsistent_never_same(change, code):
    """`item_verdict` compares an item with what its receipt maps to, so a receipt the mapping
    refuses has nothing to be compared with: `inconsistent`, with the mapping's code in the
    note, and never `same`, which would be agreement with a receipt nobody could map.

    `null` is the case that needed this. The node check ahead of the mapping reads an absent
    node and a null one alike, so a `recipe` that was a string returned `inconsistent` while
    one that was null raised: two routes for one fact. `output` and `recipe.code` are not
    nodes that check names at all.
    """
    item = {"properties": {"receipt:recipe_id": "a" * 64}}
    good = {"output": _form(), "recipe": {"recipe_id": "a" * 64}, "result": {},
            "context": _when()}
    assert r.item_verdict(item, item, good).verdict == "same", "control"
    got = r.item_verdict(item, item, {**good, **change})
    assert got.verdict == "inconsistent" and not got.ok, got
    assert any(f"({code})" in note for note in got.notes), got.notes


@pytest.mark.parametrize("part,asset_fields,code", [
    (None, {"file:checksum": "1220" + "f" * 64}, "block_not_object"),
    ("x", {"file:checksum": "1220" + "f" * 64}, "block_not_object"),
    ([], {}, "block_not_object"),
    (7, {}, "block_not_object"),
    # A part the mapping refuses, behind an asset that does not carry the field that would
    # have shown it: the walk that used to live in `item_verdict` consulted a part only
    # through the fields the item happened to publish.
    ({"sha256": "b" * 64 + "\n", "bytes": 12}, {"file:size": 12}, "part_sha256_not_sha256"),
    ({"sha256": "b" * 64, "bytes": -5}, {"file:checksum": "1220" + "b" * 64},
     "bytes_not_whole"),
    ({"sha256": "b" * 64, "bytes": 1.5}, {}, "bytes_not_whole"),
    ({}, {}, "part_sha256_not_sha256"),
], ids=["null part", "string part", "list part, no file fields", "number part, no file fields",
        "digest with a newline, size only", "negative bytes, checksum only",
        "fractional bytes, no file fields", "empty part, no file fields"])
def test_a_part_the_mapping_refuses_is_never_same(part, asset_fields, code):
    """An asset of the item names a part of the receipt, so the mapping has to be able to map
    that part, whichever of `file:checksum` and `file:size` the item carries -- none
    included. `item_verdict` asks `stac_fields` for exactly the assets that name a part, so
    there is one reading of the asset rows and not a second copy that agrees with it only
    where someone remembered to keep it in step."""
    rec = {"output": _form(), "recipe": {"recipe_id": "a" * 64}, "context": _when(),
           "result": {"parts": {"x.tif": part}}}
    item = {"properties": {"receipt:recipe_id": "a" * 64},
            "assets": {"data": {"href": "x.tif", **asset_fields},
                       "thumb": {"href": "t.png", "file:checksum": r.multihash("e" * 64)}}}
    got = r.item_verdict(item, item, rec)
    assert got.verdict == "inconsistent" and not got.ok, got
    assert any(f"({code})" in note and "x.tif" in note for note in got.notes), got.notes


def test_an_asset_that_carries_neither_file_field_still_agrees_with_a_good_part():
    """The other direction of the test above: asking the mapping about every asset that names
    a part must not turn an item that publishes no file fields into a disagreement."""
    rec = {"output": _form(), "recipe": {"recipe_id": "a" * 64}, "context": _when(),
           "result": {"parts": {"x.tif": {"sha256": "b" * 64, "bytes": 12}}}}
    item = {"properties": {"receipt:recipe_id": "a" * 64},
            "assets": {"data": {"href": "x.tif"}, "also": {"href": "x.tif", "file:size": 12.0}}}
    assert r.item_verdict(item, item, rec).verdict == "same"


def test_the_register_is_read_and_named_by_its_own_version_not_the_forms(monkeypatch):
    """`REGISTER_VERSION` and `RECEIPT_VERSION` are both `1.0.0` today, so code that used the
    wrong one is the same program and no vector can tell. Moved apart here: `register()` must
    look for the register's directory, and a comparison must name the register's version."""
    monkeypatch.setattr(r, "_DATA", {})
    monkeypatch.setattr(r, "REGISTER_VERSION", "9.9.9")
    with pytest.raises(r.ReceiptError, match=r"register/v9\.9\.9/register\.csv"):
        r.register()
    monkeypatch.setattr(r, "_DATA", {"register": {"context.time": "record"}})
    one = {"output": {}, "recipe": {}, "result": {}, "context": {}}
    assert r.compare(one, one).register == "9.9.9"
    assert r.RECEIPT_VERSION == "1.0.0"


@pytest.mark.parametrize("time,real", [
    ("2024-02-29T00:00:00Z", True), ("2026-02-29T00:00:00Z", False),
    # The century rule, and a year the form's pattern admits that `datetime` does not have.
    ("2000-02-29T00:00:00Z", True), ("1900-02-29T00:00:00Z", False),
    ("0000-02-29T00:00:00Z", True),
    ("2026-04-30T00:00:00Z", True), ("2026-04-31T00:00:00Z", False),
    ("2026-00-10T00:00:00Z", False), ("2026-01-00T00:00:00Z", False),
    ("2026-01-01T23:59:59Z", True), ("2026-01-01T23:59:60Z", False),
    ("2026-01-01T23:60:00Z", False),
])
def test_an_instant_is_real_by_the_calendar_not_by_its_shape(time, real):
    """The mapping's vectors hold two years and two month lengths, so the rest of the calendar
    is pinned here: computed by arithmetic as crate computes it, since a date library would
    refuse year 0000, which the form's pattern and crate both accept."""
    assert r._utc_instant(time) is real


def test_a_receipt_is_migrated_by_the_presence_of_the_key_not_its_value():
    """As the form schema's `if` decides it, and as `write` does. Every vector that is
    migrated holds a string there, so reading the VALUE would pass all of them and still call
    `migrated_from: null` a receipt that lost its identity."""
    receipt = {"output": _form(migrated_from=None), "recipe": {"recipe_id": None},
               "result": {}, "context": _when()}
    assert "receipt:recipe_id" not in r.stac_fields(receipt)["properties"]
    with pytest.raises(r.ReceiptError) as e:
        r.stac_fields({**receipt, "recipe": {"recipe_id": "a" * 64}})
    assert e.value.code == "recipe_id_on_migrated"


def test_item_problems_refuses_something_that_is_not_an_item():
    assert r.item_problems("not an item")
    assert r.item_problems(None)


def test_receipt_href_is_none_when_nothing_links_a_receipt():
    assert r.receipt_href({"assets": {}}) is None
    assert r.receipt_href({}) is None
    assert r.receipt_href({"assets": {"x": {"roles": ["metadata"]}}}) is None


# =============================================================================
# Regressions from the branch review (round 1)
# =============================================================================

def test_a_second_metadata_json_asset_does_not_make_an_item_inconsistent():
    """Round 1. `item_verdict` chose "the item's receipt asset" with its own loop, which kept
    the LAST match, while the receipt actually fetched came from `receipt_href`, which returns
    the FIRST. Two producers for one fact, so it fired on good input: an item carrying a QA
    report or a legacy manifest as a second `metadata`/`application/json` asset was reported
    `inconsistent`, and `verify` turned that into a non-zero status."""
    rec = {"output": _form(), "recipe": {"recipe_id": "a" * 64}, "result": {},
           "context": _when()}
    item = {"properties": {"receipt:recipe_id": "a" * 64},
            "assets": {"receipt": {"href": "a0_receipt.json", "type": "application/json",
                                   "roles": ["metadata"],
                                   "file:checksum": r.multihash("b" * 64)},
                       "qa": {"href": "qa.json", "type": "application/json",
                              "roles": ["metadata"],
                              "file:checksum": r.multihash("c" * 64)}}}
    assert r.receipt_href(item) == "a0_receipt.json"
    assert r.receipt_asset(item)["href"] == "a0_receipt.json"
    assert r.item_verdict(item, item, rec, receipt_sha256="b" * 64).verdict == "same"


def test_one_producer_decides_which_asset_links_the_receipt():
    """The fix is structural: everything that needs that answer calls one function. An asset
    `receipt_asset` rejects must not be reachable by any other route."""
    no_href = {"assets": {"receipt": {"href": "", "type": "application/json",
                                      "roles": ["metadata"]}}}
    assert r.receipt_asset(no_href) is None
    assert r.receipt_href(no_href) is None
    assert any("no asset links the receipt" in p for p in r.item_problems(no_href))


@pytest.mark.parametrize("recipe,where", [
    ({**EMPTY, "config": ["settings.csv", "other.csv"]}, "recipe.config"),
    ({**EMPTY, "config": {"files": ["a.csv"], "settings": {}}}, "recipe.config.files"),
    ({**EMPTY, "config": "settings.csv"}, "recipe.config"),
])
def test_a_keyed_collection_is_refused_at_every_depth(recipe, where):
    """Round 1. An intermediate node that was not an object skipped the checks under it --
    `for ... else` does not run after a `break` -- so `recipe.config` as a list disabled both
    the `config.files` and `config.settings` checks and the list was hashed in written order,
    which is the exact failure the guard exists to prevent."""
    with pytest.raises(r.ReceiptError, match=f"{where} must be an object keyed by name"):
        r.recipe_id(recipe)


def test_the_order_a_list_was_written_in_can_no_longer_reach_the_hash():
    """The consequence, measured: two orders of the same intent used to give two ids."""
    for one, two in (({**EMPTY, "config": ["a", "b"]}, {**EMPTY, "config": ["b", "a"]}),):
        for recipe in (one, two):
            with pytest.raises(r.ReceiptError):
                r.recipe_id(recipe)


def test_an_absent_recipe_member_is_still_allowed():
    """A migrated recipe has every member optional, so whether one may be missing is the
    schema's question. The depth fix must not have turned absence into a refusal."""
    assert r.recipe_id({"code": {}, "inputs": {}, "seed": None})
    assert r.recipe_id({})


def test_an_items_asset_fields_are_checked_against_the_receipts_parts():
    """Round 1. `item_verdict` called `stac_fields(receipt)` with no `assets=`, so the claimed
    asset fields were always `{}` and `file:checksum` / `file:size` were never compared with
    `result.parts` -- two of the five mirrored fields. An item contradicting its own receipt
    in both, on BOTH sides, read `same` with `ok` true, and `same` sets no exit status."""
    rec = {"output": _form(), "recipe": {"recipe_id": "a" * 64}, "context": _when(),
           "result": {"parts": {"x.tif": {"sha256": "b" * 64, "bytes": 12}}}}
    good = {"properties": {"receipt:recipe_id": "a" * 64},
            "assets": {"data": {"href": "x.tif", "file:checksum": r.multihash("b" * 64),
                                "file:size": 12}}}
    assert r.item_verdict(good, good, rec).verdict == "same"

    for field, broken in (
            ("assets[data].file:checksum",
             {"href": "x.tif", "file:checksum": r.multihash("f" * 64), "file:size": 12}),
            ("assets[data].file:size",
             {"href": "x.tif", "file:checksum": r.multihash("b" * 64), "file:size": 999})):
        item = {"properties": {"receipt:recipe_id": "a" * 64}, "assets": {"data": broken}}
        got = r.item_verdict(item, item, rec)
        assert got.verdict == "inconsistent", field
        assert not got.ok
        assert field in got.fields, (field, got.fields)


def test_an_asset_the_receipt_does_not_describe_is_not_a_disagreement():
    """An overview, a thumbnail, or the receipt itself: not a part, so there is nothing to
    compare it with. Refusing them would make every real item inconsistent."""
    rec = {"output": _form(), "recipe": {"recipe_id": "a" * 64}, "context": _when(),
           "result": {"parts": {"x.tif": {"sha256": "b" * 64, "bytes": 12}}}}
    item = {"properties": {"receipt:recipe_id": "a" * 64},
            "assets": {"data": {"href": "x.tif", "file:checksum": r.multihash("b" * 64)},
                       "thumb": {"href": "t.png", "file:checksum": r.multihash("e" * 64),
                                 "file:size": 5}}}
    assert r.item_verdict(item, item, rec).verdict == "same"


@pytest.mark.parametrize("block", ["output", "recipe", "result", "context"])
def test_a_block_that_is_a_scalar_on_both_sides_is_still_compared(block):
    """Round 1. `_diff`'s branch arm iterated the union of both sides' keys, which is empty
    when NEITHER side is an object -- so a difference at any branch node that was a scalar on
    both sides was dropped, and the function whose job is to refuse answered `identical`."""
    base = {"output": {}, "recipe": {}, "result": {}, "context": {}}
    one, two = {**base, block: "x"}, {**base, block: "y"}
    got = r.compare(one, two)
    assert got.verdict == "different", got
    assert (block, "refuse") in got.fields, got.fields


def test_a_nested_branch_that_is_a_scalar_on_both_sides_is_still_compared():
    base = {"output": {}, "recipe": {}, "result": {}, "context": {}}
    got = r.compare({**base, "recipe": {"config": "x"}},
                    {**base, "recipe": {"config": "y"}})
    assert got.verdict == "different"
    assert ("recipe.config", "refuse") in got.fields, got.fields


def test_two_equal_scalars_at_a_branch_node_are_not_a_difference():
    """The other direction: the fix must not invent a difference where there is none."""
    base = {"output": "x", "recipe": {}, "result": {}, "context": {}}
    assert r.compare(base, dict(base)).verdict == "identical"
    empty = {"output": {}, "recipe": {}, "result": {}, "context": {}}
    assert r.compare(empty, dict(empty)).differences == ()


def test_a_tolerance_that_is_not_a_number_does_not_leak_a_typeerror():
    """Round 1. `read` validates nothing, so a hand-edited receipt reaches `compare`; the
    tolerance was used in `abs(va - vb) <= tol` without a type check, and a string raised a
    TypeError out of an API that reports everything else malformed as a ReceiptError."""
    def doc(km, tol):
        return {"output": {}, "recipe": {}, "context": {},
                "result": {"summary": {"km": km}, "tolerance": {"summary": {"km": tol}}}}
    for tol in ("1e-9", None, True, [1e-9]):
        got = r.compare(doc(1.0, tol), doc(2.0, tol))
        assert got.verdict == "different", tol


@pytest.mark.parametrize("block", ["output", "recipe", "result", "context"])
@pytest.mark.parametrize("value", ["a string", [1, 2], 7, None])
def test_compare_reports_a_malformed_block_as_a_difference(block, value):
    """`compare`'s post-processing read every block with `doc.get(x) or {}`, which keeps a
    truthy non-mapping, so a scalar `recipe` raised AttributeError out of the one function
    whose job is to refuse malformed input. `read` checks only the version, so such a receipt
    reaches here.

    The assertion is the VERDICT, not "did not raise". It was
    `in ITEM_VERDICTS or in ("identical", "equivalent", "different")`, which is true for
    every value `compare` can return -- a test that could not fail, and it was green against
    the wrong `identical` verdicts of the collection-arm defect (round 2b).
    """
    base = {"output": {}, "recipe": {}, "result": {}, "context": {}}
    got = r.compare({**base, block: value}, base)
    assert got.verdict == "different", (block, value, got)
    assert got.fields, (block, value, got)


@pytest.mark.parametrize("value", ["a string", [1, 2], 7])
@pytest.mark.parametrize("member", ["result", "recipe", "assets"])
def test_item_verdict_never_agrees_over_a_node_it_could_not_read(value, member):
    """This test used to assert `same`, and that was **pinning a bug** (round 3). `_mapping`
    turns a present non-mapping into `{}`, which stops a crash and then makes every check
    below find nothing to disagree with -- so an item contradicting its receipt read `same`
    with `ok` true, and `verify` left the exit status at 0.

    `ItemVerdict`'s own docstring says `inconsistent` is never reported as agreement. A node
    that is present but not an object is exactly that case: nobody could read it, so nothing
    can be established from it.
    """
    item = {"properties": {"receipt:recipe_id": "a" * 64}}
    receipt = {"output": _form(), "recipe": {"recipe_id": "a" * 64}, "result": {},
               "context": _when(), member: value}
    got = r.item_verdict(item, item, receipt)
    if member == "assets":
        # A receipt's `assets` is not a member of a receipt at all, so it is not consulted.
        assert got.verdict == "same", (member, value, got)
    else:
        assert got.verdict == "inconsistent", (member, value, got)
        assert not got.ok


@pytest.mark.parametrize("where,doc_key", [
    ("receipt.result", "result"),
    ("receipt.result.parts", "parts"),
])
@pytest.mark.parametrize("value", ["x", [], ["a"], 7, True])
def test_a_malformed_receipt_node_is_inconsistent_not_same(where, doc_key, value):
    """The symptom measured in round 3: 12 of 24 malformed nodes read `same` with `ok` true,
    for an item whose asset fields contradicted the receipt -- because the asset half of the
    published-vs-receipt check, which round 1 added for exactly this symptom, was skipped for
    every asset once `parts` became `{}`."""
    good = {"output": _form(), "recipe": {"recipe_id": "a" * 64}, "context": _when(),
            "result": {"parts": {"x.tif": {"sha256": "b" * 64, "bytes": 12}}}}
    item = {"properties": {"receipt:recipe_id": "a" * 64},
            "assets": {"data": {"href": "x.tif", "file:checksum": r.multihash("f" * 64),
                                "file:size": 999}}}
    assert r.item_verdict(item, item, good).verdict == "inconsistent", "control"
    broken = dict(good)
    if doc_key == "result":
        broken["result"] = value
    else:
        broken["result"] = {"parts": value}
    got = r.item_verdict(item, item, broken)
    assert got.verdict == "inconsistent", (where, value, got)
    assert where in got.fields, (where, got.fields)


@pytest.mark.parametrize("side", ["published", "served"])
@pytest.mark.parametrize("member", ["assets", "properties"])
@pytest.mark.parametrize("value", ["x", [], 7])
def test_a_malformed_item_node_is_inconsistent_not_same(side, member, value):
    good = {"output": _form(), "recipe": {"recipe_id": "a" * 64}, "context": _when(),
            "result": {}}
    item = {"properties": {"receipt:recipe_id": "a" * 64}, "assets": {}}
    assert r.item_verdict(item, item, good).verdict == "same", "control"
    pair = {"published": dict(item), "served": dict(item)}
    pair[side][member] = value
    got = r.item_verdict(pair["published"], pair["served"], good)
    assert got.verdict == "inconsistent", (side, member, value, got)
    assert f"{side}.{member}" in got.fields, got.fields


@pytest.mark.parametrize("value", ["a string", [1, 2], 7])
def test_item_problems_is_total_where_stac_fields_refuses(value):
    """The two have opposite jobs, so they take opposite answers -- which is the distinction
    round 3's mechanism turns on. `item_problems` REPORTS, so it must be total: a malformed
    item has to come back as a list of problems, never an exception. `stac_fields` PRODUCES
    the fields an item will publish, so it refuses: dropping a non-mapping block would publish
    an item with no provenance and no error.

    This test previously asserted that `stac_fields` survived, which pinned the weaker of the
    two behaviours.
    """
    assert r.item_problems({"properties": value, "assets": value})
    with pytest.raises(r.ReceiptError, match="present but not an object"):
        r.stac_fields({"recipe": value, "result": value, "context": value})


@pytest.mark.parametrize("code", ["a string", ["repo"], 7, None, {"stacs": "0.3.0"},
                                  {"stacs": None}])
def test_stac_fields_refuses_a_malformed_code_block_rather_than_crashing(code):
    """The last instance of round 1's mechanism, found by enumerating every member read in
    `src/stacs/*.py` rather than by a reviewer: `(recipe.get("code") or {}).items()` kept a
    truthy non-mapping and raised AttributeError. `item_verdict` calls `stac_fields` on a
    receipt nothing validated, so it has to refuse rather than crash.

    This test used to assert that a malformed `code` was read as "no repositories", and the
    item came back with no `processing:software` and no error. Mapping v1.1.0 names that as
    the wrong answer: a block or entry present but not an object, `null` included, is refused.
    """
    with pytest.raises(r.ReceiptError, match="present but not an object") as e:
        r.stac_fields({"recipe": {"recipe_id": "a" * 64, "code": code},
                       "result": {}, "context": _when(), "output": _form()})
    assert e.value.code == "block_not_object"


# =============================================================================
# Regressions from round 2b
# =============================================================================

def test_every_register_collection_is_also_a_leaf_row():
    """The measurement behind the finding below: the collection arm and the leaf arm of
    `_diff` are not alternatives for these patterns, they are the same path reached two ways.
    Enumerated from the register so a row added upstream joins the set automatically."""
    table = r.register()
    collections, _prefixes = r._patterns(table)
    both = sorted(collections & set(table))
    assert len(both) == 11, both
    assert sorted(c for c in collections if c) == both, \
        "a collection with no leaf row would have no action to fall back on"


@pytest.mark.parametrize("path,one,two,action", [
    ("recipe.code", "garbage-a", "garbage-b", "refuse"),
    ("recipe.inputs", ["network"], ["roads"], "refuse"),
    ("recipe.config.files", ["a.csv"], ["b.csv"], "refuse"),
    ("recipe.config.settings", ["x"], ["y"], "refuse"),
    ("result.fingerprint", "a", "b", "refuse"),
    ("result.parts", ["a.csv"], ["b.csv"], "refuse"),
    ("result.summary", 1.0, 2.0, "refuse"),
    ("result.tolerance.tables", ["t"], ["u"], "refuse"),
    ("result.tolerance.summary", ["s"], ["v"], "refuse"),
    ("context.toolchain", "x", "y", "record"),
])
def test_a_collection_that_is_not_an_object_on_either_side_is_still_compared(path, one, two,
                                                                            action):
    """Round 2b, and the round 1 mechanism one axis over: `_diff`'s COLLECTIONS arm was tested
    before the branch arm and `keys()` is empty for anything that is not a dict, so two
    non-mappings at a collection path compared nothing and `compare` answered `identical`.

    Eleven register patterns are both a collection and a leaf row, so all eleven were silent.
    The list form is the sharpest case: `recipe_id` REFUSES to hash `{"inputs": ["network"]}`
    because "a list would hash in the order it was written", while `compare` called
    `["network"]` and `["roads"]` identical -- one contract, two answers.
    """
    def at(value):
        doc = {"output": {}, "recipe": {}, "result": {}, "context": {}}
        parts = path.split(".")
        node = doc
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
        return doc

    got = r.compare(at(one), at(two))
    assert (path, action) in got.fields, (path, got.fields)
    # `record` never changes the verdict, which is crate's rule; `refuse` makes it different.
    assert got.verdict == ("different" if action == "refuse" else "identical"), got


def test_a_collection_that_is_an_object_on_one_side_still_walks_its_keys():
    """The other direction: the fix must not turn a real collection into a leaf."""
    base = {"output": {}, "recipe": {}, "result": {}, "context": {}}
    got = r.compare({**base, "recipe": {"inputs": {"a": {"sha256": "1" * 64}}}},
                    {**base, "recipe": {"inputs": {"b": {"sha256": "1" * 64}}}})
    assert ("recipe.inputs", "refuse") in got.fields, got.fields
    assert any("only in a" in d.detail for d in got.differences), got.differences


@pytest.mark.parametrize("href", [["x.tif"], {"a": 1}, 7, None])
def test_an_asset_href_that_is_not_a_string_is_not_used_as_a_dict_key(href):
    """Round 2b. An href indexes `result.parts`, so a list or dict raised
    `TypeError: unhashable type` instead of refusing -- out of `item_verdict`, which
    `_receipt_verdicts` reaches with no audit in front of it on the verify path, so one
    malformed published item would have ended the run with a traceback.

    This is a third mechanism: a JSON value consumed as a dict KEY. The enumeration after
    round 1 could not see it, because its population was member reads.
    """
    rec = {"output": _form(), "recipe": {"recipe_id": "a" * 64}, "context": _when(),
           "result": {"parts": {"x.tif": {"sha256": "b" * 64, "bytes": 1}}}}
    item = {"properties": {"receipt:recipe_id": "a" * 64},
            "assets": {"data": {"href": href, "file:checksum": r.multihash("b" * 64)}}}
    got = r.item_verdict(item, item, rec)
    if href is None:
        # An asset with no href names no part; nothing to compare it with.
        assert got.verdict == "same", got
    else:
        assert got.verdict == "inconsistent", got
        assert "assets[data].href" in got.fields, got.fields


@pytest.mark.parametrize("href", [["x.tif"], {"a": 1}, 7])
def test_stac_fields_refuses_a_non_string_href_from_its_caller(href):
    rec = {"output": _form(), "recipe": {"recipe_id": "a" * 64}, "context": _when(),
           "result": {"parts": {"x.tif": {"sha256": "b" * 64, "bytes": 1}}}}
    with pytest.raises(r.ReceiptError, match="href must be a string"):
        r.stac_fields(rec, assets={"data": href})


@pytest.mark.parametrize("bad", ["x.tif", ["x.tif"], 7])
def test_stac_fields_refuses_an_assets_argument_that_is_not_a_mapping(bad):
    """Enumeration, mechanism D: a public parameter walked with `.items()`. Everything else
    malformed here is a ReceiptError; an AttributeError would name neither the parameter nor
    the type."""
    with pytest.raises(r.ReceiptError, match="assets maps an asset key"):
        r.stac_fields({"output": {}, "recipe": {}, "result": {}, "context": {}}, assets=bad)


@pytest.mark.parametrize("bad", ["context.time", ["context.time"], 7])
def test_compare_refuses_an_overrides_argument_that_is_not_a_mapping(bad):
    base = {"output": {}, "recipe": {}, "result": {}, "context": {}}
    with pytest.raises(r.ReceiptError, match="overrides maps a register field"):
        r.compare(base, base, overrides=bad)


def test_item_verdict_never_says_same_over_a_node_it_could_not_read():
    """Round 3's second post-condition: `same` implies every node the verdict depended on was
    absent or a mapping. Enumerated from `VERDICT_NODES`, which is the list the code itself
    consults -- a second list here would be the "two lists that happen to agree" shape that
    produced three of this branch's defects.
    """
    good_receipt = {"output": _form(), "recipe": {"recipe_id": "a" * 64},
                    "context": _when(), "result": {"parts": {}}}
    good_item = {"properties": {"receipt:recipe_id": "a" * 64}, "assets": {}}
    assert r.item_verdict(good_item, good_item, good_receipt).verdict == "same", "control"

    assert r.VERDICT_NODES, "an empty node list would make this pass on anything"
    for where in r.VERDICT_NODES:
        side, _, member = where.partition(".")
        for value in ("x", [], ["a"], 7, True):
            receipt_doc = {k: (dict(v) if isinstance(v, dict) else v)
                           for k, v in good_receipt.items()}
            published, served = dict(good_item), dict(good_item)
            if side == "receipt":
                if member == "result.parts":
                    receipt_doc["result"] = {"parts": value}
                else:
                    receipt_doc[member] = value
            elif side == "published":
                published[member] = value
            else:
                served[member] = value
            got = r.item_verdict(published, served, receipt_doc)
            assert got.verdict == "inconsistent", (where, value, got)
            assert not got.ok, (where, value)


@pytest.mark.parametrize("block", ["recipe", "result", "context"])
@pytest.mark.parametrize("value", ["x", [], 7])
def test_stac_fields_refuses_a_block_that_is_present_but_not_an_object(block, value):
    """Round 3 named the asymmetry: `assets=` raised while a non-mapping `recipe` was silently
    dropped -- so a builder handed a malformed receipt would publish an item with no
    provenance fields and no error."""
    doc = {"output": {}, "recipe": {}, "result": {}, "context": {}}
    doc[block] = value
    with pytest.raises(r.ReceiptError, match=f"receipt.{block} is present but not an object"):
        r.stac_fields(doc)
