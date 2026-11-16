# Code-check round 1: #19 branch (38a45a3...d032f86, planning/ excluded)

## Checklist read

- code-check-python.md: in full.
- code-check.md: the prose of all 14 H3s under `## Mechanisms` (table rows and evidence
  blocks skipped). From the stand-alone rules, "Percent-encode a URL at construction, not
  at consumption" (the diff resolves URLs). The other stand-alone, Security and
  Spreadsheets headings were not read (18): none names a tool or shape this diff uses.
- code-check-shell.md: no headings read (0 of its index). The diff has no shell, and
  `remote_script` is untouched.
- code-check-r.md: no headings read (0 of its index). The diff has no R.
- Repo CLAUDE.md above `# Agent Operating Rules`: read.

## What was checked, and how

- **Full suite at d032f86** in a detached worktree: 1073 passed (`uv run pytest -q`, 42 s).
  Only `planning/` moved since then (eff81f8), so the result still describes the code.
- **Mutation, receipt site** (`_receipt_verdicts`, `resolve_href` changed back to
  `urljoin`): `test_a_receipt_href_to_a_local_file_is_never_read_from_an_http_catalogue`
  fails. The other new register tests pass.
- **Mutation, item-link site** (`_run`, changed back to `urljoin`):
  `test_an_item_link_to_a_local_file_refuses_an_http_catalogue[all|drift|verify]` fail (3).
- **Can the property be bypassed?** No. A local read happens only in `_read_url`'s
  `url.startswith("file://")` branch. The web branch uses `requests`, which has no `file`
  adapter, and an `InvalidSchema` on a redirect to `file:` is a `RequestException`. A string
  that literally starts with `file://` always has the `urlsplit` scheme `file`, so a web base
  refuses it. Case, whitespace and control-character variants either get the scheme `file`
  (and are refused) or get no scheme. Then `urljoin` treats them as relative and they stay
  web URLs. That holds whether or not the installed Python's `urlsplit` strips leading
  C0 characters and spaces: every route fails safe.
- **Fetch keys stay consistent:** `resolve_href` returns `urljoin`'s string unchanged, so
  `fetch_key(by_id[i])`, `published_digests` and `item_url` see the same URLs as before.
- **Sibling callers:** I grepped every fetch (`_read_url`, `fetch_bodies`, `urlopen`,
  `session.get`, `requests.get`) and every `urljoin`. The only other `urljoin` on a server
  href is `verify.collections_listed`, which follows the API's `next` link. That goes
  through `requests`, so it cannot read a local file. `receipt._relative_href` resolves
  asset hrefs but fetches nothing. No sibling site is left unguarded.
- **`_read_url`'s new comment** ("reaches here only from a file:// base"): it holds. The
  `fetch_bodies` callers are register.py:615 (resolved links) and register.py:895 (resolved
  receipts). The direct call at register.py:536 reads `coll_url`, which comes from config.

## Findings

- **[severity: fragile]** README.md:174-175 and NEWS.md:12-13: two docs sentences claim more
  than the code does.
  - The README says "`verify` reports an item whose receipt is linked anywhere else
    `inconsistent`".
  - NEWS says "A receipt href that leaves its item's scheme makes the item `inconsistent` in
    `verify`".
  - The code checks a receipt href only for an item that is on the receipt axis. That needs
    `require_receipt` set, the collection registered (`coll_state != "missing"`), and the
    item in `changed` (register.py:657-665).
  - Any other item linking a `file:///...` receipt is never looked at. If every item is in
    sync, `verify` prints `IN SYNC` and exits 0.
  - The file is not read, so this is not a security hole. But an operator who reads either
    sentence as "verify flags any item whose receipt points off-scheme" will trust a clean
    run that never looked.
  - The README's own receipts section (README.md:241-245) adds the qualifier "when its
    published and served bodies differ" to the matching sentence. These two sentences do not.
  - **Rule:** code-check.md "A guard's scope, escape hatches, and remedies"

No code defects found. Both guards fire under mutation. The security property holds by
construction, not just on the fixtures.
