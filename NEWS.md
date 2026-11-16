# stacs

Versions track the package. A tag is a release consumers can pin with
`tag = "vX.Y.Z"` in `[tool.uv.sources]`; `pyproject.toml` carries the same version.

## Unreleased

- **Behaviour change:** an href a published body supplies is fetched only within the scheme
  of the URL it is resolved against, by the new `catalogue.resolve_href`: http and https
  mix, and `file://` is read only from a `file://` base. An item link in `collection.json`
  that leaves the collection's scheme refuses `register` in every mode before anything is
  fetched or written. A receipt href that leaves its item's scheme makes the item
  `inconsistent` where `verify` reads receipts (under `require_receipt`, for an item whose
  published and served bodies differ). Before, an absolute `file:///...` href in a catalogue served
  over https had a file on the machine running stacs read: a receipt was hashed and
  reported on, and in `all`, `ids` or `drift` an item was upserted and served by the API (#19).

## 0.5.0

- **Behaviour change:** `receipt.item_verdict` holds the published item to its receipt in
  both directions. A `receipt:recipe_id`, `processing:datetime` or `processing:software` the
  item publishes and the receipt's mapping does not produce is a disagreement, so the item
  is `inconsistent`: a recipe identity over a migrated receipt, or software (an empty
  `processing:software` included) over a receipt with no versioned code, was never held
  against the receipt, and read `same`, `rebuilt` or `changed` by what the served body
  carried. A field the item leaves out is still not a disagreement (#17).
- **Behaviour change:** `item_verdict` matches an asset to the part it names through the
  common spellings of one href. A relative href is normalised (`./x.tif` and `sub/../x.tif`
  name part `x.tif`, and a fragment is dropped), and so is each part key. An absolute href
  is made relative against the new `item_url` argument, the published item's own URL, which
  `verify` passes; scheme and host compare case-insensitively, and a default port or
  userinfo does not stop a match. Percent-encoding is not decoded. Before, only an href
  spelled exactly as a part key was compared, so a contradicting `file:checksum` behind any
  other spelling was never held against the receipt, and a catalogue that publishes absolute
  hrefs compared no asset at all. Matching more hrefs can also reach a part the mapping
  refuses, which makes the item `inconsistent`. Two part keys that spell the file an href
  names, neither of them its exact spelling, and an asset carrying `file:checksum` or
  `file:size` with no href, are disagreements, and so is an href no URL parser reads as
  written (an unclosed IPv6 host, a port that is not one, a control character such as a tab
  or a newline, a space at either end). Only `.` and `..` segments are removed, so
  `a//b.tif` and `x.tif/` name no part `a/b.tif` or `x.tif`. An href with a query names no
  part, and with no `item_url` an absolute href is matched to none and the notes say so.
- **Behaviour change:** an asset entry that is not an object, `null` included, makes the
  item `inconsistent` on either side, whether or not the receipt describes that asset. It
  used to be skipped. `file:size` is compared as a whole number, so a size too large for a
  double no longer raises `OverflowError` and two sizes beyond a double's precision no
  longer compare equal.
- **Behaviour change:** under `require_receipt`, an item that links a receipt and carries no
  `receipt:recipe_id` (what `stac_fields` returns for a migrated receipt, or a build that
  dropped the identity) is refused with its own sentence, `receipt.NO_RECIPE_IDENTITY`.
  `audit` files it with items whose receipt fields do not hold up, no longer with items that
  carry no receipt, and `verify` reports it `inconsistent` in the same words, where it used
  to read `same`, `rebuilt` or `changed` by what the served body carried. A catalogue that
  holds migrated items does not declare `require_receipt`.
- **Behaviour change:** an asset's `roles` and an item's `stac_extensions` are read only as
  lists. A non-zero number or `true` used to raise `TypeError`: as `roles`, out of `audit
  --require-receipt` and `verify`; as `stac_extensions`, out of `audit --require-receipt`
  for an item carrying `processing:` or `file:` fields. A string or an object was searched
  with `in`, so `roles: "metadata"` linked the receipt and a `stac_extensions` string
  holding the processing URL counted as listing it. `item_problems` now reports an asset
  whose `roles` is present and not a list, `null` included.
- `verify` stops paging with its own error when `/search` returns a link that is not an
  object ahead of the next link, a next link whose body is not an object, or a token that is
  an object or a list. Each of these, the body only when non-empty and the token only when
  non-empty, used to raise `AttributeError` or `TypeError`. A link after the next link is
  not read, as before. A numeric token is followed, as it was.
- `verify` marks an item whose receipt href no URL parser reads `inconsistent`, saying so,
  and goes on to the other items. It used to end the run with a `ValueError` that named no
  item.

## 0.4.0

- **crate's receipt contract, each part at its own version** (#15). crate versioned the
  register and the mapping apart from the receipt form, so the vendored copies are pinned by
  contract version as the schemas already were: register v1.0.0 and mapping v1.1.0, vendored
  from crate tag `v0.16.0`. The CI check compares each with the versioned URL crate serves it
  at, as well as with the tag. Inside the package the two files moved to
  `data/receipt/register/v1.0.0/register.csv` and `data/receipt/mapping/v1.1.0/mapping.csv`.
- crate's `stac.json` runs in CI: 142 cases that pin how a receipt becomes an item's fields,
  each a set of fields or a refusal with a code. `receipt.stac_fields` agreed on 87 before
  this release and agrees on all 142 now, compared by code.
- **Behaviour change:** `receipt.stac_fields` refuses what mapping v1.1.0 refuses, with a
  `ReceiptError` whose new `code` attribute is crate's name for the refusal
  (`receipt.STAC_REFUSALS` lists them). It now refuses a receipt whose `output.receipt_version`
  is not `1.0.0`; a `recipe_id` that is null or missing on a receipt that was not migrated, or
  set on a migrated one; a `context.time` that is missing or not an instant that exists; a
  block or entry that is present but not an object, `null` included; a repository whose
  `version` is set to anything but a non-empty string (a null or missing one is still left
  out), or whose name is empty; a part an asset names whose `bytes` is negative; a
  `receipt_asset` that is not a string, is empty or is also a key of `assets`; and
  a `receipt_sha256` given with no `receipt_asset`. Of the receipts `receipt.validate` passes,
  the mapping refuses two kinds: one whose `context.time` is not an instant that exists, and
  one whose `recipe_id`, `context.time` or a part's `sha256` ends in a newline.
- **Behaviour change:** the item checks behind `audit --require-receipt`, which also run
  before a `register` or `load` write, share those patterns. An item is refused when
  `receipt:recipe_id`, `processing:datetime` or a `file:checksum` ends in a newline, when
  `processing:datetime` is written in digits outside ASCII or is not an instant that exists
  (month 13, 29 February in a common year, hour 24), or when a `file:size` is negative.
- **Behaviour change:** `verify` reports an item `inconsistent` when the mapping refuses the
  receipt it links, or refuses a part one of the item's assets names by its exact key. Where
  the mapping is the check that refuses, the note carries its code; a check that runs before
  it answers in its own words for a receipt it cannot read. `receipt.item_verdict` asks
  `stac_fields` about those assets and returns `inconsistent` where it refuses; it used to
  return that for some such receipts, raise for others, and read a part held as `null` as not
  described at all.
- `receipt.compare` names the rulebook behind its verdict: `Comparison.register` is the
  register version it read, and `Comparison.overrides` each action the caller's `overrides`
  changed. Code that constructs a `Comparison` itself must now pass both.

## 0.3.0

- **Provenance receipts** (#12). `stacs.receipt` reads, writes and compares a provenance
  receipt, computes a `recipe_id`, fingerprints a table, and maps a receipt onto the
  identity fields an item mirrors. The contract is crate's, settled in its v0.12.0: the
  receipt canonical form is plain RFC 8785, kept apart from `verify.canonical_json`, which
  drops `links` and null members for pgstac's round trip. A `recipe_id` is published, so
  unlike a body digest its bytes are frozen by the receipt schema version.
- crate's test vectors run in CI, vendored at tag `v0.12.0` and re-checked against it before
  pytest: 2,637 number spellings, 10 canonical JSON cases, 7 `recipe_id`s, 13 table
  fingerprints and 9 receipt comparisons. They are what keeps the two implementations byte
  for byte alike, and the same step proves each frozen schema URL still serves the vendored
  bytes.
- A catalogue may declare `require_receipt = true` under `[catalogue]`, or pass
  `--require-receipt`. `audit` then refuses an item whose receipt fields are missing or do
  not hold up, and the check runs before a `register` or `load` write as well, so `audit`
  cannot refuse what `register` loads.
- `verify` reports a verdict per item whose published and served bodies differ: `same`,
  `rebuilt`, `changed` or `inconsistent`, written to `--out-dir` and summarised on stderr.
  These are stacs' words, not crate's three: with one receipt and the identity fields an item
  mirrors, crate's `equivalent` cannot arise, and `rebuilt` is the distinction the issue
  asked for. The receipt is resolved from the item's asset with role `metadata` and its bytes
  are checked against that asset's `file:checksum`.
- `verify.items_serving` reads served item bodies rather than reducing each to a digest, for
  checks on an item's fields. `jsonschema` is now a declared dependency.
- **Behaviour change:** `catalogue.fetch_bodies` refuses a URL list containing a duplicate.
  It runs one worker per element and names each file after a digest of its URL, so a repeated
  URL meant two workers writing one temporary path and racing the rename — the loser reported
  a failure for a body that was correctly on disk. Every existing caller already deduplicates
  upstream; a caller that passes a duplicate now gets a `ValueError` instead of a wrong
  answer.

## 0.2.0

- **Behaviour change:** `--dryrun` now probes the host, and `register --dryrun` the API as
  well (#5). Both probes are read-only. `register --dryrun` (all modes) and
  `load --dryrun` used to return before them, so a dryrun that passed proved nothing about ssh,
  and in `all` and `ids` nothing about the API either. A dryrun now exits 1 when one does
  not answer, including in a CI job with no ssh key or known_hosts, and says what it
  reached. It still stops before the item fetch (`all`, `ids`) or the audit (`drift`), and
  never runs the script on the host; the README says what each one skips.
- An `all` or `ids` dryrun names only the queryables it would load, not every declared
  one.

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
