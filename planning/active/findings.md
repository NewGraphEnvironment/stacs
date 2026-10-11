# Findings — Declare and load collection queryables from stacs.toml (#8)

## Issue context

**If we do it:** a catalogue declares the item properties its API should let users filter on, and `stacs register` loads them, so `/collections/<id>/queryables` lists them and CQL2 filters on them are advertised. **If we never do:** queryables can only be loaded by hand on the database host, and nothing records which a collection should have.

## What is there

pgstac serves `/collections/<id>/queryables` from its own `queryables` table, not from the collection JSON. A collection body that names a property does not make it queryable. stacs registers collections and items and does not touch that table, so a catalogue cannot declare a queryable today.

## Need

NewGraphEnvironment/stac_dem_bc#55 adds `lidarbc:delivery` to stac-elevation-bc items and asks for it in the collection's queryables, so a client can match items to the same delivery in stac-pointcloud-bc with one filter. stac-pointcloud-bc carries the same key and will want the same.

## Shape

- Declared in `stacs.toml` (property name, JSON Schema fragment, collection ids), beside the asset rules.
- Loaded as an upsert during `stacs register` (pypgstac's `load-queryables` is the mechanism), after the collection and before the item content check.
- `stacs verify` compares the served `/queryables` with the declaration.

## Errors Encountered

| Error | Resolution |
|-------|------------|
