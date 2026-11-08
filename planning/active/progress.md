# Progress — Read, write and compare provenance receipts for catalogue items (#12)

## Session 2026-11-08

- Synced `CLAUDE.md` with soul's published conventions (`17e4e9f` on `main`); `provenance.md`
  now applies to this repo and joined the appendix.
- Plan-mode exploration: read `verify.py`'s canonical form, `validate.py`'s audit, the CLI,
  `register.py`'s verify path, the test harness and docs wiring; read crate's receipt contract
  from GitHub at tag `v0.12.0` (the local checkout is at v0.11.0 and has none of it).
- Probe: ran crate's own `data-raw/receipt_vectors_crosscheck.py` against the v1.0.0 vectors in
  this repo's environment — 2,637 + 10 + 7 + 13 cases, **0 mismatches**. The hashing core needs
  no library work; the open half is `compare.json`, validation, the STAC mapping and the
  `audit` / `verify` integration.
- Probe: both published schemas answer 200, are draft-07, and carry no `$ref` with sibling
  keywords, so Python's `jsonschema` and R's ajv agree.
- Gate decisions approved by the owner: `verify` compares against the item's **mirrored identity
  fields** (stateless, no stored baseline); all seven Proposed items land in this PR.
- Created branch `12-read-write-and-compare-provenance-receip` off `origin/main` at `17e4e9f`.
- Scaffolded the PWF baseline with the approved phases.
- Next: start Phase 1.
