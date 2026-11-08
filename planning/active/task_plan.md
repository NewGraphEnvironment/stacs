# Task: Read, write and compare provenance receipts for catalogue items, passing crate's test vectors (#12)

crate v0.12.0 (2026-11-06, crate#44) settled a **receipt** contract: one record per output
with `output` / `recipe` / `result` / `context` blocks, a `recipe_id` over RFC 8785 canonical
JSON, a frozen draft-07 schema, and test vectors any language can run. crate implements it in
R. The catalogues build and register items in Python, so without a Python implementation each
catalogue either puts R on its publish path or keeps its own provenance fields and sits outside
the provenance every other NGE output carries.

Today across the catalogues: `file:checksum` appears only where a builder downloaded the whole
file; `version` is stamped at release and cleared between; the fields tying an item to how it
was made gate the build and are never published; and `verify` recomputes every body digest on
both sides each run and stores none.

This belongs in stacs: computing ids and writing a receipt from values the builder hands over
reads no source data and builds no item, so it stays inside stacs' source-agnostic boundary.

Reference: `vignette("receipt", package = "crate")` and `research/provenance_receipt.md` at tag
`v0.12.0`.

## Measured before planning

**crate's own Python crosscheck passes every hashing vector in this repo's environment,
today** — `data-raw/receipt_vectors_crosscheck.py` (126 lines, fetched at tag `v0.12.0`)
against the v1.0.0 vectors: `{'numbers.json': 2637, 'jcs.json': 10, 'recipe_id.json': 7,
'fingerprint.json': 13}`, **0 mismatches**, with `rfc8785` 0.1.4 already a declared dependency.
So the hashing core is a port of a script that already agrees byte for byte, and the real work
is everything that script does **not** do: `compare.json`'s nine receipt pairs, schema
validation, the STAC mapping, and the `audit` / `verify` integration.

Both published schemas answer 200 and are draft-07 with **no `$ref` carrying sibling
keywords**, so Python's `jsonschema` and R's ajv read them the same way; the STAC field
schema's `patternProperties: {"^(?!receipt:)": {}}` lookahead is valid in Python `re`.

## Decided at the gate (2026-11-08, the owner)

- **`verify` compares the published receipt against the item's mirrored identity fields**, on
  the published body and on the body pgstac serves — not against a baseline stacs stores.
  Nothing new is stored, so `verify` stays as stateless as `drift`. The fields it can name are
  the mirrored identity set (`receipt:recipe_id`, `file:checksum`, `file:size`,
  `processing:software`, `processing:datetime`), not every receipt member.
- **All seven of the issue's Proposed items land in this PR**; #12 closes on merge, and the
  catalogues get one tag to pin.

Decided without asking (mechanism, with the reason):

- **Vendor crate's vectors and contract data at tag `v0.12.0`** (349 KB total), because
  `conftest.py` refuses every non-loopback lookup for the whole session, so nothing in the
  suite can fetch a vector. Freshness is a CI step *outside* pytest that re-downloads at the
  pinned tag and diffs. An absent or empty vector file **fails**; it never skips.
- **`table_fingerprint` takes the vectors' own column-major shape**, so the vectors exercise
  the public API rather than a test-only adapter.
- **`verify` fetches `receipt.json` only for the ids that already read `missing`/`changed`** —
  that is where "rebuilt or changed?" is asked. Fetching all of them would double the fetch on
  a 102,460-item collection.

## Phase 1: `stacs.receipt` — plain JCS, `recipe_id`, table fingerprint

- [x] `src/stacs/receipt.py`. Module docstring states the boundary, and that this canonical
      form is **frozen** by `output.receipt_version` — the opposite of `verify.canonical_json`,
      whose docstring says the form may change because nothing stores a digest. Add a sentence
      to each naming the other.
- [x] `load_json(text)` — the one reader, `json.loads(..., parse_int=float)`. Every receipt and
      vector entry point goes through it, so the 2^53 trap cannot be reintroduced per call site.
- [x] `canonical(value) -> bytes` — plain `rfc8785.dumps`, **no** STAC rules (no `links`
      removal, no null-member stripping); `float(x)` for an int beyond ±(2^53−1); NaN, Inf and
      a lone surrogate raise a named error, as `verify.DigestError` does.
- [x] `recipe_id(recipe) -> str` — drop `recipe_id`, canonicalize, SHA-256 lowercase hex.
      Refuse a list where the contract says an object keyed by name (`code`, `inputs`,
      `config.files`): a list canonicalizes happily and yields a plausible wrong id.
- [x] `table_canonical(table, tolerance) -> bytes` / `table_fingerprint(...) -> str` — columns
      and rows sorted by UTF-8 bytes, every cell a JSON string or null, types `character`,
      `integer`, `double`, `logical`, `date`, `datetime`; a declared tolerance `10^-k` written
      `format(x, ".kf")` with the `-0.00` strip; NaN/Inf, fractional seconds and years outside
      1–9999 refuse. Built by the specified concatenation, not by serialising a dict.
- [x] `tolerance_decimals(tol)` — power of ten from 1 to 1e-15, `abs(tol / 10.0**-k - 1) < 1e-9`.
- [x] Python's own type refusals (crate's R whitelist has no Python equivalent): `bool` tested
      **before** `int`, so `True` is `"true"` and never `"1"`; `Decimal`; a `datetime` with
      non-UTC `tzinfo`; `bytes` and surrogate-escaped `str`.
- [x] Tests: the two documented traps as named cases (`1152921504606846976` →
      `1152921504606847000`; bits `3e70000000000000` → `5.960464477539063e-8`), and **a test
      that `receipt.canonical` and `verify.canonical_json` disagree** on a body with `links` and
      a null member, so neither is later "simplified" into the other.
- [x] `"receipt"` added to `tests/test_harness.py`'s module tuple, with a doctest to pin.

## Phase 2: crate's vectors and contract data, vendored at `v0.12.0` and diffed in CI

- [x] `tests/vectors/receipt/v1.0.0/` — `numbers.json` (2,637), `jcs.json` (10),
      `recipe_id.json` (7), `fingerprint.json` (13), `compare.json` (9), `README.md`, plus a
      `SOURCE` file naming the repo, tag and each file's blob sha.
- [x] `src/stacs/data/` — the frozen receipt schema, the STAC `receipt:` field schema,
      `register.csv` (43 rows) and `mapping.csv`, each at its versioned path.
- [x] Runner tests read from disk and **fail on an absent or empty vector file** (the
      `assert files, "…this check would pass on anything"` shape the repo already uses).
- [x] A step in `test.yml` **before** pytest (network allowed there, not inside it) that
      re-downloads the vectors and both published schemas at the pinned tag and diffs them
      against the vendored copies; any mismatch fails the build.
- [x] A guard test that the workflow still carries that step at the pinned tag, plus a mutation
      check on the guard itself.
- [x] *(review)* Vendor crate's two worked-case receipts and its example STAC item: the only
      artifacts that can pin the on-disk file format and the mirrored-field shapes. Without
      them Phase 3's byte-identical test would have been written against Python's own output.
- [x] *(review)* Count the frozen URLs the script checked against a literal, because the
      success line claims both were checked; blanking `URLS` passed before.
- [x] *(review)* Make `SOURCE` load-bearing: a test recomputes each git blob sha offline, so
      an edited vendored file fails without the network, and editing `SOURCE` to match fails
      the network diff instead.
- [x] *(review)* The workflow guard reads the step's own block, so `continue-on-error: true`
      or an `if:` on it is a failure rather than a step that is present and guards nothing.

## Phase 3: write, read, validate

- [x] `write(receipt, path)` — the canonical bytes **re-indented as text** at indent 2, `{}`/`[]`
      collapsed, one trailing newline, temp file + `os.replace`, **with the temp file's mode set
      before the rename** (`mkstemp` + `os.replace` otherwise leaves the target at 0600).
      *(review, measured)* Never `json.dumps` an object: JCS writes `0.000001` and `1e-9` where
      `json.dumps` writes `1e-06` and `1e-09`, and crate's worked-case receipt carries both as
      ordinary content. It computes `recipe.recipe_id` itself, and returns the SHA-256 of the
      bytes it wrote, which is what lets an item carry its receipt asset's `file:checksum`.
- [x] `read(path)` — `load_json`, then refuse any `output.receipt_version` but `1.0.0`, as
      crate's reader aborts rather than warns.
- [x] `validate(receipt)` — `jsonschema` against the vendored schema. `jsonschema` is in
      `uv.lock` only transitively via `pystac[validation]`, so declare it directly in
      `pyproject.toml` and re-run `uv lock` **in the same commit** (CI runs `uv sync --locked`).
      *(review)* Forgetting the declaration passes CI, because the transitive copy is there, so
      a test asserts it is in `[project.dependencies]`.
- [x] *(review, measured — and the review's remedy dropped)* `jsonschema` 4.26.0 does accept
      `4.0` for `{"type": "integer"}`, so `validate` is not a guard there. But a whole float and
      an int are **byte-identical in JCS** (`rfc8785.dumps(3.0) == rfc8785.dumps(3)`), and the
      schema *does* refuse `4.5`, so a "check the whole-number members" guard in `write` would
      change nothing: the gap is unobservable in the bytes and in the hash. The property is
      pinned by a test instead — a receipt read back and rewritten is byte-identical although
      `parse_int=float` turned every number into a float.
- [x] *(review)* Load the vendored schema and register **lazily and cached**, never at import:
      the deployment guard imports every module via `pkgutil.walk_packages` and
      `--doctest-modules` imports them too, so an import-time read turns a missing data file
      into a suite-wide collection error instead of one failing test.
- [x] Required-but-nullable members emitted as `null` (`output.scope`, `output.schema`,
      `recipe.code.<repo>.version`, `recipe.seed`, `context.lockfile_sha256`,
      `context.session`); `context.host` dropped entirely when publishing. Empty keyed
      collections are `{}` — pinned by a test that an empty recipe hashes crate's
      `ecb53cd4…0493`.
- [x] `parse_int=float` means `rows`, `bytes` and `seed` read back as floats: a round-trip must
      write them as integers. Test that read → write is byte-identical for crate's two
      worked-case receipts.
- [x] Verify the wheel ships `src/stacs/data/**` (`uv build`, list the wheel) — `uv_build`'s
      package-data behaviour is unverified, and a receipt module that cannot find its schema
      once installed passes every test in the source tree.

## Phase 4: compare — identical / equivalent / different

- [x] `compare(a, b)` → verdict (any `refuse` → `different`; else any `within` → `equivalent`;
      else `identical`) and `differences` as an **ordered list** of `(side, field, action,
      detail)` sorted by field as bytes, duplicates allowed — `a migrated receipt` lists
      `recipe.inputs` and `recipe.config.settings` twice, so a set would be wrong.
- [x] The register walk: collection prefixes derived from the `*` patterns; the collection check
      wins over the leaf check (`recipe.code`, `context.toolchain` are both); leaf equality is
      same-canonical-JSON, so absent and null compare equal; an unrecognised field defaults to
      `refuse`. Field paths are `block.member` with a key in brackets
      (`result.parts[access_check.csv].sha256`), the register's own patterns use `*`.
- [x] `within` from its three sources: `result.summary.*` inside a tolerance **both** receipts
      declare identically (`|a−b| <= tol`); `result.parts.*.{bytes,sha256}` only when both name
      the **same** table, it is in both `result.fingerprint` maps, and every fingerprint
      difference for it resolved to `within`; `result.fingerprint.*.sha256` left `refuse` with
      the `fingerprints differ (receipts only): ` prefix when no tables are supplied.
- [x] A null `recipe_id` on either side always yields one `refuse` at `recipe.recipe_id`, so a
      migrated receipt is never `identical` or `equivalent`.
- [x] Passes all nine `compare.json` pairs on the verdict **and** the exact ordered
      `(field, action)` sequence. This is the half crate's crosscheck script does not cover.
- [x] A mutation test that `register.csv` is load-bearing: flip one row's action, watch a
      verdict change. Honour a caller's register override under crate's rule — known fields
      only, and no `recipe.*` field may be overridden.
- [x] Out of scope and said so: `mode="bytes"` (re-reading supplied tables). The vectors do not
      exercise it; recorded in `research/`.

## Phase 5: STAC identity fields and `audit`

- [x] `stac_fields(receipt, assets)` → item `properties` (`receipt:recipe_id`,
      `processing:datetime` from `context.time`, `processing:software.<repo>` from
      `recipe.code[<repo>].version`) and per-asset `file:checksum` (multihash `1220` + the 64
      hex) and `file:size`, the part keyed by the asset's href relative to the item. A migrated
      receipt (null `recipe_id`) **omits** the field rather than publishing a null.
- [x] `EXTENSION_URL`, listed verbatim in `stac_extensions` — the field schema asserts
      `contains: {const: <that exact URL>}`, and any other `receipt:`-prefixed key fails it.
- [x] *(review)* **Three** extension URLs, not one: crate's example item lists
      `file/v2.1.0` and `processing/v1.2.0` beside the receipt one, because `stac_fields` emits
      `file:*` and `processing:*`. Each is a constant, and `audit` requires the ones whose
      fields are present. An item emitting them without their URLs is non-conformant and the
      vendored field schema cannot notice: it constrains only `receipt:`-prefixed keys.
- [x] *(review)* The receipt asset's own `file:checksum`. `mapping.csv` has no row for it and
      `stac_fields` cannot compute it -- it never sees the receipt's bytes -- so it takes the
      digest `write` returned. This is also what lets `verify` prove it fetched *the* receipt
      the item claims, which is a stronger check than the mirrored compare.
- [x] *(review)* `audit` owns the formats the field schema does not reach: `^1220[0-9a-f]{64}$`
      for a multihash, and the receipt schema's own `context.time` pattern for
      `processing:datetime`. The `file`/`processing` extension schemas are unfetchable offline.
- [x] *(review)* `Target` gains the flag, `Target.check()` a type check, and `build_target`
      plus the `[catalogue]` config key the wiring: `verify` reaches the catalogue only through
      `Target`, so Phase 6 cannot see the declaration without this. A bool default is safe
      under the deployment guard, which exempts bools.
- [x] *(review)* `_run`'s pre-write audit passes the rule too, or `stacs audit` would refuse an
      item that `stacs register` loads.
- [x] *(review, out of scope, said rather than left silent)* `mapping.csv`'s sixth `STAC item`
      row, `properties.version` from `context.legacy`, is a release label and not provenance.
- [x] `audit_items(..., require_receipt=False)`: for a collection that declares it carries
      receipts, an item fails when `receipt:recipe_id` is absent or ill-formed, the extension
      URL is not listed, or the receipt fields fail the **vendored** field schema. Offline, by
      `jsonschema` — not via pystac, which fetches the extension URL and would die on the test
      guard. `Audit` gains `missing_receipt` / `bad_receipt` **path** lists, and `rules` reports
      the check as applied.
- [x] CLI `--require-receipt` + `[catalogue] require_receipt`, wired into `cmd_audit` and
      `load items`, under the existing precedent: declared rules are the caller's, never keyed
      by collection id, and a flag may add a rule but never remove a configured one.

## Phase 6: `verify` reads receipts

**Corrected by the plan review** (`review-plan.md` B2, reproduced against the vendored
`register.csv`). Comparing a full receipt against a five-field projection of itself is not a
receipt pair, so it does not get crate's words: all four identity fields a served item carries
are `refuse` in the register and the fifth is `record`, and `within` needs members a served
item does not have (`result.summary` with its tolerance, `parts.*.table` with both
`fingerprint` maps, or re-read tables). The reachable verdicts there are `identical` and
`different` only, so the issue's `equivalent` cannot occur and a test asserting it could never
pass. `receipt.compare()` keeps crate's three words for two receipts, which the vectors
require; **`verify` reports its own ladder and says so in its output.**

- [x] `same`, `rebuilt`, `changed`, `inconsistent` — `rebuilt` is the case the issue is for
      (`receipt:recipe_id` agrees on both sides, a mirrored result field differs), and
      `inconsistent` is an item whose own mirrored fields disagree with the receipt it links.
      The output names these as stacs' verdicts, not crate's.
- [x] *(review)* A served-side reader: both existing API readers reduce a feature to
      `body_digest(f)` and discard it, so `fields_serving` returns the mirrored properties per
      id over the existing paging.
- [x] *(review)* Resolve the receipt from the item's **asset with role `metadata`** and against
      the item's own URL, not from "`receipt.json` beside the item" — that is a convention, the
      asset link is the contract, and a catalogue with a `receipts/` prefix would break the
      convention silently. It also makes the fixtures expressible: the existing harness writes
      every item flat, so the convention would be one shared receipt for every item.
- [x] *(review)* Receipts fetch into their **own** directory: `fetch_bodies` refuses a
      non-empty one, and `fetch_dir` is full by then. An unread receipt raises from the returned
      failed list rather than relying on `fetch_bodies`' own stderr print, which bypasses the
      injected `warn`.
- [x] *(review)* Verify the fetched receipt against the receipt asset's `file:checksum` before
      comparing anything — otherwise there is no way to tell it fetched the receipt the item
      claims.
- [x] *(review)* Skip the axis when the collection is not registered, and bound it: "only
      `missing`/`changed`" is a filter, not a bound, and on an unregistered collection every id
      is `missing`. A `missing` id has no served side at all, so it is checked for consistency
      with its own receipt only, and the output says which check ran.
- [x] *(review)* Report a summary plus the first five through `warn`, as the DRIFT block does:
      `_write_list` is a no-op when `out_dir is None`, which is `cmd_verify`'s default, so
      per-item verdicts would otherwise go nowhere in the default invocation. Full lists still
      go to `out_dir` when there is one.
- [x] *(review)* `same` on an id that reads `changed` is the common case — a bbox fix changes
      the body and not the recipe — so it is reported as "the body differs and the recipe does
      not", never as a bare verdict beside a DRIFT line.
- [x] Placement: inside `if mode == "verify":`, after the `_write_list` calls and before `rc` is
      computed. In the shared `drift`/`verify` branch, `drift` would pay for the fetch on ids it
      is about to overwrite, and an unreadable receipt would abort a legitimate registration.
- [x] Tests on the existing `file://` bucket + stub API harness, with each item linking its own
      receipt asset: a positive control (edit one receipt → `changed`, naming the field), a
      rebuilt item (same `recipe_id`, different `file:checksum` → `rebuilt`), an item whose
      mirrored fields contradict its receipt (→ `inconsistent`), and an unreadable receipt
      (→ failure, never `same`).

## Phase 7: docs, NEWS, research

- [ ] `docs/reference/receipt.md` **and** the `mkdocs.yml` nav entry — under `strict: true`
      with nav validation at `warn`, either one alone fails the build.
- [ ] README: a `What it does` bullet and a matched `[start:receipt]` / `[end:receipt]` marker
      pair, included from a page, with links absolute (a relative one resolves against `docs/`).
- [ ] `NEWS.md`: a new `## Unreleased` section (there is none now).
- [ ] `research/receipt_parity.md` with the provenance header, and in `research/README.md`'s
      table: what the vectors cover and the one thing they do not, the two traps, the probed
      schema facts, the measured 2,667/2,667 pass, crate#50's R-only 2^31-1 fingerprint limit
      that Python does not share, and the cross-language scalar-vs-array hazard in
      `config.settings` (R's `I()` unboxing — two different `recipe_id`s for one intent).

## Owed at the end (reported, done after merge)

- [ ] Adoption issues in the catalogue repos, pinning the tag this ships in.

## Validation

- [ ] Tests pass (`uv run pytest`), 3.11 and 3.12
- [ ] `/code-check branch` clean, three-round floor
- [ ] All 2,667 hashing vectors and all 9 compare pairs green through stacs' own public API,
      not through a copy of crate's crosscheck script
- [ ] `uv build` + wheel listing shows the vendored contract data ships
- [ ] `mkdocs build --strict` (never `-q`) clean
- [ ] `tests/test_no_deployment_defaults.py` green with the narrow
      `newgraphenvironment.github.io/crate/` carve-out, and a mutation check showing anything
      else still fails
- [ ] PWF checkboxes match landed work; `/planning-archive`, then `/gh-pr-push`

### A guard that needs its own note

`test_no_deployment_defaults.py::test_no_source_file_names_a_deployment` greps
`src/stacs/**/*.py` for `"newgraphenvironment"`. The frozen schema URLs are
`https://newgraphenvironment.github.io/crate/...` and are part of the contract — written into
every receipt-bearing item's `stac_extensions`. The carve-out goes **in the guard**, narrowly
and with a mutation test, rather than hiding the URLs in a data file the grep does not read:
that would be an escape hatch, not an exception.
