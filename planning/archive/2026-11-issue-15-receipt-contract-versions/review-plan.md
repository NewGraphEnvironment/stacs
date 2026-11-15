# Plan review — stacs#15

A read-only Plan agent, spawned 2026-11-15T21:53Z against the baseline (`761574b`), reading the
plan, the issue, the code it names and crate at `v0.16.0`. It ran no stacs code. Its findings,
condensed, each with what was done. Every claim acted on was reproduced first.

| # | tag | finding | disposition |
|---|---|---|---|
| F1 | Blocker | `REGISTER_URL` and `MAPPING_URL` in `receipt.py` trip `tests/test_no_deployment_defaults.py`, whose carve-out is the two schema URLs | Already met while building Phase 1, same remedy: no URL constants; the `URLS` rows are pinned to the version constants by a test |
| F2 | Gap | `docs/receipts.md` is one include line; the prose is `README.md` between the `receipts` markers | Phase 4 edits the README section |
| F3 | Gap | `Comparison.register` would name a constant while `register()` read a literal path | `register()` builds its path from `REGISTER_VERSION`; the runners build their directories from the constants |
| F4 | Gap | `multihash` and `_whole` carry no code, and one site refused both an absent part and a non-object part | `stac_fields` checks and codes each itself before the helpers; `_whole` takes the code; the part lookup is split |
| F5 | Assumption | crate's R raises `assets_not_named` and `href_empty`, which its README table, `stac.json` and cross-check do not hold | Reproduced (`R/crt_receipt_stac.R`, `stac_assets_arg`). stacs coins no code the published contract lacks; filed with crate as a gap. stacs still publishes an asset keyed `""` |
| F6 | Assumption | "the three byte-identical files" is two: the vendored `mapping.csv` was v1.0.0, which decision 2 does not vendor | `register.csv` and `compare.json` moved; `mapping.csv` removed and v1.1.0 written by `vendor` |
| F7 | Assumption | "migrated" must be key presence, and no vector tells presence from value | Already by presence; `test_a_receipt_is_migrated_by_the_presence_of_the_key_not_its_value` added |
| F8 | Assumption | a real instant must be arithmetic: year 0000 is valid to the form and to crate | Already arithmetic; pinned with F17 |
| F9 | Gap | `item_verdict` returned `inconsistent` for a receipt node that is a string and raised for one that is null; `output` and `recipe.code` are in no node list | Reproduced. `item_verdict` now returns `inconsistent` with the mapping's code in the note for any receipt the mapping refuses; 12 cases pinned |
| F10 | Gap | `item_verdict`'s own walk of the assets skipped a part that is present but not an object, ending in `same` | Reproduced (`same`). Now a disagreement at `result.parts[<href>]`; 4 cases pinned |
| F11 | Gap | tests asserting today's leniency, one of which must be inverted (a malformed `recipe.code` was read as "no repositories") | Done: 31 tests were red; fixtures gained the form version, an instant and a recipe identity, and the `recipe.code` test now asserts the refusal |
| F12 | Gap | decision 6 had no test, and `stac.json` reaches `stac_fields` only | Eight audit cases, three accept cases and two `multihash` cases added; each has a mutation row |
| F13 | Gap | "at least 0" belongs in `_whole`, or the audit still passes `file:size: -1` | In `_whole`; NEWS says so |
| F14 | Scope | NEWS omitted what an operator sees; the `except` branch of `_receipt_verdicts` had no test | NEWS lines in Phase 4; `test_a_receipt_the_mapping_refuses_marks_its_item_inconsistent` runs the verify harness with a `write`-produced month-13 receipt |
| F15 | Ordering | "red at 55" cannot come from a by-code runner | Two baselines recorded in `findings.md`; no red commit |
| F16 | Ordering | `MAPPING_VERSION` lands a phase before the code that meets it | Phase 1 is not pushed alone |
| F17 | Acceptance | the vectors hold two years and two month lengths; presence of `migrated_from` and the century rule are unpinned | `test_an_instant_is_real_by_the_calendar_not_by_its_shape`, 12 cases |
| F18 | Acceptance | "exactly the 17" must have a static source | Four statements held to one set: `STAC_REFUSALS`, the `code="..."` literals in the module's source, the codes in `stac.json`, and the code table in the vendored README |
| F19 | Acceptance | the stray-file guard needs `SOURCE` exempted by exact path and a stated population | Filesystem walk from the two roots, `SOURCE` exempted by path, dotfiles ignored, shown saying no on a copy |
| F20 | Acceptance | `REGISTER_VERSION` equals `RECEIPT_VERSION`, so a substring pin cannot tell them apart | The four `URLS` rows are asserted as one exact mapping, both columns |

Found sound by the reviewer: the blobs at `v0.16.0` against `SOURCE`; seven `STAC item` rows in
mapping v1.1.0; `overrides` as planned matching crate; one reader of `register.csv`; the verify
fixtures going through `write`; `Comparison` gaining fields breaking nothing; guard order equal
in crate's R and its Python cross-check, where 34 of the 142 cases trip more than one guard and
every one of them is `block_not_object` against reading that block as absent.

Not checked by the reviewer: it ran no code, and did not read the form schema's patterns or
crate's vector generator.

One thing its "not checked" list raised and a probe confirmed: `write` accepts a `context.time`
of month 13, because the form schema's pattern does, and `stac_fields` then refuses the receipt
it wrote. Left as it is: `write` validates against the form, and the form is crate's.
