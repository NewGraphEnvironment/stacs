# Code-check review — phase 1, round 1 (staged diff)

## Clean

No issues found.

## What was checked

- **Port fidelity, mechanically.** Parsed `stac_dem_bc/scripts/register_manifest.py`, `src/stacs/verify.py` and
  `src/stacs/catalogue.py` with `ast`, removed docstrings, and compared the `ast.unparse` of every ported function
  and module constant. 19 of 23 are byte-identical: `RETRIES`, `PAGE_SIZE`, `_post`, `_search_pages`, `search_body`,
  `ids_diff`, `_canonical`, `body_digest`, `content_diff`, `_href_to_id`, `collection_item_links`, `fetch_key`,
  `_local`, `_read_url`, `fetch_bodies`, `published_digests`, `read_hrefs`. The other 4 (`ids_registered`,
  `bodies_registered`, `bodies_serving`, `collection_state`) differ only in the signature: `api: str = API_DEFAULT`
  became `api: str`. `api` keeps its position, so the source CLI's positional calls
  (`ids_registered(args.collection_id, args.api)` etc.) still bind the same way. Not ported, as intended:
  `API_DEFAULT`, `_S3_VIRTUAL`, `_S3_PATH`, `item_ids_from_urls`, `ndjson_write`, `s3_bucket_name`, `audit_items`, `main`.
- **Tests.** Every source test of a ported function is present in `tests/test_verify.py` / `tests/test_catalogue.py`.
  Fixtures moved to `example.invalid`. `uv run pytest -q`: 65 passed. `uv lock --check`: consistent, and `requests`
  (2.34.2) is locked. `requests>=2.31` also guarantees that `resp.json()`'s `JSONDecodeError` is a
  `RequestException` (true from 2.27), so `_post` and `collection_state` still retry a garbled body instead of raising
  on the first one.
- **The no-deployment-defaults guard fires.** I tested this in a scratch copy; the repo was not touched. I gave
  `collection_state` the default `api="https://images.a11s.one"`, and both
  `test_no_deployment_parameter_has_a_default` and `test_no_source_file_names_a_deployment` went red, with the
  copy's `verify.py` named in the output. `test_the_structural_check_sees_modules` covers the module walk finding
  nothing.
- **Repo rules.** No deployment default remains: a grep of `src/` for `a11s`, `images.`, `geopro`, `amazonaws`,
  `stac_dem` and `newgraph` returns nothing. Verification compares id sets and digests, never counts. An absent
  digest raises (`content_diff`, `published_digests`, `body_digest(None)`). No secrets are handled in this diff.

## Notes for later commits (not defects in this diff)

- `_href_to_id`'s docstring says that `published_digests` **and the register path** refuse a body whose `id` differs
  from its link. stacs has no register path yet: in the source that check lives in the `fetched-paths` CLI branch.
  The sentence is accurate only if the later port keeps that check.
- `KNOWN_DEPLOYMENT_STRINGS` contains `"amazonaws.com"`. If `s3_bucket_name` is ported with its source comment
  (`# Virtual-hosted (\`<bucket>.s3[...].amazonaws.com\`)`, register_manifest.py:540), the textual test will fail.
  That is the guard working, but the commit should expect it.
- Behaviour unchanged from the source, but worth knowing for a public tool:
  - `collection_item_links` returns hrefs verbatim. A catalogue with relative item hrefs (`./x.json`, the STAC
    norm for self-contained catalogues) would make every fetch fail (`MissingSchema`). That failure is loud,
    not silent.
  - `_href_to_id` inverts only one encoder. A catalogue encoded another way gives wrong ids, which
    `published_digests` refuses loudly.
