# Code-check round 2 (#6) — branch diff, focus on 2ae77aa

## Findings

- **[fragile]** src/stacs/register.py:417 and :429 — Python's half of the check does
  not compare "exactly `db`" for every name. `subprocess.run(..., text=True)` reads
  stdout with universal newlines (a lone `\r` becomes `\n`), and `str.splitlines()`
  also splits on `\v`, `\f`, `\x1c`-`\x1e`, `\x85`, ` `/` `. So a mark
  `STACS_LOADED 1 collections stacdb\r` (or `stacdb\x1cother`) yields a line that
  equals the expected mark exactly, and `_send` accepts it.
  Probe: with the host compare disabled in a copy (`if false && [ ... ]`), the
  `stacdb\r` case loads and Python raises nothing; the test went red only on its
  stderr / `loads.log` assertions, i.e. on the host half. Not reachable today: the
  host's `[ "$__stacs_db" != stacdb ]` refuses every such name before the load and
  the mark is printed only after it. It matters only because
  `test_a_mark_that_does_not_name_the_database_is_not_a_load` documents Python's half
  as requiring "exactly `db`" on its own, and its parameters never include a
  separator character, so that claim is untested where it is false. If the Python
  half is meant to stand alone, compare against `r.stdout.split("\n")` with the
  `\r`-translation off (`newline` handling via bytes), or reject a mark line
  containing any character outside `_DB_NAME`'s set; otherwise narrow the docstring.
  Low priority.

## Checked and clean

- Round 1 fix (`printf %q` in the FATAL line): `/bin/bash` 3.2.57 and bash 5.3 print
  identical output for all three parametrized names (`$'stacdb\r'`, `''`,
  `stacdb\ extra`); nested quotes inside `$( )` inside `"..."` parse on 3.2 (the
  harness runs PATH `bash`, which is `/bin/bash` 3.2 here). `{t.db}` unquoted in the
  message is safe: `_DB_NAME.fullmatch` restricts it. The `if ...; then echo; exit 1; fi`
  exits under the subshell's `-e`, before the load.
- Mutation: removing the host compare reds 4 tests; removing `%q` reds the `stacdb extra`
  case (and the others). The guards are pinned.
- fire: probed fire 0.7.1 against a class with pypgstac 0.10.0's exact constructor
  signature (`dsn=""`, `version`, `debug`, `usequeue`, plus a `version` property).
  `_db` is not consumed as the positional `dsn` (fire does not pass a class's
  defaulted args positionally), `_db` resolves via `dir()`, the query arrives as one
  string, and stdout is exactly `stacdb\n`. pypgstac 0.10.0's `query_one` returns
  `r[0]` for a one-column row; `connect()` runs only `search_path`/`application_name`
  setup, autocommit, no writes.
- The query runs in the same subshell, after the env file, PATH, `cd`, PG* and
  PGPASSWORD exports, with the same launcher words as the load, so it opens the
  connection the load opens. No secret enters argv.
- Full suite in a copy (fresh venv): 482 passed.
