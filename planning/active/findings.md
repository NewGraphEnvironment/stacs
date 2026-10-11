# Findings — register --dryrun skips the API and ssh probes; say so or probe (#5)

## Issue context

**If done:** a reader of the README knows `register --dryrun` proves nothing about the host or API, and reaches for `--mode drift` (no dryrun) against an in-sync API, or a probe flag, when that is what they want to test. **If never:** a dryrun keeps reading as a connectivity check, and someone signs off a config whose ssh or API never got touched.

## Observed

stacs v0.1.1, `src/stacs/register.py`: in `--mode all`/`ids` with `--dryrun`, `_run` returns at the `[dryrun] would fetch` branch (~461-467), before `_api_probe` and the ssh `probe` (~472-474). For `drift` the dryrun likewise skips the probes. `build_transport` only runs the local `Transport.check()`.

Found adopting stacs in stac_airphoto_bc#42 (2026-10-07): the plan used `--mode all --dryrun` to "exercise the documented command"; a review showed it reached nothing `stacs verify` had not. What did exercise the transport was `register --mode drift` against an IN SYNC API (probes ran, nothing written), and then `stacs load collection` with the byte-identical published body (load path confirmed, 6 s). stac_dem_bc#49 hit the same thing (its review-plan A1).

## Options

- README: one line under `register` saying `--dryrun` skips the probes, and naming the no-write test (`--mode drift` against an in-sync API)
- Or: run `_api_probe` + `probe` in dryrun too, since both are read-only — then a dryrun becomes a real preflight

## Exploration (2026-10-11)

- `register._run` returns on `--dryrun` at the all/ids branch and the drift branch, both
  before the `if writes and not dryrun:` block holding `_api_probe` and `probe`.
- Correction to the issue: a drift dryrun does read the API (`_registered`,
  `_collection_state`, `_queryables_drift`); what it skips is the ssh probe. all/ids
  dryruns read the bucket only.
- The skip was deliberate: `test_all_dryrun_previews_and_touches_nothing` set the ssh probe
  to fail and required the dryrun to pass.
- `stacs load --dryrun` has the same gap: `_send` returns before `probe(t)`.
- `register --mode drift` against an in-sync API returns "already in sync" before any load,
  so it probes but never runs the remote script. Only a real load exercises the env file,
  pypgstac and the database check.

## Plan review (2026-10-11, Plan agent)

Folded in: B1 (a dryrun still skips the fetch/audit and the remote script, so the README
names what each mode skips, not "everything but the write"); G1 (autouse probe stub in
test_cli, since conftest's socket guard cannot see the ssh subprocess); G2 (dead-API
dryrun tests take `no_retry_sleep`, else ~6 s each); G3 (probe moved in `_send`, not
added); G4 (an all/ids dryrun with queryables now reads `/collections/<id>` and its
queryables, and names only what it would load); G5; O1 (`test_ids_mode_refuses_a_missing_or_empty_file`
stays on the dead API: it pins the ids-file check ahead of the probes); A1 (the "smallest
real load" is a no-op only when `verify` reports the collection `same`); A2 (a CI preview
with no ssh keys or known_hosts now exits 1); S2 (NEWS states it as a behaviour change);
S3 (`run` docstring).

Mutations, each in a scratch copy (each turned tests red): dryrun skipping the probes (9
failed), no `_api_probe` (3), no ssh probe in `_run` (6), no probe in `_send` (5), no
"reached" line (2), the dryrun naming every declared queryable (1).

## Errors Encountered

| Error | Resolution |
|-------|------------|
