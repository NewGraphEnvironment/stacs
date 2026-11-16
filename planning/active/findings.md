# Findings — verify follows a published item's receipt href to any scheme, file:// included (#19)

## Issue context

**If we do it:** `verify` reads a receipt only from where the catalogue itself is served. **If we never do:** a published item can make `verify` read a local file on the machine running it, parse it, hash it and report whether its digest matches the item's claim.

`register._receipt_verdicts` resolves the receipt asset's href against the item's URL with `urllib.parse.urljoin` and fetches the result through `catalogue.fetch_bodies`. `catalogue._read_url` reads any `file://` URL with `urllib.request.urlopen`; that path exists so the test suite can publish a bucket on disk. An absolute href replaces the base, so an item served over https that links `file:///some/local.json` as its receipt has that local file read during `verify`. Its bytes are parsed as a receipt and their SHA-256 compared with the item's `file:checksum`, so the verdict (`inconsistent` with "hashes to ...", or a parse error) says something about a local file to whoever controls the catalogue.

Narrow, and it was there before #17: the content is not echoed, and only a JSON object passes `receipt.read`. Found by the code review of the #17 branch.

- [ ] Decide the rule: a receipt URL must share the item URL's scheme (and host?), or `file://` is read only when the item itself is `file://`
- [ ] Apply the same rule to anything else `verify` fetches from an href a published body supplies

## Fetch sites reached by an href a published body supplies (2026-11-16, origin/main 38a45a3)

- `register.py:561` — collection item links, `urljoin(coll_url, h)`, fetched in every mode.
  A `file://` link in an https collection is read, and in `all`/`ids` upserted if its `id`
  matches its basename.
- `register.py:860` — receipt href, `urljoin(item_url, href)`, fetched in `verify`.
- Not reached: asset hrefs (normalised in `item_verdict`, never fetched); the API's
  `/collections` `next` href (`verify.py:532`) is the configured API's, through `requests`.
- `_read_url` (`catalogue.py:112`) opens only a `file://` prefix with urllib; every other
  scheme goes to `requests`, which has no adapter for `ftp:`/`data:`/`file:`.
- `urljoin` lowercases the scheme and adds `//` for `file:/x`, so the check reads
  `urlsplit(...).scheme`, never a string prefix.

## Errors Encountered

| Error | Resolution |
|-------|------------|
