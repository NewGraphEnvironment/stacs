# Review round 3 -- branch 6-report-the-database-each-load-reached (through 1db271c)

## Mechanism

R1 and R2 share one assumption: **a value compared or shown after a layer has re-framed it
is still the value the producer emitted.** Each layer between pypgstac and the comparison
applies its own framing rules: a tty adds `\r`, the shell's `$( )` strips trailing `\n`,
Python's universal newlines and `str.splitlines()` break at `\r`, `\x1c`, `\x85` and
others, and a terminal draws `\r` as nothing. Where one of those rules is not injective,
two different raw values come out as the same text, and an equality check (R2) or a
human reading the text (R1) treats them as equal. Both fixes do the same thing. They pick
one framing that is decided before the comparison (bytes split on `\n` only, then an exact
whole-line compare), and they show values through an injective encoding (`printf %q`).
The test for any remaining instance is whether some layer can collapse two distinct names
or lines into one before an exact compare.

Every place in this change, and in the code it touches, where remote output, a database
name or the mark is produced, moved, split, compared or shown:

1. **`Transport.db` validation** (`_DB_NAME.fullmatch`, ASCII `[A-Za-z0-9_]+`). SAFE.
   `fullmatch` does not accept a trailing `\n`, unlike `$`. The host literal `q(t.db)`,
   the `expected {t.db}` text and the Python mark all use this one ASCII value.
2. **Producer: real pypgstac via fire** (`<launcher> _db query_one 'SELECT
   current_database()'`). SAFE. Probed with real fire 0.7.1 and the real
   `PgstacCLI` from pypgstac 0.10.0, with only `PgstacDB.query_one` stubbed. fire does not
   take `_db` as the constructor's `dsn`. It resolves the private member, passes the
   query as one string (`[('SELECT current_database()',)]`) and prints `stacdb\n`.
   Constructing `PgstacDB` neither connects nor writes to stdout. `query_one` returns
   `r[0]`, a bare `str`. `load` returns None, so fire prints nothing for it.
   I could not check an older fire on a pypgstac 0.9.6 host, because only 0.7.1 is cached.
   If one cannot resolve `_db`, fire exits non-zero and the load is refused, so that case
   fails closed.
3. **Host capture: `__stacs_db=$( ... ) || exit 1`**. SAFE IN PRACTICE, with one theoretical
   collapse. `$( )` strips every trailing `\n` (measured on bash 3.2: `stacdb\n\n\n` reads as
   `stacdb`). A database whose real name is `stacdb` followed by newlines would therefore
   pass. libpq connects to the exact `PGDATABASE`, so that can only happen if a launcher
   with its own DSN points at a database someone deliberately created with a trailing
   newline in its name. `\r`, spaces, banners and an empty result all survive the capture
   and are refused. Not a finding. If it ever matters, the fix is
   `$(...; echo .)` and then stripping the sentinel plus one `\n`.
4. **Host compare: `[ "$__stacs_db" != 'stacdb' ]`**. SAFE. The variable is quoted and
   compared byte for byte. It runs in the subshell after the env file and the PG* exports,
   and before the load. It also catches the case where a `PGSERVICE` set in the env file
   overrides the exported `PGDATABASE` (libpq applies service-file values before env vars).
5. **Host display: `$(printf %q "$__stacs_db")` in the FATAL**. SAFE. Measured on
   `/bin/bash` 3.2.57: `$'stacdb\r'`, `''`, `stacdb\ extra`, `$'a\034b'`. The value is an
   argument, not the format, so a `%` in it is inert. A failing substitution inside an
   `echo` argument does not trip `-e`, and `exit 1` follows either way. The tests run
   this under bash 3.2, because `/bin/bash` comes first on PATH and the ssh stub's
   `/bin/sh -c` resolves `bash` there.
6. **Host success line: `echo "STACS_LOADED $__stacs_n <kind> $__stacs_db"`**. SAFE. It is
   reached only after item 4 has passed, so `$__stacs_db` is exactly `t.db` (ASCII
   alphanumerics, so `xpg_echo` cannot change it). pypgstac runs as a child process and
   cannot reassign the variable. The success line is still printed only inside the
   subshell, after the load returns 0.
7. **Transport: ssh** (`_ssh`, no `-t`/`-T`). SAFE for this change. Without a pty, no
   `\r` is added. With `RequestTTY force` in a user's ssh config, the mark would arrive as
   `...stacdb\r` and Python would refuse a load that actually succeeded. That fails closed,
   and the payload over a pty was already broken before this branch (canonical-mode echo
   and line-length limits), so it is not new here. `-T` would close both.
8. **Python decode** (`r.stdout.decode("utf-8", errors="replace")`). SAFE. An invalid
   byte becomes U+FFFD and never an ASCII character, so a replacement cannot produce the
   mark.
9. **Python split** (`.split("\n")`, then dropping one trailing `""`). SAFE. `str.split`
   with an explicit separator splits on that separator only. Empty stdout gives `[]`, as
   before.
10. **Python compare** (`f"STACS_LOADED {lines} {kind} {t.db}" in out_lines`). SAFE. It
    requires an exact whole line, with `\r` and `\x1c` / `\x85` suffixes refused.
    Side effect of R2's fix: output that ends in a lone `\r` with no `\n` (a progress
    meter) would now run into the mark's line, so a good load would be refused. That fails
    closed, and pypgstac writes nothing to stdout on a load (see item 2), so no producer
    is known.
11. **Python relay** (`log(line.rstrip("\r"))` for every line not starting with the mark).
    SAFE. It strips only the trailing `\r` for display, and the compare never sees the
    stripped value. A mismatched mark line is hidden from the log. That is reachable only
    if the host compare is bypassed, and the error still names the database expected.
12. **Python display** (`reached  : {t.db}`, error text). SAFE. It shows the validated
    `t.db`, which equals the name read whenever this line is reached (accepted tradeoff).
13. **Test fake pypgstac**. SAFE. It checks argv exactly, echoes `$FAKE_PYPGSTAC_DB` (by
    default `$PGDATABASE`, which matches libpq) with its bytes intact, and logs the
    database it was asked under. `test_the_real_fire_...` runs the real fire over the
    words `shlex.split` takes from the generated line.
14. **Test mark injection** (`printf '%s\n' '<mark>'` with a literal CR, `\x1c` or U+0085 in
    the script). SAFE. The bytes reach the stub unchanged as UTF-8 argv.

Mutation table, run in a copy with the copy's own interpreter. Note that the copied
`.venv/bin/pytest` shebang points at the original venv, so use `uv run python -m pytest`
in a copy:

| mutation | result |
|---|---|
| host compare disabled | 4 failed |
| `.split("\n")` back to `.splitlines()` | 12 failed |
| relay `rstrip("\r")` removed | 1 failed |
| `printf %q` removed | 3 failed |
| Python compare ignores `<db>` | 4 failed |
| query replaced by `echo t.db` | 7 failed |

Each guard fires.

## Clean

No issue that causes a failure, a security problem or data loss. Items 3, 7 and 10 are
residuals in the fail-closed direction or need contrived setups. They are recorded above
and are not findings.
