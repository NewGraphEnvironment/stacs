# Code-check round 1 -- branch 17-a-non-list-roles-or-stac-extensions-rais (8390c5d...HEAD)

## Checklist read

- code-check-python.md: in full.
- code-check.md: the prose of all 14 H3s under `## Mechanisms` (table rows skipped), with
  close reading of "A guard that fails toward pass", "A fixture that cannot reach the failure
  mode", "A proxy is not the property", "A guard's scope, escape hatches, and remedies" and
  "Restore the bug and prove the guard fires". Of the 24 H3s under "Rules that stand alone",
  Security and Spreadsheets: "Percent-encode a URL at construction, not at consumption" and
  "Documentation Staleness" read; 22 not read (no tool or shape in this diff).
- code-check-shell.md: none read. The diff touches no shell, git, sed or `gh` code
  (71 headings not read).
- code-check-r.md: none read. No R in the diff (121 headings not read).

## Method

Read the full diff, `item_verdict` / `_relative_href` / `_part_key` / `_inside` /
`stac_fields` / `receipt_asset` / `item_problems` in receipt.py, `_receipt_verdicts` in
register.py, `audit_items` in validate.py, and `_search_pages` in verify.py. Ran URL edge
cases through `item_verdict` directly. Ran 22 mutations, one per new guard, in a detached
worktree (`tests` + `src`, `-x`). 21 were killed and one survived (finding 2). The worktree
is removed and the checkout is clean.

## Findings

- **[severity: bug]** src/stacs/receipt.py:1612-1613 (`_relative_href`), reached from
  src/stacs/register.py:909-913. `urllib.parse.urldefrag` and `urlsplit` raise `ValueError`
  on some hrefs, for example `"http://[::1/x.tif"` ("Invalid IPv6 URL"),
  `"//[x/y.tif"`, and `"https://h＃x@y/c/x.tif"` ("contains invalid characters under
  NFKC normalization"). I reproduced the first and third: `item_verdict(item, item, r,
  item_url=...)` raises `ValueError`, with or without `item_url`. `_receipt_verdicts` reads
  the published body with plain `json.load` and runs no audit first, and it catches only
  `receipt.ReceiptError` around `item_verdict`. So one published item with a malformed asset
  href escapes `run`'s `except RegisterError` and reaches `cli.main`'s `except ValueError`,
  which exits 2 with `ERROR: Invalid IPv6 URL`. That message names no item. The DRIFT
  summary and every other item's verdict are lost. This is the shape the comment at
  register.py:914-920 says round 3 closed. The base had no such path, because the href was
  only tested with `href in parts`. Fix: catch `ValueError` from the URL parsing in
  `_relative_href` and treat that href as one that names no part, or as a disagreement,
  just as a non-string href already is at receipt.py:1788-1794.
  - **Rule:** code-check.md "A guard that fails toward pass" ; code-check.md "A guard's scope, escape hatches, and remedies"

- **[severity: fragile]** src/stacs/receipt.py:1632-1633. The prefix guard
  `if not path.startswith(base.path): return None, False` survives mutation: deleting it
  leaves all 982 tests passing. Its fixtures cannot reach the failure. "a sibling directory
  sharing a prefix" (`/catalogue/cat/x.tif` under `/catalogue/c/`) slices to `t/x.tif`, and
  "climbs out for good" (`/catalogue/x.tif`) slices to `tif`. Neither is a part key, so both
  still read `same` with the guard removed. Without the guard, an asset in another directory
  whose name is as long as the item's directory, such as
  `https://example.invalid/catalogue/d/x.tif`, slices to `x.tif`. That asset is then
  compared with part `x.tif`, which gives a false `inconsistent`, or a false agreement with
  another file's digest. The code is correct today, but CLAUDE.md requires a mutation check
  for each guard and this guard has none. A fixture of `.../catalogue/d/x.tif` kills the
  mutation.
  - **Rule:** code-check.md "Restore the bug and prove the guard fires" ; code-check.md "A fixture that cannot reach the failure mode"

- **[severity: fragile]** NEWS.md:14 ("matches an asset to the part it names however its
  href is spelled") does not hold, and where it fails the result reads as agreement. In
  `_relative_href` (receipt.py:1625-1628), scheme and netloc are compared as lower-cased
  strings only. An href that spells the same URL with a default port
  (`https://h:443/c/x.tif` under item URL `https://h/c/item.json`) or with userinfo matches
  no part. I reproduced this with `file:size: 99` against a part of 12 bytes: the verdict
  is `same`, with no note. Percent-encoding is also not decoded, which the owner decided,
  but the "however" sentence leaves that out too. The wording and the code disagree, and
  where they do, a contradicting `file:checksum` or `file:size` reads `same`. Fix: either
  drop the port when it is the scheme's default before comparing, or narrow the NEWS
  sentence (and the README line "An asset is compared with the part its href names") to the
  spellings that are actually normalised.
  - **Rule:** code-check.md "A proxy is not the property" ; code-check.md "A guard's scope, escape hatches, and remedies"

- **[severity: fragile]** NEWS.md:43-45 says `verify` now stops "when `/search` returns ...
  a token that is not a string. Each used to raise `AttributeError` or `TypeError`." That is
  true only for an unhashable token (a list or an object). A numeric token such as
  `{"token": 5}` used to pass `if not token` and was followed: an int is hashable, so the
  `seen_tokens` set accepted it and paging went on. verify.py:95 now refuses it with
  "no token". That is a behaviour change for a server that sends numeric tokens, and the
  NEWS entry calls it a crash fix. Fix: correct the sentence, or accept any hashable
  non-empty scalar.
  - **Rule:** none

Every other NEWS claim checked out against the code. The "either side" claim for malformed
asset entries holds (receipt.py:1750-1752). So does "null included" for roles
(receipt.py:1509). The `NO_RECIPE_IDENTITY` wording is identical in audit and verify. A
non-list `stac_extensions` is reported once, by the field schema, and I confirmed this for
a string and for an int. `file:size` is compared through `_whole`. The three paging
refusals hold, apart from the token case above.

/Users/airvine/Projects/repo/stacs/planning/active/review-round1.md
