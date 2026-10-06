# Task: stacs: package the pgstac registration and verification layer shared by the stac_*_bc repos (#1)

The part of our STAC tooling that is genuinely shared across catalogue repos is
**registration and verification**, and it is not packaged. It is copied, it has drifted,
and one repo already runs it out of another repo's checkout
(`stac_airphoto_bc/scripts/run_pipeline.sh` `cd`s into `stac_dem_bc`). Only
`stac_dem_bc`'s copy carries every lesson: upsert-only, collection before items, id
**sets** both directions, body **digests**, an unread body is an error, secrets via env,
stdin not argv.

## Decided at the plan gate (2026-10-06)

- **Transport: SSH stream.** stacs owns the NDJSON stream, the receiving-side line-count
  guard, and `pypgstac load <kind> --method upsert`. The caller supplies host, db and a
  remote prelude (what `/opt/geoserv/.env` + `cd /opt/geoserv/scripts` + PG* exports are
  today). No local pypgstac dependency; the DB password never leaves the host.
- **Config: `stacs.toml` + CLI flags.** `--config FILE` (no implicit cwd lookup); any value
  overridable by a flag. Works for conda/.venv repos with no pyproject.
- **Scope: the PR ends at parity.** Adoption is filed as issues in stac_dem_bc,
  stac_airphoto_bc, stac_uav_bc, stac_orthophoto_bc, stac_floodplains_bc; #1's body is
  edited to match; #1 closes on merge.

## What moves, what stays

| from `stac_dem_bc` | goes to | note |
|---|---|---|
| `_post`, `_search_pages`, `ids_registered`, `bodies_registered`, `search_body`, `bodies_serving`, `ids_diff`, `_canonical`, `body_digest`, `content_diff`, `collection_state` | `stacs.verify` | `API_DEFAULT` removed: `api` required everywhere |
| `collection_item_links`, `_href_to_id`, `fetch_key`, `_read_url`, `fetch_bodies`, `published_digests`, `read_hrefs` | `stacs.catalogue` | the published side; `%20`-only decode kept unchanged, assumption documented |
| `ndjson_write`, ssh load in `item_register.sh` / `collection_register.sh`, `catalogue_register.sh` orchestration | `stacs.register` | Python port; remote guard + `mktemp`/trap kept |
| `audit_items` (+ `--expect`, applied-rules print), pystac item validation | `stacs.validate` | asset rules are caller-declared |
| `item_ids_from_urls` / `ids-from-urls` | **stays** in dem | knows `PATH_S3` and `.tif` |
| `s3_bucket_name`, `same-bucket`, `hrefs-in-bucket`, own-vs-foreign policy | **stays / retired** | issue: declared rules replace #42's bucket test |
| `collection_unregister.sh` | **stays** | a delete path; stacs is upsert-only |

## Phase 1: Extract the pure core, behaviour unchanged
- [x] `stacs.verify` and `stacs.catalogue` from `register_manifest.py` per the table above; `api` and `collection_id` required, no defaults
- [x] `requests` runtime dependency; `uv.lock` updated
- [x] Port `tests/test_register_manifest.py` (minus `item_ids_from_urls` cases) with fixtures on fake hosts (`example.invalid`), all passing unchanged
- [x] Test: no module-level default names a real host, bucket or collection (grep-style guard over `src/`)
- [x] Plan review folded in (`review-plan.md`); explicit `encoding="utf-8"` on every open

## Phase 2: RFC 8785 canonicalisation
- [x] `body_digest` serialises with JCS (`rfc8785`, added to pyproject/lock); keep `links` removal and null-member stripping; drop the float→int step
- [x] Only `type(x) is int` values beyond ±(2^53−1) become doubles (JCS's model: every number is an IEEE double). Pin as a decision: distinct ints above 2^53 that round to one double digest equal. Overflow, NaN/Infinity and lone surrogates raise a named error naming the problem, never a bare library exception
- [x] Tests: every existing digest case still holds (`-126.0`/`-126`, `-0.0`/`0`, `1e16`/int, bool ≠ 1, nulls); an RFC 8785 Appendix vector; non-ASCII; non-BMP key order; 1.5e300 vs its served integer
- [x] Benchmark digest cost on a realistic item (~205k digests per whole-catalogue verify); record in findings
- [x] Confirm in code and note in findings: digests computed fresh both sides every run, nothing stored, so no migration

## Phase 3: `stacs.validate`
- [x] `audit_items` plus the `audit-items` branch guards: zero items fails, forbid list parsed with empty keys dropped, rules printed as APPLIED, `expect` as a set gate where ids are known, directory mode excludes `collection.json`
- [x] Port the audit tests from stac_dem_bc `tests/test_item_migrate.py` (217-283, 531-565)
- [x] pystac `Item.from_dict(...).validate()` per item (`pystac[validation]` dependency), collecting failures rather than stopping at the first; not called from `register` (parity: the shell never validated)
- [x] Offline tests: 1.1.0 items without extensions (the schemas pystac bundles), under a proxy that refuses every fetch; a schema that cannot be fetched is a failure, not a pass

## Phase 4: `stacs.register` — port of `catalogue_register.sh` and the two register scripts
- [x] `Target` dataclass (api, collection_id, bucket_url, ssh fields, asset rules, page/chunk sizes, fetch workers) so Phase 4 runs in-process and Phase 5 only maps TOML + flags onto it
- [x] Transport: structured fields, each `shlex.quote`d — host (refuse a leading `-`; `--` before it), db (validated `[A-Za-z0-9_]+`), env_file, workdir, path_prepend, pg_host/pg_port/pg_user, password_env (a host-side variable NAME, validated as an identifier), pypgstac launcher argv. stacs emits the PG* exports after sourcing, so the validated db is the one loaded. Remote script run under `bash -c`; `BatchMode` on probe AND write
- [x] Load path: payload fully assembled to a local file before ssh starts; local written==expected; zero items exits 0 saying so; receiving-side line-count guard; remote `set -euo pipefail` + trap cleanup; one `pypgstac load` per kind, never chunked (one transaction); collection exactly 1 line; `ndjson_write(expect_collection=)` + its tests from test_item_migrate.py (285-315)
- [x] Orchestration, every guard enumerated from the shell: startup banner (collection, mode, asset policy incl. "none" said out loud); zero published refuses; collection id in the file must equal the configured one (generic message); relative item hrefs resolved against the collection URL; `ids` input normalised (blank lines, duplicates, none left → refuse) and an id with no link refused; one id ↔ one href ↔ one row, refused before any write; dryrun previews (`all`/`ids` before probe and fetch, `drift` after the diff); probe before the fetch in every writing mode; fetch gate as a SET of expected files vs files present, failures and stderr reported; the to-do bodies resolved by href, a body naming another id refused before any write; `collection_state` tri-state, anything else an error; `verify` reports missing/changed/orphaned/collection with full lists to an output dir and exits 1 on any; drift collection-only path; audit only when to-do > 0, before the collection upsert; collection before items; post-write collection must read `same`; full re-compare when the collection may have changed, else verify-serving (sent set == wanted set); orphans never a failure after a write; `ids` mode prints "run verify after" (it does not re-check the catalogue)
- [x] Asset rules are declared, not keyed by collection id: a changed `--collection` cannot drop them, and flags may add rules but never remove configured ones
- [x] Port the `tests/test_catalogue_register.py` harness in-process: `file://` bucket, stub API, ssh stub matching the new remote command shape and logging `(kind, lines)`, proxy-env network-proofing asserted on the proxy reason (not DNS); keep T4's properties; add the untested guards (id mismatch, zero published, ids guards, failed probe, remote truncation, db/host validation, paging no-token / repeated token, retries and 404 vs 5xx with injected sleep)

## Phase 5: CLI, config, docs
- [x] `stacs` console script (argparse): `verify`, `register --mode drift|all|ids [--dryrun]`, `load items` (paths on stdin) / `load collection FILE` for repos that register their own build output, `audit`, `validate`; `--config stacs.toml` (stdlib `tomllib`) with flag overrides under the asset-rule restriction above; secrets never accepted as flags or config values
- [x] Example `stacs.toml` with fake values in README; README usage, the boundary sentence first, the paging dialect (stac-fastapi next-link body) stated; NEWS Unreleased entries
- [x] `research/pgstac_round_trip.md` carried over with provenance to stac_dem_bc's, updated for JCS

## Phase 6: Parity gate (live, read-only)
- [x] Reference sets from stac_dem_bc `register_manifest.py diff --missing-out --orphaned-out --changed-out` + `collection-state` (the shell's `--verify` prints only five of each); `stacs verify` writes full lists; both for `stac-elevation-bc` and `stac-airphoto-bc`; compared set-for-set
- [x] Verdict equivalence item by item: old digest equal ⇔ JCS digest equal, over the same fetched bodies and served pages
- [x] Positive control (a `file://` collection with one body edited reads `changed` in both); the 29 float and 160 null items read `same`; NaN / huge-number scan; distinct-digest count; wall time
- [x] Record numbers by collection (API as `$API`) in findings and the archive README; any disagreement explained and fixed before proceeding

## Phase 7: Hand-off
- [ ] File adoption issues (pin `v0.1.0` once tagged): stac_dem_bc (catalogue_register.sh, register scripts, `update.yml` audit calls; which validators stay build-side), stac_airphoto_bc (drop the `cd`; `--all` then `verify`; its "--drift never refreshes" note is stale since stac_dem_bc#45), stac_uav_bc, stac_orthophoto_bc, stac_floodplains_bc (`stacs load`)
- [ ] Edit #1's body: work list reflects the split, links the new issues

## Validation

- [ ] Tests pass
- [ ] `/code-check` clean on each commit
- [ ] PWF checkboxes match landed work
- [ ] No real host/bucket/collection in `src/` (structural + text guard)
- [ ] `/planning-archive` on completion
