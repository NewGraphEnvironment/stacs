## Outcome

`stacs` now fetches an href a published body supplies only within the scheme family of the
URL it is resolved against, through the new `catalogue.resolve_href`: http and https are one
family, and `file://` is read only from a `file://` base (#19). The issue named one site,
the receipt href `verify` reads. Exploration found a larger one: an item link in
`collection.json` was read in every mode that fetched it, and upserted into pgstac by `all`,
`drift` or an `ids` run naming it, so a catalogue served over https could put a file from
the machine running stacs into the API. A refused item link now refuses the run before any
item is fetched, a dryrun included; a refused receipt marks its item `inconsistent`. At the
gate the owner chose the scheme family over also comparing hosts, so a catalogue may still
link items or receipts on another host, an internal http one included. What the review
rounds kept teaching was not about the code, which held from the first round: every
sentence about how far the old defect reached was written from where the new guard sits
(before the mode branch) instead of from where the harm happened (after each mode picked its
subset), so each round found the next mode or condition the prose had left out. The durable
version is [`research/href_matching.md`](../../../research/href_matching.md), section "Which
hrefs `stacs` fetches".

## Measurement

- **Reproduced before the fix:** an item over http linking a valid local receipt read
  `rebuilt` (the file was read and agreed); `all` with a `file://` item link upserted the
  local item `a9`.
- **Mutation, each guard reverted to `urljoin`:** the item-link site fails all 5 refusal
  cases (`all`, `ids`, `drift`, `verify`, `all` dryrun); the receipt site fails the receipt
  test with `2 rebuilt`. Per-mode reads under the mutation: `all`, `drift`, `verify` read
  the local file; an `ids` run not naming it and a dryrun do not, and an `ids` run naming it
  reaches the load.
- **A wrong turn:** the plan said `urljoin` lowercases an absolute href's scheme. A probe
  showed it returns `FILE:///x` as written; only a literal `file://` prefix was ever read,
  and the guard reads `urlsplit`'s scheme, a superset.
- **A harness red:** the `drift` refusal case first failed for lacking a transport, not for
  the defect; fixed in the test and re-proved by the mutation.
- **Review:** a plan review and three code-check rounds, 4 reviewer spawns. Findings 1, 1, 2,
  all in prose; round 3's docstring finding sat in the sentence round 2's fix had edited, so
  the loop ended on round 3's enumeration of 33 scoped claims, each checked against the
  code (31 held, 2 fixed, 1 tightened), plus a measurement of the one new claim.
- **Suite:** 1075 collected and passed, 1046 at the base (38a45a3): 29 added, 21
  `resolve_href` unit cases, 7 run-level cases (the refusal test parametrised over 5) and
  `resolve_href`'s doctest.

Closed by: PR (to be opened from branch `19-verify-follows-a-published-item-s-receip`)
