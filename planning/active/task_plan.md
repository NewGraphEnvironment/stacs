# Task: crate's receipt register and mapping are versioned, and mapping v1.1.0 pins the STAC mapping: re-vendor, pin by version, run stac.json (#15)

**If we do it:** stacs pins the receipt register and mapping by contract version, the way it already pins the schema, its comparison names the rulebook that produced each verdict, and its `stac_fields()` passes the vectors that now pin the STAC mapping. **If we never do:** the next re-vendor fails on moved paths, and stacs keeps pinning a crate commit rather than a version of the contract.

Branch `15-crate-s-receipt-register-and-mapping-are`, cut from `origin/main` at `e674cda`.

## Context

stacs vendors crate's receipt contract at tag `v0.12.0`, where `register.csv` and `mapping.csv`
sat unversioned. crate has since versioned both (crate#58) and published mapping v1.1.0 with
`stac.json`, 142 cases that pin how a receipt becomes STAC item fields (crate#59, crate#60).
The issue asks stacs to follow: new source paths, a pin by contract version, a comparison that
names its register, and a `stac_fields()` that passes the vectors.

What exploration measured (2026-11-15, crate read at its tags over HTTPS):

- **The release the issue calls "next" is out.** `v0.15.0` is the first tag with
  `register/v1.0.0/` and `mapping/v1.0.0/`; `v0.16.0` (2026-11-11, crate's newest, identical to
  its `main` for every receipt file) is the first with `mapping/v1.1.0/`.
- **The three moved files are byte-identical** to what stacs vendors: `register.csv`,
  `mapping.csv` (v1.0.0) and `compare.json` all `cmp` clean against `v0.16.0`. Only
  `vectors/v1.0.0/README.md` differs.
- **Served versioned URLs:** `register/v1.0.0/register.csv`, `mapping/v1.0.0/mapping.csv`,
  `mapping/v1.1.0/mapping.csv` and `CHANGELOG.md` answer 200 and match the tag. `compare.json`
  and `stac.json` are not served (404), so those two can only be checked against the tag.
- **`stac.json` reproduces the issue's number.** `stacs.receipt.stac_fields` at `e674cda`
  agrees on 87 of 142; the other 55 are cases it accepts and crate refuses, across 15 of the 17
  codes. All 17 accept cases already agree, value for value.
- **stacs has no refusal code.** `ReceiptError` carries a message only, and the vectors are
  compared by code.
- **`mapping.csv` is not read at run time** (only shipped and presence-tested); `register.csv`
  is, by `receipt.register()`.
- **A form-valid receipt is nearly unaffected.** The frozen form schema already refuses a
  missing `context.time`, a null or missing `recipe_id` on a receipt that was not migrated, and
  one set on a migrated receipt. It accepts an impossible instant (month 13). So the new
  refusals bite a receipt that was never validated: `stac_fields` called directly, and
  `item_verdict` on a fetched receipt, where `receipt.read` checks the version only.
- **`item_verdict` calls `stac_fields(receipt)`**, and `register._receipt_verdicts` already
  turns its `ReceiptError` into `inconsistent` with the reason. So a fetched receipt the mapping
  refuses becomes `inconsistent`, never a crash.
- The issue has no comments.

## Decided at the gate

Recommendations, each taken unless the plan is edited at approval (owner, 2026-11-15):

1. **Pin crate tag `v0.16.0`.** It is the newest release and the first that holds everything
   the issue names.
2. **Vendor mapping v1.1.0 only**, not v1.0.0 beside it. stacs executes one mapping version, and
   v1.1.0's rows for older records are unchanged.
3. **Layout mirrors crate's versions.** In the package, read through `importlib.resources`:
   `src/stacs/data/receipt/register/v1.0.0/register.csv` and
   `src/stacs/data/receipt/mapping/v1.1.0/mapping.csv`. Test vectors stay out of the wheel:
   `tests/vectors/receipt/register/v1.0.0/{compare.json,README.md}` and
   `tests/vectors/receipt/mapping/v1.1.0/{stac.json,README.md}`. The old unversioned paths go.
4. **A refusal's code is `ReceiptError.code`**, `None` where crate tables no code (a stacs-only
   refusal such as `assets` not being a mapping).
5. **`Comparison` gains `register` and `overrides`.** The issue asks for the first. The second is
   what crate carries beside it, so a verdict judged under a changed action says so; strike it
   to keep the change to `register` alone.
6. **The item audit gets the same strict patterns.** `_SHA256_HEX`, `_MULTIHASH_SHA256` and
   `_UTC_TIME` are shared by `stac_fields`, `multihash` and `item_problems`, so fixing them
   (ASCII digits, `fullmatch`) and the real-instant check reaches `audit --require-receipt` too:
   an item whose `processing:datetime` is month 13, or carries a trailing newline, is refused.
   One producer, so audit cannot pass what `stac_fields` refuses to write.

## Phase 1: Re-vendor at crate `v0.16.0`, pinned by contract version

Purpose: the vendored files sit at versioned paths, and `check` proves each served version.

- [x] `tools/crate_receipt_vendor.sh`: `CRATE_TAG=v0.16.0`; `FILES` reads
      `register/v1.0.0/register.csv`, `mapping/v1.1.0/mapping.csv`,
      `register/v1.0.0/{compare.json,README.md}` and `mapping/v1.1.0/{stac.json,README.md}`,
      landing at the paths in decision 3; drop the two unversioned rows and
      `vectors/v1.0.0/compare.json`
- [x] `URLS` gains the served `register/v1.0.0/register.csv` and `mapping/v1.1.0/mapping.csv`;
      `FROZEN_URLS=4`; the success line and its comments stop saying "both"; the comment that
      the register and mapping "are NOT versioned in crate" is rewritten
- [x] `git mv` the three byte-identical files to their new paths, then run `vendor` (network) so
      `SOURCE` is rewritten by the script, and `check` reads `OK`
- [x] `receipt.py`: `REGISTER_VERSION = "1.0.0"`, `MAPPING_VERSION = "1.1.0"`; `register()` reads
      `register/v1.0.0/register.csv`. *(Corrected while building: no `REGISTER_URL` or
      `MAPPING_URL` constant. Nothing reads one at run time, and a crate URL that is not a
      schema trips the deployment-name guard, whose carve-out is deliberately the two schema
      URLs. The served URLs live in the script's `URLS` block, and a test ties each to its
      version constant.)*
- [x] Tests: each URL constant is pinned to its version constant and to a row of the script's
      `URLS` block; `test_package.py` and the compare runner read the new paths; a new guard
      that no file under `src/stacs/data/receipt/` or `tests/vectors/receipt/` is absent from
      the script's `FILES` (a stale unversioned copy left behind would otherwise still be read)
- [x] `.github/workflows/test.yml`: the step comment names the register and mapping URLs too
- [x] Mutation check: restore an old-path file, delete a `URLS` row, edit one vendored byte;
      each turns a named test or `check` red

## Phase 2: `stac_fields()` under mapping v1.1.0

Purpose: all 142 `stac.json` cases agree, each refusal by its code.

- [ ] Test first: `tests/test_receipt_vectors.py` runs `stac.json` through the public
      `stac_fields` (receipts read with `load_json`), count pinned at 142, `stac_extensions`
      compared in order, `properties` and `assets` as canonical JSON, a refusal by `e.code`;
      recorded red at 55 before the code changes
- [ ] `ReceiptError(message, code=None)` with a `code` attribute
- [ ] `_SHA256_HEX`, `_MULTIHASH_SHA256`, `_UTC_TIME`: `[0-9]` for `\d`, `fullmatch` at every use
- [ ] `_utc_instant()`: the form's pattern and a real instant (month, a day that month has,
      hour 00-23, minute and second 00-59), used by `stac_fields` and `item_problems`
- [ ] `stac_fields` refuses, with crate's code: a block or entry present but not an object,
      `null` included (`output`, `recipe`, `result`, `context`, `recipe.code` and each entry,
      `result.parts` and the named part); `output.receipt_version` not `1.0.0`; `recipe_id`
      missing on a receipt that was not migrated, or set on a migrated one; `context.time`
      missing or not a real UTC instant; a `version` that is not a non-empty string; an empty
      repository name; `bytes` negative or not whole; `receipt_asset` not a string, empty, or
      also a key of `assets`; `receipt_sha256` without `receipt_asset`; a digest that is not 64
      lower-case hex
- [ ] Existing refusals take their code (`href_not_a_part`, `part_sha256_not_sha256`,
      `receipt_asset_without_digest`, `recipe_id_not_sha256`, `digest_not_sha256`)
- [ ] A test that the codes `stac_fields` can raise are exactly the 17 `stac.json` uses
- [ ] `tests/test_receipt.py` and the docstring examples of `stac_fields` and `item_verdict`:
      the bare receipts they build gain `receipt_version`, `context.time` and a `recipe_id`
      where the mapping now requires them; a new test that `item_verdict` on a receipt the
      mapping refuses raises `ReceiptError`, which `_receipt_verdicts` reports as `inconsistent`
- [ ] Mutation table: remove each new guard in turn and name the `stac.json` cases that go red

## Phase 3: The comparison names its register

- [ ] `Comparison.register` is `REGISTER_VERSION`; `Comparison.overrides` is the
      `(field, action)` pairs whose declared action differs from the register's, sorted by field
      as bytes (restating the register's own action is not an override, as in crate)
- [ ] Tests: all nine `compare.json` pairs report `register == "1.0.0"` and no overrides; an
      override that changes an action is listed whether or not that field differed; one that
      restates the register is not

## Phase 4: Documentation and the record

- [ ] `NEWS.md` under `## Unreleased`: the re-vendor and version pins, `stac.json` in CI, and
      each **behaviour change** (`stac_fields` refusals, the audit's stricter patterns,
      `Comparison`'s two new fields)
- [ ] `docs/receipts.md` and the `stac_fields`, `compare`, `register` docstrings: the versions,
      the refusal codes and where they are tabled
- [ ] `research/receipt_parity.md`, revised in place: tag `v0.16.0`, the vectors table gains
      `stac.json` (142) and the measured 87-to-142, the "not covered" list loses what is now
      covered, the STAC row count is seven, the header's verified date moves
- [ ] `uv run --group docs mkdocs build --strict` (no `-q`) passes
- [ ] File a stacs issue for a defect found here and left out of scope: the table-cell patterns
      `_DATE` and `_DATETIME` use `.match` with `$` and `\d`, so a date cell with a trailing
      newline is hashed into a fingerprint (measured: `"2026-01-01\n"` passes `_DATE`)

## Validation

- [ ] Tests pass
- [ ] `/code-check` clean (once over the branch with `/code-check branch`)
- [ ] PWF checkboxes match landed work
- [ ] `/planning-archive` on completion

How each change is proved:

- `bash tools/crate_receipt_vendor.sh check` prints `OK` naming the file count and four URLs.
- `uv run pytest` and `uv run --python 3.11 pytest` are green; the `stac.json` runner reports
  142 of 142, against the 87 recorded before Phase 2's code.
- The Phase 1 and Phase 2 mutation tables are written into `findings.md`: each guard removed,
  the test that went red.
- `mkdocs build --strict` prints no warning.
- The version is not bumped here; `/gh-pr-merge` does that with the `## Unreleased` rename.

The Plan review (`planning.md` item 3) is spawned in the background once the baseline is
committed, and its findings are folded in as they land.
