# Review: #3 phases 3-4, round 2 (staged set)

Method: `git checkout-index -a` into scratch copies, one copy per mutation, `mkdocs build`
(strict from mkdocs.yml, no `-q`) on each. mkdocs 1.6.1 from the repo venv.
`uv lock --check`: consistent. Unmutated staged set builds clean.

## Findings

- **[fragile]** CLAUDE.md:66-67 (and mkdocs.yml:13-16) — the claim "keep a README link
  absolute or outside the markers: a relative one resolves against `docs/` and fails the
  strict build" is false for three link classes, each of which builds rc 0 and 404s on the
  site:
  - a relative link MkDocs calls *unrecognized* — no file extension, or a directory:
    `[lic](LICENSE)` and `[r](research/)` inside `start:home` log
    `INFO - ... unrecognized relative link 'LICENSE', it was left as is.`, rc 0.
    `[LICENSE](LICENSE)` is a routine README link (this README has a `## License`
    section, currently outside the markers and unlinked).
  - an absolute-path link (`/stacs/nowhere/`): INFO, rc 0.
  - raw HTML inside the markers (`<a href="nowhere.md">`, `<img src="docs/assets/nope.png">`):
    not checked at all, rc 0.

  (A relative link *with* an extension is caught: `data-raw/make_hexsticker.R` and a
  markdown image `docs/assets/logo.png` both abort.) Fix for the first two: add
  `unrecognized_links: warn` and `absolute_links: warn` under `validation:` beside
  `anchors: warn`. Verified: the current site builds clean with both, and
  `[lic](LICENSE)` then aborts ("Aborted with 1 warnings in strict mode!"). Raw HTML
  has no MkDocs setting, so CLAUDE.md should say so (keep `<img>`/`<a>` outside the
  markers, as the logo already is).

- **[false claim]** NEWS.md:12-13 — "Runnable examples in the docstrings of the public
  functions that work offline". Two public functions rendered on the reference pages work
  offline and have no example: `catalogue.published_digests` (reads a local fetch
  directory) and `register.remote_script` (returns a string). Neither is in findings.md's
  offline list nor its "needs a live API or ssh" list; they were missed, not excluded.
  Add examples or narrow the wording.

- **[false claim, low]** CLAUDE.md:67-68 — "Never set `docs_dir` to the repo root, which
  would publish `CLAUDE.md` and `planning/`": MkDocs 1.6.1 refuses that config outright
  ("The 'docs_dir' should not be the parent directory of the config file", "Aborted with a
  configuration error!"), so it cannot publish anything. The routes that *can* put
  CLAUDE.md or planning/ on the site are a snippet include (`base_path: ["."]` makes any
  repo file includable) or a symlink under `docs/`. Same paragraph, line 64-65: "pull
  their prose from README.md and NEWS.md by section marker" — NEWS.md is included whole
  (`docs/changelog.md`), with no markers.

## Questions asked, answered

`anchors: warn` false positives — none found:
- markdown link to a mkdocstrings anchor (`reference/verify.md#stacs.verify.body_digest`):
  passes; a wrong one (`#stacs.verify.nope`) aborts, so mkdocstrings anchors are known to
  the validator, not skipped.
- autorefs `[stacs.verify.body_digest][]`: passes; a bad target aborts (autorefs warning).
- changelog headings (`changelog.md#010`, `#unreleased`): pass.
- Material permalinks / toc: current build clean.
- docstring cross-page link with a valid anchor (`../configuration.md#configuration`)
  and a `[x][stacs.verify.ids_diff]` ref: pass.
- absolute GitHub URLs (with or without anchors): not checked, so no false positive.
- a README same-page anchor that crosses a page boundary after the split
  (`[Configure](#configure)` in `home`): aborts — the intended catch.

`mkdocs gh-deploy`: unchanged except that it inherits the check. With a bad anchor,
`gh-deploy --force` against a bare remote aborted rc 1 and the remote had no branches.

Still invisible to strict after the fix above:
- anchors in docstring markdown links: `[r](../cli.md#nowhere)` and `[r](#nowhere)` in a
  docstring both build rc 0 (the path half is checked: `[m](missing.md)` aborts). No
  docstring has a markdown link today; autorefs-style refs are checked.
- absolute URLs to the site's own host (`https://newgraphenvironment.github.io/stacs/nowhere/`): rc 0.
- raw HTML, above.

Rechecked, no issue:
- `-q` claim: bad anchor, `-q` rc 0, without rc 1. True.
- NEWS: root conftest move (tests/conftest.py absent, root conftest present), hexsticker
  script path, "built strict on every pull request" (no branch/paths filter), reference
  pages, home/config/CLI/changelog pages: true.
- README prose across the split: no "below"/"above"/"this README"; NEWS's "this file as
  its changelog" reads correctly on the changelog page.
- docs/assets/logo.png and logo_small.png are tracked.
- Workflow: action versions match the green test.yml; no matrix, so the job-level
  concurrency group is fine; no `paths:` filter; deploy gated to push on main; top-level
  `contents: read`, deploy elevates only itself.
