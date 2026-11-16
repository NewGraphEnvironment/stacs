# Matching an asset href to a receipt part

**Verified:** 2026-11-16 on CPython 3.12.13 (`requires-python >= 3.11`) · **Issues:** #17
(found), #19 (spawned) · **Produced by:** probes run during #17's code review, recorded in
`planning/archive/2026-11-issue-17-item-receipt-checks/`, and the RFC 3986 reference sweeps
in `tests/test_receipt.py` (`_rfc3986_remove_dot_segments`).

crate's mapping keys a part by the asset's href **relative to the item**. Published items
spell one file many ways, so `receipt.item_verdict` normalises the href and every part key
the same way before comparing (`_relative_href`, `_part_key`, `_remove_dots`). This file is
why the merge is done by hand rather than by `urllib.parse`.

## What `urllib.parse` does that a part key must not

Each line was measured on the version above.

| call | input | output | why it matters |
|---|---|---|---|
| `urljoin` | base `https://h/c/a0.json`, href `../c/a//b.tif` | `https://h/c/a/b.tif` | collapses `//` when it merges a climbing reference, so `a//b.tif`, another object-store key, matched part `a/b.tif` |
| `urljoin` | base `https://h/c//d/a0.json`, href `.` | `https://h/c/d/` | collapses `//` in the base, so no absolute href under such an item matched |
| `urljoin` | base `https://h/c/a0.json`, href `https://h/c/sub/../x.tif` | unchanged | leaves dot segments in an href that is already absolute |
| `urljoin` | base `https://h/`, href `https://h/c/./a0.json` | unchanged | so `verify`'s item URLs can carry dot segments, and the item's directory needs them removed |
| `urlsplit` | `x\t.tif` | path `x.tif` | deletes tab, CR and LF anywhere, and strips control characters and spaces at the ends |
| `urldefrag` | `x\t.tif` / `x\t.tif#b` | `x\t.tif` / `x.tif` | re-serialises only when there is a `#`, so the same href read two ways |
| `urlsplit` | `http://[::1/x` | `ValueError` | an unclosed IPv6 host raises |
| `.port` | `https://h:99999/x` | `ValueError` | `urlsplit` accepts it; reading the port raises |
| `urlsplit` | `x\x7f.tif` | path kept | DEL is read through as part of a name |

`posixpath.normpath` is no substitute: it also collapses `//` and drops a trailing `/`.

## The rule `stacs` applies

- Only `.` and `..` segments are removed (RFC 3986 section 5.2.4). Whether a path is rooted
  is read once, from its first character; a `..` at a root stays there, and a `..` that
  climbs past the start of a relative path leaves the item's directory.
- The merge with the item's URL is RFC 3986 section 5.2.3 done by hand: the item's
  directory plus the href.
- Two URLs share an origin when scheme, host and port agree, case-insensitively, with the
  default port filled in and userinfo ignored.
- A fragment is cut with `str.partition`. An href with a query names no part.
  Percent-encoding is not decoded.
- An href a parser would rewrite (a control character, DEL, a space at either end), or one
  it cannot read, is malformed, which is a disagreement.

Two sweeps in `tests/test_receipt.py` hold this against the RFC's own algorithm. One covers
every rooted path of up to four segments, and the other every relative href of up to four
segments resolved under an item URL. During review a third sweep ran outside the suite:
7,774 absolute, network-path and path-absolute hrefs, with no disagreement.

## Not covered

- A receipt href that reaches another scheme, `file://` included, is still fetched (#19).
