# How pgstac loads and serves queryables

**Verified:** 2026-10-11 · **Issues:** #8;
[stac_dem_bc#55](https://github.com/NewGraphEnvironment/stac_dem_bc/issues/55) ·
**Produced by:** reading upstream source at tags, no live run:
[pgstac](https://github.com/stac-utils/pgstac) `v0.9.8` and `v0.10.0`
(`src/pypgstac/src/pypgstac/pypgstac.py` `load_queryables`, `load.py` `read_json`,
`src/pgstac/sql/002a_queryables.sql`, `001a_jsonutils.sql`), and
[stac-fastapi-pgstac](https://github.com/stac-utils/stac-fastapi-pgstac) `main`
(`stac_fastapi/pgstac/extensions/filter.py`).

pgstac serves `/queryables` and `/collections/<id>/queryables` from its own `queryables`
table. A collection body that names a property does not make it queryable, and loading a
collection does not touch the table.

## Loading

`pypgstac load_queryables FILE [--collection_ids=[...]] [--delete_missing] [--index_fields=[...]]`,
added in pypgstac 0.9.6. It is a `fire` CLI, so a list argument is a Python literal.
It reads the first JSON document in `FILE` and loads one row per member of its
`properties`.

| behaviour | 0.9.8 | 0.10.0 | what stacs does |
|---|---|---|---|
| core columns (`id`, `geometry`, `datetime`, `end_datetime`, `collection`; 0.10.0 also `start_datetime`) | skipped silently | skipped silently (`queryable_column`) | refuses to declare them: a skipped name would verify as missing forever |
| a `properties.` prefix | kept | stripped (`strip_properties_prefix`) | refuses it |
| replacing an existing row of the name | deletes the row with exactly these `collection_ids` **and the global row** (`collection_ids IS NULL`), then inserts | deletes **every conflicting row**: the global one and every row whose collections overlap (`conflicting_queryables`), then inserts | loads for the catalogue's own collection only, and checks after the load that no other collection lost or changed a declared name |
| a row shared by this collection and another | kept, so the insert trigger raises `unique_violation` and nothing loads | replaced by this collection's own row | queryables load after the items, so a failure cannot hold the items back |
| the index setting (`property_index_type`) | every load deletes and reinserts, so the new row has none unless `--index_fields` names it | same; the delete trigger drops the reference index | never passes `--index_fields`; loads a name only when it is missing or served differently, never one already served as declared |
| `--delete_missing` | deletes the collection's rows the file does not list | same, via `delete_missing_queryables` | never passed: upsert only |
| backslashes | `read_json` replaces `\\` with `\` in each line before parsing, as it does for items ([`pgstac_round_trip.md`](pgstac_round_trip.md)) | same | refuses a declaration containing a backslash |

**The row passed in wins.** This is the hazard. A queryable loaded for collection A
replaces a global row of the same name, so every other collection stops serving it. In
0.10.0 it also replaces a row shared by A and B with one for A alone, so B stops
serving it. Rows for disjoint collections coexist, which is why each catalogue declares
its own and never names another's.

**Which loads can harm another collection.** The rows a load replaces are exactly the
rows of the name that are served on *this* collection: 0.10.0's `conflicting_queryables`
is "global, or overlapping these collections", and 0.9.x deletes the exact match and the
global row. So a declared name that is not served here yet cannot touch any other
collection. A name served here with a different definition may come from this
collection's own row, a shared row or a global one, and the API cannot show which,
because every collection a row covers serves it. For those names only, stacs reads what
every other collection serves just before the load and again after it, and fails the run
if any lost or changed one. The second read happens on every way out once the load has
been attempted, failures included: a load can commit and then report failure (a dropped
connection), and the next run would find this collection's own row serving the name as
declared and check nothing. Queryables are loaded last, once the collection is
registered, so the drift is asked of a collection that exists. A global row then shows as
served here: a matching one is not loaded at all, and a differing one is guarded. Refusing before the write would also refuse the ordinary case: two
catalogues each declaring the same key for themselves, one of which later changes it.

A collection that declares the queryable itself gets it back by re-registering. A global
row cannot come back beside a per-collection one: in 0.10.0 a global row conflicts with
every row of its name, and in 0.9.x the insert trigger refuses it. Losing a global row
also changes root `/queryables` and every collection created later, which no check made
after the load can see.

Upstream `main` has since removed pypgstac. Its replacement is a Rust `pgstac` CLI,
`pgstac load-queryables FILE --collection-ids a,b`. stacs drives the pypgstac form, which
is what released hosts run.

## Serving

stac-fastapi-pgstac answers `/collections/<id>/queryables` with `get_queryables(<id>)` and
sets `$id` to the request URL. When that returns NULL it answers **404**.

- For an **existing collection with no queryable rows**, `get_queryables` is not NULL:
  it is an aggregate with no `GROUP BY`, so an empty set still yields one row, with
  `"properties": null`. stacs reads that as none served.
- `get_queryables` returns NULL only for a collection that does not exist. stacs never
  asks about one: a collection that is not registered has every declaration missing.
- With the filter extension disabled (`ENABLED_EXTENSIONS` without `filter`), the route
  itself 404s. For an existing collection, then, a 404 means "this API does not serve
  queryables", never "none". stacs raises rather than report every declaration missing
  forever.
- Root `/queryables` is `get_queryables(NULL)`, which is NULL while the database holds
  no collection at all, so it 404s on a fresh database. The pre-write probe accepts that
  404 only when `/collections` lists none.

`get_queryables` merges every row of a name that covers the collection:

- the definition is taken from the first row (lowest id);
- `enum` is `jsonb_agg(DISTINCT ...)` over every row's members, so it is **deduplicated and
  reordered**, and an empty `enum` is served **absent** (`nullif_jsonbnullempty`);
- `minimum` and `maximum` take the widest values (0.9.8 has a typo, `'maxiumn'`, so its
  `maximum` is whatever the first row said).

With one row of the name, the served fragment is the loaded one, except that `enum` is
reordered. stacs therefore compares `enum` as a sorted set, refuses an empty `enum`, and
compares everything else by digest of the RFC 8785 form, as it does for bodies.

Undeclared served names cannot be attributed: pgstac's global defaults and another
loader's rows look the same. `stacs verify` reports only declared names that are missing
or served differently.
