# Review: Phase 5 (CLI) round 1

Scope: `git diff --cached` (src/stacs/cli.py, tests/test_cli.py, README.md, NEWS.md,
pyproject.toml, research/). Every finding below was reproduced in a scratch copy
(`scratchpad/r1`, suite 288 passed before probing); nothing under the repo was modified
except this file. No network outside loopback.

## Findings

- **[bug]** src/stacs/cli.py:152-163 (`cmd_load`), README.md "Use" example. `load items` /
  `load collection` take `--config` but use only `[transport]`. The config's declared
  `[assets]` rules and `[catalogue] collection_id` are silently ignored, and
  `--expect-collection` is not defaulted from the config. Repro: config
  `collection_id = "new-coll"`, `forbid = ["legacy"]`, plus one item with
  `collection: "old-coll"` and a `legacy` asset.
  `echo items/a.json | stacs load items --config cfg.toml --dryrun` gives rc=0 and
  assembles the item. `stacs audit --config cfg.toml` on the same item fails both rules.
  Without `--dryrun`, that item upserts into `old-coll` with no error. That is the
  hazard `ndjson_write`'s docstring describes, and the README's "rules are declared,
  never loosened" claim does not hold on this documented path. Apply
  `merge_asset_rules` and audit, or refuse `[assets]` on `load`, and default
  `expect_collection` to the config's `collection_id`. `load collection` similarly never
  checks the file's id against `collection_id`.

- **[bug]** src/stacs/cli.py:156 together with register.py `load()` (`return 0` on no
  paths). `stacs load items` exits **0** when it loaded nothing. Reproduced with empty
  stdin (`</dev/null`), with `--dir` on an empty directory, and with `--dir ""`. Each
  printed `nothing to register (0 items)` and returned rc=0. The README's own pipeline
  (`find build/items ... | stacs load items`) with a wrong path or an unbuilt tree reads
  as success in CI. `audit` and `validate` both treat zero items as a failure, and
  `load` should match them at the CLI level.

- **[fragile]** src/stacs/cli.py:133 (`_paths`). `if getattr(args, "dir", None)` treats
  `--dir ""` (an unset variable) as "no --dir" and silently reads stdin. That is the
  empty-flag-read-as-none pattern the asset flags explicitly refuse. With `load items`
  it gives exit 0 (previous finding). With `audit` or `validate` on a terminal stdin it
  blocks waiting for input. Test `is not None` and refuse an empty value.

- **[fragile]** src/stacs/cli.py:209-213 (`_asset_flags`). Each flag is a single-value
  `store`, so a repeated flag keeps only the last value and drops the earlier ones
  silently.
  - `audit --forbid-asset legacy --forbid-asset other` reported `forbid=other`, rc=0, on
    an item that carries `legacy`.
  - `--require-asset zzz --require-asset legacy` checks only `legacy`.

  The config's rules survive, but a rule the caller added is dropped without notice.
  Use `action="append"` (or refuse repeats).

- **[bug]** src/stacs/cli.py:119,128 (`[tuning]` passed through unchecked). `chunk`,
  `page_size` and `fetch_workers` reach `Target` with no type or range check, and
  `chunk` is first used in the read-back after the upsert. Run through the register
  harness in `--mode ids`, every bad value below loaded both the collection and the
  items first, then:
  - `chunk = 0`: `ERROR: could not read back what was registered: range() arg 3 must
    not be zero`, rc 1.
  - `chunk = -1`: the read-back loop runs zero times, so it reports
    `after registering, 1 id(s) are not served by any-collection`. That is a false
    statement that the write did not land, after it did.
  - `chunk = "500"`: TypeError traceback after the write.

  `fetch_workers = "20"` and `fetch_workers = 0` fail before writes, as a traceback and
  as exit 2 respectively. Validate each as a positive int, not bool, in the CLI, before
  `run`.

- **[fragile]** src/stacs/cli.py:102-114 (`build_transport`). `[transport]` values of the
  wrong TOML type cause tracebacks instead of refusals (all before any write):
  - `host = 5`: AttributeError
  - `db = ["x"]`: TypeError
  - `password_env = 1`: TypeError
  - `pypgstac = 5`: TypeError

  Separately, `pg_port = true` passes `Transport.check` because `bool` is an `int`, and
  is exported as `PGPORT='True'`. Type-check the strings and the int (excluding bool) in
  `build_transport`, or add these errors to the refusal path.

- **[fragile]** src/stacs/cli.py:275 (`main`). Only `ConfigError` and `ValueError` are
  caught, so `audit --dir nope` and `validate --dir nope` end in a FileNotFoundError
  traceback. The exit is still nonzero (1). Catch `OSError` as a refusal, as `cmd_load`
  already does.

## Checked and fine

- `require` given as a list, as `""`, or as a different flag value is refused.
- `forbid` works as a string or a list. As `""`, `","` or `[1]` it is refused, and `[]`
  means no rule (tested).
- An empty `[assets]` table means no rules.
- A different `--collection-id` keeps the declared rules.
- Unknown tables and keys are refused, so `password` is refused.
- No argparse default names a deployment, and no secret flag exists.
- `pg_port = "5432"` is refused by `Transport.check` (rc 1).
- `pypgstac` as a string is refused.
- `validate` and `audit` over nothing exit 1.
- The `verify` and `register` exit codes come from `run`.
- The console-script entry point is `stacs.cli:main` (int return, wrapped by
  `sys.exit`).
- Every README command and flag exists.
