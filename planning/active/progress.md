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
- Next: Phase 2
