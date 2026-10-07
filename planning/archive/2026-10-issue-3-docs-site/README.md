## Outcome

A documentation site for stacs (#3), the Python counterpart of the NGE pkgdown sites:
MkDocs with Material and mkdocstrings, built strict on every PR and deployed to a
`gh-pages` branch from `main`. README.md stays the one source of the prose: the Home,
Configuration and Command line pages are its sections, cut out by snippet markers.
Fourteen, then seventeen, docstring examples now run with the tests, and a black-and-white
hexsticker is made by `data-raw/make_hexsticker.R`.

What was learned, mostly from the review rounds, which found a defect inside the previous
round's fix in every phase:

- **The network guard was not where the doctests needed it.** pytest loads a conftest only
  for the paths it is given and their parents, so the guard in `tests/` was absent from
  `pytest src/...`. It moved to the root. The pins went wrong twice on the way, both times by
  checking from inside one session as if it stood for every invocation: first "the root
  conftest registered" (a stub passes), then "a src-only run is guarded" (a guard in `src/`
  passes). They now probe a lookup in child runs over src-only, tests-only and bare
  invocations, and assert what a bare run collects rather than what the config says.
- **Strict is not every check.** `mkdocs build --strict -q` passes a dead link, because `-q`
  hides the warnings strict counts. MkDocs' defaults also leave a missing anchor, an
  extensionless relative link, an absolute path and a page left out of nav at info level,
  where strict passes them; all seven validation settings are now at warn. A lost `[end:x]`
  snippet marker silently runs a section to the end of the README (`tests/test_docs.py`).
- **hexSticker draws its text at showtext's session-global dpi**, not the device's. The
  stac_dem_bc small sticker it was copied from has its name over the icon for that reason;
  this one halves `p_size` with the dpi and pins `showtext_opts(dpi = 96)`.

## Measurement

- Strict build vs a dead `.md` link: `--strict -q` rc 0; `--strict` rc 1; not strict rc 0.
  Changed the workflow (never `-q`) and CLAUDE.md.
- Each mutation in the tables (guard location × invocation, collection settings, link
  classes, README marker shapes) red; unmutated green. Suite 346 → 370 collected: 17
  doctests, 4 harness tests (3 invocation probes, 1 collection), 3 marker tests.
- hexsticker: a dpi-300 showtext session rendered different, overrunning bytes before the
  pin and byte-identical ones after.

## Evidence

`review-*.md` in this directory: one file per review round (`p1`, `p2`, `p34`) and the plan
review.

Closed by: PR for #3 (branch `3-documentation-site-mkdocs-on-github-page`)
