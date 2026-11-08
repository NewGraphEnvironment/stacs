"""stacs is a public tool: the host, database, API, bucket and collection are always the
caller's. Two checks, because either alone has a hole.

- Structural: no public function gives a deployment parameter a default. A default is
  exactly the thing that goes unnoticed when a caller forgets to pass the value.
- Textual: no source file names a deployment this package was extracted from. The
  structural check cannot see a module constant used inside a function body.
"""

import dataclasses
import functools
import importlib
import inspect
import pkgutil
import re
from pathlib import Path

import pytest

import stacs

# Substrings, not exact names: `bucket=`, `pghost=` and `dsn=` are as much a deployment
# default as `bucket_url=`. `None` is not a deployment ("not supplied").
DEPLOYMENT_PARAM = re.compile(r"api|host|db|database|dsn|conninfo|endpoint|uri|url|"
                              r"server|collection|bucket|prelude|env_file|workdir|"
                              r"user|password")

# Names of real deployments. Fixtures use example.invalid instead.
KNOWN_DEPLOYMENT_STRINGS = ("a11s.one", "geopro", "/opt/geoserv", "146.190.",
                            "stac-dem-bc", "stac-elevation-bc", "stac-airphoto-bc",
                            "dev-imagery-uav-bc", "objectstore.gov.bc.ca",
                            "amazonaws.com", "newgraphenvironment")

# The one exception, and it is a SCHEMA IDENTITY rather than a deployment: a versioned crate
# receipt schema URL. `stacs.receipt` writes these into stored records -- the receipt names its
# schema, and an item lists the extension in `stac_extensions` -- so the URL is part of the
# contract, not a default a caller should have supplied. It cannot be hidden in a data file
# instead: this check reads only `*.py`, so moving the string there would be an escape hatch
# rather than an exception.
#
# Deliberately narrow: the version is a version, the host and path are fixed, and the only
# optional segment is crate's `stac/`. Anything else under the same host -- a bucket, a
# published catalogue, a page -- still fails, which
# `test_the_schema_carve_out_admits_nothing_else` shows.
CRATE_SCHEMA_URL = re.compile(
    r"https://newgraphenvironment\.github\.io/crate/(?:stac/)?receipt/"
    r"v\d+\.\d+\.\d+/schema\.json")


def _modules():
    for info in pkgutil.walk_packages(stacs.__path__, prefix="stacs."):
        yield importlib.import_module(info.name)


def _callables(mod):
    """Module functions and partials, and every class's constructor, methods,
    staticmethods and classmethods -- a dataclass field default reaches callers through
    the generated __init__, and a classmethod is a bound method to getmembers."""
    for name, obj in vars(mod).items():
        if isinstance(obj, functools.partial):
            yield name, obj
        elif inspect.isfunction(obj) and obj.__module__ == mod.__name__:
            yield name, obj
        elif inspect.isclass(obj) and obj.__module__ == mod.__name__:
            for mname, m in vars(obj).items():
                fn = m.__func__ if isinstance(m, (staticmethod, classmethod)) else m
                if inspect.isfunction(fn):
                    yield f"{name}.{mname}", fn


def _defaults(fn):
    """(name, default) for every parameter a call can omit."""
    if isinstance(fn, functools.partial):
        yield from fn.keywords.items()
        fn = fn.func
    for p in inspect.signature(fn).parameters.values():
        yield p.name, p.default


def test_no_deployment_parameter_has_a_default():
    offenders = []
    for mod in _modules():
        for name, fn in _callables(mod):
            for pname, default in _defaults(fn):
                if DEPLOYMENT_PARAM.search(pname) and _is_a_value(default):
                    offenders.append(f"{mod.__name__}.{name}({pname}={default!r})")
    assert offenders == []


def _is_a_value(default) -> bool:
    """Anything but "not supplied". None, a bool switch and an empty container are not
    deployments; a string, a number, a Path, a non-empty tuple all are. A dataclass
    field with a default_factory shows up as a sentinel here and is checked by
    `test_no_dataclass_field_defaults_to_a_deployment` instead."""
    if default is inspect.Parameter.empty or default is None or isinstance(default, bool):
        return False
    if default is dataclasses._HAS_DEFAULT_FACTORY:
        return False
    if isinstance(default, (list, tuple, dict, set, frozenset)) and not default:
        return False
    return True


def test_no_dataclass_field_defaults_to_a_deployment():
    offenders = []
    for mod in _modules():
        for name, cls in inspect.getmembers(mod, dataclasses.is_dataclass):
            if getattr(cls, "__module__", None) != mod.__name__:
                continue
            for f in dataclasses.fields(cls):
                if not DEPLOYMENT_PARAM.search(f.name):
                    continue
                value = (f.default_factory() if f.default_factory is not dataclasses.MISSING
                         else f.default)
                if value is not dataclasses.MISSING and _is_a_value(value):
                    offenders.append(f"{mod.__name__}.{name}.{f.name}={value!r}")
    assert offenders == []


def test_the_walk_sees_classmethods_staticmethods_and_partials():
    import types
    mod = types.ModuleType("probe")

    def _impl(bucket):
        return bucket

    class Client:
        @classmethod
        def from_env(cls, api="https://fake.example.invalid"):
            return cls

        @staticmethod
        def make(host="h.example.invalid"):
            return host

    _impl.__module__ = Client.__module__ = "probe"
    Client.from_env.__func__.__module__ = Client.make.__module__ = "probe"
    mod._impl, mod.Client = _impl, Client
    mod.bound = functools.partial(_impl, bucket="fake-bucket")
    found = {pname for _, fn in _callables(mod) for pname, d in _defaults(fn)
             if _is_a_value(d)}
    assert {"api", "host", "bucket"} <= found


def test_the_value_predicate_catches_the_shapes_that_matter():
    from pathlib import Path
    for v in ("https://x", 5432, Path("/opt/x"), ("h",), ["h"]):
        assert _is_a_value(v), v
    for v in (None, True, False, (), [], inspect.Parameter.empty,
              dataclasses._HAS_DEFAULT_FACTORY):
        assert not _is_a_value(v), v


def test_the_pattern_catches_the_spellings_that_matter():
    for name in ("api", "host", "db", "collection_id", "collection", "bucket",
                 "bucket_url", "remote_prelude", "env_file", "pg_user", "pghost",
                 "dsn", "pg_dsn", "conninfo", "hostname", "endpoint", "uri", "server",
                 "apiurl"):
        assert DEPLOYMENT_PARAM.search(name), name
    for name in ("page_size", "chunk", "workers", "session", "path", "ids_only"):
        assert not DEPLOYMENT_PARAM.search(name), name


def test_the_structural_check_sees_modules():
    """A walk that found nothing would pass the check above vacuously."""
    assert {m.__name__ for m in _modules()} >= {"stacs.verify", "stacs.catalogue"}


def _deployment_hits(name: str, text: str) -> list[str]:
    """Deployment names in one source file, with crate's versioned schema URLs removed first.

    Returned rather than asserted so the carve-out can be shown admitting nothing else.
    """
    stripped = CRATE_SCHEMA_URL.sub("", text.lower())
    return [f"{name}: {s}" for s in KNOWN_DEPLOYMENT_STRINGS if s in stripped]


def test_no_source_file_names_a_deployment():
    src = Path(stacs.__file__).parent
    files = sorted(src.rglob("*.py"))
    assert files, "no source files found: this check would pass on anything"
    hits = [h for f in files for h in _deployment_hits(f.name, f.read_text())]
    assert hits == []


@pytest.mark.parametrize("text", [
    # The two the carve-out exists for.
    "SCHEMA_URL = 'https://newgraphenvironment.github.io/crate/receipt/v1.0.0/schema.json'",
    "URL = 'https://newgraphenvironment.github.io/crate/stac/receipt/v1.0.0/schema.json'",
])
def test_the_schema_carve_out_admits_a_versioned_crate_schema(text):
    assert _deployment_hits("probe.py", text) == []


@pytest.mark.parametrize("text", [
    "u = 'https://newgraphenvironment.github.io/crate/'",
    "u = 'https://newgraphenvironment.github.io/stac_dem_bc/collection.json'",
    "u = 'https://newgraphenvironment.github.io/crate/receipt/latest/schema.json'",
    "u = 'https://newgraphenvironment.github.io/crate/receipt/v1.0.0/other.json'",
    "bucket = 'newgraphenvironment-public'",
    "api = 'https://stacs.newgraphenvironment.com'",
], ids=["host only", "another path", "unversioned", "another file", "a bucket", "a host"])
def test_the_schema_carve_out_admits_nothing_else(text):
    """The carve-out is a regex substitution over source text, which is exactly the shape that
    quietly widens. Shown refusing every near miss."""
    assert _deployment_hits("probe.py", text) != [], text


def test_the_carve_out_still_sees_the_other_deployment_names():
    """Stripping one URL must not stop the scan: a file carrying both the schema URL and a
    real bucket is still a failure."""
    text = ("S = 'https://newgraphenvironment.github.io/crate/receipt/v1.0.0/schema.json'\n"
            "B = 'https://s3.amazonaws.com/some-bucket'\n")
    assert _deployment_hits("probe.py", text) == ["probe.py: amazonaws.com"]
