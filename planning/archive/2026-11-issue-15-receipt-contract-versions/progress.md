# Progress — crate's receipt register and mapping are versioned, and mapping v1.1.0 pins the STAC mapping: re-vendor, pin by version, run stac.json (#15)

## Session 2026-11-15

- Plan-mode exploration — phases approved by user
- Created branch `15-crate-s-receipt-register-and-mapping-are` off origin/main
- Scaffolded PWF baseline from issue #15 with approved phases
- Plan review spawned in the background at 2026-11-15T21:53Z (Plan agent, findings to
  `planning/active/review-plan.md` when they land)
- Phase 1 done: re-vendored at crate `v0.16.0`, register and mapping at versioned paths,
  `check` compares four frozen URLs, stray-file and version-pin guards with a mutation table
  in `findings.md`. Plan correction: no URL constants in `receipt.py` (see `task_plan.md`)
- Phase 2 done: `stac_fields` executes mapping v1.1.0, 142 of 142 `stac.json` cases by code;
  `ReceiptError.code`; strict patterns and a real-instant check shared with the audit
- Plan review landed (`review-plan.md`, 20 findings): F1 already met; F9 and F10 changed
  `item_verdict` (a refused receipt and a non-object part are `inconsistent`, never `same`);
  F5 goes to crate as a gap in its published code table
- Phase 3 done: `Comparison.register` and `Comparison.overrides`, with a mutation table
- Phase 4 done: NEWS, the README receipts section, `research/receipt_parity.md` revised in
  place; filed #16 (trailing newline in table cells and `validate`) and crate#65 (two refusal
  codes outside crate's table)
- Code-check round 1: 4 findings against the diff, all fixed; 2 that predate it filed as #17
- Code-check round 2: 1 finding, inside round 1's fix (a NEWS sentence wider than the code);
  fixed, and the enumeration over all 142 vector cases and every quantified claim is in
  `findings.md`
- Code-check round 3: 1 finding, the same NEWS sentence; the claim is replaced by one that is
  measured (75 of 75) and asserted. The loop ended on the enumeration in `findings.md`
- Archived to `planning/archive/2026-11-issue-15-receipt-contract-versions/`; PR next
