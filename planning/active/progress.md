# Progress — stacs: package the pgstac registration and verification layer (#1)

## Session 2026-10-06

- Plan-mode exploration — phases approved by user (transport: SSH stream; config:
  `stacs.toml` + flags; scope: PR ends at parity, adoption filed as issues)
- Created branch `1-stacs-package-the-pgstac-registration-an` off main
- Scaffolded PWF baseline from issue #1 with approved phases
- Next: start Phase 1
- Plan review (Plan agent) folded into task_plan.md; record in `review-plan.md`
- Phase 1: `stacs.verify`, `stacs.catalogue` extracted; `api` required; four code-check
  rounds (`review-p1-round{1..4}.md`), the fourth finding a defect inside round 3's fix,
  ended by enumerating every absence-producing point (findings.md). 101 tests.
- Phase 2: `body_digest` over RFC 8785 (`canonical_json`, `DigestError`); 3 code-check rounds (`review-p2-round{1..3}.md`). 118 tests.
- Phase 3: `stacs.validate` (audit, pystac validation of the raw body); suite-wide loopback-only network guard in conftest.py; 2 code-check rounds ended by enumeration (`review-p3-round{1,2}.md`). 187 tests.
- Phase 6 reference run started in the background (stac_dem_bc `register_manifest.py`, read-only).
- Phase 4: `stacs.register` (Transport, Target, load, run); harness runs the remote script for real against a fake pypgstac; 2 code-check rounds + 1 self-found defect, ended by enumeration (`review-p4-round{1,2}.md`). 256 tests.
- Phase 6 reference + equivalence runs complete (findings to be recorded in Phase 6).
- Phase 5: `stacs` CLI + `stacs.toml`, README, NEWS, research/pgstac_round_trip.md; 2 code-check rounds ended by enumeration (`review-p5-round{1,2}.md`). 319 tests.
