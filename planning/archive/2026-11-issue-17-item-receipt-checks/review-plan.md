# Plan review — #17 (Plan agent, spawned 2026-11-16 01:05 UTC, returned during Phase 2)

Written here by the parent session from the agent's reply (Plan agents cannot write).

## Blocker
- Phase 3 helper order: `urljoin` leaves dot segments in an already-absolute href
  (`https://h/c/sub/../x.tif` stays as is), so strip the directory prefix THEN normpath and
  climb-check.

## Gap
- An asset with `file:*` and no href needs its own branch in the asset loop; `_part_key` has no
  href to resolve. Treat `""` as no href (`normpath("")` is `"."`).
- Part keys are never normalised: `parts: {"./x.tif": ...}` never matches `x.tif`. If part keys are
  normalised, two keys collapsing to one must refuse, not take the first.
- A relative href that climbs (`../c/x.tif`) may land back in the item's directory under
  `item_url`; say whether the climb refusal ends the lookup or falls through to urljoin.
- "Absolute" for the no-item_url note must include `//h/x.tif` and `/x.tif`, not only a scheme.
- Fragment and query: `x.tif#f` and `x.tif?v=1` silently name no part; drop a fragment
  (`urldefrag`); decide a query. Scheme and host compared case-sensitively.
- Prefix strip must use `urljoin(item_url, ".")`, not a bare startswith (`/cat/` vs `/c`).
- Phase 2: a `null` asset entry must be malformed too; the existing node test skips None.
- Verify path vs the migrated decision: `verify` still says `same` for a migrated item the
  audit now refuses.

## Other callers
- None missed. `VERDICT_NODES` and its post-condition test do not cover asset entries.

## Acceptance
- Served side cannot read `inconsistent` from the reverse check (only the published item is
  held to the receipt): state the served expectations (`changed` / `rebuilt`).
- The exploration's reproduction script is not in the repo; the tests are the proof.

## Assumption
- Reverse check never fires wrongly on `processing:datetime`. `processing:software: {}` over
  unversioned code now reads `inconsistent`: test and NEWS it.
- Receipt `bytes` are doubles (load_json); a true size above 2^53 now disagrees. Comment it.
- NEWS: a non-object entry for an undescribed asset (`"thumb": 5`) now flips to
  `inconsistent`; an absolute href that now resolves can name a malformed part, so
  `stac_fields` refuses where it used to read `same`.

## Ordering / Scope
- Nothing beyond the verify-path question.

## Disposition (parent session)
- All Phase 3 items folded into Phase 3's checkboxes below. Query: an href with a query names
  no part (a query can select a different representation), and gets no note; fragment dropped.
  Scheme and host compared after lower-casing via `urlsplit`.
- Part keys: matched by the same normalisation; two part keys that normalise to one href
  make the asset a disagreement (ambiguous), never a guess.
- Climb: a relative href that climbs falls through to the item_url resolution when item_url
  is given; without it, it names no part.
- Null asset entry: covered (Phase 2 tests include `None`).
- Verify vs migrated: the gate decision says require_receipt admits only items with a recipe
  identity; `_receipt_verdicts` runs only under require_receipt, so it marks a published item
  with no `receipt:recipe_id` `inconsistent` with the audit's sentence. Added to Phase 4.
  Reported in the PR summary as a plan correction.
- VERDICT_NODES: asset entries are checked by their own loop, tested by their own test; the
  tuple stays a list of fixed nodes, and its docstring says entries are covered separately.
- Size above 2^53: commented.
