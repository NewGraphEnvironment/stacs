"""`stacs.receipt`'s own behaviour: the frozen canonical form, and what it refuses.

The vectors (`test_receipt_vectors.py`) prove agreement with crate. This file pins the things
the vectors cannot see: that the receipt canonical form is kept apart from `stacs.verify`'s,
that the frozen URLs say what they claim, and that a Python value with no place in the
contract is refused by name rather than hashed into something plausible.
"""

import datetime

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
