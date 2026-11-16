# Task: verify follows a published item's receipt href to any scheme, file:// included (#19)

**If we do it:** `verify` reads a receipt only from where the catalogue itself is served. **If we never do:** a published item can make `verify` read a local file on the machine running it, parse it, hash it and report whether its digest matches the item's claim.

## Context

`verify` resolves an item's receipt href against the item's URL (`register.py:860`,
`urllib.parse.urljoin`) and fetches it through `catalogue.fetch_bodies` → `_read_url`,
which reads any `file://` URL with `urlopen` (`catalogue.py:112`). An absolute
`file:///…` href replaces the base, so an item served over https can make `verify` read,
parse and hash a local file and report something about it.

Exploration found a **second, larger site**, which the issue's second checkbox asks for:
item links in `collection.json` are resolved against the collection URL the same way
(`register.py:561`) and fetched in **every** mode. A `file://` item link in an https
collection is read during `register all/ids` and, if it is a JSON object whose `id` matches
its basename, **upserted into pgstac and served by the API**.

Not in scope (no published-body href reaches a fetch): asset hrefs (`item_verdict` only
normalises them, never fetches; the audit checks presence), and the API's own `/collections`
`next` href (`verify.py:532`), which is the configured API's answer and goes through
`requests`, which has no `file:` adapter. Other schemes urllib would open (`ftp:`,
`data:`) never reach `urlopen`: `_read_url` sends everything but a `file://` prefix to
`requests`, which refuses them. (Corrected after a probe: `urljoin` returns an absolute href
with its own scheme as written, so `FILE:///x` and `file:/x` reach `_read_url` unchanged and
go to `requests`; only a literal `file://` prefix was ever read.) The check reads the scheme
with `urlsplit`, which lowercases it and strips leading whitespace and tabs, so it refuses a
superset of what reaches `urlopen`.

## Decided at the gate

- **The rule is the scheme family** (owner, 2026-11-16): an href resolved against an
  `http`/`https` URL must resolve to `http`/`https` (mixing allowed), and `file` only from a
  `file` base. Any other resolved scheme is refused. Hosts are not compared, so a
  catalogue whose items or receipts sit on another host still works. An https item pointing
  at an internal http host is still fetched (accepted).
- It applies to **both** sites: receipt hrefs (verify) and collection item links (all modes).
- A refused **item link** refuses the run before any fetch, like the existing child-link
  and `.json` refusals in `collection_item_links`. A refused **receipt href** marks its own
  item `inconsistent` and the run goes on, as a non-URL receipt href already does.

## Phase 1: Tests first (fail before the fix)

- [x] `tests/test_catalogue.py`: unit tests for a new `catalogue.resolve_href(base, href)`:
  relative and absolute same-family hrefs resolve; http↔https mix allowed; `file:///x`,
  `FILE:///x`, `file:/x` from an https base refused; `ftp://`, `data:` refused; `file`
  from a `file` base allowed; an `https` href from a `file` base refused; an unparseable
  href still raises `ValueError`.
- [x] `tests/test_register.py`: run-level tests with the bucket served over loopback http
  (reuse the shape of `test_catalogue.py`'s `http_bucket` fixture, adapted for `_run`):
  - an item whose receipt href is an absolute `file://` URL to a real local receipt file
    that would otherwise read `same` is `inconsistent`, its note says why, the run goes on
    for the other items, and the local file is never opened (asserted by its verdict
    not being `same`/`rebuilt`, plus a monkeypatched `_read_url` that records URLs
    and finds no `file:` URL)
  - a collection link to a `file://` item in an http-served collection refuses the
    run in `all` (nothing upserted, `r.writes == 0`), `verify` and `drift`, naming the href
  - the existing file:// bucket tests stay green (file from file is allowed)
- [x] Mutation check: each test fails with the guard removed at its call site.

## Phase 2: The guard

- [x] `src/stacs/catalogue.py`: add `resolve_href(base, href)`, which does `urljoin`
  and raises `ValueError` when `urlsplit(result).scheme` is outside the base's family. Add a
  docstring with doctest examples (fake hosts, `example.invalid`).
- [x] `src/stacs/register.py:561`: resolve item links through it, and turn a
  `ValueError` into a `RegisterError` naming the item and href.
- [x] `src/stacs/register.py:860`: resolve the receipt href through it. The existing
  `except ValueError` stays, with its message reworded so it covers both "not a URL" and
  "leaves the scheme the item is served over". The existing non-URL test's `"not a URL"`
  assertion stays true.
- [x] Update the comment at `catalogue.py:113` to say a `file://` URL is reached only from
  a `file://` base.

## Phase 3: Docs and release notes

- [x] `NEWS.md` `## Unreleased`: a **Behaviour change** entry (a `file://` item link or
  receipt href under an http(s) collection is now refused; it is a minor bump per
  CLAUDE.md "Versioning").
- [x] Check whether the README's verify/receipt prose says how hrefs resolve; add one
  sentence only if it describes resolution (keep the section markers intact).
- [x] `uv run pytest` green, and `uv run mkdocs build --strict` (no `-q`) if the README
  changed.

## Validation

- [x] Tests pass (`uv run pytest`)
- [x] `/code-check` clean (once over the branch with `/code-check branch`)
- [x] PWF checkboxes match landed work
- [ ] `/planning-archive` on completion

How each change is proved:
- the guard: unit tests per scheme case, plus a mutation run with `resolve_href`
  replaced by bare `urljoin` at each call site, which must turn the run-level tests red
- no local read: a recorded-URL assertion, not just the verdict
- no write: `r.writes == 0` and no loads on the refused-item-link `all` run

