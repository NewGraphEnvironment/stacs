# Progress — A non-list roles or stac_extensions raises TypeError, and item_verdict misses a field the item publishes that its receipt does not (#17)

## Session 2026-11-15

- Plan-mode exploration — phases approved by user; two gate decisions (migrated items refused with their own sentence; hrefs resolved against the item URL)
- Created branch `17-a-non-list-roles-or-stac-extensions-rais` off origin/main
- Scaffolded PWF baseline from issue #17 with approved phases
- Next: start Phase 1
- Phase 1: `_list` helper; `roles` and `stac_extensions` read through it; `item_problems` reports a non-list `roles` on any asset; `verify._search_pages` refuses a non-object link, a non-object next body and a non-string token. Mutation-checked: each of the six guards reverted makes its test fail. Suite 920 passed.
