"""stacs is a public tool: the host, database, API, bucket and collection are always the
caller's. Two checks, because either alone has a hole.

- Structural: no public function gives a deployment parameter a default. A default is
  exactly the thing that goes unnoticed when a caller forgets to pass the value.
- Textual: no source file names a deployment this package was extracted from. The
  structural check cannot see a module constant used inside a function body.
"""

import importlib
import inspect
import pkgutil
import re
from pathlib import Path

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


def _modules():
    for info in pkgutil.walk_packages(stacs.__path__, prefix="stacs."):
        yield importlib.import_module(info.name)


def _callables(mod):
    """Module functions, and every class's constructor and methods -- a dataclass
    field default reaches callers through the generated __init__."""
    for name, obj in inspect.getmembers(mod):
        if getattr(obj, "__module__", None) != mod.__name__:
            continue
        if inspect.isfunction(obj):
            yield name, obj
        elif inspect.isclass(obj):
            for mname, m in inspect.getmembers(obj, inspect.isfunction):
                yield f"{name}.{mname}", m


def test_no_deployment_parameter_has_a_default():
    offenders = []
    for mod in _modules():
        for name, fn in _callables(mod):
            for p in inspect.signature(fn).parameters.values():
                if (DEPLOYMENT_PARAM.search(p.name)
                        and p.default not in (p.empty, None)):
                    offenders.append(f"{mod.__name__}.{name}({p.name}={p.default!r})")
    assert offenders == []


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


def test_no_source_file_names_a_deployment():
    src = Path(stacs.__file__).parent
    files = sorted(src.rglob("*.py"))
    assert files, "no source files found: this check would pass on anything"
    hits = [f"{f.name}: {s}" for f in files for s in KNOWN_DEPLOYMENT_STRINGS
            if s in f.read_text().lower()]
    assert hits == []
