# Task: A non-list roles or stac_extensions raises TypeError, and item_verdict misses a field the item publishes that its receipt does not (#17)

**If we do it:** `verify` and `audit --require-receipt` finish with a verdict for every item, and an item that publishes a provenance field its receipt does not produce is reported. **If we never do:** one published item with a malformed `roles` or `stac_extensions` ends the run with a traceback, and an item claiming a recipe identity over a migrated receipt reads `same`.


## Context

[stacs#17](https://github.com/NewGraphEnvironment/stacs/issues/17) lists defects in how
`stacs.receipt` reads a published item. The review of #15 found them, and they were already
there before that change. The issue has no comments. I reproduced every claim on `main` at
8390c5d (`uv run python`, 2026-11-15):

- `receipt_href` and `item_problems` raise `TypeError` on `roles: 7` or `stac_extensions: 7`.
  A **string** `roles: "metadata"` is worse: `in` matches it as a substring, so the asset is
  accepted as the receipt asset. The issue does not mention this case.
- `item_verdict(item, item, migrated)` returns `same` when the item publishes
  `receipt:recipe_id`. It also returns `same` when the item publishes `processing:software`
  over a receipt that has no versioned code.
- An asset with a contradicting `file:checksum` returns `inconsistent` behind href `x.tif`,
  and `same` behind `./x.tif`, behind an absolute href, or with no href. An asset entry that
  is not an object returns `same`. A `file:size` of 10**400 raises `OverflowError`.
- `stac_fields(migrated)` builds an item that `item_problems` refuses for two reasons: it has
  no `receipt:recipe_id`, and crate's field schema wants the receipt extension listed. The
  audit files that item under `missing_receipt`.

In the verify path, `register._receipt_verdicts` (register.py:839, 897) catches only
`ReceiptError`. A `TypeError` or `OverflowError` from an item body therefore ends the whole
run with a traceback.

## Decided at the gate (owner, 2026-11-15)

- **Migrated items under `require_receipt`: refuse them, and say why.** `require_receipt`
  means every item carries a recipe identity, so `verify` can tell a rebuilt item from a
  changed one, and a migrated item cannot. An item that links a receipt asset but carries
  no `receipt:recipe_id` gets its own sentence in `bad_receipt`: "links a receipt but
  carries no recipe identity: a migrated receipt, which require_receipt does not admit, or
  a build that dropped it". It no longer goes under "carry no receipt". Nothing new is read.
- **Href matching: resolve each href against the item URL.** `item_verdict` gains an
  optional `item_url`, and `verify` passes it. Relative spellings are normalised. An
  absolute href is made relative when it sits under the item's directory. Without
  `item_url`, an absolute href gets a note saying the asset half compared nothing, never a
  silent `same`.
- Mine, on conventional grounds:
  - Leaving a mirrored field out is still allowed. Crate's field schema says "each field is
    optional", so a field the item leaves out is not a disagreement. Only a field the item
    **publishes** that the mapping does not produce is one.
  - For `file:*` on assets the reverse check needs no new code. `stac_fields` always
    produces both `file:checksum` and `file:size` for an asset that names a part. An asset
    that names no part, such as a thumbnail, may carry `file:*` legitimately. So the only
    asset fix is to match more hrefs to parts.
  - Percent-encoding is not decoded. A part is keyed by its path verbatim, as the mapping
    keys it.
  - This is a **minor bump (0.5.0)**. `item_verdict` now says `inconsistent` in cases where
    it used to say `same`, which is a Behaviour change entry (CLAUDE.md, Versioning).

## Phase 1: Non-list reads (tests first)

- [x] Failing tests in `tests/test_receipt.py`: `roles` set to `7`, `True`, `"metadata"` or
      `{}`, and `stac_extensions` set to `7` or a string. `receipt_href` returns None or the
      right asset, and `item_problems` returns problems instead of raising.
- [x] Add a `_list(node, key)` helper beside `_mapping` (receipt.py:81) that returns `[]`
      for anything that is not a list. Read `roles` (receipt.py:1411) and `stac_extensions`
      (receipt.py:1445) through it.
- [x] `item_problems` reports "asset {key!r} roles is not a list". The field schema already
      reports a non-list `stac_extensions`, so that message is not repeated.
- [x] A verify-path test in `tests/test_register.py`: an item with `roles: 7` gets a
      verdict, and the run continues.
- [x] Sweep `src/stacs/` for the same shape. The one hit outside receipt.py is
      `verify.py:81,85`, where a `next` link that is not an object, or a truthy `body` that
      is not an object, raises `AttributeError` while paging. Raise `RuntimeError` there
      instead, matching the surrounding paging checks, and add a test in
      `tests/test_verify.py`.
- [x] Mutation-check each guard: remove it and watch its test fail.

## Phase 2: `item_verdict` checks both directions (tests first)

- [x] Failing tests. A migrated receipt with an item that publishes `receipt:recipe_id`
      gives `inconsistent`. A receipt with no versioned code and an item that publishes
      `processing:software` gives `inconsistent`. Run each through both `published` and
      `served`.
- [x] For `receipt:recipe_id`, `processing:datetime` and `processing:software`, a field the
      published item carries that `claimed["properties"]` lacks is a disagreement
      (receipt.py:1685).
- [x] An asset entry that is not an object is malformed on both sides. Add each such entry
      to the existing `malformed` node check (receipt.py:1623) as `published.assets[k]` or
      `served.assets[k]`. Today the code skips it at receipt.py:1659 and in `_mirrored`.
- [x] Compare sizes without converting to a double. Read the size through `_whole` and
      compare it as an int, with a fractional or non-number size counting as a
      disagreement. Add a test with `file:size` set to `10**400`.
- [x] Update the `item_verdict` docstring and the `ItemVerdict` docstring to describe the
      check in both directions.
- [x] (review) A `processing:software: {}` over unversioned code is `inconsistent`: test it.
      Served-side expectations stated (`changed`). Size above 2^53 commented: receipt bytes
      are doubles. `VERDICT_NODES` docstring says asset entries have their own check.

## Phase 3: Match an asset href to a part (tests first)

- [ ] Failing tests: `./x.tif`, `sub/../x.tif`, an absolute href under `item_url`, an
      absolute href with no `item_url` (expect a note and no silent agreement on the asset
      half), an asset with `file:*` and no href (expect a disagreement), and an href that
      leaves the item's directory (expect it to name no part).
- [ ] Add a helper `_part_key(href, parts, item_url)`. It tries an exact key first, which
      keeps today's behaviour. Then it normalises a relative path with
      `posixpath.normpath` and refuses a path that climbs above the item's directory. Then,
      when `item_url` is given, it uses `urljoin` and strips the item's directory prefix.
      The matched key goes into `named`, so `stac_fields` stays the only producer.
- [ ] (review) In the helper: drop a fragment; an href with a query names no part; strip the
      prefix of `urljoin(item_url, ".")` and normpath and climb-check AFTER stripping; compare
      scheme and host case-insensitively; a climbing relative href falls through to item_url;
      "absolute" for the note covers a scheme, `//host` and `/path`; part keys are matched by
      the same normalisation, and two part keys that normalise to one make the asset a
      disagreement. An asset with `file:*` and no href, or href `""`, is a disagreement in
      the asset loop itself.
- [ ] Add `item_verdict(..., item_url=None)`. `register._receipt_verdicts` passes
      `by_id[item_id]`, the URL it already resolves the receipt href against
      (register.py:848). Add a test there with absolute hrefs.

## Phase 4: Migrated items under `require_receipt`

- [ ] Failing test in `tests/test_validate.py`. Build an item from
      `stac_fields(migrated)` plus a receipt asset. It lands in `bad_receipt` with the
      migrated sentence, not in `missing_receipt`. An item with no receipt asset and no id
      still lands in `missing_receipt`.
- [ ] Change `audit_items` (validate.py:215-221): no `receipt:recipe_id` together with
      `receipt.receipt_href(doc)` set means `bad_receipt` with that sentence.
- [ ] Say in the `item_problems` docstring and the README that `require_receipt` admits
      only items that carry a recipe identity.
- [ ] (review) `verify` agrees with the audit: `_receipt_verdicts` (which runs only under
      `require_receipt`) marks a published item with no `receipt:recipe_id` `inconsistent`
      with the same sentence. Test in `tests/test_register.py`.

## Phase 5: Documentation

- [ ] Add `## Unreleased` to `NEWS.md` with **Behaviour change** entries for: the reverse
      check (including `processing:software: {}`), non-object asset entries (any asset, one
      the receipt does not describe included), href resolution and `item_url` (a resolved href
      can now name a part the mapping refuses), the non-list reads (a string `roles` is no
      longer accepted as the receipt role; a null `roles` is reported), the paging refusals,
      and the migrated-item sentence in the audit and in verify. Derive every number in the entries from the code.
- [ ] README receipts section (inside the markers, absolute links only): how hrefs are
      matched to parts, and what `require_receipt` admits.
- [ ] Run `uv run mkdocs build --strict` without `-q`, and `tests/test_docs.py`.

## Validation

- [ ] Tests pass (`uv run pytest`, with doctests)
- [ ] `/code-check` clean (once over the branch with `/code-check branch`)
- [ ] PWF checkboxes match landed work
- [ ] `/planning-archive` on completion

How each change is proved: every defect in the issue, plus the string-`roles` case, gets a
test that fails on 8390c5d and passes after the change. Each new guard gets a mutation
check: remove it and watch its test fail. The verify path is tested through
`tests/test_register.py`'s ssh/HTTP stubs, so a non-`ReceiptError` cannot end a run. The exploration's reproduction
script was not committed, so the tests are the proof (review).

