# Findings — stacs: package the pgstac registration and verification layer (#1)

## Issue context

## Problem

The part of our STAC tooling that is genuinely shared across catalogue repos is
**registration and verification**, and it is not packaged. It is copied, it has drifted,
and one repo already runs it out of another repo's checkout.

Measured 2026-09-30 on each repo's `origin/HEAD`:

| script | copies | state |
|---|---|---|
| `item_register.sh` | 4 (dem, uav, orthophoto, floodplains) | 4 different hashes, 43–138 lines |
| `collection_register.sh` | 3 (dem, uav, floodplains) | 3 different hashes, 32–129 lines |
| `item_validate.py` | 4 (dem, uav, orthophoto, floodplains) | 4 different hashes, 49–1,806 lines |
| `catalogue_register.sh` + `register_manifest.py` (~1,550 lines) | 1 (`stac_dem_bc`) | `stac_airphoto_bc/scripts/run_pipeline.sh:67` runs it by `cd ~/Projects/repo/stac_dem_bc` |

That last row is the compartmentalisation failure: airphoto's registration depends on this
repo's working tree being on `main` with a working `.venv`.

What only this repo's copy knows, because each was learned the expensive way: upsert,
never delete-then-load (the 2026-08-29 outage); collection before items; verify by id
**sets** in both directions, never counts; verify **bodies** by canonical digest (NewGraphEnvironment/stac_dem_bc#45);
password through PG* env, never argv; `find -exec cat {} +`, never a glob. The other
copies carry some or none of these.

## Scope change (2026-09-30)

This issue originally proposed extracting the whole Python pipeline (`item_create`,
`stac_utils`, `collection_create`, …). That targets the wrong half. **Item creation
is per-source and stays in each repo**: DEM/DSM pairing here, ODM outputs in uav,
georeferenced scans in airphoto, and PDAL-read `.laz` in the coming
`stac_pointcloud_bc`. What every repo repeats, and gets wrong differently, is getting a
catalogue into pgstac and proving it arrived.

## The package: `stacs`

Repo `NewGraphEnvironment/stacs` (public), import `stacs`, CLI `stacs`. Managed with uv
(`pyproject.toml` + committed `uv.lock`, as `stac_floodplains_bc` already is) and
installed from git by its consumers:

```toml
[tool.uv.sources]
stacs = { git = "https://github.com/NewGraphEnvironment/stacs", tag = "v0.1.0" }
```

**Never published to PyPI.** The name there belongs to an unrelated credential scanner
(stacscan/stacs, archived 2023-05). A git source means uv never consults PyPI for it, so
the collision only matters to someone typing `pip install stacs`. If we ever publish,
it gets a different distribution name.

### What goes in it, and what does not

**`stacs` holds what is source-agnostic: anything done to a STAC catalogue after its
items exist.** Reading a source to build items stays in the repo that owns the source
(DEM/DSM pairing here, ODM outputs in uav, PDAL headers in the point cloud repo). This
sentence goes in the README's first paragraph; it is what keeps a broad name from
becoming a junk drawer.

**It carries no NGE context.** It is a public tool (soul `newgraph.md`, three-layer
architecture), so the STAC host, database, API URL, bucket and collection are parameters
supplied by each catalogue repo, never package defaults. `root@geopro` and
`images.a11s.one` stay in `stac_dem_bc` and its siblings.

### Modules

| module | does | when |
|---|---|---|
| `stacs.verify` | id-set diff in both directions, body digest, post-register content check | this issue |
| `stacs.register` | collection-then-items upsert; `verify` / `drift` / `all` / `ids` modes | this issue |
| `stacs.validate` | `pystac` item validation, plus each catalogue's declared asset rules (replacing NewGraphEnvironment/stac_dem_bc#42's bucket test) | this issue |
| `stacs.publish` | S3 upload: items before collection, never `--delete` (`s3_sync-ci.sh`) | next |
| `stacs.checksum` | `file:checksum` helpers for builders that host their own bytes | when a second repo wants it |

### Hashing scope

Three different hashes, and only the first is this package's core:

| hash | answers | lives |
|---|---|---|
| item body digest (NewGraphEnvironment/stac_dem_bc#45) | is the API serving the body we published | `stacs.verify` |
| asset `file:checksum` | which bytes did this item mean | each repo's item builder; `stacs.validate` may require the field, never recomputes it |
| Merkle root (stacchain) | can a third party prove the catalogue unaltered | not now; computed over the static catalogue before upload, so build-side if ever |

**Canonicalise with RFC 8785 (JCS).** stacchain's Merkle tooling hashes RFC 8785 JSON,
so matching it now lets a later Merkle layer reuse our leaf hashes. JCS formats numbers
as ECMAScript does, which should subsume the integral-float normalisation
(`-126.0` → `-126`); null stripping stays ours. Confirm against the 29 known float
items and 160 null items (`research/pgstac_round_trip.md`) before relying on it, and
confirm the digests are computed fresh on both sides each run, so changing the
canonical form has no stored state to migrate.

### Work

- [x] skeleton repo (uv, `src/stacs`, tests, NEWS, planning, research)
- [ ] extract `register_manifest.py` with its existing tests, unchanged in behaviour
- [ ] port `catalogue_register.sh` (625 lines) to Python
- [ ] RFC 8785 canonicalisation, verified against the known pgstac normalisations
- [ ] **parity gate:** on the live API, `stacs verify` reports the same missing /
      changed / orphaned sets as `catalogue_register.sh --verify`, before anything switches
- [ ] `stac_dem_bc` adopts it and deletes its copies; `stac_airphoto_bc` adopts it and
      drops the `cd` into this checkout
- [ ] uav, orthophoto, floodplains adoption filed as their own issues

### Decided at the plan gate

- Port `catalogue_register.sh` to Python rather than ship it as a script (recommended:
  shell is what a Python package holds badly, and it is where the argv/`ps` and
  ARG_MAX defects lived).

## Why Python, not R

The boundary is already in the right place: R for discovery and analysis (packaged in
`ngr`), Python for standard conformance. `pystac` schema validation,
`rio_cogeo.cog_validate` and `pypgstac` have no R equivalents, and point clouds add PDAL.
`pystac` is what the ecosystem reads with, so it is the stronger test.

## Sequencing

Blocks the point cloud collection (NewGraphEnvironment/stac_dem_bc#35): with registration packaged, `stac_pointcloud_bc`
holds only discovery and item creation. NewGraphEnvironment/stac_dem_bc#29 (the inventory this issue originally waited
on) has landed.

## Note from NewGraphEnvironment/stac_dem_bc#27

NewGraphEnvironment/stac_dem_bc#27 deliberately did not extract, and added `register_manifest.py` plus four shell
scripts. `item_register.sh` / `collection_register.sh` exist in `stac_uav_bc` with
defects NewGraphEnvironment/stac_dem_bc#27's versions fixed (argv/ARG_MAX, fixed remote temp path, cleanup skipped on
failure, items registered before the collection).

Relates to NewGraphEnvironment/stac_dem_bc#27, NewGraphEnvironment/stac_dem_bc#29, NewGraphEnvironment/stac_dem_bc#35, NewGraphEnvironment/stac_dem_bc#42, NewGraphEnvironment/stac_dem_bc#45, NewGraphEnvironment/rtj#229, NewGraphEnvironment/soul#62




## Exploration (2026-10-06, stac_dem_bc origin/main 763f17d)

- Source: `scripts/register_manifest.py` (921 lines), `scripts/catalogue_register.sh` (625),
  `scripts/item_register.sh` (138), `scripts/collection_register.sh` (129); tests
  `tests/test_register_manifest.py` (657), `tests/test_catalogue_register.py` (931).
- Every sibling (dem, uav, orthophoto, floodplains) writes by `ssh HOST` + remote
  `uv run pypgstac load`; uav still puts the password in `--dsn` (argv).
- `register_manifest.py` imports `stac_utils` only for `PATH_S3` / `url_to_item_id`
  (used by `item_ids_from_urls`, dem-specific); `API_DEFAULT` is the live API.
- `catalogue_register.sh` reads dem's `collection_patch.COLLECTION_ID`,
  `stac_utils.PATH_S3_STAC` / `ASSET_DEM`, `item_migrate.ASSET_RENAMES` for its own-vs-foreign
  asset policy (#42). In stacs the caller declares its rules instead.
- `stac_airphoto_bc/scripts/run_pipeline.sh` tells the operator `--drift registers only ids
  the API lacks` — stale since stac_dem_bc#45 made drift compare bodies.

## Probes (2026-10-06)

- `rfc8785` 0.1.4 (pure Python): `-126.0` → `-126`, `-0.0` → `0`, `1e16` (float) →
  `10000000000000000`, `1e21` → `1e+21`, non-ASCII emitted as UTF-8, keys sorted by
  UTF-16 code unit (`😀` before `｡`, the reverse of Python's code-point sort). **Any int
  ≥ 2^53 raises `IntegerDomainError`** — including the `10000000000000000` pgstac serves
  for a published `1e16`. So ints go to doubles before JCS, which is JCS's own model
  (every JSON number is an IEEE double).
- `pystac` 1.15.2 bundles only STAC **1.1.0** core + GeoJSON schemas. A 1.0.0 item, or
  any `stac_extensions` entry, fetches its schema over the network. Offline tests use
  1.1.0 items without extensions, under a proxy that refuses every fetch.
- Relative item hrefs (`./x.json`), normal in self-contained catalogues, make every fetch
  fail in the source (code-check P1 round 1, carried over unchanged, fails loudly).
  The register/verify orchestrator knows the collection URL, so resolving them there is
  a candidate for Phase 4.

- Digest cost (synthetic 2.7 KB item, 20k reps): old `json.dumps` 54 µs, `rfc8785` 139 µs.
  ~205k digests per whole-catalogue verify: 11 s → 28 s, on a ~6 min run.

- `pypgstac` 0.10.0 `load.read_json` (load.py:142-167) parses NDJSON line by line and does
  not look at the file extension, so the remote temp file needs no `.ndjson` suffix (BSD
  `mktemp` would not randomise X's followed by a suffix). It also rewrites every line with
  `.replace("\\\\", "\\")` (twice) **before** parsing: a JSON string holding an escaped
  backslash (`"a\\b"`, i.e. `a\b`) is loaded as `"a\b"` -- a backspace -- or fails to parse.
  Upstream defect, not worked around: `stacs verify` reports any such item as `changed`
  every run, which is the right signal. Phase 6 scans the live bodies for backslashes.

## Phase 1 code-check: terminated by enumeration (2026-10-06)

| Round | Findings | Fixed | Accepted | Inside previous fix? |
|---|---|---|---|---|
| 1 | 0 (AST-compared every ported function with the source: 19/23 identical, 4 differ only by `api` losing its default) | 0 | — | — |
| 2 | 6 test gaps (guards no test could trip) | 6 | 0 | n |
| 3 | 1 bug + 5 fragile, all inherited from the source | 6 | 0 | n |
| 4 | 1 bug + 3 fragile | 4 | 0 | **y** — the stale-body fix only covered URLs in the current call |

**Mechanism** (round 4): the code concluded something was absent -- not served, missing, last
page, unchanged, nothing published -- from not seeing it, and a failed, partial, stale or
out-of-scope read looks identical. It recurred because each guard went into one caller rather
than the shared producer (`ids_registered`/`bodies_registered`, `_search_pages`/`bodies_serving`,
`fetch_bodies`/`published_digests`, `published_digests`/`collection_item_links`).

**Enumeration** -- every point in `verify.py` and `catalogue.py` that yields an absence,
from a grep of each `return`, `.get(…, default)`, `if not` and `404`:

| point | absence produced | status |
|---|---|---|
| `collection_item_links` no links / no item links | empty published set | raises |
| `collection_item_links` child link | items never listed | raises |
| `collection_item_links` two hrefs → one id | id collapsed by a set | raises |
| `fetch_bodies` leftover in out_dir | stale body read as this run's | refuses non-empty dir |
| `fetch_bodies` non-object body | absent body counted present | failed URL |
| `published_digests` file absent / unparseable / other id / repeat | absent digest | raises |
| `_post` HTTP error | error body read as a page | raises after retries |
| `_search_pages` no `features` | early last page | raises |
| `_search_pages` no `links` | early last page | raises (added after round 4) |
| `_search_pages` next without token / repeated token | early or looping end | raises |
| `_search_pages` no next link | the normal end | inherent: a server that truncates without a next link is undetectable |
| `ids_registered` / `bodies_registered` repeated id | overlap or skip hidden | raises |
| `bodies_serving` no features / next link | ids read "not served" | raises |
| `bodies_serving` no `links` key | could hide a truncation | loud direction only: unread ids read "not served" (false drift, never false sync) |
| `content_diff` empty digest | unread body compared equal | raises |
| `collection_state` 404 | "missing" | only if `{api}/collections` answers 2xx; a 2xx from a different API reads "missing" -- loud direction (a redundant upsert), never "same" |

Nothing in the set yields a false "in sync" or "unchanged". Spend: 1 plan review + 4 rounds.

## Phase 2 code-check (2026-10-06)

| Round | Findings | Fixed | Accepted | Inside previous fix? |
|---|---|---|---|---|
| 1 | 1 fragile: a lone surrogate in a KEY escaped as UnicodeEncodeError (rfc8785's UTF-16 key sort runs before its own serialiser). Also: JCS number output byte-identical to V8 `JSON.stringify` over 303,066 doubles | 1 | 0 | — |
| 2 | 1 test gap: the negative bound of the int→double conversion (`-1e16`) untested; 19-mutant table, 4 survivors all equivalent | 1 | 0 | n |
| 3 | Clean: no parser difference between `json.loads(bytes)` and `requests .json()` yields a false equal or a permanent false different; Postgres jsonb keeps the last duplicate key, as Python does (measured in postgres:16) | — | — | n |

Ended on a clean round 3 with no inside-a-fix finding.

## Phase 3 code-check: terminated by enumeration (2026-10-06)

| Round | Findings | Fixed | Accepted | Inside previous fix? |
|---|---|---|---|---|
| 1 | 2 bugs (non-object `assets` satisfied `require` by substring/membership; empty `collection_id` matched items with none) + 4 fragile (`require_asset=""` disabled the check; relaxed defaults predicate; network guard bypassable by loopback proxy / session fixtures; pystac schema fetch has no timeout) | 5 | 1 (pystac timeout: upstream, `validate` is opt-in) | — |
| 2 | 2 bugs (`Item.from_dict().validate()` validates pystac's rewrite, not the body; zero items returned the success value) + 5 fragile (empty forbid keys, null asset values, missing ids, UDP/legacy-lookup guard gaps, classmethod/partial defaults) | 7 | 0 | **y** -- the empty-forbid case is the class round 1's "every way of passing nothing refuses" fix claimed to close |

**Mechanism** (round 2): Python's polymorphic `in`, `!=`, truthiness and `set()` answer
for any input shape, so an input whose type or emptiness is not pinned reads as "matches"
or "nothing to check", and the result reads ok.

**Enumeration** -- every input and operator site in `validate.py`:

| site | unpinned input | status |
|---|---|---|
| `collection_id` | None / "" / non-str | raises |
| `require_asset` | "" / whitespace / non-str | raises; None = no rule |
| `forbid_assets` | "" / "," / empty element / non-str-or-list | raises; None or [] = no rule |
| body | non-object | unreadable |
| body `id` | missing / "" / non-str | unreadable (so `expect_ids` with None cannot match) |
| body `assets` | non-object | unreadable; null = {} as in the source |
| required asset value | null / string / no href | missing_asset |
| forbidden key `in assets` | assets pinned to dict | dict membership; a forbidden key with a null value still counts (fails closed) |
| body `collection` `!=` | non-str | wrong_collection (fails closed) |
| `expect` | bool / float | benign: still a numeric comparison |
| `expect_ids` | a string | `set()` of characters, mismatch (fails closed) |
| `paths` | a single string | iterates characters, each unreadable (fails closed) |
| zero items, audit | — | failure |
| zero items, validate | — | raises |
| validate target | pystac's model | raw dict via `validate_dict` |

Nothing in the set reads ok for a wrong item. Mutation table for both rounds' guards: all red.

## Phase 4 code-check: terminated by enumeration (2026-10-06)

Before review, a mutation table over 22 guards in `register.py` left 4 survivors (the
post-write collection check, `ndjson_write(expect_collection)`, one-collection-per-load,
an unreachable payload count); each got a test that kills it.

| Round | Findings | Fixed | Accepted | Inside previous fix? |
|---|---|---|---|---|
| 1 | 1 bug: on bash 3.2 a failed `.` (missing `env_file`) or any expansion error under the EXIT trap exits 0, so `load()` reported a load that never ran -- the class of the `${VAR:?}` fix, which had covered one instance. Every shell guard from the three scripts confirmed ported | 1 (success flag + `STACS_LOADED <n> <kind>` sentinel required on stdout) | 0 | — |
| 2 | 2 bugs: the env file is sourced into the shell that prints the sentinel, so `set +e` in it hides a failed pypgstac, and assigning `t` redirects the load and deletes another file; 1 fragile: "one transaction" is false for items (pypgstac commits per chunk) | 3 | 0 | **y** |
| own | the isolation subshell was written `( ... ) \|\| exit 1`, and bash suspends `set -e` for everything inside a tested list -- a failed `cd` let pypgstac run. Caught by `test_options_are_reasserted_after_the_env_file` | 1 (plain `( ... )`) | 0 | **y** |

**Mechanism** (round 2): the process that does the work also produces the proof of it, and
caller-supplied code runs inside that process.

**Enumeration** -- every subprocess or remote result `register.py` trusts:

| result | trusted for | now verified by |
|---|---|---|
| `probe` ssh exit 0 | host reachable | claims no work; any failure refuses (fails closed) |
| remote line count | complete transfer | computed by the receiver from the bytes it holds |
| pypgstac exit 0 | the load ran | `\|\| exit 1` and `-e` reasserted in the subshell after the env file; pypgstac exits 1 on a failed load (measured by review); `kind` is validated, so the `load <unknown>` exit-0 path is unreachable |
| `STACS_LOADED <n> <kind>` | the load ran | printed inside the subshell after pypgstac returned 0; an env file's `exit 0` or `set +e` cannot produce it. A deliberately forged line from the env file could -- it is the caller's own trusted code, and `run()` does not rely on it alone (next row) |
| any write inside `run()` | the API serves what was sent | an independent read back through the API: collection state, then the whole catalogue or `bodies_serving` over the to-do set |
| `fetch_bodies` return | bodies fetched | the gate is the set of files on disk, in a directory that had to be empty |
| `audit_items` | items fit | in-process, pinned inputs (Phase 3 enumeration) |

Standalone `stacs load` (no `run()`) rests on the remote's confirmation; documented.

## Phase 5 code-check: terminated by enumeration (2026-10-06)

| Round | Findings | Fixed | Accepted | Inside previous fix? |
|---|---|---|---|---|
| 1 | 2 bugs (`load` ignored the declared collection and asset rules; `load items` exited 0 having loaded nothing) + 5 (`--dir ""` read stdin; repeated asset flags kept only the last; `[tuning]` unchecked so a bad `chunk` failed after the write; `[transport]` wrong types crashed or passed; a missing dir gave a traceback) | 7 | 0 | — |
| 2 | 1 doc bug (README loaded items before the collection) + 4 (the audit copied onto `load` without its repeated-id check; `load collection` with no declared id checked nothing; `--ids-file` accepted and ignored outside ids mode; `all` mode never read the API before writing) | 5 | 0 | **y** -- the audit fix landed in one of two callers |

**Mechanism** (round 2): an input accepted in one place and applied -- or dropped -- in
another, with nothing mapping each accepted input to where it is applied; and a check
written per caller instead of in the shared producer. The repeated-id check now lives in
`audit_items`, so every caller has it.

**Enumeration** -- every subcommand and the inputs it accepts:

| command | input | applied / guarded |
|---|---|---|
| all | `--config` | unknown tables and keys refused; never implicit |
| `verify` | `[catalogue]` / `--api --collection-id --bucket-url` | Target, `Target.check` |
| `verify` | `[assets]`, asset flags | merged and validated (empty refused); not applied, because verify writes nothing -- the rules govern loads |
| `verify` | `[transport]` | not read (verify writes nothing) |
| `verify` | `[tuning]`, `--out-dir` | Target (checked); lists written |
| `register` | everything above + `[transport]`, `--host --db` | `Transport.check` (types first), API probe and ssh probe before the fetch |
| `register` | `--mode`, `--ids-file`, `--dryrun` | `--ids-file` refused outside ids; ids mode without it refused |
| `load items` | `[catalogue].collection_id` / `--expect-collection` | required; audit + `ndjson_write(expect_collection)` |
| `load items` | `[assets]` | audit before sending |
| `load items` | `--dir` / stdin | `--dir ""` and missing dir refused; zero items exits 1; repeated ids refused (in the audit) |
| `load items/collection` | `[catalogue].api`, `bucket_url`, `[tuning]` | not read: `load` sends local files and does not verify through the API (README says so) |
| `load collection` | FILE, collection id | id must equal `--expect-collection` or the declared id; one is required |
| `audit` | collection, asset rules, `--dir`/stdin, `--expect` | all applied; repeated ids refused |
| `validate` | `--dir`/stdin | zero items exits 1; `--dir ""` refused |

Every accepted input is either applied where it is accepted or documented as not read by
that command.

## Errors Encountered

| Error | Resolution |
|-------|------------|
| Write/heredoc tooling decoded `\uXXXX` escapes inside a file being written (RFC 8785 sample vector came out with a literal `"`) | build test strings from `chr()` codes |
| `( ... ) \|\| exit 1` around the load: bash suspends `set -e` inside any list whose status is tested, so the reasserted `-e` did nothing | run the subshell untested; the parent's `-e` and the success flag carry the failure |
| bash 3.2: `: "${VAR:?msg}"` under an `EXIT` trap exits **0** (the trap's status), so a remote guard written that way passes. Found by the Phase 4 harness running the remote script for real | explicit `if [ -z "${VAR:-}" ]; then echo ... >&2; exit 1; fi` |
