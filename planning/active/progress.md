# Progress — register --dryrun skips the API and ssh probes; say so or probe (#5)

## Session 2026-10-11

- Plan-mode exploration — phases approved by user (option: probe in dryrun)
- Created branch `5-register-dryrun-skips-the-api-and-ssh-pr` off main
- Scaffolded PWF baseline from issue #5 with approved phases
- Next: start Phase 1

- Phases 1-3: new dryrun tests written first (12 failing), probes moved ahead of every
  dryrun return, offline dryrun tests given the stub API, CLI probe stubbed. Plan review
  folded in (findings.md). Mutation table in findings.md. Full suite 498 passed.
- Phase 4: README dryrun paragraph, --dryrun help, NEWS Unreleased. mkdocs --strict clean.
