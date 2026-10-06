# Review — phase 2, round 3 (parser paths into body_digest)

## Clean

No case found where the published side (`json.loads(bytes)` in `catalogue.published_digests`,
or `json.load(text)` in `verify.collection_state`) and the served side (`requests`
`.json()` in `verify._post` and `collection_state`) give different Python objects for
the same JSON content and so produce a false "equal" or a permanent false "different".
Every case below was reproduced in a temp copy of `src/` (scratchpad `r3/probe.py`).
Postgres behaviour was checked in a throwaway `postgres:16` container.

## Enumerated and checked

| Difference | Published parse | Postgres jsonb / served parse | Digest |
|---|---|---|---|
| `1.0E2` vs `100` / `100.0` | float 100.0 | jsonb `100` -> int 100 | equal (JCS writes `100`) |
| `-0` | int 0 | `0` | equal |
| `-0.0` | float -0.0 | jsonb `0.0` -> 0.0 | equal (JCS writes `0`) |
| `1e-400` | 0.0 | jsonb keeps a 400-digit decimal -> 0.0 | equal |
| `0.30000000000000004441` (more digits than a double) | nearest double | jsonb keeps the digits; parse rounds to the same double | equal |
| `\/` vs `/` | `/` | jsonb stores `/` | equal |
| `é` vs a literal `é` | same str | same | equal |
| NFC `é` vs NFD `e`+U+0301 | distinct | Postgres `=` is false; rfc8785 does not normalise (emits `e\xcc\x81`) | different. That is correct, because they are different content and nothing normalises |
| duplicate key `{"k":1,"k":2}` | last wins (2) | Postgres keeps the last (`{"k": 2}`, measured); orjson (pypgstac's loader) also keeps the last | equal, and consistent |
| duplicate key, last is null | last wins -> None -> dropped by `_canonical` | `{"k": null}` -> `jsonb_strip_nulls` -> `{}` | equal |
| UTF-8 BOM, fetched body | `json.loads(bytes)` detects `utf-8-sig` | n/a | parses |
| UTF-8 BOM, `collection_state` file | `json.load` on a utf-8 text handle raises "Unexpected UTF-8 BOM" | n/a | raises, so no false result |
| `requests` encoding | n/a | `application/geo+json` has no charset, so `guess_json_utf` gives utf-8; `application/json` gives utf-8; an explicit `charset=utf-8` gives utf-8 | equal under all three |
| `simplejson` installed (requests switches to it) | n/a | measured: dupes last-wins, `1.0E2` gives 100.0, `-0` gives 0, `1e400` gives inf (accepted) | same objects as `json` |
| lone surrogate `\ud800` | accepted, then `DigestError` | Postgres refuses it ("low surrogate must follow a high surrogate"), so it can never be served | raises |
| `\u0000` | accepted | Postgres refuses it ("cannot be converted to text") | a registration failure, not a verify comparison |

Not parser-level and not reproduced, so not reported: whether PostGIS's
`ST_AsGeoJSON` precision on the served geometry can shorten coordinates. The `_canonical`
docstring states the geometry round trip was measured on a live catalogue.
