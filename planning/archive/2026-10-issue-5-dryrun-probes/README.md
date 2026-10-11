## Outcome

`--dryrun` used to return before the read-only API and ssh probes, so a green dryrun was
read by two consumers as a connectivity check that had never run. Chosen at the plan gate
over a docs-only fix: the probes now run before every dryrun return, in `register` (all,
ids, drift: API and host) and in `load`/`load_queryables` (host), and the dryrun says what
it reached. A dryrun now exits 1 when they do not answer, which NEWS marks as a behaviour
change. The README states per command where a dryrun stops, and that none runs the
script on the host (env file, pypgstac, database check), with the smallest real load for
that. What was learned: describing a dryrun as "the run minus the write" was wrong for
every command in a different way, and three review rounds each found a sentence still
making that claim. The loop ended by enumerating every dryrun claim on the branch
(findings.md), not by a quiet round.

Closed by: PR for branch `5-register-dryrun-skips-the-api-and-ssh-pr`
