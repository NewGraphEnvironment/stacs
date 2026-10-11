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
| `--delete_missing` | deletes the collection's rows the file does not list | same, via `delete_missing_queryables` | never passed: upsert only |
| backslashes | `read_json` replaces `\\` with `\` in each line before parsing, as it does for items ([`pgstac_round_trip.md`](pgstac_round_trip.md)) | same | refuses a declaration containing a backslash |

**The row passed in wins.** This is the hazard. A queryable loaded for collection A
replaces a global row of the same name, so every other collection stops serving it. In
0.10.0 it also replaces a row shared by A and B with one for A alone, so B stops
serving it. Rows for disjoint collections coexist, which is why each catalogue declares
its own and never names another's.

The API cannot show whether a served queryable comes from a global row or a
per-collection one: both appear in every collection they cover. So stacs cannot refuse
before the write. It records what every other collection serves for the declared names
and compares that again afterwards.

Upstream `main` has since removed pypgstac. Its replacement is a Rust `pgstac` CLI,
`pgstac load-queryables FILE --collection-ids a,b`. stacs drives the pypgstac form, which
is what released hosts run.

## Serving

stac-fastapi-pgstac answers `/collections/<id>/queryables` with `get_queryables(<id>)` and
sets `$id` to the request URL. When that returns nothing it answers **404**, including for
an existing collection with no queryable rows at all. pgstac seeds global defaults, so in
practice that does not happen.

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
