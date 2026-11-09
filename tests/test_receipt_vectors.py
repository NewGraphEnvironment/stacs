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

VECTORS = Path(__file__).resolve().parent / "vectors" / "receipt" / "v1.0.0"

# The v1.0.0 case counts. Pinned, so a truncated or replaced file fails here rather than
# passing over fewer cases: "they are frozen with the receipt schema v1.0.0, a change is a new
# version directory, never an edit."
COUNTS = {"numbers": 2637, "jcs": 10, "recipe_id": 7, "fingerprint": 13, "compare": 9}


def _cases(name):
    path = VECTORS / f"{name}.json"
    assert path.is_file(), (f"{path} is not vendored; run "
                            f"`bash tools/crate_receipt_vendor.sh vendor`")
    cases = json.loads(path.read_text(encoding="utf-8"))
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
