# Progress — Documentation site: MkDocs on GitHub Pages, with a black-and-white hexsticker (#3)

## Session 2026-10-06

- Plan-mode exploration — phases approved by user ("go all phases")
- Created branch `3-documentation-site-mkdocs-on-github-page` off main
- Scaffolded PWF baseline from issue #3 with approved phases
- Next: start Phase 1
- Phase 1: hexsticker rendered (`data-raw/make_hexsticker.R` -> `docs/assets/logo{,_small}.png`).
  /code-check 3 rounds: r1 small-sticker text overlapped the icon (text not scaled with dpi;
  fixed); r2 clean; r3 named the cause, showtext's session-global dpi, unpinned (pinned to 96,
  bytes unchanged; a dpi-300 session now renders identically, removing the pin does not).
  Ended by enumeration of the render's six inputs. Plan review landed (`review-plan.md`).
- Phase 2: 14 docstring examples across verify/catalogue/validate/register, collected with
  the tests; guard moved to a root `conftest.py`. /code-check 3 rounds, each finding a
  defect inside the previous fix, one mechanism: a check reading its own session as if it
  stood for every invocation (r1 guard registered ≠ active; r2 src-only probe missed a guard
  in src/; r3 collection pinned by config, not by what is collected). Ended by enumeration:
  conftest locations {root, tests/, src/, src/stacs/, stub root} × invocations {src, tests,
  bare}, and collection deciders {testpaths, --doctest-modules, collect_ignore(_glob)} —
  every mutation red, unmutated green.
