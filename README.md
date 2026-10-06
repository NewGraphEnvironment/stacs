# stacs

Register a STAC catalogue into [pgstac](https://github.com/stac-utils/pgstac) and prove it
arrived.

**`stacs` works on a catalogue after its items exist.** It does not read source data or
build items: that belongs to the repository that owns the source. Anything source-agnostic
that is done to a published catalogue belongs here.

> **Status: pre-release.** The package is being extracted from
> [`stac_dem_bc`](https://github.com/NewGraphEnvironment/stac_dem_bc), where the
> registration and verification code has run against a 102,460-item collection. Nothing
> is usable from this repository yet.

## What it will do

- **Verify** what a STAC API serves against what is published: item id sets compared in
  both directions, and every item body compared by digest. Never by count, because a
  STAC API can omit ids it does not have without reporting an error, so equal counts can
  hide unequal sets.
- **Register** with upserts only, collection before items. Nothing in the routine path
  deletes. `drift` mode registers only what the API is missing or serves differently,
  which keeps it stateless: a skipped run is picked up by the next one.
- **Validate** items with [`pystac`](https://github.com/stac-utils/pystac) and the asset
  rules a catalogue declares for itself.

The host, database, API and bucket are always supplied by the caller. `stacs` has no
defaults that point at any particular deployment.

## Install

Managed with [uv](https://docs.astral.sh/uv/). Install from git rather than PyPI: the
`stacs` name on PyPI belongs to an unrelated, archived project.

```toml
[tool.uv.sources]
stacs = { git = "https://github.com/NewGraphEnvironment/stacs", tag = "v0.1.0" }
```

## Development

```bash
uv sync
uv run pytest
```

## License

MIT
