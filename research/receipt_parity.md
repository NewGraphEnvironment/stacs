# Receipt parity: holding two implementations of one contract byte for byte

**Verified:** 2026-11-15 · **Issues:** stacs#12, stacs#15, stacs#16, crate#43, crate#44,
crate#23, crate#58, crate#59, crate#60, crate#65 ·
**Produced by:** `tests/test_receipt_vectors.py` over the vendored
`tests/vectors/receipt/`, and `tools/crate_receipt_vendor.sh check` ·
**Status:** OPEN — the contract is frozen at receipt form v1.0.0, register v1.0.0 and mapping
v1.1.0; what is not covered is named below.

crate's provenance receipt has two implementations: crate's in R, and `stacs.receipt` in
Python. They must produce the same bytes, because a `recipe_id` is published inside items and
beside them, and nothing recomputes it downstream. This records what makes that hold, what is
not checked, and the traps that cost time.

## What keeps them aligned

crate's test vectors. The contract has three parts, each versioned on its own (crate#58), and
each part's vectors are frozen with it: the hashing with the form
(`inst/extdata/receipt/vectors/v1.0.0/`), `compare.json` with the register
(`register/v1.0.0/`) and `stac.json` with the mapping (`mapping/v1.1.0/`). Vendored here from
tag `v0.16.0`. Measured 2026-11-15, all passing through this package's own public API:

| vectors | part | cases | what each pins |
|---|---|---|---|
| `numbers.json` | form | 2,637 | the RFC 8785 spelling of a double, from its bits |
| `jcs.json` | form | 10 | canonical JSON of a parsed document, including two top-level scalars |
| `recipe_id.json` | form | 7 | the canonical bytes of a recipe and its SHA-256 |
| `fingerprint.json` | form | 13 | a table's canonical form and its fingerprint |
| `compare.json` | register | 9 | the verdict and the exact ordered `(field, action)` list |
| `stac.json` | mapping | 142 | the item fields a receipt maps to (17 cases), or the code it is refused with (125 cases, 17 codes) |

`stac.json` is the one that moved this package. Before mapping v1.1.0 the STAC rows had no
vectors, and `stac_fields` as first written agreed with 87 of the 142: every one of the other
55 was a receipt it mapped and crate refuses. By code: `block_not_object` 17 (a block that
was `null` or not an object, read as absent), `time_not_utc` 13, `receipt_version_unknown` 6,
`recipe_id_missing` 4, `version_not_string` 4, and 11 across ten other codes. A refusal is
compared by its **code**, never its message, so `ReceiptError` carries one.

Two further artifacts do what no vector can:

- **crate's worked-case receipts** (`examples/worked_case/build_{1,2}/receipt.json`). A read
  and rewrite of each is **byte identical**, 2835 and 2837 bytes. That is the only oracle for
  the file on disk, and it also confirms `recipe_id` agrees for a real receipt rather than
  only for the vectors, because `write` recomputes it.
- **crate's example STAC item** (`stac/receipt/examples/item.json`). `item_problems` finds
  nothing wrong with it and `stac_fields` reproduces its property names, extension list and
  multihash forms. An oracle written by the other implementation is the only kind that cannot
  agree with whatever this code happens to do.

The vendored copies are re-checked against the tag before pytest, because the suite runs
offline and could not fetch them. The same step proves each frozen URL still serves the
vendored bytes — the two schemas, the register and the mapping, each at its version — which is
crate's never-edit rule enforced from the consumer's side. crate serves no URL for
`compare.json` or `stac.json`, so those two are checked against the tag alone.

## What is not covered, and should not be assumed

- **`compare`'s `bytes` mode.** crate can settle a differing table fingerprint by re-reading
  both builds' tables and certifying each against its own receipt. `compare.json` supplies no
  tables, so that path has no vector and is **not implemented here** rather than implemented
  untested. A fingerprint difference says so in its detail instead of reading as a plain
  refusal.
- **`crt_receipt_migrate`.** Reading an older record into a receipt is crate's; this package
  reads and writes migrated receipts (null `recipe_id`, `output.migrated_from`) but does not
  produce them.
- **`mapping.csv`'s non-STAC rows.** Only the seven `STAC item` rows are used, and of those the
  `properties.version` ← `context.legacy` row is deliberately skipped: a release label is not
  provenance.
- **The shape of the `assets` argument.** Every `stac.json` case passes `assets` as an object
  with non-empty keys and hrefs. crate's R refuses an empty key and an empty href with two
  codes its table and vectors do not hold (crate#65); here an empty key is published and an
  empty href is refused as naming no part. Nothing compares the two on it.
- **The calendar beyond what the vectors hold.** `stac.json` has two years and two month
  lengths. The century rule and year 0000 are pinned by this package's own test, computed by
  arithmetic as crate computes it, since a date library refuses year 0000.
- **A date or datetime cell of a table.** The mapping's patterns were tightened; the table
  fingerprint's were not, and still hash a cell with a trailing newline (stacs#16).

## Where the two implementations genuinely differ

- **Reach, on a large table.** crate#50 is open: `crt_table_fingerprint()` fails on a table
  whose canonical JSON passes 2^31-1 bytes, which is R's string-length limit, hit by a
  4,033,543 × 34 table. Python has no such limit, so this package can fingerprint tables crate
  currently cannot. The bytes agree wherever both can compute them; the vectors are small, so
  parity is unaffected.
- **Scalar versus array in `config.settings`.** An R length-one vector auto-unboxes, so an
  R-written receipt may hold `"CO"` where a Python one holds `["CO"]` — and those are **two
  different `recipe_id`s for one intent**. Nothing in either implementation can detect it;
  any output written from both languages has to agree per setting.
- **What `write` accepts and `stac_fields` refuses.** The form's pattern for `context.time`
  admits month 13, so `write`, which validates against the form, publishes a receipt whose
  item fields the mapping then refuses. On the verify path that item reads `inconsistent`.
- **Type refusals.** crate refuses a list of R-specific hazards by name (`integer64`, a
  `Date` as a value, names on an atomic vector). Those have no Python meaning; this package
  refuses its own (`bool` before `int`, `Decimal`, a naive `datetime`, `bytes`), which is the
  same discipline rather than the same list.

## Traps, measured

- **Read every JSON number as a double.** `json.loads(..., parse_int=float)`; `rfc8785`
  refuses an int past 2^53, and `jcs.json` carries `1152921504606846976` for exactly this.
  Consequence: `rows`, `bytes` and `seed` come back as floats. That is harmless in the bytes —
  `rfc8785.dumps(3.0) == rfc8785.dumps(3)` — so no coercion is needed, and a test pins the
  round trip rather than a guard that would do nothing.
- **Never re-serialise a parsed receipt to write the file.** JCS writes `0.000001` and `1e-9`
  where `json.dumps` writes `1e-06` and `1e-09`, and crate's worked-case receipt carries both
  as ordinary tolerance values. The file is the canonical bytes **re-indented as text**.
- **`jsonschema` accepts `4.0` where the schema says `integer`** (4.26.0, draft-07 semantics).
  It does refuse `4.5`. So schema validation is not a guard against a whole float.
- **The power-of-two spelling is a non-issue in Python.** `rfc8785` uses Python's
  shortest-round-trip formatting, which is correct at a tie; 2^-24 comes out
  `5.960464477539063e-8` as the vectors require. R needed a bisection search reading
  candidates back through a correctly rounded parser, because `as.numeric()` is not one on
  arm64. This is why `numbers.json` carries all 2,098 powers of two.
- **Two sort orders, neither a collation.** Object keys sort by UTF-16 code units (JCS, left
  to `rfc8785`); a table's columns and rows sort by UTF-8 bytes. They differ above U+FFFF, and
  Python's default `sorted` on strings is the second, not the first.
- **Empty keyed collections are `{}`.** An R-ism in the contract, and it is load-bearing: the
  empty recipe hashes `{"code":{},"config":{"files":{},"settings":{}},"inputs":{},"seed":null}`
  to `ecb53cd4e03b09490f6c581b1195aa9635e5fff51790d64e19d2a2a79f8a0493`.
- **Both published schemas are draft-07 with no `$ref` carrying sibling keywords**, so
  Python's `jsonschema` and R's ajv read them alike; and the field schema's
  `patternProperties: {"^(?!receipt:)": {}}` negative lookahead is valid in Python `re`.
- **`validate` passes a value that ends in a newline.** `jsonschema` applies the form
  schema's patterns with Python's `re`, where `$` also matches before a trailing newline. Of
  the 125 receipts `stac.json` refuses, 28 pass `validate`: 17 are refused for an argument
  and not the receipt, 8 hold an instant that does not exist, which the form's pattern
  admits, and 3 hold a `recipe_id`, a `context.time` or a part's `sha256` followed by a
  newline (stacs#16). So `validate` is not a guard for the mapping, and the mapping checks
  with `fullmatch` and `[0-9]`.
- **A `oneOf` makes `jsonschema`'s message useless**, and `best_match` prefers the branch
  selector ("'Collection' was expected" about an Item) because it is shallower. Descend into
  the context and drop each branch's own `type` error first.

## Why `verify` does not use crate's verdicts

crate's `identical` / `equivalent` / `different` compare **two receipts**, and its register
decides them. `verify` has one receipt and the five identity fields an item mirrors. Four of
those five are `refuse` in the register and the fifth is `record`, and `within` — the only
route to `equivalent` — needs `result.summary` with its tolerance, `result.parts.*.table` with
both `result.fingerprint` maps, or re-read tables. A served item carries none of them, so the
reachable set is `identical` and `different` only.

So `verify` reports `same` / `rebuilt` / `changed` / `inconsistent` and says they are its own.
`rebuilt` is the distinction stacs#12 asked for and the one crate cannot name here.

## Related work

- [crate's receipt vignette](https://github.com/NewGraphEnvironment/crate/blob/main/vignettes/receipt.Rmd)
  and `research/provenance_receipt.md` in crate: the contract itself, and the decisions behind
  it.
- [`research/pgstac_round_trip.md`](pgstac_round_trip.md): the other canonical form in this
  package, and why it may change while this one may not.
