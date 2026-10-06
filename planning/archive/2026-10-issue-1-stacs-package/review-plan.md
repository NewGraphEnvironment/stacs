# Plan review (Plan agent, 2026-10-06) — condensed record

Checked against stac_dem_bc origin/main 763f17d. The reviewer is read-only; this file was
written by the parent from its reply. Disposition column: **folded** = now in
task_plan.md; **declined** = reason given.

| id | finding | disposition |
|---|---|---|
| B1 | Guards living in `register_manifest.py` `main()` branches (fetched-paths 781-804, hrefs-published --ids-file 723-741, audit-items 813-864 incl. `--dir` excluding collection.json, verify-serving 881-915, diff 752-772) are not in the move table; fetched-paths' body-names-another-id refusal is the guard `--all`/`--ids` rely on before writing | folded (Phase 3, 4) |
| B2 | Transport boundary undefined: prelude mixes deployment facts (`.env`, PATH, cwd, `uv run`) with stacs-owned ones (PG* exports, db); free-form prelude goes into ssh argv, so a literal password in config would land in `ps` | folded: structured, quoted fields; stacs emits PG* after sourcing; password by host-side variable NAME only |
| G1 | Shell guards missing from Phase 4: --ids input normalisation; probe position (before fetch, every writing mode); fetch gate on files on disk + stderr report; collection_state tri-state; verify reports all directions; drift collection-only path; audit only when todo>0; orphans not a failure after write; dryrun previews; startup banner incl. "asset audit: none"; local WRITTEN==EXPECTED; zero items exits 0; one load = one transaction, never chunk; payload fully assembled before ssh; remote set -euo pipefail + trap; collection exactly 1 line; BatchMode on the write ssh too; option injection via host `-o...` | folded |
| G2 | "Any value overridable by a flag" reopens what #42 closed; rules must not follow the collection id; flags may add, never remove | folded |
| G3 | uav/orthophoto/floodplains call item_register.sh / collection_register.sh directly; without `stacs load items|collection` they have nothing to adopt | folded (Phase 5) |
| G4 | send payload sha256 too | declined: line count + one-transaction load already refuse truncation; corruption in transit is ssh's job |
| G5 | count gates → set gates where in-process Python allows | folded |
| G6 | bare `#NN` in extracted docstrings point at stacs issues | folded (Phase 1 port carries none; checked) |
| G7 | deps per phase (rfc8785, pystac[validation]; tomllib is stdlib) | folded |
| G8 | open() without encoding | folded (Phase 1 fix) |
| G9 | no release step before adoption issues | folded: issues say "pin v0.1.0 once tagged"; tag is /gh-pr-merge's |
| J1 | only ints > 2^53 need converting; that collapses distinct big ints (pin as decision); 1.5e300 served as 301-digit int reads changed forever today and equal under the plan; ints > 1.8e308 OverflowError → named error; `type(x) is int` not isinstance; drop float→int | folded |
| J2 | NaN/Infinity accepted by json.loads; rfc8785 raises → named per-item error; scan live in Phase 6 | folded |
| J3 | non-ASCII digests change (harmless, nothing stored — confirmed); lone surrogates raise → named error | folded |
| J4 | assert an RFC 8785 Appendix vector, not only self-consistency | folded |
| J5 | rfc8785 is pure Python; ~205k digests per verify — benchmark | folded |
| T1 | encoder-dependent tests need an inline reference encoder | done in Phase 1 |
| T2 | test_item_migrate.py holds audit_items and expect_collection tests | folded (Phase 3, 4) |
| T3 | network-proof test goes vacuous on example.invalid (DNS fails anyway); assert on the proxy reason | folded |
| T4 | declared-rule cases must keep: policy printed at startup/dryrun; flag cannot loosen; old collection id does not drop rules; forbid parsing to nothing says so; refusal before any fetch | folded |
| T5 | untested shell guards: id mismatch, zero published, --ids guards, failed probe, remote truncation, db regex, paging no-token/repeat, retries/404 vs 5xx with injected sleep | folded |
| T6 | ssh stub conventions must match the new remote command shape | folded |
| T7 | real names in fixtures | done in Phase 1 (example.invalid) |
| — | grep guard publishes the names it searches for | accepted: the names are already public in the issue body and README; the structural (inspect) check is the primary guard |
| — | PAGE_SIZE / chunk tuned to one API's max_limit | folded: config fields with the current values as defaults (not deployment facts — they are paging sizes) |
| O1 | config needed in Phase 4 → typed dataclass at the start of Phase 4 | folded |
| O2 | Phase 4 tests run `register.run(cfg)` in-process | folded |
| O3 | parity failure not attributable to extraction vs JCS → verdict-equivalence check old vs new digest item by item | folded (Phase 6) |
| O4/O5 | audit tests before Phase 4; release before Phase 7 | folded |
| A1 | relative hrefs: resolve against collection.json URL or refuse with a test | folded: resolve with urljoin |
| A2 | remote shell assumed bash → wrap in `bash -c` | folded |
| A3 | stac-fastapi next-link-body paging dialect → README | folded |
| A4 | shell's --all/--ids dedupe was locale-collated; Python sets differ | noted for Phase 6 |
| A5 | live commands with real hosts in a public repo | folded: record numbers by collection, API as `$API` |
| S1 | which validators stay build-side, per repo | folded into Phase 7 issues |
| S2 | no pystac validation inside register | agreed |
| S4 | --ids upserts the collection but never re-checks the catalogue | kept for parity; prints "run verify after" |
| AC1 | shell --verify prints head -5 and deletes $WORK; use `register_manifest.py diff --*-out` for reference sets; stacs verify needs full-list output | folded |
| AC2 | empty sets prove nothing: positive control, 29 float + 160 null items read same, distinct-digest count | folded |
| AC3/AC4 | wall time, NaN/huge scan; validation list additions | folded |
