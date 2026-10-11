# Review round 1 — branch 6-report-the-database-each-load-reached

## Findings

- **[fragile]** src/stacs/register.py:308-311 (the `__stacs_db=$(... query_one 'SELECT current_database()')` line and its compare) — `current_database()` returns the **backend's** database name, and the same `t.db` is used both as `PGDATABASE` (what the client asks for) and as the expected answer. Those two differ whenever the connection goes through a pooler that aliases databases: pgbouncer `[databases] stacdb = host=... dbname=pgstac_prod` accepts `PGDATABASE=stacdb` and answers `current_database()` with `pgstac_prod`. Such a deployment loaded fine on 0.1.2 and is now refused on every load, and there is no setting that fixes it: setting `db` to the backend name makes `PGDATABASE` name a database the pooler does not know. It fails closed (nothing is loaded, the FATAL line names both values), so this is a regression for that topology rather than a data-loss risk. If that topology is out of scope, say so in NEWS; otherwise the expected name needs to be separable from the requested one (e.g. an optional `expect_db` defaulting to `db`).

## Notes (not defects; for the author's judgement)

- NEWS.md "Unreleased" says a launcher that does not pass `PGDATABASE` on, "a container, a wrapper with its own DSN", used to load into another database unnoticed. The check compares the database **name** only. A wrapper whose own DSN points at another server, or another cluster, carrying a database of the same name (common names: `postgres`, `pgstac`) passes the check and loads there. The accepted tradeoff covers `db` naming the wrong database; this is a different case: the right name on the wrong server. Worth one clause in NEWS so the guard is not read as covering it.
- A launcher that writes CRLF (a TTY-allocating wrapper such as `docker exec -t`) is refused with `reached database 'stacdb', expected 'stacdb'`, because the `\r` is invisible in the message. It fails closed, but the message reads as a contradiction.

## Probes run (in a scratchpad copy, repo untouched)

- Full suite in a copy: 479 passed.
- pypgstac 0.9.6 and 0.10.0 wheels inspected: `PgstacCLI.__init__` sets `self._db = PgstacDB(dsn=dsn, ...)` in both. `query_one` is identical in both and returns `r[0]` (a bare `str`) for a one-column row. pypgstac writes nothing to stdout outside `load.py`'s `-` stream. It requires `fire>=0.7.0`, and fire 0.7.1's real `Fire` is what the new test drives.
- I ran the generated script under `/bin/bash` 3.2.57 against a stub launcher. The query printing `otherdb`, printing nothing, printing `stacdb\r`, printing a noise line before `stacdb`, and exiting 1 all exit 1 with no load and no `STACS_LOADED`. A correct name, with or without a trailing newline, loads and prints `STACS_LOADED 1 collections stacdb`.
- Quoting: `t.db` is `_DB_NAME.fullmatch`-validated before its unquoted use inside the FATAL message's double quotes. `$__stacs_db` is expanded inside double quotes and never re-evaluated. No secret is put in argv.
