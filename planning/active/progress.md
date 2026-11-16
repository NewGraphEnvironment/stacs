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
- Plan review (review-plan.md): no blocker; gaps folded in — `ids` and `dryrun` refusal
  cases, README reflow, test renamed to what it checks, `_read_url` comment names the
  requests-has-no-file-adapter assumption; plan's urljoin claim corrected.
- Code-check round 1 (review-round1.md): no code defect; README/NEWS overclaimed the receipt
  verdict (the axis runs only under `require_receipt`, on items in `changed`) — reworded.
  Mutation: item-link site reverted fails all 5 refusal cases incl. `ids` and dryrun.
- Code-check round 2 (review-round2.md): round 1's fix confirmed true; one finding in the
  original text, not inside a fix — `drift` loads `missing | changed`, so it upserted a local
  item too (measured by the reviewer under mutation). NEWS, the register.py comment and the
  test docstring now name `all`, `ids` or `drift`.
- Code-check round 3 (review-round3.md): mechanism named — each scope sentence was written
  from where the guard sits (before the mode branch) rather than from where the old harm
  happened (after each mode picked its subset). Enumerated 33 scoped claims in the diff's
  prose: 31 held; fixed the test docstring ("read in every mode", false for an `ids` not
  naming it and for dryrun — the sentence round 2's fix edited, so counted inside a fix) and
  the README refusal list (http/https count as one); tightened NEWS "before anything is
  fetched" to "before any item is fetched". Measured the one new claim no round had: under
  mutation an `ids` run naming the local item reaches the load (fails only at read-back).
  Loop ended on the enumeration.
- Next: archive, PR
