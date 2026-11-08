import ast
import sys
import tomllib
from pathlib import Path

import stacs


def test_version_matches_pyproject():
    # The installed metadata is what __version__ reads; pyproject.toml is what a release
    # bumps. A stale install is the case this catches.
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert stacs.__version__ == declared


# The standard library, which needs no declaring. Everything else a module imports is a
# dependency, whether or not something else happens to install it.
STDLIB = set(sys.stdlib_module_names)


def _third_party_imports() -> set:
    """Every third-party top-level module `src/stacs/**/*.py` imports, by reading the source.

    Derived with `ast` rather than listed: a hardcoded set is a guard that stops guarding the
    moment someone adds the fifth import, and nothing would say so (round 1).
    """
    root = Path(stacs.__file__).parent
    files = sorted(root.rglob("*.py"))
    assert files, "no source files found: this check would pass on anything"
    found = set()
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return {name for name in found if name not in STDLIB and name != "stacs"}


def test_every_directly_imported_third_party_package_is_declared():
    """`stacs.receipt` imports jsonschema directly, and `pystac[validation]` already brings it
    -- so forgetting to declare it would install, lock and pass CI, right up until the package
    in the middle drops it. A direct import belongs in [project.dependencies]."""
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
    names = {d.split(">")[0].split("[")[0].split("=")[0].strip() for d in declared}
    imported = _third_party_imports()
    assert imported, "the import walk found nothing: this check would pass on anything"
    assert imported <= names, f"imported but not declared: {sorted(imported - names)}"


def test_the_import_walk_sees_both_import_forms():
    """The walk is the guard above; a walk that missed `from x import y` would pass it."""
    import textwrap
    tree = ast.parse(textwrap.dedent("""
        import alpha.one
        from beta import two
        from . import local
        import json
    """))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    assert found == {"alpha", "beta", "json"}, found
    assert "json" in STDLIB and "alpha" not in STDLIB


def test_the_vendored_contract_sits_inside_the_package_directory():
    """The schemas and the register are read at run time through `importlib.resources`, so they
    have to be inside the package rather than beside it.

    This pins the LAYOUT, not the wheel: `uv sync` installs this project editable, so
    `importlib.resources` reads the source tree either way. What stops a wheel shipping only
    the `.py` files is `uv_build` including everything under the package directory, which the
    next test pins, plus the `uv build` check in the release path.
    """
    from importlib import resources
    root = resources.files("stacs").joinpath("data", "receipt")
    for name in ("v1.0.0/schema.json", "v1.0.0/stac_schema.json", "register.csv",
                 "mapping.csv", "SOURCE"):
        ref = root.joinpath(*name.split("/"))
        assert ref.is_file(), f"{name} is not inside the installed package"
        assert ref.read_text(encoding="utf-8").strip(), f"{name} is empty"


def test_nothing_excludes_the_vendored_contract_from_the_build():
    """`uv_build` ships everything under `src/stacs/` by default, so the way the data stops
    reaching a wheel is an exclude added later. Checked here because the editable install
    above cannot see it."""
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text()).get("tool", {}).get("uv", {}) \
        .get("build-backend", {})
    for key in ("source-exclude", "wheel-exclude", "data"):
        assert key not in config, (f"[tool.uv.build-backend] {key} is set: check it does not "
                                   f"drop src/stacs/data, which is read at run time")
