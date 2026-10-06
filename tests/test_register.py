"""End-to-end tests for stacs.register, with no network.

Ported from stac_dem_bc's tests/test_catalogue_register.py, run in-process.

How it runs offline:
  - collection.json and every item link are `file://` URLs
  - a stub STAC API on localhost answers POST /search and GET /collections/<id>
  - `ssh` is a stub on PATH. The probe (`... HOST true`) answers $SSH_PROBE_RC; any
    other call RUNS the remote script locally, as a remote login shell would, so the
    receiving-side line count, the PG* exports and the trap are exercised for real
  - the remote launcher is a fake `pypgstac` that logs `<kind> <lines> db=<PGDATABASE>
    pw=<set|unset>` and exits $FAKE_PYPGSTAC_RC
  - conftest.py refuses every lookup and connection outside loopback
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from stacs import register as reg

COLL = "any-collection"
ASSETS = ("data", "thumbnail")

SSH_STUB = r"""#!/bin/bash
last="${@: -1}"
if [ "$last" = "true" ]; then exit "${SSH_PROBE_RC:-0}"; fi
echo "$last" >> "$SSH_CMDS"
if [ -n "${SSH_SILENT_SUCCESS:-}" ]; then cat > /dev/null; exit 0; fi
if [ -n "${SSH_TRUNCATE:-}" ]; then
  sed '$d' | /bin/sh -c "$last"
else
  /bin/sh -c "$last"
fi
"""

FAKE_PYPGSTAC = r"""#!/bin/bash
# fake_pypgstac load <kind> <file> --method upsert
[ "$1" = "load" ] && [ "$4" = "--method" ] && [ "$5" = "upsert" ] || { echo "bad args: $*" >&2; exit 2; }
n=$(wc -l < "$3" | tr -d ' ')
if [ -n "${FAKE_PYPGSTAC_SAY:-}" ]; then echo "$FAKE_PYPGSTAC_SAY"; fi
head=$(head -c 12 "$3" | tr -d ' \n')
echo "$2 $n db=${PGDATABASE:-} pw=${PGPASSWORD:+set} head=$head" >> "$SSH_LOG"
exit "${FAKE_PYPGSTAC_RC:-0}"
"""


def _item(item_id, collection=COLL, assets=ASSETS):
    return {"type": "Feature", "stac_version": "1.1.0", "id": item_id,
            "collection": collection, "geometry": None, "properties": {},
            "links": [], "assets": {k: {"href": f"https://example.invalid/{k}"}
                                    for k in assets}}


def _collection(collection_id=COLL, links=()):
    return {"type": "Collection", "id": collection_id, "stac_version": "1.1.0",
            "description": "fixture", "license": "proprietary",
            "extent": {}, "links": list(links)}


# =============================================================================
# Harness
# =============================================================================

class _StubAPI:
    def __init__(self):
        self.items = {}
        self.collection = None
        self.searches = []
        self.on_load = None      # fn(api), run once after a collection load is logged
        self.load_log = None
        self.fail = {}           # path -> HTTP status to answer instead

    def sync(self):
        if self.on_load and self.load_log and self.load_log.exists() and \
                "collections" in self.load_log.read_text():
            fn, self.on_load = self.on_load, None
            fn(self)


def _handler(api):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, payload):
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            api.sync()
            if self.path in api.fail:
                self._send(api.fail[self.path], {"code": "ServerError"})
                return
            if self.path == "/collections":
                self._send(200, {"collections": []})
                return
            prefix = "/collections/"
            if self.path.startswith(prefix) and "/" not in self.path[len(prefix):]:
                c = api.collection
                if c is not None and c["id"] == self.path[len(prefix):]:
                    self._send(200, {**c, "links": [{"rel": "self", "href": "x"}]})
                    return
            self._send(404, {"code": "NotFoundError"})

        def do_POST(self):
            if self.path != "/search":
                self._send(404, {})
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            api.sync()
            if self.path in api.fail:
                self._send(api.fail[self.path], {"code": "ServerError"})
                return
            api.searches.append(body)
            docs = [d for d in api.items.values()
                    if d.get("collection") in body.get("collections", [])]
            if "ids" in body:
                docs = [d for d in docs if d["id"] in set(body["ids"])]
            docs.sort(key=lambda d: d["id"])
            limit = body.get("limit", 10)
            start = int(body.get("token") or 0)
            page = docs[start:start + limit]
            if body.get("fields", {}).get("include") == ["id"]:
                page = [{"id": d["id"]} for d in page]
            else:
                page = [{**d, "links": [{"rel": "self", "href": "x"}]} for d in page]
            links = [{"rel": "self", "href": "x"}]
            if start + limit < len(docs):
                links.append({"rel": "next", "body": {"token": str(start + limit)}})
            self._send(200, {"type": "FeatureCollection", "features": page,
                             "links": links})
    return H


@pytest.fixture
def api():
    a = _StubAPI()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(a))
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    a.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield a
    server.shutdown()
    server.server_close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Stubs on PATH. The network is already loopback-only (conftest.py)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("ssh", SSH_STUB), ("fake_pypgstac", FAKE_PYPGSTAC)):
        p = bindir / name
        p.write_text(body)
        p.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("SSH_LOG", str(tmp_path / "loads.log"))
    monkeypatch.setenv("SSH_CMDS", str(tmp_path / "ssh_cmds.log"))
    for k in ("SSH_PROBE_RC", "SSH_TRUNCATE", "SSH_SILENT_SUCCESS", "FAKE_PYPGSTAC_RC",
              "FAKE_PYPGSTAC_SAY"):
        monkeypatch.delenv(k, raising=False)
    # Set for every test, so a test aimed at something else cannot pass because the
    # password check refused first.
    monkeypatch.setenv("STACS_TEST_PW", "not-a-real-password")
    return tmp_path


def _publish(tmp_path, items, collection_id=COLL, before=None):
    bucket = tmp_path / "bucket"
    bucket.mkdir(exist_ok=True)
    links = []
    for doc in items:
        p = bucket / f"{doc['id']}.json"
        p.write_text(json.dumps(doc))
        links.append({"rel": "item", "href": p.as_uri(),
                      "type": "application/json"})
    (bucket / "collection.json").write_text(json.dumps(_collection(collection_id, links)))
    if before is not None:
        before(bucket)
    return bucket


def _transport(**kw):
    t = dict(host="nobody@stub.invalid", db="stacdb", pypgstac=["fake_pypgstac"],
             password_env="STACS_TEST_PW")
    t.update(kw)
    return reg.Transport(**t)


class Run:
    def __init__(self, rc, out, err, tmp_path):
        self.rc, self.out, self.err = rc, out, err
        self.all = out + err
        log = tmp_path / "loads.log"
        self.loads = [] if not log.exists() else [
            tuple(line.split()) for line in log.read_text().splitlines()]
        cmds = tmp_path / "ssh_cmds.log"
        self.writes = 0 if not cmds.exists() else sum(
            1 for line in cmds.read_text().splitlines() if line.startswith("bash -c"))


def _run(tmp_path, mode, api_url="http://127.0.0.1:9", items=(), collection_id=COLL,
         before=None, transport=True, ids_file=None, dryrun=False, out_dir=None,
         monkeypatch=None, **target):
    bucket = _publish(tmp_path, items, collection_id, before)
    out, err = [], []
    target.setdefault("fetch_workers", 4)
    t = reg.Target(api=api_url, collection_id=target.pop("expect_id", collection_id),
                   bucket_url=bucket.as_uri(),
                   transport=_transport() if transport is True else transport,
                   **target)
    rc = reg.run(t, mode, ids_file=ids_file, dryrun=dryrun, out_dir=out_dir,
                 log=lambda m: out.append(str(m)), warn=lambda m: err.append(str(m)))
    return Run(rc, "\n".join(out), "\n".join(err), tmp_path)


def _in_sync(api, items, collection_id=COLL):
    api.collection = _collection(collection_id)
    api.items = {d["id"]: json.loads(json.dumps(d)) for d in items}


def _items(n=3):
    return [_item(f"a{i}") for i in range(n)]


# =============================================================================
# Startup and the published set
# =============================================================================

def test_the_asset_policy_is_said_out_loud_at_startup(env):
    """Off is said out loud, or an unaudited run reads as a checked pass."""
    r = _run(env, "all", items=_items(1), dryrun=True)
    assert r.rc == 0, r.all
    assert "asset audit: none" in r.out
    d = env / "declared"
    d.mkdir()
    r = _run(d, "all", items=_items(1), dryrun=True, require_asset="data",
             forbid_assets=["legacy"])
    assert "asset audit: require=data forbid=legacy" in r.out


def test_a_collection_id_mismatch_is_refused_before_any_fetch(env):
    r = _run(env, "all", items=_items(2), expect_id="other-collection")
    assert r.rc == 1
    assert "collection id mismatch" in r.err
    assert "fetching 2 item" not in r.out and r.writes == 0


@pytest.mark.parametrize("links, match", [
    ([], "no item links"),
    ([{"rel": "child", "href": "sub/catalog.json"}], "child link"),
])
def test_a_published_collection_that_would_omit_items_is_refused(env, links, match):
    def rewrite(bucket):
        (bucket / "collection.json").write_text(json.dumps(_collection(COLL, links)))
    r = _run(env, "verify", items=[], before=rewrite)
    assert r.rc == 1 and match in r.err, r.all
    assert r.writes == 0


def test_an_unreadable_collection_json_is_refused(env):
    r = _run(env, "verify", items=_items(1),
             before=lambda b: (b / "collection.json").write_text("{trunc"))
    assert r.rc == 1 and "could not read" in r.err


def test_relative_item_hrefs_resolve_against_the_collection(env, api):
    items = _items(2)
    _in_sync(api, items)

    def relative(bucket):
        c = json.loads((bucket / "collection.json").read_text())
        for link in c["links"]:
            link["href"] = "./" + link["href"].rsplit("/", 1)[-1]
        (bucket / "collection.json").write_text(json.dumps(c))

    r = _run(env, "verify", api.url, items, before=relative)
    assert r.rc == 0, r.all
    assert "IN SYNC" in r.out


# =============================================================================
# ids mode input
# =============================================================================

def test_ids_mode_normalises_blank_lines_and_duplicates(env):
    ids = env / "ids.txt"
    ids.write_text("a1\n\n  \na1\na0")      # no trailing newline, blank, duplicate
    r = _run(env, "ids", items=_items(3), ids_file=ids, dryrun=True)
    assert r.rc == 0, r.all
    assert "to register: 2" in r.out


@pytest.mark.parametrize("content", [None, "", "\n \n"])
def test_ids_mode_refuses_a_missing_or_empty_file(env, content):
    ids = env / "ids.txt"
    if content is not None:
        ids.write_text(content)
    r = _run(env, "ids", items=_items(1), ids_file=ids, dryrun=True)
    assert r.rc == 1 and ("missing or empty" in r.err or "no ids" in r.err), r.all


def test_ids_mode_refuses_an_id_with_no_published_link(env):
    ids = env / "ids.txt"
    ids.write_text("a0\nnope\n")
    r = _run(env, "ids", items=_items(1), ids_file=ids)
    assert r.rc == 1 and "no item link" in r.err and "'nope'" in r.err
    assert r.writes == 0


# =============================================================================
# Transport
# =============================================================================

@pytest.mark.parametrize("kw, match", [
    (dict(host="-oProxyCommand=touch /tmp/x"), "invalid ssh host"),
    (dict(host=""), "invalid ssh host"),
    (dict(db="stac; rm -rf /"), "suspicious database name"),
    (dict(password_env="PW=secret"), "must name a variable"),
    (dict(pg_port=0), "invalid pg_port"),
    (dict(pypgstac=[]), "list of words"),
])
def test_a_transport_value_that_could_inject_is_refused_before_anything(env, kw, match):
    r = _run(env, "all", items=_items(1), transport=_transport(**kw))
    assert r.rc == 1 and match in r.err, r.all
    assert "fetching" not in r.out and r.writes == 0


def test_a_writing_mode_needs_a_transport(env):
    r = _run(env, "drift", items=_items(1), transport=None)
    assert r.rc == 1 and "no transport" in r.err


def test_an_unreachable_host_is_refused_before_the_fetch(env, api, monkeypatch):
    monkeypatch.setenv("SSH_PROBE_RC", "255")
    r = _run(env, "all", api.url, items=_items(2))
    assert r.rc == 1 and "cannot reach" in r.err
    assert "fetching 2 item" not in r.out and r.writes == 0


def test_the_remote_script_loads_with_the_validated_db_and_the_password_by_name(env, api):
    """The password reaches pypgstac through PGPASSWORD, expanded on the host from a
    variable NAME; the value itself is in no ssh argument."""
    items = _items(2)
    _in_sync(api, items)
    api.items.clear()
    r = _run(env, "all", api.url, items)
    assert ("collections", "1", "db=stacdb", "pw=set") in [l[:4] for l in r.loads], r.all
    cmds = (env / "ssh_cmds.log").read_text()
    assert "not-a-real-password" not in cmds
    assert "STACS_TEST_PW" in cmds


def test_an_unset_password_variable_fails_on_the_host_and_loads_nothing(env, api, monkeypatch):
    monkeypatch.delenv("STACS_TEST_PW")
    items = _items(1)
    r = _run(env, "all", api.url, items,
             transport=_transport(password_env="STACS_NOT_SET_ANYWHERE"))
    assert r.rc == 1 and "failed on" in r.err
    assert r.loads == []


def test_a_truncated_transfer_is_refused_on_the_receiving_side(env, api, monkeypatch):
    """The sender cannot see a short transfer; only the receiver counts lines."""
    monkeypatch.setenv("SSH_TRUNCATE", "1")
    items = _items(3)
    r = _run(env, "all", api.url, items)
    assert r.rc == 1, r.all
    assert r.loads == [], "pypgstac must not run on a short file"


def test_a_remote_that_exits_0_without_loading_is_a_failure(env, monkeypatch):
    """Whatever made the remote exit 0 -- bash 3.2's EXIT-trap status, a wrapper -- a
    load that did not confirm itself did not happen."""
    monkeypatch.setenv("SSH_SILENT_SUCCESS", "1")
    p = env / "c.json"
    p.write_text(json.dumps(_collection()))
    with pytest.raises(reg.RegisterError, match="without confirming"):
        reg.load(_transport(), "collections", [str(p)])


@pytest.mark.parametrize("shell", ["/bin/bash", "bash"])
def test_a_missing_env_file_fails_the_load(env, monkeypatch, shell):
    """On bash 3.2 a failed `.` under an EXIT trap exits 0. Run under the system bash
    (3.2 on macOS) and whichever bash is first on PATH."""
    stub = env / "bin" / "ssh"
    stub.write_text(stub.read_text().replace('/bin/sh -c "$last"',
                                             f'{shell} -c "$last"'))
    p = env / "c.json"
    p.write_text(json.dumps(_collection()))
    with pytest.raises(reg.RegisterError):
        reg.load(_transport(env_file=str(env / "no_such.env")), "collections", [str(p)])
    assert not (env / "loads.log").exists(), "pypgstac ran"


def test_the_success_flag_alone_catches_the_bash_3_2_exit(env):
    """The shell layer on its own: with the sentinel check bypassed, the remote still
    exits non-zero on a failed `.` under /bin/bash."""
    import subprocess
    script = reg.remote_script(_transport(env_file=str(env / "no_such.env")),
                               "collections", 1)
    r = subprocess.run(["/bin/bash", "-c", script], input="{}\n", text=True,
                       capture_output=True)
    assert r.returncode != 0 and reg.LOADED_MARK not in r.stdout


def _env_file(env, body):
    p = env / "host.env"
    p.write_text(body)
    return str(p)


@pytest.mark.parametrize("body", ["set +e\n", "set +euo pipefail\n"])
def test_an_env_file_that_turns_errexit_off_cannot_hide_a_failed_load(env, monkeypatch,
                                                                       body):
    """The env file is the caller's code. It runs in the subshell with the load, under
    `set -euo pipefail` reasserted after it, so a failed pypgstac still fails."""
    monkeypatch.setenv("FAKE_PYPGSTAC_RC", "1")
    p = env / "c.json"
    p.write_text(json.dumps(_collection()))
    with pytest.raises(reg.RegisterError, match="failed on"):
        reg.load(_transport(env_file=_env_file(env, body)), "collections", [str(p)])


def test_options_are_reasserted_after_the_env_file(env):
    """An env file's `set +e` must not let a failed step before the load (a `cd` into a
    directory that is not there) run pypgstac from the wrong place."""
    p = env / "c.json"
    p.write_text(json.dumps(_collection()))
    with pytest.raises(reg.RegisterError):
        reg.load(_transport(env_file=_env_file(env, "set +e\n"),
                            workdir=str(env / "no_such_dir")), "collections", [str(p)])
    assert not (env / "loads.log").exists()


def test_an_env_file_that_exits_0_cannot_report_a_load(env):
    p = env / "c.json"
    p.write_text(json.dumps(_collection()))
    with pytest.raises(reg.RegisterError):
        reg.load(_transport(env_file=_env_file(env, "exit 0\n")), "collections", [str(p)])
    assert not (env / "loads.log").exists()


def test_an_env_file_cannot_redirect_the_payload(env):
    """Variables the script keeps are namespaced and readonly: an env file assigning
    them neither loads another file nor deletes it."""
    victim = env / "victim.txt"
    victim.write_text("keep me\n")
    body = (f"t={victim}\nn=1\nok=1\n"
            f"__stacs_tmp={victim} 2>/dev/null || true\n")
    p = env / "c.json"
    p.write_text(json.dumps(_collection()))
    try:
        reg.load(_transport(env_file=_env_file(env, body)), "collections", [str(p)])
    except reg.RegisterError:
        pass
    assert victim.read_text() == "keep me\n"
    log = (env / "loads.log").read_text() if (env / "loads.log").exists() else ""
    # Refused (the readonly assignment fails under -e) or the real payload loaded --
    # never the env file's choice of file.
    assert "head=keepme" not in log, "pypgstac loaded the env file's file"


def test_a_failed_items_load_does_not_claim_nothing_was_committed(env, api, monkeypatch):
    """pypgstac commits items per chunk, so the message must not promise a rollback."""
    items = _items(2)
    calls = {"n": 0}
    real_run = reg.subprocess.run

    def fail_items(cmd, **kw):
        if "load items" in cmd[-1]:
            monkeypatch.setenv("FAKE_PYPGSTAC_RC", "1")
        return real_run(cmd, **kw)

    monkeypatch.setattr(reg.subprocess, "run", fail_items)
    r = _run(env, "all", api.url, items)
    assert r.rc == 1
    assert "may have been committed" in r.err and "re-running is safe" in r.err


def test_a_read_back_failure_returns_1_not_a_traceback(env, api, monkeypatch):
    items = _items(2)

    def boom(*a, **k):
        raise RuntimeError("API request failed after 3 attempts: boom")

    monkeypatch.setattr(reg, "bodies_serving", boom)
    api.load_log, api.on_load = env / "loads.log", lambda a: _in_sync(a, items)
    ids = env / "ids.txt"
    ids.write_text("a0\n")
    r = _run(env, "ids", api.url, items, ids_file=ids)
    assert r.rc == 1 and "could not read back" in r.err


def test_a_failed_load_reports_and_writes_no_items(env, api, monkeypatch):
    monkeypatch.setenv("FAKE_PYPGSTAC_RC", "1")
    r = _run(env, "all", api.url, _items(2))
    assert r.rc == 1 and "failed on" in r.err
    assert [l[0] for l in r.loads] == ["collections"], "items after a failed collection"


def test_remote_script_quotes_every_caller_value():
    t = _transport(env_file="/etc/my env", workdir="/opt/a b", path_prepend="/x y/bin",
                   pg_host="db.example.invalid", pg_port=5433, pg_user="u",
                   pypgstac=["uv", "run", "pypgstac"])
    s = reg.remote_script(t, "items", 3)
    assert ". '/etc/my env'" in s and "cd '/opt/a b'" in s
    assert "export PATH='/x y/bin':\"$PATH\"" in s
    assert "export PGDATABASE=stacdb" in s and "export PGPORT=5433" in s
    assert 'uv run pypgstac load items "$__stacs_tmp" --method upsert || exit 1' in s
    # PG* after the env file, so the validated db is the one loaded.
    assert s.index("export PGDATABASE") > s.index(". '/etc/my env'")


def test_load_with_nothing_to_load_says_so_and_sends_nothing(env):
    msgs = []
    assert reg.load(_transport(), "items", [], log=msgs.append) == 0
    assert "nothing to register" in msgs[0]


# =============================================================================
# Audit before any write; asset rules are declared
# =============================================================================

def test_a_mixed_population_is_refused_before_the_collection_upsert(env, api):
    items = [_item("a0"), _item("a1", collection="some-other-collection")]
    r = _run(env, "all", api.url, items)
    assert r.rc == 1 and "name another collection" in r.err, r.all
    assert r.writes == 0, "refused after a write -- the audit must run first"


@pytest.mark.parametrize("rules, bad_assets, match", [
    (dict(require_asset="thumbnail"), ("data",), "lack asset 'thumbnail'"),
    (dict(forbid_assets=["legacy"]), ("data", "legacy"), "retired asset key"),
])
def test_declared_asset_rules_refuse_before_any_write(env, api, rules, bad_assets, match):
    items = [_item("a0"), _item("a1", assets=bad_assets)]
    r = _run(env, "all", api.url, items, **rules)
    assert r.rc == 1 and match in r.err, r.all
    assert r.writes == 0


def test_a_body_naming_another_id_is_refused_before_any_write(env, api):
    """pgstac upserts by the body's OWN id, so a link a1.json serving a0's body would
    overwrite the registered a0."""
    items = _items(3)
    _in_sync(api, items)

    def swap(bucket):
        (bucket / "a1.json").write_text(json.dumps(items[0]))

    for mode in ("all", "drift"):
        d = env / mode
        d.mkdir()
        r = _run(d, mode, api.url, items, before=swap)
        assert r.rc == 1 and "names id 'a0'" in r.err, (mode, r.all)
        assert r.writes == 0, mode
    ids = env / "ids.txt"
    ids.write_text("a1\n")
    d = env / "ids"
    d.mkdir()
    r = _run(d, "ids", api.url, items, before=swap, ids_file=ids)
    assert r.rc == 1 and "names id 'a0'" in r.err and r.writes == 0


def test_a_duplicated_item_link_is_refused_before_any_fetch(env, api):
    items = _items(2)

    def dup(bucket):
        c = json.loads((bucket / "collection.json").read_text())
        c["links"].append(next(l for l in c["links"] if l["rel"] == "item"))
        (bucket / "collection.json").write_text(json.dumps(c))

    for mode in ("all", "drift", "verify"):
        d = env / mode
        d.mkdir()
        r = _run(d, mode, api.url, items, before=dup)
        assert r.rc == 1 and "more than once" in r.err, (mode, r.all)
        assert "fetching 2" not in r.out and r.writes == 0


# =============================================================================
# verify
# =============================================================================

def test_verify_reports_in_sync_when_bodies_match(env, api):
    """Control: without it, every "changed" assertion could pass on a comparison that
    never matches anything."""
    items = _items()
    _in_sync(api, items)
    r = _run(env, "verify", api.url, items, transport=None)
    assert r.rc == 0, r.all
    assert "IN SYNC: 3 published" in r.out
    assert r.writes == 0


def test_verify_reports_every_direction_and_writes_full_lists(env, api):
    items = _items(4)
    _in_sync(api, items)
    del api.items["a3"]                                   # missing
    api.items["a1"]["properties"] = {"stale": True}       # changed
    api.items["z"] = _item("z")                           # orphaned
    api.collection["description"] = "old"                 # collection changed
    out_dir = env / "report"
    r = _run(env, "verify", api.url, items, transport=None, out_dir=out_dir)
    assert r.rc == 1 and "IN SYNC" not in r.all
    for line in ("1 published item(s) are not registered",
                 "1 registered item(s) differ from the published body",
                 "1 registered item(s) are no longer published",
                 "collection body differs"):
        assert line in r.err, (line, r.all)
    assert (out_dir / "missing.txt").read_text() == "a3\n"
    assert (out_dir / "changed.txt").read_text() == "a1\n"
    assert (out_dir / "orphaned.txt").read_text() == "z\n"
    assert (out_dir / "collection_state.txt").read_text() == "changed\n"


def test_verify_reports_a_collection_that_is_not_registered(env, api):
    items = _items()
    _in_sync(api, items)
    api.collection = None
    r = _run(env, "verify", api.url, items, transport=None)
    assert r.rc == 1 and "collection is not registered" in r.err


def test_verify_fails_when_a_published_body_cannot_be_fetched(env, api, monkeypatch):
    """A body that cannot be read fails the run; it never compares as unchanged."""
    from stacs import catalogue
    monkeypatch.setattr(catalogue.time, "sleep", lambda s: None)
    items = _items()
    _in_sync(api, items)
    r = _run(env, "verify", api.url, items, transport=None,
             before=lambda b: (b / "a2.json").unlink())
    assert r.rc == 1 and "IN SYNC" not in r.all
    assert "fetched 2 of 3" in r.all, r.all


def test_an_id_with_spaces_and_parentheses_round_trips(env, api):
    items = [_item("a (2) b"), _item("plain")]
    _in_sync(api, items)
    api.items["a (2) b"]["properties"] = {"x": 1}

    def encode_spaces_only(bucket):
        c = json.loads((bucket / "collection.json").read_text())
        for link in c["links"]:
            stem = link["href"].rsplit("/", 1)[-1].replace("%28", "(").replace("%29", ")")
            link["href"] = bucket.as_uri() + "/" + stem
        (bucket / "collection.json").write_text(json.dumps(c))

    r = _run(env, "verify", api.url, items, transport=None, before=encode_spaces_only)
    assert r.rc == 1, r.all
    assert "a (2) b" in r.err and "1 registered item(s) differ" in r.err


# =============================================================================
# drift
# =============================================================================

def test_drift_dryrun_lists_a_changed_item_and_writes_nothing(env, api):
    items = _items()
    _in_sync(api, items)
    api.items["a0"]["assets"] = {}
    r = _run(env, "drift", api.url, items, dryrun=True)
    assert r.rc == 0, r.all
    assert "to register: 1" in r.out and "a0" in r.out
    assert r.writes == 0


def test_drift_in_sync_does_nothing(env, api):
    items = _items()
    _in_sync(api, items)
    r = _run(env, "drift", api.url, items)
    assert r.rc == 0 and "already in sync" in r.out, r.all
    assert r.writes == 0


def test_drift_loads_only_the_todo_bodies_and_fails_if_they_do_not_read_back(env, api):
    """drift fetches the WHOLE catalogue to compare it; the loader gets only the to-do
    set. The stub API does not take the load, so the post-register check must fail --
    the guard against a drift that re-registers forever without converging."""
    items = _items(4)
    _in_sync(api, items)
    del api.items["a3"]
    api.items["a0"]["properties"] = {"x": 1}
    r = _run(env, "drift", api.url, items)
    assert [l[:2] for l in r.loads] == [("collections", "1"), ("items", "2")], r.all
    assert r.rc == 1 and "DONE" not in r.out
    assert "not served" in r.err and "differs from the one sent" in r.err, r.all


def test_drift_upserts_a_changed_collection_with_no_item_changes(env, api):
    items = _items()
    _in_sync(api, items)
    api.collection["license"] = "CC-BY-4.0"

    def after(a):
        a.collection = _collection()

    api.load_log, api.on_load = env / "loads.log", after
    r = _run(env, "drift", api.url, items)
    assert "to register: 0" in r.out and "already in sync" not in r.out
    assert [l[:2] for l in r.loads] == [("collections", "1")], r.all
    assert r.rc == 0 and "DONE: 0 item(s)" in r.out


def test_drift_bootstraps_a_collection_the_api_has_never_seen(env, api):
    items = _items(3)

    def after(a):
        _in_sync(a, items)

    api.load_log, api.on_load = env / "loads.log", after
    r = _run(env, "drift", api.url, items)
    assert "to register: 3" in r.out, r.all
    assert [l[:2] for l in r.loads] == [("collections", "1"), ("items", "3")]
    assert r.rc == 0, r.all


def test_drift_rechecks_untouched_items_when_the_collection_changed(env, api):
    """pgstac serves items hydrated against their collection, so a collection upsert
    can change how items NOT in the to-do set read back."""
    items = _items(3)
    _in_sync(api, items)
    api.collection["license"] = "old-license"
    api.items["a0"]["properties"] = {"x": 1}

    def after(a):
        a.collection = _collection()
        a.items["a0"] = json.loads(json.dumps(items[0]))
        a.items["a2"]["properties"] = {"hydrated": "differently"}    # untouched

    api.load_log, api.on_load = env / "loads.log", after
    r = _run(env, "drift", api.url, items)
    assert [l[:2] for l in r.loads] == [("collections", "1"), ("items", "1")], r.all
    assert r.rc == 1 and "DONE" not in r.out
    assert "a2" in r.err


def test_drift_with_a_changed_collection_passes_when_items_read_back_unchanged(env, api):
    """Control for the test above: the full re-check is not merely always red."""
    items = _items(3)
    _in_sync(api, items)
    api.collection["license"] = "old-license"

    def after(a):
        a.collection = _collection()

    api.load_log, api.on_load = env / "loads.log", after
    r = _run(env, "drift", api.url, items)
    assert r.rc == 0, r.all
    assert "OK: every published item is served with the published body" in r.out


# =============================================================================
# all / ids end to end
# =============================================================================

def test_all_succeeds_end_to_end_when_the_api_serves_what_was_sent(env, api):
    """The positive path: writes succeed, the API serves the published bodies."""
    items = _items(3)

    def after(a):
        _in_sync(a, items)

    api.load_log, api.on_load = env / "loads.log", after
    r = _run(env, "all", api.url, items)
    assert r.rc == 0, r.all
    assert [l[:2] for l in r.loads] == [("collections", "1"), ("items", "3")]
    assert "OK: every published item is served with the published body" in r.out
    assert "DONE: 3 item(s)" in r.out


def test_all_dryrun_previews_and_touches_nothing(env, monkeypatch):
    monkeypatch.setenv("SSH_PROBE_RC", "255")     # a probe would fail the run
    r = _run(env, "all", items=_items(4), dryrun=True)
    assert r.rc == 0, r.all
    assert "to register: 4" in r.out and "[dryrun]" in r.out
    assert "fetching 4" not in r.out and r.writes == 0


def test_ids_registers_exactly_those_and_says_to_verify_after(env, api):
    items = _items(3)

    def after(a):
        _in_sync(a, items)

    api.load_log, api.on_load = env / "loads.log", after
    ids = env / "ids.txt"
    ids.write_text("a2\n")
    r = _run(env, "ids", api.url, items, ids_file=ids)
    assert r.rc == 0, r.all
    assert [l[:2] for l in r.loads] == [("collections", "1"), ("items", "1")]
    assert "run 'verify'" in r.out


# =============================================================================
# The harness itself
# =============================================================================

def test_the_fetcher_cannot_reach_the_network(env):
    """A harness bug that pointed a run at a real bucket must fail the fetch, not fetch
    100k items. Asserted on the reason, because a fake host would fail on DNS whether or
    not the guard were in effect."""
    from stacs.catalogue import fetch_bodies
    out = env / "net"
    out.mkdir()
    failed = fetch_bodies(["https://example.com/collection.json"], out, workers=1,
                          retries=1)
    assert failed == ["https://example.com/collection.json"]
    with pytest.raises(OSError, match="network disabled in tests"):
        import socket
        socket.getaddrinfo("example.com", 443)


@pytest.mark.parametrize("forbid", ["", ",", [""]])
def test_forbid_keys_that_parse_to_nothing_are_refused_before_anything(env, forbid):
    r = _run(env, "all", items=_items(1), forbid_assets=forbid)
    assert r.rc == 1 and "forbid_assets" in r.err
    assert "fetching" not in r.out


def test_an_empty_require_key_is_refused_before_anything(env):
    r = _run(env, "all", items=_items(1), require_asset="")
    assert r.rc == 1 and "require_asset" in r.err
    assert "fetching" not in r.out


# =============================================================================
# The pieces, on their own
# =============================================================================

def _write_item(tmp_path, name, collection=COLL):
    doc = {"id": name, "type": "Feature", "collection": collection,
           "assets": {"data": {"href": f"https://example.invalid/{name}.tif"}}}
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(doc, indent=2))          # pretty, to prove compaction
    return p


def test_ndjson_write_one_compact_line_per_item(tmp_path):
    paths = [_write_item(tmp_path, n) for n in ("a", "b", "c")]
    out = tmp_path / "items.ndjson"
    assert reg.ndjson_write([str(p) for p in paths], out) == 3
    lines = out.read_text().splitlines()
    assert len(lines) == 3 and all(json.loads(l)["collection"] == COLL for l in lines)


def test_ndjson_write_skips_blank_lines_and_handles_spaces(tmp_path):
    p = _write_item(tmp_path, "a (2)")
    out = tmp_path / "items.ndjson"
    assert reg.ndjson_write([str(p) + "\n", "", "\n"], out) == 1
    assert json.loads(out.read_text())["id"] == "a (2)"


def test_ndjson_write_raises_on_a_missing_file(tmp_path):
    """A silently-skipped input is a silently-unregistered item."""
    with pytest.raises(FileNotFoundError):
        reg.ndjson_write([str(tmp_path / "nope.json")], tmp_path / "out.ndjson")


def test_ndjson_write_refuses_an_item_from_another_collection(tmp_path):
    """pgstac routes each item by its own `collection` field, so a stale body upserts
    into the PREVIOUS collection successfully, with no error anywhere."""
    paths = [str(_write_item(tmp_path, "good")),
             str(_write_item(tmp_path, "stale", collection="old-collection"))]
    with pytest.raises(reg.RegisterError, match="old-collection"):
        reg.ndjson_write(paths, tmp_path / "out.ndjson", expect_collection=COLL)
    assert reg.ndjson_write(paths, tmp_path / "out2.ndjson") == 2   # opt-in


def test_load_items_refuses_another_collection_before_sending(env):
    p = _write_item(env, "stale", collection="old-collection")
    with pytest.raises(reg.RegisterError, match="old-collection"):
        reg.load(_transport(), "items", [str(p)], expect_collection=COLL)
    assert not (env / "ssh_cmds.log").exists()


def test_load_refuses_more_than_one_collection(env):
    a, b = _write_item(env, "a"), _write_item(env, "b")
    with pytest.raises(reg.RegisterError, match="one collection per load"):
        reg.load(_transport(), "collections", [str(a), str(b)])


def test_load_refuses_when_the_payload_does_not_match_the_paths(env, monkeypatch):
    """Unreachable through ndjson_write today; pinned so a change there cannot make the
    count and the payload disagree silently."""
    p = _write_item(env, "a")
    monkeypatch.setattr(reg, "ndjson_write", lambda paths, out, expect: 0)
    with pytest.raises(reg.RegisterError, match="refusing to load"):
        reg.load(_transport(), "items", [str(p)])
    assert not (env / "ssh_cmds.log").exists()


def test_a_collection_that_does_not_read_back_after_the_write_fails_the_run(env, api):
    """The write succeeded, but the API still serves the old collection body."""
    items = _items(2)
    _in_sync(api, items)
    api.collection["license"] = "old-license"          # and nothing updates it
    r = _run(env, "drift", api.url, items)
    assert [l[:2] for l in r.loads] == [("collections", "1")], r.all
    assert r.rc == 1 and "the collection reads 'changed'" in r.err
    assert "DONE" not in r.out



@pytest.mark.parametrize("kw, match", [
    (dict(chunk=0), "chunk"), (dict(chunk=-1), "chunk"), (dict(chunk="500"), "chunk"),
    (dict(page_size=0), "page_size"), (dict(fetch_workers=True), "fetch_workers"),
])
def test_a_tuning_value_that_would_fail_after_the_write_is_refused_before_it(env, kw,
                                                                            match):
    """`chunk` is first used in the read-back AFTER the upsert, so it is checked first."""
    r = _run(env, "all", items=_items(1), **kw)
    assert r.rc == 1 and match in r.err
    assert "fetching" not in r.out and r.writes == 0



def test_an_api_that_does_not_answer_is_refused_before_any_write(env, monkeypatch):
    """`all` writes before it ever compares, so the API it will verify against is read
    first: a wrong URL would otherwise surface only after the upsert."""
    from stacs import verify
    monkeypatch.setattr(verify.time, "sleep", lambda s: None)
    r = _run(env, "all", "http://127.0.0.1:9", items=_items(2))
    assert r.rc == 1 and "does not answer" in r.err
    assert r.writes == 0 and "fetching 2" not in r.out



# =============================================================================
# Paths the end-to-end tests above do not reach
# =============================================================================

@pytest.fixture
def no_retry_sleep(monkeypatch):
    from stacs import verify
    monkeypatch.setattr(verify.time, "sleep", lambda s: None)


def test_a_search_that_keeps_failing_is_a_refusal_not_a_traceback(env, api,
                                                                   no_retry_sleep):
    items = _items(2)
    _in_sync(api, items)
    api.fail["/search"] = 503
    r = _run(env, "verify", api.url, items, transport=None)
    assert r.rc == 1 and r.err.startswith("ERROR:") and "failed after" in r.err
    assert "IN SYNC" not in r.out


def test_a_collection_read_that_keeps_failing_is_a_refusal(env, api, no_retry_sleep):
    items = _items(2)
    _in_sync(api, items)
    api.fail["/collections/any-collection"] = 503
    r = _run(env, "verify", api.url, items, transport=None)
    assert r.rc == 1 and "could not compare the registered collection" in r.err


def test_an_unexpected_collection_state_is_refused(env, api, monkeypatch):
    items = _items(1)
    _in_sync(api, items)
    monkeypatch.setattr(reg, "collection_state", lambda *a, **k: "perhaps")
    r = _run(env, "verify", api.url, items, transport=None)
    assert r.rc == 1 and "unexpected collection state 'perhaps'" in r.err


def test_a_collection_json_that_is_not_an_object_is_refused(env):
    r = _run(env, "verify", items=_items(1),
             before=lambda b: (b / "collection.json").write_text("[]"))
    assert r.rc == 1 and "is not a JSON object" in r.err


@pytest.mark.parametrize("kw, match", [
    (dict(api=""), "api must be"),
    (dict(collection_id="  "), "collection_id must be"),
    (dict(bucket_url=None), "bucket_url must be"),
])
def test_target_check_refuses_empty_catalogue_settings(kw, match):
    t = reg.Target(**{**dict(api="http://127.0.0.1:9", collection_id="c",
                             bucket_url="file:///x"), **kw})
    with pytest.raises(reg.RegisterError, match=match):
        t.check()


@pytest.mark.parametrize("mode, ids_file, match", [
    ("bogus", None, "unknown mode 'bogus'"),
    ("ids", None, "needs an ids file"),
])
def test_run_refuses_a_bad_mode_when_called_directly(env, mode, ids_file, match):
    r = _run(env, mode, items=_items(1), ids_file=ids_file)
    assert r.rc == 1 and match in r.err and "fetching" not in r.out


def test_remote_script_refuses_an_unknown_kind():
    with pytest.raises(ValueError, match="unknown load kind"):
        reg.remote_script(_transport(), "catalogs", 1)


def test_the_hosts_own_output_is_relayed_and_the_mark_is_not(env, monkeypatch):
    monkeypatch.setenv("FAKE_PYPGSTAC_SAY", "pypgstac: 1 row upserted")
    p = env / "c.json"
    p.write_text(json.dumps(_collection()))
    said = []
    reg.load(_transport(), "collections", [str(p)], log=said.append)
    assert "pypgstac: 1 row upserted" in said
    assert not any(line.startswith(reg.LOADED_MARK) for line in said)
    assert "loaded   : 1 collections" in said
