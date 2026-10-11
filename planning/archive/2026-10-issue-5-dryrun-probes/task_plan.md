# Task: register --dryrun skips the API and ssh probes; say so or probe (#5)

**If done:** a reader of the README knows `register --dryrun` proves nothing about the host or API, and reaches for `--mode drift` (no dryrun) against an in-sync API, or a probe flag, when that is what they want to test. **If never:** a dryrun keeps reading as a connectivity check, and someone signs off a config whose ssh or API never got touched.

Decision (plan gate, 2026-10-11): **probe in dryrun.** Both probes are read-only. A dryrun that passes now means the API answered and ssh to the host authenticated; it still stops before the fetch (all/ids) or the audit (drift), and never runs the remote script, and the README says so (review B1). The cost is accepted: a dryrun now needs the host and the API reachable.

Acceptance (revised from the issue's "If done", which described the docs-only option): a reader of the README knows what a passing dryrun proved and what it did not, and which command exercises the rest.

## Phase 1: Tests first (failing)
- [x] `tests/test_register.py`: for each of all / ids / drift, a dryrun whose ssh probe fails (`SSH_PROBE_RC=255`) exits 1 with "cannot reach", and nothing is written (`r.writes == 0`)
- [x] For each of all / ids / drift, a dryrun against a dead API (`127.0.0.1:9`) exits 1 with "does not answer", and nothing is written
- [x] A passing dryrun reached the host: the ssh stub's command log holds the `true` probe, no `bash -c`, and the output says what it reached
- [x] `load` / `load_queryables` with `dryrun=True` and a failing probe are refused, and nothing is sent
- [x] Invert `test_all_dryrun_previews_and_touches_nothing`: it now probes and writes nothing
- [x] Mutation check: remove each new probe call and watch its test fail

## Phase 2: Probe before every dryrun return
- [x] `register._run`: move the "before the expensive stage" block (`_api_probe`, `probe`, queryables drift) above the all/ids dryrun branch, with the condition changed to `if writes:`. Drift then probes before its fetch too. The local checks (ids file, link set) still run first
- [x] The dryrun branches say what was reached (the API and the host), so a pass is affirmative rather than silent
- [x] `register._send`: call `probe(t)` before the `[dryrun] nothing sent` return (this covers `stacs load` and `load_queryables`); moved, not duplicated, so a real load probes once
- [x] The all/ids dryrun names the queryables it would load (`q_missing + q_changed`), not every declared one, now that the diff runs (review G4); `_send`'s dryrun says which host it reached (G5); `run`'s docstring says what a dryrun does (S3)

## Phase 3: Existing tests that relied on an offline dryrun
- [x] `tests/test_register.py`: give the dryrun tests that ran against the dead default API (asset-policy startup, the ids dryruns, `test_all_dryrun_names_the_queryables`) the `api` fixture
- [x] `tests/test_cli.py`: the `load --dryrun` tests run with no ssh stub. Stub `stacs.register.probe` with a recorder (no real ssh from the suite) and assert it was called (autouse, so no future test runs real ssh)

## Phase 4: Docs
- [x] README "Use" (inside the markers): one paragraph. A dryrun writes nothing and still reaches the API (`register`) and the host (both). It stops before the fetch (all/ids), the audit (drift), or after `load`'s checks, and never runs the remote script, so the env file, pypgstac and the database check are first exercised by a real load. When `verify` reports the collection `same`, `stacs load collection` with a downloaded copy of the published `collection.json` is the smallest real load (review A1)
- [x] `cli.py`: `help=` on both `--dryrun` flags, saying the same in one line
- [x] `NEWS.md` `## Unreleased` entry, marked as a behaviour change (review S2; the version bump and tag happen at release, by hand)

## Validation

- [x] Tests pass (`uv run pytest`), and `mkdocs build --strict` passes (README markers)
- [x] `/code-check` clean (each commit, or once over the branch with `/code-check branch`)
- [x] PWF checkboxes match landed work
- [ ] `/planning-archive` on completion
