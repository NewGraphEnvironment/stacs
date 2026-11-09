# Code check — round 1, branch `12-read-write-and-compare-provenance-receip`

Base `17e4e9f930085bd99ed4b8915995525affca5868`. Suite re-run on this tree: `702 passed`.
Wheel built locally to settle one claim (`uv build --wheel`): `stacs/data/receipt/**` does ship.

## Checklist read

- `code-check-python.md` — **in full** (all 6 headings).
- `code-check.md` — the prose of **13 of the 14** H3 under `## Mechanisms` in full (skipping `|`
  table rows): guard that fails toward pass, fixture that cannot reach the failure mode, proxy is
  not the property, verification that reads its own output, a guard's scope, a fix lands in one of
  two callers, restore the bug and prove the guard fires, a wrapper's exit is not the work,
  zero-length/empty/unset, the probe is broken before the world is, written data outlives the fix,
  serialization loses meaning silently, one fact derived twice. The 14th ("A shared working tree,
  and what generators leave in it") skimmed to its first ~40 lines and judged not to apply — no
  generator, worktree or release step in this diff. Of the 15 "Rules that stand alone" I read in
  full: "An ordered dispatch makes severity ordering load-bearing", "An assertion that matches an
  interpolated value" and the Security block's index lines; the remaining 12 were read as index
  lines only and judged not to touch this diff (no YAML booleans, no URLs built from filenames, no
  preview flag, no expiring credentials, no human-tested artifact, no spreadsheets/PDFs).
- `code-check-shell.md` — read in full the 10 headings the vendor script's shapes name: heredoc
  precedence in pipelines; a heredoc whose body contains its own delimiter; reading a file
  line-by-line drops the last line; empty arrays under `set -u` on bash 3.2; quoting; `mktemp`
  template needs enough X's (index line); a second `trap … EXIT` replaces the first; put cleanup on
  the EXIT trap, not RETURN; a failed `cd` lets every later command run in the directory you were
  already in; bash 3.2 quote-matching a heredoc inside `$( )`; `a && b || c`. Roughly 60 further
  headings read as index lines only (git/gh/aws/docker/psql/sips — none of those commands appear).
- `code-check-r.md` — index lines only; no R in this diff. Checked the four that cross languages
  (ajv vs Python `jsonschema` sibling-keyword rule; locale-dependent sorting; `-0`/`0` digesting
  differently; Postgres row order) against `receipt.py`'s sorting and the two vendored schemas — all
  three sorts are explicit byte/code-unit orders, both schemas keep every `$ref` alone, and `-0.0`
  is normalised in both canonical forms and in `_cell`.

The vendored `tests/vectors/**` and `src/stacs/data/**` were read where a finding needed them
(`register.csv`, both schemas, `SOURCE`) but not reviewed as authored code.

## Findings

- **[bug]** `src/stacs/receipt.py:1275-1283` — `item_verdict` resolves "the item's receipt asset"
  with its own loop that keeps the **last** asset with role `metadata` and type `application/json`
  (no `break`), while the receipt that was actually fetched was chosen by `receipt_href`
  (`:1100-1108`), which returns the **first** match. The two sides of the digest comparison
  therefore have different producers, so the guard fires on good input. An item that also carries,
  say, a QA report or a legacy `provenance.json` as a `metadata` + `application/json` asset is
  reported `inconsistent` and `register.py:689-705` turns that into `rc 1`. Reproduced on this tree:

  ```
  receipt_href picks: a0_receipt.json
  verdict: inconsistent ('assets[receipt].file:checksum',)
    "the receipt fetched hashes to 1220bbbb…, and the item's receipt asset claims 1220cccc…"
  ```

  `receipt_href` is also the stricter of the two (it requires a non-empty string `href`), so the
  digest loop can select an asset `receipt_href` would never return. Resolving the asset once — one
  helper returning the asset, used by `receipt_href`, `item_problems` and `item_verdict` — removes
  the disagreement.
  - **Rule:** code-check.md "One fact derived twice"

- **[bug]** `src/stacs/receipt.py:209-220` — `_check_keyed`'s `for part in path: … else:` skips the
  check entirely whenever an **intermediate** node is not a dict, because the `break` has no `else`
  arm. So `recipe.config` written as a list disables both the `config.files` and the
  `config.settings` checks and the list is hashed in the order it was written — the exact failure
  the guard exists to prevent ("a list would hash in the order it was written"). Measured on this
  tree:

  ```
  recipe_id({**EMPTY, "config": ["settings.csv", "other.csv"]}) -> 86faa373…
  recipe_id({**EMPTY, "config": ["other.csv", "settings.csv"]}) -> 235eb0e5…   # two ids, one intent
  ```

  `write()` would refuse this body at `validate()`, but `recipe_id()` is public and documented as
  the thing a builder stamps onto an item, and it refuses nothing here. The error path and the
  "nothing to check" path are the same path: raise when a node on the way down is present and not a
  dict.
  - **Rule:** code-check.md "A guard that fails toward pass"

- **[bug]** `src/stacs/receipt.py:1291-1300` — `item_verdict` builds `claimed = stac_fields(receipt)`
  with **no `assets=` argument**, so `claimed["assets"]` is always `{}` and only the three
  `properties` are compared with the published item. The other two mirrored fields —
  `file:checksum` and `file:size`, which `_RESULT_ASSET_FIELDS` names and `_mirrored` does compare
  between the two sides — are never checked against `result.parts`. An item whose asset digest
  contradicts the receipt it links is therefore reported as agreement:

  ```
  published asset contradicts receipt, served matches it -> rebuilt
  both sides contradict the receipt                      -> same   (ok == True)
  ```

  `same` sets no `rc` in `register.py:704`, so that item passes the receipt axis. The docstring at
  `:1255-1256` ("an item whose mirrored fields do not match the receipt beside it is `inconsistent`
  whatever the two sides agree on") and `research/receipt_parity.md` ("`verify` has one receipt and
  the five identity fields an item mirrors") both quantify over five fields where the code reads
  three. The map it needs is already in the item: the asset keys whose `href` is a part.
  - **Rule:** code-check.md "A guard that fails toward pass"

- **[bug]** `src/stacs/receipt.py:834-838` — `_diff`'s walk has three arms (collection, leaf, branch)
  and the branch arm iterates `keys(x) + keys(y)`, which is `[]` when **neither** side is a dict. A
  difference at any branch node that is a scalar on both sides is silently dropped, so `compare`
  reports agreement:

  ```
  compare({"output": "x", …}, {"output": "y", …})            -> identical, no differences
  compare({"recipe": {"config": "one"}}, {… "config": "two"}) -> identical, no differences
  ```

  (A dict on one side and a scalar on the other is reported correctly; it is the both-scalar case
  that rests at "agrees".) `compare` validates nothing and `read` only checks the version, so a
  hand-edited or foreign receipt reaches this. For the function whose job is to refuse, the
  outcome nobody enumerated should stop the comparison, not pass it — raise, or treat a non-dict at
  a branch as a leaf and compare it.
  - **Rule:** code-check.md "A guard that fails toward pass"

- **[fragile]** `src/stacs/receipt.py:925` — `abs(va - vb) <= tol` type-checks `va` and `vb`
  (`numbers`) but not `tol`, which comes straight from `result.tolerance.summary` on both receipts.
  A receipt whose tolerance is a string (the schema's `enum` forbids it; `read()` does not validate)
  raises `TypeError: '<=' not supported between instances of 'float' and 'str'` out of a public API
  that raises `ReceiptError` for every other malformed input. One `isinstance` beside the `numbers`
  check, or `tolerance_decimals(tol)` to reuse the existing refusal.
  - **Rule:** none

- **[fragile]** `src/stacs/register.py:805-868` — `_receipt_verdicts` is called with the whole
  `changed` set (`register.py:657`), which is unbounded: a publisher-wide rebuild or a pgstac
  round-trip change makes `changed` the entire catalogue. Three consequences on the 102k-item
  catalogue this package is written for: one HTTP fetch per changed item for the receipts; every
  changed **published** body and every changed **served** body held in memory at once, which is what
  `items_serving`'s own docstring tells callers not to do ("Deliberately not the basis of
  `bodies_serving` … Call this on a subset"); and `:841-843` aborting the whole run on the first
  unreadable receipt, after the drift answer has already been computed, where partial failure over
  ~10^5 fetches is close to certain. The DRIFT counts on stdout and the `--out-dir` lists survive
  that abort (they are written at `:638-645`), but the `DRIFT:`/`RECEIPTS:` stderr summary does not.
  "An unread receipt is never agreement" is right; marking that *item* `inconsistent` keeps it
  without discarding the run.
  - **Rule:** code-check.md "A guard that fails toward pass" (its mirror mistake — failing toward
    abort where partial failure is certain)

- **[fragile]** `tests/test_package.py:25-35` — `test_the_vendored_contract_is_importable_package_data`
  says it stops "a wheel that shipped only the .py files [passing] every test in a source tree", but
  `uv sync` installs this project editable (`.venv/lib/python3.12/site-packages/stacs.pth` ->
  `<repo>/src`), so `resources.files("stacs")` resolves to the source tree and the test cannot reach
  the failure it names. It does pin "the data is inside the package directory", which is most of
  what `uv_build` needs — and the wheel I built from this tree does carry all five files — so
  nothing is broken today; the claim is just wider than the fixture. Listing the built wheel (or
  `wheel-exclude`) is the only thing that can see it.
  - **Rule:** code-check.md "A fixture that cannot reach the failure mode"

- **[fragile]** `tests/test_package.py:15-23` — `test_every_directly_imported_third_party_package_is_declared`
  asserts a hardcoded four-name set is a subset of `[project.dependencies]`. A fifth direct import
  added later — the case the name promises to cover, and the one the `jsonschema` comment describes —
  is not caught. The import set is derivable (walk `src/stacs/**/*.py`'s `ast` imports, drop stdlib
  and `stacs`), which turns the curated list into an enumeration.
  - **Rule:** code-check.md "A guard's scope, escape hatches, and remedies"

## Checked and clean (not findings)

- `reindent()` — fuzzed 20,000 random documents built from brace/bracket/comma/colon/quote/backslash/
  control-character/astral strings: for every one, `canonical(load_json(reindent(c))) == c`, and
  stripping the inserted whitespace outside strings reproduces `c` byte for byte. Nothing inside a
  string is touched and no number is re-spelled.
- `_atomic_write` — temp mode set before `os.replace` (target's own `S_IMODE` where it exists,
  `0o666 & ~umask` where it does not); tests cover both paths. Matches
  code-check-python.md "`tempfile.mkstemp` then `os.replace` leaves the target at mode 0600".
- Python floor — every new/changed `.py` parses under 3.11 and 3.9 ASTs (no newline inside an
  f-string's braces); `resources.files(...).joinpath(a, b, c)` returns a `pathlib.Path` for a regular
  package on 3.11, so the multi-arg `joinpath` is safe below 3.12.
- `tools/crate_receipt_vendor.sh` — one `EXIT` handler reading a global armed before `mktemp`;
  both `while read` loops fed by heredocs (not pipes), so `bad`/`n`/`u` survive; `printf '%s\n'`
  guarantees a terminating newline, so no row is dropped; `curl -sS --fail -L --max-time 120` plus a
  `-s` non-empty check; `FROZEN_URLS=2` counted against the loop; no `a && b || c`; `cd` guarded by
  `set -e` and by `&& pwd`; no heredoc body can contain `EOF`/`INNER`; no command substitution
  wrapping a heredoc. A failed `git hash-object` inside the SOURCE writer would silently write a
  blank sha, and `test_the_source_record_names_the_repo_and_tag_it_was_vendored_from` catches that.
- The deployment-string carve-out — `.lower()` before a lowercase-only pattern cannot widen it
  beyond case; six near-miss tests plus a both-in-one-file test; the substitution leaves every other
  known name visible.
- `register.csv` walk — all four `within` paths (summary tolerance, the two `result.parts.*`
  promotions via `table_agrees`, and the migrated-receipt refusal) agree with the register's own
  `why` column, and `table_agrees` reads "no fingerprint row differs for this table", which is the
  right reading in `receipts` mode.
- Dataclass field insertion — `require_receipt` lands mid-`Audit`, and `validate.py:179` is the only
  construction site, positional and correct.
- mkdocs — `mkdocs build` (strict, no `-q`) passes with the two new pages; the new README section's
  `[start:receipts]`/`[end:receipts]` markers are balanced and its links are absolute; no docstring
  or page names `CLAUDE.md`, `planning/` or `research/`.
- No secrets, no argv-passed credentials, no real host, bucket, database or API default in the new
  code or fixtures.
