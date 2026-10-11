# Progress — Declare and load collection queryables from stacs.toml (#8)

## Session 2026-10-11

- Plan-mode exploration — phases approved by user; scope decided at the gate: own
  collection only, no collection-ids key
- Created branch `8-declare-and-load-collection-queryables-f` off main
- Scaffolded PWF baseline from issue #8 with approved phases
- Next: start Phase 1
- Phase 1: research/pgstac_queryables.md from upstream source (pgstac v0.9.8, v0.10.0;
  stac-fastapi-pgstac filter.py); #8 body edited (own collection only);
  src/stacs/queryables.py with parse/document/digest/diff; `[queryables]` in the config
  and on Target. Both guards mutation-checked (removed → tests fail).
