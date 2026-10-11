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

- [ ] Tests first. Extend `remote_script` with kind `queryables`, which runs
      `<launcher> load_queryables "$__stacs_tmp" --collection_ids=<python-literal list of
      the one id>`, never `--delete_missing`. The same `STACS_LOADED 1 queryables` mark
      and the same bash-3.2 discipline apply. Extend the fake `pypgstac` in
      `tests/test_register.py` to accept and log this form.
- [ ] A test that runs the real `fire` (new dev dependency) over the exact arguments
      generated, against a stub with `load_queryables`' signature. It asserts
      `collection_ids == [id]`, including for an id containing a quote or a space.
- [ ] `load_queryables(t, collection_id, declared, dryrun, log)` in `register.py`. It
      reuses `load`'s send, line-count and mark path, factored out rather than copied.

## Phase 3: Register and verify

- [ ] Tests first, with the stub API extended: `/queryables`,
      `/collections/<id>/queryables`, several collections, paging on `/collections`. The
      fake pypgstac applies a queryables load to the stub, including a mode that mimics
      "the row passed wins" against another collection's queryable.
- [ ] `verify.py`:
      - `queryables_served(collection_id, api)`: GET with retries. A 404 counts as "none"
        only if `/collections` answers, as `collection_state` does.
      - `queryables_diff(declared, served) -> (missing, changed)`: by digest of each
        fragment, with `enum` compared as a sorted, deduplicated set. Undeclared served
        names are not reported, because pgstac's global defaults cannot be told apart
        from them.
- [ ] `_run`:
      - Log the declared names.
      - `_api_probe` also GETs `/queryables` when any are declared, so an API without
        the filter extension is refused before writing.
      - **verify** reports `DRIFT` for missing or changed queryables (exit 1) and writes
        `queryables_missing.txt` and `queryables_changed.txt` to `--out-dir`.
      - **drift** loads the queryables when they differ, and "already in sync" now also
        requires them to be in sync.
      - **all** and **ids** load them whenever any are declared.
      - Order: collection, then queryables, then items.
      - After the load, the collection's served queryables must equal the declaration,
        or `RegisterError`.
- [ ] A guard for other collections. Before the load, enumerate `/collections`
      (following `next` links) and record each other collection's served definitions of
      the declared names. After the load, re-read them. Any that were lost or changed
      raise a `RegisterError` naming the collections, with the remedy (re-register them).
      It cannot prevent the replacement, because the API cannot tell a global row from
      a per-collection one; it can make the damage loud.
- [ ] Mutation-check each new guard: remove it, watch a test fail, restore it.

## Phase 4: Docs and release notes

- [ ] README `configure` section: a `[queryables."lidarbc:delivery"]` example plus prose.
      Cover own collection only; that removing a declaration leaves the row (upsert
      never deletes); pypgstac ≥ 0.9.6 on the host; and the filter extension under
      "What it assumes". Keep the snippet markers intact.
- [ ] `docs/reference/queryables.md` and its mkdocs nav entry. Run the strict build
      without `-q`.
- [ ] `NEWS.md` `## Unreleased` entry. No version bump in this PR; the release is cut by
      hand at merge.

## Validation

- [ ] Tests pass
- [ ] `/code-check` clean (each commit, or once over the branch with `/code-check branch`)
- [ ] PWF checkboxes match landed work
- [ ] `/planning-archive` on completion
