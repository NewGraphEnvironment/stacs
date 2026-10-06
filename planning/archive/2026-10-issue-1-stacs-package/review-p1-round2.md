# Review p1 round 2: can the tests reach their failure modes?

Method: copied `src/` + `tests/` to a scratch dir and ran a 23-row mutation table against
the copy (`PYTHONPATH=<copy>/src .venv/bin/python -m pytest -p no:cacheprovider`, with
`test_version_matches_pyproject` deselected because it needs `pyproject.toml`, which the
copy does not have). Baseline 64 passed. A row "survives" when all 64 still pass. The repo
was not modified apart from this file.

| mutation | result |
|---|---|
| `_search_pages`: tokenless `next` link -> `return` | SURVIVED |
| `_search_pages`: repeated token -> `return` | SURVIVED |
| `ids_registered`: drop `collections` | SURVIVED |
| `ids_registered` / `bodies_registered`: drop `limit` | SURVIVED (paging still finishes, so this is speed, not correctness) |
| `bodies_serving`: unscoped body / `ids_only=True` / first chunk only | SURVIVED (all 3) |
| `collection_state`: always `"same"` / exhausted retries -> `"same"` | SURVIVED (both) |
| `_post`: drop `raise_for_status()` | SURVIVED |
| `fetch_bodies`: drop the `.part` unlink / write straight to `out` | SURVIVED (both) |
| `fetch_bodies`: no retry | SURVIVED |
| `fetch_bodies`: drop the JSON-object check | SURVIVED |
| `published_digests`: skip a non-object body | SURVIVED |
| a new `bucket=` / `collection=` default on a public function | SURVIVED |
| `_canonical` without null stripping | killed |
| `content_diff` checking only `None`, not `""` | killed |
| `_href_to_id` using `urllib.parse.unquote` | killed |
| `api=` default on `ids_registered` | killed |

All of the `body_digest`, `content_diff`, `search_body`, `ids_diff` and `_href_to_id`
tests can reach their failure modes. The mutation table shows the integral-float,
null-member, null-array-element, bool and links cases each fail when their rule is removed.

## Findings

- **[fragile]** tests/test_verify.py:319-324 (`ids_registered`, src/stacs/verify.py:92-96).
  If `"collections"` is removed from `ids_registered`'s body, every test still passes.
  `_PagingSession` ignores `collections`, and this test checks only `fields`. That is the
  unscoped-`/search` hazard named in CLAUDE.md, in the function whose output goes to
  `ids_diff`. With the mutation, `orphaned` fills with the ids of every other collection
  on the endpoint. The module docstring's claim 2 ("one with no `collections` answers
  about every collection") is pinned on the pure `search_body` and on `bodies_registered`
  (line 308), but not here.
  `bodies_serving` (verify.py:161-179) has no test at all. It can stop calling
  `search_body`, switch to id-only stubs (every digest would then read as "changed") or
  send only the first chunk (every id after 500 would read as "missing"), and each change
  survives.
  So the claim-2 tests pin the builder, not the two callers that send a `/search` body.

- **[fragile]** src/stacs/verify.py:74-80, reached by nothing in tests/test_verify.py:284-297.
  `_PagingSession` can only return well-formed tokens that move forward. It cannot return
  a `next` link without a token, or a token it has already returned. So both guards that
  turn a short enumeration into an error can be replaced with `return` and nothing fails.
  The `_search_pages` docstring says why that matters: a short enumeration reports every
  unenumerated item as missing and sends a drift run to re-register a catalogue that was
  fine. The gap was inherited: stac_dem_bc's tests/test_register_manifest.py has no such
  case either.

- **[fragile]** src/stacs/verify.py:35-47 and 261-287 have no test. `collection_state` can
  return `"same"` unconditionally, or return `"same"` once retries run out, and both
  survive. Its docstring claims "an unreachable API cannot read as 'same'". Dropping
  `raise_for_status()` from `_post` also survives. Without it, a 5xx with a JSON error
  body parses as a page with no `features` and no `next` link, so the enumeration ends
  "normally" and every published id reads as missing. That is an unread body treated as
  data. Both untested paths are inherited from the source.

- **[fragile]** tests/test_catalogue.py:134 and :145 `assert not list(out.glob("*.part"))`
  pass vacuously. Every failure the fixtures cause (a missing `file://` URL, or truncated
  JSON) happens in `_read_url`/`json.loads`, before `.part` is written. So no `.part` file
  ever exists to be left behind. Removing `part.unlink(...)`, or dropping the
  `.part`+`os.replace` scheme and writing straight to `out`, both survive. The "never
  leaves a partial file" claim in `fetch_bodies` is not reached.

- **[fragile]** src/stacs/catalogue.py:109-110 and :154: the "must be a JSON *object*"
  guards have no fixture that is valid JSON but not an object (`null`, `[]`, `"x"`).
  `test_fetch_bodies_refuses_a_body_that_is_not_json` (line 148) uses only truncated
  JSON, which `json.loads` rejects with or without the guard. Each guard survives removal
  alone, because the other one stops the bad body at run time. With both removed, a
  `null` body is skipped silently and its id drops out of the published map, so it reads
  as orphaned.

- **[fragile]** tests/test_no_deployment_defaults.py:17. `DEPLOYMENT_PARAMS` is an
  allowlist of exact names, so the structural guard fails toward pass for any other name.
  Adding `bucket='https://…'` or `collection='prod'` as a default to a public function
  survives, yet CLAUDE.md names "bucket and collection" as always-caller parameters. The
  guard also cannot see an argparse `default=` (the source's `--api default=API_DEFAULT`
  is the original form of this hazard), and the register-path commit will port a CLI. The
  textual list at :21 does not include the source's other real hosts,
  `dev-imagery-uav-bc` and `nrs.objectstore.gov.bc.ca`. None of this breaks today. It is
  scope that the next commit's code will fall outside of.

## Not findings

- `match="a"` at tests/test_catalogue.py:174 and :183 matches almost any message. Removing
  the explicit `exists()` check or the `try/except` survives, but only because the
  natural `FileNotFoundError`/`JSONDecodeError` still raises. The behaviour being pinned
  (an absent or unreadable body raises) holds either way.
- `fetch_bodies` retry is untested, and so is the missing `limit` in the paging bodies.
  The first is resilience. The second is speed: pagination still covers everything.
