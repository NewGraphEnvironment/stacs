# Code-check round 3: branch `15-crate-s-receipt-register-and-mapping-are` at `1610a1e`

Base `e674cda`, three-dot diff, `planning/` and the vendored `stac.json` excluded from review
(its structure was read and measured). Reviewed 2026-11-15 from a detached worktree of
`1610a1e`; nothing in the checkout was edited but this file, and the worktree is removed
(`git worktree list` shows the checkout alone, `git status` clean).

## Checklist read

- `code-check-python.md`: in full (8 headings).
- `code-check.md`: the prose of all 14 H3 under `## Mechanisms` (table rows skipped), and 3
  standalone rules in full: "Documentation Staleness", "An ordered dispatch makes severity
  ordering load-bearing, and nothing enforces it" (its table rows skipped), "An assertion that
  matches an interpolated value cannot see the claim around it". Not read beyond the index
  line: 21 (11 standalone, 6 Security, 4 Spreadsheets and PDFs).
- `code-check-shell.md`: 14 of 71 headings, evidence blocks dropped and each cut at 1,500
  characters: "Reading a file line-by-line drops the last line without a trailing newline",
  "Empty arrays under `set -u` on bash 3.2", "Heredoc precedence in pipelines", "A heredoc
  whose body contains its own delimiter ends early, and the rest runs as shell", "`mktemp`
  template needs enough X's, and a failed `mktemp` leaves an empty var", "A `curl` in a
  parallel fan-out needs `--max-time`", "A verification command can be shadowed by a shell
  function or alias", "A second `trap … EXIT` replaces the first", "`grep -c` prints the count
  AND exits 1 when it is zero", "`curl -o` without `-L` saves the redirect page as the
  download", "A failed `cd` lets every later command run in the directory you were already
  in", "macOS `/bin/bash` 3.2 quote-matches a heredoc inside `$( )`", "Put cleanup on the EXIT
  trap, not RETURN", "`a && b || c` runs `c` when any step before the `||` fails". Not read
  beyond the index line: 57. The script's diff is data and one message.
- `code-check-r.md`: index lines only, 0 sections (the diff holds no R).

## Verdict

Not clean, by one low-severity finding against the diff, and it is again inside the sentence
the previous round rewrote. The code holds: I found no input for which the head returns
agreement over a receipt the mapping refuses, and no new exception. The enumeration test is
not vacuous and does what its name says for the 123 cases it executes.

The author's reading of the mechanism is right about the verdict and one link short about
the prose. On the `verify` path the question "does this receipt map to item fields?" is
answered by a chain of three readers, not two, and `NEWS.md` describes which of them answers
by naming two.

## Findings

- **[severity: fragile]** `NEWS.md:34-38`, with `planning/active/findings.md:251` marking it
  as holding — "The note carries the mapping's code, except where `recipe`, `context`,
  `result` or `result.parts` is present and neither an object nor null" is false on `verify`
  for a second family the sentence does not name. `register._receipt_verdicts` reads the
  fetched receipt with `receipt.read` (`src/stacs/register.py:884`) before it calls
  `item_verdict`, and `read` refuses a receipt whose `output` is not an object or whose
  `output.receipt_version` is not `1.0.0` (`src/stacs/receipt.py:630-634`). The mapping
  refuses the same receipts as `block_not_object` and `receipt_version_unknown`, and the
  note `verify` prints is `read`'s, with no code.
  - Reproduced through `register.run(..., "verify")` with the suite's own harness
    (`_item_with_receipt`, `_receipt_run`), one changed member per receipt:
    `receipt_version: "2.0.0"`, `receipt_version` missing, `receipt_version: null`,
    `output: "x"`, `output: null`, `output` absent. Each: exit 1, `1 inconsistent`, note
    `its receipt (...) could not be read as a receipt: ... is receipt version None; this
    reads '1.0.0'`, and no `(receipt_version_unknown)` or `(block_not_object)`. Controls in
    the same run: `recipe: null` and month 13 each carry their code.
  - Counted over the vectors, each receipt written to a file and taken in `verify`'s order
    (`read`, then `item_verdict` on what `read` returned): of the 106 cases the mapping
    refuses for the receipt, the note carries the case's code for **75**, the node check
    answers for **16** (the exception NEWS names), and `read` answers for **15** (not named:
    all 6 `receipt_version_unknown`, 5 `block_not_object` for `output`, 4 for a receipt that
    is not an object, which `fetch_bodies` refuses even earlier as "body is not a JSON
    object"). So `receipt_version_unknown` never reaches a `verify` note at all.
  - Two more arms answer first under a second, independent fault, also unnamed: the digest
    check (`receipt.py:1631-1638`; measured, month 13 plus a receipt asset claiming another
    digest gives the digest note and no code) and the four item nodes of `VERDICT_NODES`
    (read, not run).
  - The verdict is `inconsistent` on every one of these, so nothing is reported as
    agreement. What is wrong is the sentence: a reader who greps the note for the mapping's
    code misses 31 of the 106, and NEWS tells them to expect 16.
  - The sentence has now been wider than the code in three consecutive rounds, each time by
    one link of the same chain. Listing exceptions is what keeps failing; "the note carries
    the mapping's code where the mapping is the check that refuses; `receipt.read` and the
    node check answer first for a receipt they cannot read" survives the next link.
  - **Rule:** code-check.md "A guard's scope, escape hatches, and remedies"

### Predates the branch (not counted against the diff)

Both reproduce in lines the diff does not touch. They are here because the round asked where
else the mechanism reaches.

- **[severity: fragile]** `src/stacs/receipt.py:1557` and `:1525` — the list of mirrored
  fields `_mirrored` compares between the two sides is a second hand-kept copy of what
  `stac_fields` publishes, and three of its five members are held by no test. Removing
  `processing:software`, removing `processing:datetime`, and removing `file:size` from
  `_RESULT_ASSET_FIELDS` each left the suite at 896 passed. Each mutation changes behaviour:
  on the head a served item that differs from the published one only in that field reads
  `rebuilt`, and with the member gone it would read `same`. The two lists agree today
  (measured over the 17 accept cases: `stac_fields` publishes exactly
  `receipt:recipe_id`, `processing:datetime`, `processing:software`, `file:checksum`,
  `file:size`). This is the same shape round 1 closed inside `item_verdict`, one function
  down: a field the mapping gains would be compared with the receipt and not between the
  sides.
  - **Rule:** code-check.md "Restore the bug and prove the guard fires"
- **[severity: fragile]** `src/stacs/receipt.py:1448-1450` (`item_problems`) and
  `src/stacs/validate.py:218` against `stac_fields` — the two disagree about one of the 17
  accept cases. The mapping leaves `receipt:recipe_id` and the receipt extension out for a
  migrated receipt (`a migrated receipt: no receipt:recipe_id, never a null one`). An item
  built from exactly what `stac_fields` returns for that case, on crate's example item,
  gets two problems from `item_problems` (`properties has no receipt:recipe_id`; the field
  schema's `stac_extensions` rule), and `audit_items` files it under `missing_receipt`, the
  list its comment reserves for an item that carries no receipt yet. The other 16 accept
  cases come back with no problems. I did not run `audit` to its exit status. Not in
  issue 17's list.
  - **Rule:** none

## The questions this round asked

### Is the author's reading of the mechanism right and complete?

Right for the verdict. `item_verdict` now takes the receipt's item fields from one producer,
and the differential the previous round ran found no triple moving away from `inconsistent`.

Incomplete as a description of what is read. The fact "this receipt maps to item fields" has
these readers on the `verify` path, in the order they answer:

| reader | where | what it refuses | note carries the mapping's code |
|---|---|---|---|
| `fetch_bodies` | `catalogue.py:194`, called at `register.py:867` | a body that is not a JSON object | no |
| `receipt.read` | `register.py:884`, `receipt.py:616` | `output` not an object, `receipt_version` not `1.0.0` | no |
| `item_verdict`, receipt guard | `receipt.py:1594` | a receipt that is not an object (unreachable from `verify`) | yes, a literal copy of the code's name |
| `item_verdict`, node check | `receipt.py:1610-1629` | four receipt nodes and four item nodes, present and neither object nor null | no |
| `item_verdict`, digest check | `receipt.py:1631-1638` | a fetched receipt whose digest the item's asset contradicts | no |
| `stac_fields` | `receipt.py:1673` | everything the mapping refuses | yes |

Every reader says `inconsistent`, which is why the verdict is safe. Anything said about which
reader answers is derived by hand from whichever link was being edited, and that is the one
mechanism behind both of the author's two: in the code it was a second copy of the asset
rows, in the prose it is a second copy of the chain. `read` and the mapping agree on accept
or refuse for all 142 vectors (127 pass both, 15 are refused by both: 6 version, 5 `output`,
4 non-object receipt), so this pair differs only in the note.

The receipt half of the node check is now redundant with `stac_fields` (`_block` refuses the
same four nodes), and it is pinned as a separate route: dropping the four receipt nodes from
the check turns `test_a_malformed_receipt_node_is_inconsistent_not_same` red (10 cases),
because that test asserts the node's name in `fields`. That is the accepted tradeoff; it is
also why the chain has to be described rather than a single producer.

### Can the enumeration test pass while the property it names is false?

Not within the cases it executes. What I checked:

- **Vacuity.** The three arm counts are asserted (106, 17, 19) and sum to the pinned 142.
  Narrowing the hand-off so a part is asked about only when the asset carries a file field
  (round 1's defect) turns it red, with `test_a_part_the_mapping_refuses_is_never_same`.
- **Does the item exercise the asset rows?** Yes in the refused arm: all 11
  `part_sha256_not_sha256` and all 6 `bytes_not_whole` cases come back `inconsistent` with
  the case's own code in the note, which can only happen if the item's asset reached
  `stac_fields` as naming that part, and the items there carry no file field at all. In the
  accept arm 5 of the 17 cases carry an asset with expected file fields, 15 carry
  `processing:software` and 1 is migrated. The accept arm proves only that the function does
  not refuse everything: published and served are one object, so it cannot see whether a
  field is compared. Other tests hold that (round 2's mutation rows).
- **The population it does not reach.**
  - The 19 cases of the argument arm are counted and never run: the loop `continue`s before
    `item_verdict` is called (`tests/test_receipt_vectors.py:511-513`). For 15 that is
    exact, `item_verdict` passes no `receipt_asset` or digest. The other 4 are
    `href_not_a_part`, and three of those are receipt states, not arguments (`result
    absent`, `result.parts absent`, `result.parts[walks.csv] absent`). Measured: all four
    read `same`, and still `same` when the asset carries a `file:checksum` and `file:size`
    that no part vouches for. That is the family issue 17 holds, so the behaviour is known;
    the point here is that "nothing sits above its source of truth" is a statement about 123
    executed cases, and the 4 where the two readings differ by design are the ones no
    assertion touches.
  - An asset whose href is not spelled as the part's key (issue 17).
  - The `verify` ordering above: the test calls `item_verdict` directly, so it cannot see
    that `read` answers first for 15 of its 106.
  - A receipt that is not an object is in the population (4 cases) and is covered.

### Did the claims table miss a claim, or mark a false one as holding?

One row is marked as holding and is false: the finding above. The other rows I re-walked hold.

Quantified claims the branch added that the table does not list, each executed:

| claim | where | verdict |
|---|---|---|
| "Used with `fullmatch` only, through the three predicates below" | `receipt.py:1102` | holds: the three patterns appear at `:1126`, `:1130`, `:1148` and nowhere else in `src/` |
| "Two refusals carry no code" | `stac_fields` docstring | holds, by parsing: 69 `ReceiptError(...)` calls, none with a second positional argument; 16 literal codes on them plus `bytes_not_whole` handed to `_whole` are the 17 of `STAC_REFUSALS`; the two uncoded raises in `stac_fields` are the two named |
| "Every `stac.json` case passes `assets` as an object with non-empty keys and hrefs" | parity note | holds: 142 objects, no empty key, no empty or non-string href |
| "`stac.json` has two years and two month lengths" | parity note, a test docstring | holds: 2024 and 2026; February and November |
| "Every vector that is migrated holds a string there" | test docstring | holds: 2 cases, both strings |
| "an empty key is published and an empty href is refused as naming no part" | parity note | holds: key `""` published, href `""` gives `href_not_a_part` |
| "Of the receipts `validate` passes, the mapping refuses two kinds" | NEWS | no counter-example in 27 targeted changes to crate's worked-case receipt, chosen to add what replacing a value cannot (a repository with an empty name, an empty `version`, `migrated_from: null`, digits outside ASCII in each pattern, a missing `bytes`) and leaving out the two known kinds: none of the 27 passes `validate` and is refused |
| "17 are refused for an argument and not the receipt" | parity note | holds: 19 argument cases, of which `result absent` and `result.parts absent` fail `validate` |

### Does the mechanism reach another pair in the diff?

| pair | agree today | held by a test | |
|---|---|---|---|
| `receipt.read` and `stac_fields`' version check | yes, all 142 | each side separately | the order is the finding |
| `_mirrored` and `stac_fields` | yes | no, 3 of 5 members | predates; above |
| `item_problems` and `stac_fields` | 16 of 17 accept cases | no | predates; above |
| `register()` and `compare` against `REGISTER_VERSION` | yes | yes | one constant read in two places, the directory at first load and the name at each `compare`; the cache key carries no version, which cannot matter while the constant is fixed for a process, and the `monkeypatch` test moves them apart |
| the script's `FILES` and `URLS` against the tests | yes | yes | the tests parse the blocks out of the script; `_frozen() == want` pins both columns of all four rows to the module's constants; source and destination version directories match on every row |
| `STAC_REFUSALS` against the code | yes | yes | the test's text scan and a parse give the same 17 |
| `stac_fields` against crate's two readings | yes, by reading | by the 142 vectors | crate's `data-raw/receipt_vectors_crosscheck.py` and `R/crt_receipt_stac.R` at `v0.16.0`: the same checks in the same order, the same patterns and calendar arithmetic; crate's Python publishes `file:size` as the float it read and this module as an `int`, equal as canonical JSON |
| docstrings and comments against the code beside them | yes | | walked: the module docstring, the constants' comment, `ReceiptError`, `Comparison`, the pattern comment, `STAC_REFUSALS`, `_utc_instant`, `_whole`, `_block`, `stac_fields`, `ItemVerdict`, the three comments in `item_verdict`, `register.py:901-907`, the vendor script's header, `FILES` and `URLS` comments and success line, and the workflow comment |

## Mutations

Run in the worktree copy with bytecode caching off, the file restored after each and the tree
confirmed clean at the end. Baseline on the head: 896 passed.

| mutation | result |
|---|---|
| `_mirrored` drops `processing:software` | green, 896 |
| `_mirrored` drops `processing:datetime` | green, 896 |
| `_RESULT_ASSET_FIELDS` drops `file:size` | green, 896 |
| a part handed to `stac_fields` only when the asset carries a file field | red, 5: the enumeration test and `test_a_part_the_mapping_refuses_is_never_same` |
| node check never returns | red, 23 |
| node check without its four receipt nodes | red, 10: `test_a_malformed_receipt_node_is_inconsistent_not_same` |
| `read` accepts any version | red, 1: `test_read_refuses_another_receipt_version` |
| the literal code name in `item_verdict`'s non-object note misspelled | red, 5: `test_a_receipt_that_is_not_an_object_is_inconsistent_not_a_crash` |

## Not checked

- What rounds 1 and 2 verified was not repeated: the suite on 3.11, `check` under bash 3.2,
  the strict docs build, the wheel, the vector counts, the issue numbers, the differential
  fuzz, their mutation rows.
- crate's R and crate's Python crosscheck were read at `v0.16.0`, not run.
- `audit` was not run on the migrated item; `item_problems` was, and `validate.py:218` was read.
- The four item nodes answering before the mapping under a second fault were read, not run.
