# Code-check round 3 -- #17 branch (base 8390c5d = v0.4.0, HEAD 1ef3129)

## Checklist read

- `code-check-python.md`: in full.
- `code-check.md`: the prose of every H3 under `## Mechanisms` (table rows skipped). From the
  stand-alone rules, "Percent-encode a URL at construction, not at consumption". The other
  stand-alone, Security and Spreadsheet headings were not read: none names a tool or shape
  this diff uses.
- `code-check-shell.md`: no headings read. Every heading names a shell, git, gh or host-tool
  shape, and the diff touches none of them.
- `code-check-r.md`: no headings read. The diff has no R.

## Mechanism

Both candidates hold, and they turn out to be one mechanism seen from two ends: **the
branch says what a parser does from the cases it wrote down, not from the parser's own
code.**

- (a) **Confirmed, with a sharper statement.** The href matcher runs a published value
  through three stdlib routines: `urldefrag`, `urlsplit` and `urljoin`. Each one
  normalises or re-serialises the value on some routes and not on others. The docstring,
  NEWS and the round-2 test (`test_only_dot_segments_are_removed_so_another_key_is_not_matched`)
  all describe the normalisation as "`_remove_dots`, and only that". But `_remove_dots`
  is only one of four transformations a value can go through, and which ones apply depends
  on the route:
  1. `urldefrag` re-serialises an href through `urlparse`/`urlunparse` **only when it
     holds a `#`**. That strips every `\t`, `\r` and `\n`, plus leading C0 control and
     space characters.
  2. `urlsplit` does the same stripping, and its `scheme` decides whether an href counts
     as absolute.
  3. `urljoin(item_url, href)`, for a reference with no netloc (root-relative, or a
     relative href that climbs), runs Python's own dot removal **plus
     `segments[1:-1] = filter(None, ...)`**. That collapses `//`, the very thing round 2
     removed from `_inside`. For a scheme outside `uses_relative` (`s3`, `gs`) it returns
     the href unchanged.
  4. `urljoin(item_url, ".")` collapses `//` in the base path. The path of an absolute
     href is never collapsed.

  Round 2 fixed `posixpath.normpath`, the instance it saw. Its fixture covers a relative
  href with no `#` and an absolute href, which are exactly the two routes that skip
  transformations 1 and 3. So that test passes while the same normalisation re-enters
  through `urljoin`.
- (b) **Confirmed.** Two release-note sentences describe the v0.4.0 behaviour from the case
  the author had in mind rather than from the v0.4.0 code. One is the R1 numeric-token
  shape again: input 0.4.0 accepted is now refused, and the note files it as a crash fix.

## Enumeration

### (a) Every call in the changed code that takes a value from a published item, receipt or API page

| # | where | call / operator | what it raises or normalises | handled? |
|---|---|---|---|---|
| 1 | receipt.py `receipt_asset` | `RECEIPT_ROLE in _list(asset, "roles")` | list `==` membership, nothing raised | holds |
| 2 | receipt.py `item_problems` | `URL not in _list(item, "stac_extensions")` | as above | holds |
| 3 | receipt.py `item_problems` | `"roles" in asset and not isinstance(..., list)` | none | holds |
| 4 | receipt.py `item_verdict` | `urlsplit(item_url)`, `_origin` (`.port`, `.hostname`) | ValueError on a bad IPv6 host or port | holds: becomes ReceiptError, then this item's `inconsistent` |
| 5 | receipt.py `item_verdict` | asset-entry loop over `_mapping(doc,"assets").items()` on both sides | none | holds |
| 6 | receipt.py `item_verdict` | `asset.get("href")`; non-str becomes a disagreement; `not href` with file fields becomes a disagreement | none | holds |
| 7 | receipt.py `_part_key` | `href in parts` (dict key, href is a str) | none | holds |
| 8 | receipt.py `_relative_href` | `urldefrag(href)` | ValueError (caught). **Re-serialises only when `#` is present: strips `\t\r\n` anywhere and leading C0/space** | **does not hold**: F1 |
| 9 | receipt.py `_relative_href` | `urlsplit(href)` | ValueError (caught). Strips as in #8, and `split.scheme` decides `absolute`, so `" https://..."` counts as absolute | **does not hold**: F1 |
| 10 | receipt.py `_origin` | `.port`, `.hostname`, `.scheme.lower()` | ValueError (caught at both call sites); host lower-cased; userinfo dropped | holds |
| 11 | receipt.py `_inside` / `_remove_dots` | pure string split on `/` | dot segments only, RFC 5.2.4, root clamp | holds |
| 12 | receipt.py `_relative_href` | `urljoin(item_url, ".")` | **collapses `//` in the base path** (relative-reference branch of `urljoin`) | **does not hold**: F1 (absolute href under an item URL containing `//` is never matched) |
| 13 | receipt.py `_relative_href` | `urljoin(item_url, href)` | **for a root-relative or climbing href: own dot removal plus `filter(None, segments[1:-1])`, which collapses `//`**. Strips whitespace as #8. For an `s3`/`gs` item URL, returns the href unchanged, so it never matches and no note is written | **does not hold**: F1. s3: holds for `verify`, which only fetches http(s) and `file:` (`catalogue._read_url`). A direct caller passing an `s3://` item URL gets "matched to none" with no note, which is not reported as a finding |
| 14 | receipt.py `_relative_href` | `full.query` truthiness | an empty `?` reads as no query, so `https://h/c/x.tif?` matches and relative `x.tif?` does not | holds in effect; not reported |
| 15 | receipt.py `_relative_href` | `path.startswith(base.path)` | base path always ends in `/` (urljoin with `.`) | holds |
| 16 | receipt.py `_part_key` | `_inside(k)` over part keys, `isinstance(k, str)` | none | holds |
| 17 | receipt.py `item_verdict` | `canonical(properties[key])` in the both-directions loop | ReceiptError on NaN. Short-circuited for a key the receipt does not produce, so nothing raises that did not raise before | holds: `_receipt_verdicts` catches ReceiptError |
| 18 | receipt.py `item_verdict` | `_whole(asset["file:size"])` then `==` | ReceiptError, caught, becomes a disagreement; int `==` int | holds |
| 19 | receipt.py `item_verdict` | `asset["file:checksum"] != want` | none | holds |
| 20 | register.py `_receipt_verdicts` | `"receipt:recipe_id" not in properties` after an `isinstance` | none | holds |
| 21 | register.py `_receipt_verdicts` | `urljoin(by_id, href)` for the receipt | ValueError caught, becomes `unlinked`. Whitespace stripping was there before the branch | holds |
| 22 | register.py | `item_url=by_id[item_id]` | already parsed and fetched, so `_origin` cannot fail on it | holds |
| 23 | validate.py `audit_items` | `receipt_href(doc) is not None` | none | holds |
| 24 | verify.py `_search_pages` | `all(isinstance(l, dict) for l in links)` | none. **Refuses a page whose non-object link comes after the next link, which 0.4.0 followed** | holds as code; the NEWS claim about it does not: F2 |
| 25 | verify.py | `l.get("rel") == "next"`, `next_body.get("token")` | none | holds |
| 26 | verify.py | `isinstance(token,(dict,list)) or not token`, then `token in seen_tokens` | str, int, float and bool are hashable. A NaN token is followed and never counts as repeated, but that was already so at v0.4.0 (`if not token`) | holds; not a regression |

### (b) Every "used to / no longer / now / as it was / before" claim in NEWS `## Unreleased` and the README receipts section, against 8390c5d and HEAD

| # | claim | v0.4.0 (8390c5d) | verdict |
|---|---|---|---|
| N1 | recipe identity over a migrated receipt, or software over one with no versioned code, "used to read `same`" | not compared, so the verdict came from the side diff: `same`, or `rebuilt`/`changed` when mirrored fields differed | holds in substance (it was never `inconsistent`); `same` is the common case, not the only one |
| N2 | "A field the item leaves out is still not a disagreement" | `if key in properties` | holds |
| N3 | "Before, only an href spelled exactly as a part key was compared ... absolute hrefs compared no asset at all" | `elif href in parts` | holds |
| N4 | "Only `.` and `..` segments are removed, so `a//b.tif` and `x.tif/` name no part `a/b.tif` or `x.tif`" | (new) | **does not hold at HEAD**: F1 |
| N5 | README "a part key and an href must spell a name alike" | (new) | **does not hold at HEAD** for `\t`/`\n`/leading space on re-serialised routes and `//` on urljoin routes: F1 |
| N6 | non-object asset entry "used to be skipped" | `continue` in the published loop and in `_mirrored` | holds |
| N7 | size too large for a double "no longer raises OverflowError"; beyond-precision sizes "no longer compare equal" | `float(size)` | holds |
| N8 | migrated-receipt item: audit "no longer" files it with items carrying no receipt; verify reports it `inconsistent` "where it used to read `same`" | `missing_receipt`; verdict from the side diff | holds ("where" scopes it) |
| N9 | roles / stac_extensions: "A non-zero number or `true` used to raise `TypeError` out of `audit --require-receipt` and `verify`" | roles: raised in both (`receipt_href`). stac_extensions: raised only in audit, and only when processing:/file: fields were present. `verify` never reads `stac_extensions` (`item_verdict` does not, and `audit_items` runs only on the register path) | **over-claims** for stac_extensions in verify. Folded into F2 as a second instance |
| N10 | "A string or an object was searched with `in`, so `roles: "metadata"` linked the receipt ..." | `in (asset.get("roles") or [])` | holds |
| N11 | "A link that was not an object ... used to raise `AttributeError`" | `next(l for l in links if l.get(...))` stops at the first next link, so a non-object link AFTER it was never touched and the page was followed | **does not hold**: F2. That page is now refused, an undeclared new refusal |
| N12 | "a non-empty body that was not one, or a non-empty token of either kind used to raise" | `(body or {}).get`; `token in set` | holds |
| N13 | "A numeric token is followed, as it was" | `if not token` | holds |
| N14 | receipt href no parser reads "used to end the run with a `ValueError` that named no item" | `urljoin` unguarded at 8390c5d | holds |
| N15 | README: verify reports a migrated item `inconsistent` "when its published and served bodies differ" | (new) | holds (changed set only) |

## Mutation table (detached worktree, tests/test_receipt.py, test_register.py, test_validate.py, test_verify.py; each restored before the next)

The baseline at HEAD was 1003 passed, full suite. Every substitution matched exactly once
before its run.

| mutation | result |
|---|---|
| M1 register receipt-href `urljoin` unguarded | 1 failed |
| M2 `..` at an absolute root returns None (no clamp) | 1 failed |
| M3 `_remove_dots` collapses `//` again | 4 failed |
| M4 audit NO_RECIPE_IDENTITY branch removed | 1 failed |
| M5 register NO_RECIPE_IDENTITY check removed | 1 failed |
| M6 `receipt_asset` roles via `or []` | 8 failed |
| M7 `item_problems` roles check removed | 8 failed |
| M8 `stac_extensions` via `or []` | 3 failed |
| M9 served asset entries not checked | 5 failed |
| M10 one direction only (properties) | 3 failed |
| M11 href-less file fields ignored | 4 failed |
| M12 size compared as float | 2 failed |
| M13 non-object link check removed | 1 failed |
| M14 `ambiguous` not a disagreement | 1 failed |
| M15 absolute-href note dropped | 3 failed |
| M16 verify passes no `item_url` | 1 failed |
| M17 fragment kept | 1 failed |
| M18 query not refused | 1 failed |

Every guard the branch added goes red when removed. The gap is the routes the fixtures do
not take (F1), not a guard that never fires.

## Findings

- **[severity: fragile]** src/stacs/receipt.py:296-311 (`_relative_href`, the `urljoin`
  branch) and :282 (`urldefrag`). The round-2 fix still normalises more than dot segments,
  through routes the round-2 test does not reach. For a root-relative or climbing href,
  Python's `urljoin` collapses `//` (`segments[1:-1] = filter(None, ...)`). When an href
  carries a `#`, `urldefrag` re-serialises it, and so does any `urlsplit`/`urljoin` of an
  absolute href; each strips `\t`, `\r`, `\n` and leading C0/space. Reproduced through
  `item_verdict` with `ITEM_URL` and parts `{a/b.tif, x.tif}`. One object, spelled three
  ways, gets two answers:
  - `a//b.tif` gives `same` (not matched);
  - `/catalogue/c/a//b.tif` gives `same` (not matched);
  - `../c/a//b.tif` gives `inconsistent` on `file:checksum`: it was compared with part
    `a/b.tif`.

  The same holds for `x\t.tif` (no match) against `x\t.tif#b` (matched to `x.tif`), for
  `x.tif\n` against `x.tif\n#b`, and for `https://.../c/x.tif\n` (matched). The reverse
  case is an absolute href under an item URL whose path holds `//`. The base path is
  collapsed by `urljoin(item_url, ".")` and the href's path is not, so the asset is never
  compared and no note says so. That is #17's original "compared no asset" symptom, with a
  contradicting digest reading `same`.

  This contradicts NEWS ("Only `.` and `..` segments are removed, so `a//b.tif` ... name[s]
  no part `a/b.tif`"), the README ("a part key and an href must spell a name alike") and
  the `_remove_dots` docstring. The consequence is round 2's: an asset is compared with a
  part whose key names another object. That gives a false `inconsistent`, or `same` when
  the digests agree.

  Remedy shape: do the RFC 3986 §5.2.2 merge by hand (the base directory joined to the
  reference path, then `_remove_dots`) instead of trusting `urljoin`'s path. Refuse, or
  leave unmatched, an href whose text `urlsplit` would change (any `\t\r\n`, or a leading
  C0/space), rather than letting the route decide.
  - **Rule:** code-check.md "A fixture that cannot reach the failure mode" (the round-2
    parametrisation covers the two routes that skip `urljoin`'s collapse and the `#`
    re-serialisation). The same defect is a fix that landed in one of two code paths over
    one normalisation.

- **[severity: fragile]** NEWS.md `## Unreleased`, the `verify` paging bullet. "A link that
  was not an object ... used to raise `AttributeError`" holds at 8390c5d only when the
  non-object link comes before the next link, or the page has no next link.
  `next(l for l in links if l.get("rel") == "next")` stops at the first match. So
  `links: [{"rel": "next", "body": {"token": "t"}}, "junk"]` was followed in 0.4.0, and
  HEAD (verify.py:81) refuses it. As with R1's numeric token, this is a new refusal of
  input the release accepted, and the note files it as a crash fix. A second instance is in
  the roles/stac_extensions bullet: "A non-zero number or `true` used to raise `TypeError`
  out of `audit --require-receipt` and `verify`" is false for `stac_extensions` in
  `verify`, which never reads it (`item_verdict` does not touch it, and `audit_items` runs
  only on the register path, register.py:741). In audit it raised only when the item
  carried processing: or file: fields (the `and` short-circuits). Remedy: name the new
  refusal as a behaviour change, or drop the check for links after the next one, and scope
  the TypeError sentence to roles in both commands and stac_extensions in audit.
  - **Rule:** code-check.md "A guard's scope, escape hatches, and remedies"

## Outside the diff (pre-existing at 8390c5d, recorded, not a finding of this branch)

- register.py:860 resolves a published item's receipt href with `urljoin` and fetches it
  through `catalogue._read_url`, which opens any `file://` URL with `urlopen`. A published
  item on an https bucket whose receipt href is `file:///...` therefore makes `verify` read
  a local file. It is parsed as JSON, hashed and compared with the item's claimed
  `file:checksum`, so it works as a digest oracle over local JSON files. Narrow, and
  unchanged by this branch.
