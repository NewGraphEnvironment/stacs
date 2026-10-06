# Review: Phase 5 (CLI) round 2

Scope: `git diff --cached`, focused on the round-1 fixes. Every claim below was
reproduced in a scratch copy of the index (`git checkout-index` into
`scratchpad/r2`, where the suite gave 311 passed and 1 deselected). Probes ran with
`--dryrun` or through the register test harness (stub ssh, loopback only). Nothing
under the repo was modified except this file.

## Findings

- **[bug]** README.md:100-102 (the "Use" example). The README runs `stacs load items`
  first and `stacs load collection` second. That order breaks the "Collection before
  items" hazard in CLAUDE.md, which `register` itself follows (register.py:521-526).
  - On a first load, or after a rename, the items load fails on
    `pgstac.items.collection REFERENCES collections(id)`.
  - When `collection.json` changed, the items are written while the stale collection
    row is still served.

  Swap the two lines. Nothing in `cmd_load` enforces the order, so the documented
  order is the only guard there is.

- **[fragile]** src/stacs/cli.py:195 (`cmd_load`) and cli.py:227 (`cmd_audit`). The
  round-1 fix copied the audit onto the load path, but not its repeated-id check.
  `register` calls `audit_items(..., expect_ids=todo)` (register.py:513), which
  refuses a repeated id. `cmd_load` and `cmd_audit` pass no `expect_ids`, so a
  repeated id passes. Reproduced:
  - `stacs load items --config cfg.toml --dir it --dryrun`, where `it/a.json` and
    `it/a2.json` both have `"id": "a"` with different bodies. Output: `audit : 2
    item(s) ... OK`, `items : 2`, rc 0. One id with two bodies goes into one payload.
  - The same path given twice on stdin to `load items` also gives rc 0 with 2 lines.
  - `printf 'a.json\na.json\n' | stacs audit --config cfg.toml --expect 2` gives
    `OK`, rc 0. One item satisfies a count of two, which is the "count satisfied by
    the wrong items" case that the `audit_items` docstring warns about.

  What pgstac then does depends on chunking and partitions. pypgstac's items upsert is
  `INSERT ... ON CONFLICT (id) DO UPDATE` with no dedupe (read from pypgstac 0.10.0
  `load.py:455`). Within one chunk and partition, Postgres raises "cannot affect row a
  second time", by which point earlier chunks may already be committed. Across chunks,
  one body silently wins. I did not run this against Postgres; the SQL is read, not
  measured. Fix: refuse a repeated id in `cmd_load`, and in `cmd_audit` alongside
  `--expect`. `len(audit.ids) != len(set(audit.ids))` is enough, or have
  `audit_items` always fail on repeats.

- **[fragile]** src/stacs/cli.py:208 (`cmd_load`, collection branch). The new check
  only runs when `[catalogue] collection_id` is declared.
  - `load collection --config nocoll.toml coll.json --dryrun` (no `[catalogue]`) gives
    rc 0.
  - `load collection --host … --db … coll.json` (no config) gives rc 0.

  `load items` treats a missing collection as a refusal (cli.py:186). `load
  collection` treats it as "no check", so a missing setting turns the check off on
  one of the two load paths. The harm is bounded: it is an upsert of one row, and the
  cascade does not apply. But a stale or wrong `collection.json` replaces another
  collection's body, which changes how that collection's items hydrate. Either
  require the declared id (as items does), or add `--expect-collection` to `load
  collection` and require one of the two.

- **[fragile]** src/stacs/cli.py:174 (`cmd_register`). `--ids-file` is accepted with
  `--mode all` or `--mode drift` and silently ignored, because `_run` reads it only
  for `ids`. So `stacs register --mode all --ids-file subset.txt` upserts the whole
  catalogue and reports DONE. This is the same "accepted, not applied" shape as
  round 1's config finding. Refuse `--ids-file` unless `--mode ids`.

- **[fragile, pre-existing, outside this diff]** register.py:422-526. In `--mode all`,
  the API is never contacted before the write. Reproduced in the harness with
  `api=http://127.0.0.1:9` (dead) and `all` with 2 items: rc 1, `writes 2`, and the
  loads were `collections 1` then `items 2`, followed by "could not compare the
  registered collection: API request failed".
  - `Target.check` closes the local half of round 1's "first used after the write"
    finding (type and sign).
  - It cannot close the server half: a wrong `api` URL, or a `page_size` the server
    rejects, still surfaces only after the upsert. The `chunk` cap is reported
    honestly by `bodies_serving`, but also after the write.
  - The docstring "Everything that can be refused before the first read" overstates
    this.

  A one-request API probe before the write in every writing mode closes it (one
  `/search` with `limit=page_size`, or GET `/collections`), mirroring `probe()` for
  ssh. No data is lost, because every write is an upsert, but a registration that
  landed reports as failed.

## Checked and fine (the round-1 fixes)

- `load items` reads paths once (`_paths`), and the audit and `load()` get the same
  list. Both filter blank lines identically, so no path is audited and then dropped
  or added. `--dir` wins over stdin; with both given, stdin is ignored.
- `--expect-collection ""` is refused (rc 2, "needs the collection"). It is not read
  as "use the declared one". A non-string declared `collection_id` (e.g. `5`) is also
  refused.
- `--forbid-asset a --forbid-asset ""` is refused ("empty asset key in ''"), as is a
  `","` among several values. `--require-asset ["data", ""]` is refused ("more than
  one key"), and `["", ""]` is refused ("empty").
- `Target.check` runs in `_run` before any read for every mode (verify, drift, all,
  ids). The only uses of `chunk`, `page_size` and `fetch_workers` are inside `_run`
  (register.py:438, 553, 582). No other code builds or consumes a `Target`. `bool` is
  excluded via `type(...) is int`.
- `load collection` with a declared id refuses a mismatch, including a non-string
  declared id.
- `Transport.check` refuses wrong TOML types before use. `build_transport` calls it,
  `load()` and `probe()` call it again, and `pg_port = true` is refused.
- `load items` exits 1 on zero items (empty stdin, or an empty `--dir`). `--dir ""` is
  refused and a missing `--dir` is a ConfigError, on all three commands that take it
  (`load items` has no test for `--dir ""`, but `_paths` is shared).
- `audit_items`'s ValueError, the ConfigError and OSError are all caught in `main` →
  rc 2.

## Mechanism

Round 1's findings had one cause: **an input is accepted at one layer and its meaning
is decided, or dropped, at another**, with no single point that maps every accepted
input to the place it is applied. `read_config` checks key names only. Each
subcommand then picks, ad hoc, which tables and flags it consumes and validates. That
produces three recurring shapes:

1. **Accepted, not applied.** Examples: the `[assets]`/`[catalogue]` tables on `load`,
   a repeated flag kept as only its last value (`store`), and now `--ids-file` outside
   `ids` mode.
2. **Empty read as absent.** `if x` where `is not None` was meant (`--dir ""`). Its
   relative is a missing setting read as "no check" (`load collection` with no
   declared id).
3. **Validated at use.** A value is checked where it is consumed, and for some values
   that is after the write: `[tuning]` and `[transport]` types (fixed locally), and the
   API URL and server limits in `all` mode (still open, pre-existing).

The round-1 fixes also introduced one shape of their own, the "fix lands in one of two
callers" mechanism. The audit now exists in two copies: `register._run` and
`cli.cmd_load`/`cmd_audit`. They take different arguments, and only the register copy
passes `expect_ids`.

### Every entry point and flag, and what guards it

| entry | flag / config | status |
|---|---|---|
| all | `--config` | guarded: explicit only, unknown table/key refused |
| verify | `--api`, `--collection-id`, `--bucket-url` | guarded: `_pick` refuses "", `Target.check` types |
| verify | `--require-asset` (append) | guarded: one key; "" refused; cannot replace declared |
| verify | `--forbid-asset` (append) | guarded: union; any empty part refused |
| verify | `--out-dir` | used in verify only (n/a elsewhere) |
| verify | `[tuning]` | guarded by `Target.check` (verify uses only `page_size`; all three checked) |
| verify | `[transport]` | not read, not validated; harmless, since verify does not write |
| register | catalogue/asset flags, `[tuning]` | as verify |
| register | `--host`, `--db`, `[transport]` | guarded: `build_transport` + `Transport.check` |
| register | `--mode` | guarded: argparse choices, `_run` check |
| register | `--ids-file` | **ignored unless `--mode ids`** (finding 4); missing or empty refused in ids mode |
| register | `--dryrun` | applied in all/ids/drift |
| register | `api` reachability, `page_size` ≤ server max | **unchecked before the write in `all`** (finding 5, pre-existing) |
| load items | `--host`, `--db`, `[transport]` | guarded |
| load items | `--expect-collection` / `[catalogue] collection_id` | guarded: required, "" refused |
| load items | `[assets]` | guarded: applied via `merge_asset_rules` + audit; no flags exist to add rules (by design) |
| load items | stdin / `--dir` | guarded: zero items → 1; `--dir ""` → 2; missing dir → 2 |
| load items | repeated ids across paths | **unguarded** (finding 2) |
| load items | `--dryrun` | applied after the audit |
| load items | `[tuning]`, `api`, `bucket_url` | not used (n/a) |
| load collection | `FILE` id vs `[catalogue] collection_id` | guarded **only when declared** (finding 3) |
| load collection | `[assets]` | not applicable; not validated on this path |
| load (both) | order relative to each other | **unenforced; README shows the wrong order** (finding 1) |
| audit | `--collection-id` / config | guarded: `_pick` + `audit_items` |
| audit | asset flags | guarded, as verify |
| audit | `--dir` / stdin | guarded: "" and missing refused; zero items → 1 |
| audit | `--expect` | a count, satisfied by a duplicated path (finding 2) |
| validate | `--dir` / stdin | guarded: "" and missing refused; zero items → 1; no config |
