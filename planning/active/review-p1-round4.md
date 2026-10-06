# Code-check review: phase 1, round 4 (the round-3 fixes, and the mechanism behind them)

Method: copied `src/` and `tests/` to a scratch dir and ran everything against the copy
(`PYTHONPATH=<copy>/src`; `stacs.__file__` confirmed to resolve to the copy). The repo was
not modified apart from this file. Baseline: 88 passed. The one failure,
`test_version_matches_pyproject`, comes from the copy having no `pyproject.toml`.

## Mutation table over the round-3 fixes

Each fix was reverted on its own in a fresh copy.

| reverted fix | result |
|---|---|
| `fetch_bodies`: `out.unlink` before the first attempt | killed (`test_a_failed_refetch_does_not_leave_the_previous_runs_body`) |
| `fetch_bodies`: `part.unlink` in `except` | killed (`test_a_failure_after_the_part_file_is_written_leaves_nothing`) |
| `published_digests`: `read_bytes` changed back to `read_text` | killed (BOM test) |
| `bodies_serving`: raise on a `next` link | killed (`..._refuses_a_server_that_caps_the_limit`) |
| `_search_pages`: `features` must be a list | killed (2 paging params) |
| `ids_registered`: raise on a repeated id | killed |
| `collection_state`: the `/collections` probe on a 404 (removed, or `raise_for_status` dropped) | killed (both) |
| `_post`: `raise_for_status` | killed |
| `bodies_serving`: `features` must be a list | **SURVIVED.** The guard is present, but no test reaches it (see Mechanism) |

## Findings

- **[severity: bug]** `src/stacs/catalogue.py:104-109` and `:151-153`. **The stale-body fix is scoped to the URLs
  of one `fetch_bodies` call, but `published_digests` still decides "fetched" from the fact that a file exists.**
  The defect is the same one, a single axis over. The fix guarantees that a URL passed to *this* call has either
  this run's body or no file. It guarantees nothing about a URL that was left out of the call. Reproduced in the
  scratch copy:
  1. Run 1 fetches `a` and `b` into `items/`.
  2. The publisher rebuilds both.
  3. Run 2 fetches only `a` (a subset, such as the ids being registered) into the same `items/`. It returns `[]`
     (no failures).
  4. `published_digests([a, b], items/)` returns **b's run-1 digest**: `== stale rev1: True`,
     `== current rev2: False`.

  Nothing fails and nothing is printed, and `content_diff` reports `b` as **unchanged**. That is a false IN SYNC,
  which is exactly what CLAUDE.md forbids ("an unread body is an error, never 'unchanged'"). The docstring
  promise "every way a published digest could be absent raises -- a body not fetched" is still false for "not
  fetched by this run".

  The source was safe only because its caller made a fresh `mktemp -d` for every run
  (`stac_dem_bc/scripts/catalogue_register.sh:197`). That caller was not ported, and both functions are now
  public API. The decision needs to move to something `published_digests` can check. Either:
  - `fetch_bodies` records what it fetched (return it, or write a run manifest) and `published_digests` takes
    that record, not the directory listing; or
  - `fetch_bodies` refuses an `out_dir` that already holds `*.json` it was not asked to fetch.

- **[severity: fragile]** `src/stacs/catalogue.py:53-58` (`collection_item_links`). **A collection with no `rel:
  item` links returns `[]` without error, and every comparison then passes vacuously.** Reproduced for:
  - a collection whose items sit behind `rel: child` sub-catalogues (a common STAC layout for large
    catalogues);
  - a catalog file passed by mistake;
  - a file with no `links` key at all.

  In each case `ids_diff([], [])` gives `([], [])` and `content_diff({}, {})` gives `([], [], [])` against a
  collection that was never registered. That is the "loop over nothing exits 0" shape. Once the register path is
  ported it will be worse, because the register path and the verifier will read the same empty list, so they
  agree by construction ("verification that reads its own output"). With child links and some items linked
  directly, it is a **silent subset**: items behind child catalogues are neither registered nor reported. The
  accepted unsupported cases (relative hrefs, other encoders) fail loudly; this one does not. Raise on zero item
  links, and on any `rel: child` link, so that "unsupported" is loud here too.

- **[severity: fragile]** `src/stacs/catalogue.py:53-58` vs `src/stacs/verify.py:105-110`. **The repeated-id
  guard landed in three of the four enumerators, but not in the published-side producer that the id-only path
  reads.** `ids_registered`, `bodies_registered` and `published_digests` all raise on a repeated id.
  `collection_item_links` does not, and `ids_diff` collapses its input through `set()`.

  `_href_to_id` keeps only the basename, so `https://…/2018/x.json` and `https://…/2019/x.json` both become id
  `x`. Reproduced: `collection_item_links` returns `[('x', …/2018/x.json), ('x', …/2019/x.json)]`, and
  `ids_diff(that, ['x'])` gives `([], [])`. The catalogue publishes two bodies under one id, and the API can hold
  only one of them (and an upsert of the second will overwrite the first). The content path raises; the id-only
  path reports in sync. Raise on a repeated id inside `collection_item_links`, so that both paths inherit the
  guard.

- **[severity: fragile, low]** `tests/test_no_deployment_defaults.py:292-293`. **The fix replaced exact names with
  a token pattern, but the tokens are still a closed literal set.** Measured:
  - It misses `dsn`, `pg_dsn`, `conninfo`, `pghost`, `hostname`, `endpoint`, `uri`, `server`, `conn`, `root`,
    `href` and `apiurl`.
  - It catches `pg_host`, `database_url` and `stac_api`.

  The next commit (the pgstac register path) will take a database connection, and `dsn`/`conninfo` is the
  psycopg spelling. A default there gets past the structural check, and the textual check catches only the
  literal hosts it lists. The structural check also sees only module-level functions, not methods or argparse
  `default=`, which round 2 already noted. Nothing violates this today. The pattern needs `dsn|conninfo|
  endpoint|uri|server|hostname` (or no trailing `(_|$)` on `host`) before that commit lands.

## Mechanism

**A negative fact (not served / missing / no more pages / unchanged / nothing published) is inferred from *not
seeing* something, on a channel where a failed, partial, stale or out-of-scope read produces the same
observation.** Each original finding read absence as an answer without an independent signal that the read which
would have shown the thing had completed for *this run* and *this scope*:
- the stale body: a file exists, read as "this run fetched it";
- the ignored `next`: absent from the page, read as "not served";
- no `features`: read as "no more pages";
- a 404 from the wrong prefix: read as "not registered";
- locale decoding: a different reader of the same bytes.

A secondary mechanism made it recur: **the guard is attached to one caller, not to the shared producer**, so the
sibling callers drift. The pairs are `ids_registered`/`bodies_registered`, `_search_pages`/`bodies_serving`,
`fetch_bodies` (bytes)/`published_digests` (text), and now `published_digests`/`collection_item_links`.

Every place in the two modules this reaches:

| site | negative fact inferred | status |
|---|---|---|
| `verify._post` | HTTP error, read as a page | **guarded** (`raise_for_status`; non-JSON 200 is a `RequestException` under `requests>=2.31`) |
| `_search_pages` `features` | missing, read as an empty last page | **guarded**, tested |
| `_search_pages` `next` without a token / repeated token | read as the end | **guarded**, tested |
| `_search_pages` `links` key absent | read as "no next", so the enumeration ends | **unguarded** (`page.get("links", [])`). Low: a conformant STAC API always sends links. Mid-run it would hide orphans in unread pages |
| `ids_registered` repeated id | collapsed, which can hide a skipped item | **guarded**, tested |
| `bodies_registered` repeated id | collapsed by dict | **guarded**, tested |
| `bodies_serving` `next` link | ids past a cap read as "not served" | **guarded**, tested. Only when the server emits `next`. A server that crops silently without a link cannot be detected by any check here |
| `bodies_serving` `features` missing | read as "nothing served" | **guarded, untested.** The mutation survives |
| `bodies_serving` repeated id in one response | collapsed by dict | unguarded. Unreachable: one page, primary key, scoped to one collection |
| `ids_diff` | `set()` on both inputs | correct for its inputs. Duplicate-free only where the producer guards it: registered side guarded, **published side not** (finding 3) |
| `content_diff` empty/None digest | read as "equal" | **guarded**, tested |
| `body_digest` non-object | hashed | **guarded**, tested |
| `collection_state` 404 | read as "missing" | **guarded by a proxy**: the 2xx status of `{api}/collections`, not its body. A 200 from a different API or a proxy still reads "missing". Fails toward a redundant, idempotent collection upsert, not toward "same" |
| `collection_state` other failures | read as "same" | **guarded**, tested |
| `collection_item_links` no item links / `child` links | read as "nothing published" | **unguarded** (finding 2) |
| `collection_item_links` repeated id | collapsed downstream by `ids_diff` | **unguarded** (finding 3) |
| `fetch_bodies` failed refetch of a URL in this call | old body read as current | **guarded**, tested |
| `fetch_bodies`/`published_digests` URL not in this call, same dir | old body read as current | **unguarded** (finding 1) |
| `published_digests` file absent / not JSON / not an object / wrong id / repeated id | various | **guarded**, tested |
| `fetch_bodies` vs `published_digests` parse predicate | one body, two readers | **guarded** (both parse bytes), tested |
| `collection_item_links`, `collection_state`, `read_hrefs` text decoding | — | `encoding="utf-8"`. A BOM'd local file raises loudly. Not silent |

The fixes themselves introduced no new defect. Two cases were checked explicitly and end either loud or correct:
- the `out.unlink` race when the same URL appears twice (two workers share one `.part`);
- an `out` path that is a directory.

What the fixes did not do is move the decision onto a fact that this run produced. Finding 1 is the same
predicate ("file exists") with a narrower hole. Findings 2 and 3 are places the original sweep never enumerated,
because they are on the published side rather than the API side.
