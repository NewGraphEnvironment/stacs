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

## Errors Encountered

| Error | Resolution |
|-------|------------|
