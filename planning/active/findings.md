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

## Errors Encountered

| Error | Resolution |
|-------|------------|
