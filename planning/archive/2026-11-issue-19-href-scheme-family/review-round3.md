# Code-check round 3 -- #19 (branch vs 38a45a3, planning/ excluded)

## Checklist read

- `code-check-python.md`: in full.
- `code-check.md`: the prose of all 14 H3s under `## Mechanisms` (table rows skipped), including
  "A guard's scope, escape hatches, and remedies" in full. Standalone rules read: "Percent-encode
  a URL at construction, not at consumption" and "An assertion that matches an interpolated
  value cannot see the claim around it". The other 23 standalone/Security/PDF headings were not
  read: none names a tool, shape or pattern this diff uses.
- `code-check-r.md`: no heading read (the diff has no R). All headings unread.
- `code-check-shell.md`: no heading read (the diff has no shell; the remote script is untouched).
  All headings unread.

## The mechanism behind rounds 1, 2 and this round

**A consequence's reach is written from the guard's position, not from the code path that
produced the consequence.** The new guard sits in `_run` before any mode branches (register.py
563-569) and in `_receipt_verdicts`, so the guard reaches *every* mode. The harm it prevents
happened *after* mode-specific selection: `ids` fetches only the ids named (`fetch = [(i, by_id[i])
for i in todo]`, 580), `all`/`ids` dryrun returns before the fetch (602-609), `drift` upserts
`missing | changed` (643), and the receipt axis runs only in `verify` under `require_receipt` on
`changed` (659-665). A sentence describing "what the fix stops" inherits the guard's universal
scope and overstates the subset the old code actually reached. Round 1 (receipt axis scope),
round 2 (which modes upserted) and Finding 1 below are each that.

## Findings

- **[severity: fragile]** tests/test_register.py:2266-2268 -- the docstring of
  `test_an_item_link_to_a_local_file_refuses_an_http_catalogue` says a `file:///` item link "had
  that file read in every mode". Measured by restoring the old line (`urljoin(coll_url, h)` at
  register.py:566) in a detached worktree and printing the `reads` fixture per parametrization:
  the local file was read in `all`, `drift` and `verify`, and **not** read in the test's own
  `ids` case (ids file names `a0`, not `a9`; `fetch` holds only the named ids) nor in `all`
  dryrun (returns at 609 before the fetch). Pre-fix outputs: `ids False ... file_reads []`,
  `all True ... file_reads []`. The test still goes red in both cases (on `r.writes`/`r.probes`),
  so the guard is sound; the sentence is false for two of its own five parametrizations, and it is
  the record a later reader uses to decide which modes were exposed. Same shape as rounds 1 and 2.
  A wording that holds: "had that file read in every mode that fetched it (`all`, `drift`,
  `verify`, and `ids` when it names the item), and in `all`, `ids` or `drift` upserted".
  - **Rule:** code-check.md "A guard's scope, escape hatches, and remedies"

- **[severity: fragile]** README.md:154-156 -- "`register` refuses before writing wherever it can:
  ... an item link duplicated, outside the collection's URL scheme ...". The code refuses an item
  link outside the collection's scheme *family*: an https collection linking an `http://` item is
  outside its URL scheme and is accepted (`resolve_href`, catalogue.py:141-142; pinned as accepted
  by tests/test_catalogue.py `("http://bucket...", "https://x...")` and the `ITEM, "http://..."`
  rows). The qualifier ("http and https mix") is 16 lines later, in a different section. NEWS:9-11
  carries the qualifier in the same bullet, so it holds there. A reader of line 155 alone expects a
  downgrade to http to be refused. Weakest of the two findings; "outside the collection's scheme
  family (http and https mix)" closes it.
  - **Rule:** code-check.md "A guard's scope, escape hatches, and remedies"

Nothing else found in the code. `resolve_href` and both call sites behave as described; see the
probes and the table.

## Probes run (detached worktree, removed after; checkout untouched)

| probe | result |
|---|---|
| new tests on HEAD (`-k 'resolve_href or local_file or relative_item_links'`) | 28 passed |
| M1: receipt href back to `urljoin` (register.py:870) | receipt test red: `0 same, 2 rebuilt, 0 changed, 0 inconsistent` -- confirms the docstring's "reading it would give `rebuilt`" |
| M2: item link back to `urljoin` (register.py:566) | all 5 parametrizations red; per-mode file reads: all yes, ids no, drift yes, verify yes, all-dryrun no |
| `urlsplit(" file:///x").scheme` across installed interpreters | `'file'` on 3.9.25, 3.10.20, 3.11.11, 3.11.15, 3.12.x, 3.14.7; `''` on 3.9.6 (pre CVE-2023-24329 fix). On an unfixed interpreter `urljoin` treats the href as relative and the result stays `https://...`, so it is not a bypass, only a test row that would fail there (3.11.0-3.11.3 are within `requires-python >=3.11`; CI runs current 3.11). Not a finding. |
| `_read_url` dispatch vs `resolve_href` | a URL `resolve_href` admits from a web base cannot start with `file://` (urlsplit of any `file://...` reads scheme `file`); a `FILE://` or `HTTP://` it admits from a web base goes to requests, whose default Session mounts only http(s) adapters. From a file base `urljoin` re-serialises same-scheme results to lowercase `file:///`. |

## Enumeration: every quantified or scoped claim the diff's prose makes

| claim | file:line | code that decides it | verdict |
|---|---|---|---|
| "an href a published body supplies is fetched only within the scheme of the URL it is resolved against, by the new `catalogue.resolve_href`" | NEWS.md:8-9 | the only fetches of published-body hrefs are `fetch_bodies(hrefs)` register.py:615 and `fetch_bodies(wanted)` :895; both lists come from `resolve_href` (:566, :870). Asset hrefs are compared, never fetched (receipt.py 1641-1810, no fetch). `validate` reads local paths. | holds |
| "http and https mix, and `file://` is read only from a `file://` base" | NEWS.md:9-10 | `_SCHEME_FAMILY`, catalogue.py:110, :141-142 | holds |
| "An item link ... that leaves the collection's scheme refuses `register` in every mode" | NEWS.md:10-11 | register.py:563-569, before the mode branch at :574 and before the dryrun returns (:602, :728); `MODES` (:50), CLI register modes are all/ids/drift (cli.py:337); `verify` refuses too (unclaimed) | holds ("scheme" = family, defined in the same bullet) |
| "... before anything is fetched or written" | NEWS.md:11-12 | collection.json is read at :536 before the check (it is what is judged); no item fetch, probe or write precedes :566 | holds in substance; literally, collection.json is fetched first |
| "A receipt href that leaves its item's scheme makes the item `inconsistent` where `verify` reads receipts (under `require_receipt`, for an item whose published and served bodies differ)" | NEWS.md:12-14 | `_receipt_verdicts` called only in verify, under `require_receipt`, coll_state != missing, on `changed` (:659-665); an off-family href -> `unlinked` -> `inconsistent` (:869-879). A changed item lacking `receipt:recipe_id` is `inconsistent` earlier (:853-861), still `inconsistent`. | holds |
| "Before, an absolute `file:///...` href in a catalogue served over https had a file ... read: a receipt was hashed and reported on, and in `all`, `ids` or `drift` an item was upserted and served by the API" | NEWS.md:14-16 | pre-fix, M2 probe: item upserted in all and drift (writes 2), ids only when named; receipt read only on the verify receipt axis | holds (existential, no "every") |
| "`register` refuses ... an item link duplicated, outside the collection's URL scheme ..." | README.md:154-156 | catalogue.py:141-142 accepts http under https | **imprecise** -- Finding 2 |
| "An item link is read only over the scheme the collection is served over, and a receipt only over its item's: http and https mix, and `file://` is read only from a catalogue that is itself `file://`" | README.md:171-173 | :566 against `coll_url`; :870 against `by_id[item_id]` (already a resolved item URL, so a file receipt implies a file item implies a file catalogue) | holds |
| "Where the catalogue declares receipts, `verify` reports an item whose published and served bodies differ, and whose receipt is linked anywhere else, `inconsistent`" | README.md:173-175 | :659-665, :869-879 | holds |
| "any other item's receipt is never fetched" | README.md:175 | the only receipt fetch is :895, reached only from :665 | holds |
| `resolve_href`: "For an href a published body supplies: an item link against its collection, a receipt against its item" | catalogue.py:116-117 | the two call sites, register.py:566, :870 (grep: no other caller) | holds |
| "An absolute href replaces the base" | catalogue.py:117 | `urljoin` | holds |
| "`file` is read only from a `file` base, which is how a catalogue on disk (the tests') is served" | catalogue.py:119-120 | :141-142; tests' `bucket.as_uri()` (test_register.py:316) | holds |
| "Hosts are not compared" | catalogue.py:121 | no netloc comparison in :138-146 | holds (accepted tradeoff) |
| "`urlsplit` ... lowercases it and strips what a parser would (a leading space, a tab), so `FILE:///x` and ` file:///x` are refused like `file:///x`" | catalogue.py:123-124 | `urlsplit(url).scheme` at :140 | holds on 3.11.4+ (all interpreters on this machine and in CI); on an unfixed interpreter the href stays in https rather than being refused, so the security claim still holds |
| "Raises ValueError, as `urljoin` already does on an href no parser reads" | catalogue.py:125 | :138, :143; test_catalogue `https://[bad` | holds |
| `_read_url`: "An href a published body supplies reaches here only from a file:// base" | catalogue.py:155-156 | callers of `fetch_bodies` (:615, :895) take only `resolve_href` output; `_read_url` direct call :536 is `bucket_url` (operator config) | holds |
| "Every other URL goes to requests, which has no file: adapter, so a redirect cannot reach a local file" | catalogue.py:156-158 | `requests.Session()` default adapters http(s) only (:165) | holds |
| `_run`: "a file:// link in a collection served over https would have a local file read, and in `all`, `ids` or `drift` upserted ... Refused before anything is fetched" | register.py:559-562 | M2 probe; "would" is conditional (ids only when named); collection.json read at :536 | holds |
| `_receipt_verdicts`: "a file:// receipt for an item served over https would have a local file read, hashed and reported on" | register.py:866-868 | pre-fix :870 + :895 + :911 | holds |
| error: "item link of {i!r} cannot be read: ..." | register.py:568 | raised for both off-family and unparseable hrefs | holds |
| error: "links a receipt whose href {href!r} is not a URL it may be read from ({e}), so its provenance cannot be established" | register.py:872-874 | both ValueError causes (urljoin parse, family) | holds |
| error: "{href!r} leaves the scheme of {base}: it resolves to {scheme or 'no'} scheme, and an href is read only within http/https, or file from file" | catalogue.py:143-145 | also raised for an unsupported *base* (s3://), where the href did not "leave" anything | holds loosely; base check is the operator's config and the message still names the rule |
| test_catalogue comment "urljoin keeps an absolute href's case" | test_catalogue.py `FILE:///` row | urljoin returns the href verbatim when schemes differ | holds |
| test_catalogue comment "urlsplit strips what a parser would" | test_catalogue.py ` file:` row | as above | holds on 3.11.4+ |
| `http_bucket`: "every other test here serves it as file://" | test_register.py:2192-2193 | the other `bucket_url=` uses (:1234, :1766, :1780) build Targets without serving `env/bucket`; `_run` default `bucket.as_uri()` (:316) | holds |
| `reads`: "Every URL `fetch_bodies` reads" | test_register.py:2212 | patches `catalogue._read_url`, which `fetch_bodies` looks up at call time; register.py's own `_read_url` import (collection.json) is not recorded, consistent with the claim | holds |
| receipt test: "reading it would give `rebuilt`" | test_register.py:2238-2239 | M1: `2 rebuilt` | holds |
| item-link test: "had that file read in every mode" | test_register.py:2266-2267 | M2 per-mode reads | **false** for `ids` not naming it and for dryrun -- Finding 1 |
| item-link test: "and in `all`, `ids` or `drift` upserted" | test_register.py:2267-2268 | M2: writes in all, drift; ids only if named | holds as existential |
| item-link test: "Refused before any item is fetched or anything is written" | test_register.py:2268-2269 | :566 before :615, :762 | holds |
| item-link test: "A dryrun is refused too, before it probes the host" | test_register.py:2284-2285 | :566 before :593-594 | holds (`r.probes == 0`) |
| relative-links test: "(A relative receipt over http is item `a1` in the receipt test above.)" | test_register.py:2302-2303 | `_item_with_receipt` href `f"{item_id}_receipt.json"` (:1854), written by `before` | holds |
