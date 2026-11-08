# Research

What is known, kept current: settled methods and measured facts about external systems.
The story of each issue is in `planning/archive/`; this directory holds the verdict.

Naming: `<topic>.md`, revised in place, from 2026-10-06.

| file | covers |
|---|---|
| [`pgstac_round_trip.md`](pgstac_round_trip.md) | what pgstac changes about a STAC body between load and serve, what the digest canonicalises, and why RFC 8785 |
| [`pgstac_queryables.md`](pgstac_queryables.md) | how pypgstac loads queryables (the row passed in wins), how the API serves them, and what stacs guards |
| [`pypgstac_database_query.md`](pypgstac_database_query.md) | asking pypgstac which database its connection reaches (`_db query_one`), and what the answer cannot see |
| [`receipt_parity.md`](receipt_parity.md) | what holds crate's receipt contract byte for byte across its R and Python implementations, what is not covered, and where the two genuinely differ |

## Related work

- [`stac_dem_bc/research/pgstac_round_trip.md`](https://github.com/NewGraphEnvironment/stac_dem_bc/blob/main/research/pgstac_round_trip.md):
  the original measurement (2026-09-29), which `pgstac_round_trip.md` here continues.
