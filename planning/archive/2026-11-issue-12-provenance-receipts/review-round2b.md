# Review round 2b (re-run) — findings

Branch `12-read-write-and-compare-provenance-receip`, base `17e4e9f`. Tree verified intact
(746 passed, 47.9 s) before and after every probe; all probes ran from the scratchpad and
wrote nothing into the repo.

## Checklist read

- `code-check-python.md` — **in full** (7,237 bytes, all 6 rules).
- `code-check.md` — prose of all 14 H3s under `## Mechanisms`, plus the stand-alone and
  Security headings this diff touches: "An ordered dispatch makes severity ordering
  load-bearing", "A link to a repo-hosted artifact must be *tracked*", "An assertion that
  matches an interpolated value cannot see the claim around it", "A preview flag is only safe
  if it previews", "Bare `y`, `n`, `on`, `off` … YAML 1.1", "Documentation Staleness",
  "Test the cold/create path", "Do not edit files a long test run is reading", Process
  Visibility, Secrets in Committed Files, Credentials. Not read: Spreadsheets and PDFs (3),
  "Adopting Existing Config", "Fetch an expiring credential", "Firewall Defaults",
  "Gitleaks pre-commit hook", "Public bucket ≠ listable", "A pluralisation marker",
  "Test a persistent change through its per-process override", "Do not write to an artifact a
  human is testing on", "Percent-encode a URL at construction" — nothing in the diff uses
  them.
- `code-check-shell.md` — read by heading for `tools/crate_receipt_vendor.sh`: empty arrays
  under `set -u` on bash 3.2, Quoting, the three heredoc rules, `mktemp` template, failed
  `cd`, `grep -c`, `curl -o` without `-L`, BSD vs GNU sed/grep, GNU `stat`/`date` on this Mac,
  `a && b || c`, a second `trap … EXIT`, `local` in one statement,
  `for x in $(cmd | grep … || true)`, a sed/awk range running to EOF, a variable in a sed
  replacement, `if ! cmd; then rc=$?`, bare `wait`, reading a file line-by-line,
  "A verification command can be shadowed", "A Python CLI redirected to a log". ~45 headings
  not read (git/gh/ssh/aws/s3cmd/docker/psql/sips/perl — none of those tools appear).
- `code-check-r.md` — index only; no R in the diff.

## Findings

### 1. [bug] `src/stacs/receipt.py:850-857` — `_diff`'s COLLECTIONS arm has the hole round 1 closed in the branch arm, and it needs no null to stay silent

Round 1 #4 fixed the `else` (branch) arm by comparing the nodes themselves when neither side
has keys (line 865-873). The `if pattern in collections:` arm above it was not touched, and it
is reached **first** for every register pattern that is both a leaf row and a collection.
Enumerated rather than recalled (`sorted(collections & set(register()))`), that is **eleven**
patterns, and every collection the register names has a leaf row: `context.toolchain`,
`recipe.code`, `recipe.config.files`, `recipe.config.settings`, `recipe.inputs`,
`result.fingerprint`, `result.parts`, `result.summary`, `result.tolerance.summary`,
`result.tolerance.tables`, `result.tolerance.tables.*`. `keys(x)` returns `[]` for anything that is
not a dict, so both key sets come out empty, no common key is walked, and the `refuse` leaf
row the register carries for that same path never fires.

Measured on the tree under review (`compare(a, b)` on receipts identical except the named
member):

```
recipe.code        "garbage-a"  vs "garbage-b"  -> identical []
recipe.code        "garbage"    vs {}           -> identical []
recipe.inputs      ["network"]  vs ["roads"]    -> identical []
recipe.config.files ["a.csv"]   vs ["b.csv"]    -> identical []
result.parts       ["x.tif"]    vs ["y.tif"]    -> identical []
result.summary     1.0          vs 2.0          -> identical []
context.toolchain  "x"          vs "y"          -> identical []
```

Two things make this worse than the branch-arm case that was fixed:

- It needs nothing contrived. The branch-arm defect only stayed silent when the dict side's
  members were all null; here two plainly different scalars, or two different one-element
  **arrays**, report no difference at all.
- The array form is the shape `_check_keyed` exists to refuse. `recipe_id()` refuses to hash
  `{"inputs": ["network"]}` precisely because "a list would hash in the order it was written";
  `compare()` answers `identical` for `inputs: ["network"]` against `inputs: ["roads"]`. A
  list is also what `jsonlite` produces from an unnamed R list, so this is reachable from a
  receipt written by a non-conforming producer of the same contract, not only by hand editing
  — and `read` validates nothing but the version, so such a receipt gets here.

Same fix as round 1's: when both key sets are empty at a collection node, compare the nodes
themselves. The existing guard test `test_a_block_that_is_a_scalar_on_both_sides_is_still_compared`
parametrizes over `output`/`recipe`/`result`/`context` only, which are branch nodes, never
collection nodes — which is why three rounds have not seen this.

- **Rule:** code-check.md "A fix lands in one of two callers that share a harness"

### 2. [bug] `src/stacs/register.py:859,868` + `src/stacs/catalogue.py:128-188` — two items that link the SAME receipt URL make every one of them read `inconsistent`, reproducibly

`_receipt_verdicts` builds `urls` as `{item_id: urljoin(item_url, href)}` and passes
`list(urls.values())` to `fetch_bodies`, which is the first call site in the package that can
contain a duplicate (the item fetch passes distinct item URLs). `fetch_bodies` runs one worker
per list element, and each worker for the same URL writes the **same** `…json.part` path and
then `os.replace`s it: whichever worker loses writes its part, finds it already renamed away,
and fails with `FileNotFoundError` — on all three attempts. The URL then lands in the returned
`failed` list although the file is sitting correctly in the batch directory, and
`register.py:868` turns that into

```python
if urls[item_id] in failed:
    out[item_id] = receipt.ItemVerdict("inconsistent", (), ("its receipt could not be read …",))
```

for **every** item that links it.

Measured end to end, 3 runs out of 3, six items in a flat bucket each linking
`"href": "receipt.json"` with the correct `file:checksum`:

```
{'a0': 'inconsistent', 'a1': 'inconsistent', ..., 'a5': 'inconsistent'}
fetch failed after 3 attempts: …/bucket/receipt.json: [Errno 2] No such file or directory:
  '…/work/receipts_0/<md5>.json.part' -> '…/work/receipts_0/<md5>.json'
```

and `fetch_bodies([u, u, u, u], …)` alone returned `failed: [u]` in 4 of 5 runs while writing
the correct file.

This is not a contrived catalogue. The contract is "one record per published output" with
`output.scope` for partitions, so one receipt per build shared by the items it produced is a
legitimate shape, and `receipt_asset`'s own docstring is explicit that the contract is the
asset link rather than a filename — `_item_with_receipt`'s comment in `tests/test_register.py`
even records that a filename convention "would give every item one receipt", and gives each
fixture item its own href to avoid it. So the one shape the fixtures deliberately steer around
is the one that fails, and it fails as a false `inconsistent` with `rc = 1` on good data —
the verdict the module documents as "never reported as agreement".

Deduplicating the fetch list (`sorted(set(urls.values()))`) fixes it at this call site; the
`.part` collision in `fetch_bodies` is pre-existing but unreachable from any other caller.

- **Rule:** code-check-shell.md "Parallel writers sharing one output file interleave mid-record"

### 3. [bug] `src/stacs/receipt.py:1371` — a JSON array or object as an asset `href` raises `TypeError` out of `item_verdict`

```python
part = parts.get(asset.get("href"))
```

`dict.get` hashes its argument, so an asset whose `href` is `[]` or `{}` raises
`TypeError: unhashable type: 'list'` instead of a `ReceiptError`. Measured:

```
item = {"properties": {...}, "assets": {"data": {"href": ["x.tif"], "roles": ["data"]}}}
item_verdict(item, item, r)   -> TypeError unhashable type: 'list'
item_verdict(item, item, {... "result": {}})  -> TypeError   (empty result.parts too)
```

Reachable from `register._receipt_verdicts`, which reads the published body with `json.load`
and hands it to `item_verdict` with no audit in front of it on the `verify` path — so
`stacs verify --require-receipt` dies on a traceback over one malformed published item instead
of reporting it. `receipt_href`/`item_problems` tolerate the same item (there the href is
`isinstance`-checked at line 1165), which is what makes it easy to miss.
`stac_fields(receipt, assets={"data": ["x.tif"]})` raises the same way at line 1117, but there
the href comes from the caller's own argument.

**This is the third mechanism the brief asks about, and `review-enumeration.md` cannot see it
by construction:** its population is *member reads* (`X.get(k)` then used as a mapping). A
JSON value used as a dict **key** is the same family — a value consumed as something it may
not be — and none of the 11 rows is one.

- **Rule:** code-check.md "A guard's scope, escape hatches, and remedies"

### 4. [fragile] `tests/test_receipt.py:758-767` — the assertion in `test_compare_refuses_a_malformed_block_rather_than_crashing` cannot fail

```python
assert got.verdict in r.ITEM_VERDICTS or got.verdict in ("identical", "equivalent", "different")
```

`compare` returns exactly one of those last three by construction, so the disjunction is
unconditionally true and the `ITEM_VERDICTS` clause (a copy from the `item_verdict` test, and
a set `compare` can never return) is dead. The only thing the test checks is "did not raise",
which is what round 1 #9 needed — but the name and docstring say *refuses*, and a reader
looking for coverage of "compare and a malformed block" finds this and stops. It is green
today against the `identical` verdicts in finding 1.
`test_item_verdict_refuses_a_malformed_receipt_rather_than_crashing` (line 770) has the same
shape (`in r.ITEM_VERDICTS` is total for `item_verdict`).

- **Rule:** code-check.md "Restore the bug and prove the guard fires"

## `review-enumeration.md` — are the ten dismissals right?

Each checked against the tree. **All ten are correct.**

| row | verdict |
|---|---|
| `receipt.py:414` / `:416` `table.get("columns")`, `table["columns"]` | right — `isinstance(table.get("columns"), dict)` *is* the guard, and 416 is after it |
| `receipt.py:600` `doc.get("output")` in `read` | right — inside `isinstance(…, dict)`; the `_mapping` beside it is redundant, as it says |
| `receipt.py:724` `doc.get("recipe")` in `write` | right — `isinstance` raise on the next line |
| `receipt.py:733` `doc.get("context")` in `write` | right — `publish and isinstance(context, dict)` |
| `receipt.py:1359` `claimed["properties"]` | right — `stac_fields` constructs that key on every return |
| `validate.py:196` `doc.get("assets")` | right — `None → {}`, then `isinstance` → `unreadable` + `continue` |
| `validate.py:215` `doc.get("properties")` | right |
| `verify.py:471` `doc.get("properties", …)` | right — `isinstance(doc, dict)` guard, `props` type-checked after |
| `cli.py:83` `cfg.get("assets", {})`, `cfg.get("catalogue", {})` | right — `read_config` raises `ConfigError` on any table that is not a dict (`cli.py:57-58`), and both call sites take `cfg` from `read_config` |

Mechanism B (one producer for the receipt asset) re-checked by grep over `src/`: the predicate
appears once, at `receipt.py:1163-1165`; every other `RECEIPT_ROLE` / `application/json`
occurrence is the constant or a message. Accurate.

**What the enumeration does not establish is completeness**, and it does not claim to: the
population it parses is "member read then used as a mapping". Finding 3 is outside that
population (a value used as a dict *key*), and finding 1 is outside it too (a *walk* that
treats a non-mapping as having no members rather than reading a member off it). The honest
closing statement is "0 unguarded member reads", not "0 instances of the mechanism".

## Areas probed and clean

- **`reindent()`** — 4,000 randomized round trips: strings containing `" \ { } [ ] , :`,
  control bytes, astral-plane characters; `-0.0`, `1e-9`, `1e-6`, `5e-324`, `1e300`, ints to
  ±(2^53-1). Every case parses back to the same value, re-canonicalises to the same bytes, and
  the output with the inserted whitespace stripped **outside strings** is byte-identical to the
  canonical form. No string content altered, no number spelling changed, escapes handled.
- **`_check_keyed`** — walked over all four `_KEYED` paths: refuses a non-mapping at every
  depth (`recipe`, `recipe.config`, and each leaf), allows an absent intermediate at every
  depth including `config.settings`. The `for … else` is gone; no `break` skips a check.
- **`_mapping(x, key)` with `node[key] is None`** → `{}`, which is the right answer at all nine
  call sites (each follows with `.get`/`.items()`/`in`).
- **`item_verdict`'s asset comparison** — a part with a malformed `sha256` or `bytes` yields
  `want = None` and disagrees; `file:size` alone and `file:checksum` alone are each checked
  independently; `file:size` as a float from `load_json` compares equal to the int `_whole`
  returns; an absent href falls through to `continue`. (The one remaining soft spot is an
  asset publishing `"file:checksum": null` beside a part with a malformed digest — both sides
  `None`, so no disagreement; an asset that publishes a null is not claiming a digest, so I do
  not read that as a defect.)
- **`_receipt_verdicts` batching** — exercised directly with `chunk=2` over 5 ids (the suite
  only ever runs one batch): 3 batches, directories `receipts_0 / receipts_2 / receipts_4`, no
  id dropped or double-counted (`out` keys per batch == `unlinked | published` == the batch),
  `items_serving` receives exactly the linked ids, correct verdicts. The three remaining
  `raise RegisterError` paths (unreadable published body, `items_serving` failure, an id the
  API stopped serving) do abort before the drift report, but each is a deliberate, commented
  "the run's problem, not the item's" decision rather than the round-1 defect.
- **`_diff`'s no-keys arm** — the `return` is the last statement of that arm; nothing is
  skipped.
- **`tools/crate_receipt_vendor.sh`** — `set -euo pipefail` with every failure routed through
  `|| { bad=…; continue; }`; one `trap cleanup EXIT` reading a global; `mktemp -d -t` template
  has 6 X's and a failed `mktemp` aborts under `set -e`; heredoc bodies are command
  substitutions, so the last line is newline-terminated and the loops run in the current shell
  (so `bad`/`n`/`u` persist); `curl` has `-L`, `--fail`, `--max-time` and an `-s "$2"` empty
  check; `n > 0` and `u == FROZEN_URLS` both counted rather than claimed; no BSD/GNU-divergent
  flags, no `sed`/`awk`, no `git` beyond `hash-object`. (`SOURCE` is written before the `bad`
  gate, so a partially failed `vendor` leaves a SOURCE listing old blob shas — but the run
  exits 1, so it is not a silent pass.)
- **`requires-python = ">=3.11"`** — all 22 `.py` files parse under CPython 3.11.11 (no PEP 701
  f-string newline).
- **NEWS.md's counts** — `2637 / 10 / 7 / 13 / 9` measured against the vendored vector files:
  all five correct. `COUNTS` in `test_receipt_vectors.py` matches.
- **README snippet markers** — `[start:receipts]` / `[end:receipts]` paired, all five sections
  closed, the new page's include resolves, and every link in the new section is absolute.
  `mkdocs build --strict` (no `-q`) is clean and both new pages render non-empty
  (`reference/receipt/index.html` 76 KB).
- **Deployment-string carve-out** — the regex is applied to the lowered text, matches only
  `https://newgraphenvironment.github.io/crate/(stac/)?receipt/vN.N.N/schema.json`, and the six
  near-miss tests plus `test_the_carve_out_still_sees_the_other_deployment_names` pin both
  directions. No secret, no credential and no host in the diff.
