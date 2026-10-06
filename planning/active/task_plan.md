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
- [ ] `stacs.verify` and `stacs.catalogue` from `register_manifest.py` per the table above; `api` and `collection_id` required, no defaults
- [ ] `requests` runtime dependency; `uv.lock` updated
- [ ] Port `tests/test_register_manifest.py` (minus `item_ids_from_urls` cases) with fixtures on fake hosts (`example.invalid`), all passing unchanged
- [ ] Test: no module-level default names a real host, bucket or collection (grep-style guard over `src/`)

## Phase 2: RFC 8785 canonicalisation
- [ ] `body_digest` serialises with JCS (`rfc8785` library); keep `links` removal and null-member stripping
- [ ] Ints passed as doubles before JCS (JSON numbers are doubles), so `-126.0`/`-126`, `-0.0`/`0` and ≥1e16 compare equal without `rfc8785`'s safe-integer refusal; `bool` untouched
- [ ] Tests: every existing `_canonical` case still holds; non-ASCII strings, non-BMP key ordering, 1e16 float vs int
- [ ] Confirm in code and note in findings: digests computed fresh both sides every run, nothing stored, so no migration

## Phase 3: `stacs.validate`
- [ ] `audit_items` ported (wrong collection, missing/forbidden asset, unreadable, `--expect`, prints rules as applied, zero items fails)
- [ ] pystac `Item.from_dict(...).validate()` per item, collecting failures rather than stopping at the first
- [ ] Offline tests: schema fetches cannot reach the network in CI (pinned/cached schemas or network-proof harness)

## Phase 4: `stacs.register` — port of `catalogue_register.sh`
- [ ] NDJSON assembly (`ndjson_write`, `--expect-collection`) and SSH transport: paths never in argv, payload on stdin, `BatchMode` reachability probe, receiving-side line-count guard, `pypgstac load <kind> <tmp> --method upsert`, remote prelude from config, db name validated
- [ ] Modes `verify` / `drift` / `all` / `ids` + `dryrun`, with every guard: zero published refuses, collection-id-in-file mismatch refuses, duplicate/missing item links refused before any write, fetch count gate from the artifact fetched, audit before the collection upsert, collection before items, post-write collection check, full re-compare when the collection may have changed, `verify-serving` otherwise, IN SYNC said out loud
- [ ] Port `tests/test_catalogue_register.py` harness: `file://` bucket, stub API, ssh stub logging `(kind, lines)`, proxy-env network-proofing; the dem-specific own-collection/bucket cases replaced by declared-rule cases

## Phase 5: CLI, config, docs
- [ ] `stacs` console script (argparse): `verify`, `register --mode drift|all|ids`, `audit`, `validate`; `--config stacs.toml` with flag overrides; secrets never accepted as flags
- [ ] Example `stacs.toml` with fake values in README; README "What it will do" → usage; NEWS Unreleased entries
- [ ] `research/` note: the pgstac round-trip table carried over with provenance to dem's `research/pgstac_round_trip.md`

## Phase 6: Parity gate (live, read-only)
- [ ] `catalogue_register.sh --verify` (dem `main`) and `stacs verify` against the live API for `stac-elevation-bc` and `stac-airphoto-bc`
- [ ] Compare missing / changed / orphaned id sets and collection state, set-for-set; record commands, numbers and log prefix in findings and the archive README
- [ ] Any disagreement explained and fixed before proceeding

## Phase 7: Hand-off
- [ ] File adoption issues: stac_dem_bc (adopt, delete copies), stac_airphoto_bc (adopt, drop the `cd`; its "--drift never refreshes" note is stale since stac_dem_bc#45), stac_uav_bc, stac_orthophoto_bc, stac_floodplains_bc
- [ ] Edit #1's body: work list reflects the split, links the new issues

## Validation

- [ ] Tests pass
- [ ] `/code-check` clean on each commit
- [ ] PWF checkboxes match landed work
- [ ] `/planning-archive` on completion
