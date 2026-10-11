# Asking pypgstac which database its connection reaches

**Verified:** 2026-10-11 · **Issues:** #6 · **Produced by:** reading pypgstac source at
tags `v0.9.6`, `v0.9.8` and `v0.10.0`
([pgstac](https://github.com/stac-utils/pgstac) `src/pypgstac/src/pypgstac/pypgstac.py`,
`db.py`) and fire 0.7.1 `core.py`; real fire run over the words `register.remote_script`
emits, against a stub with pypgstac 0.10.0's `PgstacCLI` constructor
(`tests/test_register.py`, `test_the_real_fire_reaches_the_database_query_and_prints_the_bare_name`).

`pypgstac _db query_one 'SELECT current_database()'` prints the name of the database the
CLI's own connection reaches, and needs nothing on the host beyond pypgstac.

- `PgstacCLI.__init__` sets `self._db = PgstacDB(dsn=dsn, ...)` in all three versions.
  With no `--dsn`, `dsn` is `""`, so the pool's `conninfo` is empty and libpq reads the
  PG* environment: the same connection a `pypgstac load` in the same environment opens.
- `fire.core._GetMember` resolves any name in `dir(component)`, private ones included, so
  `_db` is reachable as a subcommand. fire does not take `_db` for the positional `dsn`:
  it does not pass a class's defaulted arguments positionally.
- `PgstacDB.query_one` returns a one-column row as the bare value, and fire prints a `str`
  result as itself plus `\n`. `connect()` sets `search_path` and `application_name` and
  writes nothing.

What it tells you: the database **name** on whatever server the connection reached. It
cannot see a database of the same name on another server, and behind a pooler that maps
a client-side name to a different server-side one (pgbouncer `stacdb = dbname=other`) it
answers with the server-side name. pypgstac sets `search_path` per session, so it only
works through a session-mode pooler in the first place.

How stacs uses it: `register.remote_script` runs the query in the load's own subshell before
the load, refuses on the host if the answer is not `Transport.db`, and prints the name in its
success line, `STACS_LOADED <n> <kind> <db>`, which `_send` requires exactly. The
archive of #6 has the mutation table and the review rounds.
