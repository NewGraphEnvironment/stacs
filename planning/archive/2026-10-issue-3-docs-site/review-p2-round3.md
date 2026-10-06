# Review — phase 2, round 3 (staged diff)

## The mechanism behind rounds 1 and 2

Each check looked at the property from inside the pytest session the check was running
in, and treated that one session as if it stood for every invocation. Whether the guard
is active, and whether the examples are collected, depends on how pytest is invoked:
the args, cwd compared with rootdir, where the ini file is, confcutdir, `-c`,
`--noconftest`, `collect_ignore`/`--ignore`. Round 1 read the registration state of its
own session. Round 2 sampled one invocation shape. In both, the observing session was
assumed to be representative of all of them.

## Findings

- **[fragile]** tests/test_harness.py:77-81 (`test_docstring_examples_are_collected`): this
  is the same mechanism, in the second half of what the harness says it pins. It reads
  `pytestconfig.getini("testpaths")` and `option.doctestmodules` from the session it runs
  in. Those settings stand in for the property ("a bare `pytest` collects the examples in
  src/"). They are not that property. I measured this on an export of the index:
  - Adding `collect_ignore = ["src/stacs"]` or `collect_ignore_glob = ["src/stacs/*.py"]`
    to the root conftest makes a bare `pytest` at the repo root (the shape CI runs) collect
    **0** `src/` items, down from 14. `tests/test_harness.py` still passes 13/13. A
    `--ignore=src/stacs` in addopts or a `norecursedirs` entry would have the same effect.
  - `cd tests && pytest` collects 0 doctests, because testpaths applies only when cwd is
    rootdir, and the test still passes. `pytest tests/` gives the same result.

  The claim in CLAUDE.md ("`tests/test_harness.py` pins both") therefore holds for the
  guard and not for collection. The fix is cheap, because the `bare` parametrization of
  `test_the_guard_loads_however_pytest_is_invoked` already runs `--collect-only -q` with
  no args and cwd=REPO, which is CI's shape. In that case, assert that the child's stdout
  lists doctest ids, such as `src/stacs/verify.py::stacs.verify.body_digest` (or one id
  per module). That measures collection in the invocation that matters, rather than the
  config of whichever session runs the test.

- **[fragile, prose only]** pyproject.toml:35-36 says "so it covers them however pytest is
  invoked". CLAUDE.md:53 says the root conftest refuses lookups "for the whole session".
  Neither is true for `--confcutdir=<subdir>`, `-c <ini outside the root>` or
  `--noconftest`. I measured `--confcutdir=tests tests/<probe>` and
  `-c tests/none.ini tests/<probe>`: both made a **real** resolver call
  (`gaierror(8, 'nodename nor servname…')`, not `NetworkDisabled`). These are explicit
  opt-outs, and the same was true when the guard lived in `tests/`, so no code change
  is needed. The sentence should say "for any invocation that reads the root
  pyproject.toml" (or name the opt-outs). As written it is the prose form of the
  assumption that rounds 1 and 2 removed from the code.

## Checked, not findings

- **Doctest examples and session state.** Each module run alone (`pytest
  src/stacs/{verify,catalogue,validate,register}.py`): 5/3/4/2 pass. Under `--noconftest
  src`: 14 pass. Bare: 364 pass. On Python 3.11 (CI floor, fresh `uv sync --locked` venv,
  with `--cov=stacs`): 364 pass. No example depends on test order, an earlier test's pystac
  schema cache, cwd (all paths come from `tempfile`), or NO_PROXY. `validate_items` passing
  alone under the guard shows that the 1.1.0 schemas really are local. The examples do
  depend on the ini's ELLIPSIS and NORMALIZE_WHITESPACE (the `search_body` dict wraps
  across lines, and the RegisterError and `search_body` messages use `...`), so
  `python -m doctest` would fail them. That failure is loud, and only pytest runs them.
- **Completeness of the guard enumeration.**
  - Parents of the repo root are never loaded: confcutdir defaults to the ini file's
    directory, so a guard there turns all three parametrizations red.
  - Running from a subdirectory (`cd tests && pytest test_harness.py`): the root conftest
    still loads, and the in-process lookup and connect tests pass.
  - `--rootdir=tests`: still guarded, because confcutdir follows the ini, not the rootdir.
  - `--pyargs stacs.verify` with the editable install: guarded.
  - Residual risks, neither a defect now:
    - (a) The enumeration covered single locations. A copy in both `tests/` and `src/`
      passes all three probes, but it also guards every path pytest can collect in the
      repo (there are no root-level test files), so that is not a hole.
    - (b) Every probe runs with cwd=REPO. That is sound only while the root
      `pyproject.toml` is the only ini. A `pytest.ini` or `tox.ini` added under `tests/`
      would make `cd tests && pytest` set confcutdir=tests and skip the root conftest,
      and no probe would notice.
- `python -m pytest` in the child puts REPO on sys.path, which `uv run pytest` does not.
  That does not affect conftest discovery, which is path-based.
- Tracked `.py` files outside `src/` and `tests/` (`planning/archive/.../evidence/*.py`)
  have `__main__` guards. They are collected only by an explicit `pytest .`.

/Users/airvine/Projects/repo/stacs/planning/active/review-p2-round3.md
