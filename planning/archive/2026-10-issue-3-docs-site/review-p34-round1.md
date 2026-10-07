# Review: phases 3-4 (docs site + workflow), round 1

Staged diff reviewed 2026-10-06. Every changed file read in full; uv.lock checked with
`uv lock --check` only (rc 0, 71 packages).

## Clean

No issues found that could cause a failure, a security problem or data loss.

## What was checked, and how

All builds ran in a scratch export of the index (`git checkout-index -a`), never in the repo.

**Strict build, as CI runs it (`mkdocs build`, no `-q`)**: rc 0 on the staged tree. One
mutation per defect class, each in a fresh copy:

| mutation | result |
|---|---|
| broken autorefs cross-reference in a docstring (`[x][stacs.validate.nonexistent_thing]`) | rc 1, "Could not find cross-reference target", aborted in strict mode |
| griffe docstring warning (an `Args:` entry for a parameter that does not exist) | rc 1, two `griffe:` warnings counted, aborted in strict mode |
| missing snippet FILE (`--8<-- "NOPE.md"`) | rc 1, `SnippetMissingError` |
| misspelt snippet section (`README.md:usee`) | rc 1, `SnippetMissingError` |
| bad nav entry (`clii.md`) | rc 1, aborted in strict mode |
| dead `.md` link in a page | rc 1, aborted in strict mode |
| `::: stacs.registerr` | rc 1, BuildError (not strict-dependent) |
| broken anchor only (`configuration.md#nope`) | **rc 0** -- see note 1 |

So griffe warnings are routed into the `mkdocs` logger and do count; `strict: true` in
mkdocs.yml is honoured by a plain `mkdocs build`.

**gh-deploy, simulated as CI runs it**: bare "origin", fresh `git clone --depth 1` per run,
bot identity set, `mkdocs gh-deploy --force`.

- First deploy: rc 0, creates `gh-pages` with `.nojekyll`, commit
  "Deployed bdbd9db with MkDocs version: 1.6.1" (short sha of HEAD: the provenance).
- Second deploy from another shallow clone: rc 0. With no local `gh-pages` ref, ghp-import
  writes a parentless commit and `--force` replaces the remote branch.
- Same without `--force`: rc 1, rejected (fetch first). So `--force` is load-bearing and present.
- The "Version check skipped" WARNING is logged after the build finishes, so strict does
  not count it and the deploy does not fail on it.
- gh-deploy with a dead link: rc 1, "Aborted ... in strict mode", nothing pushed. The
  deploy job cannot publish a site the build job would reject.

**Workflow**
- Action versions match test.yml (`actions/checkout@v7`, `astral-sh/setup-uv@v10.2.0`).
- checkout v7 `persist-credentials` defaults to `true` (read from its `action.yml` at
  `v7`), so the GITHUB_TOKEN with `contents: write` is configured for ghp-import's push.
- Permissions: top-level `contents: read`, deploy job alone gets `contents: write`.
- `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`: every PR, fork or
  not, is a `pull_request` event and skips deploy; a fork PR's token is read-only anyway.
- Concurrency: job-level on `deploy`, no matrix, so the CLAUDE.md matrix trap does not
  apply. `cancel-in-progress: true` cancels an older in-flight deploy for a newer one; the
  push is a single atomic `git push`, so a cancellation cannot half-publish. A run created
  late for an older commit can still publish a stale site, and would with
  `cancel-in-progress: false` too -- that is the out-of-order case CLAUDE.md says is
  caught by detection (the deploy commit's sha), not by workflow config.
- `uv sync --locked --group docs` then `uv run --group docs`: correct; test.yml's
  `uv sync --locked` (default group `dev`) is unaffected -- `uv lock --check` passes.

**What the site can publish**
- Built site contains only docs/ pages, docs/assets/, the theme, search index, sitemap,
  objects.inv. No `CLAUDE.md`, `planning/`, `research/` or `.env` content; no marker text
  (`8&lt;`, `start:`, `end:`) in any built page.
- Snippets `base_path: ["."]` could include any repo file, but only via a `--8<--` line;
  none exists in `src/` docstrings (which render through the same extensions) or NEWS.md,
  and docs/ includes only README.md sections and NEWS.md. `restrict_base_path` defaults on.

**README on GitHub**: rendered the staged README through GitHub's `/markdown` API (gfm).
Markers are invisible; each marker directly before a paragraph, list or fence still yields
the right `<p>`/`<pre>`; headings and paragraphs come out exactly as before.

**Sections to pages**: home (intro, What it does, Install) and development -> index;
configure -> configuration; use (incl. "What it assumes") -> cli; NEWS -> changelog. Each
section reaches exactly one page; License and the site link sit outside every marker.

**No deployment defaults**: `site_url`/`repo_url` name the project's own docs and repo,
not a STAC host, database, API or bucket; the rule does not reach them.

## Notes (not failures)

1. Strict does not catch a broken *anchor* (`page.md#missing`): MkDocs 1.6's
   `validation.anchors` defaults to `info`. No anchor link exists in README, NEWS or the
   docstrings today, so nothing is broken now; `validation: {anchors: warn}` in mkdocs.yml
   would close it if wanted.
2. Cosmetic: the cli page goes H1 ("Command line") straight to H3 ("What it assumes"),
   since the README's `## Use` is replaced by the page's `#`. The changelog page's H1 reads
   "stacs" (NEWS.md's own title).
3. task_plan.md Phase 3 says `index.md` carries "assumptions"; they are on the cli page.
