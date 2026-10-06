# Findings — Documentation site: MkDocs on GitHub Pages, with a black-and-white hexsticker (#3)

## Issue context

## Problem

stacs has docstrings (`help()`, `python -m pydoc`, `stacs --help`) and a README, but no
browsable documentation site like the NGE R packages have with pkgdown. Python has no
built-in equivalent: a site is opt-in, generated from the docstrings by a tool the project
chooses.

## Proposal

The Python counterpart to pkgdown:

| R / pkgdown | here |
|---|---|
| roxygen → `man/` → reference pages | docstrings → [mkdocstrings](https://mkdocstrings.github.io/) → reference pages |
| `_pkgdown.yml` | `mkdocs.yml`, [Material](https://squidfunk.github.io/mkdocs-material/) theme |
| README as home, NEWS as changelog | the same files, pulled into `docs/` |
| `@examples` run in CI | docstring examples run by `pytest --doctest-modules` |
| pkgdown workflow → GitHub Pages | `mkdocs build` workflow → GitHub Pages |
| `man/figures/logo.png` | theme `logo` + `favicon`, and the logo top-right in the README |

## Work

- [ ] Hexsticker, **black and white** (the NGE palette), made the way stac_dem_bc's
      `data-raw/make_hexsticker.R` makes its own, with `nge-icon_white.png`; committed as
      the source script plus the rendered PNGs
- [ ] `mkdocs.yml` (Material, black/white palette, logo, favicon); `docs/` with home
      (README), CLI usage, configuration (`stacs.toml`), API reference (mkdocstrings over
      `stacs.verify`, `catalogue`, `validate`, `register`), changelog (NEWS)
- [ ] Docs dependencies in a `docs` dependency group, not the runtime dependencies
- [ ] Runnable examples in the public functions' docstrings, executed in CI
- [ ] Workflow: build on PRs (strict, so a broken reference fails), deploy to GitHub Pages
      from `main`
- [ ] Repo homepage and README link to the site

## Notes

- MkDocs publishes only what is under `docs/`, so a root `CLAUDE.md` or `planning/` cannot
  reach the site the way soul's pkgdown-publishing convention describes for pkgdown. Keep
  it that way: no `docs_dir` at the repo root.
- After v0.1.0; the release does not depend on it.

## Plan-mode exploration (2026-10-06)

stacs has docstrings and a README but no browsable site like the NGE R packages' pkgdown
sites. Issue #3 asks for the Python counterpart: mkdocstrings reference pages, Material
theme, README as home, NEWS as changelog, doctests run in CI, a Pages workflow, and a
black-and-white hexsticker made the way `stac_dem_bc/data-raw/make_hexsticker.R` makes its own.

What exploration found, and what shaped the phases:

- **No doctests exist** (`grep '>>>' src` is empty) and there is no `[tool.pytest.ini_options]`.
  The network guard is `pytest_configure` in `tests/conftest.py`, so doctests must run **in
  the same pytest session as `tests/`**, or they run unguarded. Plan: `testpaths = ["tests",
  "src"]` + `--doctest-modules`, and a harness test pinning that doctests are collected and
  guarded (mutation-checked, per CLAUDE.md).
- **Offline-pure public functions** take runnable examples: `verify.{search_body, ids_diff,
  canonical_json, body_digest, content_diff}`, `catalogue.{fetch_key, collection_item_links,
  read_hrefs}`, `validate.{parse_asset_keys, item_paths_in_dir, audit_items, validate_items}`,
  `register.{ndjson_write, describe_rules}`. Functions that need a live API or ssh
  (`ids_registered`, `bodies_*`, `collection_state`, `fetch_bodies`, `probe`, `load`, `run`)
  get **no** example rather than a `+SKIP` one — an example that never runs is rot; their
  usage is the CLI page. Example values are obviously fake (`example.org`), which
  `tests/test_no_deployment_defaults.py` already scans for.
- **README is the single source** for prose. `pymdownx.snippets` (ships with Material) pulls
  README sections into pages via `<!-- --8<-- [start:x] -->` markers, so Home / Configuration /
  CLI are not copies. Two README links would break the strict build: the logo `<img>`
  (kept outside the included sections) and `research/pgstac_round_trip.md` (made an absolute
  GitHub URL, since `research/` must not enter `docs/`).
- **Hexsticker**: Rscript + hexSticker are installed locally. Same script shape as
  stac_dem_bc's, `package_name <- "stacs"`, outputs to `docs/assets/` (MkDocs can only serve
  the logo from inside `docs/`); `data-raw/nge-icon_white.png` committed like stac_dem_bc's.
  README gets `# stacs <img src="docs/assets/logo.png" align="right" height="139" alt="stacs logo" />`
  — the fly/pkgdown pattern.
- **Deploy to a `gh-pages` branch** (`mkdocs gh-deploy`), not a Pages artifact: the CI
  convention's provenance check (`git log -1 FETCH_HEAD` on gh-pages) then works here as on
  every pkgdown repo. Repo has `has_pages: false`, `homepage: null` today.
- Pin `mkdocs<2` in the docs group (MkDocs 2 is announced as plugin-breaking); verify at
  lock time.

## Hexsticker (2026-10-06)

hexSticker warns `font family 'Helvetica' not found, will use 'sans'` on this machine; the
render matches stac_dem_bc's committed `man/figures/logo.png` (same layout, same sans
lettering), so the sibling stickers were evidently made with the same fallback.

## Doctests and the network guard (2026-10-06)

- `pytest src/stacs/catalogue.py --trace-config` registered no conftest at all: pytest loads
  conftests for the given paths and their parents only, so the guard in `tests/` never ran
  for a src-only run. Moved to the root (`git mv`); confirmed registered after.
- `validate_items` works offline for STAC 1.1.0 (bundled core schemas) but not 1.0.0, which
  pystac fetches from schemas.stacspec.org — probed with lookups blocked. Its example uses
  1.1.0 and shows only `[]` and the empty-input error, since jsonschema's messages vary.
- Examples use `example.invalid` (the suite's convention), which fails closed if a run
  were ever unguarded; `example.org` resolves.
- No example on the functions that need a live API or ssh (`ids_registered`, `bodies_*`,
  `collection_state`, `fetch_bodies`, `probe`, `load`, `run`): an example that never runs
  is rot. Their usage is the CLI page.
- `doctest_optionflags = ELLIPSIS, NORMALIZE_WHITESPACE` so long outputs wrap and a temp
  path can be elided.

## The site build (2026-10-06)

- Locked: mkdocs 1.6.1, mkdocs-material 9.7.7, mkdocstrings 1.0.6, mkdocstrings-python
  2.0.9, pymdown-extensions 10.x. Material prints a boxed MkDocs-2.0 notice on every build;
  it is not a logged warning, and the strict build passes with it.
- **`mkdocs build --strict -q` passes a dead link.** `-q` raises the log level past WARNING
  and strict counts warnings, so nothing is counted. Measured in a scratch copy: a link to
  a missing `.md` — `-q`: rc 0; no `-q`, strict: "Aborted with 1 warnings", rc 1; no `-q`,
  not strict: warning, rc 0. The workflow never passes `-q`; CLAUDE.md says so.
- A misspelt snippet section (`README.md:usee`) raises `SnippetMissingError`, rc 1.
- README is the single source: `<!-- --8<-- [start:x] -->` markers (invisible on GitHub)
  for home / configure / use / development; the logo `<img>` and the site link sit outside
  them. The one relative README link (`research/pgstac_round_trip.md`) is now absolute,
  since inside `docs/` it would resolve to a page that does not exist.
- ghp-import commits "Deployed <sha> with MkDocs version: <v>" to gh-pages, not pkgdown's
  "Deploying to gh-pages from @ …"; the provenance check reads `<sha>` from it all the same.

## Review of the site (2026-10-06)

- Example coverage, enumerated from the modules rather than recalled: every public function
  in verify/catalogue/validate/register has an example except the seven that need a live
  API or ssh (`ids_registered`, `bodies_registered`, `bodies_serving`, `collection_state`,
  `probe`, `load`, `run`). Round 2 had found `published_digests`, `remote_script` and
  `fetch_bodies` (which reads `file://`) missed; added.
- Link validation: MkDocs 1.6 has seven link-validation settings (nav: omitted_files,
  not_found, absolute_links; links: not_found, anchors, absolute_links, unrecognized_links).
  All seven are at warn; each mutation (extensionless `[LICENSE](LICENSE)`, `/stacs/nowhere/`,
  a page left out of nav, a missing anchor, a missing page) aborts the strict build. Not
  checked by any setting: raw HTML, and links inside docstrings that mkdocstrings renders
  (none exist today).
- `docs_dir: .` is refused by MkDocs 1.6 outright, so the way CLAUDE.md or planning/ could
  reach the site is a snippet include (`base_path: ["."]`), not the docs dir.

## Errors Encountered

| Error | Resolution |
|-------|------------|
