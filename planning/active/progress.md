# Progress — A non-list roles or stac_extensions raises TypeError, and item_verdict misses a field the item publishes that its receipt does not (#17)

## Session 2026-11-15

- Plan-mode exploration — phases approved by user; two gate decisions (migrated items refused with their own sentence; hrefs resolved against the item URL)
- Created branch `17-a-non-list-roles-or-stac-extensions-rais` off origin/main
- Scaffolded PWF baseline from issue #17 with approved phases
- Next: start Phase 1
- Phase 1: `_list` helper; `roles` and `stac_extensions` read through it; `item_problems` reports a non-list `roles` on any asset; `verify._search_pages` refuses a non-object link, a non-object next body and a non-string token. Mutation-checked: each of the six guards reverted makes its test fail. Suite 920 passed.
- Plan review (Plan agent) returned during Phase 2: written to `review-plan.md`, folded into Phases 2-5 as `(review)` checkboxes. One plan correction: `verify` will also mark a published item with no recipe identity `inconsistent` under require_receipt, so it agrees with the audit and the gate decision (Phase 4).
- Phase 2: reverse property check over `_MIRRORED_PROPERTIES`; every non-object asset entry (null included) on either side is malformed; sizes compared through `_whole`. Mutation-checked: three guards each fail their tests when reverted. Suite 943 passed before the last test was added; test_receipt.py 300 passed.
- Phase 3: `_relative_href` / `_part_key` / `_inside`; `item_verdict(item_url=)`, passed by `register._receipt_verdicts`. An asset with file fields and no href is a disagreement, which changed one older test (null href used to read `same`). Mutation-checked: 11 guards; two first survived (a relative-query guard that was redundant, removed; normpath-before-prefix, which needed an `/c/../c/` case) and are now caught.
- Phase 4: `receipt.NO_RECIPE_IDENTITY`, one sentence for the audit (`bad_receipt`, told apart by the linked receipt asset) and for `verify` (`_receipt_verdicts` marks the item `inconsistent` before fetching its receipt). The existing no-receipt audit test's fixture linked a receipt asset; it now links none, matching what it describes. Mutation-checked: three guards. Suite 982 passed. README sentence pending, with Phase 5.
