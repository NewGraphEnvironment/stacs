# Review round 2: branch 5-register-dryrun-skips-the-api-and-ssh-pr vs main

Reviewed: src/stacs/register.py, src/stacs/cli.py, tests/test_register.py, tests/test_cli.py,
README.md, NEWS.md, planning/active/*. I ran the suite in a scratch copy, after deleting the
copied `.venv` and confirming that `stacs.__file__` named the copy: 498 passed. The
original `register.py` was compared with `cmp` after the mutations and is intact.

## Findings

- **[fragile, minor: a test weaker than its name]** tests/test_register.py:991-995
  `test_a_dryrun_reaches_the_host_and_the_api_and_says_so`. The host half is real
  (`r.probes == 1`). The API half rests only on the string
  `[dryrun] reached {api.url} and ...`, and `_say_reached` prints that unconditionally.
  It is not evidence that the API was read. Mutation in the copy: replacing
  `_api_probe(target)` in `_run` with `pass` leaves all three parametrizations green (all,
  ids, drift). Only `test_a_dryrun_refuses_an_api_that_does_not_answer` turns red (3
  failed). So the guard is pinned, but by the refuse test and not by this one. For `all`
  and `ids` without queryables, nothing else in a dryrun touches the API, so this test
  would stay green if the API probe were dropped there. This is "verification that reads its own
  output". Either assert on the stub API's request log, or drop "and the api" from the
  name and lean on the refuse test.

- **[fragile, minor: a test weaker than its name]** tests/test_register.py:974-978
  `test_all_dryrun_previews_probes_and_writes_nothing`. It was renamed to say "probes",
  but it asserts nothing about probing. Mutation in the copy: deleting
  `probe(target.transport)` from `_run` leaves it green. The probe is pinned elsewhere, by
  `test_a_dryrun_reaches_...` (`r.probes == 1`) and `test_a_dryrun_refuses_an_unreachable_host`.
  Add `r.probes == 1` here, or keep the old name.

- **[minor: release-note accuracy]** NEWS.md:9-13. "`--dryrun` now probes the API and the
  host ... A dryrun now exits 1 when either does not answer". This holds for `register`
  only. `load --dryrun` probes the host alone (`_send` → `probe`); it has no API to reach,
  so a dead API never fails it. The README paragraph has it right ("`register` asks the
  API ..., and both commands run `ssh <host> true`"); the NEWS entry merges the two.
  Suggested wording: "`register --dryrun` now probes the API and the host, and
  `load --dryrun` the host".

## Checked and correct (no finding)

- **Round-1 fix.** NEWS now says "proved nothing about ssh, and in `all` and `ids`
  nothing about the API either". That matches main: a drift dryrun read the API through
  `_registered`, `_collection_state` and `_queryables_drift`.
- **README: "`register` asks the API for one item of the collection".** `_api_probe`
  POSTs `/search` with `limit: 1` for the collection. It also GETs `/collections`, and
  `/queryables` when queryables are declared. An all or ids dryrun with queryables reads
  `/collections/<id>` and its queryables, and drift reads every body. So the sentence
  understates what is read, but nothing in it is false.
- **README: "`all` and `ids` before fetching any item body, `drift` after comparing every
  body with the API but before the asset audit, `load` after its checks".** This matches
  `_run` (dryrun returns at about line 580 and line 669) and `cmd_load`. `load` runs the
  audit for items, or the id check for a collection, then `ndjson_write` with its
  duplicate and `expect_collection` refusals, then `_send` → `probe`, then the dryrun
  return.
- **README: "it upserts the body the database already holds".** True to within what
  `body_digest` ignores (`links`) and the pgstac round trip that `_canonical` absorbs.
  Every `register` run loads the same published file, and the remote script uses
  `--method upsert` (register.py:251, :321). It is not destructive.
- **"None of them runs the script on the host".** True. `_send` returns before the
  `bash -c` call, and all/ids/drift dryruns return before any `load`.
- **The `--help` strings.** These are accurate and contain no `%`, so argparse formatting
  is safe.
- **Real (non-dryrun) paths.** These are unchanged in order and in probe count. drift
  probed before the fetch on main too. `_send`'s probe moved and was not duplicated.
- **The all/ids dryrun f-string.** `q_missing` and `q_changed` are bound whenever
  `target.queryables` is truthy, because the `if writes:` block always runs for all and
  ids. There is no UnboundLocalError.
- **Offline guarantee.** The `SSH_CMDS` env var is set by the `env` fixture
  (tests/test_register.py:261), so the stub's `$SSH_CMDS.probes` never lands in the
  cwd. The autouse fixture in test_cli stubs `register.probe`, which is looked up as a
  module global by both `_run` and `_send`.
- **README markers.** The new paragraph is inside `use` (lines 117-170) and has no links.

/Users/airvine/Projects/repo/stacs/planning/active/review-round2.md
