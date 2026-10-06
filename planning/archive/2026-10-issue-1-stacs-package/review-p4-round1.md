# Review p4 round 1: staged diff (src/stacs/register.py, tests/test_register.py)

Scope: the staged diff, compared against stac_dem_bc `catalogue_register.sh`,
`item_register.sh`, `collection_register.sh` and the `register_manifest.py` main() branches
(fetched-paths, hrefs-published, verify-serving, diff). Probes ran in a scratch copy, and
the suite was green there (244 passed, 1 deselected).

## Findings

- **[severity: bug]** src/stacs/register.py:153-164, 232-235. On bash 3.2 the remote
  script exits 0 without loading when sourcing `env_file` fails, and `load()` then reports
  success. This is the same class as the `${VAR:?}` case that was already fixed. That fix
  covered one instance. The class is broader: any expansion error, and any failed `.`,
  that happens after `trap ... EXIT` is armed. On 3.2 these leave `$?` at 0 inside the
  trap and the shell exits 0. Explicit `exit 1`, a failing command and a 127 are all
  preserved.

  The script has two paths in this class, both outside the code:
  - `. <env_file>` when the file is missing or unreadable.
  - Any unbound reference inside the caller's env file, under `set -u`. A
    docker-compose `.env` with an unquoted `$` in a value is the common way to get one.

  Measured, with `set -euo pipefail` and then `trap 'rm -f "$t"' EXIT`:

  | line after the trap | bash 3.2.57 | bash 5.3.9 |
  |---|---|---|
  | `. ./nonexistent_env` | rc=0 | rc=1 |
  | `. ./envfile_unbound` (contains `A=${NOT_DEFINED}`) | rc=0 | rc=1 |
  | `echo "$UNSET_X"` | rc=0 | rc=1 |
  | `false` / `no_such_cmd` | rc=1 / 127 | same |

  With no trap, 3.2 returns 1 for all three of the first rows, so the trap is the cause.

  End to end in a scratch copy: an ssh stub that runs the script under /bin/bash 3.2, and
  `Transport(env_file="/nonexistent/.env")`. The result was
  `load(t, "collections", [...])` returning 1 ("loaded"). pypgstac never ran.

  `run()` is mostly protected, because it verifies after every load:
  - A collection that needed changing reads back `changed`.
  - Items that needed changing are not served.

  Two problems remain. First, the error then names the wrong cause ("after registering, N
  id(s) are not served") instead of the load failure. Second, `load()` used on its own reads
  a failure as success. The suite cannot reach this: no end-to-end test sets `env_file`.
  The only test that does is the string assertion in
  `test_remote_script_quotes_every_caller_value`.

  A status-preserving trap does not fix it (`trap 'rc=$?; ...; exit $rc'`): on 3.2, `$?`
  is already 0 inside the trap. What does fix it, measured on 3.2 and 5.3 across all four
  rows above: a success flag, set as the script's last line, which the trap tests:

  ```sh
  ok=0
  t=$(mktemp ...)
  trap 'rm -f "$t"; [ "$ok" = 1 ] || exit 1' EXIT
  ...
  pypgstac load ...
  ok=1
  ```

  Alternatively (or as well), capture stdout on the Python side and require the in-band
  `loaded $n <kind>` line rather than trusting the exit status, per "A wrapper's exit is
  not the work". A test with `env_file` pointing at a missing file, under a bash-3.2 stub
  `bash`, would pin either fix.

## Checked and found sound (no finding)

- **Guards enumerated from the shell.** Each one has a counterpart in the port:
  - `collection_register.sh`: DB name validation, probe first, BatchMode, the receiving
    count of 1, upsert, no `--dsn`.
  - `item_register.sh`: zero paths reported as nothing to do,
    `WRITTEN != EXPECTED`, `--expect-collection`, the receiving-side count, payload on
    stdin.
  - `catalogue_register.sh`:
    - the id mismatch;
    - zero published items, and duplicate ids with different hrefs (both refused in
      `collection_item_links`);
    - identical-href duplicates;
    - unknown ids in an ids file;
    - dryrun exits before the probe and the fetch;
    - probe before the fetch in every writing mode;
    - the fetch gate on the on-disk set;
    - `collection-state` restricted to same, changed or missing;
    - verify in all directions, plus the collection;
    - drift's dryrun and in-sync exits;
    - the fetched-paths id check (via `_digests`) and the audit with `expect_ids`, both
      before the collection upsert;
    - collection before items;
    - the post-load collection state, the full recheck for all and for drift with a
      changed collection, and verify-serving content and id sets.
- **Quoting layers.** Every caller value is shlex-quoted once, for the bash that runs the
  script. The whole script is shlex-quoted once, for the remote login shell that gets the
  space-joined ssh command. Other details:
  - `--` blocks option injection through the host.
  - db and password_env are regex-restricted with `fullmatch`.
  - PG* exports come after the env file.
  - The password is referenced by name and expanded inside double quotes, so it is never
    re-parsed. It is in no argv on either end.
  - The POSIX `'"'"'` form survives sh, dash, bash and zsh, and fish too since the script
    has no backslashes. csh fails loudly.
- **Write ordering and refusals before writes.** All refusals that can come before the
  collection upsert do: the audit, the id checks, the fetch gate, and the transport check.
  Item ndjson's `expect_collection` runs after the collection upsert, but the audit has
  already applied the same predicate to the same files.
- **Resources at 100k.** Both temp dirs are context-managed. Every file handle is opened
  with `with`. Executor shutdown and cancellation are handled. Digests are kept rather than
  bodies.
