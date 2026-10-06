# Review: Phase 3 staged diff, round 2 (the round-1 fixes)

Reviewed: `git diff --cached` at fbe1496 + staged. Every claim was reproduced in a temp copy
(scratchpad `r2/`, src + tests copied; repo `validate.py` cmp'd intact afterwards). Baseline there:
163 passed, 1 deselected. Network probes used `example.invalid` and TEST-NET-1 `192.0.2.1` only.

## Findings

- **[bug] src/stacs/validate.py:158-161 — `validate_items` validates pystac's re-serialisation, not the file.**
  `pystac.Item.from_dict(doc).validate()` validates `item.to_dict()`, which is not the body on disk.
  pystac 1.15.2 parses and re-emits datetimes, and it migrates older versions to 1.1.0 on read.
  Reproduced, with each body compared to `pystac.validation.validate_dict(raw)`:
  - `"datetime": "2020-01-01T00:00:00"` (naive): `validate_items` says **PASS**, raw says `STACValidationError`. `to_dict()` re-emits it as `...Z`.
  - `"datetime": "2020-01-01"` (date only): `validate_items` says **PASS**.
  - `"stac_version": "1.0.0"`: `validate_items` says **PASS** offline, against the bundled 1.1.0 schema after migration. The 1.0.0 body is what gets registered, and it was never validated.

  So an item the STAC schema rejects is reported valid, and a naive datetime then lands in pgstac
  in the server's timezone. Round 1's "checked" entry ("naive datetime ... failed through
  validate_items exactly as through validate_dict") is wrong; the probe is in `r2/probe/p2.py`/`p3.py`.
  Fix: check `isinstance(doc, dict)`, then call `pystac.validation.validate_dict(doc)` on the raw dict.
  That still validates the declared `stac_extensions`, and a 1.0.0 body then needs its real 1.0.0
  schema (an unreachable schema stays a failure, as the docstring promises).

- **[bug] src/stacs/validate.py:147-167 — `validate_items` returns the success value for zero items.**
  `[]` means "all valid". Reproduced: `validate_items([]) == []`, and so are `validate_items(["\n", ""])`
  and a generator already consumed by `audit_items`. `audit_items` enforces "zero items is never a
  pass" (line 123); `validate_items` is the sibling entry point and does not. A caller writing
  `if not validate_items(paths)` gets a pass on nothing. Fix: count the items checked, and raise
  (or return a failure entry) when that count is 0.

- **[fragile] src/stacs/validate.py:58-65, 95 (against the comment at 86-88) — the "nothing refuses" fix covers `require_asset` but not `forbid_assets`.**
  The comment says "Every way of passing 'nothing' refuses rather than disabling a check". Yet
  `forbid_assets` given as `""`, `","`, `[None]` or `[""]` parses to `[]`, and the retired-key check
  silently does not run. Reproduced: an item still carrying `image` gives `ok=True` for all four.
  `rules` says `forbid=-`, but `ok` is what the gate's consumer reads, which is round 1's own
  argument for `require_asset`. The origin protected this in the caller:
  `catalogue_register.sh:140` exits when `AUDIT_FORBID` is empty for its own catalogue. The library
  has no such caller, and Phase 4 plans `--forbid-asset` / `stacs.toml` values that can be empty.
  Fix: `None` means "no rule". Any other value that parses to no keys raises `ValueError`, matching
  `require_asset`.

- **[fragile, low] src/stacs/validate.py:111-121 — the asset VALUE is never checked, which is the round-1 assets hole one level down.**
  `{"dem": null}` and `{"dem": "s3://x"}` both satisfy `require_asset="dem"` (reproduced). The fix
  pinned the container's type and not its members' types. Neither body is a usable asset, and
  `audit` is the gate that `register` runs (`validate` is opt-in). The origin had the same hole.
  Fix: a required asset must be a dict with a string `href`; otherwise record it as missing or unreadable.

- **[fragile, low] src/stacs/validate.py:118 — `id` is not pinned.**
  An item with no `id`, `"id": ""` or `"id": 5` passes `audit_items` when `expect_ids` is not given
  (reproduced). A missing id appends `None` to `ids`, so an `expect_ids` that contains `None` passes
  it (reproduced). The planned body-by-href check in Phase 4 would catch a missing id at load, so
  this is low. It is the same unpinned-shape mechanism.

- **[fragile] tests/conftest.py:1-13, 36-56 — the guard still has in-process bypasses, and the docstring's "a lookup of any non-loopback name is refused" overclaims.**
  Probed:
  - UDP `sendto` and `sendmsg` to `192.0.2.1` are not guarded: they sent, with no error.
  - `sendto(b"x", ("example.invalid", 9))`, `socket.gethostbyname`, `socket.gethostbyname_ex` and
    `_socket.socket(...).connect` all reach the real resolver or stack. They came back as `gaierror`
    or `TimeoutError`, not `NetworkDisabled`.
  - Not probed but in the same family: `gethostbyaddr`, `getnameinfo` and `getfqdn`.

  Nothing in stacs uses these paths today. `requests`, `urllib3`, `socket.create_connection`,
  `asyncio.open_connection` (by IP and by name) and UDP `connect` are all guarded (probed), so the
  gap is latent. Fix: route `sendto` and `sendmsg` through `_check_address`, and wrap
  `gethostbyname`, `gethostbyname_ex`, `gethostbyaddr` and `getnameinfo` like `getaddrinfo`.
  Alternatively, narrow the docstring to the paths that are actually guarded.

- **[fragile, pre-existing] tests/test_no_deployment_defaults.py:39-48 (`_callables`) — the predicate was widened, but the walk still misses callable shapes.**
  `inspect.getmembers(cls, inspect.isfunction)` skips classmethods, because the class attribute
  access returns a bound method. A module-level `functools.partial` has the wrong `__module__`.
  Reproduced: a scratch `Client.from_env(cls, api="https://fake.example.invalid")` and
  `connect = functools.partial(_impl, bucket="fake-bucket")` were both invisible; `_callables`
  yielded only `Client.s` and `_impl`. Phase 4's config loading is the natural home for a
  `from_*` classmethod. Fix: walk `vars(cls)`, unwrap `classmethod` and `staticmethod` via
  `__func__`, and check a partial's `.keywords` against `DEPLOYMENT_PARAM`.

## Mechanism

This is **a guard that fails toward pass through Python's polymorphic operators.** `in`, `!=`,
truthiness and `set()` each return an answer for any input shape. An input whose type or emptiness
is not pinned therefore turns a check into "matches" or "nothing to check", and the result reads
`ok`. Round 1's three validate.py findings were all this: a str or list `assets` answering `in`; a
`None` or `""` collection id answering `!=`; and `""` collapsing `require_asset` to "no rule". The
fixes pinned exactly those three sites. Every other place in validate.py the mechanism reaches:

| site | input | outcome |
|---|---|---|
| `parse_asset_keys` / `forbid` (58-65, 95, 121) | `""`, `","`, `[None]`, `[""]` | **passes**: finding 3 |
| `key in assets`, value side (120) | `{"dem": null}` / `{"dem": "str"}` | **passes**: finding 4 |
| `doc.get("id")` (118) | missing, `""`, int | **passes** without `expect_ids`: finding 5 |
| `validate_items` return (167) | zero, blank-only or exhausted `paths` | **passes**: finding 2 |
| `doc.get("collection") != collection_id` (119) | non-str item `collection` | fails closed (probed `["new"]`) |
| `r.checked != expect` (134) | `True`, `2.0` | equals 1 and 2; benign |
| `set(expect_ids)` (138) | a str | becomes a set of chars, fails closed; a `None` member matches a missing id (finding 5) |
| `for path in paths` | a single str | iterates characters, each unreadable, fails closed |
| `assets is None` → `{}` (111) | `""` / `[]` | unreadable; but reverting to `or {}` keeps all 38 validate tests green, so falsy non-dict assets are unpinned by tests (low) |

Finding 1 has a second mechanism: **a proxy is not the property.** `Item.validate()` checks pystac's
model of the item, not the bytes that will be registered.

## Checked and not a problem

- **Raising on `require_asset=""` breaks no caller.** `catalogue_register.sh:149` adds
  `--require-asset` only when it is non-empty (`[ -n "$AUDIT_REQUIRE" ]`). A whitespace-only
  `STAC_REQUIRE_ASSET` used to fail every item in the origin, and now raises; both fail. There are
  no callers of `audit_items` in `src/` yet.
- **Mutation.** Removing each round-1 guard in validate.py (the assets type check, the
  collection_id check, the require_asset check) turns 3 tests red each.
- **`forbid_assets=[1]`** raises `AttributeError`, which is loud.
- **`pytest_unconfigure`** restores the three attributes to the originals captured at import.
  There is no `tests/__init__.py`, so the conftest is the single module `conftest`, and there is no
  double capture. Env vars are not restored, which is process-local and harmless.
- **`_is_a_value`** uses only identity and `isinstance` checks, plus `not default` restricted to
  builtin container types. A numpy array, or a default whose `__bool__` or `__len__` raises, cannot
  make it raise. Only a raising `default_factory` errors the dataclass test, and that error is loud.
  `dataclasses._HAS_DEFAULT_FACTORY` exists on 3.12.13. It is private, and its removal would surface
  as a loud `AttributeError`.
- **`NO_PROXY="*"`** is honoured by urllib (`proxy_bypass_environment`) and by requests (via that
  same fallback). The origin harness builds subprocess env explicitly and overrides `no_proxy`, so
  the session-wide `*` does not defeat its proxy-proofing when ported.
