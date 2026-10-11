# Review round 1 — branch `8-declare-and-load-collection-queryables-f` vs main (#8)

Reviewer: subagent, 2026-10-11. Suite at HEAD: 460 passed. Both findings below were
reproduced by probe tests in a scratch copy of the repo (the repo itself was not modified),
using the existing `_StubAPI` harness, which models pgstac's "the row passed in wins".

## Findings

- **[bug — data loss for other collections, unguarded]** `src/stacs/register.py:670` —
  `load_queryables(..., target.queryables, ...)` sends **every** declared queryable, not
  only `q_missing + q_changed`. pgstac deletes and reinserts every name in the document.
  Two consequences:
  1. A name already served as declared is reloaded whenever any *other* declared name
     drifted. Its `property_index_type` is dropped. That contradicts README ("loads a
     queryable only when it is missing or served with a different definition") and
     research/pgstac_queryables.md ("never one already served as declared").
  2. The cross-collection guard misses it. `_others_queryables(target, q_changed)`
     (line 660) snapshots only the `q_changed` names. If the in-sync name is served
     through a **global** row whose definition matches the declaration, the load replaces
     that global row with this collection's own, and every other collection stops serving
     it. The run still reports `OK` and exits 0.

  Probe: declare `{lidarbc:delivery, zz:new}`, collection registered, `lidarbc:delivery`
  served by a matching global row, another collection `stac-other-a` present, mode
  `drift`. Result: rc 0, both names in the payload, `stac-other-a` now serves `{}`.

  Fix: send `{n: target.queryables[n] for n in q_missing + q_changed}`.

- **[bug — data loss for other collections, unguarded]** `src/stacs/register.py:544-546`,
  `:578`, `:753-754`. When the collection is not yet registered (a first registration,
  in `all`, `ids` or `drift`), `_queryables_drift(target, False)` returns every declared
  name as *missing* without reading anything, so `q_changed` is empty. The `others`
  snapshot at line 660 is therefore never taken. The research note's premise ("a declared
  name that is not served here yet cannot touch any other collection") holds only for a
  collection that exists. For an unregistered one, "not served here" says nothing about a
  global row of that name. The load then deletes the global row: 0.10.0
  `conflicting_queryables` matches `collection_ids IS NULL`, and 0.9.8 deletes
  `collection_ids IS NULL` explicitly. Every other collection loses the queryable,
  silently and with rc 0. This happens even when the global row already matched the
  declaration, so no load was needed at all. It is plausible right now, because the issue
  says queryables are currently loaded by hand on the host, and a hand load without
  `--collection_ids` is global.

  Probe: `api.collection = None`, `api.others = ["stac-other-a"]`, global row equal to
  `QUERYABLES`, mode `all`. Result: rc 0, loads `collections, items, queryables`,
  `global_queryables` is `{}`, and `stac-other-a` serves `{}`.

  Fix options:
  - Recompute `_queryables_drift(target, True)` after the collection load and before the
    queryables load, and take the `others` snapshot then. Loading this collection cannot
    change what other collections serve, so the snapshot is still a valid "before".
  - Or, when the collection was missing, snapshot every declared name.

  The first option also avoids reloading a global row that is already served as
  declared.

- **[fragile]** `src/stacs/register.py:681-687`. `_check_others` runs only if this
  collection's own post-load check passes. If ours reads drifted after a load that also
  replaced a global or shared row, the run raises about ours alone, and the loss on other
  collections is never reported. The next run's "before" snapshot no longer contains the
  lost name, so no later run can report it either. Running `_check_others` before raising
  for our own drift (or folding both into one error) closes this.

Checked and fine: the remote script's queryables branch, including the fire literal for
`--collection_ids`, the line count, the success marker and `mktemp`; the backslash and NUL
refusals against pypgstac's `read_json`; enum set comparison against
`jsonb_array_unique` (0.9.8 and 0.10.0); the 0.9.8 `maxiumn` typo (the definition's own
`maximum` survives); `properties: null` handling and the 404 paths; root `/queryables`
bootstrap probe; config parsing of `[queryables]`; docs markers and no `research/` or
`planning/` reference added inside the site's snippets or docstrings.
