# Plan review (Plan agent, 2026-10-06) — written here by the parent; Plan agents cannot write

- **Blocker** harness test via in-process pytester cannot fail: the outer session has already
  patched `socket`. Assert the config directly (`getini("testpaths")`, `option.doctestmodules`).
- **Gap** `pytest src/stacs/verify.py` alone never loads `tests/conftest.py` → doctests unguarded,
  proxies not cleared. Move the guard to a root `conftest.py` (confcutdir = inifile dir).
  Confirmed by `--trace-config` before and after the move.
- **Assumption (checked safe)** `--doctest-modules` over tests/ and cli.py: no side effects;
  conftest special-cased; `cli.py` main is behind `__name__`.
- **Gap** strict mode: only `Examples:` sections are Google section titles; `describe_rules`
  has no docstring; set `paths: [src]` in the mkdocstrings handler.
- **Gap** README relative links: only `research/pgstac_round_trip.md` (README.md:31). The
  `<img>` is raw HTML: unchecked by MkDocs, would 404 silently — keep it outside the markers.
  Check a misspelt snippet section raises with `check_paths: true`.
- **Gap** gh-deploy: set git user.name/email (github-actions[bot]); `--force` needs no
  fetch-depth; `uv run --group docs`; `contents: write` on the deploy job only; ghp-import's
  commit message is "Deployed <sha> with MkDocs version: X", not the pkgdown text.
- **Acceptance** `::: stacs.nope` aborts even without `--strict`; prove strict with a link to a
  missing `.md` (a warning) instead.
- **Assumption** `validate_items` works offline for STAC 1.1.0 (pystac bundles 1.1.0 core;
  test_validate.py:228); show only the `[]` / empty-input cases, since jsonschema messages vary.
- **Assumption** examples use `example.org`, which resolves; the suite's convention is
  `example.invalid`, which fails closed in an unguarded run.
- **Assumption** Material is in maintenance mode; check whether its MkDocs-2 notice is a
  logged warning that breaks `--strict`.
- **Ordering** `uv lock` with the docs group; README markers + absolute link with the pages.
- **Scope** `logo_small.png` overlap (already fixed in Phase 1 round 1).
