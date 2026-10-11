# Review round 3: branch `8-declare-and-load-collection-queryables-f` (HEAD d8fb84d)

Scope: the round-2 fix (`_register_queryables` and the others check on every way out),
plus everything the mechanism reaches in register.py and verify.py. I checked the
upstream facts again, read-only, against pgstac `v0.10.0` and `v0.9.8`
(`002a_queryables.sql`, `002_collections.sql`, `003a_items.sql`, `pypgstac.py`).

- Suite in the repo: 470 passed.
- Mutations ran in a copy (`scratchpad/mut`, with its own venv, and the import path was
  confirmed to be the copy). The repo was not touched.
- The strict mkdocs build is clean.

## The mechanism

Rounds 1 and 2 had one shared assumption. Each time, the guard's scope and trigger came
from the code's own account of the load:

- which names it meant to send;
- whether the collection was registered before the run;
- which exit path it took and whether it believed the load succeeded.

They did not come from the set of database states the load can actually produce. So two
lists had to agree for the guard to be complete. In every case they agreed only on the
happy path:

| round | what was loaded or written | what was guarded |
|---|---|---|
| 1 | every declared name | the names that differed |
| 1 | a first registration | only collections that already existed |
| 2 | a load that can commit on a failure exit | the success exit |

The fix that ends the class keys the after-check to "a load was attempted" rather than
to any outcome. The names it covers are keyed to the rows pgstac's conflict rule can
delete, rather than to what stacs meant to send.

### Where the mechanism reaches now, and whether each place is covered

| place | where the two lists could diverge | status |
|---|---|---|
| `_run` (load_q, l.632) | Load decided from drift read before the collection/items write | **Covered.** `_register_queryables` re-reads after the collection exists. Nothing in pgstac 0.9.8/0.10.0 changes the queryables table on a collection upsert or an item load. Only a collection DELETE touches it (`002_collections.sql:118`), and stacs never deletes. Mutation "skip the re-read" fails 12 tests. |
| `_run` (only call site) | Some other path loads queryables without the guard | **Covered.** `load_queryables` is called once, from `_register_queryables`. `stacs load` never loads queryables. |
| `_register_queryables` (send vs. snapshot) | `send = missing + changed`, but the snapshot is `changed` only | **Covered, by upstream semantics, verified.** 0.10.0 `conflicting_queryables` deletes rows that are global or overlap `[A]`. 0.9.8 deletes the exact `[A]` row and the NULL row. `get_queryables(A)` serves exactly those rows, so a name not served on A has no row the load can delete. Mutation "send all declared" fails 3 tests. Mutation "snapshot nothing" fails 9. |
| `_register_queryables` (every exit after the attempt) | The after-check runs on only some exits | **Covered.** The load and our re-read sit inside `except Exception`, and `_others_damage` runs unconditionally after it. Mutation "others check only on success" fails 4 tests. BaseException is excluded (accepted). |
| `_others_queryables` | Before and after enumerate different populations | **Covered.** One function on both sides. A collection deleted in between reads as "lost", which fails toward refusal. A collection the API does not list is unguarded. stac-fastapi-pgstac lists every collection, and `next` is followed. |
| `_others_damage` | Compared names differ from snapshotted names | **Covered.** Same names, compared per (collection, name). Its "never raises" claim holds: every exception `rfc8785` and `fragment_digest` can raise is a ValueError, RecursionError is a RuntimeError, and requests' JSONDecodeError is retried into a RuntimeError. One observation is below the table. |
| `load_queryables` | n/a (bare, documented) | Accepted. |
| `_send` | The message claims a state stacs does not know | **Covered.** A queryables failure now says it may have committed. |
| `queryables_served` | A 404 or null read as "none" | **Covered.** 404 raises, `"properties": null` is none, and anything else raises. Mutation "404 as none" fails 2 tests. |
| `collections_listed` | First page read as everything | **Covered.** It follows `next` and raises on every abnormal stop. Mutation "first page only" fails 5 tests. |
| `_get_or_absent` | A wrong prefix's 404 read as absent | **Covered.** ABSENT only when `/collections` answers. A 404 on a paging URL becomes ABSENT, which `collections_listed` then refuses. |

Observation on `_others_damage`, not a finding: the `changed` arm is unpinned. Mutating
`now != digest` to `now is None` keeps all 229 register and verify tests green. I could
not reach a "changed" outcome against real pgstac:

- In 0.10.0 a name has at most one row covering any collection, so a deleted global or
  shared row leaves B with nothing, which is "lost".
- In 0.9.8 a shared row makes the insert trigger roll the load back.
- In 0.9.8 a `'{}'` row is never deleted by the load.

So nothing is broken. It is noted only because CLAUDE.md asks for a mutation check on
every guard.

## Findings

- **[fragile] src/stacs/register.py:481** (also 538, 551, 594, 632, 732):
  `Target(queryables=None)` passes `Target.check()`, because
  `parse_queryables(None)` returns `{}` ("None means none"). But `_run` uses
  `target.queryables` raw, so `sorted(target.queryables)` raises
  `TypeError: 'NoneType' object is not iterable`. That is not a RegisterError, so
  `run()` gives a traceback instead of returning 1. I probed it:
  `Target(..., queryables=None).check()` passes, then `run(t, "verify")` raises the
  TypeError. It is library-only (the CLI always passes a dict) and it happens before
  any I/O. It is an input the validator accepts and the code cannot handle. Fix
  direction: have `check()` store the parsed value, or refuse None there.

- **[fragile, minor] src/stacs/register.py:349-375**: in dryrun, `load_queryables`
  returns `len(declared)` (1 in `test_queryables_dryrun_sends_nothing`) although
  nothing was sent. Its docstring says it returns "the number of properties sent",
  and the sibling `load()` returns 0 in dryrun, through `_send`. No caller in the
  package reads the value, so only a library caller that counts loads is misled.

No other issues against the checklist. I checked:

- The remote-script quoting and fire parsing of `--collection_ids`.
- The `read_json` backslash rewrite against `json.dumps` escapes.
- That CORE_COLUMNS is a superset of both versions' skip lists.
- The enum set comparison and min/max with one row.
- That the `/queryables` probe 404s only on an empty database.
- The free-key `[queryables]` table in the CLI.
- That uv.lock is current (`uv lock --check`).
- That no docstring or README section reaching the site names `research/` or `planning/`.
