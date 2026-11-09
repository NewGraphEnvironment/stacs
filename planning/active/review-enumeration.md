# Enumeration of the two mechanisms round 1 exposed

Parsed with `ast` over `src/stacs/*.py`, not recalled. This is what has to end the review
loop, because a defect was found inside a fix (round 1 #9), and from there a quiet round and
an exhausted reviewer look identical.

## Mechanism B — "one fact derived twice": CLOSED, 1 producer / 4 consumers / 0 re-derivations

The predicate that selects the asset linking a receipt (role `metadata` **and** type
`application/json` **and** a non-empty href) appears exactly **once**, at
`receipt.py:1159-1160`, inside `receipt_asset`. Every other occurrence of `RECEIPT_ROLE` or
`application/json` in `src/` is the constant's definition or a message string
(`receipt.py:1032, 1151, 1247-1248`; `register.py:842-843`).

Consumers, all four through the one producer:

| caller | via |
|---|---|
| `receipt.py:1168` `receipt_href` | `receipt_asset` |
| `receipt.py:1246` `item_problems` | `receipt_href` |
| `receipt.py:1337` `item_verdict` | `receipt_asset` |
| `register.py:839` `_receipt_verdicts` | `receipt_href` |

## Mechanism A — "a member read as a mapping without being one": 11 reads, 1 real instance

| read | verdict |
|---|---|
| `receipt.py:1105` `(recipe.get("code") or {}).items()` in `stac_fields` | **REAL.** `code` as a list or string survives `or {}` and `.items()` raises `AttributeError`. `item_verdict` calls `stac_fields`, so it must refuse rather than crash. → fix |
| `receipt.py:414` `table.get("columns")` | the `isinstance` guard itself |
| `receipt.py:416` `table["columns"]` | after that guard |
| `receipt.py:600` `doc.get("output")` in `read` | inside `isinstance(..., dict)`; the `_mapping` beside it is redundant but correct |
| `receipt.py:724` `doc.get("recipe")` in `write` | followed immediately by an `isinstance` check that raises |
| `receipt.py:733` `doc.get("context")` in `write` | guarded by `isinstance(context, dict)` before use |
| `receipt.py:1359` `claimed["properties"]` | `claimed` is `stac_fields`'s own return value, constructed with that key |
| `validate.py:196` `doc.get("assets")` | the existing `isinstance(assets, dict)` check records it as unreadable |
| `validate.py:215` `doc.get("properties")` | `properties if isinstance(properties, dict) else {}` |
| `verify.py:471` `doc.get("properties", ...)` | pre-existing, inside `isinstance(doc, dict)`, and `props` is type-checked after |
| `cli.py:83` `cfg.get("assets", {})` (and my `cfg.get("catalogue", {})`) | provably a dict: `read_config` raises `ConfigError` for any table that is not a table (`cli.py:57-58`) |

After the one fix, the enumeration reads 11 member reads, 0 unguarded. The script is
`scratchpad/enumerate_mechanisms.py` and exits non-zero while any remain, so it is re-runnable
rather than a one-off reading.
