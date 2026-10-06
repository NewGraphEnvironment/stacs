# What pgstac changes about a STAC body between load and serve

**Verified:** 2026-10-06 · **Issues:** #1; carried over from
[stac_dem_bc#45](https://github.com/NewGraphEnvironment/stac_dem_bc/issues/45) ·
**Produced by:** a full content verify of two live collections (102,460 and 10,100 items),
first with stac_dem_bc's `catalogue_register.sh --verify` (2026-09-29), then with
`stacs verify` and the verdict-equivalence check in
`planning/archive/2026-10-issue-1-stacs-package/` (2026-10-06).

A body published to a bucket and the body a pgstac-backed STAC API serves for the same id
are **not byte-identical**, and not identical as parsed JSON either. Anything comparing
the two must canonicalise these differences first, or it reports items as changed forever
and a drift run re-registers them every time without converging.
`stacs.verify.canonical_json` / `body_digest` is the implementation.

| difference | how it shows up | measured (2026-09-29, 102,460-item collection) | absorbed by |
|---|---|---|---|
| `links` rewritten | the published `collection` link is replaced by the API's own self/root/parent/collection set, on its host | every item | `links` removed before hashing |
| null object members dropped | `"proj:epsg": null` is served with the key absent (Postgres `jsonb_strip_nulls` semantics: object fields only, never array elements) | 160 items | null members dropped |
| integral floats served as integers | PostGIS rebuilds geometry, so `-126.0` comes back as `-126`; likewise `-0.0` → `0`, and floats ≥ 1e16 as the integer of their value | 29 items | RFC 8785 (JCS) writes every number as the double it denotes, so `-126.0` and `-126` serialise alike; integers beyond 2^53 become that double first, because `rfc8785` refuses them otherwise |

After those, every item of both live collections compares equal, and so do both
collections. Re-measured 2026-10-06: the 160 null items still differ with only `links`
removed and compare equal canonicalised; no item now differs by an integral float even with
only `links` removed, so that rule is pinned by tests rather than by live data.

**The sample did not find any of this.** 2,000 items compared equal with only `links`
removed; both later differences appeared only in a full-population run.

**Hydration.** pgstac stores items dehydrated against a base built from the collection (its
`item_assets` and `stac_version`) and rehydrates them on read, so a collection upsert can
change how items that were never touched read back. This is why `register --mode all`, and
a `drift` whose collection changed, re-compare the whole catalogue after writing.

**Duplicate keys.** Postgres jsonb keeps the last of duplicate object keys, as Python's
`json` does, so a published body with duplicates digests the same on both sides (measured in
review on postgres:16, 2026-10-06).

**The loader rewrites backslashes.** `pypgstac` 0.10.0 `load.read_json` replaces `\\` with
`\` in each NDJSON line before parsing, so a string holding an escaped backslash is loaded
as a different string, or not at all. `stacs` does not work around it: such an item reads
`changed` on every verify, which is the correct signal. No live body of either collection
carries a backslash, NaN, Infinity or an integer beyond 2^53 (scanned 2026-10-06).

## Why RFC 8785

stacchain's Merkle tooling hashes RFC 8785 JSON, so a later Merkle layer can reuse these
leaf hashes. Nothing stores a digest -- both sides are recomputed from the published bodies
and the API on every run -- so the canonical form changed from stac_dem_bc's
`json.dumps(sort_keys=True)` with no migration. Over the same bodies and the same API pass,
the two forms agree on every item's verdict: 0 disagreements in 102,460 + 10,100 items, and
every published body has a distinct digest (2026-10-06).

Cost: `rfc8785` is pure Python, ~2.5x `json.dumps` per digest (139 µs vs 54 µs on a 2.7 KB
item), about 17 s more per whole-catalogue verify of 102k items.
