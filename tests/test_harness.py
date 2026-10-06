"""The suite's own guards, pinned so they cannot silently stop guarding."""

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
import requests
import urllib3


def test_no_lookup_outside_loopback_can_happen():
    with pytest.raises(OSError, match="network disabled in tests"):
        socket.getaddrinfo("example.com", 443)


@pytest.mark.parametrize("fetch", [
    lambda: requests.get("https://example.com/", timeout=5),
    # urllib3's PoolManager ignores proxy variables; pystac fetches schemas with it.
    lambda: urllib3.PoolManager(retries=False).request("GET", "https://example.com/"),
])
def test_every_http_stack_is_stopped(fetch):
    with pytest.raises(Exception) as e:
        fetch()
    assert "network disabled in tests" in repr(e.value) or \
        "network disabled in tests" in str(e.value.__context__)


def test_loopback_still_resolves():
    assert socket.getaddrinfo("127.0.0.1", 80)


def test_no_connection_outside_loopback_can_be_opened():
    """An IP literal needs no lookup, so the connect itself is guarded."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError, match="network disabled in tests"):
            s.connect(("93.184.215.14", 80))
    finally:
        s.close()


def test_no_proxy_variable_survives(monkeypatch):
    import os
    assert os.environ.get("NO_PROXY") == "*"
    assert not any(os.environ.get(k) for k in ("http_proxy", "https_proxy",
                                                "HTTP_PROXY", "HTTPS_PROXY"))


def test_udp_cannot_leave_loopback():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(OSError, match="network disabled in tests"):
            s.sendto(b"x", ("192.0.2.1", 53))
        with pytest.raises(OSError, match="network disabled in tests"):
            s.sendto(b"x", 0, ("192.0.2.1", 53))
    finally:
        s.close()


@pytest.mark.parametrize("fn", [socket.gethostbyname, socket.gethostbyname_ex])
def test_legacy_lookups_are_refused(fn):
    with pytest.raises(OSError, match="network disabled in tests"):
        fn("example.invalid")


# =============================================================================
# Docstring examples -- collected with the tests, and under the same guard
# =============================================================================

REPO = Path(__file__).resolve().parent.parent


def test_docstring_examples_are_collected():
    """A bare `pytest` at the root (what CI runs) collects the examples of every module
    that has them. Asserted on what a child run collects, not on this session's
    settings: `testpaths`, `--doctest-modules` and any `collect_ignore` all decide it,
    and the examples would otherwise stop running with nothing failing."""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    for module in ("verify", "catalogue", "validate", "register"):
        assert f"src/stacs/{module}.py::stacs.{module}." in out.stdout, module


# Loaded into the child run with -p. It tries a lookup once collection is done, so it
# sees whatever guard that run installed -- or none.
_PROBE = """
import socket

def pytest_collection_finish(session):
    try:
        socket.getaddrinfo("example.invalid", 80)
    except OSError as e:
        if "network disabled in tests" in str(e):
            print("STACS_GUARD_ACTIVE")
            return
        raise
    raise RuntimeError("a lookup outside loopback was allowed")
"""


# Each kind of invocation loads a different set of conftests: a path loads those on it
# and above it, a bare run those of every testpath. Only the root is above all of them.
@pytest.mark.parametrize("args", [["src/stacs/verify.py"], ["tests/test_harness.py"], []],
                         ids=["src-only", "tests-only", "bare"])
def test_the_guard_loads_however_pytest_is_invoked(tmp_path, args):
    """A guard in tests/ is absent from `pytest src/...`, and one in src/ from
    `pytest tests/...`. Asserted by behaviour, in a child process: this session's
    sockets are already patched, so an in-process probe would pass with the guard
    anywhere, and a check on which conftest registered would pass with any file there."""
    (tmp_path / "stacs_guard_probe.py").write_text(_PROBE)
    path = os.pathsep.join(filter(None, [str(tmp_path), os.environ.get("PYTHONPATH")]))
    env = {**os.environ, "PYTHONPATH": path}
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         "-p", "stacs_guard_probe", *args],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "STACS_GUARD_ACTIVE" in out.stdout, out.stdout + out.stderr
