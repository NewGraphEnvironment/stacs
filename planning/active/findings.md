# Findings — Report the database each load reached, and refuse a mismatch (#6)

## Issue context

**What changes if we do it:** every load names the database it reached, so a misconfigured `db` is caught by the run itself. **What happens if we never do:** a load into the wrong database reads as success whenever the right one already serves an identical body, and only a separate host-side check can tell.

## Problem

The read-back after a write compares what the API serves with what was sent. When the body was already being served identically (a re-register, an `ids` run on an unchanged item, a first load into a catalogue that is already populated), that comparison passes whatever database pypgstac connected to. `STACS_LOADED <n> <kind>` shows pypgstac exited 0 on *some* database.

Measured on a live catalogue (2026-10-07): the only evidence of the target was a separate read-only ssh check that opened `pypgstac.db.PgstacDB()` under the same environment `remote_script()` builds and ran `SELECT current_database()`.

## Proposed Solution

Inside the remote subshell, after the load and before printing the success line, query `current_database()` through the same connection settings and include it: `STACS_LOADED <n> <kind> <db>`. The client refuses unless `<db>` equals `Transport.db`. Optionally, run the same query before the first write so a wrong target is refused before anything is written.

## pypgstac reaches its own connection through fire

pypgstac 0.9.6, 0.9.8, 0.10.0: `PgstacCLI.__init__` sets `self._db = PgstacDB(dsn=dsn, ...)`;
`PgstacDB.query_one` returns a one-column row as the bare value; `fire.core._GetMember`
resolves any name in `dir(component)`, private ones included. So
`pypgstac _db query_one 'SELECT current_database()'` opens the connection the load opens
(`dsn=""`, libpq reading PG*) and prints the name. 0.10.0 read from the uv cache;
0.9.6 and 0.9.8 via the GitHub contents API at those tags (2026-10-11).

## Mutation table (2026-10-11)

Each guard removed from `register.py` in turn; the 57 tests matching
`-k "database or mark or reached"` run against each.

| mutant | guard removed | caught by |
|---|---|---|
| M1 | host-side `[ "$__stacs_db" != db ]` refusal | `test_a_launcher_that_reaches_another_database_is_refused_before_it_loads` (the load ran: `loads != []`) |
| M2 | Python accepts a mark naming any database | all three `test_a_mark_that_does_not_name_the_database_is_not_a_load` cases |
| M2b | Python accepts a mark that only starts with the expected line | the `stacdb extra` case |
| M3 | `|| exit 1` after the query | **survives behaviourally**: the subshell reasserts `set -euo pipefail` after the env file, so a failed assignment exits, and an empty name fails the compare anyway. Kept for symmetry with the load line. (The fire test failed only because its slice anchors on that text.) |
| M4 | mark echoes `t.db` instead of the name read | **survives, equivalent**: the host compare makes the read name equal `t.db` whenever the mark is reached. M1 + M4 together would remove the protection; M1 alone is caught |

## Review round 1 (2026-10-11)

0 bugs; 1 fragile, 2 notes. `review-round1.md`.

- Pooler aliasing (pgbouncer `stacdb = dbname=pgstac_prod`): `db` is both `PGDATABASE` and
  the expected `current_database()`, so such a deployment is now refused on every load and
  no setting fixes it. Fails closed. A separate expected name would be a new config key
  (schema), so it is the user's call, raised in the PR; NEWS states the limit. pypgstac
  sets `search_path` per session, so it works only through a session-mode pooler anyway.
- NEWS overstated the guard: a name comparison cannot see the same name on another server.
  Reworded.
- A CRLF launcher (`docker exec -t`) read "reached 'stacdb', expected 'stacdb'". The FATAL
  line now prints the name with `printf %q` (bash 3.2 gives `$'stacdb\r'` too); three
  cases pinned, all red with `%q` removed.

## Errors Encountered

| Error | Resolution |
|-------|------------|
| Mutation run printed nothing: `-k database_or_mark_or_reached` matched no test | `-k "database or mark or reached"` |
