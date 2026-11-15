# #15 — crate's receipt register and mapping are versioned: re-vendor, pin by version, run `stac.json`

## Outcome

crate versioned its receipt register and mapping apart from the receipt form, and published
mapping v1.1.0 with `stac.json`, 142 cases that pin how a receipt becomes an item's fields.
stacs now vendors each part at its own version (register v1.0.0, mapping v1.1.0, from crate
tag `v0.16.0`), its CI check compares the register and the mapping with the versioned URLs
crate serves, `stac_fields` executes the mapping and refuses with crate's code, and a
`Comparison` names the register version it read and the actions an override changed. The
durable verdict is [`research/receipt_parity.md`](../../../research/receipt_parity.md),
revised in place.

Three things were learned that the plan did not hold. **The plan's URL constants could not
land:** a crate URL in `src/` that is not a schema trips the deployment-name guard, and
nothing reads one at run time, so the served URLs live in the vendor script and a test ties
each to its version constant. **`item_verdict` and `stac_fields` read one receipt
separately**, so every rule the mapping gained reached only one of them: the plan review and
each of three code-check rounds found `item_verdict` agreeing with, or crashing on, a receipt
the mapping refuses. It was fixed at the mechanism (`item_verdict` hands `stac_fields` the
item's assets that name a part and compares what comes back) and closed by a test that walks
all 142 cases. **A sentence about which check answers is derived by hand:** one NEWS sentence
listing where the note lacks the mapping's code was wrong in three consecutive rounds, the
last time in a table row this record had marked "holds". It was replaced by a claim that is
measured and asserted, not by a longer list.

Left open, each filed: a trailing newline passes the table-cell date patterns and
`receipt.validate` (#16); `item_verdict` compares an item with its receipt one way only, a
non-list `roles` raises `TypeError`, and a migrated receipt's item cannot pass
`--require-receipt` (#17); crate's R raises two refusal codes its table and vectors do not
hold (crate#65).

## Measurement

- **`stac.json` over `stac_fields`:** 87 of 142 before (55 receipts mapped where crate
  refuses: `block_not_object` 17, `time_not_utc` 13, `receipt_version_unknown` 6,
  `recipe_id_missing` 4, `version_not_string` 4, 11 across ten other codes), and 17 of 142 by
  code, since `ReceiptError` carried none. 142 of 142 by code after. That turned "the STAC
  mapping agrees with crate's example item" into a measurement over every path the mapping
  reads.
- **The same 142 through `item_verdict`:** 106 receipts the mapping refuses are all
  `inconsistent`, 17 it accepts are all `same`, 19 are refused for an argument `item_verdict`
  does not pass. In `verify`'s order, `receipt.read` first, the 106 are answered by
  `stac_fields` (75, each note carrying that case's code), the node check (16) and
  `receipt.read` (15).
- **What the form passes that the mapping refuses:** of the 125 refused receipts, 28 pass
  `receipt.validate`: 17 refused for an argument, 8 for an instant that does not exist, 3 for
  a value ending in a newline, which `jsonschema` admits because it reads `$` as Python does.
- **The vendored bytes:** `register.csv`, mapping v1.0.0 and `compare.json` at `v0.16.0` are
  byte-identical to what was vendored at `v0.12.0`; `check` reports 16 files matching the tag
  and 4 frozen URLs serving them. crate serves no URL for `compare.json` or `stac.json`.
- **Mutation tables** (in `findings.md`): 5 mutations for Phase 1, 29 guards of `stac_fields`
  and its patterns for Phase 2, 6 for Phase 3 and the plan review's two guards, and 13 across
  the three review rounds. Every one turned a named test or the `check` script red. One guard
  that predates the branch (`isinstance(size, bool)`) and three members of `_mirrored` were
  found unpinned by a reviewer's mutation and gained tests.
- **The suite:** 823 tests after Phase 1, 902 at the end, on Python 3.12; 852 on 3.11 after
  Phase 2, and 878 on both 3.12 and 3.11 by round 1's reviewer at its commit.
- **The review:** one plan review (20 findings, one a blocker already met) and three
  code-check rounds (4, 1 and 1 findings against the diff; what they found that predates it
  is in #17).
  Each round found a defect inside the previous fix, so the loop ended on the enumeration
  above, not a quiet round. Four reviewer agents in all.

## Evidence

`planning/archive/2026-11-issue-15-receipt-contract-versions/review-*.md`: the plan review and
the three rounds, each with its checklist-read record. The mutation drivers ran from a session
scratch directory and are not kept; their tables are in `findings.md`.

Closed by: the PR for #15.
