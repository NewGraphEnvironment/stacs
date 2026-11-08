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
