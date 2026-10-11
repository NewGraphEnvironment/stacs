## Outcome

Every load now names the database it reached (#6). Before writing, the remote script asks
the caller's own pypgstac launcher `_db query_one 'SELECT current_database()'`, which opens
the connection the load opens. It refuses on the host before pypgstac writes if the
answer is not `Transport.db`, and it prints the name in `STACS_LOADED <n> <kind> <db>`,
which `_send` requires exactly. The issue's scenario reproduced first, as a test: the API
already served identical bodies and the launcher reached `otherdb`, and the run reported
DONE. It is now refused, with nothing loaded. Review rounds 1 and 2 each found the same
mechanism at a different layer, a name that differs from `db` only by a character one layer
hides or splits on: a CRLF launcher's `\r` invisible in the refusal (now `printf %q`), and
Python's universal newlines and `splitlines()` cutting `stacdb\r` down to `stacdb` (now
decoded by hand and split on `\n` alone). Round 3 enumerated 14 places that mechanism
reaches and found them safe. Left to the user: a pooler that aliases `db` to another
server-side name is refused on every load, and supporting it needs a separate
expected-name setting. The durable verdict on the pypgstac query is
[`research/pypgstac_database_query.md`](../../../research/pypgstac_database_query.md).

## Measurement

Mutation table in `findings.md`: every new guard turns its tests red when removed, except
the redundant `|| exit 1` after the query (the reasserted `set -e` and the empty-name
compare also catch it) and the success line echoing `t.db` (equivalent once the host
compare has passed). 479 tests became 486.

Closed by: PR (this branch, `6-report-the-database-each-load-reached`)
