# Findings — Declare and load collection queryables from stacs.toml (#8)

## Issue context

**If we do it:** a catalogue declares the item properties its API should let users filter on, and `stacs register` loads them, so `/collections/<id>/queryables` lists them and CQL2 filters on them are advertised. **If we never do:** queryables can only be loaded by hand on the database host, and nothing records which a collection should have.

## What is there

pgstac serves `/collections/<id>/queryables` from its own `queryables` table, not from the collection JSON. A collection body that names a property does not make it queryable. stacs registers collections and items and does not touch that table, so a catalogue cannot declare a queryable today.

## Need

NewGraphEnvironment/stac_dem_bc#55 adds `lidarbc:delivery` to stac-elevation-bc items and asks for it in the collection's queryables, so a client can match items to the same delivery in stac-pointcloud-bc with one filter. stac-pointcloud-bc carries the same key and will want the same.

## Shape

- Declared in `stacs.toml` (property name, JSON Schema fragment, collection ids), beside the asset rules.
- Loaded as an upsert during `stacs register` (pypgstac's `load-queryables` is the mechanism), after the collection and before the item content check.
- `stacs verify` compares the served `/queryables` with the declaration.

## pgstac queryables semantics (2026-10-11)

Durable verdict in `research/pgstac_queryables.md`. Additions found while reading:
`start_datetime` is a core column in 0.10.0 (`queryable_column`) but not in 0.9.8's skip
list; refused either way. An empty `enum` is served absent (`nullif_jsonbnullempty`).
stac-fastapi-pgstac 404s the queryables endpoint when `get_queryables` returns NULL.

## Plan review dispositions (review-plan.md)

Probed before acting: G1 by reading `get_queryables` (`SELECT CASE ... jsonb_object_agg
... END FROM g`, an aggregate with no GROUP BY, so one row over an empty set); B1 in
stac-fastapi-pgstac `models/extensions.py` (filter is one of `ENABLED_EXTENSIONS`); B2 and
S1 from the SQL already read.

| finding | disposition |
|---|---|
| B1 filter-off 404 read as "none" | fixed: a 404 for an existing collection raises; an unregistered collection is not asked |
| B2 root /queryables 404 on an empty db | fixed: accepted only when /collections lists none; bootstrap test |
| G1 zero rows is `properties: null` | fixed, in the stub too; research note corrected |
| G2 no declaration, no requests | test over verify/drift/all with a GET log; out-dir files only when declared |
| G3 load only when it differs | adopted in every writing mode |
| G4 register docstring | amended |
| G5 dryrun | done in Phase 3 (all/ids and drift both name the queryables) |
| G6 queryables-only drift upserts the collection | kept deliberately: every write run upserts the collection, as it does for item-only drift |
| G7 docstring names research/ | removed |
| G8 plan text | Phase 3 rewritten |
| G9 NUL | refused, tested, mutation-checked |
| O1 queryables last | adopted |
| O2 snapshot before any write | already the case; kept |
| S1 guard only names served here | adopted; test that no other collection is read otherwise |
| S2 remedy wrong for a global row | message rewritten |
| S3 complete enumeration, 404 never "lost" | collections_listed guards; a 404 now raises |
| A1-A6 | A1 matches the code (enum as a set); A2 permissions and Acc1 (live run) are post-merge, in the PR body for stac_dem_bc#55; A6 caching: not new, as collection_state has the same exposure |
| H2 stub models the research note | said in the stub's docstring |
| Sc1 endpoint naming | the issue edit names /collections/<id>/queryables (see Phase 4) |
| Sc2 ids mode | harmless with diff gating; kept, as ids mode loads the collection too |

## Defects found by the tests written for the review

- `_check_others` with nothing snapshotted still enumerated every collection's
  queryables (test: a name not served here reads no other collection).
- `_get_or_absent` returned None for both a 404 and a JSON `null` body, so a broken
  collection answer would have read as `missing`; now an `ABSENT` sentinel.

## /code-check round 1 (review-round1.md)

| finding | disposition |
|---|---|
| bug: every declared name was sent, not only those that differ | fixed: send = missing + changed, asked again after the collection load |
| bug: a first registration skipped the guard, but a global row may exist | fixed: every declared name is at risk then; a matching global row is now not loaded at all |
| fragile: our own failure hid another collection's loss | fixed: both checks run, one error |

All three reproduced as red tests first; four mutations caught.

## /code-check round 2 (review-round2.md): inside round 1's fix

Mechanism: the other-collections check ran only on the success path after a load. Fixed
structurally rather than per exit. Queryables become one step (`_register_queryables`),
run last, after the collection and items are verified. The snapshot is taken just before
the load (round 2's fragile 2), and the check runs on every way out once the load is
attempted. Enumerated exits: RegisterError from the load (caught); any other exception
(was dropped by `finally`, now caught, test with OSError); the re-read of ours (caught);
`_others_damage` (never raises); `_run` after the step (log only); other callers of
`load_queryables` (none; docstring now says the bare load checks nothing). The failure
message no longer promises nothing was loaded. The after-load read failure has its own
wording. Eight mutations caught (two re-run after the first attempt was malformed).

## /code-check round 3 (review-round3.md): no instance of the mechanism

Mechanism named by the reviewer: the guard's scope and trigger came from stacs' account of
the load (what it meant to send, whether the collection existed, which exit it believed it
took), not from what the load can change in the database. Every place it reaches was
enumerated and is covered (matches the round 2 enumeration). Two library-path findings
fixed: `Target(queryables=None)` is normalised in `check()`; `load_queryables` returns 0
on a dryrun. The one mutation that survived its reviewer (`changed` arm of
`_others_damage`) is now pinned by a unit test and caught.

## Errors Encountered

| Error | Resolution |
|-------|------------|
