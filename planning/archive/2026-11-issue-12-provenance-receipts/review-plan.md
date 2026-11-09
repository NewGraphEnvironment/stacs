# Plan review (#12), with verification

A `Plan` subagent reviewed `task_plan.md` against the issue body and the code, spawned
concurrently with Phase 2 and delivered after Phases 2 and 1 had landed. Plan agents have no
Write tool, so the review arrived as reply text and is recorded here.

**Every finding below was reproduced before it was acted on**, in both directions — a review is
wrong loudly in the alarming direction and quietly in the reassuring one. Probes and verdicts
are mine; the findings are the reviewer's.

## Blockers

### B1 — `json.dumps` cannot reproduce a receipt file's bytes. **CONFIRMED, already avoided**

crate writes the file by re-indenting the canonical JCS **text** (`jsonlite::prettify`), so
every number keeps its JCS spelling. Python's `json.dumps` spells several differently:

| value | JCS (`rfc8785`) | `json.dumps` |
|---|---|---|
| `1e-6` | `0.000001` | `1e-06` |
| `1e-9` | `1e-9` | `1e-09` |
| `1e16` | `10000000000000000` | `1e+16` |
| `4.0` | `4` | `4.0` |

Measured in this repo's venv. And the worked-case receipt carries the first two as ordinary
content — `"km_total": 0.000001` (line 104) and `"km": 1e-9` (line 108), both legal members of
the `tolerance` enum. So `write` re-indents the canonical bytes; it never re-serialises an
object.

The reviewer's corollary is the more useful half: **`jsonschema` will not catch the float
contamination either.** Measured with the installed 4.26.0, `4.0` **passes**
`{"type": "integer"}` under draft-07. So `validate` is no guard against `parse_int=float`
leaking a float into `rows`, `bytes` or `seed`; the byte-identical round-trip against crate's
two worked-case receipts is the guard, and `write` checks whole-number members itself.

### B2 — crate's `equivalent` is unreachable from the mirrored-field pairing. **CONFIRMED**

The five mirrored fields map to these register rows (verified against the vendored
`register.csv`):

| mirrored field | receipt key | action |
|---|---|---|
| `receipt:recipe_id` | `recipe.recipe_id` | refuse |
| `file:checksum` | `result.parts.*.sha256` | refuse |
| `file:size` | `result.parts.*.bytes` | refuse |
| `processing:software.<repo>` | `recipe.code.*.version` | refuse |
| `processing:datetime` | `context.time` | record |

`within` is never an action in the register — its two occurrences there are in the `why`
prose. The comparison produces it from three places, and all three need members that are not
mirrored: `result.summary.*` with a matching `result.tolerance.summary`; `result.parts.*.table`
with both `result.fingerprint` maps; or `result.fingerprint.*.sha256` re-read from supplied
tables. A served item carries none of them. With the verdict algebra
any-`refuse`→different, else any-`within`→equivalent, else identical, the reachable set is
exactly **`identical`** and **`different`**.

**Accepted, and the plan is corrected** (the reviewer's option (a)): comparing a full receipt
against a five-field projection of itself is not a receipt pair, so it does not get crate's
words. `receipt.compare()` keeps `identical` / `equivalent` / `different` for two receipts, as
the vectors require. `verify` reports its own ladder — `same`, `rebuilt`, `changed`,
`inconsistent` — and says in its output that these are not crate's verdicts. The issue's
intent ("a rebuilt item can be told apart from a changed one") is met by `rebuilt`, which is
precisely the case crate cannot name here.

### B3 — nothing retains a served body, and a `missing` id has no served side. **CONFIRMED**

`verify.py:144` and `verify.py:217` both reduce a feature to `body_digest(f)` and discard it,
so the served side needs a reader that returns the mirrored properties. `fetch_bodies` is the
published-side URL fetcher and cannot read an API; it also refuses a non-empty directory
(`catalogue.py:166-170`), and `fetch_dir` is full by then, so receipts need their own. For an
id in `missing` the API serves nothing, so the only available pairing is published item ↔ its
own receipt.

**Accepted.** A new `fields_serving` in `stacs.verify` returns selected properties per id over
the existing paging; receipts fetch into their own directory; a `missing` id is checked for
consistency with its own receipt only, and the output says so.

## Gaps accepted and folded in

| # | finding | verdict and disposition |
|---|---|---|
| G1 | the worked-case receipts were not vendored, so Phase 3's byte-identical test had no oracle and would have been written against Python's own output | CONFIRMED. Vendored both, plus the example item; 13 files now |
| G2 | crate's example item lists **three** extension URLs (`file/v2.1.0`, `processing/v1.2.0`, receipt) and the plan named only the receipt one | CONFIRMED by reading the vendored item. All three become constants, and `audit` requires each whose fields are present |
| G3 | the example item's `receipt` asset carries its own `file:checksum`, and `mapping.csv` has no row for it — `stac_fields` cannot compute it | CONFIRMED (six `STAC item` rows, none for it). `write` returns the digest of the bytes it wrote; `stac_fields` takes it as an argument. This also gives `verify` a far stronger check than the mirrored compare: the receipt it fetched is the one the item claims |
| G4 | the field schema constrains only `stac_extensions`, `type` and `receipt:recipe_id`; it says nothing about `file:*` or `processing:*`, whose own schemas are unfetchable offline | CONFIRMED. Those checks are `audit`'s own: `^1220[0-9a-f]{64}$` for a multihash, the receipt schema's `context.time` pattern for `processing:datetime` |
| G5 | `verify` reaches the catalogue only through `Target`, so it cannot know receipts are declared | CONFIRMED. `Target` gains the flag, `Target.check()` a type check, `build_target` and the config key the wiring. A bool default is safe under the deployment guard, which exempts bools |
| G6 | `_run`'s pre-write audit passes only the asset rules, so `audit` would refuse what `register` loads | CONFIRMED. The rule is passed at the pre-write audit too |
| G7 | `_write_list` is a no-op when `out_dir is None`, which is `cmd_verify`'s default, so the per-item verdicts would go nowhere in the default invocation | CONFIRMED. Verdicts are warned as a summary plus the first five, as the DRIFT block does, and written to `out_dir` when there is one |
| G8 | "receipt.json beside the item" is a convention; the contract says the receipt is **linked as an asset with role `metadata`**, and the test harness writes every item flat, so the convention would make one shared receipt for every fixture item | CONFIRMED by the example item. The href is resolved from the asset and against the item's own URL |
| G10 | "only missing/changed" is a filter, not a bound: on an unregistered collection every id is `missing` | CONFIRMED. The axis is skipped when the collection is not registered, and bounded |
| (a) | the vendor script's `URLS` loop has no non-empty guard, while the success line claims both URLs were checked | CONFIRMED in my own script. Fixed, with a mutation check |
| (a) | `check` never validates `SOURCE`, so its blob shas are decorative | CONFIRMED. A test recomputes each git blob sha and compares — offline, so it runs everywhere |
| (b) | the workflow guard cannot see a step-level `continue-on-error: true` or `if: false` | CONFIRMED. The guard now reads the step's own block |
| #1 | `rules` is coupled by exact string to four existing tests | CONFIRMED. The no-rules string stays byte-identical |
| #4 | resolve package data lazily, not at import: every module is imported by the deployment guard's walk and by `--doctest-modules`, so an import-time read turns a missing file into a suite-wide collection error | CONFIRMED as a hazard. Data is loaded lazily and cached |
| #5 | `fetch_bodies` prints failures to stderr directly, bypassing the injected `warn` | CONFIRMED. An unread receipt raises from the returned failed list rather than relying on the print |
| #6 | an `identical` receipt verdict on a `changed` id is the common case (a bbox fix changes the body, not the recipe) and the plan did not say what it prints | ACCEPTED as the clearest thing the reviewer found about output. `same` on a drifting item is reported as "the body differs and the recipe does not", not as a bare verdict |

## Noted, not acted on

- **G9** — `mapping.csv`'s sixth `STAC item` row, `properties.version ← context.legacy`, is a
  release label rather than provenance, and out of scope for #12. Said so rather than left
  silent.
- **Ordering 1** — the deployment-guard carve-out belonged in Phase 1 rather than only in
  Validation. It landed in the Phase 1 commit before this review arrived.
- **Ordering 2** — `jsonschema` and `uv lock` in one commit, and a test asserting it is
  declared rather than reached transitively. Folded into Phase 3.
- **#8** — `test.yml` still has no job-level `concurrency`. Out of scope for #12; the new
  network step is only the reason it starts to matter.

## Where the reviewer was wrong

Nothing it reported was disproved. One claim it made in passing is right for the wrong reason:
it warned against PyYAML in the workflow guard because it is absent from CI's dependency
groups. Confirmed (`import yaml` is an ImportError in this venv), so the guard stays a text
scan — but the reason to keep it a text scan is that the guard's subject is the file's bytes,
not a parsed document: a YAML loader would accept a workflow GitHub rejects.
