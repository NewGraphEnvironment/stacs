"""Provenance receipts for catalogue items: crate's receipt contract, in Python.

A receipt is one record per published output -- `output` (what it is), `recipe` (how it was
made), `result` (what came out) and `context` (where and when) -- with a `recipe_id` that
identifies the recipe alone. Two items with the same `recipe_id` were made the same way, so a
rebuilt item can be told apart from a changed one.

**What this module does and does not do.** The builder hands it values; it computes the ids,
writes the receipt and compares two of them. It reads no source data and builds no item, which
is why it belongs in a package that works on a catalogue after its items exist.

**Its canonical form is frozen, which `stacs.verify`'s is not.** `verify.canonical_json` may
change shape with no migration, because nothing stores a body digest -- both sides are
recomputed every run. A `recipe_id` is *published*, inside items and beside them, so the bytes
it is taken over can move only with a new receipt schema version. The two forms are also
different on purpose: `verify`'s drops `links` and null members to absorb what pgstac's round
trip changes, and a receipt's applies no STAC rules at all. Neither may be used for the other.

The contract is crate's, in three parts that are each versioned on their own: the form (the
fields a receipt has), the register (what a difference in each field does to a comparison) and
the mapping (how a receipt's fields become an item's). Each is vendored under `data/receipt/`
at its version and checked in CI against the tag it came from and the URL crate serves it at;
crate's test vectors are the only thing keeping the two implementations in step.
"""

import copy
import csv
import datetime
import hashlib
import io
import json
import os
import re
import stat
import struct
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import rfc8785

# The frozen schema version this module reads and writes. crate's reader refuses any other
# rather than warning, and so does `read` below: a receipt from a later version may spell a
# field the same way and mean something else.
RECEIPT_VERSION = "1.0.0"

# The two frozen URLs. A published version is never edited, so these are safe to write into
# stored records -- and `tools/crate_receipt_vendor.sh check` proves each still serves the
# bytes vendored beside this file.
#
# Written out in full rather than built from RECEIPT_VERSION: a frozen URL that is recomposed
# from a variable reads as though a new version could be reached by changing the variable,
# when a new version is a new schema, a new vendored copy and a deliberate change here. A test
# pins each against RECEIPT_VERSION so the two cannot drift apart.
SCHEMA_URL = "https://newgraphenvironment.github.io/crate/receipt/v1.0.0/schema.json"
EXTENSION_URL = "https://newgraphenvironment.github.io/crate/stac/receipt/v1.0.0/schema.json"

# The other two parts of the contract, each versioned apart from the form. A receipt carries
# only RECEIPT_VERSION: a register or mapping change never moves it.
#
# REGISTER_VERSION is the rulebook `compare` reads, and every `Comparison` names it, because a
# verdict is a function of the register's rows. MAPPING_VERSION is the mapping `stac_fields`
# executes; nothing published carries it yet. A released version is never edited, so moving
# either is a new vendored directory (`tools/crate_receipt_vendor.sh`) and a deliberate change
# here, and the tests pin each constant to the directory and the served URL the script checks.
REGISTER_VERSION = "1.0.0"
MAPPING_VERSION = "1.1.0"

# JCS treats every JSON number as an IEEE double, and `rfc8785` refuses a Python int outside
# the range a double holds exactly rather than round it.
_SAFE_INT = 2**53 - 1

# The spellings a table cell's date and datetime must have, checked rather than trusted: a
# value already in the canonical form is passed through, so a wrong one would be hashed.
_DATE = re.compile(r"^-?\d{4,}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^-?\d{4,}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

CELL_TYPES = ("character", "integer", "double", "logical", "date", "datetime")


def _mapping(node, key=None):
    """`node`, or `node[key]`, when it is a mapping -- otherwise `{}`.

    `node.get(key) or {}` is not this: it keeps a truthy non-mapping, so a string where an
    object belongs reaches the next `.get` and raises `AttributeError`. Every member read
    below comes through here, because a receipt that has been hand-edited, migrated, or
    written by something else reaches `compare` and `item_verdict` unvalidated -- `read`
    checks only the version -- and those are the functions that have to refuse it rather
    than crash on it (round 1).
    """
    if key is not None:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def _list(node, key):
    """`node[key]` when `node` is a mapping and that member is a list -- otherwise `[]`.

    The list sibling of `_mapping`, for the same reason: `node.get(key) or []` keeps a truthy
    non-list, and `in` then raises on a number and matches a string by SUBSTRING and an object
    by key, so `roles: "metadata"` was taken for the receipt's role (#17). A caller that must
    say the member was malformed checks `isinstance` itself; this only stops it being read.
    """
    node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, list) else []


class ReceiptError(ValueError):
    """A receipt, recipe or table that has no canonical form, or does not meet the contract.

    Raised with what was wrong and where, never with the value alone: a message naming the
    column or the member is the difference between a two-minute fix and a bisect.

    `code` is the contract's name for the refusal where it has one, and None otherwise. The
    mapping's vectors compare two implementations by code, never by message, so a caller that
    branches on why `stac_fields` refused reads `code` too; `STAC_REFUSALS` lists them.

    Examples:
        >>> try:
        ...     stac_fields({"output": None})      # null is not an absent block
        ... except ReceiptError as e:
        ...     e.code
        'block_not_object'
        >>> ReceiptError("no canonical form").code is None
        True
    """

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def load_json(text):
    """Parse JSON the way the receipt contract requires: every number as a double.

    JSON has one number type and RFC 8785 spells every number as ECMAScript does, but Python's
    `json` reads an integer literal as `int` -- and `rfc8785` refuses an int past 2^53 rather
    than rounding it. So this is the one reader every entry point here uses, rather than a
    `parse_int=` argument repeated at each call site and forgotten at one of them.

    Examples:
        >>> load_json('{"n": 1152921504606846976}')["n"]
        1.152921504606847e+18
        >>> load_json('{"n": 3}')["n"]
        3.0
        >>> canonical(load_json('{"n": 1152921504606846976}'))
        b'{"n":1152921504606847000}'
    """
    if not isinstance(text, (str, bytes, bytearray)):
        raise ReceiptError(f"expected JSON text, got {type(text).__name__}")
    try:
        return json.loads(text, parse_int=float)
    except ValueError as e:
        raise ReceiptError(f"not valid JSON: {e}") from e


def _ready(x, where):
    """`x` with the one coercion JCS's own number model requires, and a refusal for anything
    that has no JSON spelling.

    Only `type(x) is int` is widened to a double -- `bool` is an `int` subclass and `true` is
    not `1`. Everything outside JSON's types is refused by name here rather than left to
    `rfc8785`, whose message names neither the member nor the type.
    """
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if not isinstance(k, str):
                raise ReceiptError(f"{where}: object key {k!r} is not a string")
            out[k] = _ready(v, f"{where}.{k}")
        return out
    if isinstance(x, (list, tuple)):
        return [_ready(v, f"{where}[{i}]") for i, v in enumerate(x)]
    if x is None or isinstance(x, bool) or isinstance(x, str):
        return x
    if type(x) is int:
        if -_SAFE_INT <= x <= _SAFE_INT:
            return x
        try:
            return float(x)
        except OverflowError:
            raise ReceiptError(f"{where}: integer of {len(str(abs(x)))} digits is beyond a "
                               f"double") from None
    if type(x) is float:
        return x
    raise ReceiptError(f"{where}: {type(x).__name__} has no JSON spelling; pass a string, a "
                       f"number, a bool, None, a list or a dict")


def canonical(value) -> bytes:
    """RFC 8785 (JCS) canonical JSON of `value`, with no STAC rules applied.

    This is the plain canonical form crate's specification names: nothing is removed and
    nothing is absorbed. `stacs.verify.canonical_json` is a different function for a different
    job -- it drops `links` and null members because pgstac does -- and the two must not be
    substituted for one another.

    Examples:
        Keys sorted, nulls kept, `1.0` written as `1`, `-0` as `0`:

        >>> canonical({"b": None, "a": 1.0, "c": -0.0})
        b'{"a":1,"b":null,"c":0}'

        A top-level scalar is a JSON document too:

        >>> canonical("x")
        b'"x"'

        No canonical form is an error, naming the member:

        >>> canonical({"n": float("nan")})
        Traceback (most recent call last):
        ...
        stacs.receipt.ReceiptError: no canonical form at n: ...
    """
    ready = _ready(value, "")
    try:
        return rfc8785.dumps(ready)
    # UnicodeError too: a lone surrogate in a KEY fails in rfc8785's key sort, before its own
    # serialiser can raise CanonicalizationError.
    except (rfc8785.CanonicalizationError, UnicodeError, ValueError) as e:
        where = _no_canonical_form(ready) or ""
        raise ReceiptError(f"no canonical form at {where or '<value>'}: {e}") from e


def _no_canonical_form(x, where=""):
    """The path of the first member with no canonical form, for the message above. A best
    effort: it finds the NaN or infinity, which is the case that happens."""
    if isinstance(x, dict):
        for k, v in x.items():
            hit = _no_canonical_form(v, f"{where}.{k}" if where else k)
            if hit:
                return hit
    elif isinstance(x, list):
        for i, v in enumerate(x):
            hit = _no_canonical_form(v, f"{where}[{i}]")
            if hit:
                return hit
    elif isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
        return where
    return None


def _shortest(x: float) -> str:
    """The RFC 8785 spelling of a double.

    Handed to `rfc8785` as a float on purpose: it refuses an int past 2^53, and a double is
    spelled the same way whatever its value. At a power of two the shortest spelling can be
    the decimal beside printf's rounding (2^-24 is `5.960464477539063e-8`); Python's own
    shortest-round-trip formatting, which `rfc8785` uses, gets that right, which is why no
    spelling search is implemented here.
    """
    return rfc8785.dumps(float(x)).decode("utf-8")


# =============================================================================
# recipe_id -- the recipe's identity
# =============================================================================

# Collections inside a recipe are objects keyed by name, never arrays, "because JCS sorts
# object keys and leaves arrays in the order given": two writers listing the same inputs in
# another order would otherwise compute two ids. A list here canonicalises happily and yields
# a plausible wrong id, so it is refused.
_KEYED = (("code",), ("inputs",), ("config", "files"), ("config", "settings"))


def _refuse_keyed(where, node):
    raise ReceiptError(f"{where} must be an object keyed by name, got "
                       f"{type(node).__name__}: a list would hash in the order it was "
                       f"written")


def _check_keyed(recipe):
    """Refuse a keyed collection written as anything but an object, at every depth.

    An INTERMEDIATE node matters as much as the leaf: `recipe.config` written as a list used
    to skip the checks on `config.files` and `config.settings` entirely -- the `for ... else`
    did not run after a `break` -- and the list was then hashed in written order, which is
    exactly what this guard exists to prevent (round 1).

    An ABSENT intermediate is not an error here: a migrated recipe has every member optional,
    and whether it may be missing is the schema's question, not this one's.
    """
    for path in _KEYED:
        node = recipe
        for i, part in enumerate(path):
            if node is None:
                break
            if not isinstance(node, dict):
                _refuse_keyed(f"recipe.{'.'.join(path[:i])}", node)
            node = node.get(part)
        if node is not None and not isinstance(node, dict):
            _refuse_keyed(f"recipe.{'.'.join(path)}", node)


def recipe_id(recipe) -> str:
    """SHA-256, lowercase hex, over the canonical JSON of a recipe block without its own
    `recipe_id`.

    The whole recipe and nothing else: `output`, `result` and `context` are not part of it, and
    neither is any input's result -- an input enters by its own identity (`recipe_id`,
    `version_id`, `sha256`, or a declared `none`).

    Examples:
        The empty recipe, which crate's vectors pin:

        >>> empty = {"code": {}, "config": {"files": {}, "settings": {}},
        ...          "inputs": {}, "seed": None}
        >>> recipe_id(empty)
        'ecb53cd4e03b09490f6c581b1195aa9635e5fff51790d64e19d2a2a79f8a0493'

        A recipe carrying an id hashes as though it did not:

        >>> recipe_id({**empty, "recipe_id": "0" * 64}) == recipe_id(empty)
        True

        A keyed collection written as a list is refused, not hashed:

        >>> recipe_id({**empty, "inputs": ["network"]})
        Traceback (most recent call last):
        ...
        stacs.receipt.ReceiptError: recipe.inputs must be an object keyed by name, got list: ...
    """
    if not isinstance(recipe, dict):
        raise ReceiptError(f"a recipe is a JSON object, got {type(recipe).__name__}")
    _check_keyed(recipe)
    without = {k: v for k, v in recipe.items() if k != "recipe_id"}
    return hashlib.sha256(canonical(without)).hexdigest()


# =============================================================================
# Table fingerprint -- the result's identity for a table
# =============================================================================

def tolerance_decimals(tol) -> int:
    """The decimals a tolerance rounds to.

    A tolerance is an absolute power of ten from 1 to 1e-15, so it names both the rounding of
    a fingerprint and what a comparison accepts. Anything else has no rounding that matches it.

    Examples:
        >>> tolerance_decimals(1e-9)
        9
        >>> tolerance_decimals(1)
        0
        >>> tolerance_decimals(0.5)
        Traceback (most recent call last):
        ...
        stacs.receipt.ReceiptError: tolerance 0.5 is not a power of ten from 1 to 1e-15
    """
    if isinstance(tol, bool) or not isinstance(tol, (int, float)):
        raise ReceiptError(f"a tolerance is a number, got {type(tol).__name__}")
    for k in range(16):
        if tol > 0 and abs(tol / 10.0**-k - 1) < 1e-9:
            return k
    raise ReceiptError(f"tolerance {tol!r} is not a power of ten from 1 to 1e-15")


def _year_ok(text: str, where: str) -> None:
    year = int(text.split("-")[0] or 0) if not text.startswith("-") else -1
    if not 1 <= year <= 9999:
        raise ReceiptError(f"{where}: year {text.split('T')[0]!r} is outside 1-9999, which has "
                           f"no agreed spelling")


def _cell(value, col_type: str, decimals, where: str):
    """One table cell as the contract spells it: a string, or None for a missing value.

    Every cell is a JSON *string*, so JCS's number rules never apply to a cell value -- the
    spelling is decided here and hashed verbatim.
    """
    if value is None:
        return None
    if col_type == "character":
        if not isinstance(value, str):
            raise ReceiptError(f"{where}: a character cell is a string, got "
                               f"{type(value).__name__}")
        return value
    if col_type == "logical":
        # Before the integer branch, and by type: `bool` is an `int` subclass, so an
        # `int(value)` here would write "1" where the contract wants "true".
        if not isinstance(value, bool):
            raise ReceiptError(f"{where}: a logical cell is True or False, got "
                               f"{type(value).__name__}")
        return "true" if value else "false"
    if col_type == "integer":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ReceiptError(f"{where}: an integer cell is a whole number, got "
                               f"{type(value).__name__}")
        # A float arrives from `load_json`, which reads every JSON number as a double.
        if isinstance(value, float) and not value.is_integer():
            raise ReceiptError(f"{where}: integer cell {value!r} is not whole")
        return str(int(value))
    if col_type == "double":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ReceiptError(f"{where}: a double cell is a number, got "
                               f"{type(value).__name__}")
        x = float(value)
        if x != x or x in (float("inf"), float("-inf")):
            raise ReceiptError(f"{where}: NaN and infinity have no canonical form")
        if decimals is None:
            return _shortest(x)
        text = format(x, f".{decimals}f")  # the exact binary value, ties to even
        # printf keeps the sign of a value that rounds to zero ("-0.00"); one zero has one
        # spelling.
        if text.startswith("-") and set(text[1:]) <= {"0", "."}:
            text = text[1:]
        return text
    if col_type == "date":
        if isinstance(value, datetime.datetime):
            raise ReceiptError(f"{where}: a date cell is a date, not a datetime")
        if isinstance(value, datetime.date):
            value = value.isoformat()
        if not isinstance(value, str) or not _DATE.match(value):
            raise ReceiptError(f"{where}: a date cell is YYYY-MM-DD or a date, got {value!r}")
        _year_ok(value, where)
        return value
    if col_type == "datetime":
        if isinstance(value, datetime.datetime):
            if value.tzinfo is None:
                raise ReceiptError(f"{where}: a datetime with no time zone is a guess; give "
                                   f"it UTC")
            value = value.astimezone(datetime.timezone.utc)
            if value.microsecond:
                raise ReceiptError(f"{where}: fractional seconds have no canonical form; "
                                   f"round it, or fingerprint it as a number")
            value = value.strftime("%Y-%m-%dT%H:%M:%SZ")
        if not isinstance(value, str) or not _DATETIME.match(value):
            raise ReceiptError(f"{where}: a datetime cell is YYYY-MM-DDTHH:MM:SSZ in UTC, got "
                               f"{value!r}")
        _year_ok(value, where)
        return value
    raise ReceiptError(f"{where}: unknown column type {col_type!r}; one of "
                       f"{', '.join(CELL_TYPES)}")


def table_canonical(table, tolerance=None) -> bytes:
    """The bytes a table's fingerprint is taken over.

    `table` is column-major, `{"columns": {<name>: {"type": <t>, "values": [...]}}}`, with `t`
    one of character, integer, double, logical, date, datetime. `tolerance` maps a column name
    to a power of ten; a double in such a column is written with that many decimals, and
    without one it gets its shortest round-trip spelling.

    Columns sort by their UTF-8 bytes and so do rows -- by the bytes of each row's own JSON,
    not by their values, so `["a b"]` sorts before `["a"]` (a space is below the closing
    quote). The rule is mechanical so that no implementation needs a collation.

    Examples:
        >>> t = {"columns": {"n": {"type": "integer", "values": [2, 1]},
        ...                  "km": {"type": "double", "values": [7.25, 0.5]}}}
        >>> table_canonical(t)
        b'{"columns":["km","n"],"rows":[["0.5","1"],["7.25","2"]]}'
        >>> table_canonical(t, {"km": 1})
        b'{"columns":["km","n"],"rows":[["0","1"],["7","2"]]}'
    """
    if not isinstance(table, dict) or not isinstance(table.get("columns"), dict):
        raise ReceiptError('a table is {"columns": {<name>: {"type": ..., "values": [...]}}}')
    columns = table["columns"]
    tolerance = {} if tolerance is None else tolerance
    if not isinstance(tolerance, dict):
        raise ReceiptError(f"tolerance maps a column to a power of ten, got "
                           f"{type(tolerance).__name__}")
    unknown = sorted(set(tolerance) - set(columns))
    if unknown:
        # A tolerance for a column that is not there rounds nothing, and reads as though the
        # column had been checked.
        raise ReceiptError(f"tolerance names column(s) the table does not have: {unknown}")
    decimals = {name: tolerance_decimals(tol) for name, tol in tolerance.items()}

    names = sorted(columns, key=lambda n: n.encode("utf-8"))
    n_rows = None
    for name in names:
        spec = columns[name]
        if not isinstance(spec, dict) or "type" not in spec or "values" not in spec:
            raise ReceiptError(f"column {name!r} is not "
                               f'{{"type": ..., "values": [...]}}')
        if not isinstance(spec["values"], (list, tuple)):
            raise ReceiptError(f"column {name!r}: values is not a list")
        if n_rows is None:
            n_rows = len(spec["values"])
        elif len(spec["values"]) != n_rows:
            # Ragged columns would pair cell i of one column with nothing in another, and the
            # fingerprint would describe a table that does not exist.
            raise ReceiptError(f"column {name!r} has {len(spec['values'])} value(s), "
                               f"{names[0]!r} has {n_rows}")
    n_rows = n_rows or 0

    rows = []
    for i in range(n_rows):
        row = [_cell(columns[name]["values"][i], columns[name]["type"],
                     decimals.get(name), f"row {i} of column {name!r}")
               for name in names]
        rows.append(canonical(row))
    rows.sort()
    return b'{"columns":' + canonical(names) + b',"rows":[' + b",".join(rows) + b"]}"


def table_fingerprint(table, tolerance=None) -> str:
    """SHA-256, lowercase hex, of `table_canonical(table, tolerance)`.

    Not to be confused with a schema fingerprint, which hashes a table's column names and
    types and never its values.

    Examples:
        >>> table_fingerprint({"columns": {"a": {"type": "integer", "values": []},
        ...                                "b": {"type": "integer", "values": []}}})
        '4b50177c31441e4ae3e6691a6f82a75a30a21f197dd400e7a9a781c99eff4d36'
    """
    return hashlib.sha256(table_canonical(table, tolerance)).hexdigest()


def double_from_bits(bits: str) -> float:
    """The double a 16-hex-digit big-endian bit pattern denotes.

    crate's vectors give every double as its bits, so no decimal parser stands between a
    vector and the value it fixes. A caller with a number does not need this.

    Examples:
        >>> double_from_bits("3e70000000000000")  # 2 ** -24
        5.960464477539063e-08
        >>> _shortest(double_from_bits("3e70000000000000"))
        '5.960464477539063e-8'
    """
    if not isinstance(bits, str) or not re.fullmatch(r"[0-9a-fA-F]{16}", bits):
        raise ReceiptError(f"a double's bits are 16 hex digits, got {bits!r}")
    return struct.unpack(">d", bytes.fromhex(bits))[0]


# =============================================================================
# The vendored contract, read lazily
# =============================================================================

# Read on first use and kept, never at import. Every module here is imported by the
# deployment-name guard's `pkgutil.walk_packages` walk and again by `--doctest-modules`, so an
# import-time read would turn a missing data file into a collection error across the whole
# suite instead of one failing test.
_DATA: dict = {}


def _data_text(*parts: str) -> str:
    """The text of one vendored contract file.

    Through `importlib.resources`, so it is found the same way in a source tree and in an
    installed wheel.
    """
    if parts not in _DATA:
        from importlib import resources
        ref = resources.files("stacs").joinpath("data", "receipt", *parts)
        try:
            _DATA[parts] = ref.read_text(encoding="utf-8")
        except (OSError, ValueError) as e:
            raise ReceiptError(
                f"the vendored receipt contract is missing {'/'.join(parts)}: {e}. In a source "
                f"tree, `bash tools/crate_receipt_vendor.sh vendor`") from e
    return _DATA[parts]


def _schema(name: str) -> dict:
    """One of the two frozen schemas, parsed.

    Plain `json.loads`, not `load_json`: a schema's numbers are keywords (`minLength: 1`), not
    a receipt's data, and `jsonschema` wants `1` rather than `1.0` for a length.
    """
    key = ("parsed", name)
    if key not in _DATA:
        _DATA[key] = json.loads(_data_text(f"v{RECEIPT_VERSION}", name))
    return _DATA[key]


def schema() -> dict:
    """The frozen receipt JSON Schema, as vendored.

    Examples:
        >>> schema()["$id"] == SCHEMA_URL
        True
        >>> sorted(schema()["required"])
        ['context', 'output', 'recipe', 'result']
    """
    return _schema("schema.json")


def stac_schema() -> dict:
    """The frozen `receipt:` STAC field schema, as vendored.

    Examples:
        >>> stac_schema()["$id"] == EXTENSION_URL
        True
    """
    return _schema("stac_schema.json")


# =============================================================================
# validate
# =============================================================================

def validate(receipt) -> None:
    """Check a receipt against the frozen schema. Returns None, raises on the first failures.

    Every error is collected and the message names the member paths, because a receipt that
    fails in three places usually fails for one reason and the paths are the diagnosis.

    The schema is the vendored copy, not the URL: the suite is offline, and a validator that
    fetched its schema would be checking whatever is served today against bytes that are
    supposed to be frozen. `tools/crate_receipt_vendor.sh check` is what compares the two.

    Examples:
        >>> validate({"output": {}})
        Traceback (most recent call last):
        ...
        stacs.receipt.ReceiptError: not a valid receipt: ...
    """
    import jsonschema

    validator = jsonschema.Draft7Validator(schema())
    errors = sorted(validator.iter_errors(receipt), key=lambda e: list(e.absolute_path))
    if errors:
        where = "; ".join(
            f"{'.'.join(str(p) for p in e.absolute_path) or '<receipt>'}: {e.message}"
            for e in errors[:3])
        raise ReceiptError(f"not a valid receipt: {len(errors)} problem(s); {where}")


# =============================================================================
# read and write
# =============================================================================

def read(path) -> dict:
    """Read a receipt file, refusing any version but the one this module implements.

    Refused rather than warned about, as crate's reader does: a later version may spell a
    field the same way and mean something else, and a comparison across two versions would
    report fields that agree as differing.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise ReceiptError(f"cannot read {path}: {e}") from e
    doc = load_json(text)
    if not isinstance(doc, dict):
        raise ReceiptError(f"{path} is not a JSON object")
    version = _mapping(doc, "output").get("receipt_version") \
        if isinstance(doc.get("output"), dict) else None
    if version != RECEIPT_VERSION:
        raise ReceiptError(f"{path} is receipt version {version!r}; this reads "
                           f"{RECEIPT_VERSION!r}")
    return doc


def reindent(data: bytes) -> str:
    """Canonical JSON re-indented at two spaces, with empty containers left collapsed.

    A text transformation, and that is the point: the file must carry the canonical *number
    spellings*, and re-serialising the parsed object does not. `json.dumps` writes `1e-06`
    where JCS writes `0.000001`, and `1e-09` where JCS writes `1e-9` -- and crate's own
    worked-case receipt holds both of those as ordinary tolerance values.

    Examples:
        >>> print(reindent(b'{"a":{},"b":[1,2],"c":{"d":1e-9}}'))
        {
          "a": {},
          "b": [
            1,
            2
          ],
          "c": {
            "d": 1e-9
          }
        }
    """
    text = data.decode("utf-8")
    out = []
    depth = 0
    in_string = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
        elif ch in "{[":
            # Canonical JSON carries no whitespace, so an empty container is exactly these two
            # characters side by side. Collapsed, as crate's writer collapses them.
            if i + 1 < len(text) and text[i + 1] == ("}" if ch == "{" else "]"):
                out.append(ch + text[i + 1])
                i += 2
                continue
            depth += 1
            out.append(ch + "\n" + "  " * depth)
        elif ch in "}]":
            depth -= 1
            out.append("\n" + "  " * depth + ch)
        elif ch == ",":
            out.append(",\n" + "  " * depth)
        elif ch == ":":
            out.append(": ")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _atomic_write(path: Path, data: bytes) -> None:
    """Write `data` to `path` through a temp file in the same directory.

    `mkstemp` creates the temp file 0600, and `os.replace` carries that mode onto the target,
    so a receipt published next to its item would become unreadable to everyone else. The mode
    is set before the rename: the target's own where it exists, the umask default where it does
    not.
    """
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)
        except FileNotFoundError:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write(receipt, path, publish: bool = True) -> str:
    """Write a receipt, computing its `recipe_id`, and return the SHA-256 of the bytes written.

    The caller supplies the values; the ids are computed here, so a builder cannot publish a
    `recipe_id` that does not match the recipe beside it. The receipt is validated before
    anything is written.

    `publish` drops `context.host`, which is the one member a published receipt leaves out
    rather than nulls: where a thing was built is not something an outside reader needs, and it
    is never part of an identity.

    The returned digest is what an item's `receipt` asset carries as `file:checksum`. Nothing
    else can compute it -- the receipt's own bytes are not inside it -- and without it a reader
    that fetches a receipt beside an item cannot tell it fetched *that* item's receipt.

    The caller's dict is not modified.
    """
    path = Path(path)
    if not isinstance(receipt, dict):
        raise ReceiptError(f"a receipt is a JSON object, got {type(receipt).__name__}")
    doc = copy.deepcopy(receipt)
    output = doc.setdefault("output", {})
    if not isinstance(output, dict):
        raise ReceiptError(f"output is not an object, got {type(output).__name__}")
    output.setdefault("receipt_version", RECEIPT_VERSION)
    recipe = doc.get("recipe")
    if not isinstance(recipe, dict):
        raise ReceiptError(f"recipe is not an object, got {type(recipe).__name__}")
    if "migrated_from" in output:
        # A migrated receipt has no recipe identity, and null is the contract's way of saying
        # so. Computing one would invent an identity for a recipe nobody recorded.
        recipe["recipe_id"] = None
    else:
        recipe["recipe_id"] = recipe_id(recipe)
    context = doc.get("context")
    if publish and isinstance(context, dict):
        context.pop("host", None)
    validate(doc)
    data = (reindent(canonical(doc)) + "\n").encode("utf-8")
    _atomic_write(path, data)
    return hashlib.sha256(data).hexdigest()


# =============================================================================
# compare -- identical, equivalent, different
# =============================================================================

# The verdicts, and what produces each. `within` is NOT a register action: the register says
# `refuse`, `warn` or `record`, and the comparison promotes a result value that differs inside
# its declared tolerance to `within`.
ACTIONS = ("refuse", "warn", "record", "within")

# Tables are not supplied to `compare`, so a fingerprint that differs stays a refusal. crate
# calls the other mode "bytes": it re-reads each supplied table, certifies it against its own
# receipt, and can then settle a fingerprint difference as `within`. The vectors do not
# exercise it (`compare.json` carries no tables), so it is not implemented rather than
# implemented untested.
MODE = "receipts"


@dataclass(frozen=True)
class Difference:
    """One field that differs, with the action the register gives it.

    `side` is the block the register pattern starts in, not a judgement about which receipt is
    wrong.
    """
    side: str
    field: str
    action: str
    detail: str


@dataclass(frozen=True)
class Comparison:
    """The outcome of comparing two receipts.

    `differences` is an ORDERED LIST and may repeat a field: a collection with two keys
    missing reports its own path twice, which crate's `a migrated receipt` vector shows for
    both `recipe.inputs` and `recipe.config.settings`. A set would lose one of each.

    `register` is the version of the register the verdict was judged under. A verdict is a
    function of the register's rows, so one kept without it cannot be re-read once the rows
    move. It is not the receipts' version: a register change never moves the form's.

    `overrides` is each `(field, action)` the caller's `overrides` CHANGED, sorted by field as
    bytes, and empty when it changed none. Every such field is listed whether or not it
    differed in this comparison, because the verdict was reached under those rules either
    way; restating the register's own action is not an override.
    """
    verdict: str
    mode: str
    differences: tuple
    register: str
    overrides: tuple

    @property
    def fields(self) -> list:
        """[(field, action)] -- what crate's vectors pin, without the prose detail."""
        return [(d.field, d.action) for d in self.differences]


def register() -> dict:
    """crate's register: every receipt field that can differ, and what a difference means.

    `refuse` makes the verdict `different`, `warn` and `record` never change it. Returned in
    file order, as a plain dict of field pattern to action.

    Examples:
        >>> register()["recipe.seed"]
        'refuse'
        >>> register()["context.time"]
        'record'
        >>> sorted(set(register().values()))
        ['record', 'refuse', 'warn']
    """
    if "register" not in _DATA:
        rows = csv.DictReader(io.StringIO(
            _data_text("register", f"v{REGISTER_VERSION}", "register.csv")))
        table = {}
        for row in rows:
            field, action = (row.get("field") or "").strip(), (row.get("action") or "").strip()
            if not field or action not in ("refuse", "warn", "record"):
                raise ReceiptError(f"register.csv row {row!r} has no field, or an action that "
                                   f"is not refuse, warn or record")
            table[field] = action
        if not table:
            raise ReceiptError("register.csv is empty, so every field would default to refuse")
        _DATA["register"] = table
    return dict(_DATA["register"])


def _patterns(table):
    """(collections, prefixes) derived from the register's patterns.

    A `*` in a pattern marks a keyed collection, so the path before it is walked key by key;
    every proper prefix of every pattern is a branch rather than a leaf. Derived from the
    register rather than listed, so a row added upstream is honoured without an edit here.
    """
    collections, prefixes = set(), set()
    for field in table:
        parts = field.split(".")
        for i, part in enumerate(parts):
            prefixes.add(".".join(parts[:i + 1]))
            if part == "*":
                collections.add(".".join(parts[:i]))
    return collections, prefixes


def _show(value) -> str:
    text = canonical(value).decode("utf-8")
    return text if len(text) <= 80 else text[:77] + "..."


def _diff(a, b, table) -> list:
    """Every field that differs between two receipts, before the actions are applied."""
    collections, prefixes = _patterns(table)
    found = []

    def keys(x):
        return list(x) if isinstance(x, dict) else []

    def walk(x, y, field, pattern, key):
        # A collection may be compared by its KEYS only when both sides are a collection:
        # a mapping, or absent. Anything else present -- a list, a string, a number -- has no
        # keys, so comparing key sets compares nothing and the answer comes back `identical`.
        #
        # This took three attempts, and the shape of the misses is the lesson. Round 1 closed
        # it for the branch arm. Round 2b found the collection arm, the sibling two lines up,
        # and `isinstance(x, dict) or isinstance(y, dict)` closed only the case where BOTH
        # sides were non-mappings. Round 3 found that one empty mapping is enough: `{}` versus
        # `["network"]` has three empty key sets, so all eleven patterns that are both a
        # collection and a leaf row were silent again, and `recipe.inputs` as a list was still
        # called `identical` by the same contract whose `recipe_id` refuses to hash it.
        #
        # Absent must stay collection-like, or a migrated receipt's absent `config` would be
        # reported as one whole-node difference instead of a difference per missing key, which
        # is what crate's `a migrated receipt` vector pins.
        def collectionish(v):
            return v is None or isinstance(v, dict)

        walkable = isinstance(x, dict) or isinstance(y, dict)
        if pattern in collections and collectionish(x) and collectionish(y):
            kx, ky = keys(x), keys(y)
            for k in sorted(set(kx) - set(ky)):
                found.append((field, pattern, f"{k} only in a", k))
            for k in sorted(set(ky) - set(kx)):
                found.append((field, pattern, f"{k} only in b", k))
            for k in [k for k in kx if k in set(ky)]:
                walk(x[k], y[k], f"{field}[{k}]", f"{pattern}.*", k)
        elif pattern in table or pattern not in prefixes or not walkable:
            # A leaf. Equality is "the same canonical JSON", so an absent member and a null
            # compare equal -- which is how JSON reads them, and how a receipt written with a
            # null reads back.
            if canonical(x) != canonical(y):
                found.append((field, pattern, f"{_show(x)} vs {_show(y)}", key))
        else:
            names = list(dict.fromkeys(keys(x) + keys(y)))
            if not names:
                # Neither side is an object at a node the register treats as a branch, so
                # there is nothing to walk into. Compare the nodes themselves: without this,
                # `output` as a string on both sides read `identical` however the two
                # differed, in the one function whose job is to refuse (round 1).
                if canonical(x) != canonical(y):
                    found.append((field, pattern, f"{_show(x)} vs {_show(y)}", key))
                return
            for name in names:
                walk(x.get(name) if isinstance(x, dict) else None,
                     y.get(name) if isinstance(y, dict) else None,
                     f"{field}.{name}", f"{pattern}.{name}", key)

    for block in ("output", "recipe", "result", "context"):
        walk(a.get(block), b.get(block), block, block, None)
    return found


def _summary_tolerance(a, b, name):
    """The tolerance both receipts declare for a summary value, or None.

    Only when they agree: a tolerance that differs is its own refusal, and accepting one side's
    would let a build widen what counts as unchanged.
    """
    def declared(doc):
        tol = _mapping(_mapping(_mapping(doc, "result"), "tolerance"), "summary")
        return tol.get(name) if isinstance(tol, dict) else None

    ta, tb = declared(a), declared(b)
    if ta is None or canonical(ta) != canonical(tb):
        return None
    if isinstance(ta, bool) or not isinstance(ta, (int, float)):
        # The schema types a tolerance as a power of ten, but `read` validates nothing, so a
        # hand-edited receipt reaches here. Comparing against it would raise a TypeError out
        # of an API that reports everything else malformed as a ReceiptError (round 1).
        return None
    return ta


def compare(a, b, overrides=None) -> Comparison:
    """Compare two receipts: `identical`, `equivalent` or `different`, and what differed.

    Any `refuse` makes it `different`; failing that, any `within` makes it `equivalent`; a
    `warn` or a `record` never changes the verdict, so two receipts that differ only in when
    and where they were built are `identical` with the difference still listed.

    `overrides` may change a field's action, under crate's rule: known fields only, an action
    of refuse, warn or record, and **no `recipe.*` field** -- every recipe field refuses
    because `recipe_id` covers it, and relaxing one would publish two different recipes as one.
    The result names the register version it read and each action an override changed.

    A null `recipe_id` on either side always refuses: a migrated receipt holds no recipe
    identity, so neither side can vouch for a recipe it does not have.

    Examples:
        >>> one = {"output": {}, "recipe": {}, "result": {}, "context": {"time": "t"}}
        >>> compare(one, one).verdict
        'identical'
        >>> other = {**one, "context": {"time": "later"}}
        >>> c = compare(one, other)
        >>> c.verdict, c.fields
        ('identical', [('context.time', 'record')])
        >>> compare(one, {**one, "recipe": {"seed": 1}}).verdict
        'different'
        >>> c = compare(one, other, {"context.time": "refuse", "context.host": "record"})
        >>> c.verdict, c.register, c.overrides
        ('different', '1.0.0', (('context.time', 'refuse'),))
    """
    for name, doc in (("a", a), ("b", b)):
        if not isinstance(doc, dict):
            raise ReceiptError(f"receipt {name} is not a JSON object, got "
                               f"{type(doc).__name__}")
    table = register()
    changed = {}
    if overrides is not None and not isinstance(overrides, dict):
        raise ReceiptError(f"overrides maps a register field to an action, got "
                           f"{type(overrides).__name__}")
    if overrides:
        for field, action in overrides.items():
            if field not in table:
                raise ReceiptError(f"override names {field!r}, which the register does not "
                                   f"have")
            if action not in ("refuse", "warn", "record"):
                raise ReceiptError(f"override for {field!r} is {action!r}; one of refuse, "
                                   f"warn, record")
            if field.startswith("recipe."):
                raise ReceiptError(f"{field!r} cannot be overridden: every recipe field "
                                   f"refuses, because recipe_id covers it")
            if table[field] != action:
                changed[field] = action
            table[field] = action

    rows = [{"field": f, "pattern": p, "detail": d, "key": k,
             "action": table.get(p, "refuse")} for f, p, d, k in _diff(a, b, table)]

    # A migrated receipt: one refusal at recipe.recipe_id whatever the walk said, because a
    # null id is not a value that can agree with anything.
    missing_id = [s for s, doc in (("a", a), ("b", b))
                  if _mapping(doc, "recipe").get("recipe_id", "absent") is None]
    if missing_id:
        rows = [r_ for r_ in rows if r_["pattern"] != "recipe.recipe_id"]
        rows.append({"field": "recipe.recipe_id", "pattern": "recipe.recipe_id",
                     "action": "refuse", "key": None,
                     "detail": f"recipe unknown: {' and '.join(missing_id)} holds no recipe "
                               f"identity (a migrated receipt)"})

    for row in rows:
        if row["pattern"] == "result.summary.*":
            tol = _summary_tolerance(a, b, row["key"])
            va = _mapping(_mapping(a, "result"), "summary").get(row["key"])
            vb = _mapping(_mapping(b, "result"), "summary").get(row["key"])
            numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool)
                          for v in (va, vb))
            if tol is not None and numbers and abs(va - vb) <= tol:
                row["action"] = "within"
                row["detail"] += f"; within {_show(tol)}"
        elif row["pattern"] == "result.fingerprint.*.sha256":
            # Settling this as `within` needs both builds' tables re-read, which this mode does
            # not take. Said in the detail rather than left looking like a plain refusal.
            row["detail"] = "fingerprints differ (receipts only): " + row["detail"]

    # After the fingerprint rows are settled, because a part is vouched for by its table.
    def table_agrees(name):
        if name is None:
            return False
        for doc in (a, b):
            if name not in _mapping(_mapping(doc, "result"), "fingerprint"):
                return False
        return all(row["action"] == "within" for row in rows
                   if row["key"] == name
                   and row["pattern"].startswith("result.fingerprint.*."))

    for row in rows:
        if row["pattern"] not in ("result.parts.*.bytes", "result.parts.*.sha256"):
            continue
        part = row["key"]
        names = [_mapping(_mapping(_mapping(doc, "result"), "parts"), part).get("table")
                 for doc in (a, b)]
        if names[0] is not None and names[0] == names[1] and table_agrees(names[0]):
            row["action"] = "within"
            row["detail"] += f"; table {names[0]} agrees"
        elif names[0] is None or names[0] != names[1]:
            row["detail"] += "; the file names no table that could vouch for it"
        else:
            row["detail"] += f"; table {names[0]} does not agree"

    actions = {row["action"] for row in rows}
    verdict = "different" if "refuse" in actions else \
        "equivalent" if "within" in actions else "identical"
    differences = tuple(
        Difference(side=row["pattern"].split(".")[0], field=row["field"],
                   action=row["action"], detail=row["detail"])
        for row in sorted(rows, key=lambda row: (row["field"].encode("utf-8"),
                                                 row["action"])))
    return Comparison(verdict=verdict, mode=MODE, differences=differences,
                      register=REGISTER_VERSION,
                      overrides=tuple(sorted(changed.items(),
                                             key=lambda pair: pair[0].encode("utf-8"))))


# =============================================================================
# The STAC side -- the identity fields an item mirrors
# =============================================================================

# The two standard extensions whose fields the mapping table uses. An item that emits
# `file:*` or `processing:*` without listing these is non-conformant, and the receipt field
# schema cannot notice: it constrains only `receipt:`-prefixed keys.
FILE_EXTENSION_URL = "https://stac-extensions.github.io/file/v2.1.0/schema.json"
PROCESSING_EXTENSION_URL = "https://stac-extensions.github.io/processing/v1.2.0/schema.json"

# `file:checksum` is a multihash, not a bare digest: 0x12 names sha2-256 and 0x20 its 32-byte
# length, so a sha256 is published as `1220` followed by the 64 hex digits.
MULTIHASH_SHA256 = "1220"

# Used with `fullmatch` only, through the three predicates below, and written with `[0-9]`:
# `$` under `match` also matches before a trailing newline, and `\d` matches every Unicode
# digit, so `^\d{4}...$` let "2026-11-08T00:00:00Z\n" and Arabic-Indic digits into an item.
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_MULTIHASH_SHA256 = re.compile(r"1220[0-9a-f]{64}")
_UTC_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z")
_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

# Every code `stac_fields` refuses with: the mapping's own, tabled in the README vendored
# beside its vectors (`tests/vectors/receipt/mapping/`). A test holds this list, the codes the
# vectors expect and the codes this file raises to one set.
STAC_REFUSALS = (
    "block_not_object", "receipt_version_unknown",
    "recipe_id_missing", "recipe_id_on_migrated", "recipe_id_not_sha256",
    "time_not_utc", "version_not_string", "repo_name_empty",
    "href_not_a_part", "part_sha256_not_sha256", "bytes_not_whole",
    "receipt_asset_not_string", "receipt_asset_empty", "receipt_asset_in_assets",
    "receipt_asset_without_digest", "digest_without_receipt_asset", "digest_not_sha256",
)


def _is_sha256(value) -> bool:
    """Exactly 64 lower-case ASCII hex digits."""
    return isinstance(value, str) and _SHA256_HEX.fullmatch(value) is not None


def _is_multihash_sha256(value) -> bool:
    return isinstance(value, str) and _MULTIHASH_SHA256.fullmatch(value) is not None


def _utc_instant(value) -> bool:
    """Whether `value` is the form's UTC spelling AND an instant that exists.

    The pattern alone admits month 13, the 31st of November and hour 24, and the processing
    extension declares `processing:datetime` as a `date-time`, which none of those is. A leap
    second (`:60`) is refused with them, as the mapping refuses it.

    Examples:
        >>> _utc_instant("2024-02-29T23:59:59Z"), _utc_instant("2026-02-29T00:00:00Z")
        (True, False)
        >>> _utc_instant("2026-11-08T00:00:00.25Z"), _utc_instant("2026-11-08T24:00:00Z")
        (True, False)
        >>> _utc_instant("2026-11-08T00:00:00Z" + chr(10))    # a trailing newline
        False
    """
    if not isinstance(value, str) or _UTC_TIME.fullmatch(value) is None:
        return False
    year, month, day = int(value[0:4]), int(value[5:7]), int(value[8:10])
    hour, minute, second = int(value[11:13]), int(value[14:16]), int(value[17:19])
    if not 1 <= month <= 12:
        return False
    leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
    last = 29 if month == 2 and leap else _DAYS_IN_MONTH[month - 1]
    return 1 <= day <= last and hour <= 23 and minute <= 59 and second <= 59

# The asset that links the receipt: role `metadata`, as for every other output.
RECEIPT_ROLE = "metadata"

# What a catalogue that declares `require_receipt` says of an item that links a receipt and
# carries no `receipt:recipe_id`. One sentence, used by the audit and by `verify`, so the two
# cannot describe one item two ways (#17). The item may come from a migrated receipt, whose
# mapping leaves the identity out, or from a build that dropped it: the item alone cannot tell
# which, and neither lets `verify` tell a rebuilt item from a changed one.
NO_RECIPE_IDENTITY = ("links a receipt but carries no recipe identity: a migrated receipt, "
                      "which require_receipt does not admit, or a build that dropped it")


def multihash(sha256_hex: str) -> str:
    """A sha256 hex digest as the multihash `file:checksum` publishes.

    Examples:
        >>> multihash("0" * 64)[:8]
        '12200000'
        >>> len(multihash("0" * 64))
        68
    """
    if not _is_sha256(sha256_hex):
        raise ReceiptError(f"a sha256 is 64 lowercase hex digits, got {sha256_hex!r}")
    return MULTIHASH_SHA256 + sha256_hex


def _whole(value, where: str, code=None) -> int:
    """`value` as a whole number of at least 0: a count of bytes. NaN and infinity are not
    whole, so `is_integer` refuses them with the fractions."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReceiptError(f"{where} is not a number: {value!r}", code=code)
    if isinstance(value, float) and not value.is_integer():
        raise ReceiptError(f"{where} is not whole: {value!r}", code=code)
    if value < 0:
        raise ReceiptError(f"{where} is negative: {value!r}", code=code)
    return int(value)


def _block(node: dict, key: str, where: str) -> dict:
    """`node[key]` for the mapping: `{}` when absent, refused when present but not an object.

    `null` included, which is what separates this from `_mapping`: there, "not an object" and
    "has no members" are one answer, and that is only safe where the caller's default is
    refusal. An item is published from what this returns, so a `recipe.code` that is null or a
    string must not read as "no repositories" and yield an item with no software and no error.
    """
    if key not in node:
        return {}
    value = node[key]
    if not isinstance(value, dict):
        raise ReceiptError(f"{where} is present but not an object, got "
                           f"{type(value).__name__}: it is never read as absent",
                           code="block_not_object")
    return value


def stac_fields(receipt, assets=None, receipt_asset=None, receipt_sha256=None) -> dict:
    """The receipt's identity fields, as an item mirrors them.

    `{"stac_extensions": [...], "properties": {...}, "assets": {...}}`, for a builder to merge
    into the item it is writing. The receipt itself stays the full record; these exist so a
    STAC client or a pgstac queryable needs no second fetch.

    `assets` maps an asset key to its href **relative to the item**, which is what a part is
    keyed by. A part no asset names is not mirrored, and two assets may name one part.
    `receipt_asset` names the asset that links the receipt, and `receipt_sha256` is the digest
    `write` returned for it -- nothing else can compute that one, because a receipt's own
    bytes are not inside it. The two come together or not at all, and that asset carries
    `file:checksum` with no `file:size`.

    This executes the `STAC item` rows of crate's mapping at `MAPPING_VERSION`, and crate's
    vectors for those rows run against it. It checks the values it publishes and what decides
    them -- the form version, whether the receipt was migrated, `recipe_id` and
    `context.time` -- and refuses with a `ReceiptError` whose `code` is one of
    `STAC_REFUSALS`. Two refusals carry no code, because the contract names none for them:
    an `assets` that is not a mapping, and an href that is not a string. It does not validate
    the rest of the receipt; `validate` does that.

    A block or entry that is present but not an object is refused, `null` included: it is
    never read as absent. A migrated receipt (`output.migrated_from`) has no recipe identity,
    so `receipt:recipe_id` is **left out** rather than published as a null; a `recipe_id`
    missing on any other receipt is refused, because its item would read as migrated.

    Examples:
        >>> r = {"output": {"receipt_version": "1.0.0"},
        ...      "recipe": {"recipe_id": "a" * 64,
        ...                 "code": {"stacs": {"version": "0.2.0"}, "unversioned": {}}},
        ...      "result": {"parts": {"x.tif": {"sha256": "b" * 64, "bytes": 12}}},
        ...      "context": {"time": "2026-11-08T00:00:00Z"}}
        >>> fields = stac_fields(r, assets={"data": "x.tif"})
        >>> sorted(fields["properties"])
        ['processing:datetime', 'processing:software', 'receipt:recipe_id']
        >>> fields["properties"]["processing:software"]
        {'stacs': '0.2.0'}
        >>> fields["assets"]["data"]["file:size"]
        12
        >>> fields["assets"]["data"]["file:checksum"][:4]
        '1220'

        An instant that does not exist is refused, by code:

        >>> try:
        ...     stac_fields({**r, "context": {"time": "2026-13-01T00:00:00Z"}})
        ... except ReceiptError as e:
        ...     e.code
        'time_not_utc'
    """
    if not isinstance(receipt, dict):
        raise ReceiptError(f"a receipt is a JSON object, got {type(receipt).__name__}",
                           code="block_not_object")
    if assets is not None and not isinstance(assets, dict):
        # A public parameter, so a caller's mistake reaches here. Everything else malformed in
        # this module is a ReceiptError; `.items()` on a string would be an AttributeError
        # naming neither the parameter nor the type (enumeration, mechanism D). No code: the
        # mapping's vectors always pass a mapping, so the contract names no refusal for this.
        raise ReceiptError(f"assets maps an asset key to its href, got "
                           f"{type(assets).__name__}")
    assets = {} if assets is None else assets

    # The two arguments that describe the receipt's own asset come as a pair or not at all.
    if receipt_asset is not None:
        if not isinstance(receipt_asset, str):
            raise ReceiptError(f"receipt_asset is an asset key, got "
                               f"{type(receipt_asset).__name__}",
                               code="receipt_asset_not_string")
        if receipt_asset == "":
            raise ReceiptError("receipt_asset is empty, and an asset needs a key",
                               code="receipt_asset_empty")
        if receipt_asset in assets:
            # It would replace that part's checksum and size with the receipt's own digest.
            raise ReceiptError(f"receipt_asset {receipt_asset!r} is also a key of assets: the "
                               f"receipt is not one of its own parts",
                               code="receipt_asset_in_assets")
        if receipt_sha256 is None:
            raise ReceiptError(f"receipt_asset {receipt_asset!r} needs receipt_sha256, the "
                               f"digest `write` returned for the bytes it wrote",
                               code="receipt_asset_without_digest")
    elif receipt_sha256 is not None:
        # Ignoring it would return an item with no link to the receipt it was given.
        raise ReceiptError("receipt_sha256 was given with no receipt_asset to carry it",
                           code="digest_without_receipt_asset")
    if receipt_sha256 is not None and not _is_sha256(receipt_sha256):
        raise ReceiptError(f"receipt_sha256 is not 64 lowercase hex: {receipt_sha256!r}",
                           code="digest_not_sha256")

    output = _block(receipt, "output", "receipt.output")
    recipe = _block(receipt, "recipe", "receipt.recipe")
    result = _block(receipt, "result", "receipt.result")
    context = _block(receipt, "context", "receipt.context")

    # The form decides what every other field means, so it is checked first.
    form = output.get("receipt_version")
    if not isinstance(form, str) or form != RECEIPT_VERSION:
        raise ReceiptError(f"output.receipt_version is {form!r}; mapping v{MAPPING_VERSION} "
                           f"reads receipt form {RECEIPT_VERSION!r}",
                           code="receipt_version_unknown")

    properties = {}
    # Only a migrated receipt has no recipe identity, and it never has one. By the PRESENCE of
    # `migrated_from`, as the form schema's `if` decides it.
    migrated = "migrated_from" in output
    recipe_identity = recipe.get("recipe_id")
    if recipe_identity is None:
        if not migrated:
            raise ReceiptError("recipe.recipe_id is null or missing on a receipt that was not "
                               "migrated: its item would read as one that was",
                               code="recipe_id_missing")
    else:
        if migrated:
            raise ReceiptError("recipe.recipe_id is set on a migrated receipt "
                               "(output.migrated_from), which holds no recipe identity",
                               code="recipe_id_on_migrated")
        if not _is_sha256(recipe_identity):
            raise ReceiptError(f"recipe.recipe_id is not 64 lowercase hex: "
                               f"{recipe_identity!r}", code="recipe_id_not_sha256")
        properties["receipt:recipe_id"] = recipe_identity

    time = context.get("time")
    if not _utc_instant(time):
        raise ReceiptError(f"context.time is required and must be a real ISO 8601 UTC "
                           f"instant: {time!r}", code="time_not_utc")
    properties["processing:datetime"] = time

    software = {}
    code_block = _block(recipe, "code", "recipe.code")
    for repo in code_block:
        if repo == "":
            raise ReceiptError("recipe.code has a repository with an empty name, which would "
                               "key processing:software", code="repo_name_empty")
        version = _block(code_block, repo, f"recipe.code[{repo}]").get("version")
        if version is None:
            continue    # no version to publish: left out, and with none the property is
        if not isinstance(version, str) or not version:
            raise ReceiptError(f"recipe.code[{repo}].version is not a non-empty string: "
                               f"{version!r}", code="version_not_string")
        software[repo] = version
    if software:
        properties["processing:software"] = software

    out_assets = {}
    parts = _block(result, "parts", "result.parts")
    for key, href in assets.items():
        if not isinstance(href, str):
            # An href is used as a key into `result.parts`, so a list or a dict raises
            # `TypeError: unhashable type` rather than refusing (round 2b). A value consumed
            # as a dict KEY is the same family as a member read as a mapping, and the
            # enumeration's population did not include it. No code, as for `assets` above:
            # the mapping's vectors never pass one.
            raise ReceiptError(f"asset {key!r} href must be a string, got "
                               f"{type(href).__name__}")
        if href not in parts:
            # Guessing would publish another file's digest under this asset.
            raise ReceiptError(f"asset {key!r} has href {href!r}, which is not a part of this "
                               f"receipt; parts are keyed by the href relative to the item",
                               code="href_not_a_part")
        part = _block(parts, href, f"result.parts[{href}]")
        if not _is_sha256(part.get("sha256")):
            raise ReceiptError(f"result.parts[{href}].sha256 is not 64 lowercase hex: "
                               f"{part.get('sha256')!r}", code="part_sha256_not_sha256")
        out_assets[key] = {"file:checksum": multihash(part["sha256"]),
                           "file:size": _whole(part.get("bytes"),
                                               f"result.parts[{href}].bytes",
                                               code="bytes_not_whole")}
    if receipt_asset is not None:
        # The digest of the published receipt's bytes, never from a part, and no `file:size`:
        # the digest identifies the bytes.
        out_assets[receipt_asset] = {"file:checksum": multihash(receipt_sha256)}

    # In the order crate's example item lists them. `processing` is always here, because
    # `context.time` is required; the other two only when their fields are.
    extensions = []
    if out_assets:
        extensions.append(FILE_EXTENSION_URL)
    extensions.append(PROCESSING_EXTENSION_URL)
    if "receipt:recipe_id" in properties:
        extensions.append(EXTENSION_URL)
    return {"stac_extensions": extensions, "properties": properties, "assets": out_assets}


def receipt_asset(item):
    """The asset that links an item's receipt, or None.

    The contract is the asset link, not a filename: the receipt is published beside the item
    "as an asset with role `metadata`". A catalogue that publishes under a `receipts/` prefix
    would break a `receipt.json`-beside-the-item assumption silently.

    THE ONE PRODUCER of that answer. `receipt_href`, `item_problems` and `item_verdict` all
    come through here, because they have to agree about which asset it is: a second loop that
    kept the LAST match instead of the first reported an item as `inconsistent` whenever it
    carried another `metadata` JSON asset -- a QA report, a legacy manifest -- and that is
    good input (round 1).

    The first match wins, and it must satisfy every condition: a non-empty href, role
    `metadata`, type `application/json`.
    """
    if not isinstance(item, dict):
        return None
    for asset in _mapping(item, "assets").values():
        if not isinstance(asset, dict):
            continue
        href = asset.get("href")
        if RECEIPT_ROLE in _list(asset, "roles") \
                and asset.get("type") == "application/json" \
                and isinstance(href, str) and href:
            return asset
    return None


def receipt_href(item):
    """The href of the asset that links an item's receipt, or None."""
    asset = receipt_asset(item)
    return None if asset is None else asset["href"]


def item_problems(item) -> list:
    """Everything wrong with an item's receipt fields, as a list of sentences.

    Collected rather than raised one at a time: an item is usually wrong in one way that shows
    up in three fields, and the set is the diagnosis. An empty list is the pass.

    Three layers, because no single one covers it:

    - the vendored field schema, which constrains `stac_extensions`, `type` and
      `receipt:recipe_id` and refuses any other `receipt:`-prefixed key;
    - the formats it cannot reach -- a `file:checksum` multihash and a `processing:datetime` --
      because the `file` and `processing` schemas are fetched by URL and the suite is offline;
    - the links the contract requires: each extension whose fields are present, and the asset
      that carries the receipt.

    It is the check for a catalogue that declares `require_receipt`, which admits only items
    that carry a recipe identity: an item built from a migrated receipt carries none, and is
    reported here as having no `receipt:recipe_id`.
    """
    import jsonschema

    if not isinstance(item, dict):
        return [f"not a JSON object: {type(item).__name__}"]
    problems = []
    properties = _mapping(item, "properties")
    # A non-list is reported by the field schema ("is not of type 'array'"), so it is only
    # read as empty here, never reported twice.
    extensions = _list(item, "stac_extensions")
    assets = _mapping(item, "assets")

    identity = properties.get("receipt:recipe_id")
    if identity is None:
        problems.append("properties has no receipt:recipe_id")
    elif not _is_sha256(identity):
        problems.append(f"receipt:recipe_id is not 64 lowercase hex: {identity!r}")

    for error in sorted(jsonschema.Draft7Validator(stac_schema()).iter_errors(item),
                        key=lambda e: list(e.absolute_path)):
        # The field schema's `oneOf` (an Item or a Collection) makes jsonschema report the
        # whole document as "not valid under any of the given schemas" and put the useful
        # message in `context`. An operator acts on the message, so descend to the best one --
        # after dropping each branch's own `type` selector, which is how the branch that does
        # not apply says so ("'Collection' was expected" about an Item). `best_match` prefers
        # it otherwise, being the shallower error.
        if error.context:
            branch = [e for e in error.context if list(e.absolute_path) != ["type"]]
            error = jsonschema.exceptions.best_match(branch or error.context) or error
        where = ".".join(str(p) for p in error.absolute_path) or "<item>"
        problems.append(f"{where}: {error.message}")

    time = properties.get("processing:datetime")
    if time is not None and not _utc_instant(time):
        problems.append(f"processing:datetime is not a real ISO 8601 UTC instant: {time!r}")
    if ("processing:datetime" in properties or "processing:software" in properties) \
            and PROCESSING_EXTENSION_URL not in extensions:
        problems.append(f"stac_extensions does not list {PROCESSING_EXTENSION_URL}, and the "
                        f"item carries processing: fields")

    file_fields = False
    for key, asset in assets.items():
        if not isinstance(asset, dict):
            problems.append(f"asset {key!r} is not an object")
            continue
        if "roles" in asset and not isinstance(asset["roles"], list):
            # The field schema does not constrain `roles`, so nothing else would say so, and
            # `receipt_asset` reads such an asset as linking nothing.
            problems.append(f"asset {key!r} roles is not a list")
        if "file:checksum" in asset or "file:size" in asset:
            file_fields = True
        checksum = asset.get("file:checksum")
        if checksum is not None and not _is_multihash_sha256(checksum):
            problems.append(f"asset {key!r} file:checksum is not a sha2-256 multihash "
                            f"(1220 + 64 hex): {checksum!r}")
        size = asset.get("file:size")
        if size is not None:
            try:
                _whole(size, f"asset {key!r} file:size")
            except ReceiptError as e:
                problems.append(str(e))
    if file_fields and FILE_EXTENSION_URL not in extensions:
        problems.append(f"stac_extensions does not list {FILE_EXTENSION_URL}, and the item "
                        f"carries file: fields")

    if receipt_href(item) is None:
        problems.append(f"no asset links the receipt (role {RECEIPT_ROLE!r}, type "
                        f"application/json)")
    return problems


# =============================================================================
# One item's verdict -- stacs' ladder, NOT crate's
# =============================================================================

# Deliberately not `identical` / `equivalent` / `different`. Those are `compare`'s, for two
# receipts, and crate's register decides them. Here there is one receipt and a five-field
# projection of it on each side, where four of those fields `refuse` and the fifth is `record`
# -- so crate's `equivalent` is unreachable and its `identical` would have to cover a rebuild.
# Borrowing the words would make a stacs verdict read as a crate verdict and mean something
# else, which is worse than having four words of our own.
ITEM_VERDICTS = ("same", "rebuilt", "changed", "inconsistent")

# Every node `item_verdict` consults. Named here so the post-condition over it can enumerate
# the code's own list instead of restating it: a second list would be the "two lists that
# happen to agree" shape, which is how three of this branch's defects reached review.
#
# Fixed nodes only. Each ENTRY of `published.assets` and `served.assets` is consulted too, and
# has its own check in `item_verdict` and its own test, because its key is the item's (#17).
VERDICT_NODES = ("receipt.recipe", "receipt.context", "receipt.result",
                 "receipt.result.parts", "published.assets", "served.assets",
                 "published.properties", "served.properties")

# The mirrored fields, and whether a difference in one means the recipe moved or only the
# bytes. `receipt:recipe_id` is the recipe; the rest are what the recipe produced.
_IDENTITY_PROPERTY = "receipt:recipe_id"
_MIRRORED_PROPERTIES = (_IDENTITY_PROPERTY, "processing:datetime", "processing:software")
_RESULT_ASSET_FIELDS = ("file:checksum", "file:size")


@dataclass(frozen=True)
class ItemVerdict:
    """What a receipt says about one item whose published and served bodies differ.

    - `same`: every mirrored field agrees on both sides and with the receipt, so whatever
      changed in the body is outside what the receipt describes -- a bbox correction, a link.
    - `rebuilt`: the recipe is the same on both sides and a result field moved, so the item
      was built again from the same inputs.
    - `changed`: the recipe itself differs between the two sides.
    - `inconsistent`: the item's provenance could not be established -- it disagrees with
      the receipt it links (in either direction: a mirrored field that differs, or one the
      item publishes and the receipt does not produce), an asset entry on either side is not
      an object, that receipt could not be read or maps to no item fields (`stac_fields`
      refuses it), or it links none at all. One
      category because they have one consequence; the notes say which it was. Never reported
      as agreement.
    """
    verdict: str
    fields: tuple
    notes: tuple

    @property
    def ok(self) -> bool:
        """`same` is the only verdict that is not drift on this axis."""
        return self.verdict == "same"


def _remove_dots(path):
    """`path` with its `.` and `..` segments removed, as RFC 3986 section 5.2.4 removes them.

    A `..` at the root of an absolute path stays at the root, as the RFC has it
    (`/../c/x.tif` is `/c/x.tif`). A relative path has no root, so a `..` that climbs past
    its start leaves the item's directory, and the answer is None.

    Only dot segments: `posixpath.normpath` also collapses `//` and drops a trailing `/`, and
    on an object store `a//b.tif` and `x.tif/` are other keys than `a/b.tif` and `x.tif`,
    so an asset was compared with a part it does not name (round 2).
    """
    segments = path.split("/")
    out = []
    for i, segment in enumerate(segments):
        last = i == len(segments) - 1
        if segment in (".", ".."):
            if segment == "..":
                if not out:
                    return None
                if out != [""]:
                    out.pop()
            if last:
                out.append("")      # `a/.` and `a/b/..` name the directory, `a/`
            continue
        out.append(segment)
    return "/".join(out)


def _inside(path):
    """`path`, its dot segments removed, when it is relative and names something inside the
    item's directory; else None."""
    if path.startswith("/"):
        return None
    path = _remove_dots(path)
    return path or None


# The ports a URL leaves out, so `https://h:443/x` and `https://h/x` are one origin.
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(split, scheme=None):
    """`(scheme, host, port)` of a split URL, the scheme's default port filled in.

    `scheme` stands in for a network-path reference's (`//host/x`), which takes the item's.
    Raises ValueError on a port that is out of range or not a number, which `urlsplit` itself
    accepts. Userinfo is not part of it: it names who asks, not what is fetched.
    """
    scheme = (scheme or split.scheme).lower()
    port = split.port
    return scheme, split.hostname or "", _DEFAULT_PORTS.get(scheme) if port is None else port


def _rewritten_by_a_parser(href):
    """Whether a URL parser would change `href` before reading it.

    `urlsplit` deletes tab, CR and LF anywhere and strips control characters and spaces at
    the ends, and `urldefrag` re-serialised an href only when it held a `#`, so `x\t.tif`
    named no part and `x\t.tif#b` named `x.tif` (round 3). No URL reference holds these, so
    such an href is malformed rather than read as some other spelling.
    """
    return any(ord(c) < 0x20 or c == "\x7f" for c in href) or href != href.strip(" ")


def _relative_href(href, item_url):
    """`(path, problem)`: an asset href as a path relative to the item's directory.

    `path` is None when the href names nothing inside that directory. `problem` is
    "malformed" for an href no URL parser reads as written (an unclosed IPv6 host, a port
    that is not one, a tab or a newline), "absolute" when it was only for want of the item's
    URL, and None otherwise. The contract keys a part by the href relative to the item, and
    the same file is spelled many ways: `./x.tif`, `sub/../x.tif`, `x.tif#band`, or absolute,
    which is how many catalogues publish (#17).

    A fragment never names another file, so it is cut off. A query may select another
    representation, so an href with one names no part. Dot segments, and only those, are
    removed (`_remove_dots`) on every route: the RFC 3986 merge of a reference with the item's
    URL is done here rather than by `urljoin`, which collapses `//` in the path it merges and
    in the base, so a climbing href and a plain one named different parts (round 3). Two
    URLs share an origin when scheme, host and port agree, case-insensitively and with the
    default port filled in. Percent-encoding is not decoded: a part key is the path verbatim.

    Never raises on a string: `urlsplit` raises ValueError on what it cannot read, and
    `verify` reads published bodies with no audit in front of it, so one such href would end
    the run naming no item (round 1).
    """
    if _rewritten_by_a_parser(href):
        return None, "malformed"
    href = href.partition("#")[0]
    if "?" in href:
        return None, None
    try:
        split = urllib.parse.urlsplit(href)
        _origin(split)          # a port that is not one fails here, with or without item_url
    except ValueError:
        return None, "malformed"
    absolute = bool(split.scheme or split.netloc or href.startswith("/"))
    if not absolute:
        path = _inside(href)
        if path is not None:
            return path, None
        # A relative href that climbs may come back in (`../c/x.tif`), which only the item's
        # URL can tell.
    if item_url is None:
        return None, "absolute" if absolute else None
    base = urllib.parse.urlsplit(item_url)      # `item_verdict` has refused one that fails
    directory = base.path[:base.path.rfind("/") + 1] or "/"
    if split.scheme or split.netloc:
        # The port was read above, so this cannot raise.
        if _origin(split, None if split.scheme else base.scheme) != _origin(base):
            return None, None
        path = split.path
    elif href.startswith("/"):
        path = href
    else:
        path = directory + href                 # RFC 3986 section 5.2.3, the merge
    # Dot segments removed from both before the prefix test, so `/c/../c/x.tif` is under
    # `/c/`; the directory ends in `/`, so `/cat/x.tif` is not under `/c/`.
    path, directory = _remove_dots(path), _remove_dots(directory)
    if path is None or directory is None or not path.startswith(directory):
        return None, None
    return _inside(path[len(directory):]), None


def _part_key(href, parts, item_url):
    """`(key, problem)`: the part of `parts` an asset href names.

    The exact spelling first, which is unambiguous and is what the mapping itself looks up.
    Otherwise the href and every part key are normalised the same way, and a match is taken
    only if it is the only one: two part keys spelling one file (`./x.tif`, `sub/../x.tif`)
    would otherwise be compared in whichever order the receipt listed them. `problem` is
    "ambiguous", "malformed", "absolute" (no item URL to resolve it against), or None.
    """
    if href in parts:
        return href, None
    path, problem = _relative_href(href, item_url)
    if path is None:
        return None, problem
    hits = [k for k in parts if isinstance(k, str) and _inside(k) == path]
    if len(hits) > 1:
        return None, "ambiguous"
    return (hits[0] if hits else None), None


def _mirrored(item) -> dict:
    """The mirrored identity fields of an item, flattened to one comparable mapping."""
    out = {}
    properties = _mapping(item, "properties")
    for key in _MIRRORED_PROPERTIES:
        if key in properties:
            out[f"properties.{key}"] = properties[key]
    for key, asset in _mapping(item, "assets").items():
        if not isinstance(asset, dict):
            continue
        for field_name in _RESULT_ASSET_FIELDS:
            if field_name in asset:
                out[f"assets[{key}].{field_name}"] = asset[field_name]
    return out


def item_verdict(published, served, receipt, receipt_sha256=None,
                 item_url=None) -> ItemVerdict:
    """Compare an item's published and served bodies through the receipt it links.

    `receipt_sha256` is the digest of the receipt bytes as fetched. Given, it is checked
    against the published item's receipt asset, which is the only way to tell that the receipt
    read is the one the item claims -- a receipt fetched by a filename convention could belong
    to anything.

    The receipt is what makes this more than a field diff: an item whose mirrored fields do not
    match the receipt beside it is `inconsistent` whatever the two sides agree on. It is held
    to the receipt in both directions: a mirrored field the published item carries must be one
    the receipt's mapping produces, with the same value. A field it leaves out is not a
    disagreement, because the field schema makes each one optional. Only the published item
    is held to the receipt, because it is the published item's receipt; a served item that
    names another recipe reads `changed`.

    `item_url` is the published item's own URL. An asset names a part by its href relative
    to the item, so an absolute href is made relative against it; without it, an absolute
    href is matched to no part and the notes say so. A relative href is normalised either way
    (`./x.tif` names part `x.tif`). An asset that carries `file:checksum` or `file:size` and
    no href claims a file it does not name, and is a disagreement.

    Examples:
        >>> item = {"properties": {"receipt:recipe_id": "a" * 64}}
        >>> r = {"output": {"receipt_version": "1.0.0"}, "recipe": {"recipe_id": "a" * 64},
        ...      "result": {}, "context": {"time": "2026-11-08T00:00:00Z"}}
        >>> item_verdict(item, item, r).verdict
        'same'
        >>> moved = {"properties": {"receipt:recipe_id": "b" * 64}}
        >>> item_verdict(item, moved, r).verdict
        'changed'
    """
    for name, doc in (("published", published), ("served", served)):
        if not isinstance(doc, dict):
            raise ReceiptError(f"the {name} item is not a JSON object, got "
                               f"{type(doc).__name__}")
    if item_url is not None and not isinstance(item_url, str):
        raise ReceiptError(f"item_url is the published item's URL, got "
                           f"{type(item_url).__name__}")
    if item_url is not None:
        try:
            _origin(urllib.parse.urlsplit(item_url))
        except ValueError as e:
            # A ReceiptError, which `verify` turns into this item's `inconsistent`; a
            # ValueError would end the run (round 1).
            raise ReceiptError(f"item_url {item_url!r} is not a URL: {e}") from None
    if not isinstance(receipt, dict):
        # The mapping refuses this as `block_not_object`, and so it is the same verdict as
        # every other receipt the mapping refuses. Without it, `receipt.get` below raised
        # AttributeError: the one argument of the three that was read unguarded.
        return ItemVerdict("inconsistent", ("receipt",),
                           (f"the receipt it links maps to no item fields "
                            f"(block_not_object): a receipt is a JSON object, got "
                            f"{type(receipt).__name__}",))
    notes = []

    # Nodes this verdict depends on. `_mapping` turns a present non-mapping into `{}`, which
    # stops a crash and makes every check below find nothing to disagree with -- so the answer
    # was `same`, with `ok` true, for an item that contradicted its receipt (round 3). The
    # mechanism round 3 named: "not a mapping" and "has no members" are one fact in the code,
    # and that collapse is only safe where the consumer's default is refusal. Here it is
    # agreement, so it has to be separated.
    nodes = (
        # A garbage `recipe` or `context` means `stac_fields` claims nothing, so nothing can
        # disagree with it -- round 3's list of agreement-default sites named `stac_fields`
        # silently dropping them.
        ("receipt.recipe", receipt.get("recipe")),
        ("receipt.context", receipt.get("context")),
        ("receipt.result", receipt.get("result")),
        ("receipt.result.parts", _mapping(receipt, "result").get("parts")),
        ("published.assets", published.get("assets")),
        ("served.assets", served.get("assets")),
        ("published.properties", published.get("properties")),
        ("served.properties", served.get("properties")),
    )
    malformed = [where for where, node in nodes
                 if node is not None and not isinstance(node, dict)]
    # Each asset ENTRY, on both sides, and `null` with the rest: an entry is the item's own
    # object, never an optional node, and skipping one compared nothing and read `same` (#17).
    # An entry the receipt does not describe -- a thumbnail -- included: its provenance
    # cannot be established either, and the verdict is about the item.
    for side, doc in (("published", published), ("served", served)):
        malformed += [f"{side}.assets[{key}]" for key, asset in _mapping(doc, "assets").items()
                      if not isinstance(asset, dict)]
    if malformed:
        return ItemVerdict("inconsistent", tuple(malformed),
                           (f"{len(malformed)} node(s) the comparison needs are present but "
                            f"not objects, so provenance cannot be established: "
                            f"{', '.join(malformed)}",))

    if receipt_sha256 is not None:
        linked = receipt_asset(published)
        asset_digest = None if linked is None else linked.get("file:checksum")
        want = multihash(receipt_sha256)
        if asset_digest is not None and asset_digest != want:
            return ItemVerdict("inconsistent", ("assets[receipt].file:checksum",),
                               (f"the receipt fetched hashes to {want}, and the item's "
                                f"receipt asset claims {asset_digest}",))
        if asset_digest is None:
            notes.append("the item's receipt asset carries no file:checksum, so the receipt "
                         "read cannot be tied to it")

    # The published item against the receipt it links. A mirrored field is a copy of the
    # receipt, so a disagreement means one of the two was written by something that did not
    # read the other.
    #
    # BOTH halves of the mirrored set, not just the properties, and both from ONE producer:
    # `stac_fields`, given the assets of this item that name a part. A second copy of the
    # asset rows used to live here, and it drifted from the mapping twice. With no `assets=`
    # the claimed asset fields were always `{}`, so an item contradicting its receipt in
    # `file:checksum` and `file:size` read `same` (round 1). And a copy that consulted a part
    # only through whichever of those two fields the item happened to carry never saw a part
    # the mapping refuses -- a digest ending in a newline behind an asset that carried only a
    # size -- so that read `same` too.
    disagree = []
    named = {}
    parts = _mapping(_mapping(receipt, "result"), "parts")
    for key, asset in _mapping(published, "assets").items():
        href = asset.get("href")
        if href is not None and not isinstance(href, str):
            # Unhashable as a dict key, and the item is malformed either way. Recorded as a
            # disagreement rather than raised: `_receipt_verdicts` reads the published body
            # with no audit in front of it on the verify path, and one malformed item must
            # not end the run with a traceback (round 2b).
            disagree.append(f"assets[{key}].href")
            continue
        if not href:
            # No file named, so a digest or a size it carries is a claim about nothing that
            # can be checked; it used to be skipped and read `same` (#17).
            if any(f in asset for f in _RESULT_ASSET_FIELDS):
                disagree.append(f"assets[{key}].href")
            continue
        part, problem = _part_key(href, parts, item_url)
        if problem in ("ambiguous", "malformed"):
            disagree.append(f"assets[{key}].href")
        elif problem == "absolute":
            notes.append(f"asset {key!r} has an absolute href and no item URL was given, so "
                         f"it could not be matched to a part and was not compared")
        elif part is not None:
            named[key] = part
        # Otherwise not an output this receipt describes: an overview, a thumbnail, or the
        # receipt itself, whose own digest is checked above. Nothing to compare it with.
    try:
        claimed = stac_fields(receipt, assets=named)
    except ReceiptError as e:
        # A receipt the mapping refuses maps to no item fields, so there is nothing for the
        # item to agree with -- whether it refuses the receipt's own blocks or a part this
        # item names. Returned, not raised, and by the same word as the node check above:
        # that check reads an absent node and a null one alike, so without this a `recipe`
        # that is a string came back `inconsistent` while one that is null raised -- two
        # routes for one fact, in a function whose callers read only the verdict.
        return ItemVerdict("inconsistent", ("receipt",),
                           (f"the receipt it links maps to no item fields "
                            f"({e.code or 'refused'}): {e}",))

    properties = _mapping(published, "properties")
    # Both directions. A field the item publishes and the mapping does not produce is a claim
    # the receipt does not make -- a recipe identity over a migrated receipt, software over a
    # receipt with no versioned code -- and was read as agreement (#17). A field the item
    # leaves out is not: the field schema makes each one optional.
    for key in _MIRRORED_PROPERTIES:
        if key not in properties:
            continue
        if key not in claimed["properties"] \
                or canonical(properties[key]) != canonical(claimed["properties"][key]):
            disagree.append(f"properties.{key}")
    for key, want in claimed["assets"].items():
        asset = published["assets"][key]
        if "file:checksum" in asset and asset["file:checksum"] != want["file:checksum"]:
            disagree.append(f"assets[{key}].file:checksum")
        if "file:size" in asset:
            # As a whole number, never a double: `float(size)` raised OverflowError on an int
            # too large for one, and read 2**60 + 1 as 2**60 (#17). A receipt's `bytes` is
            # read by `load_json` as a double, so a true size above 2**53 that the receipt could
            # not spell exactly disagrees here -- the receipt does not hold that size.
            try:
                size_agrees = _whole(asset["file:size"], "file:size") == want["file:size"]
            except ReceiptError:
                size_agrees = False
            if not size_agrees:
                disagree.append(f"assets[{key}].file:size")

    if disagree:
        return ItemVerdict("inconsistent", tuple(sorted(disagree)),
                           ("the published item's fields differ from the receipt it links",))

    a, b = _mirrored(published), _mirrored(served)
    differing = tuple(sorted(
        key for key in set(a) | set(b)
        if key not in a or key not in b or canonical(a[key]) != canonical(b[key])))
    if not differing:
        return ItemVerdict("same", (),
                           tuple(notes) + ("the body differs and the recipe does not: "
                                           "whatever changed is outside the receipt",))
    identity = f"properties.{_IDENTITY_PROPERTY}"
    if identity in differing:
        return ItemVerdict("changed", differing,
                           tuple(notes) + ("the two sides name different recipes",))
    return ItemVerdict("rebuilt", differing,
                       tuple(notes) + ("one recipe, different output: built again",))
