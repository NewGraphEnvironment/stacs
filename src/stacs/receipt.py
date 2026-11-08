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

import datetime
import hashlib
import json
import re
import struct

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
