import tomllib
from pathlib import Path

import stacs


def test_version_matches_pyproject():
    # The installed metadata is what __version__ reads; pyproject.toml is what a release
    # bumps. A stale install is the case this catches.
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert stacs.__version__ == declared


def test_every_directly_imported_third_party_package_is_declared():
    """`stacs.receipt` imports jsonschema directly, and `pystac[validation]` already brings it
    -- so forgetting to declare it would install, lock and pass CI, right up until the package
    in the middle drops it. A direct import belongs in [project.dependencies]."""
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
    names = {d.split(">")[0].split("[")[0].split("=")[0].strip() for d in declared}
    assert {"jsonschema", "rfc8785", "pystac", "requests"} <= names, sorted(names)


def test_the_vendored_contract_is_importable_package_data():
    """The schemas and the register are read at run time through `importlib.resources`, so they
    have to be inside the package rather than beside it -- a wheel that shipped only the .py
    files would pass every test in a source tree."""
    from importlib import resources
    root = resources.files("stacs").joinpath("data", "receipt")
    for name in ("v1.0.0/schema.json", "v1.0.0/stac_schema.json", "register.csv",
                 "mapping.csv", "SOURCE"):
        ref = root.joinpath(*name.split("/"))
        assert ref.is_file(), f"{name} is not inside the installed package"
        assert ref.read_text(encoding="utf-8").strip(), f"{name} is empty"
