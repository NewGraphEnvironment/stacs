# Review: coverage-gap tests, round 1

Scope: staged diff (`git diff --cached`) in /Users/airvine/Projects/repo/stacs.
Method: staged tree copied with `git checkout-index` to a scratch dir; full suite there
is 345 passed / 1 deselected. Each new test's target code was mutated in a fresh copy
(17 mutations, script `scratchpad/mut/run.py`).

## Findings

- **[fragile]** tests/test_catalogue.py, `test_an_interrupted_fetch_stops_rather_than_draining_the_queue`:
  **the test passes with the code it targets removed.** Two mutations of
  `src/stacs/catalogue.py` `fetch_bodies` both SURVIVE:
  - M1: drop the `try/except BaseException` entirely (`results = list(ex.map(one, urls))`)
    -> 1 passed
  - M2: `except BaseException: ex.shutdown(wait=True); raise` (waits, no cancel)
    -> 1 passed

  The cause is the one the new comment states: `Executor.map`'s result iterator cancels
  the queued futures in its own `finally`, so "the queue is not drained" holds whatever
  the except branch does. The test covers the except line (that is the coverage gain)
  but does not check it. The one thing that branch adds, per the new comment ("also stops
  waiting for the ones in flight"), goes untested. A variant that holds worker 2 in
  flight on an `Event` (`release.wait(5)` for `/1.json`) and asserts `fetch_bodies`
  raises within 2 s passes on the staged code and kills M2 (fails at 5.3 s). M1 still
  survives that variant, since without any shutdown nothing waits either. So the most a
  test can pin here is "does not wait for in-flight fetches". Variant:
  `scratchpad/mut/test_variant.py`.

- **[fragile]** tests/test_catalogue.py, same test: **it fails whenever the test process
  starts with SIGINT ignored.** `_thread.interrupt_main()` does nothing when SIGINT's
  handler is `SIG_IGN`/`SIG_DFL` (documented since 3.10), and Python keeps an inherited
  `SIG_IGN` at startup. A non-interactive shell gives exactly that to any background job
  (`cmd &`). Measured: `bash -c 'trap "" INT; pytest …'` -> FAILED (DID NOT RAISE,
  15.9 s), and `bash -c 'pytest … & wait'` -> FAILED the same way. GitHub Actions runs
  steps in the foreground, so CI is unaffected. A local run started in the background by
  a script, or by a harness that spawns that way, gets a false red. Fix: install the
  handler for the test's duration with
  `old = signal.signal(signal.SIGINT, signal.default_int_handler)` and restore it in a
  try/finally (or a fixture). `interrupt_main` then delivers however the process started.

## Checked and fine

- **Removed `--forbid-asset is empty` branch (cli.py): unreachable from every caller.**
  argparse `action="append"` yields a list of `str`. A list that is empty becomes `None`.
  `parse_asset_keys(str)` splits into at least one part and raises on any empty part, so
  every string returns one key or more, or raises. The other caller passes `None`. The
  only input that would reach the old branch is a non-list, non-str empty sequence such as
  `forbid_flag=()` (into `parse_asset_keys(())`, which gives `[]`), and nothing passes one.
  No existing test asserted the removed message. The `""`, `","` and `" , "` tests still
  refuse, through `forbid: empty asset key`.
- **Mutation kills.** These 14 mutations were each caught by the new test aimed at them:
  - the unexpected-state check
  - `collection_state` failure returned as "missing"
  - the not-a-dict `collection.json` check
  - the mode check and the ids-file check (separately)
  - the unknown load kind
  - relaying the LOADED_MARK line, and relaying nothing
  - ignoring `--db`
  - the table-type check in `read_config`
  - the blank-path skip in `audit_items`
  - the not-a-dict check in `validate_items`
  - swallowing a `/search` failure in `_registered`
  - dropping `AttributeError` from the `load collection` read

  The `"failed after"` substring is shared with catalogue's fetch message, but
  `r.err.startswith("ERROR:")` pins it.
- **Interrupt timing on loaded Linux.** `interrupt_main` is called from inside the call for
  `/0.json`, which is the future the main thread is blocked on. So the KeyboardInterrupt
  always lands inside `fetch_bodies` (the main thread wakes when future 0 completes) and
  cannot fire after the test or leak into another test. `len(calls) < 20` is an upper
  bound that load only helps: worker 2 can make at most about 0.22 s / 0.02 s calls.
  8 repeated runs all passed. One leftover: the in-flight worker's "fetch failed" line is
  printed after the test's capture closes, into whatever runs next. It is harmless here,
  because nothing after it asserts on the absence of that text.
- **HTTP fixture.** `ThreadingHTTPServer` uses daemon threads, port 0, loopback (allowed by
  the conftest guard, `NO_PROXY=*`), and `shutdown()` + `server_close()` on teardown. With
  HTTP/1.0 handlers, no connection outlives a request.
- **`python -m stacs.cli --version` subprocess.** It runs whatever `stacs` the interpreter
  imports. Under `uv run` that is the editable install of the source, and under the review
  command it was the copy via the inherited `PYTHONPATH`. `--version` does no I/O, so the
  socket guard (which does not reach subprocesses) is not needed. There is no `timeout=`,
  which is acceptable for a call that does no I/O.
- **`no_retry_sleep`.** `monkeypatch.setattr(verify.time, "sleep", ...)` patches the
  process-wide `time.sleep`, not just verify's, but only for that test, and nothing in it
  polls. Harmless.
- **CI / lock.** `uv lock --check --offline` on the staged `pyproject.toml` + `uv.lock`
  returns rc 0 (48 packages). The lock has coverage 7.16.2 cp311/cp312
  manylinux x86_64 wheels and pytest-cov 7.1.0, and `requires-dev` matches
  `pytest-cov>=5`. `uv sync --locked` will not break.

## Aside (not a defect in the diff)

`.coverage` is untracked and not in `.gitignore`. Any `--cov` run now leaves it in the
tree, where a `git add -A` would commit it.
