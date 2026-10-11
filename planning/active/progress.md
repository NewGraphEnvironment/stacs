# Progress — Report the database each load reached, and refuse a mismatch (#6)

## Session 2026-10-11

- Plan-mode exploration — phases approved by user
- Created branch `6-report-the-database-each-load-reached` off main
- Scaffolded PWF baseline from issue #6 with approved phases
- Next: start Phase 1
- Phase 1: six tests. Five fail before the fix; the first reproduces the issue exactly
  (API in sync, launcher reaching `otherdb`, run reports DONE). The two mark cases
  naming another or an extra word already pass under today's exact-line check and stay
  as guards against a prefix match.
- Phase 2: `remote_script` asks `current_database()` through the launcher before the
  load and refuses a mismatch on the host; the mark carries the name; `_send` requires
  `STACS_LOADED <n> <kind> <db>` exactly. 479 passed. Mutation table in findings.md.
- Phase 3: NEWS Unreleased, README sentence (inside the configure snippet, no link), CLAUDE.md mark. Strict mkdocs build clean.
- /code-check branch: three rounds; R1 and R2 fixes committed (2ae77aa, 1db271c); R3 clean by enumeration. 486 passed.
