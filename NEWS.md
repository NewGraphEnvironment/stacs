# stacs

Versions track the package. A tag is a release consumers can pin with
`tag = "vX.Y.Z"` in `[tool.uv.sources]`; `pyproject.toml` carries the same version.

## 0.1.3

- Every load names the database it reached (#6). Before writing, the host asks its pypgstac
  launcher for `current_database()` over the connection the load will use, and refuses
  anything but `db`; the success line is now `STACS_LOADED <n> <kind> <db>`, and `register`
  requires it. A launcher that does not pass `PGDATABASE` on (a container, a wrapper with
  its own DSN) used to load into another database unnoticed whenever that database already
  served the same bodies. It compares the name only: it cannot tell whether `db` itself is
  the right name (that stays the caller's value), nor a database of the same name on
  another server. A pooler that maps `db` to a different server-side name is refused.

## 0.1.2

- A catalogue declares its queryables in `stacs.toml`, one JSON Schema fragment per item
  property under `[queryables."<name>"]` (#8). `register` loads them through
  `pypgstac load_queryables` for the catalogue's own collection only, after the items and
  only when one is missing or served differently. `verify` compares
  `/collections/<id>/queryables` with the declaration. pgstac's loader replaces a shared or
  global row of the name, so a register that changes what another collection serves
  fails. A catalogue that declares none makes no queryables request.
- A declaration pgstac would not serve as written is refused when the config is read:
  `id`, `geometry`, `datetime`, `start_datetime`, `end_datetime` and `collection`; a
  `properties.` prefix; a backslash or a NUL; an empty `enum`; a value with no JSON form.

## 0.1.1

- A documentation site, <https://www.newgraphenvironment.com/stacs/> (#3): MkDocs with
  Material, reference pages generated from the docstrings, the README's sections as its
  home, configuration and command-line pages, and this file as its changelog. Built strict
  on every pull request; deployed to GitHub Pages from `main`.
- Runnable examples in the docstrings of the module-level functions on the API reference
  pages (`verify`, `catalogue`, `validate`, `register`) that work offline, run with the
  tests (`--doctest-modules`). The seven that need a live API or ssh have none.
- A black-and-white hexsticker, `data-raw/make_hexsticker.R`.
- The test suite's network guard moved from `tests/conftest.py` to the root `conftest.py`,
  so a run of `src/` alone is guarded too.

## 0.1.0

The registration and verification layer from
[`stac_dem_bc`](https://github.com/NewGraphEnvironment/stac_dem_bc), packaged (#1).

- `stacs verify`: every published body compared by digest with what the API serves;
  missing, changed and orphaned ids reported in both directions, with full lists via
  `--out-dir`, and the collection's own body compared too. Never by count.
- `stacs register --mode drift|all|ids`: upsert-only, collection before items, over ssh
  to the STAC host's `pypgstac`, followed by a check that the API serves what was sent.
  Refuses before writing wherever it can.
- `stacs load items|collection`, for repositories that register their own build output.
- `stacs audit` and `stacs validate`: the pre-load homogeneity audit (collection id and
  declared asset rules) and pystac validation of each body as written.
- Configured by a `stacs.toml` named with `--config`. No deployment defaults; no setting
  is a secret.

Differences from the scripts it replaces:

- Body digests are SHA-256 over RFC 8785 (JCS) canonical JSON rather than
  `json.dumps(sort_keys=True)`. Over the two live collections the two forms agree on every
  item's verdict; nothing stores a digest, so there is nothing to migrate.
- Asset rules are declared by the catalogue and can be added to by a flag, never loosened.
  stac_dem_bc's own-bucket test is gone; a catalogue states its rules instead.
- Inputs that used to read as "nothing to check" are refused: an empty `--require-asset`,
  a `--forbid-asset` that parses to no keys, a collection with no item links or with child
  links, two links resolving to one id, a fetch directory that is not empty.
- A remote load must confirm itself on stdout (`STACS_LOADED <n> <kind>`). On bash 3.2 a
  failed `.` under an EXIT trap exits 0, so the exit status alone could report a load that
  never ran.
- Relative item hrefs resolve against the collection's URL.
