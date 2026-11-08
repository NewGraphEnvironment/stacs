# Receipt test vectors, v1.0.0

The executable half of crate's provenance receipt contract
([crate#43](https://github.com/NewGraphEnvironment/crate/issues/43)). Every implementation of
the receipt (crate's in R, `stacs.receipt` in Python, any other) runs these files and must
produce each expected value byte for byte. They are frozen with the receipt schema v1.0.0:
a change is a new version directory, never an edit.

| file | each case | check |
|---|---|---|
| `numbers.json` | `bits` (an IEEE 754 double, 16 hex digits, big-endian), `expected` | RFC 8785 spelling of the double |
| `jcs.json` | `input_json`, `expected` | parse `input_json` with your JSON parser; RFC 8785 serialization equals `expected` |
| `recipe_id.json` | `recipe_json`, `jcs`, `recipe_id` | parse, drop `recipe_id` if present, serialize: equals `jcs`; SHA-256 hex of its UTF-8 bytes equals `recipe_id` |
| `fingerprint.json` | `table`, `tolerance`, `canonical`, `sha256` | the table's canonical form equals `canonical`; SHA-256 hex of its UTF-8 bytes equals `sha256` |
| `compare.json` | `a`, `b` (receipts), `verdict`, `differences` | comparing the receipts alone gives `verdict`, and the fields that differed, each with its action, are `differences` (sorted by field as bytes) |

A field in `differences` is its path, `block.member`, with a key of a keyed collection in
brackets: `result.parts[access_check.csv].sha256`. Its action is the register's
(`inst/extdata/receipt/register.csv` in crate): `refuse`, `warn`, `record`, or `within` for a
result value that differs inside its declared tolerance.

`table` is `{"columns": {<name>: {"type": <t>, "values": [...]}}}`, with `t` one of
`character`, `integer`, `double`, `logical`, `date`, `datetime`. Doubles are given as bits, as
in `numbers.json`, so no decimal parser stands between the vector and the value. Dates are
`YYYY-MM-DD`, datetimes `YYYY-MM-DDTHH:MM:SSZ`, and `null` is NA. `tolerance` maps a column to
a power of ten.

Two things trip implementations:

- **Read every JSON number as a double.** JSON has one number type. Python's `json` reads
  `1152921504606846976` as an `int`, which `rfc8785` refuses past 2^53; pass
  `parse_int=float`.
- **The number spelling needs a correctly rounded parser.** RFC 8785 writes the fewest digits
  that read back as the same double. R's `as.numeric()` is not correctly rounded on arm64;
  crate reads back through jsonlite (the C library's `strtod`).

The canonical forms are specified in the vignette (`vignette("receipt", package = "crate")`).
`data-raw/receipt_vectors.R` in crate's repository writes these files, and
`data-raw/receipt_vectors_crosscheck.py` recomputes them in Python.
