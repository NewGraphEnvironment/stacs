import tomllib
from pathlib import Path

import stacs


def test_version_matches_pyproject():
    # The installed metadata is what __version__ reads; pyproject.toml is what a release
    # bumps. A stale install is the case this catches.
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert stacs.__version__ == declared
