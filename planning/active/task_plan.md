# Task: Report the database each load reached, and refuse a mismatch (#6)

The read-back after a write compares what the API serves with what was sent. When the body was already being served identically (a re-register, an `ids` run on an unchanged item, a first load into a catalogue that is already populated), that comparison passes whatever database pypgstac connected to. `STACS_LOADED <n> <kind>` shows pypgstac exited 0 on *some* database.

Measured on a live catalogue (2026-10-07): the only evidence of the target was a separate read-only ssh check that opened `pypgstac.db.PgstacDB()` under the same environment `remote_script()` builds and ran `SELECT current_database()`.

## Approach

**How the database is queried (a mechanism choice, open to change at approval):** the
query goes through the caller's own launcher:
`<launcher> _db query_one 'SELECT current_database()'`. The words to the right of the
launcher are pypgstac's own, and the host needs nothing new. The connection is opened
exactly as the load opens its own: `PgstacDB(dsn="")`, libpq reading the same PG*
environment, in the same subshell. That means a docker or wrapper launcher that ignores
`PGDATABASE` is caught. psql was the alternative: it adds a host requirement and runs a
different client from the one the load uses.

- Checked: pypgstac 0.9.6, 0.9.8 and 0.10.0 all set `self._db = PgstacDB(...)` on
  `PgstacCLI` and define `PgstacDB.query_one`, which returns a 1-column row as a bare
  value. `fire`'s `_GetMember` resolves any name in `dir()`, including private ones. The
  0.10.0 source is in the uv cache; 0.9.6 and 0.9.8 were read via the GitHub API.
- What this does not cover, stated in NEWS: if `db` itself names the wrong (existing)
  database, the check passes, because `db` is the caller's value. What it catches is the
  connection reaching a database other than `db`.

**When the query runs:** once, inside the subshell, after the PG* exports and **before**
the load. The host refuses a mismatch before pypgstac writes anything, and the value it
read goes into the mark. The issue describes an after-load query plus an optional
pre-write one. A single pre-write query covers both: it uses the same subshell, the same
environment and the same launcher, and it refuses before the write instead of after it.
For `run()` the first load is the collection, so a wrong target is refused before
anything is written.

## Phase 1: Tests first (`tests/test_register.py`)

- [x] Fake pypgstac answers `_db query_one 'SELECT current_database()'` (exact args, else
      exit 2): it prints `${FAKE_PYPGSTAC_DB-$PGDATABASE}` and exits
      `${FAKE_PYPGSTAC_DB_RC:-0}`. It logs to `$SSH_LOG.dbq`, not `$SSH_LOG`, so
      `Run.loads` and `_StubAPI` stay unchanged. The two new variables are cleared in the
      `env` fixture.
- [x] A launcher that reaches another database is refused on the host and loads nothing:
      `all` returns rc 1, the error names both databases, and `r.loads == []`. The
      collection is never loaded.
- [x] A failing database query is refused and loads nothing.
- [x] Python requires the database in the mark. A remote printing the old
      `STACS_LOADED 1 collections`, or `... collections otherdb`, raises "without
      confirming". This runs through a monkeypatched `remote_script`, so the Python check
      is exercised without the host check.
- [x] A successful load logs the database it reached.
- [x] Real `fire` over the shell-split words of the query line, against a stub CLI with a
      `_db` attribute, calls `query_one("SELECT current_database()")`. Fire prints a str
      result as the bare value on stdout, checked with capsys. This is the same pattern
      as `test_the_real_fire_reads_the_collection_ids_as_a_list_of_that_one_id`.

## Phase 2: Implementation (`src/stacs/register.py`)

- [x] `remote_script`: after the exports, add
      `__stacs_db=$(<launcher> _db query_one 'SELECT current_database()') || exit 1`, then
      `if [ "$__stacs_db" != <q(db)> ]; then echo "FATAL: pypgstac reached database
      '$__stacs_db', expected '<db>' -- nothing loaded" >&2; exit 1; fi`, then the load.
      The mark becomes `echo "STACS_LOADED $__stacs_n <kind> $__stacs_db"`.
- [x] `_send`: require `f"{LOADED_MARK} {lines} {kind} {t.db}"` exactly, and log
      `reached  : <db>` after `loaded`.
- [x] Docstrings: the `remote_script` text and its doctest (now one extra `pypgstac` line),
      the `LOADED_MARK` comment, and the module docstring sentence on writes.
- [x] Mutation table in `findings.md`. Remove the host compare: test 2 fails on
      `loads == []`. Remove the Python db check: test 4 fails. Drop the `|| exit 1`, or
      break the query: test 3 fails.

## Phase 3: Docs

- [x] `NEWS.md` `## Unreleased` entry, including what the check cannot see.
- [x] `README.md` "No setting is a secret" paragraph: one sentence saying each load
      confirms the database the host connected to, outside the snippet markers if a link
      is added.
- [x] `CLAUDE.md` line 48: `STACS_LOADED <n> <kind> <db>`.

## Validation

- [x] Tests pass (`uv run pytest`), including the doctests
- [x] `/code-check` clean (each commit, or once over the branch with `/code-check branch`)
- [x] PWF checkboxes match landed work
- [ ] `/planning-archive` on completion
