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
- [ ] `[tool.pytest.ini_options]`: `testpaths = ["tests", "src"]`, `addopts = "--doctest-modules"`
- [ ] Harness test: doctests from `src/stacs` are collected, and a lookup inside one is
      refused by the guard; mutation-check it (drop `src` from testpaths / the guard → red)
- [ ] `>>>` examples on the offline-pure public functions listed in Context (temp files via
      `tempfile` where a path is needed); fake values only
- [ ] `uv run pytest` green; CI `test.yml` unchanged (it already runs `uv run pytest`)

## Phase 3: MkDocs site
- [ ] `docs` dependency group: `mkdocs>=1.6,<2`, `mkdocs-material`, `mkdocstrings[python]`; `uv lock`
- [ ] `mkdocs.yml`: Material, black/white palette (light + dark toggle), `logo`/`favicon`
      from `docs/assets/`, `repo_url`, `strict: true`, `pymdownx.snippets` with
      `base_path: ["."]` and `check_paths: true`; `docs_dir` stays `docs/`
- [ ] README section markers; README's `research/` link made absolute
- [ ] Pages: `index.md` (README intro, what it does, install, assumptions, development),
      `configuration.md` (README Configure), `cli.md` (README Use), `changelog.md` (NEWS),
      `reference/{verify,catalogue,validate,register}.md` (`::: stacs.<module>`,
      private members filtered)
- [ ] `uv run --group docs mkdocs build --strict` clean locally; a deliberately broken
      reference fails it (then reverted)
- [ ] `.gitignore` the `site/` build output

## Phase 4: Workflow, homepage, release notes
- [ ] `.github/workflows/docs.yml`: build `--strict` on PRs; on push to `main`, build and
      `mkdocs gh-deploy --force` (`permissions: contents: write`, job-level concurrency,
      no matrix)
- [ ] README links the site (https://newgraphenvironment.github.io/stacs/)
- [ ] `NEWS.md` `## Unreleased` entry; CLAUDE.md note: docs live under `docs/`, doctests
      share the network guard
- [ ] After merge (outside this PR): enable Pages on `gh-pages`, set repo homepage, check
      deploy provenance

## Validation

- [ ] Tests pass (`uv run pytest`, including doctests)
- [ ] `mkdocs build --strict` passes locally and in the PR's docs run
- [ ] `/code-check` clean on each commit
- [ ] PWF checkboxes match landed work
- [ ] `/planning-archive` on completion
