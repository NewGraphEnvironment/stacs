# Review: coverage-gap tests, round 3 (mechanism: covers the line, cannot fail when it is wrong)

Scope: the staged diff (`git diff --cached`) in /Users/airvine/Projects/repo/stacs. The
Ctrl-C test was skipped, as asked.

Method: the staged tree was copied with `git checkout-index` to `scratchpad/r3`, where the
full suite gives 345 passed and 1 deselected. 13 new mutations were run, each in a fresh
copy (`scratchpad/mut3/run.py`). An `ssh` stub on PATH exits 255, so a mutation that drops
`--dryrun` cannot reach a real host. Round 1's 14 mutations were re-run against the current
staged tree (`scratchpad/mut3/rerun1.py`) and all 14 are still killed.

## Findings

- **[test gap]** tests/test_catalogue.py, `test_fetch_bodies_over_http`, the line
  `assert failed == [gone], "a 404 is a failed fetch"`. **The test passes with
  `resp.raise_for_status()` removed from `_read_url` (src/stacs/catalogue.py:106).**
  Measured: SURVIVED, 1 passed.

  Why it survives: `SimpleHTTPRequestHandler.send_error` answers 404 with an HTML body.
  `fetch_bodies` already refuses any body that is not a JSON object
  (catalogue.py:142), so the URL is reported as failed whether the status is checked or
  not. The test covers line 106 but cannot fail when that line is wrong.

  What goes unpinned: an error status whose body is a JSON object, such as a STAC API or
  a gateway answering `{"code": ...}`. Without `raise_for_status`, that body would be
  written as the item's fetched body. Today, `published_digests`' id check would then
  refuse it. So this is a gap in the test, not live data loss.

  Fix, proven: give the fixture's handler an `/err.json` route that answers **500 with a
  JSON-object body**, and assert `failed == [gone, err]`. The variant passes on the staged
  code and fails with `raise_for_status` removed:
  `assert ['…/gone.json'] == ['…/gone.json', '…/err.json']`.

  ```python
  class Quiet(SimpleHTTPRequestHandler):
      def log_message(self, *a):
          pass

      def do_GET(self):
          if self.path == "/err.json":         # an error status with a JSON-object body
              body = json.dumps({"id": "err", "code": "ServerError"}).encode()
              self.send_response(500)
              self.send_header("Content-Length", str(len(body)))
              self.end_headers()
              self.wfile.write(body)
              return
          super().do_GET()
  ...
  gone, err = f"{base}/gone.json", f"{base}/err.json"
  failed = c.fetch_bodies([f"{base}/a.json", gone, err], out, workers=2, backoff=0)
  assert failed == [gone, err], "an error status is a failed fetch, JSON body or not"
  ```

  The working copy is `scratchpad/mut3/v/tests/test_catalogue.py`.

No other new test has this shape.

## Enumeration (every added `def test_`, Ctrl-C test excluded)

| test | target | can fail when target wrong? |
|---|---|---|
| test_catalogue::test_fetch_bodies_over_http | `_read_url` requests path, `raise_for_status` | **No** for the status check (the JSON-object check also rejects the HTML 404). Yes for the success path |
| test_cli::test_a_config_table_that_is_not_a_table_is_refused | read_config `isinstance(values, dict)` | Yes (M12) |
| test_cli::test_host_and_db_flags_override_the_config | build_transport `--host` / `--db` | Yes, both: `--host` ignored is KILLED; `--db` ignored is KILLED (M11) |
| test_cli::test_load_collection_dryrun_succeeds_for_the_declared_collection | cmd_load collection success path, `dryrun=` passed through, `return 0` | Yes: dryrun dropped is KILLED; return 1 is KILLED |
| test_cli::test_load_collection_refuses_an_unreadable_file[None,"{trunc","[]"] | cmd_load read `except (OSError, ValueError, AttributeError)` | Yes, per param: dropping OSError, ValueError or AttributeError each fails exactly one case. `main()` would otherwise turn OSError/ValueError into rc 2 without "cannot read" |
| test_cli::test_a_refused_load_is_exit_1_with_its_reason | cmd_load `except (RegisterError, …)` | Yes: RegisterError dropped is KILLED. It is not a subclass of what `main` catches |
| test_cli::test_validate_passes_valid_items | cmd_validate rc and summary; validate_items no false positive | Yes: always-1 is KILLED; validate_items flagging everything is KILLED |
| test_cli::test_validate_names_each_invalid_item | cmd_validate INVALID loop and `1 if bad` | Yes: loop removed is KILLED; always-0 is KILLED |
| test_cli::test_the_module_runs_as_a_script | `if __name__ == "__main__"` | Yes: guard removed is KILLED. The subprocess ran the mutated copy through PYTHONPATH |
| test_register::test_a_search_that_keeps_failing_is_a_refusal_not_a_traceback | `_registered` raising RegisterError | Yes (M15) |
| test_register::test_a_collection_read_that_keeps_failing_is_a_refusal | collection_state raising after retries | Yes (M4) |
| test_register::test_an_unexpected_collection_state_is_refused | the state allow-list | Yes (M3) |
| test_register::test_a_collection_json_that_is_not_an_object_is_refused | the not-dict check on collection.json | Yes (M5) |
| test_register::test_target_check_refuses_empty_catalogue_settings[3] | Target.check lines 119–122 | Yes: dropping `.strip()` fails the `""` and `"  "` cases. The `None` case is on the `isinstance` arm, and removing that arm raises AttributeError, not RegisterError |
| test_register::test_run_refuses_a_bad_mode_when_called_directly[2] | the mode check and the ids-file check | Yes (M6, M7) |
| test_register::test_remote_script_refuses_an_unknown_kind | the kind check | Yes (M8) |
| test_register::test_the_hosts_own_output_is_relayed_and_the_mark_is_not | LOADED_MARK filter / relay | Yes (M9, M10) |
| test_validate::test_blank_paths_are_skipped_not_read | audit_items blank skip | Yes (M13) |
| test_validate::test_validate_reports_json_that_is_not_an_object[3] | validate_items not-dict check | Yes (M14) |

## Removed cli.py branch (`if forbid_flag is not None and not added: raise ConfigError("--forbid-asset is empty")`)

**It is unreachable from every caller.** There are 3 callers, all in cli.py.

- Two (lines 135 and 225) pass `args.forbid_asset`. argparse `action="append"` gives that
  as `None` or a non-empty list of `str`. An empty list is already turned into `None` at
  line 77.
- The third (line 191) passes `None`.
- `parse_asset_keys(str)` splits into at least one part and raises on any empty one, so
  each string yields one key or more, or raises. So `added` is non-empty whenever
  `forbid_flag` is not None.
- The old branch could only fire on a direct call with a non-str, non-list value, such as
  `forbid_flag=()` or `[[]]`. No test calls `merge_asset_rules` directly, and it is not
  exported.

## Aside (not a defect)

`cli.py:342` (`sys.exit(main())`) still reports as missed under `--cov`: the run gives
cli.py 99%, missing 342, and TOTAL 99%. `test_the_module_runs_as_a_script` runs it in a
subprocess, and pytest-cov 7 does not measure subprocesses. The test still pins the
behaviour, but it adds no coverage.
