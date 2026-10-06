# Code-check review: phase 1, round 3 (staged diff, runtime behaviour against a real API)

## Findings

- **[severity: bug]** `src/stacs/catalogue.py:103-121` (`fetch_bodies.one`) with `catalogue.py:147-158`
  (`published_digests`): **a failed refetch leaves the previous run's body in place, and `published_digests`
  digests it as current.** On failure `one` removes only `.part`. An existing `<md5>.json` from an earlier run into
  the same `out_dir` is kept. `published_digests` checks `path.exists()` and nothing else, so the stale body is
  hashed. If the publisher changed the item and the API still serves the old one, `content_diff` compares old with
  old and reports the item **unchanged**. That is a false IN SYNC, and it breaks the repo rule that an unread body is
  an error, never "unchanged".
  Tested in a scratch dir with a `file://` bucket. Run 1 fetched `{"id":"a","v":1}`. The source then changed to
  `v:2` and was made unreadable. Run 2 returned the URL as failed, and `published_digests` still returned the `v:1`
  digest (`== old body: True; == new body: False`).
  *Inherited code, newly exposed.* `ast` shows it identical to the source, and the source was safe only because
  of its caller: `catalogue_register.sh:197` makes a fresh `mktemp -d` per run, and `:403-416` gates on the number
  of files on disk. That caller was not ported. Both functions are now public API, and their docstrings ("a
  failure never leaves a partial file behind"; "every way a published digest could be absent raises -- a body not
  fetched") read as covering this case when they do not. A reused `out_dir` also defeats the source's
  count-on-disk gate, because the stale files are counted.
  Fix: unlink `out` before the first attempt in `one`, or have `fetch_bodies` refuse a non-empty `out_dir`.

- **[severity: fragile]** `src/stacs/verify.py:174-178` (`bodies_serving`): **a `next` link in the response is
  ignored, so a truncated answer reads as ids "not served".** `search_body` asks for `limit=len(batch)`. Upstream
  stac-fastapi (`stac_fastapi/types/search.py`, `crop()`, `Limit = Annotated[PositiveInt,
  AfterValidator(crop)]`) silently lowers any limit above 10,000 to 10,000 and returns a `next` link.
  `bodies_serving(..., chunk=N)` with N > 10000, or any server with a lower cap, gets back a partial set. The
  missing ids then look like ids the API does not serve, which is false drift (re-registration, or a FAIL from a
  verify-serving step). This is the default-page-size trap that `search_body`'s own docstring describes, one
  parameter over. The default `chunk=500` is safe. Tested with a fake session that caps at 2: `['a','b']` of
  `a,b,c`, no error.
  *Inherited.* Fix: raise if a page carries a `rel: next` link, or follow it through `_search_pages`.

- **[severity: fragile]** `src/stacs/verify.py:66-73` (`_search_pages`): **a 200 response with no `features` key
  ends paging as a normal, complete enumeration.** `page.get("features", [])` and `page.get("links", [])` turn a
  well-formed but non-STAC 200 (a gateway or proxy JSON page) into "empty page, no next link", the one exit the
  docstring calls normal. That contradicts "every way out other than 'no next link' raises". Tested:
  `ids_registered` on `{"type":"FeatureCollection"}` returns `[]`. Usually this fails toward drift (every
  published id reads as missing). But if it happens mid-enumeration it also hides orphans that sit in unread
  pages. *Inherited.* Fix: require `"features"` to be present and be a list.

- **[severity: fragile]** `src/stacs/verify.py:97` (`ids_registered`) vs `:118-122` (`bodies_registered`): **the
  two enumerations over the same paging harness guard overlap differently.** `bodies_registered` raises on a
  repeated id ("the enumeration overlapped"). `ids_registered` returns the duplicate, and `ids_diff` then silently
  collapses it through `set()`. Tested: overlapping pages give `['a','b','b']` and no error. An overlap means
  keyset paging ran while items moved, for example during a concurrent upsert. The same movement can also *skip*
  an item, which hides an orphan and so gives a false sync in the orphaned direction. One enumerator refuses that
  state and the other accepts it. *Inherited.*

- **[severity: fragile, low]** `src/stacs/verify.py:276-277` (`collection_state`): **any 404 is "missing".**
  Suppose `api` is wrong by a path prefix, such as the API mounted under `/stac` behind a proxy. The router's 404
  then reads as "collection never registered", while the same wrong `api` makes `_post` raise. That is false
  drift, not a false sync. stac-fastapi's real not-found body is `{"code":"NotFoundError",...}`, which could
  discriminate the two cases. *Inherited.*

- **[severity: fragile, low]** `src/stacs/catalogue.py:151` and `:51` (`published_digests`,
  `collection_item_links`), and `verify.py:268` (`collection_state`): `read_text()` and `open()` with no encoding
  use the locale. A raw UTF-8 body (not `\u`-escaped) decoded as anything else gives a different digest
  (permanent "changed") or different ids (permanently missing and orphaned at once). The fetch-side check parses
  **bytes** (`json.loads(data)`), so it accepts a UTF-8 BOM. The digest side then refuses the same file
  ("Unexpected UTF-8 BOM"). That is loud, but it is two predicates for one body. CI is ubuntu-only, so this is
  latent. *Inherited.* Fix: `json.loads(path.read_bytes())` and `open(..., encoding="utf-8")`.

## Checked and found sound

- **Keyset paging.** An empty first page with no next link returns `[]` correctly, and stac-fastapi returns 200
  with no features for an unknown collection. A next link with an `href` and no body (GET-style `?token=`) raises
  "no token", so it is loud. The token is read only from the body, and a token in the href is never followed.
  stac-fastapi-pgstac's POST next body is `{**request.postbody, "token": "next:..."}`, so the merge on `:82`
  matches what the server would replace it with. A repeated token raises. Retries are safe because POST /search
  is read-only and the token is a keyset cursor.
- **`PAGE_SIZE = 10000`** is exactly at stac-fastapi's crop, so `_search_pages` would follow paging even if
  cropped.
- **Retries.** `_post` and `collection_state` also retry 4xx responses (`raise_for_status` raises
  `HTTPError`), which wastes about 6 s and still raises at the end. It never fails toward pass. A 200 with a
  non-JSON body raises `requests.JSONDecodeError`, a `RequestException` under `requests>=2.27`, so it is retried.
- **Percent-encoding.** `quote(collection_id)` encodes `%`, `?`, `#` and space. `/` stays literal, but uvicorn
  decodes `%2F` before routing anyway, so a slash in an id cannot be served by path in either form. `/search`
  carries the id in JSON, so it needs no encoding.
- **Threads.** There is one `requests.Session` per worker thread, via `threading.local`, and no Session is shared
  across threads. Sessions are released when the pool's threads exit. No descriptor growth was found across
  repeated calls. `ex.map` submits all futures up front, which costs memory but is bounded (102k measured in the
  source). Ctrl-C cancels the queued work.
- **Digest.** `links` is excluded. Null object members are dropped and integral floats become integers, on both
  sides. No path was found where two different bodies get the same digest, apart from the intended null and
  int/float equivalences.

## Not reviewed in depth

The shell-specific sections of the checklist. The diff contains no shell.
