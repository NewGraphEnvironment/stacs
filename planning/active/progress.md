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
- Phase 2: `remote_script` kind `queryables` (`load_queryables FILE
  '--collection_ids=[<repr>]'`, one shell word); `load`'s send path factored into
  `_send`, shared by `load_queryables`. The real `fire` (dev dependency) parses the
  generated words to `[id]` for 7 ids incl. quotes, backslash, non-ASCII, `[x]`, `1`;
  mutation (bare id) fails all 7.
- Phase 3: register/verify integration, other-collections guard; plan review folded in
  (dispositions in findings.md); 21 mutations caught. Issue #8 body: load order and the
  served endpoint corrected.
- Phase 4: README configure/use/assumes, NEWS Unreleased, docs/reference/queryables.md +
  nav; `mkdocs build --strict` clean (no WARNING lines). 460 tests pass.
- Next: /code-check branch, archive, PR.
