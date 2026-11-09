# #12 — Read, write and compare provenance receipts for catalogue items

## Outcome

`stacs.receipt` implements crate's provenance-receipt contract in Python, so the catalogues
can write receipts in the same shape as the R packages without putting R on their publish
path. Seven phases: the plain-JCS core (`canonical`, `recipe_id`, `table_fingerprint`),
crate's test vectors vendored at tag `v0.12.0` and re-checked against it in CI,
`read`/`write`/`validate`, `compare` driven by crate's register, the STAC identity fields with
`audit` refusing a bad one, a per-item verdict in `verify`, and the docs plus a parity record.
The durable verdict is [`research/receipt_parity.md`](../../../research/receipt_parity.md).

Two decisions shaped it. The receipt canonical form is **plain** RFC 8785, kept apart from
`verify.canonical_json`, which drops `links` and null members for pgstac's round trip and may
change shape because nothing stores a body digest — a `recipe_id` is published, so its bytes
are frozen by the receipt schema version. And `verify` reports its **own** four verdicts
rather than crate's three, because crate's `equivalent` is unreachable from the five identity
fields a served item mirrors.

## Measurement

**crate's own Python crosscheck already passed every hashing vector in this repo's environment
before any code was written** — 2,637 number spellings, 10 canonical-JSON cases, 7
`recipe_id`s, 13 table fingerprints, **0 mismatches**. That moved the work from "port the
hashing" to "implement the half crate's crosscheck does not": the 9 receipt comparisons,
schema validation, the STAC mapping, and the `audit`/`verify` integration.

All of it now passes through this package's own public API, plus:

- crate's two worked-case receipts, read and rewritten, are **byte identical** — 2835/2835 and
  2837/2837 bytes. The only oracle for the file format, and it also proves `recipe_id` agrees
  for a real receipt, since `write` recomputes it.
- crate's example STAC item passes `item_problems` with nothing wrong, and `stac_fields`
  reproduces its property names, extension list and multihash forms.
- 814 tests pass on 3.11 (the declared floor) and 3.12; a built wheel ships all five vendored
  contract files; `mkdocs build --strict` is clean.

Four measurements changed what got built:

| measured | changed |
|---|---|
| JCS writes `0.000001` and `1e-9` where `json.dumps` writes `1e-06` and `1e-09`, and crate's receipt carries both | `write` re-indents the canonical **text**, never re-serialises the object |
| `jsonschema` 4.26.0 accepts `4.0` for `{"type": "integer"}`, but `rfc8785.dumps(3.0) == rfc8785.dumps(3)` | the plan review's proposed whole-number guard was **dropped** — it could not have changed a byte or a hash |
| four of the five mirrored identity fields are `refuse` in crate's register and the fifth is `record` | `verify` got its own verdict ladder instead of crate's three |
| the duplicate-URL scan added in round 2b cost 2.6 s at 20,000 URLs — ~67 s before the first fetch on a 102,460-item catalogue | rewritten O(n): 0.005 s at 100,000 |

## What the reviews changed

The plan review and three `/code-check` rounds were not confirmations. Between them they
redesigned one phase and found **17 defects**, every one reproduced before it was touched and
none dismissed. The pattern that matters: **four were inside an earlier fix.**

| round | found | inside a previous fix? |
|---|---|---|
| plan review | crate's `equivalent` unreachable → Phase 6 redesigned; 2 holes in this branch's own vendoring guard | — |
| round 1 | 8: two guards failing toward pass, two producers for one fact, an unbounded single-pass fetch, a `TypeError` leak, two test guards over-claiming | — |
| after round 1 (enumeration) | 2: `compare` and `stac_fields` reading blocks as `doc.get(x) or {}` | yes |
| round 2b | 4: `_diff`'s **collection** arm had the identical hole round 1 closed in the **branch** arm (11 register patterns silent); duplicate receipt URLs making every sharing item `inconsistent`; an href used as a dict key; one round-1 regression assertion that could not fail | yes |
| round 3 | 5: round 2b's fix **still** incomplete (154 violations measured); `item_verdict` reporting `same` over a node it could not read — **with a test of mine pinning that wrong answer**; `ReceiptError` escaping to exit 2; the O(n²) scan; `receipts_*.txt` written when the axis never ran | yes |

### The mechanism, as round 3 finally named it

> "Not a mapping" and "has no members" are treated as the same fact — and whether that
> collapse is safe depends entirely on what the consumer does with "no members". Every defect
> sat in a consumer whose default for "no members" is **agreement**; every site the reviews
> cleared sits in one whose default is **refusal**.

That is why three rounds of type-safety fixes kept missing it: `_mapping` and `keys()` were
introduced to stop a *crash*, and they do that everywhere. They do not make a read **total**,
and totality only matters where the answer is "same".

### What ended the loop

Not a quiet round — three mechanical post-conditions, all in the suite:

1. `canonical(a_block) != canonical(b_block) ⟹ ≥1 reported difference`, parametrized over
   every path `_patterns(register())` names. Holds over 3,816 differing pairs and is
   mutation-verified against the pre-fix arm. Its carve-out is a number, not a wave-through:
   exactly the empty-vs-absent pair at each of the 11 collection patterns (22), matching
   crate's own walk, checked at crate's source.
2. `same ⟹ every node the verdict depended on was absent or a mapping`, enumerated from
   `receipt.VERDICT_NODES` so there is no second list to fall behind.
3. Every `_mapping`/`keys()` site classified by its **consumer's default** rather than by
   whether it raises — all eight agreement-default sites now refuse or are total.

## Evidence

`planning/archive/2026-11-issue-12-provenance-receipts/` — `review-plan.md`, `review-round1.md`,
`review-round2b.md`, `review-round3.md` (each with my probe and verdict per finding),
`review-enumeration.md` (including round 3's audit of that instrument), and
`enumerate_mechanisms.py`, which is re-runnable rather than a one-time reading. The vendored
vectors and their provenance are `tests/vectors/receipt/v1.0.0/` and
`src/stacs/data/receipt/SOURCE`.

## Wrong turns worth keeping

- **A commit message claimed three fixes that were not in the tree.** The script applying them
  aborted on a later needle; each file is written only once all its needles match, so that
  file's edits were discarded silently while the message asserted them. Caught because a new
  test asserted on a log line and the log still read the old way. Every later edit was
  verified present by grep *before* committing. A commit message is a claim about a tree, and
  nothing was checking it — the branch's own mechanism, in a new costume.
- **One commit shipped a red suite.** Phase 6's fixtures hand-wrote a `recipe_id` that `write`
  then recomputed, so the item claimed a recipe its receipt did not have — the code was right
  and the fixture lied. Amended before pushing; the accidental shape became a test.
- **The mutation check took three attempts to run honestly**: first the heredoc never applied
  the edit, then the mutant was present but the `-k` selection skipped the two tests it
  targets. Confirm the mutant is in the file, *and* that the selection contains the tests it
  should break.
- **My enumeration was too narrow in five ways**, including that its population could not see
  `_diff` at all — the function holding the two worst defects — and that one dismissal rested
  on a line number taken against the wrong commit. A hand-built enumeration is only as wide as
  the population its author imagined.
- My own CI ordering guard matched the bare word `pytest`, which is also the job's name, so it
  compared the step against the job header. Found by running the guard, not by reading it.

## Candidates for soul's conventions, not written

These generalise beyond this repo, so they are recorded here rather than appended to a
convention every repo loads — that is the owner's call:

- `code-check.md`, under an existing mechanism: *"not a mapping" and "has no members" are one
  fact; the collapse is safe only where the consumer's default is refusal.* Four defects over
  three rounds, each a fix of the last.
- `code-check.md`, "A fix lands in one of two callers that share a harness": the sibling-arm
  case, where the fix went to the arm the reviewer named and the arm two lines above it kept
  the defect.
- `code-check-python.md`: `jsonschema` accepts a whole float where the schema says `integer`,
  and `json.dumps` does not preserve JCS number spellings.
- An operations note: a commit message is a claim about a tree and nothing checks it; verify
  an edit landed before asserting it in the message.

## Owed

- [ ] Adoption issues in the catalogue repos, pinning the tag this ships in.

  The repos are stac_dem_bc, stac_airphoto_bc, stac_uav_bc, stac_orthophoto_bc,
  stac_floodplains_bc and stac_pointcloud_bc. #12 says each catalogue adopts receipts in its
  own issue, once this ships, so these are filed after the merge and the tag.

Closed by: PR to be opened on branch `12-read-write-and-compare-provenance-receip`; #12 closes
on merge.
