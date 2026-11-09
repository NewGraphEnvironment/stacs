# Progress — Read, write and compare provenance receipts for catalogue items (#12)

## Session 2026-11-08

- Synced `CLAUDE.md` with soul's published conventions (`17e4e9f` on `main`); `provenance.md`
  now applies to this repo and joined the appendix.
- Plan-mode exploration: read `verify.py`'s canonical form, `validate.py`'s audit, the CLI,
  `register.py`'s verify path, the test harness and docs wiring; read crate's receipt contract
  from GitHub at tag `v0.12.0` (the local checkout is at v0.11.0 and has none of it).
- Probe: ran crate's own `data-raw/receipt_vectors_crosscheck.py` against the v1.0.0 vectors in
  this repo's environment — 2,637 + 10 + 7 + 13 cases, **0 mismatches**. The hashing core needs
  no library work; the open half is `compare.json`, validation, the STAC mapping and the
  `audit` / `verify` integration.
- Probe: both published schemas answer 200, are draft-07, and carry no `$ref` with sibling
  keywords, so Python's `jsonschema` and R's ajv agree.
- Gate decisions approved by the owner: `verify` compares against the item's **mirrored identity
  fields** (stateless, no stored baseline); all seven Proposed items land in this PR.
- Created branch `12-read-write-and-compare-provenance-receip` off `origin/main` at `17e4e9f`.
- Scaffolded the PWF baseline with the approved phases.
- **Phase 2** (done first: Phase 1's tests read its vectors). `tools/crate_receipt_vendor.sh`
  vendors the contract at `v0.12.0` and re-checks it; 10 files, and both frozen schema URLs
  still serve the vendored bytes. `test.yml` runs `check` before pytest, bounded at 5 minutes.
  `tests/test_receipt_contract.py` guards it, 18 tests.
  - Two defects found by running the guards rather than reading them: the EXIT handler read a
    `local` that was out of scope by the time it fired, so a clean check exited 1
    ("tmp: unbound variable"); and the CI ordering check matched the bare word `pytest`, which
    is also the job's name, so it compared the step against the job header.
  - Mutation-checked in all three arms: an edited vendored file, a missing one, and the CI step
    removed, replaced or moved after pytest.
- **Phase 1.** `src/stacs/receipt.py`: `load_json`, `canonical`, `recipe_id`,
  `table_canonical` / `table_fingerprint`, `tolerance_decimals`, `double_from_bits`. All 2,667
  hashing vectors pass **through the module's own public API** (the only adapter is doubles,
  which the vectors give as bits). Suite: 584 passed.
  - The two canonical forms are pinned apart by a test, and each docstring now names the other.
  - The frozen URLs are written out in full rather than built from `RECEIPT_VERSION`: a
    recomposed URL reads as though a new version could be reached by changing a variable. A
    test pins each against the version and against the vendored schema's `$id`.
  - `test_no_deployment_defaults.py` gained the narrow carve-out for a versioned crate schema
    URL, with six near-miss cases (host only, another path, unversioned, another file, a
    bucket, a host) shown still failing, and a case where the schema URL and a real bucket are
    in one file and the bucket is still reported.
- **Plan review folded in** (`review-plan.md`). Spawned concurrently with Phase 2, delivered
  after Phases 2 and 1 had landed; every finding reproduced before being acted on, and nothing
  it reported was disproved. Three blockers, all confirmed by probe:
  - `json.dumps` cannot write a receipt file: JCS spells `0.000001` and `1e-9` where
    `json.dumps` writes `1e-06` and `1e-09`, and crate's worked-case receipt carries both.
    Measured. `write` re-indents the canonical text. Its corollary matters more — `jsonschema`
    4.26.0 accepts `4.0` for `{"type": "integer"}`, so `validate` is no guard against
    `parse_int=float` leaking a float into `rows`, `bytes` or `seed`.
  - crate's `equivalent` is **unreachable** from the mirrored-field pairing: four of the five
    fields are `refuse` in the register, the fifth is `record`, and `within` needs members a
    served item does not carry. Phase 6's "a rebuilt item → equivalent" could never have
    passed. Phase 6 now reports its own ladder (`same` / `rebuilt` / `changed` /
    `inconsistent`) and says so; `receipt.compare()` keeps crate's words for two receipts.
  - Both API readers reduce a feature to `body_digest(f)` and discard it, `fetch_bodies` cannot
    read an API and refuses a non-empty directory, and a `missing` id has no served side.
  - Two real holes in my own vendoring guard, both fixed and mutation-checked: the `URLS` loop
    was uncounted while the success line claimed both were checked, and `SOURCE`'s blob shas
    were decorative. They are now verified offline against the files.
  - The workflow guard now reads the step's own block: `continue-on-error: true` or an `if:` on
    it is a failure rather than a step that is present and guards nothing.
  - Also vendored, on its advice: crate's two worked-case receipts and its example item. Phase
    3's byte-identical test would otherwise have been written against Python's own output.
  Suite: 591 passed.
- **Phase 3.** `read`, `write`, `validate`, `reindent`, lazy cached access to the vendored
  contract, `jsonschema` declared and `uv lock` in the same commit.
  - **A read-and-rewrite of each of crate's two worked-case receipts is byte identical**,
    2835/2835 and 2837/2837 bytes. That pins the indentation, the collapsed empty containers,
    the canonical number spellings (`0.000001` and `1e-9`, which `json.dumps` breaks) and
    `recipe_id` itself, which `write` recomputes — so this module's id agrees with crate's for
    a real receipt and not only for the vectors.
  - The review's proposed whole-number guard was **dropped after measuring**: a whole float and
    an int are byte-identical in JCS and the schema refuses a non-whole one, so the guard would
    have changed nothing. A test pins the property instead.
  - Verified rather than assumed: a built wheel ships all five contract files under
    `stacs/data/receipt/`.
- Next: Phase 4, compare.
- **Phase 4.** `compare`, `register`, `Comparison` / `Difference`. **All nine of crate's
  receipt pairs pass on the verdict and the exact ordered `(field, action)` sequence**,
  including the 16-difference migrated case with its duplicated collection paths — the half
  crate's own crosscheck script does not implement.
  - The register is shown deciding: flipping one row's action turns `identical` into
    `different`, so the vendored CSV cannot be decoration while hard-coded actions pass the
    vectors.
  - `mode="bytes"` (re-reading supplied tables to settle a fingerprint difference) is **not
    implemented**: `compare.json` carries no tables, so it would be untested. A fingerprint
    difference says so in its detail instead of looking like a plain refusal.
  - One defect, in my own test rather than the code: it asserted the migrated receipt was side
    `a` of that vector when it is side `b`. Both directions are now asserted.
- **Phase 5.** `stac_fields`, `multihash`, `receipt_href`, `item_problems`; `require_receipt`
  through `Audit`, `audit_items`, `Target`, `describe_rules`, `build_target`, the `[catalogue]`
  config key, `cmd_audit`, `load items` and the pre-write audit in `_run`.
  - **crate's own example item passes `item_problems` with zero problems**, and `stac_fields`
    reproduces its property names, extension list and multihash forms — an oracle written by
    the other implementation, so the checks are not self-referential.
  - All three extension URLs, per the review: an item emitting `file:*` or `processing:*`
    without them is non-conformant and the field schema cannot notice.
  - Two defects found by running the tests. My `stac_fields` assertion expected the core
    `datetime` property, which a receipt must never produce. And the field schema's `oneOf`
    made jsonschema report "not valid under any of the given schemas" — useless to an
    operator — so `item_problems` now descends into the branch context, dropping each branch's
    own `type` selector first, because `best_match` prefers that shallower error. The message
    is now `properties: 'receipt:other' does not match any of the regexes: '^(?!receipt:)'`.
  - `--require-receipt` is add-only, with no `--no-require-receipt`, and a non-boolean config
    value is refused: a string is truthy, so `require_receipt = "false"` would turn the check
    on while reading as off. `load collection` does not take the flag — a collection body
    carries no receipt fields, and a flag accepted there would read as a check that passed.
- **Phase 6.** `verify.items_serving` (the reader the review showed was missing — both
  existing API readers reduce a feature to a digest and discard it), `receipt.item_verdict`
  with stacs' own four-word ladder, and `register._receipt_verdicts` wired into the verify
  branch after the id lists are written.
  - The axis runs on the **`changed`** set only, which is where "rebuilt or changed?" is the
    question; it is skipped, out loud, when nothing differs and when the collection is not
    registered (every id would read `missing`, and there is no served side at all).
  - The receipt is resolved from the item's asset with role `metadata` and against the item's
    own URL, and the receipt fetched is hashed and checked against that asset's
    `file:checksum` — otherwise a receipt read by convention could belong to anything.
  - Verdicts are reported through `warn` as a summary plus the first five, not only to
    `out_dir`, which is `None` by default. `same` says "the body differs and the recipe does
    not" rather than reading as no drift beside its own DRIFT line.
  - 11 end-to-end tests on the existing `file://` bucket and stub API, each item linking its
    own receipt.
  - **The fixtures were wrong first time, and the code was right.** They hand-wrote
    `recipe_id = "a" * 64` into both the receipt and the item, but `write` **recomputes**
    `recipe_id` from the recipe — so the published receipt carried the real id while the item
    claimed the constant, and the run correctly reported `inconsistent`. The fixtures now read
    the id back out of the written receipt, and the accidental shape became a test of its own:
    an item claiming a recipe its receipt does not have.
  - **The mutation check took three attempts to run honestly.** First attempt: the heredoc
    never applied the edit, so a green run meant nothing. Second: the mutant was present but
    `-k receipt` does not match `..._reported_as_rebuilt` or `..._reported_as_changed`, so the
    selection skipped exactly the tests the mutation targets — green again. Third, with
    `grep -c MUTANT` confirming the mutant and the whole file selected: three tests red.
    Two lessons, both already in the conventions and both worth the scar — confirm the mutant
    is in the file, and confirm the selection contains the tests it should break.
- **Phase 7.** `docs/receipts.md` and `docs/reference/receipt.md` with both nav entries,
  a `[start:receipts]` README section the page includes, the `## Unreleased` NEWS entry, and
  `research/receipt_parity.md` indexed in `research/README.md`.
  - `mkdocs build --strict` clean, no warnings, both pages rendered.
  - The research file is the durable verdict: what holds the two implementations together,
    what is **not** covered (`compare`'s bytes mode, migration, the non-STAC mapping rows),
    where they genuinely differ (crate#50's R-only 2^31-1 limit; the scalar-vs-array
    `config.settings` hazard that gives one intent two `recipe_id`s), and every measured trap.
- **`/code-check branch` round 1** (`review-round1.md`): 8 findings, 4 bug-level. **Every one
  reproduced before it was touched**, and all 8 were real — nothing to dismiss.
  - `item_verdict` chose "the item's receipt asset" with its own loop keeping the **last**
    `metadata`/`application/json` asset while `receipt_href` returned the **first**. Two
    producers for one fact, firing on *good* input: an item also carrying a QA report read
    `inconsistent` and set a non-zero status. Now one producer, `receipt_asset`.
  - `_check_keyed`'s `for ... else` did not run after a `break`, so `recipe.config` written as
    a list disabled the checks under it and the list was hashed in written order — measured,
    two ids for one intent. Depth is now refused at every level, and an absent member is still
    allowed (a migrated recipe).
  - `item_verdict` called `stac_fields(receipt)` with no `assets=`, so `file:checksum` and
    `file:size` were never compared with `result.parts`: an item contradicting its own receipt
    in both, on both sides, read `same` with `ok` true. Two of the five fields the docstring
    and the research file both quantified over.
  - `_diff` iterated the union of both sides' keys, which is empty when neither side is an
    object, so a scalar-vs-scalar difference at a branch node was dropped — `compare` answered
    `identical` for `output: "x"` against `output: "y"`.
  - A non-numeric tolerance leaked a `TypeError` out of an API that reports everything else
    as a `ReceiptError`.
  - `_receipt_verdicts` ran the whole unbounded `changed` set in one pass, holding every
    published and served body at once (which `items_serving`'s own docstring warns against),
    and aborted on the first unreadable receipt — discarding a drift answer already computed.
    Now batched by `target.chunk`, and an unreadable receipt marks its own item
    `inconsistent`, which is still never agreement.
  - Two test guards whose claims were wider than their fixtures: the wheel claim (the
    editable install reads the source tree, so it pins the layout; a second test pins that
    nothing excludes the data from the build) and a hardcoded import set (now derived with an
    `ast` walk, which finds exactly the four).
  - **A fifth bug of the same class, found by my own regression test for the fourth:**
    `compare`'s post-processing read each block with `doc.get(x) or {}`, which keeps a truthy
    non-mapping, so a scalar `recipe` crashed the one function whose job is to refuse. Every
    member read now goes through one `_mapping` helper. Suite: 743 passed.
- **Round 2 died on an API error** (ENOTFOUND) one step before writing its findings — its last
  words were "Now I'll write the findings file". No file, so the round produced nothing and
  was re-run to its own path (`review-round2b.md`); an idle or failed round is never recorded
  as Clean.
- **Enumeration** (`review-enumeration.md`), which is what has to end the loop now that a
  defect has been found inside a fix. Parsed with `ast` rather than recalled:
  - "one fact derived twice" is **closed**: the predicate selecting the receipt-linking asset
    appears exactly once, with four consumers all routed through it and no re-derivation.
  - "a member read as a mapping without being one": 11 member reads, 10 guarded or provably
    dict (each with a stated reason — an `isinstance` guard, a constructed return value, or
    `read_config` refusing any table that is not a table), and **1 real instance left**,
    `(recipe.get("code") or {}).items()` in `stac_fields`, which `item_verdict` reaches on a
    receipt nothing validated. Fixed; the enumeration script now exits 0. Suite: 746 passed.
- **`/code-check branch` round 2b** (`review-round2b.md`; round 2 itself died on an API error):
  three bugs and one dead assertion, **all four reproduced**.
  - **`_diff`'s COLLECTION arm had exactly the hole round 1 closed in the BRANCH arm** — the
    sibling two lines up, tested first, untouched. `keys()` is empty for a non-mapping, so two
    non-mappings at a collection path compared nothing and `compare` answered `identical`.
    Enumerated: **11 register patterns are both a collection and a leaf row**, so all eleven
    were silent, and `recipe.inputs` as a list was called `identical` by the same contract
    whose `recipe_id` refuses to hash it. This is the round 1 mechanism one axis over, which
    is the whole reason the loop keeps going.
  - **Two items linking one receipt made every one of them read `inconsistent`** — measured
    5/5. `_receipt_verdicts` is the first call site in the package whose URL list can
    legitimately repeat; one worker per URL meant two writing the same `.part` path and racing
    the rename, so the loser reported a failure for a body correctly on disk. Deduped at the
    call site, and `fetch_bodies` now refuses a repeated URL rather than mis-reporting.
    The fixtures elsewhere give each item its own href precisely to avoid this, which is what
    hid it: the one shape they steer around is the one that failed.
  - A non-string asset href was used as a dict key, raising `TypeError: unhashable type` out
    of `item_verdict` on the verify path, where nothing audits first.
  - **One of my round 1 regression assertions could not fail**:
    `assert verdict in ITEM_VERDICTS or verdict in ("identical","equivalent","different")` is
    true for every value `compare` can return — and it was green against the wrong `identical`
    verdicts above. Both such assertions now pin the verdict.
  - The reviewer also corrected my enumeration's closing claim, rightly: "0 unguarded member
    reads" is what it establishes, not "0 instances of the mechanism". It now walks four
    populations, and the two public keyword arguments that were walked with `.items()` refuse
    a non-mapping. Suite: 779 passed.
- **`/code-check branch` round 3**, the most valuable round, and largely a critique of my own
  work (`review-round3.md`). Three bugs, two fragilities, **all reproduced**:
  - **My round 2b fix was incomplete.** `walkable = isinstance(x, dict) or isinstance(y, dict)`
    passes when ONE side is a mapping, and the arm then compares key sets only — so an EMPTY
    mapping against a list left all three key sets empty and `compare` answered `identical`
    again. Measured mechanically: **154 violations over 3,816 differing pairs, 14 at each of
    the 11 collection patterns** — the same blast radius, re-opened one axis over. Third
    attempt: the arm now requires both sides to be a mapping *or absent*, which also preserves
    the migrated-receipt vector's per-key rows.
  - **`item_verdict` said `same` with `ok` true for an item contradicting its receipt**
    whenever `result`, `result.parts` or the item's `assets` was a non-mapping: `_mapping`
    makes it `{}` and the asset half of the check — the half round 1 added for this exact
    symptom — was skipped for every asset. 12 of 24 malformed nodes. **And a test of mine
    pinned the wrong answer**, asserting `same` for a garbage receipt.
  - `item_verdict` sat outside `_receipt_verdicts`' `except`, and it raises on input `read`
    accepts (a non-hex recipe_id, a non-ISO time, a NaN in a mirrored property).
    `ReceiptError` subclasses `ValueError`, so it escaped `run`'s handler to exit 2, naming
    neither item nor URL and discarding everything already computed.
  - The duplicate-URL scan I added in round 2b was O(n²): **67 s of CPU before the first fetch**
    on a 102,460-item catalogue. Now O(n).
  - `receipts_*.txt` were written even when the axis never ran, making "clean" and "not
    checked" the same bytes.
  - It also audited my enumeration and found **five** ways it was too narrow — including that
    population D could not see `_diff` at all (its `keys` is a local function, not an
    attribute), so *the site of the two worst defects was outside every population I walked*,
    and that one dismissal was factually wrong because I took a line number against the wrong
    commit. Recorded in `review-enumeration.md`.
- **The loop ends on three mechanical post-conditions**, not on a quiet round: the register-wide
  difference property (mutation-verified, with a 22-case carve-out that matches crate's own
  walk, checked at crate's source), the `same ⟹ readable nodes` property enumerated from
  `receipt.VERDICT_NODES`, and round 3's classification of every `_mapping`/`keys()` site by
  its consumer's default — all 8 agreement-default sites now refuse or are total.
  Suite: 813 passed.
- **A faithfulness failure of my own, caught by running the code rather than reading my
  commit.** The commit for round 3 (`df872c4`) claimed three fixes that were **not in the
  tree**: the deduped fetch log count, the `except receipt.ReceiptError` guard around
  `item_verdict`, and the O(n) duplicate scan. The script that applied them aborted on a later
  needle, and because each file is written only after all of its needles match, that file's
  edits were discarded — silently, while the commit message asserted them. Found when a new
  test's assertion on the log text failed and the log showed the old wording.
  - Applied for real, each one verified present by grep **before** committing, and the dedupe
    measured at 0.005 s for 100,000 URLs against the 67 s round 3 measured.
  - The lesson is the one this branch keeps relearning in a new costume: **a claim needs its
    own check.** A commit message is a claim about a tree, and nothing verified it.
  - Also added: a post-condition that `_receipt_verdicts` returns a verdict for every id it
    was given, so an id dropped between batches cannot be absent from a summary that still
    looks complete. Suite: 814 passed.
