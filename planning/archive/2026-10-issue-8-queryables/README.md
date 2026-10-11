## Outcome

A catalogue declares its queryables in `stacs.toml` (`[queryables."<name>"]`, one JSON Schema
fragment each). `stacs register` loads them with `pypgstac load_queryables` for the
catalogue's own collection only (the user's decision at the plan gate). It loads them last,
once the collection and items are verified, and only for a name that is missing or served
differently. `stacs verify` compares `/collections/<id>/queryables` with the declaration.

The work was mostly about pgstac's loader, whose rule is that the row passed in wins: a
per-collection load replaces a global or shared row of the name, and with it other
collections' queryables. The other-collections guard took three review passes to get right:
- the plan review;
- code-check round 1: the send set, and a first registration;
- code-check round 2: every way out after a load that can commit and still report failure.

All three passes had one cause. The guard was scoped by stacs' own account of the load
rather than by what the load can change in the database. Round 3 enumerated every place that
cause reaches and found each covered.

Every guard was mutation-checked. Upstream semantics, with sources, are in
[`research/pgstac_queryables.md`](../../../research/pgstac_queryables.md). Not yet proven
against a live host: that is stac_dem_bc#55's re-registration.

Closed by: PR for #8 (branch `8-declare-and-load-collection-queryables-f`)
