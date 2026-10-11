"""A catalogue's declared queryables, and their comparison with what an API serves.

pgstac serves `/collections/<id>/queryables` from its own `queryables` table, never from
the collection body. A catalogue declares the item properties its API should let clients
filter on in `stacs.toml`, one JSON Schema fragment per property:

    [queryables."lidarbc:delivery"]
    type = "string"
    title = "LidarBC delivery"

They are loaded for the catalogue's OWN collection and no other. pypgstac's loader
replaces every row of a name that overlaps the collections it loads for, and the global
row too, so a catalogue that named another's collection would narrow or remove that
catalogue's queryable every time it registered. Rows for disjoint collections coexist.

Every refusal here is a declaration pgstac would not serve as written, which would read
as drift on every verify. research/pgstac_queryables.md has the source for each.
"""

import hashlib
import math

import rfc8785

from stacs.verify import _canonical

# Read by pgstac as columns of `items`, not as properties. pypgstac skips them silently,
# so a declared one would never be loaded and would verify as missing forever.
CORE_COLUMNS = frozenset({"id", "geometry", "datetime", "start_datetime", "end_datetime",
                          "collection"})

SCHEMA = "http://json-schema.org/draft-07/schema#"


class QueryablesError(ValueError):
    """A declaration pgstac would not serve as written, or a served one that cannot be
    compared."""


def _check_json(value, where: str) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise QueryablesError(f"{where}: key {k!r} is not a string")
            if "\\" in k:
                raise QueryablesError(f"{where}: key {k!r} contains a backslash, which "
                                      f"pypgstac's reader rewrites before loading")
            _check_json(v, f"{where}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _check_json(v, f"{where}[{i}]")
    elif isinstance(value, str):
        if "\\" in value:
            raise QueryablesError(f"{where}: {value!r} contains a backslash, which "
                                  f"pypgstac's reader rewrites before loading")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise QueryablesError(f"{where}: {value!r} has no JSON form")
    elif not isinstance(value, (bool, int)):
        # TOML can say a date or a time; JSON cannot.
        raise QueryablesError(f"{where}: a {type(value).__name__} has no JSON form")


def parse_queryables(table) -> dict[str, dict]:
    """{name: fragment} from the `[queryables]` table of a config. None means none.

    Examples:
        >>> parse_queryables({"lidarbc:delivery": {"type": "string"}})
        {'lidarbc:delivery': {'type': 'string'}}
        >>> parse_queryables({"datetime": {"type": "string"}})
        Traceback (most recent call last):
        ...
        stacs.queryables.QueryablesError: queryable 'datetime' is read by pgstac as a ...
    """
    if table is None:
        return {}
    if not isinstance(table, dict):
        raise QueryablesError(f"[queryables] must be a table of property names, got "
                              f"{table!r}")
    out = {}
    for name, fragment in table.items():
        if not isinstance(name, str) or not name:
            raise QueryablesError(f"a queryable name is empty: {name!r}")
        if name != name.strip():
            raise QueryablesError(f"queryable {name!r} has surrounding whitespace")
        if name.startswith("properties."):
            # pgstac 0.10 strips the prefix, so the served name would never match.
            raise QueryablesError(f"queryable {name!r}: name the property without the "
                                  f"'properties.' prefix")
        if name in CORE_COLUMNS:
            raise QueryablesError(f"queryable {name!r} is read by pgstac as a column of "
                                  f"items, and pypgstac skips it without loading it")
        if not isinstance(fragment, dict):
            raise QueryablesError(f"queryable {name!r} must be a table (a JSON Schema "
                                  f"fragment), got {fragment!r}")
        _check_json({name: fragment}, "[queryables]")
        if "enum" in fragment:
            enum = fragment["enum"]
            if not isinstance(enum, list):
                raise QueryablesError(f"queryable {name!r}: enum must be a list")
            if not enum:
                # pgstac serves an empty enum as no enum at all.
                raise QueryablesError(f"queryable {name!r} has an empty enum, which "
                                      f"permits nothing and which pgstac serves as absent")
        out[name] = fragment
    return out


def queryables_document(declared: dict) -> dict:
    """The document `pypgstac load_queryables` reads: the fragments under `properties`.

    Examples:
        >>> queryables_document({"gsd": {"type": "number"}})["properties"]
        {'gsd': {'type': 'number'}}
    """
    return {"$schema": SCHEMA, "type": "object", "properties": dict(declared)}


def fragment_digest(fragment) -> str:
    """sha256 of a fragment in the form both sides are reduced to before comparing.

    RFC 8785 over the same canonical form as item bodies, with one addition: pgstac
    serves `enum` as `jsonb_agg(DISTINCT ...)`, deduplicated and reordered, so it is
    compared as a set.

    Examples:
        >>> fragment_digest({"enum": ["b", "a"]}) == fragment_digest({"enum": ["a", "b"]})
        True
    """
    if not isinstance(fragment, dict):
        raise QueryablesError(f"a queryable fragment is not an object: {fragment!r}")
    doc = dict(fragment)
    if isinstance(doc.get("enum"), list):
        members = {rfc8785.dumps(_canonical(m)): m for m in doc["enum"]}
        doc["enum"] = [members[k] for k in sorted(members)]
    return hashlib.sha256(rfc8785.dumps(_canonical(doc))).hexdigest()


def queryables_diff(declared: dict, served: dict) -> tuple[list[str], list[str]]:
    """(missing, changed): declared names the API does not serve, and those it serves
    with a different fragment.

    Served names nobody declared are not reported: pgstac's global defaults and rows
    another loader wrote look the same from the API.

    Examples:
        >>> queryables_diff({"a": {"type": "string"}, "b": {"type": "string"}},
        ...                 {"b": {"type": "number"}, "id": {"type": "string"}})
        (['a'], ['b'])
    """
    missing = sorted(n for n in declared if n not in served)
    changed = sorted(n for n in declared if n in served
                     and fragment_digest(served[n]) != fragment_digest(declared[n]))
    return missing, changed
