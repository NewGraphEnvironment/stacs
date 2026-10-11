# Task: Declare and load collection queryables from stacs.toml (#8)

**If we do it:** a catalogue declares the item properties its API should let users filter on, and `stacs register` loads them, so `/collections/<id>/queryables` lists them and CQL2 filters on them are advertised. **If we never do:** queryables can only be loaded by hand on the database host, and nothing records which a collection should have.

## Context

pgstac serves `/collections/<id>/queryables` from its own `queryables` table, not from
the collection JSON. stacs never writes to that table, so a catalogue has no way to
declare a queryable. stac_dem_bc#55 needs `lidarbc:delivery` to be queryable on
stac-elevation-bc, and stac-pointcloud-bc will need the same. The outcome: a catalogue
declares its queryables in `stacs.toml`, `stacs register` upserts them, and `stacs verify`
checks what is served against the declaration.

**What the exploration found in pgstac's loader** (read from upstream at tags v0.9.8 and
v0.10.0; these numbers go into a research file):

- `pypgstac load_queryables FILE --collection_ids=[...]` (a fire CLI, added in 0.9.6).
  It reads the document's `properties` and silently skips the core columns.
- **The row passed in wins.** For each name it deletes any *global* row
  (`collection_ids IS NULL`) and, in 0.10.0, every row whose collections overlap. So a
  per-collection load can remove a queryable another collection was serving.
- When several rows match, the served definition is merged: `enum` becomes a unique merge
  (likely sorted and deduplicated), and `minimum`/`maximum` take the widest values.
- `read_json` replaces `\\` with `\`, as it does for items, so a backslash in a fragment
  (for example in a `pattern`) would be loaded as a different value.
- Upstream `main` has since removed pypgstac in favour of a Rust `pgstac` CLI. Recorded
  only; nothing in this plan acts on it.

**Decision (user, at the gate):** each queryable loads for the catalogue's own
`collection_id` only, with no collection-ids key. This narrows the issue's Shape, so the
issue body gets edited to match.

Out of scope: a `stacs load queryables` subcommand (every consumer uses `register`),
`--delete_missing` (upsert only, never delete), and `--index_fields`.

## Phase 1: Research record and the declaration

- [x] `research/pgstac_queryables.md`: the load semantics above, with provenance
      (upstream source at v0.9.8 / v0.10.0, the file and function names) and what stacs
      does about each. Add a row to `research/README.md`.
- [x] Edit the #8 body's Shape so it reads correctly from top to bottom: own collection
      only, and why.
- [x] Write the tests first, for a new `src/stacs/queryables.py` (`parse_queryables`,
      `queryables_document`):
      - `[queryables."<name>"]` tables are JSON Schema fragments.
      - Refuse: a value that is not a table; an empty name; a `properties.` prefix
        (pgstac strips it, so verify could never match); a core column (`id`, `geometry`,
        `datetime`, `end_datetime`, `collection`; to be checked against pgstac's
        `queryable_column`), which pgstac would skip silently; a backslash anywhere;
        a TOML datetime, which has no JSON form.
- [x] Implement it, then wire it in. `read_config` treats `[queryables]` keys as
      free-form names, but each value is still checked. Add `Target.queryables`
      (default empty) checked in `Target.check`; `build_target` carries it.

## Phase 2: The load over ssh

- [x] Tests first. Extend `remote_script` with kind `queryables`, which runs
      `<launcher> load_queryables "$__stacs_tmp" --collection_ids=<python-literal list of
      the one id>`, never `--delete_missing`. The same `STACS_LOADED 1 queryables` mark
      and the same bash-3.2 discipline apply. Extend the fake `pypgstac` in
      `tests/test_register.py` to accept and log this form.
- [x] A test that runs the real `fire` (new dev dependency) over the exact arguments
      generated, against a stub with `load_queryables`' signature. It asserts
      `collection_ids == [id]`, including for an id containing a quote or a space.
- [x] `load_queryables(t, collection_id, declared, dryrun, log)` in `register.py`. It
      reuses `load`'s send, line-count and mark path, factored out rather than copied.

## Phase 3: Register and verify

Revised after the plan review (`review-plan.md`; dispositions in `findings.md`).

- [x] Tests first, with the stub API extended: `/queryables`,
      `/collections/<id>/queryables`, several collections, paging on `/collections`, a GET
      log, filter-off mode, and pgstac's serving rules (an existing collection with no
      rows is `"properties": null`; root `/queryables` 404s with no collections). The
      fake pypgstac applies a queryables load to the stub, the row passed in taking the
      global row of its name.
- [x] `verify.py`: `queryables_served` (`null` is none; a 404 for an existing collection
      raises "filter extension?"); `collections_listed` (follows `next` hrefs, never stops
      short silently); `_get_or_absent` shared with `collection_state`, with an `ABSENT`
      sentinel so a JSON `null` body is not "not there".
- [x] `queryables.py`: `fragment_digest` with `enum` compared as a set; `queryables_diff`
      reports only declared names (missing, changed). Core columns include
      `start_datetime`; empty `enum` and NUL are refused.
- [x] `_run`: declared names logged; a catalogue that declares none makes no queryables
      request. Verify reports DRIFT and writes `queryables_*.txt` only when something is
      declared. Every writing mode loads queryables **only when missing or changed**
      (each pgstac load deletes and reinserts the row, dropping an operator's index).
      Order: collection, then items, then queryables, so a queryables failure cannot hold
      items back. Post-load: served must equal declared. `_api_probe` checks root
      `/queryables`, accepting its 404 only when `/collections` lists none (bootstrap).
- [x] Other-collections guard, scoped by the review's S1: only names already served on
      this collection with a different definition can sit in a global or shared row.
      For those, every other collection is read before the first write and again after
      the load. A loss or change fails the run, with a remedy that says a global row
      cannot come back.
- [x] Mutation-checked: 21 mutations, each caught (one survived until a NUL test was
      added).

## Phase 4: Docs and release notes

- [x] README `configure` section: a `[queryables."lidarbc:delivery"]` example plus prose.
      Cover own collection only; that removing a declaration leaves the row (upsert
      never deletes); pypgstac ≥ 0.9.6 on the host; and the filter extension under
      "What it assumes". Keep the snippet markers intact.
- [x] `docs/reference/queryables.md` and its mkdocs nav entry. Run the strict build
      without `-q`.
- [x] `NEWS.md` `## Unreleased` entry. No version bump in this PR; the release is cut by
      hand at merge.

## Validation

- [x] Tests pass
- [x] `/code-check` clean (each commit, or once over the branch with `/code-check branch`)
- [x] PWF checkboxes match landed work
- [ ] `/planning-archive` on completion
