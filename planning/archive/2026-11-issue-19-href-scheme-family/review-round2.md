# Code-check round 2 for #19

Branch `19-verify-follows-a-published-item-s-receip` at 74742d0, diff against merge-base 38a45a3.

## Checklist read

- code-check-python.md: in full.
- code-check.md: the prose of every H3 under `## Mechanisms` (all fourteen, table rows and
  evidence blocks skipped). No `## Rules that stand alone` heading names a tool or shape
  this diff uses beyond "Percent-encode a URL at construction", whose index line I read; not
  applicable (no URL is built from filenames here).
- code-check-r.md: no heading read in full; none names a tool or shape this diff uses (the
  diff is Python only). Not read: all of them.
- code-check-shell.md: no heading read in full; the diff changes no shell, and the remote
  script is untouched. Not read: all of them.

## What I checked, and how

- Suite in a detached worktree at HEAD: 1075 passed.
- Mutation, each guard site restored to `urllib.parse.urljoin` in turn (worktree, removed
  after): the item-link site reddens all five parametrized cases of
  `test_an_item_link_to_a_local_file_refuses_an_http_catalogue` (all, ids, drift, verify,
  all+dryrun); the receipt site reddens
  `test_a_receipt_href_to_a_local_file_is_never_read_from_an_http_catalogue`. So the new
  `ids` and dryrun cases are not vacuous: pre-fix, `ids` naming `a0` never fetches the
  `a9` link and would exit 0, and the dryrun exits 0 after probing, so both fail
  `rc != 0` / `probes == 0` without the guard.
- README "Where the catalogue declares receipts, `verify` reports an item whose published
  and served bodies differ, and whose receipt is linked anywhere else, `inconsistent`; any
  other item's receipt is never fetched": true of the code. The receipt axis runs only in
  `mode == "verify"`, only under `target.require_receipt` (which README line 239 defines as
  the catalogue declaring receipts), only over `changed`; an off-scheme href lands in
  `unlinked` and becomes `ItemVerdict("inconsistent", ...)` (a missing recipe identity is
  checked first, and is also `inconsistent`, so the claim still holds). No other path
  fetches a receipt: `audit_items` reads only the item, `item_verdict` compares hrefs as
  strings, and the only `fetch_bodies` callers are the two guarded sites. NEWS's
  "(under `require_receipt`, for an item whose published and served bodies differ)" is the
  same set.
- `resolve_href`: an http(s) base can only yield a URL whose `urlsplit` scheme is http or
  https, and `_read_url`'s urllib branch needs a literal `file://` prefix, so no
  published href from a web base reaches urllib; everything else goes to `requests`, which
  has no file adapter. Uppercase / whitespace / control-char variants are refused or
  normalised as the tests say.

## Findings

- **[severity: fragile]** NEWS.md:16 (also src/stacs/register.py:561 and the docstring at
  tests/test_register.py:2267) — the security note says that before the fix "in `all` or
  `ids` an item was upserted and served by the API". `drift` did it too: `todo` in drift is
  `missing | changed`, so a `file://` item link whose id the API did not yet serve was
  fetched, passed `_digests` and the audit, and was loaded. Measured: with the item-link
  guard reverted to `urljoin`, the `drift` case of
  `test_an_item_link_to_a_local_file_refuses_an_http_catalogue` gets past the load and
  fails only at the read-back (`after registering, 1 id(s) are not served ... ['a9']`), i.e.
  the remote load ran on the local file. An operator reading the release note to decide
  which past runs could have published a local file into pgstac would skip their `drift`
  runs, which is the mode routinely scheduled. Name `drift` beside `all` and `ids` (and
  in the register.py comment and test docstring, which say `all` alone).
  - **Rule:** code-check.md "A guard's scope, escape hatches, and remedies"

No other issues found. The round-1 fix (README/NEWS scope of the receipt axis) is now true
of the code in every case it names, and the new test cases test what they claim.
