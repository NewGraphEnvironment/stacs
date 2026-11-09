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

## What this enumeration does NOT establish — corrected after round 2b

The closing claim above was too wide. The honest statement is **"0 unguarded member reads"**,
not "0 instances of the mechanism": the population is *a member read then used as a mapping*,
and round 2b found two instances outside it, one of them the most serious defect of the whole
review.

- **A value consumed as a dict KEY** (mechanism C). `parts.get(asset.get("href"))` raised
  `TypeError: unhashable type` for a list href, out of `item_verdict`, which the verify path
  reaches with no audit in front of it.
- **A non-mapping walked as if it had no members** (mechanism D). `_diff`'s *collection* arm
  was tested before the branch arm round 1 fixed, and `keys()` is empty for a non-mapping, so
  two non-mappings at a collection path compared nothing and `compare` answered `identical`.
  Eleven register patterns are both a collection and a leaf row, so all eleven were silent —
  and `recipe.inputs` as a list was called `identical` by the same contract whose `recipe_id`
  refuses to hash it.

`planning/active/enumerate_mechanisms.py` now walks all four populations. Current state, with
the script re-runnable rather than a one-off reading:

| mechanism | sites | real | note |
|---|---|---|---|
| A — member read as a mapping | 8 flagged of 11 | 0 | each guarded by an `isinstance` that raises, a value this code constructed, or `read_config` refusing a non-table |
| B — one fact derived twice | 1 producer | 0 | the receipt-asset predicate appears exactly once; the script exits non-zero if that stops being true |
| C — value used as a dict key | 13 flagged | 0 in this diff | 7 are type annotations (the walk's own false positives); 3 are pre-existing `verify.py` lines keyed on an API's `f["id"]`, outside this branch and noted rather than changed; `row["key"]` is always a JSON object key, so always a string |
| D — non-mapping walked as empty | 28 sites | 0 | 24 iterate locals this code built or are guarded; the two public keyword arguments (`stac_fields(assets=)`, `compare(overrides=)`) now refuse a non-mapping |

**The lesson worth keeping is about the instrument, not the bugs.** An enumeration ends a
review only over the population it actually walks, and naming that population is the load
bearing part. Mine was one mechanism wide when the defect family was three.


---

## Round 3's audit of this instrument, and what replaced it

Round 3 took the enumeration apart, and was right on every count. Recorded here because the
lesson is about the instrument, not the bugs:

1. **The safety predicate asked "will this raise?", not "can this answer agreement?"** — and
   `_mapping` was on its safe list. So three of the eight agreement-default sites printed
   `ok by construction`, one of them half of a real defect. Across all three rounds exactly
   one defect was a crash and the rest were wrong verdicts: the instrument measured the
   minority class.
2. **Population D could not see `_diff` at all.** It matched `.items()`/`.keys()`/`.values()`
   as attributes; `_diff`'s helper is a local *function* (`def keys(x)`), an `ast.Name`. The
   site of the two most serious defects of the whole review was outside every population
   walked.
3. **Population A was a hand-written list of 20 member names**, and matched only
   `X.get("member")` — so it excluded all 28 `_mapping(doc, "key")` calls, the very helper the
   round 1 fix produced. "11 reads" meant "11 reads of the 20 names I listed, in one of two
   spellings".
4. **One dismissal was factually wrong.** The mechanism-C table called `verify.py:251-253`
   pre-existing. It is not: this branch inserted `items_serving` at `verify.py:221`, so those
   lines are *this branch's own code*. A line was carved out of review by a line number taken
   against the wrong commit — the same "one fact derived twice" the enumeration was built to
   close.
5. **The script's exit status keyed only on mechanism B.** It printed "24 needing a stated
   reason" and exited 0; the reasons lived in prose that no run checks.

### The mechanism, as round 3 named it

> "Not a mapping" and "has no members" are treated as the same fact — and whether that
> collapse is safe depends entirely on what the consumer does with "no members". Every defect
> in all three rounds sits in a consumer whose default for "no members" is **agreement**;
> every site the reviews cleared sits in one whose default is **refusal**.

That is why a type-safety sweep could not find them: `_mapping` and `keys()` were introduced
to stop a *crash*, and they do that everywhere. They do not make a read **total**, and
totality only matters where the answer is "same".

### What ends the loop instead

Three post-conditions, all mechanical, all in the suite:

| post-condition | where | state |
|---|---|---|
| `canonical(a_block) != canonical(b_block) ⟹ ≥1 difference`, over every path `_patterns(register())` names | `test_compare_reports_every_difference_its_own_register_can_reach` | holds over 3,816 differing pairs; mutation-verified against the pre-fix arm |
| `same ⟹ every node the verdict depended on was absent or a mapping`, enumerated from `receipt.VERDICT_NODES` | `test_item_verdict_never_says_same_over_a_node_it_could_not_read` | holds over 8 nodes × 5 values |
| each `_mapping`/`keys()` site classified by its **consumer's default**, not by whether it raises | round 3's classification: 13 refusal-default, 8 agreement-default | all 8 agreement-default sites now refuse or are total |

The carve-out in the first is a number, not a wave-through: exactly the empty-vs-absent pair,
both orders, at each of the eleven collection patterns — 22 — and it matches crate's own walk,
where `names(NULL)` and `names(list())` are both empty
(`R/crt_receipt_compare.R:230-231`, read at the tag).

**The instrument was the problem, not the diligence.** A hand-built enumeration is only ever
as wide as the population its author imagined; a post-condition parametrized over the
register's own rows widens itself.
