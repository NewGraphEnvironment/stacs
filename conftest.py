"""Python code under test cannot reach the network, except loopback (where stub APIs
listen).

Proxy variables are not enough: requests and urllib honour them, but urllib3's
PoolManager -- which pystac uses for schema fetches whenever urllib3 is installed --
does not. So the line is drawn at the socket: a lookup of any non-loopback name is
refused, and so is a connection to any non-loopback address. Installed for the whole
session in `pytest_configure`, so session- and module-scoped fixtures are covered too.

At the repository root rather than in `tests/`: pytest loads a conftest only for the
paths it is given and their parents, so in `tests/` the guard was absent from
`pytest src/stacs/verify.py` -- a run of the docstring examples alone.

Proxy variables are removed and NO_PROXY set to `*`, or a client could reach the
internet THROUGH a loopback proxy without ever resolving the target.

Covered: getaddrinfo, gethostbyname(_ex), and connect / connect_ex / sendto / sendmsg on
`socket.socket`. Not covered, and not used by this package: the C-level `_socket` module
called directly, and subprocesses (ssh, pypgstac), which resolve in C -- the tests put
stubs for those on PATH.
"""

import ipaddress
import os
import socket

LOOPBACK_NAMES = {"localhost"}
_real_getaddrinfo = socket.getaddrinfo
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_sendto = socket.socket.sendto
_real_sendmsg = socket.socket.sendmsg
_real_gethostbyname = socket.gethostbyname
_real_gethostbyname_ex = socket.gethostbyname_ex
_PROXY_VARS = ("http_proxy", "https_proxy", "all_proxy", "ftp_proxy")


class NetworkDisabled(OSError):
    pass


def _is_loopback(host) -> bool:
    name = host.decode() if isinstance(host, bytes) else str(host)
    if name in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(name.split("%")[0]).is_loopback
    except ValueError:
        return False


def _guarded_getaddrinfo(host, *args, **kwargs):
    if host is not None and not _is_loopback(host):
        raise NetworkDisabled(f"network disabled in tests: lookup of {host!r}")
    return _real_getaddrinfo(host, *args, **kwargs)


def _check_address(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6) and not _is_loopback(address[0]):
        raise NetworkDisabled(f"network disabled in tests: connect to {address!r}")


def _guarded_connect(self, address):
    _check_address(self, address)
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    _check_address(self, address)
    return _real_connect_ex(self, address)


def _guarded_sendto(self, data, *args):
    # sendto(data, address) or sendto(data, flags, address)
    _check_address(self, args[-1])
    return _real_sendto(self, data, *args)


def _guarded_sendmsg(self, buffers, *args):
    # sendmsg(buffers[, ancdata[, flags[, address]]])
    if len(args) >= 3 and args[2] is not None:
        _check_address(self, args[2])
    return _real_sendmsg(self, buffers, *args)


def _guarded_gethostbyname(host):
    if not _is_loopback(host):
        raise NetworkDisabled(f"network disabled in tests: lookup of {host!r}")
    return _real_gethostbyname(host)


def _guarded_gethostbyname_ex(host):
    if not _is_loopback(host):
        raise NetworkDisabled(f"network disabled in tests: lookup of {host!r}")
    return _real_gethostbyname_ex(host)


_PATCHES = {
    (socket, "getaddrinfo"): (_real_getaddrinfo, _guarded_getaddrinfo),
    (socket, "gethostbyname"): (_real_gethostbyname, _guarded_gethostbyname),
    (socket, "gethostbyname_ex"): (_real_gethostbyname_ex, _guarded_gethostbyname_ex),
    (socket.socket, "connect"): (_real_connect, _guarded_connect),
    (socket.socket, "connect_ex"): (_real_connect_ex, _guarded_connect_ex),
    (socket.socket, "sendto"): (_real_sendto, _guarded_sendto),
    (socket.socket, "sendmsg"): (_real_sendmsg, _guarded_sendmsg),
}


def pytest_configure(config):
    for k in _PROXY_VARS:
        os.environ.pop(k, None)
        os.environ.pop(k.upper(), None)
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "*"
    for (owner, name), (_, guarded) in _PATCHES.items():
        setattr(owner, name, guarded)


def pytest_unconfigure(config):
    for (owner, name), (real, _) in _PATCHES.items():
        setattr(owner, name, real)
