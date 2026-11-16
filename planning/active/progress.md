# Progress — verify follows a published item's receipt href to any scheme, file:// included (#19)

## Session 2026-11-16

- Plan-mode exploration — phases approved by user (rule: scheme family, owner's choice)
- Created branch `19-verify-follows-a-published-item-s-receip` off origin/main
- Scaffolded PWF baseline from issue #19 with approved phases
- Phase 1: tests red for the defect (receipt read as `rebuilt`; `all` upserted a local item)
- Phase 2: `catalogue.resolve_href`, used at both sites. Mutation check in a scratch copy:
  item-link site reverted to `urljoin` fails 3 tests (all/drift/verify), receipt site fails 1;
  restored, 5 pass. The `drift` case was red pre-fix for a harness reason (no transport),
  fixed in the test, and re-proved by the mutation.
- Phase 3: NEWS `## Unreleased` Behaviour change entry; README's refusal list and
  "What it assumes" gain the rule (the README did describe item-link resolution).
  `mkdocs build --strict` clean, tests/test_docs.py green.
- Next: Plan review findings, `/code-check branch`, archive, PR
