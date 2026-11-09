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

The contract is crate's, vendored under `data/receipt/` at a pinned tag and checked against it
in CI; crate's test vectors are the only thing keeping the two implementations in step.
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


class ReceiptError(ValueError):
    """A receipt, recipe or table that has no canonical form, or does not meet the contract.

    Raised with what was wrong and where, never with the value alone: a message naming the
    column or the member is the difference between a two-minute fix and a bisect.
    """


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
    """
    verdict: str
    mode: str
    differences: tuple

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
        rows = csv.DictReader(io.StringIO(_data_text("register.csv")))
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
    """
    for name, doc in (("a", a), ("b", b)):
        if not isinstance(doc, dict):
            raise ReceiptError(f"receipt {name} is not a JSON object, got "
                               f"{type(doc).__name__}")
    table = register()
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
    return Comparison(verdict=verdict, mode=MODE, differences=differences)


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

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_MULTIHASH_SHA256 = re.compile(r"^1220[0-9a-f]{64}$")
_UTC_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")

# The asset that links the receipt: role `metadata`, as for every other output.
RECEIPT_ROLE = "metadata"


def multihash(sha256_hex: str) -> str:
    """A sha256 hex digest as the multihash `file:checksum` publishes.

    Examples:
        >>> multihash("0" * 64)[:8]
        '12200000'
        >>> len(multihash("0" * 64))
        68
    """
    if not isinstance(sha256_hex, str) or not _SHA256_HEX.match(sha256_hex):
        raise ReceiptError(f"a sha256 is 64 lowercase hex digits, got {sha256_hex!r}")
    return MULTIHASH_SHA256 + sha256_hex


def _whole(value, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReceiptError(f"{where} is not a number: {value!r}")
    if isinstance(value, float) and not value.is_integer():
        raise ReceiptError(f"{where} is not whole: {value!r}")
    return int(value)


def stac_fields(receipt, assets=None, receipt_asset=None, receipt_sha256=None) -> dict:
    """The receipt's identity fields, as an item mirrors them.

    `{"stac_extensions": [...], "properties": {...}, "assets": {...}}`, for a builder to merge
    into the item it is writing. The receipt itself stays the full record; these exist so a
    STAC client or a pgstac queryable needs no second fetch.

    `assets` maps an asset key to its href **relative to the item**, which is what a part is
    keyed by. `receipt_asset` names the asset that links the receipt, and `receipt_sha256` is
    the digest `write` returned for it -- nothing else can compute that one, because a
    receipt's own bytes are not inside it.

    A migrated receipt has no recipe identity (`recipe_id` null), so the field is **left out**
    rather than published as a null, which the field schema would refuse anyway.

    Examples:
        >>> r = {"output": {}, "recipe": {"recipe_id": "a" * 64,
        ...                               "code": {"stacs": {"version": "0.2.0"}}},
        ...      "result": {"parts": {"x.tif": {"sha256": "b" * 64, "bytes": 12}}},
        ...      "context": {"time": "2026-11-08T00:00:00Z"}}
        >>> fields = stac_fields(r, assets={"data": "x.tif"})
        >>> sorted(fields["properties"])
        ['processing:datetime', 'processing:software', 'receipt:recipe_id']
        >>> fields["assets"]["data"]["file:size"]
        12
        >>> fields["assets"]["data"]["file:checksum"][:4]
        '1220'
    """
    if not isinstance(receipt, dict):
        raise ReceiptError(f"a receipt is a JSON object, got {type(receipt).__name__}")
    for where in ("recipe", "result", "context"):
        node = receipt.get(where)
        if node is not None and not isinstance(node, dict):
            # Symmetric with the `assets=` refusal below, which round 3 noted this disagreed
            # with: dropping a non-mapping block would publish an item with no provenance
            # fields and no error, which is the worst of both.
            raise ReceiptError(f"receipt.{where} is present but not an object, got "
                               f"{type(node).__name__}")
    if assets is not None and not isinstance(assets, dict):
        # A public parameter, so a caller's mistake reaches here. Everything else malformed in
        # this module is a ReceiptError; `.items()` on a string would be an AttributeError
        # naming neither the parameter nor the type (enumeration, mechanism D).
        raise ReceiptError(f"assets maps an asset key to its href, got "
                           f"{type(assets).__name__}")
    recipe = _mapping(receipt, "recipe")
    result = _mapping(receipt, "result")
    context = _mapping(receipt, "context")

    properties, extensions = {}, []
    recipe_identity = recipe.get("recipe_id")
    if recipe_identity is not None:
        if not isinstance(recipe_identity, str) or not _SHA256_HEX.match(recipe_identity):
            raise ReceiptError(f"recipe.recipe_id is not 64 lowercase hex: "
                               f"{recipe_identity!r}")
        properties["receipt:recipe_id"] = recipe_identity

    time = context.get("time")
    if time is not None:
        if not isinstance(time, str) or not _UTC_TIME.match(time):
            raise ReceiptError(f"context.time is not an ISO 8601 UTC instant: {time!r}")
        properties["processing:datetime"] = time
    # `_mapping`, not `or {}`: a truthy non-mapping survives `or {}` and `.items()` then
    # raises AttributeError. `item_verdict` calls this on a receipt that `read` never
    # validated, so it has to refuse a malformed `code` rather than crash on it. Found by
    # enumerating every member read after round 1, not by a reviewer.
    software = {repo: entry.get("version")
                for repo, entry in _mapping(recipe, "code").items()
                if isinstance(entry, dict) and entry.get("version") is not None}
    if software:
        properties["processing:software"] = software

    out_assets = {}
    parts = _mapping(result, "parts")
    for key, href in (assets or {}).items():
        if not isinstance(href, str):
            # An href is used as a key into `result.parts`, so a list or a dict raises
            # `TypeError: unhashable type` rather than refusing (round 2b). A value consumed
            # as a dict KEY is the same family as a member read as a mapping, and the
            # enumeration's population did not include it.
            raise ReceiptError(f"asset {key!r} href must be a string, got "
                               f"{type(href).__name__}")
        part = parts.get(href)
        if not isinstance(part, dict):
            # Guessing would publish another file's digest under this asset.
            raise ReceiptError(f"asset {key!r} has href {href!r}, which is not a part of this "
                               f"receipt; parts are keyed by the href relative to the item")
        out_assets[key] = {"file:checksum": multihash(part.get("sha256")),
                           "file:size": _whole(part.get("bytes"),
                                               f"result.parts[{href}].bytes")}
    if receipt_asset is not None:
        if receipt_sha256 is None:
            raise ReceiptError(f"receipt_asset {receipt_asset!r} needs receipt_sha256, the "
                               f"digest `write` returned for the bytes it wrote")
        out_assets[receipt_asset] = {"file:checksum": multihash(receipt_sha256)}

    # In the order crate's example item lists them, and only the ones whose fields are here.
    if out_assets:
        extensions.append(FILE_EXTENSION_URL)
    if "processing:datetime" in properties or "processing:software" in properties:
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
        if RECEIPT_ROLE in (asset.get("roles") or []) \
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
    """
    import jsonschema

    if not isinstance(item, dict):
        return [f"not a JSON object: {type(item).__name__}"]
    problems = []
    properties = _mapping(item, "properties")
    extensions = item.get("stac_extensions") or []
    assets = _mapping(item, "assets")

    identity = properties.get("receipt:recipe_id")
    if identity is None:
        problems.append("properties has no receipt:recipe_id")
    elif not isinstance(identity, str) or not _SHA256_HEX.match(identity):
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
    if time is not None and (not isinstance(time, str) or not _UTC_TIME.match(time)):
        problems.append(f"processing:datetime is not an ISO 8601 UTC instant: {time!r}")
    if ("processing:datetime" in properties or "processing:software" in properties) \
            and PROCESSING_EXTENSION_URL not in extensions:
        problems.append(f"stac_extensions does not list {PROCESSING_EXTENSION_URL}, and the "
                        f"item carries processing: fields")

    file_fields = False
    for key, asset in assets.items():
        if not isinstance(asset, dict):
            problems.append(f"asset {key!r} is not an object")
            continue
        if "file:checksum" in asset or "file:size" in asset:
            file_fields = True
        checksum = asset.get("file:checksum")
        if checksum is not None and (not isinstance(checksum, str)
                                     or not _MULTIHASH_SHA256.match(checksum)):
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
VERDICT_NODES = ("receipt.recipe", "receipt.context", "receipt.result",
                 "receipt.result.parts", "published.assets", "served.assets",
                 "published.properties", "served.properties")

# The mirrored fields, and whether a difference in one means the recipe moved or only the
# bytes. `receipt:recipe_id` is the recipe; the rest are what the recipe produced.
_IDENTITY_PROPERTY = "receipt:recipe_id"
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
      the receipt it links, that receipt could not be read, or it links none at all. One
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


def _mirrored(item) -> dict:
    """The mirrored identity fields of an item, flattened to one comparable mapping."""
    out = {}
    properties = _mapping(item, "properties")
    for key in (_IDENTITY_PROPERTY, "processing:datetime", "processing:software"):
        if key in properties:
            out[f"properties.{key}"] = properties[key]
    for key, asset in _mapping(item, "assets").items():
        if not isinstance(asset, dict):
            continue
        for field_name in _RESULT_ASSET_FIELDS:
            if field_name in asset:
                out[f"assets[{key}].{field_name}"] = asset[field_name]
    return out


def item_verdict(published, served, receipt, receipt_sha256=None) -> ItemVerdict:
    """Compare an item's published and served bodies through the receipt it links.

    `receipt_sha256` is the digest of the receipt bytes as fetched. Given, it is checked
    against the published item's receipt asset, which is the only way to tell that the receipt
    read is the one the item claims -- a receipt fetched by a filename convention could belong
    to anything.

    The receipt is what makes this more than a field diff: an item whose mirrored fields do not
    match the receipt beside it is `inconsistent` whatever the two sides agree on.

    Examples:
        >>> item = {"properties": {"receipt:recipe_id": "a" * 64}}
        >>> r = {"recipe": {"recipe_id": "a" * 64}, "result": {}, "context": {}, "output": {}}
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
    # BOTH halves of the mirrored set, not just the properties. `stac_fields(receipt)` with no
    # `assets=` returns no asset fields at all, so `file:checksum` and `file:size` -- which
    # `_mirrored` compares between the two sides -- were never checked against `result.parts`,
    # and an item contradicting its own receipt in those two read `same` (round 1).
    claimed = stac_fields(receipt)
    disagree = []
    properties = _mapping(published, "properties")
    for key, value in claimed["properties"].items():
        if key in properties and canonical(properties[key]) != canonical(value):
            disagree.append(f"properties.{key}")

    parts = _mapping(_mapping(receipt, "result"), "parts")
    for key, asset in _mapping(published, "assets").items():
        if not isinstance(asset, dict):
            continue
        href = asset.get("href")
        if href is not None and not isinstance(href, str):
            # Unhashable as a dict key, and the item is malformed either way. Recorded as a
            # disagreement rather than raised: `_receipt_verdicts` reads the published body
            # with no audit in front of it on the verify path, and one malformed item must
            # not end the run with a traceback (round 2b).
            disagree.append(f"assets[{key}].href")
            continue
        part = parts.get(href)
        if not isinstance(part, dict):
            # Not an output this receipt describes: an overview, a thumbnail, or the receipt
            # itself, whose own digest is checked above. Nothing to compare it with.
            continue
        if "file:checksum" in asset:
            try:
                want_checksum = multihash(part.get("sha256"))
            except ReceiptError:
                want_checksum = None       # a part with no usable digest cannot vouch
            if asset["file:checksum"] != want_checksum:
                disagree.append(f"assets[{key}].file:checksum")
        if "file:size" in asset:
            try:
                want_size = _whole(part.get("bytes"), f"result.parts[{asset['href']}].bytes")
            except ReceiptError:
                want_size = None
            size = asset["file:size"]
            if want_size is None or isinstance(size, bool) \
                    or not isinstance(size, (int, float)) or float(size) != want_size:
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
