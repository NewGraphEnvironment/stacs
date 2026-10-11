# Review round 2 — branch `8-declare-and-load-collection-queryables-f` (HEAD dc8ce13)

Scope: the three round-1 fixes in `_run` (src/stacs/register.py), plus queryables.py,
verify.py, cli.py, docs. Upstream facts re-checked read-only against pgstac v0.9.8 /
v0.10.0 (`002a_queryables.sql`, `001a_jsonutils.sql`, `pypgstac.py`, `load.py`, `db.py`)
and stac-fastapi-pgstac `filter.py`. Suite: 465 passed. Probes ran in a copy
(`scratchpad/r2copy`), not in the repo.

The fixes themselves hold: only names that differ after the collection load are sent,
a first registration reads every declared name from the other collections, and a failure
of our own queryables check no longer hides another collection's loss. A name that is
*missing* here (collection registered) has no conflicting row in either pgstac version, so
leaving it out of `at_risk` is correct.

## Findings

- **[bug] src/stacs/register.py:677-710** — fix (3) moved one failure out of the way
  of the other-collections check, but two other paths still skip it. The same
  defect, one step over. Once `load_queryables` has run, every exit before
  `_check_others` loses the other collection's damage for good. The next run's
  snapshot no longer holds the name. Our own row now serves it as declared, so
  nothing is loaded and nothing is checked, and the run reports success.
  1. **The queryables load reports failure after the database applied it.**
     pypgstac's connection is `autocommit = True` (v0.10.0 `db.py:111`), so
     `upsert_queryables` is committed when the SELECT returns. If ssh drops, or
     anything exits non-zero after that point, `_send` raises
     `"load of 1 queryables failed ... Nothing was loaded."` (line 397). That
     message asserts something stacs does not know, and the exception escapes
     before line 696, so `_check_others` never runs.
     Probe: the fake pypgstac logs the load and then exits 1. Result: stderr is
     only "Nothing was loaded.", and `stac-other-a` serves `{}`.
  2. **The collection read-back runs first and raises first.** Lines 691-694
     (`_collection_state` raising on an API failure, or `after != "same"`) come
     before the queryables block.
     Probe: the collection is served differently after the load and a global row
     was taken. Result: stderr is only "after registering, the collection reads
     'changed'", the queryables load was made, and `stac-other-a` serves `{}`
     with no report.
  3. Same shape: `_queryables_drift(target, True)` at line 700 is not inside the
     `problems` collection. A transient failure reading our own
     `/collections/<id>/queryables` after the load raises past `_check_others`.

  Fix direction: once a queryables load has been attempted (`send` non-empty),
  run `_check_others(target, others)` whatever happens after that, for example in
  a `try/finally` around the load and the post-load checks. Append its result to
  the error being raised. For the queryables kind, the `_send` failure message
  should not say "Nothing was loaded."

- **[fragile] src/stacs/register.py:798** — `_others_queryables` always words a
  read failure as `"... before loading ours"`. It is also called from
  `_check_others` after the load (line 809), and that error is folded into
  `problems` at line 708. So a post-load failure to re-read the other collections
  tells the operator the load had not happened, and that the guard ran
  pre-write, when the global row may already be gone. This misstates the
  database's state in exactly the case the guard exists for.

- **[fragile] src/stacs/register.py:664-668 vs 706** — the snapshot of the other
  collections is taken before the collection and items loads. The comparison
  comes after them. An `all` run over a large catalogue keeps that window open
  for the whole items load. If another catalogue legitimately re-registers its
  own row of a shared name in that window (scheduled CI runs of sibling
  catalogues), this run fails with "loading the queryables changed what other
  collections serve" and blames the change on itself. The snapshot can be taken
  just before `load_queryables` (after the re-ask at line 681) without losing
  anything. Collection and item loads do not touch the queryables table, and our
  own collection is excluded from the snapshot anyway.

No other issues found against the checklist. I checked:
- remote-script quoting of `--collection_ids`
- fire list parsing
- `read_json`'s backslash rewrite against `json.dumps` escapes (only a literal
  backslash yields `\\`, and that is refused)
- the enum set comparison against `jsonb_agg(DISTINCT)`
- min/max merging with a single row
- `/collections` paging
- the 404 handling for `/queryables` on an empty database
- the `[queryables]` free-key table in `read_config`
- the README marker placement
- the uv.lock and dev-dependency change
