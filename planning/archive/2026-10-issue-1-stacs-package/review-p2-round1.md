# Review — phase 2, round 1 (RFC 8785 body_digest)

## Findings

- **[severity: fragile]** src/stacs/verify.py:289 — a lone-surrogate object KEY escapes
  as a bare `UnicodeEncodeError`, not `DigestError`, and the message does not name the
  item. `rfc8785` sorts keys with `kv[0].encode("utf-16be")` (`_impl.py`, `dump`), which
  raises `UnicodeEncodeError` before its own `_serialize_str` would turn the surrogate
  into a `CanonicalizationError`. `canonical_json` catches only
  `(DigestError, rfc8785.CanonicalizationError)`, so the error leaks out as
  `'utf-16-be' codec can't encode character '\ud800' ... surrogates not allowed`.
  `json.loads` accepts `{"\ud800": 1}`. Reproduced:
  `body_digest(json.loads('{"id": "item-7", "properties": {"\\ud800": 1}}'))` raises
  `UnicodeEncodeError`. Nothing compares wrongly here: it is still a `ValueError`, it still
  raises, and no caller catches either type. What breaks is the contract
  `DigestError`'s docstring states ("a string that is not valid Unicode... Raised with the
  item's id"). Through `published_digests` or `bodies_registered` over a 100k-item
  catalogue, the run aborts and gives no id to look up. The test that pins the
  surrogate case only puts it in a VALUE (`chr(0xD800)`), and a value goes through the
  path that is handled. Fix, proven in a temp copy: add `UnicodeError` to the `except`
  tuple. Added test `{"\ud800": 1}`: red against the staged code, green with the fix,
  and the suite is otherwise 115 passed.

## Checked and clean

- **JCS number formatting against an ES reference.** `rfc8785.dumps(d)` was compared with
  V8's `JSON.stringify(JSON.parse(repr(d)))` over 303,066 doubles: 300k random bit
  patterns, values 1.0/1.5/2.5/5/9.999999999999999 × 10^-330..10^309, and the named
  edges (0.1+0.2, 1e-7, 1e-6, 5e-324, 1e20, 1e21, 1e22, 1e23, 2^53±1, max/min normal,
  1.5e300, -0.0). The output was byte-identical for every one. Every output also
  re-parses to the same double.
- **Published integral float vs served integer.** For every integral double in that set,
  `canonical_json({"n": d})` was compared with the served forms `int(d)` (exact value)
  and `int(Decimal(repr(d)))` (shortest digits zero-padded): 0 mismatches. The
  `_SAFE_INT` bound equals the library's `_INT_MIN`/`_INT_MAX` (±(2^53−1)), so no int
  falls between the conversion and the library's refusal.
- **A false "different" for served non-integral numbers.** JCS output depends only on the
  double that `json.loads` produced, so two texts disagree only if pgstac serves text
  that parses to a different double. The old `json.dumps` form was exposed to that in
  exactly the same way, so the diff adds no new exposure. (pgstac's numeric→jsonb keeps
  the published digits, and any correctly rounded longer form parses back to the same
  double.)
- **`type(x) is int`.** `json.loads` and `requests`' `.json()` produce only `int`, `bool`,
  `float`, `str`, `None`, `list` and `dict`. Excluding `bool` is harmless, because `True` and
  `False` lie inside the safe range anyway.
- **DigestError and callers.** `body_digest` is called in `catalogue.published_digests`
  and in `verify.bodies_registered`, `bodies_serving` and `collection_state`, and none
  of them wraps it in a `try`. The old `json.dumps` (`allow_nan=True`, ASCII-escaped
  surrogates, arbitrary ints) never raised, so no handler was catching a different
  exception before. `fetch_bodies`' `except ValueError` wraps only `json.loads` and
  never calls the digest.
- **The RFC sample test.** It encodes RFC 8785 §3.2.3 faithfully. The input string,
  decoded from the RFC's `"€$\u000F\u000aA'B"\\\\"\/"`, matches
  the `chr()` construction, and the expected output
  `"€$\u000f\nA'B\"\\\\\"/"` matches `want` (`\"`, `\\`, `\\`, `\"`). The numbers and the
  key order also match.
- The `uv.lock` entry is 0.1.4 with sdist and wheel hashes, and it matches the version
  installed in the venv.
