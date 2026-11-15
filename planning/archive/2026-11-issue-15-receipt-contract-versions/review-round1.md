# Code-check round 1: branch `15-crate-s-receipt-register-and-mapping-are` at `1ad7de6`

Base `e674cda`, three-dot diff, `planning/` and the vendored `stac.json` excluded from review
(its structure was read and measured). Reviewed 2026-11-15 from a detached worktree of
`1ad7de6`; nothing in the checkout was edited, and the worktree is removed.

## Checklist read

- `code-check-python.md`: in full (8 headings).
- `code-check.md`: the prose of all 14 H3 under `## Mechanisms` (table rows skipped), and
  5 of the standalone rules in full: "Documentation Staleness", "An ordered dispatch makes
  severity ordering load-bearing, and nothing enforces it", "A link to a repo-hosted artifact
  must be *tracked*, not merely present", "An assertion that matches an interpolated value
  cannot see the claim around it", "A pluralisation marker takes the quantity of whatever was
  substituted last". Not read beyond the index line: 19 (9 standalone, 6 Security, 4
  Spreadsheets and PDFs).
- `code-check-shell.md`: 18 headings, each trimmed to about 1,300 characters with evidence
  blocks dropped, so the long ones were not read to the end: "Reading a file line-by-line
  drops the last line without a trailing newline", "Empty arrays under `set -u` on bash 3.2",
  "Quoting", "Heredoc precedence in pipelines", "A heredoc whose body contains its own
  delimiter ends early", "Paths", "`mktemp` template needs enough X's", "A `curl` in a
  parallel fan-out needs `--max-time`", "`if ! cmd; then rc=$?` captures the negation", "A
  verification command can be shadowed by a shell function or alias", "A second `trap … EXIT`
  replaces the first", "A `local` statement cannot read a variable it is assigning in the same
  statement", "`curl -o` without `-L` saves the redirect page", "A failed `cd` lets every later
  command run in the directory you were already in", "macOS `/bin/bash` 3.2 quote-matches a
  heredoc inside `$( )`", "An apostrophe in a comment inside a single-quoted program closes
  the program", "Put cleanup on the EXIT trap, not RETURN", "`a && b || c` runs `c` when any
  step before the `||` fails". Not read beyond the index line: 53.
- `code-check-r.md`: index lines only, 0 of 121 sections (the diff holds no R).

## Verdict

No defect that breaks the branch's main claim. The suite passes (878 on Python 3.12 and 878
on 3.11), `tools/crate_receipt_vendor.sh check` passes under `/bin/bash` 3.2.57 (`OK: 16
file(s) match … and all 4 frozen URLs serve them`), `mkdocs build --strict` exits 0, and the
wheel holds both versioned CSVs. A fuzz of `stac_fields`, `compare`, `item_problems` and
`item_verdict` (every path of a valid receipt and item replaced by 20 junk values, plus
junk arguments) found no exception other than `ReceiptError` that this branch introduced.

Four low-severity findings against the branch, then two that predate it.

## Findings

- **[severity: fragile]** `src/stacs/receipt.py:1640-1694` (`item_verdict`), with
  `NEWS.md:33-36` — a receipt the mapping refuses for a **part** is still reported `same`
  when the item's asset does not carry the field that part's fault sits in. `item_verdict`
  calls `stac_fields(receipt)` with no `assets`, so the three part-level refusals
  (`part_sha256_not_sha256`, `bytes_not_whole`, and `block_not_object` for a part) are never
  reached there; its own walk covers the third (the new `if href in parts` arm) but covers
  the other two only through whichever of `file:checksum` / `file:size` the item happens to
  carry. Reproduced on the head commit, with a receipt valid in every other member:
  - part `{"sha256": "b"*64 + "\n", "bytes": 12}`, item asset `{"href": "x.tif",
    "file:size": 12}` → `same` (`stac_fields(receipt, assets={"data": "x.tif"})` refuses
    `part_sha256_not_sha256`; `validate` passes this receipt, as NEWS says);
  - part `{"sha256": "b"*64, "bytes": -5}`, item asset with the matching `file:checksum`
    only → `same` (`bytes_not_whole`);
  - part `{}`, item asset `{"href": "x.tif"}` → `same`, while part `null` with the same
    item → `inconsistent`.
  So NEWS's "`receipt.item_verdict` returns that verdict for every such receipt" holds for
  what `stac_fields(receipt)` refuses without assets (the fuzz confirms: no refusal of
  that call ends in `same` or in a raise) and not for a receipt the mapping refuses once the
  item's own assets are named. It needs an item carrying one of the two file fields without
  the other, which `stac_fields` never builds, and `verify` has already set a non-zero
  status for the item's drift; what is wrong is the list the item lands in.
  - **Rule:** code-check.md "A fix lands in one of two callers that share a harness"

- **[severity: fragile]** `src/stacs/receipt.py:1223-1224` (`stac_fields` docstring) — "refuses
  with a `ReceiptError` whose `code` is one of `STAC_REFUSALS`" is not true of two refusals in
  the same function, which carry `code=None`: `assets` that is not a mapping (line 1263,
  commented as deliberate) and an href that is not a string (line 1355, no comment).
  Reproduced: `stac_fields(good, assets="x")` and `stac_fields(good, assets={"data": 7})`
  both raise with `e.code is None`. `item_verdict` allows for it (`e.code or 'refused'`) and
  `ReceiptError`'s own docstring says "None otherwise", so only a caller that trusts this
  sentence and indexes by `e.code` is exposed.
  - **Rule:** code-check.md "A guard's scope, escape hatches, and remedies"

- **[severity: fragile]** `tests/test_receipt_vectors.py:373` — `assert r.REGISTER_VERSION in
  DIRS["compare"]` cannot fail: `DIRS["compare"]` is built as
  `f"register/v{r.REGISTER_VERSION}"` on line 33, so both operands come from the one
  constant. Related, measured in the worktree copy: replacing `register=REGISTER_VERSION`
  with `register=RECEIPT_VERSION` in `compare`, and separately reading the register from
  `f"v{RECEIPT_VERSION}"` in `register()`, each left all 517 tests green (the receipt, vector,
  contract, register and package test files plus `receipt.py`'s doctests). Both constants are `"1.0.0"` today, so the two programs
  are the same on every input and no fixture can tell them apart until the versions diverge
  (at which point `got.register == r.REGISTER_VERSION` on line 371 would fire). The code is
  right as written; the line-373 assertion is the part that proves nothing.
  - **Rule:** code-check.md "Restore the bug and prove the guard fires" ;
    code-check.md "A fixture that cannot reach the failure mode"

- **[severity: fragile]** `NEWS.md:28-32` — under **Behaviour change**, "An item is refused
  when `receipt:recipe_id`, `processing:datetime` or a `file:checksum` carries a trailing
  newline or a digit outside ASCII". The trailing newline is new for all three. The digit
  outside ASCII is new only for `processing:datetime`: at the base the other two patterns
  were already `[0-9a-f]`, so a non-ASCII digit in a `recipe_id` or a checksum was refused
  before this branch. True as a description of what is refused, wider than what changed.
  - **Rule:** code-check.md "A guard's scope, escape hatches, and remedies"

## Predates the branch (reproduced on `e674cda` and on `1ad7de6`; lines the diff does not change)

Listed because the branch's stated aim is that `item_verdict` never reports agreement it
could not establish and that these functions refuse with `ReceiptError`; not counted against
the diff.

- **[severity: fragile]** `src/stacs/receipt.py:1651-1655` (`item_verdict`) — the published
  item is compared with the receipt one way only: the loop walks the fields the receipt
  **claims** and never the mirrored fields the item publishes that the receipt does not
  produce. Reproduced: a migrated receipt (`output.migrated_from`, `recipe_id` null) with an
  item publishing `receipt:recipe_id` → `same`, `ok` true; a receipt whose `recipe.code` is
  `{}` with an item publishing `processing:software: {"stacs": "9.9.9"}` → `same`. The
  branch closes the neighbouring case (a null `recipe_id` on a receipt that was *not*
  migrated now returns `inconsistent` through `recipe_id_missing`; the base returned `same`),
  and makes `stac_fields` refuse the receipt-side twin (`recipe_id_on_migrated`), so the
  migrated half is what is left.
  - **Rule:** code-check.md "A guard that fails toward pass"

- **[severity: bug]** `src/stacs/receipt.py:1408` (`receipt_asset`) and `:1442`, `:1469`,
  `:1490` (`item_problems`) — `asset.get("roles") or []` and `item.get("stac_extensions") or
  []` keep a truthy non-list, and `in` on a number or a bool raises `TypeError: argument of
  type 'int' is not iterable`. Reproduced: `item_problems` on an item whose asset has
  `"roles": 7`, or whose `stac_extensions` is `7` while it carries a `processing:` field;
  `receipt_href` on the same asset. `validate.py:217` calls `item_problems` and
  `register.py:839` calls `receipt_href`, both outside any handler, so one such published
  item ends `audit --require-receipt` or `verify` with a traceback. A test docstring in this
  diff states `item_problems` "must be total".
  - **Rule:** none (candidate: `x.get(k) or []` keeps a truthy non-container, the list twin
    of the `_mapping` docstring's `node.get(key) or {}`)

## Claims checked and holding

Each measured against the vendored `stac.json` (142 cases) or the code, on `1ad7de6`.

| claim | where | measured |
|---|---|---|
| `stac_fields` agreed on 87 of 142 before, 142 now | NEWS, research | base module run over the vectors: 87 agree, 55 mapped where crate refuses, 0 other; head: suite green |
| the 55 by code: 17, 13, 6, 4, 4 and "11 across ten other codes" | research | `block_not_object` 17, `time_not_utc` 13, `receipt_version_unknown` 6, `recipe_id_missing` 4, `version_not_string` 4; the rest 11 over 10 codes |
| 17 accepted, 125 refused, 17 codes | research, tests | 17 / 125 / 17 |
| of the 125 refused, 28 pass `validate`: 17 argument, 8 impossible instant, 3 trailing newline | research, NEWS "two kinds" | 28: 17 / 8 / 3. Read against the form schema too: its other constraints (`const`, `minLength`, `minimum`, the migrated `if`) leave no third kind |
| "two years and two month lengths" | research, test docstring | years 2024 and 2026; November and February |
| every case passes `assets` as an object with non-empty keys and hrefs | research | 142 dicts, no empty key or href, no non-string href |
| every migrated vector holds a string in `migrated_from` | test docstring | 2 cases, both strings |
| seven `STAC item` rows | research | 7 in `mapping/v1.1.0/mapping.csv` |
| crate computes the calendar by arithmetic; an independent Python reading exists | test docstrings | `R/crt_receipt_stac.R` and `data-raw/receipt_vectors_crosscheck.py` at `v0.16.0` |
| the patterns are used with `fullmatch` only | comment at `receipt.py:1102` | three uses, all `fullmatch`; no other module names them |
| issue numbers cited | NEWS, research, vendored READMEs | stacs#15, stacs#16, crate#43, #58, #59, #60, #65 each resolve to a title about this work |
| README link added inside the `receipts` markers is absolute and resolves | README | `crate/tree/main/inst/extdata/receipt/mapping` lists `v1.0.0`, `v1.1.0` |
| `pyproject.toml` version untouched, NEWS under `## Unreleased` | convention | yes |

Mutations run in the worktree copy, each restored and the tree confirmed clean: removing the
non-object-part arm reddens `test_a_part_an_asset_names_that_is_not_an_object_is_never_same`;
letting the mapping's refusal escape `item_verdict` reddens
`test_a_receipt_the_mapping_refuses_is_inconsistent_never_same`. The two `RECEIPT_VERSION`
swaps are in the third finding.

## Not checked

- crate's R was read (`crt_receipt_stac.R` at `v0.16.0`), not run: agreement with it rests on
  the vectors.
- The `vendor` mode of the script (it writes); only `check` was run.
- The `docs.yml` deploy job, and CI itself.
