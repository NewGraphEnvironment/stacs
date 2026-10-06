# Review — phases 3–4, round 3 (staged diff, #3)

Reviewed: `git diff --cached` in full; every changed file read; `uv lock --check` passes
(71 packages). All builds/tests run on an index export
(`checkout-index -a --prefix=<scratchpad>/r3/`), never the working tree.

## The mechanism behind rounds 1 and 2

**A scope stated from the cases in view, never computed over the population.** Round 1
read "strict" as "every link check" — it is "every check whose level is WARNING". Round 2
found the same inside that fix (anchors was not the only info-level check) and in the prose:
"examples on every public function" and "docs_dir/markers" were written from what the
author had looked at, not from an enumeration. The same assumption has a second face:
**a fact restated in two places gets fixed in the one that was quoted.**

## Findings

- **[severity: fragile — false committed claim]** `mkdocs.yml:4` — the header comment
  still says *"MkDocs publishes only docs/, so CLAUDE.md, planning/ and research/ cannot
  reach the site."* Round 2 corrected that claim in `CLAUDE.md` (which now says, correctly,
  that a snippet can include any file under `base_path: ["."]`) but not its twin here.
  Measured: appending `--8<-- "CLAUDE.md"` to `docs/cli.md` builds strict with rc=0 and
  `site/cli/index.html` contains CLAUDE.md's text ("never PyPI"). The comment is the
  config's own statement of its safety property and is the one a future editor reads first.
  Fix: replace with the CLAUDE.md wording (reaches the site only if a page names it).

- **[severity: false published claim]** `NEWS.md:12-13` — *"Runnable examples in the
  docstrings of every public function that works offline … Functions that need a live API
  or ssh have none."* The enumeration behind it covered the four modules on the site, not the
  package. `stacs.cli` is a public module (no underscore, no `__all__`) with 12 public
  names and no examples, several fully offline: `read_config` (reads a TOML file),
  `merge_asset_rules`, `build_parser`, `build_transport`, `build_target`. Public methods
  with no example are offline too: `Transport.check`, `Target.check`, `Audit.rules`,
  `Audit.ok`. So the "seven lacking one" count is seven of the documented module-level
  functions, not of the package. Fix: narrow the sentence to what was enumerated (e.g.
  "every offline function in the API reference — `verify`, `catalogue`, `validate`,
  `register`"), or add examples; narrowing is the honest one-line fix.

- **[severity: fragile — guard fails toward pass]** `README.md` section markers /
  `CLAUDE.md` "Keep the markers when editing it" — only half of that instruction is
  enforced. A missing or misspelled `[start:x]` aborts the build (`SnippetMissingError`,
  measured rc=1); a missing or misspelled `[end:x]` does not: pymdownx.snippets takes the
  section to end of file. Measured: `[end:use]` → `[end:usex]` builds strict rc=0, and the
  Command line page gains README's "Development" and "License" sections (same for
  `[end:home]`, which would pull Configure/Use/Development onto the home page, duplicating
  three pages). Nothing in the build or the tests sees it. Fix if wanted: a test in `tests/`
  asserting every `[start:NAME]` in README.md has a matching `[end:NAME]` after it (and the
  four names the docs pages use exist) — or state the gap in the CLAUDE.md paragraph.

## Checked and holding

- **The seven validation settings are MkDocs 1.6.1's complete set.** `mkdocs/config/defaults.py`
  `Validation`: `nav.{omitted_files, not_found, absolute_links}`, `links.{not_found,
  absolute_links, unrecognized_links, anchors}` — seven, all set to `warn`. The mkdocs.yml
  comment naming which defaults are info-level is accurate.
- **Plugin checks off by default: none found that matter.** mkdocstrings-python's
  `warn_unknown_params`, `warn_missing_types`, `warnings` default True; autorefs has no
  off-by-default check. Mutations: an `Args:` entry for a non-parameter → 2 griffe
  WARNINGs, strict abort rc=1; an unresolved `[stacs.nope][]` in a docstring → autorefs
  WARNING, abort rc=1. Material adds no link validation.
- **`-q` claim (workflow comment and CLAUDE.md) is true.** Dead `[dead](nowhere.md)` inside
  the home markers: `mkdocs build` rc=1; `mkdocs build -q` rc=0.
- **Raw HTML claim is true.** `<a href="nowhere.md">` inside the markers builds rc=0.
- **`nav.omitted_files: warn` does not misfire on assets.** `docs/assets/notes.txt` and
  `x.json` added → rc=0; only a `.md` page (`docs/assets/README.md`) warns (rc=1), which is
  the intended behaviour (`not_in_nav` exists if ever needed).
- **Doctests.** Full suite on the export, 3.12: 367 passed. `src/` doctests on 3.11
  (`uv sync --locked --python 3.11`): 17 passed. `fetch_bodies(retries=1)` never sleeps
  (`if attempt < retries`); its stderr line is not compared by doctest (it shows in the
  pytest log, harmless). `as_uri()` on a POSIX temp path is `file:///tmp/...`, read by
  urllib with no socket, so the network guard is not involved. The `(...)` in the
  `published_digests` traceback hides only the href; ELLIPSIS is in
  `doctest_optionflags` and applies to exception messages. `remote_script` example
  matches the script's pypgstac line and final `__stacs_ok=1` line; values are
  `example.invalid`.
- **Other NEWS/CLAUDE.md claims.** Root `conftest.py` exists, `tests/conftest.py` gone;
  `data-raw/make_hexsticker.R` exists; changelog includes NEWS whole; PR builds have no
  `paths:` filter, so "built strict on every pull request" holds; `research/pgstac_round_trip.md`
  exists on `origin/main` for the README's absolute link; a relative README link inside
  the markers does fail strict (not_found / unrecognized_links / anchors).
- **Workflow.** `actions/checkout@v7` and `astral-sh/setup-uv@v10.2.0` resolve
  (`git ls-remote`), and test.yml's last five runs with the same pins are green.
  Job-level `concurrency` on a non-matrix job; deploy only on push to main with
  `contents: write`, build-only on PRs with `contents: read`. `gh-deploy` inherits
  `strict: true` from mkdocs.yml. `origin/main` has nothing new over HEAD.
