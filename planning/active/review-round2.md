# Code-check round 2: branch `15-crate-s-receipt-register-and-mapping-are` at `d2f314a`

Base `e674cda`, three-dot diff, `planning/` and the vendored `stac.json` excluded from review.
Reviewed 2026-11-15 from a detached worktree of `d2f314a`; nothing in the checkout was edited
but this file, and the worktree is removed (`git worktree list` shows the checkout alone).

## Checklist read

- `code-check-python.md`: in full (8 headings).
- `code-check.md`: the prose of all 14 H3 under `## Mechanisms` (table rows skipped), and 3
  standalone rules in full: "Documentation Staleness", "An ordered dispatch makes severity
  ordering load-bearing, and nothing enforces it", "An assertion that matches an interpolated
  value cannot see the claim around it". Not read beyond the index line: 21 (11 standalone,
  6 Security, 4 Spreadsheets and PDFs).
- `code-check-shell.md`: 16 headings, evidence blocks dropped and each cut at 2,600
  characters (only "Quoting" ran past the cut): "Reading a file line-by-line drops the last
  line without a trailing newline", "Empty arrays under `set -u` on bash 3.2", "Quoting",
  "Heredoc precedence in pipelines", "A heredoc whose body contains its own delimiter ends
  early, and the rest runs as shell", "Paths", "`mktemp` template needs enough X's, and a
  failed `mktemp` leaves an empty var", "A `curl` in a parallel fan-out needs `--max-time`",
  "A verification command can be shadowed by a shell function or alias", "A second `trap …
  EXIT` replaces the first", "`grep -c` prints the count AND exits 1 when it is zero",
  "`curl -o` without `-L` saves the redirect page as the download", "A failed `cd` lets every
  later command run in the directory you were already in", "macOS `/bin/bash` 3.2
  quote-matches a heredoc inside `$( )`", "Put cleanup on the EXIT trap, not RETURN", "`a && b
  || c` runs `c` when any step before the `||` fails". Not read beyond the index line: 55.
  The script's diff on this branch is data only (two lists, one literal, one message).
- `code-check-r.md`: index lines only, 0 sections (the diff holds no R).

## Verdict

One low-severity finding against the diff, in NEWS. The restructured `item_verdict` holds up:
nothing it used to call `inconsistent` now reads `same`, `rebuilt` or `changed`, and it raises
nothing new. The four questions this round asked are answered below the finding, with what
predates the branch kept apart from it.

## Findings

- **[severity: fragile]** `NEWS.md:33-37` — the sentence the round 1 fix rewrote is wider
  than the code in two places. Both reproduced on `d2f314a`.
  1. "`receipt.item_verdict` ... returns that verdict wherever `stac_fields` would refuse."
     Not for a receipt that is not an object, which the mapping refuses by name
     (`block_not_object`: "the receipt, or a block or entry it reads"). `stac_fields(None)`,
     `([])`, `("x")`, `(5)` each raise `ReceiptError` with that code; `item_verdict(item,
     item, <the same>)` raises `AttributeError: ... has no attribute 'get'` at
     `src/stacs/receipt.py:1606`, before any check. `item_verdict` guards `published` and
     `served` at 1590-1593 and not `receipt`. `verify` cannot reach it (`receipt.read`
     refuses a non-object first), so only a direct caller is exposed.
  2. "`verify` reports an item `inconsistent` when the mapping refuses the receipt it links
     ... with the refusal's code in the note." Not when `recipe`, `context`, `result` or
     `result.parts` is present and not an object and not null: the node check at
     `receipt.py:1602-1621` answers first, with fields `('receipt.recipe',)` and a note that
     carries no code. Measured: `recipe: "x"`, `context: []`, `result: 7`, `result.parts:
     "x"` each give `inconsistent` with no `(block_not_object)` in any note, while `recipe:
     null`, `result.parts: null` and `output: "x"` carry it. `read` checks only the version,
     so all four reach `verify`. The verdict is right either way; a reader who greps the
     note for the code misses these four. The comment at `receipt.py:1669-1672` calls this
     "two routes for one fact" and the two routes still give two notes.
  - **Rule:** code-check.md "A guard's scope, escape hatches, and remedies"

## The four questions about the restructured `item_verdict`

**Which items and receipts get a different verdict than before.** Differential fuzz, 40,000
triples of (published, served, receipt): a valid receipt and item with 0-2 of 18 receipt
paths and 0-2 of 16 item paths set to one of 26 junk values (deletion among them), and one
more item path changed on the served side in about 40% of them. Each triple was run through
the base module (`e674cda`), the commit before the fix (`d2f314a^`) and the head.

| base | before fix | head | cases | what it is |
|---|---|---|---|---|
| X | X | X | 31,979 | the same in all three (25,749 inconsistent, 4,565 same, 1,488 rebuilt, 177 changed) |
| same / rebuilt / changed / raised `ReceiptError` | inconsistent | inconsistent | 8,010 | the branch's earlier commits: receipts `stac_fields` now refuses. Unchanged by the fix commit |
| rebuilt / same / changed | same as base | inconsistent | 10 | a part the mapping refuses behind an asset that did not carry the field showing it: the fix |
| inconsistent | same | inconsistent | 1 | part `sha256` with a newline behind an asset with `file:checksum: null`; the walk at `d2f314a^` compared `None != None` |

No triple moved from `inconsistent` to `same`, `rebuilt` or `changed` between the commit
before the fix and the head, and none raised anything but `ReceiptError`. A schema-valid
receipt with an item built from `stac_fields` reads `same` in all three.

**Whether anything but `ReceiptError` can come out.** Three routes, none introduced by this
branch (the first two reproduce on `e674cda`; the third was run on the head only), and the
first two unreachable from `verify`:

- a receipt that is not an object: `AttributeError` at `receipt.py:1606` (finding above);
- `file:size` on a published asset that names a part, as an integer too large for a double
  (`json.load` keeps it an `int`): `OverflowError: int too large to convert to float` at
  `receipt.py:1688`. Run through `verify` with the repo's own harness, the run stops earlier
  with `ERROR: body of 'a0' has no canonical form: integer of 401 digits is beyond a double`,
  so `_digests` refuses the body before the receipt axis sees it;
- a mirrored property nested 3,000 deep: `RecursionError` out of `canonical`. Not traced
  through `verify`.

The known `roles` / `stac_extensions` `TypeError` (stacs#17) was not re-run.

**Whether it can return `same` or `rebuilt` over something it could not read.** Not through
anything the fix changed. Two shapes that predate the branch still do, both inside the family
stacs#17 names (the item compared with the receipt one way only), and neither matches the
wording of its last checkbox ("on an asset that **names a part**"):

- An asset that carries `file:checksum` or `file:size` and whose href is not spelled exactly
  as a part key is skipped as "not an output this receipt describes" (`receipt.py:1660-1663`).
  Measured with a part keyed `x.tif` and an asset checksum that contradicts it, same on both
  sides: href `https://example.invalid/x.tif` gives `same`; `./x.tif` gives `same`; no href
  gives `same`; href `x.tif` gives `inconsistent`. A catalogue whose items carry absolute
  hrefs has no asset that names a part, so the asset half compares nothing there. The
  register-level fixtures are that shape (`_item` hrefs are `https://example.invalid/<key>`,
  `_receipt_doc` has `parts: {}`), so no `verify` test reaches the asset half; the unit tests
  do.
- An asset entry that is not an object (`"data": "x.tif"`, `"data": null`) on both sides is
  skipped by the walk (`receipt.py:1651`) and by `_mirrored` (`:1561`): `same`. On one side
  only it reads `rebuilt`.
  - **Rule (both):** code-check.md "A guard that fails toward pass". Not counted against the
    diff; worth a line in stacs#17 so its checkbox covers the asset that names no part.

**Whether NEWS describes it truly.** Yes apart from the finding. Checked: at the base a part
held as `null` was read as not described (`same`; head `inconsistent`); the note carries the
code for every refusal that reaches `stac_fields` (the call passes a dict of string hrefs, so
neither code-less refusal can fire); "two kinds" of receipt pass `validate` and are refused
(every path of crate's worked-case receipt replaced by 29 junk values or deleted: 10
validate-passing refusals, all `time_not_utc`, `recipe_id_not_sha256` or
`part_sha256_not_sha256`, each a trailing newline or an instant that does not exist).

## Mutations

Run in the worktree copy with bytecode caching off, each restored and the tree confirmed
clean. The first pass reused a stale `.pyc` for one row (two same-length edits within a
second), which is why caching was turned off and the row re-run.

| mutation | result |
|---|---|
| `stac_fields(receipt)` with no `assets=named` | 19 red, as `findings.md` says |
| asset `file:checksum` comparison removed | red, `test_an_items_asset_fields_are_checked_against_the_receipts_parts` |
| asset `file:size` comparison removed | red, same test |
| non-string href not recorded | red, `test_an_asset_href_that_is_not_a_string_is_not_used_as_a_dict_key` |
| mapping's refusal re-raised from `item_verdict` | red, `test_a_receipt_the_mapping_refuses_is_inconsistent_never_same` |
| properties comparison removed | red, `test_an_item_that_claims_a_recipe_its_receipt_does_not_have_is_inconsistent` |
| `_whole` accepts a negative | red, `item_problems` `[negative size]` |
| each of the three patterns back to `.match` | red: `[datetime with a trailing newline]`, `test_multihash_refuses_anything_but_a_sha256`, `[multihash with a trailing newline]` |
| `Comparison.overrides` always empty | red, `test_an_override_that_changes_an_action_is_named_on_the_comparison` |
| `receipt_asset_in_assets` check removed | red, the 142-case vector test |
| `isinstance(size, bool)` dropped from the size comparison | green, 586 tests. The guard is at the base too (`e674cda`), so not this branch's; no test holds an item with `file:size: true` |

Full suite on the head: 884 passed.

## Also seen, not findings

- `src/stacs/register.py:901-905`, in a file the diff does not touch: the comment says
  `item_verdict` raises on "a non-hex recipe_id, a non-ISO context.time". After this branch
  both return `inconsistent`; the handler is still needed for the NaN case it also names.
- `tools/crate_receipt_vendor.sh`: the changes are two list rows per moved file, two URL rows,
  `FROZEN_URLS=4` and the success message. The README link added inside the `receipts`
  markers is absolute and `crate/tree/main/inst/extdata/receipt/mapping` lists `v1.0.0` and
  `v1.1.0`.

## Not checked

- Round 1's verified items were not repeated: the suite on 3.11, `check` under bash 3.2, the
  strict docs build, the wheel, the 87/142 and 28 = 17 + 8 + 3 counts.
- crate's R was not run.
- The fuzz's junk values held no integer past 2^53 and no `roles` mutation; those two were
  probed by hand, above.

/Users/airvine/Projects/repo/stacs/planning/active/review-round2.md
