# Findings — crate's receipt register and mapping are versioned, and mapping v1.1.0 pins the STAC mapping: re-vendor, pin by version, run stac.json (#15)

## Issue context

**If we do it:** stacs pins the receipt register and mapping by contract version, the way it already pins the schema, its comparison names the rulebook that produced each verdict, and its `stac_fields()` passes the vectors that now pin the STAC mapping. **If we never do:** the next re-vendor fails on moved paths, and stacs keeps pinning a crate commit rather than a version of the contract.

## What changed in crate

crate versioned the register and the mapping (https://github.com/NewGraphEnvironment/crate/issues/58), so these paths move from the next crate release:

| was | now |
|---|---|
| `inst/extdata/receipt/register.csv` | `inst/extdata/receipt/register/v1.0.0/register.csv` |
| `inst/extdata/receipt/mapping.csv` | `inst/extdata/receipt/mapping/v1.0.0/mapping.csv` |
| `inst/extdata/receipt/vectors/v1.0.0/compare.json` | `inst/extdata/receipt/register/v1.0.0/compare.json` |

The bytes did not change: the blob shas are the ones `src/stacs/data/receipt/SOURCE` already records (`0c5b72fa…` register, `86657116…` mapping, `45495a54…` compare.json). Register v1.0.0 and mapping v1.0.0 are exactly what stacs vendors at v0.12.0. Only `vectors/v1.0.0/README.md` differs on the next re-vendor (it no longer describes `compare.json`, which has its own `register/v1.0.0/README.md`).

Both are also published at frozen versioned URLs, beside the schema, with a changelog stating the rules:

- `https://newgraphenvironment.github.io/crate/receipt/register/v1.0.0/register.csv`
- `https://newgraphenvironment.github.io/crate/receipt/mapping/v1.0.0/mapping.csv`
- `https://newgraphenvironment.github.io/crate/receipt/CHANGELOG.md`

A receipt's `receipt_version` stays the form's only: a register or mapping change never moves it. crate's comparison now carries `register` (the version it was judged under) and `overrides` (each field a declaration overrode, with its declared action), and `print()` reads `equivalent (receipts only; register v1.0.0)`.

## Proposed

- [ ] `tools/crate_receipt_vendor.sh`: the new source paths, and vendor `compare.json` and its README from `register/v1.0.0/`
- [ ] Pin the register and mapping by version (path or URL) rather than tag + blob sha alone, and have `check` compare the vendored copies with the served versioned URLs, as it does the schema
- [ ] stacs's comparison names the register version it read, to match crate's

Nothing breaks before stacs re-vendors: its tag pin keeps reading the old paths at v0.12.0.

## Since crate#59 and #60: mapping v1.1.0 and `stac.json`

crate's next release adds mapping v1.1.0 (https://github.com/NewGraphEnvironment/crate/issues/59, https://github.com/NewGraphEnvironment/crate/issues/60). Its rows for older records are unchanged. Its `STAC item` rows now state what v1.0.0 left open:

- a null `recipe_id` or `version` is left out
- a part with no asset is not mirrored
- an asset whose href names no part is refused
- the receipt asset's `file:checksum` is the digest of the published receipt's bytes, with no `file:size`

`inst/extdata/receipt/mapping/v1.1.0/stac.json` pins each rule: receipts, and the item fields each maps to or a refusal code. crate's own `crt_receipt_stac()` runs it, and so does an independent Python check in crate's `data-raw/receipt_vectors_crosscheck.py`. The format is in that directory's `README.md`.

`stac.json` is generated: every path the mapping reads, each in every state (absent, null, the wrong type, empty, each way the value can be malformed). Each refusal has a code, which crate's R carries on its condition and a runner compares, never the message. The codes are tabled in the directory's `README.md`.

Run over stacs origin/main (3b08621), `stac_fields()` agrees on 87 of the 142 cases. Each of the other 55 is a case stacs accepts and crate refuses:

- **The form and the identity.** `output.receipt_version` is not checked, so any form is read as 1.0.0 (`receipt_version_unknown`). A `recipe_id` that is null or absent on a receipt that was not migrated is left out, so the item reads as migrated (`recipe_id_missing`). One set on a migrated receipt is published (`recipe_id_on_migrated`).
- **`context.time`.** When absent or null it is left out; crate requires it. An impossible instant (month 13 or 00, day 00, the 31st of November, 29 February 2026, hour 24, minute 60, second 60) is published, where the processing extension declares `format: date-time`. `_UTC_TIME` uses `\d`, so Arabic-Indic digits pass, and `$` lets a trailing newline through (`time_not_utc`).
- **A trailing newline** on `recipe_id`, a part's `sha256` or `receipt_sha256`. `match` with `^…$` matches before it, so `fullmatch` is needed.
- **Non-object blocks.** `output`, `recipe`, `recipe.code` or a `recipe.code` entry that is null or not an object is read as absent or skipped (`block_not_object`). A repository with an empty name is published as a `processing:software` key (`repo_name_empty`).
- **Values.** A `version` that is a number, `true`, an array or empty (`version_not_string`), and a negative `bytes` (`bytes_not_whole`).
- **Arguments.** A `receipt_asset` that is not a string, or is empty. A `receipt_sha256` with no `receipt_asset` is ignored. A `receipt_asset` that is also in `assets` replaces that part's asset.

- [ ] Vendor `mapping/v1.1.0/` (`mapping.csv`, `stac.json`, `README.md`) and run `stac.json` in the offline suite, comparing each refusal's code
- [ ] Refuse the cases above in `stac_fields()`

## Exploration (2026-11-15)

crate read at its tags over HTTPS; stacs at `e674cda`.

- crate tags: `v0.15.0` is the first with `register/v1.0.0/` and `mapping/v1.0.0/`;
  `v0.16.0` (2026-11-11) is the first with `mapping/v1.1.0/`. Every receipt file at
  `v0.16.0` has the blob sha it has on crate's `main` (`ecadfc6`).
- `register.csv`, `mapping.csv` (v1.0.0) and `compare.json` at `v0.16.0` `cmp` clean against
  the copies vendored here. `vectors/v1.0.0/README.md` differs (it no longer describes
  `compare.json`).
- Served under `https://newgraphenvironment.github.io/crate/receipt/`: 200 for
  `register/v1.0.0/register.csv` (3486 B, equal to the vendored copy),
  `mapping/v1.0.0/mapping.csv`, `mapping/v1.1.0/mapping.csv` (6059 B, equal to the tag) and
  `CHANGELOG.md`; 404 for `mapping/v1.1.0/stac.json` and `register/v1.0.0/compare.json`.
- `stac.json` is a list of 142 cases, keys `name, receipt, assets, receipt_asset,
  receipt_sha256, expected, error`: 17 accept cases and 125 refusals over 17 codes
  (`block_not_object` 44, `time_not_utc` 20, `part_sha256_not_sha256` 11,
  `recipe_id_not_sha256` 9, `digest_not_sha256` 9, `receipt_version_unknown` 6,
  `bytes_not_whole` 6, `href_not_a_part` 4, `recipe_id_missing` 4, `version_not_string` 4,
  `receipt_asset_not_string` 2, and one each of `receipt_asset_without_digest`,
  `digest_without_receipt_asset`, `receipt_asset_in_assets`, `recipe_id_on_migrated`,
  `repo_name_empty`, `receipt_asset_empty`).
- `stac_fields` at `e674cda` agrees on 87 of 142. The 55 it accepts and crate refuses:
  `block_not_object` 17, `time_not_utc` 13, `receipt_version_unknown` 6,
  `recipe_id_missing` 4, `version_not_string` 4, `receipt_asset_not_string` 2, and one each
  of `digest_without_receipt_asset`, `receipt_asset_in_assets`, `recipe_id_on_migrated`,
  `repo_name_empty`, `recipe_id_not_sha256`, `part_sha256_not_sha256`, `bytes_not_whole`,
  `digest_not_sha256`, `receipt_asset_empty`. No accept case disagrees and nothing raised
  outside `ReceiptError`.
- The form schema (v1.0.0) already refuses a missing `context.time`, a null or missing
  `recipe_id` on a receipt that was not migrated, and a `recipe_id` set on a migrated one.
  It accepts month 13 in `context.time`.
- crate's comparison: `register = receipt_register_version()` (`"1.0.0"`), and `overrides`,
  the declared action of each field whose action the declaration changed, named by field and
  sorted by name (radix); restating the register's own action is not an override
  (`R/crt_receipt_compare.R` at `v0.16.0`). `receipt_mapping_version()` is `"1.1.0"`.
- crate's `data-raw/receipt_vectors_crosscheck.py` is an independent Python reading of the
  mapping's STAC rows; the processing extension is listed for every accepted receipt, since
  `context.time` is required.
- Out of scope, measured: `_DATE` (`^-?\d{4,}-\d{2}-\d{2}$` with `.match`) accepts
  `"2026-01-01\n"`, so a table cell with a trailing newline is hashed.

## Phase 1: mutation table (2026-11-15)

Each applied to the working tree alone, the named check run, then restored and `cmp`'d
against a backup.

| mutation | went red |
|---|---|
| `register.csv` copied back to its old unversioned path | `test_nothing_sits_in_the_vendored_directories_that_the_script_does_not_list` |
| the register row removed from `URLS` | `test_each_part_of_the_contract_is_checked_at_the_version_the_module_reads`, `test_the_frozen_url_count_is_the_number_of_urls_listed`, and `check` (`checked 3 frozen URL(s), expected 4`, exit 1) |
| `FROZEN_URLS=3` | `test_the_frozen_url_count_is_the_number_of_urls_listed` |
| one byte appended to the vendored `register.csv` | `test_every_blob_sha_in_source_is_the_file_beside_it`, and `check` twice (differs from the tag; the served URL no longer matches), exit 1 |
| `REGISTER_VERSION = "1.1.0"` with nothing vendored | 18 tests across the contract, vector and package files |

`check` at `v0.16.0`: `OK: 16 file(s) match NewGraphEnvironment/crate@v0.16.0, and all 4 frozen
URLs serve them`. Full suite: 823 passed.

## Phase 2: baselines and mutation table (2026-11-15)

Before the code changed, `stac.json` over `stac_fields` at `e674cda`: 87 of 142 by accept or
refuse (55 accepted where crate refuses), and 17 of 142 by code, since `ReceiptError` carried
none and only the accept cases could agree. After: 142 of 142 by code. Full suite: 852 passed
on Python 3.12 and on 3.11 before the review's additions, 875 on 3.12 after them.

Each guard removed in turn from `src/stacs/receipt.py` (driver in the session scratchpad; the
file restored and compared after). "Cases" is the count the runner reported disagreeing.

| guard removed | `stac.json` cases red | stacs tests red besides the runner |
|---|---|---|
| `_block`: null read as absent | 8 | the `item_verdict` refusal test, `test_stac_fields_refuses_a_malformed_code_block_rather_than_crashing` |
| `_block`: any non-object read as absent | 40 | 20 more |
| `receipt_version_unknown` | 6 | 1 |
| `recipe_id_missing` | 4 | `test_only_a_migrated_receipt_may_have_no_recipe_identity` |
| `recipe_id_on_migrated` | 1 | same |
| `recipe_id_not_sha256` | 9 | none |
| `time_not_utc`, the whole check | 20 | 2 |
| real-instant half (`return True`) | 6 | `test_item_problems_catches_each_way_an_item_can_be_wrong` |
| month range | 2 | 2 |
| `_UTC_TIME` `fullmatch` to `match` | 1 | `test_item_problems_catches_each_way_an_item_can_be_wrong` |
| `_UTC_TIME` `[0-9]` to `\d` | 1 | same |
| `version_not_string` | 4 | none |
| `repo_name_empty` | 1 | none |
| `href_not_a_part` | 4 | `test_stac_fields_refuses_an_asset_href_that_is_not_a_part` |
| `part_sha256_not_sha256` | runner red (a `KeyError`, not a count) | none |
| `_whole`: negative | 1 | `test_item_problems_catches_each_way_an_item_can_be_wrong` |
| `_whole`: fraction | 1 | same |
| `_whole`: not a number | 4 | none |
| `receipt_asset_not_string` | 2 | none |
| `receipt_asset_empty` | 1 | none |
| `receipt_asset_in_assets` | 1 | none |
| `receipt_asset_without_digest` | 1 | `test_stac_fields_needs_the_digest_for_the_receipt_asset` |
| `digest_without_receipt_asset` | 1 | none |
| `digest_not_sha256` | 9 | none |
| `_SHA256_HEX` `fullmatch` to `match` | 6 | `test_multihash_refuses_anything_but_a_sha256`, the audit test |
| `_MULTIHASH_SHA256` `fullmatch` to `match` | none | `test_item_problems_catches_each_way_an_item_can_be_wrong` |
| processing extension only with software | 2 | `test_a_migrated_receipt_leaves_the_field_out_rather_than_publishing_a_null` |

Run before the review's additions (F9, F10, F17), which add tests and no guard this table
removes. The two guards they did add (`item_verdict`'s catch, the non-object part) get their
mutation check in the branch review.

Measured, and left alone: `write` accepts a `context.time` of month 13 (the form schema's
pattern admits it), and `stac_fields` refuses the receipt it wrote. crate's R raises two codes
its published table and vectors do not hold (`assets_not_named`, `href_empty`); stacs publishes
an asset keyed `""`.

## Errors Encountered

| Error | Resolution |
|-------|------------|
| Two tests stayed red after `receipt.py` was restored from a backup with `cp` | The restored file had the size and mtime second of the mutated one, so Python reused the mutated bytecode cache. `touch` the file after a restore (or run mutations with `PYTHONDONTWRITEBYTECODE=1`). |
