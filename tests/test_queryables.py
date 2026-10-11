"""The declaration of a catalogue's queryables, and its comparison with what is served.

What pgstac does with a queryables document, and why each refusal here exists, is in
research/pgstac_queryables.md.
"""

import datetime
import json

import pytest

from stacs.queryables import (QueryablesError, fragment_digest, parse_queryables,
                              queryables_diff, queryables_document)

DELIVERY = {"type": "string", "title": "LidarBC delivery"}


def test_a_declaration_parses_to_its_fragments():
    got = parse_queryables({"lidarbc:delivery": DELIVERY, "gsd": {"type": "number"}})
    assert got == {"lidarbc:delivery": DELIVERY, "gsd": {"type": "number"}}


@pytest.mark.parametrize("table", [None, {}])
def test_nothing_declared_is_an_empty_declaration(table):
    assert parse_queryables(table) == {}


@pytest.mark.parametrize("table, match", [
    (["lidarbc:delivery"], "must be a table"),
    ({"lidarbc:delivery": "string"}, "must be a table"),
    ({"": DELIVERY}, "empty"),
    ({" lidarbc:delivery": DELIVERY}, "whitespace"),
    ({"properties.lidarbc:delivery": DELIVERY}, "properties."),
    ({"datetime": {"type": "string"}}, "column"),
    ({"start_datetime": {"type": "string"}}, "column"),
    ({"collection": {"type": "string"}}, "column"),
    ({"x": {"type": "string", "pattern": "^\\d+$"}}, "backslash"),
    ({"x\\y": {"type": "string"}}, "backslash"),
    ({"x": {"type": "string", "enum": []}}, "empty enum"),
    ({"x": {"type": "string", "enum": "a"}}, "enum"),
    ({"x": {"type": "string", "default": datetime.date(2026, 1, 1)}}, "JSON"),
    ({"x": {"type": "number", "maximum": float("inf")}}, "JSON"),
])
def test_a_declaration_pgstac_would_not_serve_as_written_is_refused(table, match):
    with pytest.raises(QueryablesError, match=match):
        parse_queryables(table)


def test_the_document_carries_the_fragments_under_properties():
    doc = queryables_document({"lidarbc:delivery": DELIVERY})
    assert doc["properties"] == {"lidarbc:delivery": DELIVERY}
    assert doc["type"] == "object"
    # One line, which is what the remote script counts.
    assert "\n" not in json.dumps(doc, separators=(",", ":"))


def test_a_served_enum_reordered_and_deduplicated_is_the_same_fragment():
    declared = {"type": "string", "enum": ["b", "a", "b"]}
    served = {"type": "string", "enum": ["a", "b"]}
    assert fragment_digest(declared) == fragment_digest(served)


def test_an_enum_with_a_member_missing_is_a_different_fragment():
    assert fragment_digest({"enum": ["a", "b"]}) != fragment_digest({"enum": ["a"]})


def test_an_integral_float_and_its_integer_are_the_same_fragment():
    assert fragment_digest({"minimum": 1.0}) == fragment_digest({"minimum": 1})


def test_diff_reports_missing_and_changed_never_undeclared():
    declared = {"a": {"type": "string"}, "b": {"type": "string"}, "c": {"type": "number"}}
    served = {"b": {"type": "string"}, "c": {"type": "integer"},
              "eo:cloud_cover": {"type": "number"}}
    assert queryables_diff(declared, served) == (["a"], ["c"])


def test_diff_refuses_a_served_fragment_that_is_not_an_object():
    with pytest.raises(QueryablesError, match="not an object"):
        queryables_diff({"a": {"type": "string"}}, {"a": None})


def test_a_target_built_without_the_cli_still_checks_its_queryables():
    from stacs.register import RegisterError, Target
    t = Target(api="https://api.example.invalid", collection_id="any-collection",
               bucket_url="https://bucket.example.invalid",
               queryables={"datetime": {"type": "string"}})
    with pytest.raises(RegisterError, match="queryables: .*column"):
        t.check()
