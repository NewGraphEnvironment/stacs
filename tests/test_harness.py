"""The suite's own guards, pinned so they cannot silently stop guarding."""

import socket

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
