# Code-check round 3 — issue #5 (register/load --dryrun probes)

Reviewed the diff from `main...HEAD` (f5b2dd9) with the full current `register.py`, `cli.py`,
the tests, README, NEWS and planning files. Mutations were run in a scratch copy
(`stacs.__file__` confirmed in the copy; baseline 498 passed).

## The mechanism

All three earlier findings and the two below share one premise: **a dryrun was described
as "the run minus the write", one statement for every command and mode**, rather than
derived per command and per mode from the code path. That premise is literally written
twice in the diff ("it is everything but the write"). It produces exactly the
over-generalisations already found: the API probe credited to `load` (round 2), a skip
credited to drift (round 1), and a test named for a property that one log line stood in
for (round 2). The plan scoped it correctly (task_plan Phase 4: "still reaches the API
(`register`) and the host (both)"), and plan-review B1 rejected "everything but the
write". Two places still carry the collapsed form.

## Findings

- **[severity: fragile]** README.md:135-137 — "`--dryrun` writes nothing, and it still
  reaches the API and the host." The paragraph sits directly under `load`'s description
  and the next sentence says "both commands", so "it" includes `load`. `load --dryrun`
  never contacts the API: `_send` runs only `probe(t)` (register.py:409). The same
  sentence continues "so a dryrun that passes means they answered", which for `load`
  again includes the API. This is round 2's defect (fixed in NEWS) still present in the
  README, which is the page the site publishes. Suggested: "`--dryrun` writes nothing,
  and it still reaches the host, and for `register` the API too."

- **[severity: fragile]** register.py:408 and tests/test_register.py:981 — the comments
  "a dryrun runs it too: it is everything but the write" and "A dryrun is everything but
  the write, so a pass says the host and the API answered". Both false against the code
  and against the README they sit beside: a dryrun skips the item fetch (all/ids), the
  asset audit (drift), and the remote script, whose env-file source and
  `current_database()` check are not writes (`_say_reached` itself says "the write, and
  the database check before it, did not run"). The test comment also credits every
  dryrun with the API, but the tests under it are register-only, so that half is right
  there and wrong as a general statement. These are comments, not behaviour, but they
  are the premise that produced rounds 1-3, and the next reader will reason from them.

## Checked and true (every claim / name the mechanism reaches)

| Place | Claim | Verdict |
|---|---|---|
| NEWS "Unreleased" b1 | `--dryrun` probes the host, `register --dryrun` the API as well | true (`_send` 409; `_run` 571-573) |
| NEWS | register (all modes) and load used to skip them; all/ids proved nothing about the API | true (old gate `writes and not dryrun`; drift read the API via `_registered`/`_collection_state`) |
| NEWS | exits 1 when one does not answer, incl. CI without key/known_hosts | true (BatchMode=yes; RegisterError -> cli 1 at cli.py:134/228) |
| NEWS | says what it reached | true for register (`_say_reached`) and load (`[dryrun] reached <host>`) |
| NEWS | stops before fetch (all, ids) / audit (drift), never runs the script | true |
| NEWS b2 | all/ids dryrun names only queryables it would load | true; mutation M4 below |
| README | `register` asks the API for one item; both commands run `ssh <host> true` | true (understatement accepted) |
| README | stops: all/ids before any item body, drift after comparing before the audit, load after its checks | true |
| README | none runs the script, so env file / pypgstac / db check first exercised by a real load | true |
| README | `load collection` of the published collection.json after verify `same` is the smallest real load | true enough: register itself loads that file; `body_digest` ignores only `links` |
| cli.py register `--dryrun` help | probe API and host, stop before fetch / audit, writes nothing | true |
| cli.py load `--dryrun` help | check files, probe the host, sends nothing | true |
| `run` docstring | dryrun probes API and host, stops before fetch / audit | true |
| `_run` comment 567-570 | probes before the expensive stage in every writing mode, dryrun included | true |
| `_say_reached` text | reached API and host; write and db check did not run | true |
| test_register module docstring | probe counted in `$SSH_CMDS.probes` | true |
| `/collections` comment, test line 998 | read by `_api_probe` alone in a dryrun | true for this test only because `_in_sync` registers the collection; without it `_get_or_absent`'s 404 path also GETs `/collections` |
| test_cli `probes` fixture docstring | load --dryrun probes; recorded, not run | true; no test_cli load runs without --dryrun except one with `load` stubbed |

Test names against assertions, by mutation in the copy:

| Mutation | Tests that went red |
|---|---|
| M1 drop `_api_probe` from `_run` | `test_a_dryrun_reaches_the_host_and_the_api_and_says_so[all,ids,drift]`, `test_a_dryrun_refuses_an_api_that_does_not_answer[all,ids,drift]` + 4 non-dryrun (10) |
| M2 drop `probe` from `_run` | `test_all_dryrun_previews_probes_and_writes_nothing`, `..._reaches_the_host_and_the_api...[x3]`, `..._refuses_an_unreachable_host[x3]`, 1 non-dryrun (8) |
| M3 `_send` probe back after the dryrun return | `test_a_load_dryrun_refuses_an_unreachable_host[items,queryables]`, `test_queryables_dryrun_sends_nothing`, both test_cli load-dryrun tests (5) |
| M4 all/ids dryrun names every declared queryable | `test_all_dryrun_does_not_name_queryables_served_as_declared` (1) |

Minor, not a defect: `test_all_dryrun_previews_probes_and_writes_nothing` stays green under
M1; it pins the ssh probe only. The API probe is pinned by the parametrized test, so there
is no coverage gap, only a plural name. And findings.md's mutation counts (3 for no
`_api_probe`, 6 for no ssh probe) are lower than this tree's (10, 8); the record is of an
earlier tree, not wrong at the time.

No code defect found: the probe ordering, `q_missing`/`q_changed` scoping (short-circuit
when no queryables), the ids-file check ahead of the probes, and the single probe per
`_send` all hold.
