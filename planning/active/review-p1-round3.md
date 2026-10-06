# Review — Phase 1 (hexsticker), round 3

Scope: staged diff only (README.md, data-raw/make_hexsticker.R, data-raw/nge-icon_white.png,
docs/assets/logo.png, docs/assets/logo_small.png, planning/active/{findings,task_plan}.md).

## Findings

- **[severity: fragile]** data-raw/make_hexsticker.R:31-66 — the mechanism behind round 1's
  overlap is a session-global option, and the script does not pin it.

  `hexSticker::sticker()` always calls `geom_url()`, whose default `u_family = "Aller_Rg"` matches
  a font bundled with hexSticker, so `load_font()` runs `font_add()` + `showtext_auto()` even
  with `url = ""`. From then on showtext draws all text, at `showtext::showtext_opts()$dpi`
  (default 96). It does not read the device's `res`. The hexagon and icon scale with `dpi=`
  (ggsave → `ragg::agg_png(res = dpi)`), but the text has a fixed pixel size. That is why halving
  `dpi` doubles the text against the hexagon, and why `p_size * 150 / 300` is the correct
  compensation. The script comment's "sizes text in points, which do not scale with dpi" names
  the effect, not the cause.

  The ratio fix keeps the two renders consistent with each other for any value of that global.
  The absolute text size, though, is `p_size * D / 72` pixels, where D is whatever
  `showtext_opts(dpi)` holds in the session. Measured in a scratch copy:
  - A fresh `Rscript data-raw/make_hexsticker.R` gives both PNGs byte-identical to the staged
    blobs (`eb0ee4fd9a93`, `a618c53451ed`).
  - The same script run after `showtext::showtext_opts(dpi = 300)`, i.e. `source()`d into a
    session that had set it, gives different bytes (`4ef67179e643`, `4e4e58aa9a70`). In both
    stickers "stacs" fills the full width of the hexagon and runs past its edges and into the icon.

  So yes, this can produce a visibly wrong committed asset. It needs a regeneration in a
  session where something set showtext's dpi first, which is the documented advice for anyone
  using showtext with `ggsave(dpi=)`. Nothing in ~/Projects/repo sets it today
  (`grep -r 'showtext_opts('` over *.R/*.Rmd: no hits), so it is latent rather than live.
  Fix: one line before the first `sticker()`, `showtext::showtext_opts(dpi = 96)`. This pins the
  value the committed assets were rendered with, so they stay byte-identical.

## Checked and not a finding

- **Font.** With showtext active, `"Helvetica"` is never looked up in system fonts. showtext
  falls back to sysfonts' `"sans"`, which is the **bundled** LiberationSans-Regular.ttf, so the
  glyphs are pinned by the sysfonts package and are the same on every machine. The fallback is
  deterministic, not machine-dependent.
- **Device.** ggplot2 4.0.3 picks `ragg::agg_png` when ragg is installed and otherwise
  `grDevices::png` (quartz here). showtext draws the text either way, and size uses `res` in both.
  A different device can change antialiasing bytes, but it cannot change the layout.
- **Package versions** (hexSticker 0.5.1, ggplot2 4.0.3, showtext 0.9.8, unpinned). An upgrade
  can change the bytes on regeneration, which is churn, but it cannot change the layout. The
  fresh render reproduces the committed blobs today.
- **Paths are relative to the working directory.** Run from `data-raw/`, the script writes to
  `data-raw/data-raw/` and `data-raw/docs/assets/`, and re-downloads the icon from upstream
  `main`. The committed assets are untouched, and the stray files would show as untracked.
  This is not a wrong committed asset. Download-when-absent was accepted in the brief.
- **README.md:1.** `docs/assets/logo.png` is staged, so the relative link resolves on GitHub
  for a fresh clone.
- **planning/active/task_plan.md.** The three Phase 1 boxes ticked match what is staged: the
  script with the icon, both PNGs, and the README title line. The findings.md note on the
  Helvetica→sans fallback is accurate, and sans is the bundled Liberation Sans.
