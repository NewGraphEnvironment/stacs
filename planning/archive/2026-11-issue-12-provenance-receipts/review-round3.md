# Review round 3 — mechanism, enumeration audit, and round 2b's fixes

## Checklist read

- `code-check-python.md` — in full (all six rules).
- `code-check.md` — the prose of every H3 under `## Mechanisms` (14), plus
  "Documentation Staleness" and the Security block by heading.
- `code-check-shell.md` — by heading, for `tools/crate_receipt_vendor.sh`: the `trap … EXIT`
  rule, `mktemp` template, heredoc precedence, `grep -c`, `cd … || exit`, `local` reading its
  own assignment, BSD/GNU portability, `curl -o` without `-L`, "A failed `git fetch`".
  The script is clean against all of them (notes at the end).
- `code-check-r.md` — by heading, for the three rules that touch Python/JSON from the R side
  (ajv vs jsonschema `$ref`, `{python}` chunk, Postgres row order). Nothing applies.
- Repo `CLAUDE.md` in full; the accepted-tradeoff list in the brief honoured, with one
  correction under "Enumeration audit".

Measurement scripts are under
`/private/tmp/claude-501/-Users-airvine-Projects-repo-stacs/8bf2792e-0c97-4511-ba9b-a2264c04a49f/scratchpad/`
(`r3_probe2.py`, `r3_probe3.py`, `r3_probe6.py`, `r3_invariant.py`, `r3_enum_iv.py`,
`r3_probe1.py`), all run with `.venv/bin/python` against the unmodified tree.

---

## Findings

### 1. [bug] `src/stacs/receipt.py:857-866` — `_diff`'s collection arm is still not total: an EMPTY mapping against a non-mapping reports nothing, and `compare` answers `identical`

`walkable = isinstance(x, dict) or isinstance(y, dict)` passes when **one** side is a
mapping. The collection arm then compares only **key sets**
(`set(kx) - set(ky)`, `set(ky) - set(kx)`, and the intersection). When the mapping side has
no keys, all three sets are empty, so no difference is appended — whatever the other side is.

Measured on the tree under review:

| path | a | b | verdict |
|---|---|---|---|
| `recipe.inputs` | `{}` | `["network"]` | `identical` |
| `recipe.inputs` | `["network"]` | `{}` | `identical` |
| `recipe.inputs` | `{}` | `"network"` | `identical` |
| `recipe.code` | `{}` | `7` | `identical` |
| `recipe.config.files` | `{}` | `["a.json"]` | `identical` |
| `result.parts` | `{}` | `["x.tif"]` | `identical` |
| `result.summary` | `{}` | `[1, 2]` | `identical` |
| `result.fingerprint` | `{}` | `"nope"` | `identical` |
| `result.tolerance.tables` | `{"t": {}}` | `{"t": []}` | `identical` |

`r3_invariant.py` enumerates it mechanically rather than by example: 53 register pattern
prefixes x 81 value pairs = 4,293 comparisons, asserting
`canonical(a) != canonical(b) => at least one difference`. **155 violations**, 14 at each of
**all 11 collection patterns** (the nested `result.tolerance.tables.*` included) — the same
blast radius round 2b measured, re-opened. (One of the 155 is my own check's false
positive: `recipe.recipe_id` `None`/`None`, where the migrated-receipt rule deliberately adds
a refusal row with equal bytes.) There are **no** false positives in the other direction.

The sharpest case is the one round 2b's own test docstring names: `recipe_id` refuses to hash
`{"inputs": ["network"]}` because "a list would hash in the order it was written", while
`compare({"inputs": {}}, {"inputs": ["network"]})` is `identical` — one contract, two answers.
`{"inputs": {}}` is not a contrived left side: it is the empty recipe crate's vectors pin
(`recipe_id` doctest, `receipt.py:264-265`).

Why the existing regression test does not reach it: every row of
`test_a_collection_that_is_not_an_object_on_either_side_is_still_compared`
(`tests/test_receipt.py:821-831`) puts a **non-mapping on both sides**, and
`test_a_collection_that_is_an_object_on_one_side_still_walks_its_keys`
(`tests/test_receipt.py:859-865`) — despite its name — puts a **non-empty mapping on both sides**
(`{"a": …}` vs `{"b": …}`). No fixture has a mapping on one side and a non-mapping on the
other, which is the axis the bug lives on. The parametrization also covers 10 paths while
`test_every_register_collection_is_also_a_leaf_row`, the test just above it, asserts there are **11**
(`result.tolerance.tables.*`, the nested one, is the missing row — and it is affected).

- **Rule:** code-check.md "Zero-length, empty, and unset are three different things" (an
  empty mapping, a non-mapping and an absent member are three states collapsed into "no
  keys"); code-check.md "A fixture that cannot reach the failure mode".

### 2. [bug] `src/stacs/receipt.py:1391` and `1392` — `item_verdict` reports `same` (agreement, `ok=True`) for an item that contradicts the receipt it links, whenever `receipt.result`, `receipt.result.parts` or the item's `assets` is not a mapping

`parts = _mapping(_mapping(receipt, "result"), "parts")` turns a non-mapping into `{}`, so
`parts.get(href)` is `None`, so `not isinstance(part, dict)` → `continue` ("Not an output
this receipt describes"). The asset half of the published-vs-receipt check — the half round 1
added, because without it "an item contradicting its own receipt in those two read `same`" —
is then skipped for every asset, and the function falls through to `_mirrored`, which agrees
with itself.

Measured (`r3_enum_iv.py`): with an item whose `file:checksum` is `1220cc…` and `file:size` is
999 against a receipt saying `b…`/12, the control is `inconsistent`; **12 of 24** malformed
nodes give `same`:

| node replaced by a non-mapping | verdict |
|---|---|
| `receipt.result` (`"s"`, `["k"]`, `7`, `True`) | **`same`, ok=True** |
| `receipt.result.parts` (same four) | **`same`, ok=True** |
| `published.assets` (same four) | **`same`, ok=True** |
| `receipt.recipe`, `receipt.context`, `published.properties` | `inconsistent` (caught) |

`ItemVerdict`'s own docstring says `inconsistent` covers "the item's provenance could not be
established … Never reported as agreement", and `register._run:704` leaves `rc = 0` for
`same`. So a receipt served with `"result": []` makes the whole receipt axis report in-sync.
`read` validates only the version, and `receipt.py:72-76` states this is exactly the input
`item_verdict` must refuse rather than mis-read.

**A test pins the wrong answer.** `tests/test_receipt.py:775-784`
(`test_item_verdict_returns_a_verdict_for_a_malformed_receipt`) asserts
`got.verdict == "same"` for `{"result": value}` and `{"recipe": value}`. Its docstring
reasons "A receipt whose members are garbage claims nothing, so two identical items agree" —
but "claims nothing" is the definition of `inconsistent` here, not of `same`. Fixing the code
means changing that assertion. (A third of that parametrization, `member="assets"`, builds
`{"assets": value}`, which is not a receipt block at all, so it exercises nothing.)

- **Rule:** code-check.md "Zero-length, empty, and unset are three different things";
  code-check.md "A guard that fails toward pass" (the "nothing to compare" path and the
  "cannot be read" path are indistinguishable, and the former is the agreeing one).

### 3. [bug] `src/stacs/register.py:894` — `item_verdict`'s `ReceiptError` is outside the `try`, so one malformed receipt ends the whole `verify` run with rc 2 and discards the drift answer

The `try/except (OSError, receipt.ReceiptError)` at `register.py:880-888` wraps only
`path.read_bytes()` and `receipt.read(path)`. `receipt.item_verdict(...)` at 894 is outside
it, and it raises `ReceiptError` on input that `read` accepts — measured, three routes:

| receipt content (passes `read`) | raised from |
|---|---|
| `recipe.recipe_id = 123` or `"ab"` | `stac_fields`, `receipt.py:1110-1113` |
| `context.time = "yesterday"` | `stac_fields`, `receipt.py:1116-1120` |
| a `NaN`/`Infinity` in a mirrored property of the **published item body** | `canonical`, via `_mirrored`, `receipt.py:1430-1432` |

The third needs no malformed receipt at all: `json.load` and `fetch_bodies`' own
`json.loads` accept `NaN` by default, so a published body carrying one is fetched, digested,
and then aborts here.

`ReceiptError` subclasses `ValueError` (`receipt.py:82`), so it is not caught by `run()`
(`except RegisterError`) and lands in `cli.main`'s `except (ConfigError, ValueError, OSError)`
→ `ERROR: recipe.recipe_id is not 64 lowercase hex: 123`, **rc 2**, naming neither the item
nor the receipt URL. Everything after line 657 is lost: the DRIFT warnings, the
`receipts_*.txt` lists, the `IN SYNC` line and the rc. Two docstrings on this path say it
cannot happen — `_receipt_verdicts`' "**A receipt that cannot be read marks its own item, and
does not end the run** … Raising on the first one also discarded the stderr summary the
operator ran `verify` for (round 1)", and `run()`'s "Every refusal is a RegisterError … it is
printed and returns 1".

`tests/test_register.py:186` (`test_a_receipt_that_cannot_be_read_marks_its_item…`) covers
only receipts `read` itself refuses, so the gap is untested.

- **Rule:** code-check.md "A guard that fails toward pass" — its mirror clause, "a guard that
  fails toward **abort** on an operation where partial failure is certain".

### 4. [fragile] `src/stacs/catalogue.py:173` — the new repeated-URL refusal is O(n²), measured 67 s of pure CPU before any fetch on the 102k catalogue this function's own docstring is sized for

```python
repeated = sorted({u for u in urls if urls.count(u) > 1})
```

`urls.count(u)` is a full scan per element. Measured on realistic item URLs (`r3_probe1.py`),
with the constant checked at three sizes so the extrapolation is not a guess:

| n | time | extrapolated to 102,000 |
|---|---|---|
| 5,000 | 0.161 s | 67.1 s |
| 10,000 | 0.637 s | 66.3 s |
| 20,000 | 2.566 s | 66.8 s |

`fetch_bodies`' docstring puts the whole 102k fetch at roughly 250 s (2,000 in 4.9 s), so this
adds ~27% to the stage, silently, before the first request — and it is quadratic, so a 500k
catalogue pays ~27 minutes. `collections.Counter(urls)`, or
`seen=set(); dup={u for u in urls if u in seen or seen.add(u)}`, is O(n) and the same refusal.

Two notes that bear on whether it earns the cost at all: `register._run:577` already refuses
duplicate hrefs in O(n) (`len(set(hrefs)) != len(hrefs)`) before the only non-receipt call
site, and `_receipt_verdicts:864` passes `sorted(set(...))`. So on the tree under review the
new scan can never fire, and the refusal is now derived twice with two different messages.

- **Rule:** none (no mechanism heading covers algorithmic cost; `code-check.md` "One fact
  derived twice" covers the duplication half).

### 5. [fragile] `src/stacs/register.py:696` — `receipts_*.txt` are written as empty files even when the receipt axis never ran, so an operator reading `receipts_inconsistent.txt` cannot tell "clean" from "not checked"

`_write_list(out_dir, f"receipts_{verdict}.txt", hit)` is outside any `require_receipt` test.
With `--out-dir` and no receipts declared, `verdicts` is `{}` and four empty files are written.
The sibling two lines up gets this right — `if target.queryables:` gates
`queryables_missing.txt` / `queryables_changed.txt` (`register.py:641-643`). The same applies
when the axis is skipped because `coll_state == "missing"` or `changed` is empty: the stdout
line says "skipped", the files say nothing.

- **Rule:** code-check.md "A guard that fails toward pass" (the artifact's error path and its
  "nothing to do" path are the same bytes); code-check.md "A fix lands in one of two callers
  that share a harness".

---

## Mechanism

**The shared assumption is that "this node is not a mapping" and "this node has no members"
are the same fact — and whether that collapse is safe depends entirely on what the consumer
does with "no members". Every defect in all three rounds sits in a consumer whose default for
"no members" is *agreement*; every site the reviews cleared sits in a consumer whose default
is *refusal*. Nothing in the code or in the enumeration distinguishes the two.**

That is why a fix keeps landing one axis over. `_mapping` and `_diff`'s `keys()` were both
introduced to stop a crash, and they succeed at that everywhere. What they do *not* do is make
the read **total**, and totality is only load-bearing in the consumers that answer "same" or
"identical" when they see nothing.

Both halves of the population, enumerated. Every `_mapping` call site in
`src/stacs/receipt.py`, classified by what "no members" produces:

**Default = refusal (safe; a malformed node makes the answer worse, never better).** 11 rows,
13 call sites:

| site | what `{}` produces |
|---|---|
| `599` `read`, `output` | version `None` → the file is refused |
| `899` `_summary_tolerance` | `None` → no `within` promotion → the row stays `refuse` |
| `976`, `977` `compare`, summary values | `None` → `numbers` False → no `within` |
| `993` `table_agrees` | `name not in {}` → `False` → no `within` |
| `1003` `compare`, part's table name | `None` → "names no table that could vouch for it" |
| `1132` `stac_fields`, `parts` | with `assets=`, every href "is not a part of this receipt" → raises |
| `1183` `receipt_asset`, item assets | `None` → `item_problems` reports "no asset links the receipt" |
| `1220`, `1222` `item_problems` | `{}` → "properties has no receipt:recipe_id" is reported |
| `1325` `_mirrored`, properties | the two sides' field sets diverge → `changed`/`rebuilt` |

**Default = agreement (unsafe; a malformed node makes the answer *better*).** 8 rows, and the
findings above account for all the live ones:

| site | consumer | state |
|---|---|---|
| `_diff` `keys()` at `858-866`, collection arm | `identical` | **finding 1** (round 2b closed the both-non-mappings case only) |
| `_diff` `keys()` at `873-884`, branch arm | `identical` | closed round 1, and the `if not names:` fallback does make it total |
| `1391` `item_verdict`, `result`/`result.parts` | `same` | **finding 2** |
| `1392` `item_verdict`, published `assets` | `same` | **finding 2** |
| `1329` `_mirrored`, assets | `same` when **both** sides are malformed | reachable only through 1392; fixing 1392 covers it |
| `1104-1106` `stac_fields`, `recipe`/`result`/`context` | a builder silently publishes an item with **no** identity fields | not a verdict, but the same collapse: `stac_fields` **raises** for a non-mapping `assets=` (round 2b) and **drops** a non-mapping `recipe` — the two public arguments of one function disagree about the same input class |
| `1126` `stac_fields`, `code` | `processing:software` omitted | pinned by a test; same class as the row above |
| `965` `compare`, `missing_id` | a receipt whose whole `recipe` is a non-mapping does **not** get the migrated-receipt refusal (`.get("recipe_id", "absent")` on `{}` is `"absent"`, not `None`) | reachable only when both sides are equally malformed, which finding 1's fix makes `different` anyway |

**The mechanical remedy, which is what ends this review rather than another round.** Each
consumer has one post-condition that is checkable in code, and each would have failed on all
three rounds' defects at once:

- `_diff`: `canonical(a_block) != canonical(b_block)` **⟹** at least one difference found.
  `r3_invariant.py` is that assertion, parsed from the register rather than listed, and it is
  currently 154 violations from holding. Asserting it in a test over the register's own
  pattern set (not a hand-written path list) is what stops the fourth instance.
- `item_verdict`: `same` **⟹** every node the verdict depended on was absent or a mapping.
  That is one flag set where `_mapping` currently swallows the distinction, and it is the
  difference between `same` and `inconsistent`, which is exactly what `inconsistent` is for.
- `stac_fields`: the two public arguments should refuse the same input class. `assets=` raises;
  `recipe`/`result`/`context`/`code` do not.

Sibling mechanism, named once because it is the other half of finding 3: the same collapse
decides what a **failure** means. `_receipt_verdicts` marks-and-continues for the failures it
anticipated (a fetch failure, a version refusal) and aborts the run for the ones it did not
(`stac_fields`' two format checks, `canonical` on a non-finite number). Round 1 fixed the
first class and round 2b the `TypeError`; the remaining routes are all `ReceiptError`, so
`except ReceiptError` around the `item_verdict` call is one line and closes the class, not an
instance.

---

## Enumeration audit

`planning/active/review-enumeration.md` and `enumerate_mechanisms.py` do establish what the
write-up's corrected paragraph claims — "0 unguarded member reads" — but the four populations
are still too narrow for the defect family, in four specific ways. Each is why a finding above
survived it.

**(a) The safety predicate asks "will this raise?", not "can this answer agreement?" — and
`_mapping` is on the safe list.** `SAFE_RECEIVERS` (`enumerate_mechanisms.py:26`) contains
`_mapping`, so population D prints `ok by construction` for `receipt.py:1392`
(`_mapping(published, 'assets').items()`), `1329` and `1126` — three of the seven
agreement-default sites in the table above, including one half of finding 2. `_mapping` makes a
read not crash; it does not make it total. Of the defects found across all three rounds, **one**
(round 1's `stac_fields` `code`) was a crash and the rest were verdict defects, so the
instrument is measuring the minority class.

**(b) Population D cannot see `_diff` at all.** The walk matches `ast.Call` whose `func` is an
`ast.Attribute` with `attr in ("items","keys","values")`. `_diff`'s guarded helper is a
*function*, called as `keys(x)` / `keys(y)` (defined `receipt.py:846`; called `858`, `873`) — an
`ast.Name`, not an `ast.Attribute`. Confirmed by running the script: `receipt.py:857` appears
in no population. **The site of round 2b's most serious defect, and of finding 1, is outside
every population the script walks.** The script's output is also consistent with that: the 28 D
rows include `register.py` locals and `verify.py` helpers, and not one line of `_diff`.

**(c) Population A is bounded by a hand-written name list, and misses every `_mapping` read.**
`MEMBERS` (`enumerate_mechanisms.py:20-22`) is 20 literal names, so a read of any other member
is invisible — `part.get("sha256")` (`1146`), `entry.get("version")` (`1126`),
`_mapping(...).get("table")` (`1003`), `asset.get("href")`, `asset.get("roles")`. More
structurally: A matches only `X.get("member")`, so **none** of the 28 `_mapping(doc, "key")`
reads is in the population — and `_mapping` is the helper round 1 introduced, i.e. the
population excludes precisely the code the mechanism produced. "11 reads" is really "11 reads
of the 20 names I listed, spelled one of two ways"; the script now prints 8.

**(d) One dismissal in the write-up is factually wrong.** The mechanism-C table says "3 are
pre-existing `verify.py` lines keyed on an API's `f["id"]`, outside this branch". After this
branch inserted `items_serving` (36 lines at `verify.py:221`), **`verify.py:251-253` is the new
function**, not pre-existing: `if f["id"] in got` / `got[f["id"]] = f`. The pre-existing pair is
`141-144` (`bodies_registered`) and `217` (`bodies_serving`). The brief's accepted-tradeoff list
inherits the same error ("verify.py:144/217/253 … is pre-existing code outside this branch"), so
a line this branch added was carved out of review by a line number taken at the wrong commit.
The code itself is low-risk — same shape as its sibling, our own API — but it is new code and
`code-check.md` "One fact derived twice" states the rule: "A line number is a derived fact too,
produced by the commit it was read at: re-derive every one you cite against one commit."

**(e) The script's exit status cannot report any of this.** `sys.exit(1 if len(hits) != 1 else 0)` (`enumerate_mechanisms.py:93`)
keys only on mechanism B's producer count. It printed "24 needing a stated reason" across D and
exited **0**. The reasons live in the markdown table, which no run checks, so the script is a
printer with a guard bolted to one of four populations — `code-check.md` "A guard that fails
toward pass". Mechanism B itself is genuinely single-producer and I confirmed it independently
(`grep -n '"metadata"\|application/json\|RECEIPT_ROLE' src/stacs/*.py`: one predicate at
`receipt.py:1187-1188`, everything else a constant or a message), but the guard is a text grep
for one spelling — a second producer written `"metadata" in roles` would not be found.

**What would make it terminal.** Three assertions over parsed populations, none of them a
literal list: the `_diff` invariant from the Mechanism section (parametrized over
`_patterns(register())`, so an upstream row joins automatically — the existing
`test_every_register_collection_is_also_a_leaf_row` already proves that idiom works, and the
test two rows below it then hand-lists 10 of the 11 it counted); the `item_verdict` `same`
post-condition; and, for the population question itself, classifying each `_mapping` /
`keys()` site by its consumer's default rather than by whether it raises.

---

## Round 2b's four fixes, reviewed

**`_diff`'s `walkable` guard (both arms).** It changes no correct behaviour, checked in both
directions. For a pattern that is *not* a collection, is in `prefixes` and is not a leaf row,
`not walkable` now routes two non-mappings to the leaf arm instead of to the branch arm's
`if not names:` fallback — same comparison, same result. For a collection pattern with
`walkable` false, it routes to the leaf arm, which is the fix. The leaf arm does **not** fire
where a collection should still be walked: `pattern in collections and walkable` is tested
first, so a mapping on either side keeps the collection arm
(`test_a_collection_that_is_an_object_on_one_side_still_walks_its_keys` passes, and I
re-measured `{"inputs": {"a": …}}` vs `{"inputs": ["network"]}` → `different`, detail
"a only in a"). The one defect is finding 1: `walkable` is a sufficient condition for *walking*
and the arm treats it as sufficient for *comparing*.

One cosmetic consequence of the same arm, worth knowing when reading output: when the mapping
side has keys and the other side is a non-mapping, the reported detail is `"<key> only in a"`,
which says a key is missing rather than that the whole node is not an object. The verdict is
right; the diagnosis points at the wrong thing.

**`sorted(set(urls.values()))` + the `fetch_bodies` refusal.** The dedup is correct and the
refusal breaks no caller on this tree, checked: `register._run:577` already refuses duplicate
item hrefs in O(n) before `fetch_bodies` is reached at 607, and `_read_ids_file:468` dedupes
with a set, so `mode ids` cannot produce a repeat either; `_receipt_verdicts:864` passes a set.
The costs are finding 4 (quadratic) and the duplication of one refusal in two places with two
messages. Two smaller things in the same block: `register.py:856` logs
`f"fetching {len(urls)} receipt(s)"` — the item count, not the deduped URL count it then
fetches, which is the number round 2b's finding was about; and `fetch_bodies` is a documented
public function (`docs/reference/catalogue.md`) that now raises where it previously worked, with
no NEWS entry, whereas 0.2.0 flagged this class as "**Behaviour change:**".

**The non-string href handling.** `item_verdict` (`1395-1403`) and `stac_fields` (`1133-1139`)
are both correct and I could not get a `TypeError` out of either (`r3_probe2`-style sweep over
`["x"]`, `{"a":1}`, `7`, `None`, `True`). The `href is None` case correctly falls through to
`parts.get(None)` → no part → skip. `asset["href"]` at `1417` is reachable only after the
`isinstance(href, str)` gate, so it cannot raise. `receipt_asset`'s `isinstance(href, str) and
href` keeps a non-string href from being chosen as the receipt link, so such an item is marked
`inconsistent` by `_receipt_verdicts`' `unlinked` path rather than mis-read.

**The two keyword-argument guards.** `stac_fields(assets=)` (`1098-1102`) and
`compare(overrides=)` (`941-944`) both refuse a non-mapping before any `.items()`, both raise
`ReceiptError`, and both are pinned by a test that matches the message rather than the type.
Correct. The asymmetry noted in the Mechanism table stands: in the same function, `assets=`
raises for a non-mapping while a non-mapping `recipe` is silently dropped.

---

## Notes, not findings

- `tools/crate_receipt_vendor.sh` is clean against every shell rule I checked. The EXIT trap
  is single and reads a global (the rule's own failure case, fixed in the comment); `mktemp -d
  -t crate_receipt.XXXXXX` has six X's; both `while read` loops take their heredoc body from
  `$(printf …)` rather than a heredoc inside `$( )`, so bash 3.2's quote-scanning trap does not
  apply; `curl` has `-L`, `--fail`, `--max-time` and an `-s` empty-file check; `cd` is `&&`-
  chained inside `repo_root`; the `n > 0` and `u == FROZEN_URLS` counters are both real guards
  against the "passes on anything" shape. One small thing: in `vendor` mode `$SOURCE_FILE` is
  written **before** the `bad > 0` check, so a run where one fetch failed writes a SOURCE file
  claiming the pinned tag for a file that kept its old bytes — the script still exits 1, and a
  later `check` catches it.
- `items_serving`'s docstring says "Same guards, for the same reasons: … a repeated id is
  refused". `items_serving` does refuse one; `bodies_serving` (`verify.py:217`) silently
  overwrites (`got[f["id"]] = body_digest(f)` with no membership test). The new function is the
  stricter of the two, so this is a wrong claim about the old code, not a defect in the new.
- `validate.audit_items` computes `receipt.item_problems(doc)` before the
  `"receipt:recipe_id" not in properties` branch, so it is discarded for every item that
  carries no receipt field. Measured 0.059 ms/item, 6.1 s for 102k — not worth flagging.
- All of `src/`, `tests/` and `planning/active/*.py` parse under Python 3.11.15, the declared
  `requires-python` floor (`code-check-python.md`, "A line break inside an f-string's braces").
- README snippet markers balance (5 start / 5 end) and the new `receipts` section's only links
  are absolute (`code-check-python.md`, "`mkdocs build --strict -q` passes a dead link").
