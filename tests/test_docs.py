"""The site's pages are README sections, cut out by marker. pymdownx.snippets refuses a
missing start marker, but runs a section with no end marker to the end of the file, so a
lost `[end:x]` copies every later section onto the page and the strict build passes."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MARKER = re.compile(r"<!-- --8<-- \[(start|end):([\w-]+)\] -->")


def readme_markers(text):
    return [(m.group(1), m.group(2)) for m in MARKER.finditer(text)]


def check_markers(text):
    """Problems with README's section markers: each start closed by its own end before
    the next start, and every name used once."""
    problems, open_name, seen = [], None, set()
    for kind, name in readme_markers(text):
        if kind == "start":
            if open_name is not None:
                problems.append(f"[start:{name}] inside unclosed [start:{open_name}]")
            if name in seen:
                problems.append(f"section {name!r} defined twice")
            seen.add(name)
            open_name = name
        elif name != open_name:
            problems.append(f"[end:{name}] does not close [start:{open_name}]")
        else:
            open_name = None
    if open_name is not None:
        problems.append(f"[start:{open_name}] is never closed")
    return problems


def test_every_readme_section_is_closed():
    assert check_markers((REPO / "README.md").read_text(encoding="utf-8")) == []


def test_every_section_a_page_names_exists():
    names = {n for k, n in readme_markers((REPO / "README.md").read_text(encoding="utf-8"))
             if k == "start"}
    used = {m.group(1) for page in (REPO / "docs").rglob("*.md")
            for m in re.finditer(r'--8<-- "README\.md:([\w-]+)"', page.read_text())}
    assert used and used <= names, used - names


def test_the_check_sees_the_shapes_that_break_a_page():
    start = "<!-- --8<-- [start:{}] -->"
    end = "<!-- --8<-- [end:{}] -->"
    good = "\n".join([start.format("a"), "x", end.format("a"),
                      start.format("b"), "y", end.format("b")])
    assert check_markers(good) == []
    lost_end = "\n".join([start.format("a"), "x", start.format("b"), "y", end.format("b")])
    misspelt = "\n".join([start.format("a"), "x", end.format("aa")])
    unclosed = "\n".join([start.format("a"), "x"])
    twice = "\n".join([start.format("a"), end.format("a"), start.format("a"),
                       end.format("a")])
    for broken in (lost_end, misspelt, unclosed, twice):
        assert check_markers(broken), broken
