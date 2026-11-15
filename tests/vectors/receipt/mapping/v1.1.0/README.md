# Receipt mapping, v1.1.0

How an older provenance record's fields become a receipt's, and how a receipt's fields become a STAC
item's ([crate#43](https://github.com/NewGraphEnvironment/crate/issues/43), versioned in
[crate#58](https://github.com/NewGraphEnvironment/crate/issues/58); the STAC rows executed and
pinned in [crate#59](https://github.com/NewGraphEnvironment/crate/issues/59) and
[crate#60](https://github.com/NewGraphEnvironment/crate/issues/60)).

| file | what it is |
|---|---|
| `mapping.csv` | `source_format`, `source_field`, `receipt_key`, `transform`, `stac_key`, `note`: one row per field of each older format, and the `STAC item` rows |
| `stac.json` | the vectors for the `STAC item` rows: each case is a receipt and the item fields it maps to, or a refusal |

`mapping.csv` is published at
`https://newgraphenvironment.github.io/crate/receipt/mapping/v1.1.0/mapping.csv`.

**`stac.json`**: each case is `{name, receipt, assets, receipt_asset, receipt_sha256, expected,
error}`.

- `assets` maps an asset key to its href relative to the item, which is the path a part is keyed by.
- `receipt_asset` and `receipt_sha256` are the key of the asset that links the receipt and the
  SHA-256 of the published receipt's bytes, or `null`.
- Where `error` is `null`, the item fields are `expected`: `stac_extensions` (an array, in order),
  `properties` and `assets`. Compare `properties` and `assets` as canonical JSON (RFC 8785), so
  member order does not matter.
- Where `error` is a code, the implementation must refuse the case with that code, and `expected`
  is `null`. Compare codes, never messages.

| code | refused |
|---|---|
| `block_not_object` | the receipt, or a block or entry it reads (`output`, `recipe`, `result`, `context`, `recipe.code` and each entry, `result.parts` and each part), present but not an object, `null` included: never read as absent |
| `receipt_version_unknown` | `output.receipt_version` is not `1.0.0`, the form this mapping reads, or is missing |
| `recipe_id_missing` | `recipe.recipe_id` null or missing on a receipt that was not migrated (no `output.migrated_from`), whose item would read as migrated |
| `recipe_id_on_migrated` | `recipe.recipe_id` set on a migrated receipt |
| `recipe_id_not_sha256` | `recipe.recipe_id` not exactly 64 lower-case hex digits |
| `time_not_utc` | `context.time` missing, null, not the form's pattern, or not a real instant (a month, a day that month has, hours 00-23, minutes and seconds 00-59) |
| `version_not_string` | a `recipe.code` entry's `version` that is not a non-empty string (null and missing are left out) |
| `repo_name_empty` | a `recipe.code` entry with an empty name, which would key `processing:software` |
| `href_not_a_part` | an asset whose href names no part |
| `part_sha256_not_sha256` | that part's `sha256` not exactly 64 lower-case hex digits |
| `bytes_not_whole` | that part's `bytes` not a whole number of at least 0 |
| `receipt_asset_not_string`, `receipt_asset_empty` | the receipt asset's key not a string, or empty |
| `receipt_asset_in_assets` | the receipt asset's key also an asset's |
| `receipt_asset_without_digest`, `digest_without_receipt_asset` | one of `receipt_asset` and `receipt_sha256` without the other |
| `digest_not_sha256` | `receipt_sha256` not exactly 64 lower-case hex digits |

A SHA-256 is exactly 64 lower-case ASCII hex digits: a pattern that also matches before a trailing
newline (Python's `$` with `re.match`) or any Unicode digit (`\d`) is not enough.

**Which cases.** A few cases show the mapping's rules on the worked case. The rest are generated:
every path the mapping reads (each `STAC item` row's receipt key, every ancestor of it, and
`output.receipt_version` and `output.migrated_from`), each in every state that reaches its guard:
absent, `null`, the wrong type, empty, and each way its value can be malformed. A case changes one
path, its `recipe_id` recomputed for a change inside the recipe, so it is refused for that path
alone. A string receipt is not a case: crate's R reads a string as a path.

**What a reading checks.** The values it publishes, the keys it publishes, and what decides them:
`output.receipt_version`, `output.migrated_from` (by its presence, as the form schema's `if` does),
`recipe.recipe_id` and `context.time`. It does not validate the rest of the receipt; validate it
against the form schema for that. A `version` that is missing reads as `null`, since the item is the
same either way. The receipts are I-JSON (RFC 7493), which RFC 8785 requires, so a duplicated key is
outside the contract: parsers disagree on which copy they keep.

Read the receipts' numbers as the hashing vectors in `inst/extdata/receipt/vectors/v1.0.0/`
describe.

The rows that differ from v1.0.0 are listed in the changelog at
`https://newgraphenvironment.github.io/crate/receipt/CHANGELOG.md`. A released version is never
edited: a row change, or a code change that moves a value in `stac.json`, is a new version
directory beside this one. `data-raw/receipt_vectors.R` in crate's repository writes `stac.json`.
