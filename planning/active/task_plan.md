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

## Phase 3: write, read, validate

- [ ] `write(receipt, path)` — JCS pretty-printed at indent 2, `{}`/`[]` collapsed, one trailing
      newline, temp file + `os.replace`, **with the temp file's mode set before the rename**
      (`mkstemp` + `os.replace` otherwise leaves the target at 0600).
- [ ] `read(path)` — `load_json`, then refuse any `output.receipt_version` but `1.0.0`, as
      crate's reader aborts rather than warns.
- [ ] `validate(receipt)` — `jsonschema` against the vendored schema. `jsonschema` is in
      `uv.lock` only transitively via `pystac[validation]`, so declare it directly in
      `pyproject.toml` and re-run `uv lock`.
- [ ] Required-but-nullable members emitted as `null` (`output.scope`, `output.schema`,
      `recipe.code.<repo>.version`, `recipe.seed`, `context.lockfile_sha256`,
      `context.session`); `context.host` dropped entirely when publishing. Empty keyed
      collections are `{}` — pinned by a test that an empty recipe hashes crate's
      `ecb53cd4…0493`.
- [ ] `parse_int=float` means `rows`, `bytes` and `seed` read back as floats: a round-trip must
      write them as integers. Test that read → write is byte-identical for crate's two
      worked-case receipts.
- [ ] Verify the wheel ships `src/stacs/data/**` (`uv build`, list the wheel) — `uv_build`'s
      package-data behaviour is unverified, and a receipt module that cannot find its schema
      once installed passes every test in the source tree.

## Phase 4: compare — identical / equivalent / different

- [ ] `compare(a, b)` → verdict (any `refuse` → `different`; else any `within` → `equivalent`;
      else `identical`) and `differences` as an **ordered list** of `(side, field, action,
      detail)` sorted by field as bytes, duplicates allowed — `a migrated receipt` lists
      `recipe.inputs` and `recipe.config.settings` twice, so a set would be wrong.
- [ ] The register walk: collection prefixes derived from the `*` patterns; the collection check
      wins over the leaf check (`recipe.code`, `context.toolchain` are both); leaf equality is
      same-canonical-JSON, so absent and null compare equal; an unrecognised field defaults to
      `refuse`. Field paths are `block.member` with a key in brackets
      (`result.parts[access_check.csv].sha256`), the register's own patterns use `*`.
- [ ] `within` from its three sources: `result.summary.*` inside a tolerance **both** receipts
      declare identically (`|a−b| <= tol`); `result.parts.*.{bytes,sha256}` only when both name
      the **same** table, it is in both `result.fingerprint` maps, and every fingerprint
      difference for it resolved to `within`; `result.fingerprint.*.sha256` left `refuse` with
      the `fingerprints differ (receipts only): ` prefix when no tables are supplied.
- [ ] A null `recipe_id` on either side always yields one `refuse` at `recipe.recipe_id`, so a
      migrated receipt is never `identical` or `equivalent`.
- [ ] Passes all nine `compare.json` pairs on the verdict **and** the exact ordered
      `(field, action)` sequence. This is the half crate's crosscheck script does not cover.
- [ ] A mutation test that `register.csv` is load-bearing: flip one row's action, watch a
      verdict change. Honour a caller's register override under crate's rule — known fields
      only, and no `recipe.*` field may be overridden.
- [ ] Out of scope and said so: `mode="bytes"` (re-reading supplied tables). The vectors do not
      exercise it; recorded in `research/`.

## Phase 5: STAC identity fields and `audit`

- [ ] `stac_fields(receipt, assets)` → item `properties` (`receipt:recipe_id`,
      `processing:datetime` from `context.time`, `processing:software.<repo>` from
      `recipe.code[<repo>].version`) and per-asset `file:checksum` (multihash `1220` + the 64
      hex) and `file:size`, the part keyed by the asset's href relative to the item. A migrated
      receipt (null `recipe_id`) **omits** the field rather than publishing a null.
- [ ] `EXTENSION_URL`, listed verbatim in `stac_extensions` — the field schema asserts
      `contains: {const: <that exact URL>}`, and any other `receipt:`-prefixed key fails it.
- [ ] `audit_items(..., require_receipt=False)`: for a collection that declares it carries
      receipts, an item fails when `receipt:recipe_id` is absent or ill-formed, the extension
      URL is not listed, or the receipt fields fail the **vendored** field schema. Offline, by
      `jsonschema` — not via pystac, which fetches the extension URL and would die on the test
      guard. `Audit` gains `missing_receipt` / `bad_receipt` **path** lists, and `rules` reports
      the check as applied.
- [ ] CLI `--require-receipt` + `[catalogue] require_receipt`, wired into `cmd_audit` and
      `load items`, under the existing precedent: declared rules are the caller's, never keyed
      by collection id, and a flag may add a rule but never remove a configured one.

## Phase 6: `verify` reads receipts

- [ ] For the ids that read `missing`/`changed` only, fetch `receipt.json` beside the item with
      the existing `fetch_bodies` workers, and compare it against the mirrored identity fields
      on the published body and on the body the API serves.
- [ ] Per item a verdict and the field that differed, written beside `missing.txt` /
      `changed.txt` / `orphaned.txt` in `out_dir`. `equivalent` (same `recipe_id`, different
      bytes) is reported as a rebuild and still exits 1 — drift is drift. An unread receipt is
      an error, never `identical`.
- [ ] A collection that declares no receipts skips the axis and says so in the banner, the way
      `queryables : none declared` already does.
- [ ] Tests on the existing `file://` bucket + stub API harness with receipts beside the items:
      a positive control (edit one receipt → `different`, naming the field), a rebuilt item
      (→ `equivalent`), and an unreadable receipt (→ failure).

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
