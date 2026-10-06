# stacs

Versions track the package. A tag is a release consumers can pin with
`tag = "vX.Y.Z"` in `[tool.uv.sources]`; `pyproject.toml` carries the same version.

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
