# Review: Phase 1 (hexsticker), round 1

Staged diff reviewed: README.md, data-raw/make_hexsticker.R, data-raw/nge-icon_white.png,
docs/assets/logo.png, docs/assets/logo_small.png, planning/active/{findings,task_plan}.md.

## Findings

- **[severity: fragile]** data-raw/make_hexsticker.R:48-64 / docs/assets/logo_small.png:
  in the small sticker the "stacs" lettering overlaps the bottom of the NGE icon. Viewed
  both PNGs: `logo.png` (518x600) is clean, with text well below the icon, but in
  `logo_small.png` (259x300, dpi 150) the text renders at roughly twice its relative size
  and its top runs into the icon's lower points. `p_size` is the same at both dpi values,
  and hexSticker's text does not scale with `dpi`. This comes from the sibling: stac_dem_bc's
  committed `man/figures/logo_small.png` has the same overlap, worse because its name is
  longer. It breaks nothing today. It matters because task_plan Phase 3 plans to take the
  MkDocs `logo`/`favicon` from `docs/assets/`, and Phase 1's "eyeball the result" box is
  ticked. If `logo_small.png` becomes the header logo or favicon, the defect ships on every
  page. Fix options: halve `p_size` for the dpi-150 render (`p_size = p_size / 2`, or scale
  it by `dpi / 300`), or move `p_y` lower. Alternatively, use `logo.png` for both and don't
  ship `logo_small.png`.

## Checked, no issue

- Script vs sibling: the only differences are `package_name` and the two output paths
  (`man/figures/` -> `docs/assets/`). The icon is byte-identical to stac_dem_bc's committed
  copy. Both PNG dimensions match the sibling's renders.
- `download.file` with no status check (checklist: download.file / curl -L) runs only
  when the icon is absent, and the icon is committed. Accepted per the brief.
- README `<img src="docs/assets/logo.png">`: the file is staged, so it is tracked and
  not just present (checklist: repo-hosted artifact must be tracked). The path is
  relative to the repo root, which is correct for GitHub's README render. It would not
  resolve from inside the MkDocs site (docs_dir root -> `assets/logo.png`). The brief
  says the title line is kept out of the snippet includes, so this is fine as long as
  that holds in Phase 3.
- `pyproject.toml` `readme = "README.md"`: the img tag lands in package metadata only.
  The package is never published to PyPI, so this has no effect.
- No secrets, no hardcoded absolute paths, and no deployment defaults (the logo URL is
  NGE's own public asset repo, used only when the icon is missing).
- Planning diff: the checkbox flips match the staged work. The findings note about the
  Helvetica fallback is accurate (the brief accepts it).
