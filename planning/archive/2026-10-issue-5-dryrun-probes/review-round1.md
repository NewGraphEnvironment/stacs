# Review round 1 — branch 5-register-dryrun-skips-the-api-and-ssh-pr vs main

Reviewed: src/stacs/register.py, src/stacs/cli.py, tests/test_register.py, tests/test_cli.py,
README.md, NEWS.md, planning/active/*. Suite run in a scratch copy: 498 passed.

## Findings

- **[fragile, minor: release-note accuracy]** NEWS.md:9-10 — "`register --dryrun` (all
  modes) and `load --dryrun` used to return before them, so a dryrun that passed proved
  nothing about the API or ssh." That holds for `all`, `ids` and `load`, but not for
  `drift` and the API. On main, a drift dryrun returned only after `_registered`,
  `_collection_state` and `_queryables_drift`, all of which read the API, so a dead API
  already failed a drift dryrun. `findings.md` records this correction ("a drift dryrun
  does read the API ... what it skips is the ssh probe"), but the NEWS line states the
  uncorrected version. Suggested wording: "...so a passing dryrun proved nothing about ssh,
  and in `all`/`ids` nothing about the API either."

No bugs, security issues or data-loss risks found. Checked:

- **Real (non-dryrun) paths are unchanged.** The probe block went from `writes and not
  dryrun` to `writes` and moved above the all/ids dryrun branch. It is still before the
  fetch and before any write. A real all/ids/drift run probes in `_run` once, then once per
  `_send`, which matches main (`_send`'s probe moved above the dryrun return, and was not
  duplicated). Order within the block is unchanged: `_api_probe`, ssh probe, then queryables
  drift (all/ids).
- **`verify` is untouched.** `writes` is False there, so the block is skipped as before.
- **`q_missing`/`q_changed` in the all/ids dryrun f-string.** They are referenced only when
  `target.queryables` is truthy, and all/ids always has `writes` True, so the block has
  bound them. No UnboundLocalError.
- **The ids-file and link-set checks still run before the probes.**
  `test_ids_mode_refuses_a_missing_or_empty_file` pins this on the dead API.
- **README, help and NEWS claims match the code.** These are where all/ids stop (before
  the fetch), where drift stops (after the body compare, before the audit), where load
  stops (after its checks, after the probe), that no mode runs the remote script, and the
  "reached" lines. The new README paragraph sits inside the `use` markers and has no links.
- **The tests can fail.** I ran two mutations in a scratch copy:
  - Moving `_send`'s probe back after the dryrun return turned 5 tests red (two in
    test_cli, the load-dryrun pair, and `test_queryables_dryrun_sends_nothing`).
  - Restoring `if writes and not dryrun:` turned 11 tests red (the 9 parametrized
    reach/refuse cases and both queryables-dryrun tests).
- **No real ssh and no network.** Every test_register test that reaches `_run` or
  `load`/`load_queryables` takes the `env` fixture (stub ssh on PATH), which I checked by
  AST over the file. test_cli's autouse fixture replaces `register.probe`, and every
  test_cli load is `--dryrun` or has `cli.load` monkeypatched, so the remote-script ssh is
  never reached.

/Users/airvine/Projects/repo/stacs/planning/active/review-round1.md
