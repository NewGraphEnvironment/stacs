# Code-check round 4 (#17): the enumeration

Reviewed HEAD 8533aa9 against 8390c5d (v0.4.0), 2026-11-16 UTC. Every probe ran in throwaway
worktrees (`scratchpad/wt4` at HEAD, `scratchpad/wt040` at 8390c5d), never in the checkout.
The scripts are in the session scratchpad: `ref_rfc.py` (RFC reference), `claims.py` and
`claims2.py` (NEWS claims), `mutate.py` (mutation table).

## Checklist read

- `code-check-python.md`: read in full. No rule applies. The diff has no regex, no
  mkstemp/replace and no multi-line f-string braces. The offline guard is untouched.
- `code-check.md` `## Mechanisms`: read the prose of all fourteen H3s. Three apply: "A guard's
  scope, escape hatches, and remedies" (end on an enumeration), "Restore the bug and prove the
  guard fires" (the mutation table) and "A proxy is not the property".
- `code-check-r.md`, by heading: read "Cross-function consistency for label/string
  normalization". The diff normalises one href along two routes, so this rule applies. No
  other R heading names a tool or shape this diff uses.
- `code-check-shell.md`: the diff has no shell, so no heading applies. The remote script is
  untouched.

## Enumeration (a): every changed call that takes a published value

| # | site (HEAD) | input | can raise | normalises | caller handles |
|---|---|---|---|---|---|
| 1 | receipt.py:1651 `_rewritten_by_a_parser` | asset href (str) | no | nothing; classifies C0 anywhere, DEL, space at either end | yes: malformed, so a disagreement. DEL is **not** rewritten by `urlsplit` (measured: `urlsplit("x\x7f.tif").path` keeps it), so this part is wider than its docstring. Behaviour is defensible: RFC 3986 has no DEL. |
| 2 | `href.partition("#")[0]` | href | no | cuts at the first `#`, the RFC fragment delimiter | yes |
| 3 | `"?" in href` | href after the cut | no | none | yes: names no part (owner decision); `?` inside a fragment was cut first |
| 4 | `urlsplit(href)` | href | ValueError (unclosed `[`, invalid bracketed host, NFKC netloc) | lowercases the scheme; strips leading C0 and removes `\t\r\n` (row 1 runs first) | yes: `except ValueError`, malformed |
| 5 | `_origin(split)` (`.port`, `.hostname`) | href | ValueError: port not a number, out of range, sign, underscore, non-ASCII digit (all measured) | host lowercased, IPv6 unbracketed, userinfo dropped, default port filled in, empty port read as the default | yes, same `try` |
| 6 | receipt.py:1688 relative route, `_inside(href)` then `_remove_dots` | href | no | dot segments only; None when it climbs | **no, see F1**: an empty leading segment after dots are removed |
| 7 | `item_verdict` item_url check | item_url | ReceiptError (not str; urlsplit/port ValueError) | none | yes: register catches ReceiptError and marks that item inconsistent |
| 8 | receipt.py:1696 `directory = … or "/"` | item_url | no | empty path read as `/` | RFC 5.2.3 for an authority base. For a base with no authority the RFC gives `""`, but its own `remove_dot_segments` clamps the same way (`file:x.json` + `../x.tif` is `file:x.tif`), so the result matches. A *relative* item_url is not a URL and is reachable only through the public API. |
| 9 | `_origin(split, base.scheme)` network-path and absolute | href, item_url | no (ports read above, item_url validated) | as row 5 | yes |
| 10 | path-absolute `path = href` | href | no | none | yes |
| 11 | merge `directory + href` | href | no | none | yes |
| 12 | receipt.py:1708 `_remove_dots(path)`, `_remove_dots(directory)` | both | no | dots only; root clamp | yes; None only for a non-rooted base |
| 13 | receipt.py:1711 `startswith` then `_inside(rest)` | — | no | — | **no, see F1**: a remainder that starts with `/` (`dir//x`) is refused, while the relative route returns `/x` for the same file |
| 14 | `_part_key`: `href in parts`, `_inside(k)` | href, part keys | no (`isinstance(k, str)`) | key: dot segments only | yes |
| 15 | asset loop `asset.get("href")` | asset | no (non-object entries refused earlier) | — | non-str href, or a missing/empty href with file fields: disagreement |
| 16 | `_whole(asset["file:size"])` | size | ReceiptError | int; refuses bool, NaN, inf, fractions, negatives | yes: `except ReceiptError`, disagreement; no OverflowError (measured with 10**400) |
| 17 | `canonical(properties[key])`, mirrored, both directions | properties | ReceiptError on NaN (unchanged from 0.4.0) | — | register catches ReceiptError |
| 18 | register.py:860 `urljoin(by_id, receipt href)` | receipt href | ValueError | collapses `//`, strips `\t`, accepts a non-strict scheme | ValueError caught, so inconsistent. The normalisation changes only which receipt URL is fetched, and the fetched bytes are still bound by `receipt_sha256` against the asset's checksum (stacs#19 is adjacent). It is not a part match. |
| 19 | register.py:846 `doc.get("properties")` | published body | no (a dict once `receipt_href` is non-None) | — | non-object properties give NO_RECIPE_IDENTITY |
| 20 | validate.py:218 `receipt_href(doc)` | published body | no (already a dict) | — | yes |
| 21 | `receipt_asset` `_list(asset, "roles")`, then `in` | roles | no (`in` on a list uses `==`) | non-list read as `[]` | yes |
| 22 | `item_problems` `_list(item, "stac_extensions")`, `"roles" in asset` | item | no | — | the schema reports a non-list `stac_extensions`; non-list roles reported |
| 23 | verify.py `_search_pages` loop: `isinstance(l, dict)`, `nxt.get("body")`, `next_body.get("token")`, `token in seen_tokens`, `{**body, **nxt["body"]}` | /search page | RuntimeError only | — | yes: token is str, int, float or bool, so hashable. `nxt["body"]` is a dict whenever a token was read. A NaN token is unchanged from 0.4.0 |

**`_relative_href` against an independent RFC 3986 §5.2 reference** (`ref_rfc.py`). The
reference uses the Appendix B parse, the strict 5.2.2 transform, the 5.2.3 merge and a literal
5.2.4 string-buffer `remove_dot_segments`. It applies the owner's equivalences (scheme and
host case, the default port, an empty port, userinfo ignored, no percent decoding, a query
names no part) and imports nothing from `stacs`.

The run covered 5,763,296 cases: 14 item URLs (None, plain, nested, directory, empty path, root
item, uppercase host with `:443`, userinfo with `:80`, IPv6 with a port, two `file:///`, a `//`
base, a `./` base, a `/../` base), all one- to three-segment combinations of `"" . .. a c x.tif
%2e%2e %2e` under 18 prefixes (scheme, case, userinfo, port, network-path, `file://`,
`file://localhost`, `https:`, IPv6, path-absolute), extra edge hrefs (empty, `#`, `?`,
`x.tif?`, `a:b.tif`) and 16 part-key sets. Hrefs the code calls malformed were left out of the
comparison, since they are refused by design.

The run found 82 disagreement classes, in exactly two families:

- **A (real, F1).** An href or key whose dot removal leaves an empty leading segment:
  `a/..//../x.tif`, `c/..//../c/x.tif`, `/c//x.tif` against key `.//x.tif` or `a/..//x.tif`. It
  shows on every base, and on None as well.
- **B (artefact of the reference).** Key `a:b.tif` against href `./a:b.tif`. The reference read
  the key as a URI reference (scheme `a`). The contract keys parts by path, and the code is
  right.

No other disagreement: `file:///` bases, `//` and `/./` and `/../` bases, IPv6, ports, userinfo,
case, `%2e%2e` (not a dot segment, correctly), `//`, trailing `/`, empty, `#` and `?` all agree.

## Enumeration (b): "used to / no longer / as before" claims in NEWS `## Unreleased` and README

Each claim was run against `wt040` (8390c5d) and `wt4` (HEAD). The outputs are in the session
transcript.

| claim | 0.4.0 measured | HEAD measured | verdict |
|---|---|---|---|
| L11-16: a recipe id over a migrated receipt, or software (`{}` included) over a versionless receipt, "used to read `same`" | `same` when the two sides agree. With the served side differing: `rebuilt` (other datetime) or `changed` (other recipe) | `inconsistent` | **Narrow**: true of an agreeing pair only (F2) |
| L16: "A field the item leaves out is still not a disagreement" | `same` | `same` | true |
| L22-25: "Before, only an href spelled exactly as a part key was compared", so a contradicting checksum read `same` behind other spellings, and absolute hrefs compared nothing | `x.tif` inconsistent, `./x.tif` and absolute `same` | `./x.tif` inconsistent; absolute inconsistent with item_url, `same` (plus a note) without | true |
| L33-35: a non-object asset entry, either side, described or not, "used to be skipped" | `same` in all 4 | `inconsistent` in all 4 | true |
| L35-37: size "no longer raises OverflowError", and sizes beyond a double "no longer compare equal" | OverflowError; 2**60+1 against 2**60 `same` | inconsistent | true |
| L41-43: audit files the item "no longer with items that carry no receipt" | `missing_receipt` | `bad_receipt` with NO_RECIPE_IDENTITY | true |
| L43: `verify` reports it `inconsistent` "where it used to read `same`" | `same`, or `rebuilt` (served checksum or datetime differs), or `changed` (served carries an id). The verify axis runs only on the changed set, so all three are reachable | inconsistent (short-circuit before item_verdict) | **Narrow** (F2) |
| L45-49: roles or extensions, "A non-zero number or `true` used to raise TypeError …; a string or object was searched with `in`" | roles 1/True TypeError, 0 none; `"metadata"` and `{"metadata":1}` link; ext 1/True TypeError only with processing fields; an ext string holding the URL counted as listed | no raise; non-list roles reported (null included) | true |
| L51-54 paging: each "used to raise AttributeError or TypeError", body or token only when non-empty | non-object link before next or with no next: AttributeError; body `"abc"`/`[1]`: AttributeError; body `[]`: RuntimeError; token object/list: TypeError; `{}`: RuntimeError | all RuntimeError | true |
| L54: "A link after the next link is not read, as before" | followed (2 items) | followed (2 items) | true |
| L55: "A numeric token is followed, as it was" | 5 and True followed, 0 refused | same | true |
| L56-58: receipt href no parser reads "used to end the run with a ValueError that named no item" | `urljoin` raises `Invalid IPv6 URL`; `run` catches only RegisterError | inconsistent, run continues | true |
| README L228-232 and L241-243 | (no historical claim) | `./x.tif` matches; verify passes item_url; percent-encoding verbatim; audit refuses a migrated item; verify inconsistent on the changed set | true |

## Enumeration (c): mutation table for 8533aa9's guards

Each mutation was applied to `wt4` after `git checkout --` and checked to have taken
(count == 1 and the file changed). Each ran `tests/test_receipt.py`, `test_verify.py`,
`test_register.py` and the receipt and verify doctests. The tree read clean afterwards.

| mutation | result | red arm |
|---|---|---|
| M1 `_rewritten_by_a_parser` check removed | 18 red | `test_an_href_a_parser_would_rewrite_is_malformed_on_every_route[*]` |
| M1a control-char half removed | 14 red | same test (NUL, CR, newline, absolute …) |
| M1b end-space half removed | 4 red | same test (leading and trailing, with and without item_url) |
| **M1c `c == "\x7f"` removed** | **green** | none |
| M2 query refusal removed | 1 red | `test_an_href_that_names_no_part_is_not_compared[absolute…]` |
| M3 fragment not cut | 1 red | `test_an_href_that_names_a_part_is_compared_however_it_is_spelled[with…]` |
| M4 network-path takes its own empty scheme | 1 red | `…however_it_is_spelled[network-path…]` |
| **M5 `or "/"` removed (empty base path)** | **green** | none. HEAD: `("https://h/x.tif", "https://h")` gives `x.tif`; the mutant gives none |
| M6 path-absolute branch removed | 2 red | `…[path-absolute]`, `test_an_item_url_whose_path_holds_a_doubled_slash…[path-absolute]` |
| M7 merge drops the directory | 2 red | `…[climbs…]`, `…doubled_slash…[climbing…]` |
| **M8 directory dot segments kept** | **green** | none. Reachable from register: `urljoin` keeps `/c/./item.json` from an absolute collection link (measured). HEAD gives `x.tif` for `../c/x.tif`; the mutant gives none |
| **M9 `directory is None` removed** | **green** | none. Unreachable with a rooted item_url; only a relative item_url through the public API |
| **M10 `path is None` removed** | **green** | none. Same reach: with a relative item_url (`items/x.json` and `../../x.tif`) the mutant raises AttributeError out of `item_verdict` |
| M11 non-object link check removed | 1 red | `test_paging_refuses_every_early_exit[payloads5-not…]` |
| M12 `break` at the next link removed | 1 red | `test_a_malformed_link_after_the_next_link_is_not_read_as_it_was_not_before` |

## Findings

- **[severity: bug]** src/stacs/receipt.py:1609 and 1621, reached from 1688 and 1711:
  dot-segment removal disagrees with RFC 3986 when it leaves an empty leading segment. The
  relative route and the merge route then name different parts for one file.
  - **Mechanism.** `_remove_dots` takes `out == [""]` to mean "at the root". In a relative path
    it also means "an empty first segment left by `//` after everything before it was popped".
    A following `..` is then swallowed instead of popping that empty segment, and the result is
    joined with a leading `/`. Separately, `_inside` tests `startswith("/")` *before* removing
    dots, so it returns `/x.tif` for `.//x.tif` or `a/..//x.tif`. The merge route's remainder
    for the same object is refused by the same `_inside` (line 1711), because it starts with
    `/`.
  - **Measured on HEAD**, with the receipt's part digest `b…` and the asset's `c…`:
    - `a/..//../x.tif` names `x.tif` under RFC 5.2.4 (`/c/a/..//../x.tif` is `/c/x.tif`).
      Against part `x.tif`, the code gives `_relative_href = ('/x.tif', None)` and the verdict
      is `same`, with or without item_url.
    - With parts `x.tif` and `.//x.tif`, the same href is compared with `.//x.tif`, a part it
      does not name.
    - Part `.//x.tif` is matched by `././/x.tif` (relative route) but missed by
      `https://h/c//x.tif` and by `/c//x.tif`, which name the same object; those verdicts read
      `same`.
  - **Scope.** This is round 3's class ("a climbing href and a plain one named different
    parts"), one axis over. The spellings are unusual, so the likelihood is low, but the
    consequence is the one #17 exists to prevent. No test holds `..//` or `.//`.
  - **A fix shape.** Track rootedness by whether the input started with `/`, not by
    `out == [""]`. Or send the relative route through the same merge against a sentinel
    directory, so both routes are one code path, and stop `_inside` refusing a remainder that
    starts with `/`.
  - **Rule:** `code-check-r.md`, "Cross-function consistency for label/string normalization";
    `code-check.md`, "A guard's scope, escape hatches, and remedies".
- **[severity: fragile]** NEWS.md:11-16 and NEWS.md:39-40: two behaviour-change sentences
  state the v0.4.0 verdict as `same`. Measured at 8390c5d, it was `same` only when the
  published and served mirrored fields agreed; it was `rebuilt` when the served checksum or
  datetime differed, and `changed` when the served item carried a recipe id. On `verify`'s
  axis the item is always in the changed set, so all three were reachable. The `rebuilt` and
  `changed` cases now read `inconsistent` too, so an id moves between `receipts_<verdict>.txt`
  lists. The sentence "where it used to read `same`" leaves out two of the three old outcomes.
  Suggested wording: "where it used to read `same`, `rebuilt` or `changed` by the served body".
  - **Rule:** `code-check.md`, "A guard's scope, escape hatches, and remedies" (compression
    runs both ways: execute a claim against each source).
- **[severity: fragile]** src/stacs/receipt.py:1651, 1696, 1708 and 1710: four guards added in
  8533aa9 survive their own removal (table rows M1c, M5, M8, M9/M10).
  - **M8** is reachable from `verify`: `urljoin` keeps `/c/./item.json` from an absolute
    collection link. HEAD is correct there (the reference agrees on a `./` base), but nothing
    pins it.
  - **M5** is reachable from a collection that links an item at a host root.
  - **M1c's** docstring says a parser would rewrite the href, which `urlsplit` does not do for
    DEL.
  - **M9/M10** are reachable only through the public `item_verdict` with a non-rooted item_url.
    There M10's removal raises AttributeError, not ReceiptError.
  - **Rule:** `code-check.md`, "Restore the bug and prove the guard fires"; the repo
    `CLAUDE.md` says "A guard added here gets a mutation check".

**Does anything sit above its source of truth?** Yes, F1. On every other axis I enumerated,
the code agrees with the independent RFC reference and the NEWS claims hold when re-run
against 8390c5d. The two exceptions are F2's narrowing and the untested guards in F3.
