# Code-check round 2 -- #17 branch (base 8390c5d, HEAD 434e06e)

## Checklist read

- `code-check-python.md`: in full.
- `code-check.md`: the prose of every H3 under `## Mechanisms` (table rows skipped); from
  the stand-alone rules, "Percent-encode a URL at construction, not at consumption". The
  other 18 stand-alone, Security and Spreadsheet headings were not read: none names a tool
  or shape this diff uses.
- `code-check-shell.md`: no headings read. Every heading names shell, git, gh, sed, awk or
  another host tool, and the diff touches none of them (0 read, all skipped).
- `code-check-r.md`: no headings read. The diff has no R (0 read, all skipped).

## How the round-1 fixes were checked

- Probed `_relative_href` / `_origin` directly (Python 3.12.13) on: `file:///` item URLs
  against `file:///` and root-relative hrefs (match), `file://localhost/` (no match; it was
  no match before the branch too), IPv6 with and without a port, `:80` and `:443` filled in,
  an empty port `h:/` (matches, does not read as malformed), userinfo, upper-case
  scheme and host, `//h/...` network-path hrefs, an empty query `?` and an empty fragment `#`,
  an item URL with a query, `//` inside the item URL, `%2F` in the item path, and an `s3://`
  item URL. No result was wrong for an http(s) or file item URL, and none raised.
- Mutation table, each run in a detached worktree against tests/test_receipt.py,
  test_verify.py and test_register.py, each restored before the next:

  | mutation | result |
  |---|---|
  | M1 drop `_origin(split)` from the first `try` | 2 failed |
  | M2 no default port in `_origin` | 1 failed |
  | M3 `netloc.lower()` in place of `hostname` | 2 failed |
  | M4 drop the `item_url` check in `item_verdict` | 1 failed |
  | M5 `"malformed"` not a disagreement | 9 failed |
  | M6 numeric token refused again | 1 failed |
  | M7 dict/list token not refused | 1 failed |
  | M8 prefix guard removed | 1 failed |
  | M9 origin check removed | 3 failed |
  | M10 query check removed | 1 failed |

  Every guard round 1 added goes red when removed. Full suite on HEAD: 997 passed.

## Findings

- **[severity: bug]** src/stacs/register.py:857 -- a published item whose receipt href no
  URL parser reads still ends `verify` with a traceback. `receipt_asset` accepts any
  non-empty string href, and `_receipt_verdicts` resolves it with
  `urllib.parse.urljoin(by_id[item_id], href)` outside every guard, so
  `"https://[bad/a0_receipt.json"` raises `ValueError: Invalid IPv6 URL`. That is not a
  `RegisterError`, so it gets past `run`'s `except RegisterError` (register.py:505). The run
  then dies naming no item, and the drift lists it had already computed are thrown away.
  Reproduced in a worktree with the test harness (`_receipt_run` with a0's receipt href set to
  that string and a1 good). The traceback ends at `register.py:857 in _receipt_verdicts`. The
  line was already there at 8390c5d, so 0.4.0 has the same defect. But it is the class round 1
  fixed for asset hrefs ("one such href would end the run naming no item"), and the fix went
  only into `item_verdict`'s asset loop, not into the other href this function resolves for
  the same published body. Remedy shape: treat a `ValueError` from that `urljoin` as this
  item's `inconsistent` (as `unlinked` does), not as the run's error.
  - **Rule:** code-check.md "A fix lands in one of two callers that share a harness"

- **[severity: fragile]** NEWS.md `## Unreleased`, second bullet -- "So is an href no URL
  parser reads ..., which used to raise `ValueError` out of `verify`" is false against the
  last release. At 8390c5d (v0.4.0) `receipt.py` contains no `urlsplit`/`urljoin`
  (`git show 8390c5d:src/stacs/receipt.py | grep -c urlsplit` is 0). The asset loop only did
  `href in parts`, so 0.4.0 never raised here. The ValueError was introduced and fixed on this
  branch, and the release note describes a behaviour no released version had. (The receipt
  href in the finding above *does* raise in 0.4.0, and still does.)
  - **Rule:** code-check.md "A guard's scope, escape hatches, and remedies"

- **[severity: fragile]** NEWS.md `## Unreleased`, last bullet -- "a next link whose body is
  not an object, or a token that is an object or a list. Each used to raise `AttributeError`
  or `TypeError`." In 0.4.0 (`(nxt.get("body") or {}).get("token")`, then `if not token`) only
  a *truthy* non-object body raised AttributeError, and only a *non-empty* dict or list token
  raised TypeError. A body of `[]`, `""`, `0` or `null`, and a token of `{}` or `[]`, already
  got this function's RuntimeError. Same pattern in the fifth bullet: "A number or a bool used
  to raise `TypeError`" holds for a truthy number or bool, but `roles: 0` and `roles: false`
  became `[]` through `or []` and raised nothing. "Each" quantifies over members that did
  not do it.
  - **Rule:** code-check.md "A guard's scope, escape hatches, and remedies"

- **[severity: fragile]** README.md receipts section, "so an item built from a migrated
  receipt is refused by both" -- `verify` runs the receipt axis only on the `changed` set
  (register.py:647-657). A migrated item whose published and served bodies agree gets no
  verdict and is not refused. The sentence just before it scopes verify to "each item whose
  published and served bodies differ", but "refused by both" reads as unconditional. NEWS
  words the same fact correctly ("where it used to read `same`").
  - **Rule:** none

- **[severity: fragile]** src/stacs/receipt.py `_inside` (posixpath.normpath) -- the
  normalisation does more than the docstring's "dot segments are removed". `normpath` also
  collapses `//` and drops a trailing `/`, so `a//b.tif` and `x.tif/` name parts `a/b.tif` and
  `x.tif`. RFC 3986 resolution keeps an empty segment, and on an object store `a//b.tif` and
  `a/b.tif` are two different keys. So an asset that names another object is compared with
  the wrong part: a false `inconsistent`, or `same` if the digests happen to agree. And a
  receipt listing both spellings makes a good `./a/b.tif` read `ambiguous`, which is a
  disagreement. This is narrow, and it conflicts with the owner's "a part key is the path
  verbatim" only at the edge. It is recorded because `posixpath.normpath` is a filesystem
  normaliser, not a URL one.
  - **Rule:** none
