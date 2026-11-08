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


def _check_keyed(recipe):
    for path in _KEYED:
        node = recipe
        for part in path:
            if not isinstance(node, dict):
                break
            node = node.get(part)
        else:
            if node is not None and not isinstance(node, dict):
                raise ReceiptError(
                    f"recipe.{'.'.join(path)} must be an object keyed by name, got "
                    f"{type(node).__name__}: a list would hash in the order it was written")


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
    version = (doc.get("output") or {}).get("receipt_version") \
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
        if pattern in collections:
            kx, ky = keys(x), keys(y)
            for k in sorted(set(kx) - set(ky)):
                found.append((field, pattern, f"{k} only in a", k))
            for k in sorted(set(ky) - set(kx)):
                found.append((field, pattern, f"{k} only in b", k))
            for k in [k for k in kx if k in set(ky)]:
                walk(x[k], y[k], f"{field}[{k}]", f"{pattern}.*", k)
        elif pattern in table or pattern not in prefixes:
            # A leaf. Equality is "the same canonical JSON", so an absent member and a null
            # compare equal -- which is how JSON reads them, and how a receipt written with a
            # null reads back.
            if canonical(x) != canonical(y):
                found.append((field, pattern, f"{_show(x)} vs {_show(y)}", key))
        else:
            for name in list(dict.fromkeys(keys(x) + keys(y))):
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
        tol = ((doc.get("result") or {}).get("tolerance") or {}).get("summary") or {}
        return tol.get(name) if isinstance(tol, dict) else None

    ta, tb = declared(a), declared(b)
    if ta is None or canonical(ta) != canonical(tb):
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
                  if (doc.get("recipe") or {}).get("recipe_id", "absent") is None]
    if missing_id:
        rows = [r_ for r_ in rows if r_["pattern"] != "recipe.recipe_id"]
        rows.append({"field": "recipe.recipe_id", "pattern": "recipe.recipe_id",
                     "action": "refuse", "key": None,
                     "detail": f"recipe unknown: {' and '.join(missing_id)} holds no recipe "
                               f"identity (a migrated receipt)"})

    for row in rows:
        if row["pattern"] == "result.summary.*":
            tol = _summary_tolerance(a, b, row["key"])
            va = ((a.get("result") or {}).get("summary") or {}).get(row["key"])
            vb = ((b.get("result") or {}).get("summary") or {}).get(row["key"])
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
            if name not in ((doc.get("result") or {}).get("fingerprint") or {}):
                return False
        return all(row["action"] == "within" for row in rows
                   if row["key"] == name
                   and row["pattern"].startswith("result.fingerprint.*."))

    for row in rows:
        if row["pattern"] not in ("result.parts.*.bytes", "result.parts.*.sha256"):
            continue
        part = row["key"]
        names = [((doc.get("result") or {}).get("parts") or {}).get(part, {}).get("table")
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
