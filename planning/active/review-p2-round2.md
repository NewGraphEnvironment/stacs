# Review p2, round 2 -- the child-process guard probe

Scope: staged diff, focused on `tests/test_harness.py::test_the_guard_loads_for_a_run_of_src_alone`
and the root `conftest.py`. Run against an export of the index (`checkout-index`), never the
working tree. Staged suite with `--cov=stacs`: 362 passed.

## Findings

- **[fragile]** tests/test_harness.py:100-113 -- the child probe pins only the `src/` half of
  "the guard loads however pytest is invoked". The symmetric mutation, guard moved to
  `src/conftest.py` with no root conftest, keeps CI fully green and leaves `pytest tests/...`
  unguarded:

  | mutation (in an exported copy) | bare `pytest` (what CI runs) | `pytest tests/` |
  |---|---|---|
  | none | 362 passed | (guarded) |
  | root `conftest.py` moved to `src/conftest.py` | **362 passed** | 10 failed, 86 s (real lookups and connects went out) |

  Under bare `pytest` both testpaths are collected, so `src/conftest.py` registers during
  collection, its `pytest_configure` (a historic hook) patches the sockets before any test
  runs, and every in-process guard test plus the child probe (which collects `src/` only)
  passes. Nothing in CI runs `tests/` alone, so the in-process tests that would go red there
  never do. That is the same failure as round 1's finding, mirrored: a guard whose location
  covers one invocation and not the other, reported green. Less likely than the original
  regression (moving it back into `tests/`), but cheap to close: parametrize the child run
  over both a `src` path and a `tests` path (e.g. `src/stacs/verify.py` and
  `tests/test_harness.py`); `--collect-only` keeps both fast.

## Questions asked, and what they came to

- **Guard absent, can the probe pass?** No. The gaierror is re-raised from
  `pytest_collection_finish`. Measured: a raising hook in that position gives INTERNALERROR,
  **rc=3**, so `returncode == 0` fails first. A resolver that answers `.invalid` (NXDOMAIN
  hijacking) reaches the `RuntimeError`, also rc=3. A hang hits `timeout=120`, so
  `TimeoutExpired` (red). The traceback may echo the `print("STACS_GUARD_ACTIVE")` source line,
  but only when rc is non-zero, and that assertion comes first.
- **Output captured, so the print is lost?** No. A plugin printing from
  `pytest_collection_finish` reaches the child's stdout under default capture and under
  `PYTEST_ADDOPTS=--capture=sys`. The child's pipe is flushed on normal exit.
- **Cached plugin?** No. `stacs_guard_probe.py` lives in a fresh `tmp_path` and runs in a fresh
  interpreter, with `-p no:cacheprovider`.
- **Partial guard (getaddrinfo but not connect)?** Not caught by the probe (accepted in the
  brief). The in-process tests pin the other entry points under bare `pytest`.
- **Late guard (installed in a fixture or runtest hook)?** The probe goes red, which is a false
  red and the safe direction.
- **Spurious CI failure?** None found. `uv run pytest` makes `sys.executable` the venv python
  with pytest importable. `cwd=REPO` comes from `__file__`. pytest-cov is 7.1.0 (locked), which
  has no subprocess `.pth`, so the child neither starts coverage nor writes `.coverage.*`
  files. The inherited `PYTEST_CURRENT_TEST`, `NO_PROXY=*` and removed proxy variables are
  harmless. CI sets no `PYTEST_ADDOPTS` (staged `.github/workflows/test.yml`).
- **Leak?** In the unmutated tree, none. With the guard absent, there is a single lookup of
  `example.invalid` (accepted).

Doctest examples in the staged `src/` additions use only `example.invalid` hosts. No
deployment defaults.
