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
- **Correction to the plan's Context (probed 2026-11-16):** `urljoin` does NOT lowercase or
  rewrite an absolute href with its own scheme: `FILE:///x`, `file:/x`, ` file:///x` and
  `fi\tle:///x` come back as written. `_read_url`'s `startswith("file://")` misses them and
  sends them to `requests`, which has no adapter, so none is a bypass today. `urlsplit`
  lowercases the scheme and strips leading whitespace and tabs, so a guard on
  `urlsplit(...).scheme` refuses all of them, stricter than `_read_url` needs.
- Reproduced red before the fix: the receipt case reads `2 rebuilt` (the local file was
  read and agreed), and `all` with a `file://` item link upserted the local item `a9`.

## Errors Encountered

| Error | Resolution |
|-------|------------|
| `drift` refusal test red with "no transport is configured" | `drift` writes; the test gives it a transport. Its pre-fix red had been the harness, so the mutation check re-proved it |
