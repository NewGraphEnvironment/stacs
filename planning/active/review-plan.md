# Plan review — #19 (Plan agent, spawned 2026-11-16T14:20:34Z)

Reviewed after Phases 1–2 had landed (00f62da, a576faf); probes were in-memory
`python -I -c` calls on urljoin/urlsplit/requests. Verdict: no open blocker; no bypass from
an http(s) base to a local read.

## Q1. Other places a body or API href reaches a fetch
- register.py item links → fetch_bodies: guarded.
- register.py receipt hrefs → fetch_bodies: guarded.
- register.py `_read_url(coll_url)`: from config `bucket_url`, out of scope.
- verify.py:532 `/collections` `next` href → requests only (no `file:` adapter); configured
  API, different trust boundary. Reusing `resolve_href` there would need it moved
  (catalogue imports verify → cycle).
- requests follows 3xx after the guard; harmless while requests has no `file:` adapter
  (`get_adapter("file:///...")` raises InvalidSchema).
- validate.py:296 `pystac.validation.validate_dict` fetches each `stac_extensions` URI; a
  scheme-less one is a plain local `open()`. Reached only from `stacs validate` on
  operator-given paths. Same class, outside #19: suggested follow-up issue.
- Asset hrefs: normalised, never fetched.

## Q2. Bypass
None. The only local-read sink is `_read_url`'s `startswith("file://")`; any such string has
`urlsplit` scheme `file`, so the guard refuses a strict superset. Probed `FILE:///x`,
`file:/x`, `file:x`, ` file:///x`, `fi\tle:///x`, `\x00file:///x`, `file\n:///x` → all scheme
`file`, refused; `%66ile:///x` → relative https path, harmless; `//evil/x` → https.
From a file base `//host/x` → `file://host/x` (allowed; urllib does a DNS lookup for a
non-local host) — operator-owned bucket only. Do not make `_read_url` dispatch on
`urlsplit`: that would widen the sink.

## Q3. Harness
Done the least invasive way: `http_bucket` serves `env/bucket` on loopback; `_relative_links`.

## Blocker
- None open. The `drift` param ran with `transport=None` and failed for the harness reason;
  already fixed and recorded.

## Gap
1. task_plan.md Context's claim "urljoin lowercases the scheme" is false (findings has the
   correction) — fix in the plan.
2. `ids` mode not in the item-link test parametrisation, though NEWS names it.
3. `dryrun` refusal not tested (guard runs before the dryrun exit; expect rc 1, `scheme`,
   `r.probes == 0`).

## Assumption
1. Internal http hosts reachable (owner accepted); a ReceiptError message could quote
   internal-body fragments into logs. Suggest recording the accepted risk.
2. file-from-file reaches any local path: fine while a file bucket is operator-owned.
3. Safety leans on requests having no `file:` adapter (redirects, verify.py:532): say so in
   `_read_url`'s comment.

## Scope
- `stacs validate` via pystac: file separately.
- verify.py:532: correctly left out.

## Acceptance
- README refusal list has a ragged line ("a body that could not be fetched," alone): reflow.
- NEWS Behaviour change → minor; check `/gh-pr-merge`'s BUMP line.
- `test_an_http_catalogue_with_relative_links_still_registers` runs only `verify`, no
  receipts, yet its docstring says "items and receipts": fix name/docstring.
- Keep the record that the mutation re-run followed the `drift` fix (progress.md has it).
