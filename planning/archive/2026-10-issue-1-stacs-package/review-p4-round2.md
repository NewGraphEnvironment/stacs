# Review p4 round 2: the round-1 fixes (success flag + `STACS_LOADED` sentinel)

Scope: the staged `src/stacs/register.py` and `tests/test_register.py`, focused on
`remote_script()` and `load()`. Every probe ran in a scratch copy
(`scratchpad/r2`), never against the repo tree. The suite there is green as staged
(248 passed, 1 deselected). pypgstac 0.10.0 was installed from PyPI into a scratch venv to
read its source and measure its exit codes. Its only connection attempt went to
127.0.0.1:1, which refused.

## Findings

- **[severity: bug]** src/stacs/register.py:171-172, 189-191. The sentinel only proves
  the script reached the line after pypgstac. That counts as proof the load succeeded
  only while `set -e` is still on, and the caller's `env_file` can turn it off: it is
  sourced into the same shell. With an env file containing `set +e` and pypgstac exiting
  1, the remote exits 0 and prints `STACS_LOADED 1 collections`. `load()` then logs
  `loaded   : 1 collections` and returns 1. Measured on both /bin/bash 3.2.57 and
  /opt/homebrew/bin/bash 5.x, using `remote_script` directly and end to end through
  `load()` with the test harness (`test_r2_env_file_set_plus_e_hides_a_failed_pypgstac`,
  added in the copy only, red on both shells). Nothing in the env file has to be unusual
  apart from that one line. An env file that is really a shell script, such as an
  activate or init snippet, can carry it. `run()` still catches the failure for any
  item or collection whose served body differs, because it reads back afterwards. A
  standalone `load()` reads it as success, which is the exact failure round 1 set out
  to close.

  **Fix, proven in the copy:**

  ```python
  lines.append(f'{launcher} load {kind} "$t" --method upsert || exit 1')
  ```

  With that line the probe goes green on both shells, and the suite passes (250 passed,
  with the one string assertion in `test_remote_script_quotes_every_caller_value`
  updated). An explicit `exit 1` keeps its status under bash 3.2's EXIT trap. A guard
  that does not depend on `-e` is also needed, because `-e` is caller-mutable state.
  Re-asserting `set -euo pipefail` after the `.` line costs nothing as well.

- **[severity: bug]** src/stacs/register.py:160-164, 172, 189. The script keeps its
  state in `t`, `n` and `ok`, and then sources the caller's file into the same
  namespace. If the env file assigns `t`, three things happen:
  - pypgstac loads THAT file instead of the payload;
  - the EXIT trap runs `rm -f` on it, deleting a file on the STAC host;
  - the real payload temp file leaks.

  The sentinel still prints and the remote exits 0. Measured on both bashes: an env
  file with `t=<path>/victim.txt` produced `pypgstac got file=.../victim.txt`, and
  afterwards `victim_exists=False`. `run()`'s read-back would flag the wrong content,
  but the host file is already gone.

  The other two names are lower risk:
  - assigning `n` breaks the sentinel, which fails closed;
  - assigning `ok=1` defeats the trap flag, but the sentinel still covers it.

  **Fix:** use names that cannot plausibly collide (`__stacs_tmp`, `__stacs_n`,
  `__stacs_ok`), mark the first two `readonly` before the `.` line, or both. On 3.2, an
  assignment to a readonly variable becomes a failure that the ok-flag trap turns into
  `exit 1`.

- **[severity: fragile]** src/stacs/register.py:5-6, 144-147, 247-249. These lines say
  a failed load is whole-or-nothing:
  - the module docstring: "A load that fails here leaves the previous rows serving";
  - `remote_script`'s docstring: "One `pypgstac load` is one transaction ... a failure
    rolls back whole";
  - the error raised: "nothing from this load was committed".

  In pypgstac 0.10.0 that holds for collections, but not for items:
  - `PgstacDB.connect()` sets `autocommit = True` (db.py:111).
  - `Loader.load_items` splits the input into chunks of 10000. Within each chunk it
    groups by partition and calls `load_partition` once per group (load.py:654-680).
  - Each `load_partition` call commits in its own `with conn.transaction():`
    (load.py:363).

  So an items load that fails part way has already committed every earlier chunk or
  partition. The data is safe: upsert-only means a re-run converges. But the message
  tells the operator the database is unchanged when it may hold a mixed catalogue. That
  is the state the "never chunk" reasoning claims to rule out. **Fix:** reword the error
  ("pypgstac commits per partition, so part of it may be committed; re-run, upsert makes
  that safe"). Drop the single-transaction claim, or bound it to `kind == "collections"`.

## Answers to the specific questions

- **Can the sentinel appear without pypgstac succeeding?**
  - Yes, through the first finding (`set +e` in the env file), and through the second
    (pypgstac succeeding on the wrong file).
  - Not through a `-e`-suspended context in the script itself. The launcher line is
    top-level: not inside `if`, `&&`, `||` or a function, and not part of a pipeline.
  - Not through pypgstac's own output either. pypgstac 0.10.0 wrote 0 bytes to stdout
    in every measured case, because Fire prints nothing for a `None` return and logging
    goes to stderr.
- **Does `pypgstac load` exit non-zero on failure?**
  - A connection failure gives rc=1, through an uncaught `PoolTimeout` under Fire.
  - Exceptions in `load_items`/`load_collections` propagate the same way, so a failed
    load does exit non-zero.
  - One caveat, unreachable here because `remote_script` validates `kind`: `pypgstac
    load <anything other than items|collections> f` exits 0 having done nothing, since
    `PgstacCLI.load` is two bare `if`s with no else. A pypgstac exit 0 is not proof of
    work in general.
  - Partition-stats failures after the commit are logged and exit 0 by design; the rows
    are in.
- **Pipe deadlock or decoding?**
  - No deadlock. stdin is a regular file, only stdout is a pipe, stderr is inherited,
    and `run()` drains stdout with `communicate()`.
  - Non-UTF-8 bytes are covered by `errors="replace"`, and the sentinel is ASCII.
  - Large output is held in memory but is not a hang.
- **Is `in out_lines` exact enough?** Yes. It is whole-line equality on
  `STACS_LOADED <written> <kind>`, and `<n>` is the receiver's own count, so it also
  re-asserts the count.
  - The only mismatch mode is a false failure: a preceding stdout writer that leaves no
    trailing newline glues itself to the sentinel line. That fails closed, and pypgstac
    does not do it.
  - An env file that installs its own `trap ... EXIT` replaces the ok-flag trap, and on
    3.2 the expansion-error exit goes back to 0 (measured). The sentinel still catches
    that case (measured), so the two layers do cover each other there.

## Mechanism

**The process that did the work also produced the proof of it, and caller-supplied code
runs inside that process.**

Round 1 was "an exit status taken as proof the work happened." The sentinel moves the
proof from the exit status to a line on stdout. But that line is printed by the same
shell, and it is printed only because `-e` stopped the shell when pypgstac failed. The
sourced env file can turn `-e` off, rebind `t`, `n` and `ok`, or replace the trap. So the
sentinel carries the same trust as before, still self-reported. The closer the proof
gets to an independent observation, the less any of that matters:
1. an explicit `|| exit 1` that does not depend on `-e`;
2. names the caller cannot rebind;
3. at the top, `run()`'s read-back through the API.

### Every trusted subprocess or remote result

| # | where | what is trusted | verified by something other than its own status? |
|---|---|---|---|
| 1 | `probe()` L204 | `ssh host true` exit 0 means reachable | No, but it claims no work. A false pass only moves the failure to `load()`. Fails closed. |
| 2 | remote `mktemp` L161 | exit status | Not needed: a failure aborts before anything is read or loaded. |
| 3 | remote `cat > "$t"` L163 | that stdin arrived whole | Yes. The receiver's `wc -l` must equal `written` (L164-169), and the sentinel echoes `$n` back to Python. |
| 4 | remote `[ "$n" -ne N ]` L165 | numeric `n` | Fails toward pass if `n` is non-numeric (`[` rc 2 in `if` means proceed). Unreachable: `wc -l | tr -d ' '` is always digits, and a `wc` failure aborts under `-e`/pipefail. |
| 5 | remote `. env_file` L172 | exit status, plus the assumption that it leaves the shell's state alone | Status: yes, through the ok-flag and the sentinel. State: **no**. See findings 1 and 2. |
| 6 | remote `cd`, `export` L174-187 | exit status | Yes, through `-e` and the ok-flag. The password guard is an explicit `exit 1`. |
| 7 | remote `pypgstac load` L189 | **pypgstac exit status, through `-e`** | **Only through `-e`, which the env file can turn off (finding 1).** pypgstac's own exit 0 is not universal proof of work (the unknown-table case). |
| 8 | `load()` L246-252 | ssh rc and the sentinel | Both are now required. Both are still produced by the remote shell itself (rows 5 and 7). |
| 9 | `load()` L228 | `ndjson_write`'s own count against `len(paths)` | Self-reported, but the independent check is row 3, where the receiver counts the bytes that actually arrived. |
| 10 | `fetch_bodies` L392 | its `failed` list | Not trusted. The gate is the on-disk set (L394-397), and every body is parsed and id-checked by `_digests`. |
| 11 | `_read_url` L333 | collection.json body | Parsed, and its id is checked against `collection_id`. |
| 12 | `bodies_registered` / `collection_state` / `bodies_serving` | API answers | Id sets in both directions plus digests. A repeated id, a short page or a missing digest raises. `bodies_serving` (L505) and `content_diff` (L410, L496, L508) are not wrapped in `RegisterError`, so their RuntimeError or ValueError escapes `run()` as a traceback instead of `return 1`. That is fail-closed, so not a finding. |
| 13 | `load("collections")` in `run()` L477 | rows 7 and 8 | Yes. The read-back `_collection_state(...) == "same"` at L484. |
| 14 | `load("items")` in `run()` L479 | rows 7 and 8 | Yes. The full re-diff, or `bodies_serving` on `todo` with digests. The one blind spot is inherent and harmless: an item whose body was already identical cannot reveal a silent load failure. |

In short: inside `run()`, every write is verified by read-back through the API.
Standalone, `load()` is verified only by things the remote shell says about itself, and
findings 1 and 2 show the caller's env file can make it say them falsely.
