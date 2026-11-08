# Findings — Read, write and compare provenance receipts for catalogue items (#12)

## Issue context

**If we do it:** the catalogues, whose items are built and registered mostly in Python, write
provenance receipts in the same shape as the R packages without taking R onto their publish path.
`verify` compares what is published and served against stored receipts and answers identical,
equivalent or different per item, so a rebuilt item can be told apart from a changed one, and a
catalogue's provenance can be compared with the outputs of the packages it is built from. **If we
never do:** each catalogue either calls R to write its receipts, adding R setup to every publish,
or keeps its own fields, and the catalogues sit outside the provenance every other output carries.

### Problem

Across the catalogues today:

- Some assets publish `file:checksum` and `file:size`, but only where the builder downloaded the
  whole file; an asset read at an overview over HTTP carries none.
- `version` is stamped on a collection at release and cleared between releases.
- The fields that tie an item to how it was made (a pipeline commit, the version of the package that
  georeferenced it, a footprint digest, the source file's md5, listing ETags) gate the build and are
  never published.
- `verify` recomputes every item body's digest on both sides each run and stores none.

NewGraphEnvironment/crate#43 defines a receipt: one per output, with `output`, `recipe`, `result` and `context` blocks,
a `recipe_id` over RFC 8785 canonical JSON, a JSON Schema, and test vectors any language can run.
crate implements it in R. The catalogues need a Python implementation that agrees with it byte for
byte.

### What crate shipped (v0.12.0, 2026-11-06)

The contract is settled in crate [v0.12.0](https://github.com/NewGraphEnvironment/crate/releases/tag/v0.12.0)
(NewGraphEnvironment/crate#44). The reference is `vignette("receipt", package = "crate")`.

- **Schema:** `https://newgraphenvironment.github.io/crate/receipt/v1.0.0/schema.json` (draft-07), frozen once published.
- **Hash:** SHA-256 everywhere (`recipe_id`, table fingerprints, parts), lowercase hex.
- **`recipe_id`:** the SHA-256 of the RFC 8785 JSON of the `recipe` block without its own `recipe_id`.
  Collections in the recipe (`code`, `inputs`, `config.files`) are objects keyed by name, never arrays.
- **Table fingerprint:** the SHA-256 of the RFC 8785 JSON of `{"columns": [...], "rows": [[...], ...]}`.
  Columns are sorted by UTF-8 bytes, every cell is a string or null, and rows are sorted by the bytes of their own JSON.
  A double with a declared tolerance `10^-k` is written with `k` decimals as `format(x, ".kf")` writes it.
- **Test vectors:** `inst/extdata/receipt/vectors/v1.0.0/` at tag `v0.12.0`:
  - 2,637 number spellings, every power of two among them
  - canonical JSON cases
  - `recipe_id`s
  - table fingerprints
  - nine receipt pairs with their verdicts
  - a README giving each file's format
  `data-raw/receipt_vectors_crosscheck.py` in crate already recomputes every hashing vector in Python with `rfc8785`, with no mismatch. It is a starting point for `stacs.receipt`.
- **Two traps the vectors catch:**
  - Read every JSON number as a double (`json.loads(..., parse_int=float)`). Otherwise `rfc8785` refuses integers past 2^53.
  - At a power of two, the shortest spelling can be printf's neighbour: 2^-24 is `5.960464477539063e-8`.
- **Comparison:** verdicts `identical`, `equivalent` or `different`, each field written as `block.member[key]`.
  Each field's action comes from the register (`inst/extdata/receipt/register.csv`): `refuse`, `warn`, `record`, or `within` its tolerance.
  A part whose bytes change is `equivalent` only when it names a table (`result.parts.<path>.table`) whose fingerprint agrees.
- **`receipt:` STAC field schema:** `https://newgraphenvironment.github.io/crate/stac/receipt/v1.0.0/schema.json`, with `receipt:recipe_id` (64 hex).
  An item built from a migrated receipt, which has a null `recipe_id`, leaves the field out.
- **Mapping table:** `inst/extdata/receipt/mapping.csv` pairs receipt keys with `file:checksum` (multihash `1220…`), `file:size`, `processing:software` and `processing:datetime`.

### Proposed

- [ ] **`stacs.receipt`**: write, read, validate (against the schema URL above), compare,
      and `recipe_id`. The builder hands it values; it computes the ids and writes the receipt. It
      reads no source data and builds no item, so it stays inside stacs' scope of source-agnostic
      work on a catalogue.
- [ ] **Plain RFC 8785 for receipts.** `canonical_json()` already serializes JCS through `rfc8785`,
      but drops `links` and null members for pgstac's round trip. A receipt's `recipe_id` uses
      plain JCS as crate's specification states, with no STAC rules applied.
- [ ] **crate's test vectors in CI**, fetched at crate tag `v0.12.0` (`inst/extdata/receipt/vectors/v1.0.0/`); any mismatch
      fails the build. They are the only thing keeping the two implementations aligned.
- [ ] **A stored id freezes its form.** `canonical_json()`'s docstring says the digest form can change
      with no migration because nothing stores a digest. A stored `recipe_id` cannot, so the
      receipt's canonical form moves only with a new receipt schema version.
- [ ] **Items carry the receipt's identity fields**: `receipt:recipe_id` under crate's `receipt:`
      STAC field schema (crate#23's pattern, listed in `stac_extensions`), with `file:checksum`,
      `file:size`, `processing:software` and `processing:datetime` per crate's mapping table.
- [ ] **`verify` reads stored receipts**: per item it reports identical, equivalent or different
      and the field that differed. Body digests stay as the check that what pgstac serves is what
      was published.
- [ ] **`audit` refuses an item whose receipt fields are missing or do not validate**, for a
      collection that declares it carries receipts.

**Decided (2026-11-05):** each item's receipt is its own `receipt.json`, published beside the item
and linked from it as an asset with role `metadata`, as for every other output. The largest
collection today gains 102,460 objects. The identity fields above are mirrored into the item so a
STAC client or a queryable needs no second fetch; the receipt is the full record of how the item
was made.

Each catalogue adopts it in its own issue, once this ships.

Relates to NewGraphEnvironment/crate#43, NewGraphEnvironment/crate#23

The issue carries no comments (checked 2026-11-08).

---

## Measured: Python already agrees on every hashing vector

2026-11-08, this repo's environment (`uv run`, CPython 3.12.13, `rfc8785` 0.1.4). crate's own
`data-raw/receipt_vectors_crosscheck.py` at tag `v0.12.0`, run against the v1.0.0 vectors
downloaded at the same tag:

```
cases: {'numbers.json': 2637, 'jcs.json': 10, 'recipe_id.json': 7, 'fingerprint.json': 13}
0 mismatch(es)
```

**What this closes:** the hashing core (number spelling, JCS, `recipe_id`, table fingerprint) is a
port of a 126-line script that already agrees byte for byte, with no library work needed.

**What it does not close**, and where the work therefore is: `compare.json`'s nine receipt pairs
(the crosscheck script does not implement comparison at all), schema validation, the STAC mapping,
and the `audit` / `verify` integration.

## Probed facts about the two published schemas

Both answer 200 (2026-11-08): the receipt schema is 8,450 B, the STAC field schema 2,882 B.

- Both are draft-07, `$id` equal to their published URL.
- **No `$ref` anywhere carries sibling keywords**, so Python's `jsonschema` and R's ajv read them
  identically (`code-check-r.md`: "ajv honours keywords beside a `$ref`; Python's jsonschema
  ignores them").
- The STAC field schema's `patternProperties: {"^(?!receipt:)": {}}` uses a negative lookahead,
  which Python's `re` supports, so it is not an ECMA-only construct.
- The receipt schema's own `definitions`: `config`, `context`, `input`, `name`, `output`, `recipe`,
  `recipe_migrated`, `result`, `sha256`, `tolerance`.

## The receipt document, from the frozen schema

Top level is **exactly** `output`, `recipe`, `result`, `context`, `additionalProperties: false`.
There is **no schema-URL member inside a receipt**; the version is `output.receipt_version`
(`const "1.0.0"`), and `recipe_id` lives only at `recipe.recipe_id`. The schema switches on
`output.migrated_from`: present → `recipe_migrated` (every field optional, `recipe_id` **null**),
absent → `recipe`.

| block | required | notes |
|---|---|---|
| `output` | `name`, `scope`, `receipt_version`, `schema` | `scope` and `schema` are required **but nullable**; `migrated_from` optional |
| `recipe` | `code`, `config`, `inputs`, `seed`, `recipe_id` | `code` keyed by repo → `{commit (40 hex), version (nullable), dirty}`; `config` = `{files, settings}`, `files` keyed by path → sha256; `inputs` keyed by name → an object with **exactly one** of `recipe_id`/`version_id`/`sha256`/`none` |
| `result` | `fingerprint`, `parts`, `summary`, `tolerance` | `fingerprint.<table>.{sha256,rows}`; `parts.<path>.{bytes,sha256,table?}`, path relative, no leading slash; `tolerance` = `{tables, summary}` |
| `context` | `time` only | optional `host`, `run`, `session`, `toolchain`, `lockfile_sha256`, `inputs`, `legacy`. `host` is **dropped entirely** when publishing, not nulled |

`tolerance` is an **enum** of the powers of ten 1 … 1e-15, not a numeric range.

On disk, `receipt.json` is the canonical JSON **pretty-printed at indent 2** (so keys are in JCS
order), with `{}` / `[]` collapsed, one trailing newline, written temp-file-then-rename.

## Comparison semantics

Verdict: any `refuse` → `different`; else any `within` → `equivalent`; else `identical`. **`warn`
and `record` never change the verdict** — the `toolchain only` vector is `identical` *with* a
listed `record` difference.

- Field paths are `block.member` with a key in brackets (`result.parts[access_check.csv].sha256`),
  because keys contain dots. The register's own patterns use `*` (`result.parts.*.sha256`).
- A key present on one side only is reported at the **collection's** own path with no bracket
  (`recipe.inputs`, detail `<key> only in a`), so one comparison can list the same field twice.
  `differences` is therefore an **ordered list, not a set**, sorted by field as bytes.
- The collection check wins over the leaf check: `recipe.code` and `context.toolchain` are both
  register leaves *and* collection prefixes.
- Leaf equality is "same canonical JSON", so **absent and null compare equal**.
- An unrecognised field defaults to **`refuse`**.
- Collection prefixes derived at v1.0.0: `recipe.code`, `recipe.config.files`,
  `recipe.config.settings`, `recipe.inputs`, `result.fingerprint`, `result.parts`,
  `result.summary`, `result.tolerance.tables`, `result.tolerance.tables.*`,
  `result.tolerance.summary`, `context.toolchain`.

`register.csv` is 43 rows of `field,action,why`: **31 `refuse`**, **3 `warn`**
(`output.receipt_version`, `output.schema`, `output.migrated_from`), **9 `record`** (all of
`context`). Only `field` and `action` are read. A caller's override may name known fields only,
must be one of `refuse|warn|record`, and **no `recipe.*` field may be overridden** ("every recipe
field refuses, because `recipe_id` covers it").

`within` is **not** in the register — the comparison produces it, from three places:

1. `result.summary.*`, when both receipts declare the **same** tolerance for it and
   `|a − b| <= tol` (inclusive). A differing tolerance is its own refusal.
2. `result.parts.*.{bytes,sha256}`, only when both receipts name the **same** table for the part,
   that table is in both `result.fingerprint` maps, and every fingerprint difference for it
   resolved to `within` (vacuously true when the fingerprints are equal). Otherwise `refuse` —
   "a file that names no table, such as a raster nobody fingerprinted, is `different`".
3. `result.fingerprint.*.sha256`, settled by re-reading supplied tables (`mode = "bytes"`). With
   no tables it stays `refuse` with detail prefixed `fingerprints differ (receipts only): `.

A null `recipe_id` on either side always produces one `refuse` at `recipe.recipe_id`, so a
migrated receipt is never `identical` or `equivalent`.

## The vectors

Every file is a UTF-8 JSON array of case objects, each with a `name`. 349 KB in total:
`numbers.json` 274,479 B, `compare.json` 63,373 B, `fingerprint.json` 9,220 B,
`recipe_id.json` 5,239 B, `README.md` 2,673 B, `jcs.json` 2,458 B.

| file | each case | check |
|---|---|---|
| `numbers.json` (2,637) | `bits` (double, 16 hex, big-endian), `expected` | RFC 8785 spelling of the double |
| `jcs.json` (10) | `input_json`, `expected` | parse, serialize, equals `expected`. Two cases are top-level **scalars** |
| `recipe_id.json` (7) | `recipe_json`, `jcs`, `recipe_id` | parse, drop `recipe_id`, serialize == `jcs`; sha256 of its UTF-8 bytes == `recipe_id` |
| `fingerprint.json` (13) | `table`, `tolerance`, `canonical`, `sha256` | canonical form == `canonical`; sha256 == `sha256` |
| `compare.json` (9) | `a`, `b`, `verdict`, `differences` | receipts alone give `verdict` and the ordered `(field, action)` list |

`table` is column-major: `{"columns": {<name>: {"type": <t>, "values": [...]}}}` with `t` one of
`character`, `integer`, `double`, `logical`, `date`, `datetime`. **Doubles are given as bits**, so
no decimal parser stands between the vector and the value. Dates `YYYY-MM-DD`, datetimes
`YYYY-MM-DDTHH:MM:SSZ`, `null` is NA. `tolerance` maps a column to a power of ten.

Landmark values to self-check against:

- empty recipe → JCS `{"code":{},"config":{"files":{},"settings":{}},"inputs":{},"seed":null}`,
  `recipe_id` `ecb53cd4e03b09490f6c581b1195aa9635e5fff51790d64e19d2a2a79f8a0493`
- the worked case and the same members in another order share
  `eff3a5b85b2bb8e2f085537378568703b2ed97583dcb455266d86289a91a638f` (the order-independence proof)
- a recipe carrying its own `recipe_id` hashes as if it were absent
- `2^-24` (bits `3e70000000000000`) → `5.960464477539063e-8`; `2^-1074` → `5e-324`;
  `2^60` → `1152921504606847000`
- `jcs.json` "integers and whole doubles": `[0,-0,1,-1,100,1.0,4.50,1e2,9007199254740992]` →
  `[0,0,1,-1,100,1,4.5,100,9007199254740992]`
- empty table → `{"columns":["a","b"],"rows":[]}`,
  `4b50177c31441e4ae3e6691a6f82a75a30a21f197dd400e7a9a781c99eff4d36`
- row order is **byte** order, so `["a b"]` sorts before `["a"]` (space 0x20 < quote 0x22), and a
  `null` cell sorts after any quoted string

The nine compare pairs and their verdicts: `worked case, km within tolerance` → equivalent;
`a receipt and itself` → identical (no differences); `toolchain only` → identical (one `record`);
`another run setting` → different; `another seed` → different; `bytes moved in a file that names
no table` → different; `summary value past its tolerance` → different; `fingerprints differ,
receipts only` → different; `a migrated receipt` → different (16 differences, with
`recipe.config.settings` and `recipe.inputs` each listed **twice**).

## The STAC side

Extension URL, listed verbatim in `stac_extensions`:
`https://newgraphenvironment.github.io/crate/stac/receipt/v1.0.0/schema.json`. The schema asserts
`stac_extensions` `contains: {const: <that exact URL>}`, and **any `receipt:`-prefixed key other
than `receipt:recipe_id` fails validation**. Scope: Item properties, Item and Collection assets,
Collection `item_assets`, and Collection `summaries` (as an array). Every field is optional.

Receipt key → STAC key, from `mapping.csv`'s `STAC item` rows:

| receipt key | STAC key | transform |
|---|---|---|
| `recipe.recipe_id` | `properties.receipt:recipe_id` | none; **omitted** when null (migrated) |
| `context.time` | `properties.processing:datetime` | none |
| `recipe.code[<repo>].version` | `properties.processing:software.<repo>` | none; a third-party tool goes to `context.toolchain` instead |
| `result.parts[<path>].sha256` | `assets.<key>.file:checksum` | **multihash**: `1220` + the 64 hex (68 chars) |
| `result.parts[<path>].bytes` | `assets.<key>.file:size` | none |
| `context.legacy` | `properties.version` | a release label, not provenance |

The asset's href relative to the item **is** the part's path. `crt_receipt_stac()` (writing the
fields onto an item) is explicitly "Not in v1" in crate, so the Python side is the first
implementation of it.

## Traps and asymmetries between the two implementations

- **Read every JSON number as a double.** `json.loads(..., parse_int=float)`; `rfc8785` refuses an
  int past 2^53. Consequence: `rows`, `bytes` and `seed` come back as floats, so a round-trip must
  write them back as integers (the schema types them `integer`).
- **The power-of-two spelling.** Non-issue in Python — `rfc8785` uses Python's shortest-round-trip
  formatting, which is correct at ties. It is why `numbers.json` carries all 2,098 powers of two.
  R needed a bisection search reading candidates back through jsonlite's `strtod`, because R's
  `as.numeric()` is not correctly rounded on arm64.
- **Two sort orders.** Object **keys** sort by UTF-16 code units (JCS, let `rfc8785` do it); table
  **columns and rows** sort by UTF-8 bytes. They differ above U+FFFF.
- **Empty keyed collections are `{}`.** An R-ism baked into the contract (crate has
  `receipt_object()` to force it). Python dicts do it naturally, but `[]` or `None` for "no inputs"
  gives a different `recipe_id` and a schema failure.
- **`config.files` keys enter `recipe_id`,** so they must be checkout-independent: crate refuses an
  unnamed absolute, `~` or `..` path, and hashes the file's bytes **as checked out** with no
  line-ending normalisation.
- **`bool` is an `int` subclass in Python.** `str(int(True))` would write `"1"` where the contract
  wants `"true"` — test `bool` first.
- **Scalar vs array in `config.settings`.** R's length-one vector auto-unboxes, so an R-written
  receipt may hold `"CO"` where a Python one holds `["CO"]` — **two different `recipe_id`s for one
  intent**. Any cross-language output must agree per setting.
- **crate#50 is open:** `crt_table_fingerprint()` fails on a table whose canonical JSON passes
  2^31-1 bytes (an R string limit; 4,033,543 × 34 hit it). Python has no such limit, so the
  implementations diverge in **reach**, not in bytes. The vectors are small, so parity is
  unaffected.
- **`result.fingerprint` is not a schema fingerprint.** crate's `crt_schema_fingerprint()` hashes
  column names and types and stays XXH64; do not reuse SHA-256 there or conflate the two.

## Constraints this repo imposes

- `tests/test_no_deployment_defaults.py::test_no_source_file_names_a_deployment` greps
  `src/stacs/**/*.py` for `"newgraphenvironment"` (lowercased). The frozen schema URLs contain it,
  so the guard needs a narrow, mutation-tested carve-out — not a data file that dodges the grep.
- `conftest.py` refuses every non-loopback lookup and connection for the whole session
  (`pytest_configure`), so nothing in the suite can fetch a schema or a vector, and pystac
  validation of an item listing the receipt extension would fail on the fetch.
- `tests/test_harness.py::test_docstring_examples_are_collected` pins a hardcoded tuple
  `("verify", "catalogue", "validate", "register")` in a child pytest process; a new module joins
  it and must carry at least one doctest.
- `mkdocs.yml` is `strict: true` with nav validation at `warn`, so a new module needs **both**
  `docs/reference/receipt.md` and a nav entry. A module docstring may not name `research/`,
  `planning/` or `CLAUDE.md` (snippets `base_path: ["."]`).
- `jsonschema` 4.26.0 is in `uv.lock` only transitively, via `pystac[validation]`.
- `.gitignore` has no pattern that would ignore `tests/vectors/`; a cache directory would need a
  new entry, and `build/` and `dist/` are unanchored, so those names must be avoided.
- `test.yml` has no job-level `concurrency` (so the 3.11 / 3.12 matrix cannot cancel itself) and no
  `timeout-minutes` anywhere.
- `NEWS.md` has no `## Unreleased` section; `pyproject.toml` is at 0.2.0, matching the top heading.

## Errors Encountered

| Error | Resolution |
|-------|------------|
| `/claude-md-init` and `/planning-init` bash blocks refused: "this shell (bash 3.2.57) is too old to run it reliably" | Wrote each block to a script file in the scratchpad and ran `bash <file>`; the skills' blocks use `$(...)`-heavy preambles the harness will not pass through inline |
| Local `~/Projects/repo/crate` checkout is at v0.11.0, so it carries no receipt code | Read every crate file from GitHub at tag `v0.12.0` with `gh api -H "Accept: application/vnd.github.raw"`; do not expect the local checkout to answer |
