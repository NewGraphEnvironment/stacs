# Plan review (Plan agent, 2026-10-11), as returned; dispositions in findings.md

Blockers: B1 a 404 on /collections/<id>/queryables also means the filter extension is off,
and verify never runs the probe, so it would report DRIFT forever; B2 a root /queryables
probe 404s on a database with no collections (get_queryables(NULL) is NULL then), so it
refuses the bootstrap.
Gaps: G1 an existing collection with zero rows is 200 {"properties": null}, not 404
(aggregate with no GROUP BY over an empty set returns one row); G2 a declaration-free
catalogue must touch no queryables endpoint, so test it; G3 loading in every all/ids run is
a delete-and-insert each time (drops property_index_type, fires maintain_partitions), so
load only when missing or changed; G4 the register.py docstring "nothing deletes" is now
false; G5 dryrun; G6 a queryables-only drift still upserts the collection; G7 a docstring
names research/ (CLAUDE.md: don't); G8 the plan text drifted (start_datetime, empty enum,
enum as a set); G9 NUL is not refused (jsonb rejects it).
Ordering: O1 collection, then items, then queryables, so a queryables failure (0.9.x
unique_violation on a shared row, pypgstac < 0.9.6, permissions) does not block items;
O2 take the snapshot before any write.
Guard: S1 the rows a load replaces are exactly rows served on OUR collection, so a name not
served on ours cannot harm another; guard only names served on ours beforehand; S2 the
"re-register" remedy cannot restore a global row; S3 the enumeration must be complete, and
a 404 on another collection must never read as "lost".
Assumptions A1-A6 (fragments served verbatim apart from $id; permissions; pypgstac >=
0.9.6; never load an empty document; fire literal; caching). Harness H1-H3. Scope Sc1
(issue says /queryables, the endpoint used is /collections/<id>/queryables), Sc2 (ids
mode). Acceptance Acc1 (a live run on the host, a second drift run being a no-op), Acc2
(backward compatibility), Acc3 (mutation-check B1, B2 and S1).
