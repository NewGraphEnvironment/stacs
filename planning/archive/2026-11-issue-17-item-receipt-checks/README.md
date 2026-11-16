## Outcome

`stacs.receipt` now gives every published item a verdict, and holds the item to its receipt
in both directions (#17). A provenance field the item publishes and the receipt's mapping does
not produce is a disagreement, so a recipe identity over a migrated receipt no longer reads
`same`. An asset is matched to the part its href names through the common spellings of one
href, and an absolute href is resolved against the item's URL, which `verify` now passes as
`item_url`. Malformed input that used to raise or be skipped is reported instead:
- `roles` or `stac_extensions` that is not a list;
- an asset entry that is not an object;
- a huge `file:size`;
- an href or receipt href no parser reads;
- a malformed paging link.

At the gate the owner decided that `require_receipt` admits only items that carry a recipe
identity. `audit` and `verify` now refuse an item from a migrated receipt with one sentence,
`receipt.NO_RECIPE_IDENTITY`. The lesson the review rounds kept teaching: the href code was
first written from the cases that came to mind, not from what `urllib.parse` does. Each of
`urljoin`, `urlsplit` and `urldefrag` normalises on some routes and not others, so the merge
is now RFC 3986 done by hand. The durable version is
[`research/href_matching.md`](../../../research/href_matching.md).

## Measurement

- **Code-check:** four rounds over the branch, plus a plan review: 5 reviewer spawns, the
  bound. Findings per round: 4, 5, 2, 3, all fixed. Rounds 2, 3 and 4 each found a defect
  inside an earlier round's fix:
  - round 2: a NEWS line describing a bug that never shipped;
  - round 3: `urljoin` re-collapsing the `//` that round 2 had stopped `normpath` collapsing;
  - round 4: `_remove_dots` reading an emptied `//` as the root.

  So the loop ended on an enumeration, not a quiet round.
- **Enumeration:** round 4 compared `_relative_href` with an RFC 3986 reference over 5.76M
  generated cases and found one real class of disagreement, the root confusion. After the
  fix, two sweeps in the suite (780 rooted paths; every relative href of up to 4 segments)
  and 7,774 absolute-route cases run outside it found 0 disagreements. The 3 the outside
  script first reported were its own generator's error, `"/" + "//../r/a"` being a
  network-path reference.
- **A reviewer claim that did not hold:** round 3 said `urljoin` collapses `//` for a
  path-absolute href. Measured on CPython 3.12.13, it does not; only the climbing merge and
  the base do. The research note records what was measured.
- **Mutation checks:** every guard added on the branch was reverted once to watch its test
  fail. Survivors were treated as findings:
  - two at Phase 3: a redundant relative-query guard, removed; and a normpath-order case
    that needed a sharper fixture;
  - one at round 2: a `..` at an absolute root returned None where the RFC clamps it, a
    real defect;
  - five at round 4: guards no test reached, now pinned;
  - two more while fixing round 4, now pinned.
- **Tests:** 920 on the base, 1046 at the end, all passing.

## Evidence

`planning/archive/2026-11-issue-17-item-receipt-checks/review-*.md`: the plan review and
the four code-check rounds, each with its checklist record and findings.

Closed by: the PR for #17.
