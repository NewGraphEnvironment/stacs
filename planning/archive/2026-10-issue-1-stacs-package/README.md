# Issue #1: package the pgstac registration and verification layer

## Outcome

`stacs` now holds what every `stac_*_bc` repo repeated: `stacs.verify` (id sets both ways,
body digests), `stacs.catalogue` (the published side), `stacs.validate` (pre-load audit,
pystac validation), `stacs.register` (upsert over ssh to the host's pypgstac, then read
back through the API) and the `stacs` CLI configured by `stacs.toml`. Extracted from
stac_dem_bc with no deployment defaults (pinned by a structural and a text guard). The
digest moved to RFC 8785. A plan review and 13 code-check rounds (4, 3, 2, 2, 2 across the
five code phases) found that the
extracted code was right about everything it had been tested against in production and
wrong in the same few directions elsewhere: **absence inferred from not seeing** (a stale
body in a reused fetch dir, a short page read as the last), **polymorphic operators on
unpinned inputs** (`"data" in "data"` satisfying a required asset), **an exit status taken
as proof the work happened** (bash 3.2 exits 0 from an EXIT trap after an expansion error;
`( ... ) || exit 1` suspends `set -e` inside the subshell), and **a check written per
caller rather than in the shared producer**. Each phase ended by enumerating the candidate
set its mechanism implied (findings.md), not by a reviewer going quiet. Adoption is filed per
repo: stac_dem_bc#49, stac_airphoto_bc#42, stac_uav_bc#35, stac_orthophoto_bc#47,
stac_floodplains_bc#71.

## Measurement

Live, read-only, 2026-10-06, against the production STAC API:

- **Parity:** `stacs verify` and stac_dem_bc's `register_manifest.py diff` produced
  byte-identical missing / changed / orphaned lists and collection state for
  `stac-elevation-bc` (102,460 items; 760 s vs 744 s) and `stac-airphoto-bc` (10,100; 63 s
  vs 67 s). Both in sync.
- **Positive control:** one body edited in a `file://` copy of airphoto -- both tools report
  exactly that id changed. Without it the empty sets above would prove nothing.
- **Verdict equivalence:** old digest vs RFC 8785 digest over the same bodies and API pass:
  0 disagreements in 112,560 items. 160 elevation items differ with only `links` removed and
  compare equal canonicalised (the null-member class of 2026-09-29); the 29 integral-float
  items of that date no longer differ, so that rule is now pinned by tests only.
- **Scan:** no published body carries NaN/Infinity, an integer beyond 2^53, or a backslash
  -- so the pypgstac 0.10.0 loader's backslash rewrite (recorded, not worked around) touches
  no live item.
- **Cost:** `rfc8785` 139 µs vs `json.dumps` 54 µs per 2.7 KB item; ~17 s per 102k-item
  verify, within the 2% wall-time difference above.

What changed because of them: the switch to JCS is safe to ship (no verdict moved, nothing
stored to migrate), and the adoption issues could state parity as measured rather than
expected. The durable verdict is [`research/pgstac_round_trip.md`](../../../research/pgstac_round_trip.md).

## Evidence

`evidence/20261006_*` -- the reference and stacs run logs, the equivalence results, and the
positive control; `evidence/*.py`, `evidence/reference.sh` -- the scripts that produced them
(API and bucket URLs as environment variables).

Closed by: PR to be opened from branch `1-stacs-package-the-pgstac-registration-an`
