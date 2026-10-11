# Task: register --dryrun skips the API and ssh probes; say so or probe (#5)

**If done:** a reader of the README knows `register --dryrun` proves nothing about the host or API, and reaches for `--mode drift` (no dryrun) against an in-sync API, or a probe flag, when that is what they want to test. **If never:** a dryrun keeps reading as a connectivity check, and someone signs off a config whose ssh or API never got touched.
Decision (plan gate, 2026-10-11): **probe in dryrun.** Both probes are read-only, so a dryrun becomes everything a real run does except the write. The cost is accepted: a dryrun now needs the host and the API reachable.

## Phase 1: Tests first (failing)
- [ ] `tests/test_register.py`: for each of all / ids / drift, a dryrun whose ssh probe fails (`SSH_PROBE_RC=255`) exits 1 with "cannot reach", and nothing is written (`r.writes == 0`)
- [ ] For each of all / ids / drift, a dryrun against a dead API (`127.0.0.1:9`) exits 1 with "does not answer", and nothing is written
- [ ] A passing dryrun reached the host: the ssh stub's command log holds the `true` probe, no `bash -c`, and the output says what it reached
- [ ] `load` / `load_queryables` with `dryrun=True` and a failing probe are refused, and nothing is sent
- [ ] Invert `test_all_dryrun_previews_and_touches_nothing`: it now probes and writes nothing
- [ ] Mutation check: remove each new probe call and watch its test fail

## Phase 2: Probe before every dryrun return
- [ ] `register._run`: move the "before the expensive stage" block (`_api_probe`, `probe`, queryables drift) above the all/ids dryrun branch, with the condition changed to `if writes:`. Drift then probes before its fetch too. The local checks (ids file, link set) still run first
- [ ] The dryrun branches say what was reached (the API and the host), so a pass is affirmative rather than silent
- [ ] `register._send`: call `probe(t)` before the `[dryrun] nothing sent` return (this covers `stacs load` and `load_queryables`)

## Phase 3: Existing tests that relied on an offline dryrun
- [ ] `tests/test_register.py`: give the dryrun tests that ran against the dead default API (asset-policy startup, the ids dryruns, `test_all_dryrun_names_the_queryables`) the `api` fixture
- [ ] `tests/test_cli.py`: the `load --dryrun` tests run with no ssh stub. Stub `stacs.register.probe` with a recorder (no real ssh from the suite) and assert it was called

## Phase 4: Docs
- [ ] README "Use" (inside the markers): one paragraph. `--dryrun` makes every read a real run makes before writing (the published set, the API, ssh to the host) and stops before the first write. It never runs the remote script, so the env file, pypgstac and the database check are first exercised by a real load. Upserting the already-published `collection.json` with `stacs load collection` is the smallest real load
- [ ] `cli.py`: `help=` on both `--dryrun` flags, saying the same in one line
- [ ] `NEWS.md` `## Unreleased` entry (the version bump and tag happen at release, by hand)

## Validation

- [ ] Tests pass (`uv run pytest`), and `mkdocs build --strict` passes (README markers)
- [ ] `/code-check` clean (each commit, or once over the branch with `/code-check branch`)
- [ ] PWF checkboxes match landed work
- [ ] `/planning-archive` on completion
