# Review — phase 2, round 2 (RFC 8785 body_digest, UnicodeError fix + mutation table)

## Findings

- **[severity: fragile]** src/stacs/verify.py:268 (`not -_SAFE_INT <= x <= _SAFE_INT`) and
  tests/test_verify.py (the RFC 8785 section) — the **lower bound** of the int-to-float
  guard is untested. The mutant `not x <= _SAFE_INT`, which drops the negative side,
  passes the whole suite (116 passed). What it would break: a published negative
  integral float of magnitude 2^53 or more (for example `-1e16`) that pgstac serves back
  as the integer `-10000000000000000`. The served side would then raise `DigestError`
  ("exceeds safe integer domain") and abort the verify run. That is the same round-trip
  the positive cases in `test_an_integral_float_and_its_served_integer_digest_equal`
  pin. With the guard as staged it works: `body_digest({"n": -1e16}) ==
  body_digest({"n": -10**16})` is True. Only the pin is missing. Reproduced in a scratch
  copy: under the mutant, `body_digest({"id": "x", "n": -10**16})` raises
  `DigestError: ... -10000000000000000 exceeds safe integer domain for JSON floats`. The
  smallest pin that kills it is one more parametrize row, `(-1e16, -10000000000000000)`
  (or `(-1.5e300, int(-1.5e300))`).

## Mutation table (scratch copy, full suite per mutant)

| mutant | result |
|---|---|
| M1 `return float(x)` → `return x` | killed (1e16, 1.5e300, 2^53 tests) |
| M2 `type(x) is int` → `isinstance(x, int)` | survived — **equivalent**: bool is inside ±(2^53−1), so the branch never fires for it |
| M3 drop lower bound | **survived — real gap, see Findings** |
| M4 drop upper bound | killed |
| M5 `_SAFE_INT = 2**53` | killed (2^53 decision test) |
| M6 `_SAFE_INT = 2**53 - 2` | survived — **equivalent**: float(2^53−1) is exact and JCS writes it identically |
| M7 convert every int to float | survived — **equivalent**: 200k random safe ints plus edge cases, `rfc8785.dumps(float(i)) == rfc8785.dumps(i)` with 0 mismatches |
| M8 remove the OverflowError branch | killed (10**400) |
| M9 except tuple without DigestError | killed (10**400 message lacks the id) |
| M10 except tuple without CanonicalizationError | killed (nan/inf/-inf/value surrogate) |
| M11 except tuple without UnicodeError | killed (key-surrogate test) |
| M12 keep `links` | killed |
| M13 keep null members | killed |
| M14 also strip nulls inside arrays | killed |
| M15 remove the non-dict TypeError | killed |
| M16 revert to `json.dumps(sort_keys=True)` | killed (UTF-16 order, nan, -0.0, -126.0) |
| M17 message without the item id | killed |
| M18 except `(ValueError,)` | survived — **equivalent** for reachable input: every caught type is already a ValueError subclass |
| M19 re-add the old float→int rule | killed (1e16, 1.5e300, RFC sample) |

## Checked and clean (focus 1: the UnicodeError catch and other escape paths)

- **The UnicodeError catch masks nothing.** Inside `rfc8785.dumps`, the only
  `UnicodeError` source that is not already converted is the key sort
  (`kv[0].encode("utf-16be")`). `_serialize_str` converts its own
  `UnicodeEncodeError` to `CanonicalizationError`, and int/float formatting is ASCII.
  `_canonical` raises no UnicodeError. The `try` covers only those two calls, so there is
  nothing else to mask. Reversed surrogate pairs from `json.loads`
  (`"\ude00\ud83d"`) in a key are now `DigestError` with the id. A surrogate in `id`
  itself is also `DigestError`, and its `!r` message renders.
- **Non-str keys** (int, and int mixed with str): rfc8785 turns the `AttributeError` into
  `CanonicalizationError`, so these surface as `DigestError` with the id. They are not
  reachable from `json.loads` in any case.
- **Huge negative int** (`-10**400`): `DigestError` with the id, as for positive.
- **Ints over 4300 digits**: `_canonical`'s message calls `str(abs(x))`, which would raise
  a bare `ValueError` (int max str digits) inside the handler. This is unreachable:
  `json.loads` refuses the same literal with the same limit at parse time, and both
  callers parse with `json.loads`, where `catalogue.fetch_bodies` already names the
  failure. Not a finding.
- **Deep nesting → RecursionError**: this escapes unnamed, but it is not new. The staged
  code digests up to depth 993, HEAD up to 995, and `json.loads` accepts up to 9997. Both
  versions recurse in Python (`_canonical`), and a STAC body is nowhere near this depth.
  Not a regression, so not a finding.
- **Silent wrong digests**: none found. A negative large float and its served int digest
  equal. Safe ints are untouched. `bool` stays `true`/`false`. The null-stripping and
  `links` removal behave as documented. Round 1's V8 comparison covers number text.
- The repo working tree was not modified. All mutation work ran in
  `scratchpad/mut/`, and `src/stacs/verify.py` still matches the index (`cmp`).
