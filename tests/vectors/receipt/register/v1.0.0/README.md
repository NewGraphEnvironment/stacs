# Receipt register, v1.0.0

The rulebook a comparison of two receipts reads ([crate#43](https://github.com/NewGraphEnvironment/crate/issues/43),
versioned in [crate#58](https://github.com/NewGraphEnvironment/crate/issues/58)). It covers receipt
form v1.0.0: one row per field of that schema, and none other.

| file | what it is |
|---|---|
| `register.csv` | `field`, `action`, `why`: what a difference in each field does. `refuse` makes the verdict `different`, `warn` is reported without changing it, `record` is listed only |
| `compare.json` | the vectors for this register: each case is `a`, `b` (receipts), `verdict`, `differences` |

`register.csv` is published at
`https://newgraphenvironment.github.io/crate/receipt/register/v1.0.0/register.csv`, so an
implementation in any language can fetch the exact rows its verdicts are computed from.

**`compare.json`**: comparing the receipts alone gives `verdict`, and the fields that differed,
each with its action, are `differences` (sorted by field as bytes). A field is its path,
`block.member`, with a key of a keyed collection in brackets:
`result.parts[access_check.csv].sha256`. Its action is this register's: `refuse`, `warn`,
`record`, or `within` for a result value that differs inside its declared tolerance. The receipts
are written to form v1.0.0; read their numbers as the hashing vectors in
`inst/extdata/receipt/vectors/v1.0.0/` describe.

A released version is never edited. A row whose `action` changes changes a published verdict, so
it is a new version directory beside this one; see the changelog at
`https://newgraphenvironment.github.io/crate/receipt/CHANGELOG.md`.
`data-raw/receipt_vectors.R` in crate's repository writes `compare.json`.
