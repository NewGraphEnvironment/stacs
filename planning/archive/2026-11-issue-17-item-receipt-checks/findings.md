# Findings — A non-list roles or stac_extensions raises TypeError, and item_verdict misses a field the item publishes that its receipt does not (#17)

## Issue context

**If we do it:** `verify` and `audit --require-receipt` finish with a verdict for every item, and an item that publishes a provenance field its receipt does not produce is reported. **If we never do:** one published item with a malformed `roles` or `stac_extensions` ends the run with a traceback, and an item claiming a recipe identity over a migrated receipt reads `same`.

Two defects in how `stacs.receipt` reads a published item. Both were found by the review of #15 and both predate it: they reproduce before and after that change, in lines it does not touch.

## A truthy non-list `roles` or `stac_extensions` raises `TypeError`

`receipt_asset` reads `asset.get("roles") or []` and `item_problems` reads `item.get("stac_extensions") or []`. `or []` keeps a truthy non-list, so `in` on a number or a bool raises.

```python
from stacs import receipt as r
r.receipt_href({"assets": {"a": {"href": "x.json", "type": "application/json", "roles": 7}}})
# TypeError: argument of type 'int' is not iterable
r.item_problems({"stac_extensions": 7, "properties": {"processing:datetime": "2026-11-08T00:00:00Z"}})
# TypeError
```

`validate.audit_items` and `register._receipt_verdicts` call these outside any handler, so `audit --require-receipt` and `verify` stop on the first such item. `item_problems` is documented as total: a malformed item comes back as a list of problems.

- [ ] Read both through a check that the value is a list, and report a non-list as a problem
- [ ] Sweep `src/stacs/` for the same shape (`.get(k) or []` followed by `in` or iteration)

## `item_verdict` compares the item with the receipt one way only

It walks the fields the receipt maps to and checks the item's copy of each. It never asks the other question: does the item publish a mirrored field the receipt does not produce?

```python
migrated = {"output": {"receipt_version": "1.0.0", "migrated_from": "manifest.json"},
            "recipe": {"recipe_id": None}, "result": {},
            "context": {"time": "2026-11-08T00:00:00Z"}}
item = {"properties": {"receipt:recipe_id": "a" * 64}}
r.item_verdict(item, item, migrated).verdict   # 'same', ok True
```

The same holds for an item publishing `processing:software` over a receipt whose `recipe.code` is empty. The docstring says an item whose mirrored fields do not match the receipt beside it is `inconsistent` whatever the two sides agree on.

- [ ] For `receipt:recipe_id`, `processing:datetime` and `processing:software`, a field the item publishes and the receipt's mapping does not produce is a disagreement
- [ ] Decide the same for `file:checksum` and `file:size` on an asset that names a part

## More of the same family, from a later review round

All reproduce before and after #15.

- **An asset is compared only when its href is spelled exactly as a part's key.** A contradicting `file:checksum` reads `same` behind an absolute href, `./x.tif`, or no href, and `inconsistent` behind `x.tif`. The contract keys a part by the href relative to the item, so a catalogue that publishes absolute hrefs has no asset that names a part, and the asset half of the check compares nothing there.
- **An asset entry that is not an object** is skipped on both sides and reads `same`.
- **A `file:size` integer too large for a double** on an asset that names a part raises `OverflowError` out of `item_verdict` (`float(size)`). `verify` does not reach it, because the body digest refuses such a body first; a direct caller does.

- [ ] Decide whether an href should be resolved against the item before it is looked up as a part
- [ ] An asset entry that is not an object is a disagreement, not a skip
- [ ] Compare a size without converting it to a double

## A migrated receipt's item cannot pass `--require-receipt`

The mapping leaves `receipt:recipe_id` out for a migrated receipt (`output.migrated_from`): an item never publishes a null identity. `item_problems` reports "properties has no receipt:recipe_id" for exactly that item, and `audit_items` files it under `missing_receipt`. So an item built from what `stac_fields` returns for a migrated receipt is refused by the audit, which also runs before a `register` or `load` write.

- [ ] Decide whether a catalogue that declares `require_receipt` may hold migrated items, and if so how the audit tells one from an item that carries no receipt at all (the receipt asset is still linked)


## Reproduction on main at 8390c5d (2026-11-15)

- `receipt_href` with `roles: 7`: TypeError. `roles: "metadata"`: matched by substring, returns the href.
- `item_problems` with `stac_extensions: 7`: TypeError. As a string: no raise (substring `in`), schema reports "not of type 'array'".
- `item_verdict(item, item, migrated)` with item publishing `receipt:recipe_id`: `same`.
- `processing:software` published over a receipt with `code: {}`: `same`.
- Contradicting `file:checksum` behind `x.tif`: inconsistent; behind `./x.tif`, an absolute href, no href: `same`.
- Asset entry `5`: `same`. `file:size` 10**400: OverflowError.
- `item_problems` on an item built from `stac_fields(migrated)` plus a receipt asset: "properties has no receipt:recipe_id" and the field schema's `contains` on `stac_extensions`.

## Sweep for `.get(k) or []` / `or {}`

Hits in `src/stacs/`: receipt.py:1411 (`roles`), receipt.py:1445 (`stac_extensions`), verify.py:85 (`nxt.get("body") or {}` then `.get`; and verify.py:81 `l.get("rel")` over links that may not be objects).

## Errors Encountered

| Error | Resolution |
|-------|------------|
| A mutant survived: relative-href query guard | Redundant (a relative query stays in the path, never equals a part key); removed. The resolved-URL query check is the real one, now tested with an absolute href |
| A mutant survived: normpath before prefix strip | The dot-segment case resolved either way; added `.../c/../c/x.tif`, which only matches when normalised first |
