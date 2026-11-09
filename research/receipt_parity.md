# Receipt parity: holding two implementations of one contract byte for byte

**Verified:** 2026-11-08 · **Issues:** stacs#12, crate#43, crate#44, crate#23 ·
**Produced by:** `tests/test_receipt_vectors.py` over the vendored
`tests/vectors/receipt/v1.0.0/`, and `tools/crate_receipt_vendor.sh check` ·
**Status:** OPEN — the contract is frozen at receipt schema v1.0.0; what is not covered is
named below.

crate's provenance receipt has two implementations: crate's in R, and `stacs.receipt` in
Python. They must produce the same bytes, because a `recipe_id` is published inside items and
beside them, and nothing recomputes it downstream. This records what makes that hold, what is
not checked, and the traps that cost time.

## What keeps them aligned

crate's test vectors, frozen with the schema version at
`inst/extdata/receipt/vectors/v1.0.0/` and vendored here at tag `v0.12.0`. Measured
2026-11-08, all passing through this package's own public API:

| vectors | cases | what each pins |
|---|---|---|
| `numbers.json` | 2,637 | the RFC 8785 spelling of a double, from its bits |
| `jcs.json` | 10 | canonical JSON of a parsed document, including two top-level scalars |
| `recipe_id.json` | 7 | the canonical bytes of a recipe and its SHA-256 |
| `fingerprint.json` | 13 | a table's canonical form and its fingerprint |
| `compare.json` | 9 | the verdict and the exact ordered `(field, action)` list |

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
offline and could not fetch them. The same step proves each frozen schema URL still serves the
vendored bytes, which is crate's never-edit rule enforced from the consumer's side.

## What is not covered, and should not be assumed

- **`compare`'s `bytes` mode.** crate can settle a differing table fingerprint by re-reading
  both builds' tables and certifying each against its own receipt. `compare.json` supplies no
  tables, so that path has no vector and is **not implemented here** rather than implemented
  untested. A fingerprint difference says so in its detail instead of reading as a plain
  refusal.
- **`crt_receipt_migrate`.** Reading an older record into a receipt is crate's; this package
  reads and writes migrated receipts (null `recipe_id`, `output.migrated_from`) but does not
  produce them.
- **`mapping.csv`'s non-STAC rows.** Only the six `STAC item` rows are used, and of those the
  `properties.version` ← `context.legacy` row is deliberately skipped: a release label is not
  provenance.

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
