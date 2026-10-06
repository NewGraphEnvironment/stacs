# Review: Phase 3 staged diff (validate.py, conftest guard, deployment-default check), round 1

Reviewed: `git diff --cached` at fbe1496 + staged. Every claim below was reproduced in a temp copy
(scratchpad `r1/`, src + tests copied). Baseline suite there: 149 passed, 1 deselected.

## Findings

- **[bug] src/stacs/validate.py:80-81, 98-105 — `assets` that is not a dict satisfies `require_asset`.**
  `assets = doc.get("assets") or {}` followed by `require_asset not in assets` does substring
  matching on a str and membership on a list. Reproduced: an item with `"assets": "data"` and one
  with `"assets": ["data"]` both return `ok=True` for `require_asset="data"`. Neither body is valid
  STAC, and both go on to upsert. The origin (stac_dem_bc `audit_items`) has the same hole, so this
  is inherited rather than introduced. Still, this is the last gate before pgstac, and the check
  passes on a body it never understood. Fix: when `assets` is present and not a dict, record the
  item as unreadable (or as missing the asset). A missing or empty `assets` already reads as missing.

- **[bug] src/stacs/validate.py:78-79, 97 — an empty or None `collection_id` passes items that have no `collection`.**
  `doc.get("collection") != collection_id` is `None != None`, which is False. Reproduced:
  `audit_items([item_without_collection], None).ok is True`. The same happens with `""` against
  `"collection": ""`. A caller that reads the id from an unset variable gets a pass, on exactly the
  property this gate exists to check. `verify.search_body` already refuses an empty `collection_id`
  (verify.py:170, "collection_id is required"), so audit is the one entry point that does not.
  Fix: `if not collection_id: raise ValueError(...)` at the top of `audit_items`.

- **[fragile] src/stacs/validate.py:79 — `require_asset=""` silently turns the require check off. In the origin it failed closed.**
  `Audit(collection_id, require_asset or None, ...)` maps `""` to "no requirement". Reproduced: an
  item with `assets: {}` gives `audit_items([p], "new", require_asset="").ok is True` (rules: "no
  asset checks"). In the origin, `audit_items(..., args.require_asset="")` tested `"" not in assets`
  and so flagged every item. That was a failure, if for the wrong reason, and it happened in
  exactly the case `--require-asset "$UNSET_VAR"` produces. The port is also inconsistent with
  itself: `" "` (whitespace) is still treated as a literal key and fails every item, while `""`
  passes everything. The `rules` string is honest, but `ok` carries no signal, and the gate's
  consumer reads `ok`. Fix: raise on a str `require_asset` whose `.strip()` is empty, or at minimum
  document that `""` means "none" and make `" "` behave the same way.

- **[fragile] tests/test_no_deployment_defaults.py:56-58 — the relaxed predicate no longer catches several deployment defaults the old one caught.**
  The new test is `isinstance(default, (str, bytes, int, float))`. Reproduced by adding a scratch
  module with `workdir=Path("/srv/fake")`, `env_file=Path("~/.fake.env")`,
  `hosts=("fake.example.invalid",)` and a dataclass `api_url: str = field(default_factory=lambda:
  "https://...")`. The new check passes all four. The HEAD version of the test flags them.
  `workdir` and `env_file` are named in `DEPLOYMENT_PARAM`, and `Path` is their natural type. The
  textual check catches only the listed known strings. The exemption actually needed is narrower:
  a dataclass factory shows up in `__init__` as the sentinel `dataclasses._HAS_DEFAULT_FACTORY`
  (repr `<factory>`). Keep the old `not in (p.empty, None)` test, exempt `bool`, and for `<factory>`
  resolve the field's `default_factory` through `dataclasses.fields(cls)`, then flag any non-empty
  result.

- **[fragile] tests/conftest.py:28-30 — the network guard has three bypasses, and the docstring ("Every test runs with the network off") overstates it.**
  Each was reproduced against `example.invalid`, so no real traffic was sent:
  1. **A loopback proxy.** With `HTTPS_PROXY=http://127.0.0.1:9`, `requests.get("https://example.invalid/")`
     never resolves the target. It connects to the proxy, which the guard allows as loopback (it
     reached `127.0.0.1:9`, connection refused, and never raised `network disabled`). With a live
     local proxy set, as sandboxed agent shells commonly have, requests and urllib calls reach the
     internet. `test_harness` would go red for the `requests` case in that environment, but any
     stacs test whose fake URL goes through `requests`/`urllib` would get a proxy error rather than
     the guard. Fix: in the fixture, `monkeypatch.delenv` `HTTP(S)_PROXY`/`ALL_PROXY` in both
     upper and lower case, and `setenv("NO_PROXY", "*")`. On macOS, urllib also reads system proxy
     settings when the environment is empty, so `NO_PROXY` is needed as well as the deletes.
  2. **Higher-scoped fixtures run before it.** A `scope="session"` fixture calling
     `socket.getaddrinfo("example.invalid", 80)` reached the real resolver (`gaierror`, not
     `NetworkDisabled`), because session and module fixtures are set up before function-scoped
     autouse ones. Import-time code is also unguarded. None exists today; the gap is latent.
  3. **C-level resolution.** `socket.socket().connect(("example.invalid", 80))` resolves inside C,
     not through the Python `getaddrinfo`, and so do libpq and subprocesses (`ssh`, `pypgstac`).
     The planned transport (task_plan Phase "Transport"/"Load path") runs `ssh`, and none of that
     is covered. Pure-Python HTTP stacks are covered as claimed.

- **[fragile, low] src/stacs/validate.py:136-140 — `validate_items` can hang on an extension schema host that accepts the connection and then stalls.**
  pystac 1.15.2 fetches schemas with `urlopen(req)` or `urllib3.PoolManager().request(...)` with
  no timeout (`pystac/stac_io.py:299-326, 463`). An unreachable host fails, as the test shows. A
  host that stalls blocks forever, and the docstring's "a schema that cannot be fetched is a
  failure" never comes into play. This is an upstream behaviour, and the function is opt-in (not
  run by `register`). Noted so it is not read as bounded.

## Checked and not a problem

- Trailing whitespace or `\r` in a path, or a path that is a directory: `open` raises
  `OSError`, the path goes to `unreadable`, and `ok` is False. Blank-only input gives "no item
  JSONs to check". Fails closed.
- A BOM or non-UTF-8 body raises `ValueError` (`JSONDecodeError`/`UnicodeDecodeError`) and is
  recorded as unreadable.
- `expect_ids`: items missing `id` put `None` into `got`, so the comparison fails. Repeated ids are
  caught. Unhashable ids raise a `TypeError`, which fails rather than passes. A str `expect_ids`
  becomes a set of characters, which fails closed.
- `forbid_assets` given as a dict (a rename map) uses its keys. `","` and `None` give no keys, and
  `rules` reports it honestly, matching the origin.
- Compared with the origin CLI: zero items fails, the forbid parse drops empty keys, rules are
  printed as applied, `--expect` matches, and `item_paths_in_dir` reproduces the
  `collection.json` exclusion. All equivalent.
- `validate_items` validates the original body, not a lossy round-trip. pystac's
  `preserve_dict` meant `datetime` without an offset, missing `links` and `stac_version: 9.9.9`
  each failed through `validate_items` exactly as through `validate_dict(doc)`.
