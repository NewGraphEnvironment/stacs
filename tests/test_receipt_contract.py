"""The vendored half of crate's receipt contract, and the guards that keep it honest.

The suite is offline (`conftest.py`), so the contract cannot be fetched at test time: crate's
test vectors, its two frozen JSON Schemas, its register and its mapping table live in this
repository, vendored at a pinned tag by `tools/crate_receipt_vendor.sh`.

Three things can go wrong quietly, so each has a test here:

- **The vendored files go missing.** A vector runner over an absent file passes vacuously, and
  an empty file diffs clean against another empty file. Absence is a failure, never a skip.
- **CI stops checking them.** The diff against crate's tag is the only thing that would notice
  a hand-edited vector, and it is one line in a workflow that nothing else protects.
- **The tag stops being pinned.** A script fetching `main` would make the vectors change under
  the suite, which is the opposite of what a frozen contract is for.

The file list is read out of the script rather than restated here: two lists that must agree
are a list that will not (`code-check.md`, "One fact derived twice").
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "crate_receipt_vendor.sh"
WORKFLOW = REPO / ".github" / "workflows" / "test.yml"

# What the workflow must run, and what must come after it. The pytest needle is the RUN LINE,
# not the bare word: the job itself is named `pytest`, so `"pytest"` matches the job header
# above every step and the ordering check then compares the step against the header.
CHECK_COMMAND = "bash tools/crate_receipt_vendor.sh check"
PYTEST_COMMAND = "uv run pytest"


def _block(text: str, name: str) -> list[tuple[str, str]]:
    """The `<NAME>='...'` block of the vendor script, as (source, destination) pairs.

    Raises rather than returning nothing: an unreadable block would make every check below
    pass over an empty list.
    """
    m = re.search(rf"^{name}='\n(.*?)^'$", text, re.MULTILINE | re.DOTALL)
    if m is None:
        raise AssertionError(f"{SCRIPT.name} has no {name}='...' block")
    pairs = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise AssertionError(f"{name} line is not '<source> <destination>': {line!r}")
        pairs.append((parts[0], parts[1]))
    if not pairs:
        raise AssertionError(f"{name} is empty, so these checks would pass on anything")
    return pairs


def _script() -> str:
    assert SCRIPT.is_file(), f"{SCRIPT} is missing: the contract could not be re-vendored"
    return SCRIPT.read_text(encoding="utf-8")


def _destinations() -> list[str]:
    return [dst for _src, dst in _block(_script(), "FILES")]


# =============================================================================
# The vendored files themselves
# =============================================================================

def test_the_vendor_script_lists_both_the_vectors_and_the_package_data():
    """A list that had lost one side would still look like a list."""
    dests = _destinations()
    assert any(d.startswith("tests/vectors/receipt/") for d in dests), dests
    assert any(d.startswith("src/stacs/data/receipt/") for d in dests), dests


@pytest.mark.parametrize("dest", _destinations())
def test_every_vendored_contract_file_is_present_and_not_empty(dest):
    """Absence is a failure, not a skip. A vector runner over a missing file reports nothing,
    which is indistinguishable from a runner that passed."""
    path = REPO / dest
    assert path.is_file(), (f"{dest} is not vendored; run "
                            f"`bash tools/crate_receipt_vendor.sh vendor`")
    assert path.stat().st_size > 0, f"{dest} is empty"


def test_the_source_record_names_the_repo_and_tag_it_was_vendored_from():
    source = REPO / "src" / "stacs" / "data" / "receipt" / "SOURCE"
    assert source.is_file(), "the vendored contract carries no SOURCE record"
    text = source.read_text(encoding="utf-8")
    assert "repo: NewGraphEnvironment/crate" in text, text
    assert re.search(r"^tag: v\d+\.\d+\.\d+$", text, re.MULTILINE), text
    # One blob sha per vendored file, so a reader can tell which bytes these are.
    assert len(re.findall(r"^  [0-9a-f]{40}  ", text, re.MULTILINE)) == len(_destinations())


# =============================================================================
# The guards: the tag is pinned, and CI still checks it
# =============================================================================

def test_the_vendor_script_pins_a_crate_tag():
    """Fetching a branch would let the frozen contract move under the suite."""
    text = _script()
    assert re.search(r"^CRATE_TAG=v\d+\.\d+\.\d+$", text, re.MULTILINE), \
        "CRATE_TAG must pin a released tag, not a branch"
    assert "/main/" not in text and "refs/heads" not in text, text


def _workflow_checks_contract_before_pytest(text: str) -> list[str]:
    """[] when the workflow runs the contract check before pytest, else the problems.

    Returned rather than asserted so the mutation test below can show it saying no.
    """
    problems = []
    if CHECK_COMMAND not in text:
        problems.append(f"no step runs {CHECK_COMMAND!r}")
    if PYTEST_COMMAND not in text:
        problems.append("no step runs pytest")
    if not problems and text.index(CHECK_COMMAND) > text.index(PYTEST_COMMAND):
        problems.append("the contract check runs after pytest, so a stale vector is read first")
    return problems


def test_ci_checks_the_vendored_contract_before_pytest():
    assert WORKFLOW.is_file(), f"{WORKFLOW} is missing"
    assert _workflow_checks_contract_before_pytest(
        WORKFLOW.read_text(encoding="utf-8")) == []


def _reorder(text: str) -> str:
    """The same workflow with the contract check moved after the pytest step."""
    check = f"      - run: {CHECK_COMMAND}\n        timeout-minutes: 5\n"
    assert check in text, "the step is not shaped as this mutation expects"
    return text.replace(check, "") + check


@pytest.mark.parametrize("mutate,expect", [
    (lambda t: t.replace(CHECK_COMMAND, "echo skipped"), "no step runs"),
    (lambda t: t.replace("bash tools/crate_receipt_vendor.sh check\n        timeout-minutes: 5",
                         "true"), "no step runs"),
    (_reorder, "runs after pytest"),
], ids=["step removed", "step replaced", "step moved after pytest"])
def test_the_ci_guard_notices_when_the_step_goes_away(mutate, expect):
    """The guard above is a string search over a file, which is exactly the kind of check that
    keeps passing after the thing it checks is gone. Shown saying no."""
    mutated = mutate(WORKFLOW.read_text(encoding="utf-8"))
    problems = _workflow_checks_contract_before_pytest(mutated)
    assert problems, "the guard passed a workflow with no contract check"
    assert any(expect in p for p in problems), problems


def test_the_block_parser_refuses_what_it_cannot_read():
    """The file list is parsed out of a shell script. A parser that returned nothing on a
    changed script would silently empty every parametrized check above."""
    with pytest.raises(AssertionError, match="no FILES"):
        _block("CRATE_TAG=v1.2.3\n", "FILES")
    with pytest.raises(AssertionError, match="is empty"):
        _block("FILES='\n\n'\n", "FILES")
    with pytest.raises(AssertionError, match="not '<source> <destination>'"):
        _block("FILES='\nonly_one_field\n'\n", "FILES")
