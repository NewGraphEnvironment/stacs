"""crate's receipt test vectors, run against `stacs.receipt`'s own public API.

These are the only thing keeping two implementations of one contract in step, so they are run
through the functions a caller would use -- not through a transcription of crate's crosscheck
script, which would be a check that reads its own output.

The one adapter is doubles: every vector gives a double as its 16-hex-digit bit pattern, "so
no decimal parser stands between the vector and the value". `double_from_bits` is that
conversion and nothing else; the spelling, cell coercion, sorting and hashing under test are
the module's.

Each runner collects every mismatch and asserts the list is empty, rather than stopping at the
first: when a canonicalisation rule is wrong it is usually wrong for a family of cases, and
the family is the diagnosis.
"""

import hashlib
import json
from pathlib import Path

import pytest

from stacs import receipt as r

VECTORS = Path(__file__).resolve().parent / "vectors" / "receipt"

# Where each vector file lives. The three parts of the contract are versioned apart, so the
# hashing vectors sit with the form, `compare.json` with the register whose actions it tests,
# and a directory is named from the version constant the module reads: moving a constant
# without vendoring its vectors fails here as a missing file.
DIRS = {"numbers": f"v{r.RECEIPT_VERSION}", "jcs": f"v{r.RECEIPT_VERSION}",
        "recipe_id": f"v{r.RECEIPT_VERSION}", "fingerprint": f"v{r.RECEIPT_VERSION}",
        "compare": f"register/v{r.REGISTER_VERSION}",
        "stac": f"mapping/v{r.MAPPING_VERSION}"}

# The case counts. Pinned, so a truncated or replaced file fails here rather than passing over
# fewer cases: "a released version is never edited", so a count moves only with a version.
COUNTS = {"numbers": 2637, "jcs": 10, "recipe_id": 7, "fingerprint": 13, "compare": 9,
          "stac": 142}


def _cases(name, load=json.loads):
    path = VECTORS / DIRS[name] / f"{name}.json"
    assert path.is_file(), (f"{path} is not vendored; run "
                            f"`bash tools/crate_receipt_vendor.sh vendor`")
    cases = load(path.read_text(encoding="utf-8"))
    assert isinstance(cases, list) and cases, f"{path} holds no cases"
    assert len(cases) == COUNTS[name], \
        f"{path} holds {len(cases)} case(s), expected {COUNTS[name]}"
    return cases


def test_every_vector_file_is_readable_and_full():
    """A runner over an empty list passes while checking nothing, so the counts are their own
    test as well as a precondition of each runner below."""
    for name, n in COUNTS.items():
        assert len(_cases(name)) == n, name


# =============================================================================
# numbers.json -- the RFC 8785 spelling of a double
# =============================================================================

def test_every_number_is_spelled_as_the_vectors_say():
    bad = []
    for c in _cases("numbers"):
        got = r._shortest(r.double_from_bits(c["bits"]))
        if got != c["expected"]:
            bad.append(f"{c['name']}: {got} != {c['expected']}")
    assert bad[:10] == [], f"{len(bad)} of {COUNTS['numbers']} spellings differ"


def test_the_power_of_two_trap_is_spelled_the_shorter_way():
    """2^-24 is exactly 5.9604644775390625e-8, a tie at 16 digits: printf rounds to the
    neighbour that does not read back, and the one beside it does. Python and Node write
    5.960464477539063e-8. Named here because it is the case a hand-rolled spelling search
    gets wrong, and it would otherwise be 1 failure among 2,637."""
    assert r._shortest(r.double_from_bits("3e70000000000000")) == "5.960464477539063e-8"


# =============================================================================
# jcs.json -- canonical JSON of a parsed document
# =============================================================================

def test_every_canonical_json_case_matches():
    bad = []
    for c in _cases("jcs"):
        got = r.canonical(r.load_json(c["input_json"])).decode("utf-8")
        if got != c["expected"]:
            bad.append(f"{c['name']}:\n  got      {got}\n  expected {c['expected']}")
    assert bad == []


def test_an_integer_past_2_53_is_read_as_a_double():
    """`json.loads` without `parse_int=float` reads this as an int, which `rfc8785` refuses.
    The vectors catch it, but only in the case that happens to carry such a literal."""
    assert r.canonical(r.load_json('{"n":1152921504606846976}')) == b'{"n":1152921504606847000}'
    with pytest.raises(r.ReceiptError, match="beyond a double"):
        r.canonical({"n": 10**400})


# =============================================================================
# recipe_id.json -- the recipe's identity
# =============================================================================

def test_every_recipe_id_case_matches_both_the_bytes_and_the_hash():
    bad = []
    for c in _cases("recipe_id"):
        recipe = r.load_json(c["recipe_json"])
        without = {k: v for k, v in recipe.items() if k != "recipe_id"}
        got_jcs = r.canonical(without).decode("utf-8")
        if got_jcs != c["jcs"]:
            bad.append(f"{c['name']} jcs:\n  got      {got_jcs}\n  expected {c['jcs']}")
        got_id = r.recipe_id(recipe)
        if got_id != c["recipe_id"]:
            bad.append(f"{c['name']} id: {got_id} != {c['recipe_id']}")
    assert bad == []


def test_the_order_members_were_written_in_does_not_change_the_id():
    """The reason the keyed collections are objects: JCS sorts object keys and leaves arrays
    in the order given, so two writers listing the same inputs differently would otherwise
    compute two ids. crate's vectors carry the pair; this names the invariant."""
    cases = {c["name"]: c for c in _cases("recipe_id")}
    a = cases["worked case"]
    b = cases["worked case, members in another order"]
    assert r.recipe_id(r.load_json(a["recipe_json"])) == \
        r.recipe_id(r.load_json(b["recipe_json"]))
    assert a["recipe_id"] == b["recipe_id"]


def test_a_seed_makes_another_recipe():
    cases = {c["name"]: c for c in _cases("recipe_id")}
    assert cases["empty recipe"]["recipe_id"] != cases["a seed makes another recipe"]["recipe_id"]


# =============================================================================
# fingerprint.json -- the table canonical form
# =============================================================================

def _table_from_vector(table):
    """The vector's table with each double's bits turned into the double.

    Only the doubles are touched: character, integer, logical, date and datetime values are
    already in the shape a caller passes, and `null` stays `None`.
    """
    columns = {}
    for name, spec in table["columns"].items():
        values = spec["values"]
        if spec["type"] == "double":
            values = [None if v is None else r.double_from_bits(v) for v in values]
        columns[name] = {"type": spec["type"], "values": values}
    return {"columns": columns}


def test_every_table_fingerprint_case_matches_both_the_bytes_and_the_hash():
    bad = []
    for c in _cases("fingerprint"):
        table = _table_from_vector(c["table"])
        got = r.table_canonical(table, c["tolerance"]).decode("utf-8")
        if got != c["canonical"]:
            bad.append(f"{c['name']} canonical:\n  got      {got}\n  "
                       f"expected {c['canonical']}")
        got_sha = r.table_fingerprint(table, c["tolerance"])
        if got_sha != c["sha256"]:
            bad.append(f"{c['name']} sha256: {got_sha} != {c['sha256']}")
    assert bad == []


def test_the_two_builds_of_the_worked_case_agree_only_once_rounded():
    """The point of a tolerance: the same table from two builds differs in the exact doubles
    and agrees to 1e-9. If this ever passed in both directions the tolerance would be doing
    nothing."""
    cases = {c["name"]: c for c in _cases("fingerprint")}
    exact = (cases["worked case, first build, exact"],
             cases["worked case, second build, exact"])
    rounded = (cases["worked case, first build, km to 1e-9"],
               cases["worked case, second build, km to 1e-9"])
    assert exact[0]["sha256"] != exact[1]["sha256"]
    assert rounded[0]["sha256"] == rounded[1]["sha256"]
    # And computed, not just read out of the file.
    got = [r.table_fingerprint(_table_from_vector(c["table"]), c["tolerance"])
           for c in rounded]
    assert got[0] == got[1] == rounded[0]["sha256"]


def test_a_row_sorts_by_its_bytes_and_not_by_its_values():
    cases = {c["name"]: c for c in _cases("fingerprint")}
    c = cases["row order is byte order"]
    got = r.table_canonical(_table_from_vector(c["table"]), c["tolerance"]).decode("utf-8")
    assert got == c["canonical"]
    # "a b" before "a": the space (0x20) is below the closing quote (0x22).
    assert got.index('["a b"]') < got.index('["a"]')


def test_a_missing_value_is_not_an_empty_string_or_the_text_NA():
    cases = {c["name"]: c for c in _cases("fingerprint")}
    c = cases["NA, empty and the string NA"]
    got = r.table_canonical(_table_from_vector(c["table"]), c["tolerance"]).decode("utf-8")
    assert got == c["canonical"]
    assert '[""]' in got and '["NA"]' in got and "[null]" in got


# =============================================================================
# The sha256 of the canonical bytes is the fingerprint, in both directions
# =============================================================================

def test_the_fingerprint_is_the_hash_of_the_bytes_it_publishes():
    """Two functions, one fact: `table_fingerprint` must be nothing but the digest of
    `table_canonical`, or a caller comparing bytes and a caller comparing hashes could
    disagree."""
    c = _cases("fingerprint")[0]
    table = _table_from_vector(c["table"])
    assert r.table_fingerprint(table, c["tolerance"]) == hashlib.sha256(
        r.table_canonical(table, c["tolerance"])).hexdigest()


# =============================================================================
# compare.json -- the nine receipt pairs
# =============================================================================

def _pairs():
    return {c["name"]: c for c in _cases("compare")}


def test_every_compare_case_matches_the_verdict_and_the_exact_field_list():
    """The half crate's own Python crosscheck does not implement, so these nine pairs are the
    only check that two implementations of the comparison agree.

    The field list is compared as an ORDERED SEQUENCE, not a set: `a migrated receipt` carries
    `recipe.inputs` and `recipe.config.settings` twice each, because a collection with two
    keys missing reports its own path once per key.
    """
    bad = []
    for c in _cases("compare"):
        got = r.compare(c["a"], c["b"])
        want = [(d["field"], d["action"]) for d in c["differences"]]
        if got.verdict != c["verdict"]:
            bad.append(f"{c['name']}: verdict {got.verdict} != {c['verdict']}")
        if got.fields != want:
            bad.append(f"{c['name']} fields:\n  got      {got.fields}\n  expected {want}")
    assert bad == []


def test_a_receipt_compared_with_itself_has_no_differences():
    c = _pairs()["a receipt and itself"]
    got = r.compare(c["a"], c["b"])
    assert (got.verdict, got.differences) == ("identical", ())


def test_a_record_difference_does_not_change_the_verdict():
    """`toolchain only` is `identical` WITH a difference listed. A verdict derived from "are
    there any differences" would call it different, and every rebuild would read as a change."""
    c = _pairs()["toolchain only"]
    got = r.compare(c["a"], c["b"])
    assert got.verdict == "identical"
    assert [d.action for d in got.differences] == ["record"]


def test_a_part_is_equivalent_only_when_a_table_vouches_for_it():
    """The two sides of crate's rule, from two vectors that differ in nothing else: the worked
    case names a table whose fingerprint agrees, so changed bytes are `within`; strip the
    table and the same changed bytes are `refuse`."""
    vouched = r.compare(*[_pairs()["worked case: one recipe, km within tolerance"][k]
                          for k in ("a", "b")])
    unvouched = r.compare(*[_pairs()["bytes moved in a file that names no table"][k]
                            for k in ("a", "b")])
    by_field = {d.field: d for d in vouched.differences}
    assert by_field["result.parts[access_check.csv].sha256"].action == "within"
    assert "agrees" in by_field["result.parts[access_check.csv].sha256"].detail
    by_field = {d.field: d for d in unvouched.differences}
    assert by_field["result.parts[access_check.csv].sha256"].action == "refuse"
    assert "names no table" in by_field["result.parts[access_check.csv].sha256"].detail
    assert (vouched.verdict, unvouched.verdict) == ("equivalent", "different")


def test_a_summary_value_is_within_its_tolerance_or_refused():
    inside = r.compare(*[_pairs()["worked case: one recipe, km within tolerance"][k]
                         for k in ("a", "b")])
    outside = r.compare(*[_pairs()["summary value past its tolerance"][k]
                          for k in ("a", "b")])
    assert {d.field: d.action for d in inside.differences}["result.summary[km_total]"] == "within"
    assert {d.field: d.action
            for d in outside.differences}["result.summary[km_total]"] == "refuse"


def test_a_migrated_receipt_can_never_be_identical_or_equivalent():
    """A null `recipe_id` always refuses: neither side can vouch for a recipe it does not
    have. Without that rule a migrated receipt whose result happens to match would read as
    `identical`, which would publish provenance nobody recorded."""
    c = _pairs()["a migrated receipt"]
    got = r.compare(c["a"], c["b"])
    assert got.verdict == "different"
    recipe_id = [d for d in got.differences if d.field == "recipe.recipe_id"]
    assert len(recipe_id) == 1 and recipe_id[0].action == "refuse"
    assert "holds no recipe identity" in recipe_id[0].detail
    # The MIGRATED side (b: `migrated_from` set, `recipe_id` null) against itself is still
    # different, because a null id is not a value that can agree with anything. Side a is the
    # ordinary receipt, and comparing that with itself is `identical` -- which is what makes
    # this worth asserting on the right side.
    assert r.compare(c["b"], c["b"]).verdict == "different"
    assert r.compare(c["a"], c["a"]).verdict == "identical"


def test_a_collection_with_two_missing_keys_reports_its_path_twice():
    """`differences` is a list, not a set."""
    c = _pairs()["a migrated receipt"]
    fields = [d.field for d in r.compare(c["a"], c["b"]).differences]
    assert fields.count("recipe.inputs") == 2
    assert fields.count("recipe.config.settings") == 2


# =============================================================================
# The register is what decides, and it can be shown deciding
# =============================================================================

def test_the_register_is_load_bearing_and_not_decoration():
    """Flip one row's action and the verdict changes. Without this, a comparison with the
    actions hard-coded in Python would pass every vector above while the vendored register did
    nothing -- and the next crate release would change the file and not the behaviour."""
    c = _pairs()["toolchain only"]
    assert r.compare(c["a"], c["b"]).verdict == "identical"
    assert r.compare(c["a"], c["b"], {"context.toolchain": "refuse"}).verdict == "different"


def test_an_override_must_name_a_known_field_with_a_known_action():
    c = _pairs()["toolchain only"]
    with pytest.raises(r.ReceiptError, match="the register does not have"):
        r.compare(c["a"], c["b"], {"context.nonesuch": "record"})
    with pytest.raises(r.ReceiptError, match="one of refuse, warn, record"):
        r.compare(c["a"], c["b"], {"context.time": "within"})


def test_no_recipe_field_can_be_overridden():
    """Every recipe field refuses because `recipe_id` covers it; relaxing one would publish
    two different recipes as one."""
    c = _pairs()["another seed"]
    with pytest.raises(r.ReceiptError, match="cannot be overridden"):
        r.compare(c["a"], c["b"], {"recipe.seed": "record"})


def test_an_unregistered_field_defaults_to_refuse():
    """A member crate adds in a later version must not be waved through by an older reader."""
    one = {"output": {}, "recipe": {}, "result": {}, "context": {"time": "t"}}
    other = {**one, "output": {"something_new": 1}}
    got = r.compare(one, other)
    assert got.verdict == "different"
    assert [(d.field, d.action) for d in got.differences] == \
        [("output.something_new", "refuse")]


def test_the_register_carries_every_action_the_contract_names():
    table = r.register()
    assert len(table) >= 40, len(table)
    assert set(table.values()) == {"refuse", "warn", "record"}
    # `within` is produced by the comparison, never read from the register.
    assert "within" not in table.values()


# =============================================================================
# A comparison names the rulebook it was judged under
# =============================================================================

def test_every_comparison_names_the_register_version_it_read():
    """The version constant is also the directory `register()` reads and the directory these
    nine pairs were vendored into, so the name on a comparison is the name of the rows that
    produced it. Against the constant, not a literal: a literal here would still pass after
    the register moved. That it is the REGISTER's constant and not the form's, which is equal
    today, is `test_the_register_is_read_and_named_by_its_own_version_not_the_forms`."""
    for c in _cases("compare"):
        got = r.compare(c["a"], c["b"])
        assert got.register == r.REGISTER_VERSION, c["name"]
        assert got.overrides == (), c["name"]


def test_an_override_that_changes_an_action_is_named_on_the_comparison():
    """Listed whether or not that field differed: the verdict was reached under the changed
    rule either way, and a reader of the comparison has to be able to tell."""
    c = _pairs()["toolchain only"]
    table = r.register()
    assert table["context.toolchain"] == "record" and table["output.schema"] == "warn"
    got = r.compare(c["a"], c["b"], {"output.schema": "refuse", "context.toolchain": "refuse"})
    assert got.verdict == "different"
    # Sorted by field as bytes, and `output.schema` did not differ in this pair.
    assert got.overrides == (("context.toolchain", "refuse"), ("output.schema", "refuse"))
    assert "output.schema" not in [d.field for d in got.differences]


def test_restating_the_registers_own_action_is_not_an_override():
    c = _pairs()["toolchain only"]
    got = r.compare(c["a"], c["b"], {"context.toolchain": "record", "context.time": "record"})
    assert (got.verdict, got.overrides) == ("identical", ())


# =============================================================================
# stac.json -- the mapping's STAC rows: the item fields a receipt maps to, or a refusal
# =============================================================================

def _stac_cases():
    """Read with `load_json`, as the receipts' numbers are meant to be read: every number a
    double, so a part's `bytes` arrives as it would from a receipt file."""
    return _cases("stac", r.load_json)


def _mapped(c):
    """(fields, code): what `stac_fields` returned for one case, or the code it refused with."""
    try:
        return r.stac_fields(c["receipt"], assets=c["assets"],
                             receipt_asset=c["receipt_asset"],
                             receipt_sha256=c["receipt_sha256"]), None
    except r.ReceiptError as e:
        # A refusal that carries no code is its own outcome, and never equal to an expected
        # one: "it refused" is not agreement about why.
        return None, e.code if e.code is not None else "<refused with no code>"


def test_every_stac_case_maps_to_the_item_fields_or_the_refusal_the_vectors_say():
    """The mapping's STAC rows, executed. crate's R runs these cases and so does its own
    independent Python reading of the rows; this is the third, and the only thing that says an
    item written through stacs carries what one written through crate would.

    A refusal is compared by its CODE, never its message, and an accepted case by value:
    `stac_extensions` in order, `properties` and `assets` as canonical JSON so member order
    and `12` against `12.0` do not matter.
    """
    bad = []
    for c in _stac_cases():
        got, code = _mapped(c)
        if code != c["error"]:
            bad.append(f"{c['name']}: {'accepted' if code is None else 'refused ' + code}, "
                       f"expected {c['error'] or 'accepted'}")
            continue
        if got is None:
            continue
        want = c["expected"]
        if sorted(got) != ["assets", "properties", "stac_extensions"]:
            bad.append(f"{c['name']}: returned {sorted(got)}")
        elif got["stac_extensions"] != want["stac_extensions"]:
            bad.append(f"{c['name']} stac_extensions:\n  got      {got['stac_extensions']}"
                       f"\n  expected {want['stac_extensions']}")
        else:
            for member in ("properties", "assets"):
                if r.canonical(got[member]) != r.canonical(want[member]):
                    bad.append(f"{c['name']} {member}:\n  got      {r.canonical(got[member])}"
                               f"\n  expected {r.canonical(want[member])}")
    assert bad == [], f"{len(bad)} of {COUNTS['stac']} case(s) disagree"


def test_the_stac_vectors_hold_both_outcomes():
    """A runner over cases that all refuse, or all map, would be checking half the mapping.
    Every case is one or the other, and exactly one of `expected` and `error` is set."""
    cases = _stac_cases()
    accepted = [c for c in cases if c["error"] is None]
    refused = [c for c in cases if c["error"] is not None]
    assert (len(accepted), len(refused)) == (17, 125)
    assert all(isinstance(c["expected"], dict) for c in accepted)
    assert all(c["expected"] is None and isinstance(c["error"], str) for c in refused)


def test_the_refusal_codes_are_exactly_the_ones_the_vectors_use():
    """Three statements of one set, which must be one set: the codes the vectors expect, the
    codes the module declares, and the codes its source actually raises. A code declared and
    never raised would read as covered, and one raised and not declared is a refusal no
    vector can match."""
    import inspect
    import re
    in_vectors = {c["error"] for c in _stac_cases() if c["error"] is not None}
    raised = set(re.findall(r'code="([a-z0-9_]+)"', inspect.getsource(r)))
    assert raised, "no `code=\"...\"` literal found in the module, so this compares nothing"
    assert set(r.STAC_REFUSALS) == in_vectors
    assert raised == in_vectors
    assert len(r.STAC_REFUSALS) == len(set(r.STAC_REFUSALS)) == 17
    # And the contract's own table of them, in the README vendored beside the vectors: the
    # first cell of each row after the `| code | refused |` header.
    readme = (VECTORS / DIRS["stac"] / "README.md").read_text(encoding="utf-8")
    table = readme[readme.index("| code | refused |"):].split("\n\n")[0]
    tabled = {code for row in table.splitlines()[2:]
              for code in re.findall(r"`([a-z0-9_]+)`", row.split("|")[1])}
    assert tabled == in_vectors


# =============================================================================
# item_verdict against the same 142 cases: it never agrees where the mapping refuses
# =============================================================================

# The refusals that are about `stac_fields`' own arguments, which `item_verdict` does not
# pass: it names no receipt asset, and an asset whose href is not a part's key is, to it, an
# asset the receipt does not describe (a thumbnail), never an error.
ARGUMENT_REFUSALS = {"href_not_a_part", "receipt_asset_not_string", "receipt_asset_empty",
                     "receipt_asset_in_assets", "receipt_asset_without_digest",
                     "digest_without_receipt_asset", "digest_not_sha256"}


def test_item_verdict_is_inconsistent_wherever_the_mapping_refuses_the_receipt():
    """The enumeration that ended the review of this code. Three rounds each found `item_verdict`
    agreeing with, or crashing on, a receipt that `stac_fields` refuses, and each time it was
    the same mechanism: the two functions read one receipt separately, so a rule the mapping
    gained reached one of them. `item_verdict` now asks `stac_fields`, and this walks every
    case the contract has rather than the ones a reviewer thought of.

    For each case, an item is built from the case's own `assets`. Where the mapping refuses
    the RECEIPT, the verdict must be `inconsistent`. Where it accepts, the item is given the
    fields the case expects, and the verdict must be `same` -- the direction that stops this
    passing by refusing everything.
    """
    counted = {"refused": 0, "agreed": 0, "argument": 0}
    answered = {"the mapping, by the case's code": 0, "the node check": 0}
    bad = []
    for c in _stac_cases():
        assets = {key: {"href": href} for key, href in c["assets"].items()}
        item = {"properties": {}, "assets": assets}
        if c["error"] in ARGUMENT_REFUSALS:
            counted["argument"] += 1
            continue
        if c["error"] is None:
            item["properties"] = dict(c["expected"]["properties"])
            for key, fields in c["expected"]["assets"].items():
                if key in assets:
                    assets[key].update(fields)
            got = r.item_verdict(item, item, c["receipt"])
            counted["agreed"] += 1
            if got.verdict != "same":
                bad.append(f"{c['name']}: {got.verdict} {got.fields} {got.notes}")
            continue
        got = r.item_verdict(item, item, c["receipt"])
        counted["refused"] += 1
        if got.verdict != "inconsistent" or got.ok:
            bad.append(f"{c['name']} ({c['error']}): {got.verdict}")
        # Which check answered, counted rather than described: three rounds running, a
        # sentence listing where the note carries the mapping's code was wider than the code.
        # Where the mapping answers, the note must carry THIS case's code and no other.
        elif any("maps to no item fields" in note for note in got.notes):
            answered["the mapping, by the case's code"] += 1
            if not any(f"({c['error']})" in note for note in got.notes):
                bad.append(f"{c['name']}: note carries another code than {c['error']}: "
                           f"{got.notes}")
        elif any("present but not objects" in note for note in got.notes):
            answered["the node check"] += 1
        else:
            bad.append(f"{c['name']}: an unrecognised note {got.notes}")
    assert bad == []
    assert answered == {"the mapping, by the case's code": 90, "the node check": 16}, answered
    # Every case is in exactly one arm, and the arm that proves something is not empty.
    assert counted == {"refused": 106, "agreed": 17, "argument": 19}, counted
    assert sum(counted.values()) == COUNTS["stac"]


# =============================================================================
# The post-condition that ends the review loop
# =============================================================================

# Values chosen to cross every type boundary the walk can meet, including the three that
# `code-check.md` keeps apart: zero-length, empty, and unset.
PROBE_VALUES = ({}, {"k": 1}, [], ["x"], "s", 7, 0, None, True)


def _at(path, value):
    """A receipt with `value` at a dotted register path."""
    doc = {"output": {}, "recipe": {}, "result": {}, "context": {}}
    parts = path.split(".")
    node = doc
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
    return doc


def _collection_paths():
    return r._patterns(r.register())[0]


def test_compare_reports_every_difference_its_own_register_can_reach():
    """**This is what ends the review loop**, and it is a property rather than a reviewer's
    opinion: a quiet round and an exhausted reviewer look identical, a measured post-condition
    does not.

    The property: if two receipts' blocks have different canonical bytes, `compare` must report
    at least one difference. Parametrized over every path the register itself names, so a row
    added upstream joins the population automatically -- no hand-written list to fall behind.

    It took three rounds to hold. Round 1 fixed `_diff`'s branch arm; round 2b found the
    collection arm two lines above it; round 3 found that `isinstance(x, dict) or
    isinstance(y, dict)` still left `{}` against `["network"]` silent, 154 violations over
    3,816 differing pairs. Each fix was written under the same assumption as the last: that
    "not a mapping" and "has no members" are one fact.

    The one exemption is enumerated below, not waved through.
    """
    table = r.register()
    collections, prefixes = r._patterns(table)
    exempt, violations, checked = [], [], 0
    for pattern in sorted(prefixes):
        block = pattern.split(".")[0]
        for one in PROBE_VALUES:
            for two in PROBE_VALUES:
                a, b = _at(pattern, one), _at(pattern, two)
                if r.canonical(a[block]) == r.canonical(b[block]):
                    continue
                checked += 1
                if r.compare(a, b).differences:
                    continue
                # The exemption: an EMPTY collection against an ABSENT one. crate walks a
                # collection by its key sets (`names(NULL)` and `names(list())` are both
                # empty in R/crt_receipt_compare.R:230-231), so it reports nothing either --
                # and a receipt that declares no inputs still differs from one that records
                # none at `recipe.recipe_id`, which is compared and refuses.
                if pattern in collections and {canon(one), canon(two)} == {"{}", "null"}:
                    exempt.append((pattern, one, two))
                else:
                    violations.append((pattern, one, two))
    assert checked > 3000, f"only {checked} differing pairs: the probe got narrower"
    assert violations == [], f"{len(violations)} of {checked} differing pairs reported nothing"
    # The carve-out is a number too: exactly the empty-vs-absent pair, both orders, at each of
    # the eleven collection patterns.
    assert len(exempt) == 2 * len(collections), (len(exempt), len(collections))


def canon(value):
    return r.canonical(value).decode("utf-8")


def test_the_post_condition_probe_can_fail():
    """The property above is only worth having if it would catch the defect it was written
    for. Restored here against the logic rather than the code: the old collection arm compared
    key sets only, which is this."""
    def old_arm(x, y):
        kx = list(x) if isinstance(x, dict) else []
        ky = list(y) if isinstance(y, dict) else []
        return bool(set(kx) ^ set(ky))

    # The exact pair round 3 measured: one empty mapping, one list.
    assert not old_arm({}, ["network"]), "the old arm did report this; the probe is wrong"
    assert r.compare(_at("recipe.inputs", {}), _at("recipe.inputs", ["network"])).differences
