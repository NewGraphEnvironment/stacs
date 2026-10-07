# Task: Documentation site: MkDocs on GitHub Pages, with a black-and-white hexsticker (#3)

stacs has docstrings (`help()`, `python -m pydoc`, `stacs --help`) and a README, but no
browsable documentation site like the NGE R packages have with pkgdown. Python has no
built-in equivalent: a site is opt-in, generated from the docstrings by a tool the project
chooses.

## Phase 1: Hexsticker
- [x] `data-raw/make_hexsticker.R` adapted from stac_dem_bc's (`package_name <- "stacs"`,
      outputs `docs/assets/logo.png` and `docs/assets/logo_small.png`), with
      `data-raw/nge-icon_white.png` committed
- [x] Render; commit the script and PNGs; eyeball the result (black fill, white border/text)
- [x] README title line carries the logo top-right

## Phase 2: Runnable docstring examples, executed in CI
- [x] `[tool.pytest.ini_options]`: `testpaths = ["tests", "src"]`, `addopts = "--doctest-modules"`
- [x] Harness test: doctests from `src/stacs` are collected, and a lookup inside one is
      refused by the guard; mutation-check it (drop `src` from testpaths / the guard → red)
      — *corrected in flight:* a lookup probe run in-process cannot fail (the session's
      sockets are already patched), and `pytest src/...` alone never loaded
      `tests/conftest.py`. The guard moved to a root `conftest.py`; the harness pins the
      config and, by subprocess, that a `src`-only run registers the guard
- [x] `>>>` examples on the offline-pure public functions listed in Context (temp files via
      `tempfile` where a path is needed); fake values only
- [x] `uv run pytest` green; CI `test.yml` unchanged (it already runs `uv run pytest`)

## Phase 3: MkDocs site
- [x] `docs` dependency group: `mkdocs>=1.6,<2`, `mkdocs-material`, `mkdocstrings[python]`; `uv lock`
- [x] `mkdocs.yml`: Material, black/white palette (light + dark toggle), `logo`/`favicon`
      from `docs/assets/`, `repo_url`, `strict: true`, `pymdownx.snippets` with
      `base_path: ["."]` and `check_paths: true`; `docs_dir` stays `docs/`
- [x] README section markers; README's `research/` link made absolute
- [x] Pages: `index.md` (README intro, what it does, install, development),
      `configuration.md` (README Configure), `cli.md` (README Use, with its assumptions),
      `changelog.md` (NEWS),
      `reference/{verify,catalogue,validate,register}.md` (`::: stacs.<module>`,
      private members filtered)
- [x] `uv run --group docs mkdocs build --strict` clean locally; a deliberately broken
      reference fails it (then reverted) — *done with a dead `.md` link instead:* a bad
      `::: ref` aborts even without strict, so it proves nothing about strict
- [x] `.gitignore` the `site/` build output

## Phase 4: Workflow, homepage, release notes
- [x] `.github/workflows/docs.yml`: build `--strict` on PRs; on push to `main`, build and
      `mkdocs gh-deploy --force` (`permissions: contents: write`, job-level concurrency,
      no matrix)
- [x] README links the site (https://newgraphenvironment.github.io/stacs/)
- [x] `NEWS.md` `## Unreleased` entry; CLAUDE.md note: docs live under `docs/`, doctests
      share the network guard
- [ ] After merge (outside this PR): enable Pages on `gh-pages`, set repo homepage, check
      deploy provenance

## Validation

- [x] Tests pass (`uv run pytest`, including doctests)
- [ ] `mkdocs build --strict` passes locally and in the PR's docs run
- [x] `/code-check` clean on each commit
- [x] PWF checkboxes match landed work
- [ ] `/planning-archive` on completion
