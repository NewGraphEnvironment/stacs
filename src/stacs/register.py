"""Register a published catalogue into pgstac, and prove it arrived.

Upsert only, collection before items, and nothing in this module deletes.
`pgstac.items.collection` is `ON DELETE CASCADE`: dropping a collection row destroys every
item in it, which is how a delete-then-load once took a catalogue offline. A load that
fails here leaves the previous rows serving: an upsert never removes one.

Writes go over ssh to the STAC host, which runs `pypgstac load` there: the database
password never leaves the host, and a STAC API without the transaction extension cannot
be written through anyway. The host, database, environment file and launcher are all the
caller's (`Transport`); nothing here names a deployment.

Modes:

- `verify`: compare every published body with what the API serves and report missing,
  changed and orphaned items and the collection's state. Writes nothing.
- `drift`: register what the API is missing or serves with a different body. Stateless:
  it asks the API what it has, so a skipped run is picked up by the next one.
- `all`: register every published item.
- `ids`: register exactly the ids in a file.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from stacs.catalogue import (_read_url, collection_item_links, fetch_bodies, fetch_key,
                             published_digests)
from stacs.validate import audit_items, parse_asset_keys
from stacs.verify import (PAGE_SIZE, bodies_registered, bodies_serving, collection_state,
                          content_diff)

MODES = ("verify", "drift", "all", "ids")

# The remote script's last act. `load` requires this exact line on stdout, so a remote
# shell that exits 0 without loading -- whatever the reason -- reads as a failure.
LOADED_MARK = "STACS_LOADED"

# Interpolated into a remote shell, so restricted rather than quoted alone.
_DB_NAME = re.compile(r"[A-Za-z0-9_]+")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class RegisterError(Exception):
    """A refusal. Raised before anything is written wherever the check allows."""


@dataclass
class Transport:
    """How to reach pgstac: ssh to `host`, then `pypgstac load` there.

    Every value is the caller's. `password_env` is the NAME of a variable the host's
    environment (usually `env_file`) defines, never a password: the remote script is
    an ssh argument, and argv is visible in `ps` on both ends.
    """
    host: str
    db: str
    env_file: str | None = None
    workdir: str | None = None
    path_prepend: str | None = None
    pg_host: str | None = None
    pg_port: int | None = None
    pg_user: str | None = None
    password_env: str | None = None
    pypgstac: list[str] = field(default_factory=lambda: ["pypgstac"])

    def check(self) -> None:
        # Types first: a value from a config file can be anything TOML can say.
        for name in ("host", "db"):
            if not isinstance(getattr(self, name), str):
                raise RegisterError(f"{name} must be a string, got {getattr(self, name)!r}")
        for name in ("env_file", "workdir", "path_prepend", "pg_host", "pg_user",
                     "password_env"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise RegisterError(f"{name} must be a non-empty string, got {value!r}")
        if not self.host or self.host.startswith("-"):
            # `-oProxyCommand=...` as a host is option injection.
            raise RegisterError(f"invalid ssh host: {self.host!r}")
        if not self.db or not _DB_NAME.fullmatch(self.db):
            raise RegisterError(f"suspicious database name: {self.db!r}")
        if self.password_env is not None and not _ENV_NAME.fullmatch(self.password_env):
            raise RegisterError(f"password_env must name a variable, got "
                                f"{self.password_env!r}")
        if self.pg_port is not None and not (type(self.pg_port) is int
                                             and 0 < self.pg_port < 65536):
            raise RegisterError(f"invalid pg_port: {self.pg_port!r}")
        if (not isinstance(self.pypgstac, (list, tuple)) or not self.pypgstac
                or not all(isinstance(a, str) and a for a in self.pypgstac)):
            raise RegisterError(f"pypgstac launcher must be a list of words: "
                                f"{self.pypgstac!r}")


@dataclass
class Target:
    """One catalogue: where it is published, where it is served, how it is written,
    and the asset rules it declares for itself."""
    api: str
    collection_id: str
    bucket_url: str
    transport: Transport | None = None
    require_asset: str | None = None
    forbid_assets: list[str] = field(default_factory=list)
    page_size: int = PAGE_SIZE
    chunk: int = 500
    fetch_workers: int = 20

    def check(self) -> None:
        """The local half of "refuse before writing": types and ranges, so a bad
        `chunk` cannot first fail in the read-back AFTER the upsert. Whether the API
        answers is checked separately, by `_api_probe`, before any write."""
        for name in ("api", "collection_id", "bucket_url"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise RegisterError(f"{name} must be a non-empty string, got {value!r}")
        for name in ("page_size", "chunk", "fetch_workers"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise RegisterError(f"{name} must be a positive integer, got {value!r}")
        if self.require_asset is not None and (not isinstance(self.require_asset, str)
                                               or not self.require_asset.strip()):
            # An empty key would otherwise disable the requirement while reading as set.
            raise RegisterError(f"require_asset must be an asset key or None, got "
                                f"{self.require_asset!r}")
        try:
            parse_asset_keys(self.forbid_assets)
        except ValueError as e:
            raise RegisterError(f"forbid_assets: {e}") from e


# =============================================================================
# NDJSON and the load over ssh
# =============================================================================

def ndjson_write(paths, out, expect_collection: str | None = None) -> int:
    """Compact one item JSON per line. Returns the number of lines written.

    json.dumps never emits a raw newline, so a record cannot straddle lines however odd
    the source formatting is.

    `expect_collection` is the last checkpoint before pgstac. pgstac routes each item by
    its OWN `collection` field, so an item whose body still names the previous
    collection upserts into the previous collection SUCCESSFULLY, with no error anywhere.
    """
    n = 0
    with open(out, "w", encoding="utf-8") as fh:
        for path in paths:
            path = str(path).rstrip("\n")
            if not path:
                continue
            with open(path, encoding="utf-8") as src:
                doc = json.load(src)
            if expect_collection is not None:
                got = doc.get("collection") if isinstance(doc, dict) else None
                if got != expect_collection:
                    raise RegisterError(
                        f"{path} names collection {got!r}, expected "
                        f"{expect_collection!r}. Loading it would register the item "
                        f"into {got!r} without erroring.")
            fh.write(json.dumps(doc, separators=(",", ":")))
            fh.write("\n")
            n += 1
    return n


def remote_script(t: Transport, kind: str, expected: int) -> str:
    """The script the host runs, payload on stdin. Every caller value is quoted.

    The line count is checked on the RECEIVING side: if the sender dies mid-stream the
    remote `cat` sees EOF, and pypgstac would load a syntactically valid short file and
    report success.

    The caller's environment file is the caller's code, so it runs in a SUBSHELL with the
    load, never in the shell that holds this script's state. It cannot turn `-e` off for
    the parent, nor reassign the payload path (`readonly`, and namespaced). The success
    line `STACS_LOADED <n> <kind>` is printed inside that subshell only after pypgstac
    returns 0, so neither an `exit 0` nor `set +e` in the environment file can produce it.

    The PG* exports come AFTER the environment file is sourced, so the database
    validated here is the one loaded, whatever the file sets.

    Atomicity: a collection load is one row. An items load is NOT one transaction --
    pypgstac commits each chunk per partition -- so a failed items load can leave some
    of its items committed. Every load is an upsert, so re-running converges.
    """
    if kind not in ("items", "collections"):
        raise ValueError(f"unknown load kind: {kind!r}")
    q = shlex.quote
    lines = [
        "set -euo pipefail",
        # A success flag, not the exit status: on bash 3.2, once an EXIT trap is armed,
        # an expansion error leaves $? at 0 inside the trap and the shell exits 0. Only
        # reaching the last line sets it.
        "__stacs_ok=0",
        f'__stacs_tmp=$(mktemp "${{TMPDIR:-/tmp}}/stacs_{kind}.XXXXXX")',
        "trap 'rm -f \"$__stacs_tmp\"; [ \"$__stacs_ok\" = 1 ] || exit 1' EXIT",
        'cat > "$__stacs_tmp"',
        "__stacs_n=$(wc -l < \"$__stacs_tmp\" | tr -d ' ')",
        # `! [ -eq ]`, not `[ -ne ]`: a count that is not a number makes `test` fail,
        # which must refuse rather than read as "not unequal".
        f'if ! [ "$__stacs_n" -eq {int(expected)} ] 2>/dev/null; then',
        f'  echo "FATAL: received $__stacs_n line(s), expected {int(expected)}'
        f' -- transfer truncated, nothing loaded" >&2',
        "  exit 1",
        "fi",
        "readonly __stacs_tmp __stacs_n",
        "(",
    ]
    sub = []
    if t.env_file:
        sub.append(f". {q(t.env_file)}")
    # Whatever the environment file did to the shell options, the load runs under these.
    sub.append("set -euo pipefail")
    if t.path_prepend:
        sub.append(f'export PATH={q(t.path_prepend)}:"$PATH"')
    if t.workdir:
        sub.append(f"cd {q(t.workdir)}")
    sub.append(f"export PGDATABASE={q(t.db)}")
    for var, val in (("PGHOST", t.pg_host), ("PGPORT", t.pg_port), ("PGUSER", t.pg_user)):
        if val is not None:
            sub.append(f"export {var}={q(str(val))}")
    if t.password_env:
        # A reference, expanded on the host. No --dsn: a password there is in argv.
        # An explicit exit, not `${VAR:?}`, which bash 3.2 can turn into exit 0.
        sub.append(f'if [ -z "${{{t.password_env}:-}}" ]; then echo '
                   f'"FATAL: {t.password_env} is not set on the host" >&2; exit 1; fi')
        sub.append(f'export PGPASSWORD="${{{t.password_env}}}"')
    launcher = " ".join(q(a) for a in t.pypgstac)
    sub.append(f'{launcher} load {kind} "$__stacs_tmp" --method upsert || exit 1')
    sub.append(f'echo "{LOADED_MARK} $__stacs_n {kind}"')
    lines += ["  " + l for l in sub]
    # A plain `( ... )`, never `( ... ) || exit 1`: bash suspends `set -e` for every
    # command inside a list whose status is tested, so `||` here would let a failed
    # `cd` or export run pypgstac anyway. Untested, a failing subshell fails the parent
    # under its own -e, and the success flag covers bash 3.2's EXIT-trap status.
    lines += [")", "__stacs_ok=1"]
    return "\n".join(lines) + "\n"


def _ssh(t: Transport, command: str) -> list[str]:
    # BatchMode on every call: a write that stops at a prompt in CI hangs, it does not
    # fail. `--` ends option parsing before the host.
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", t.host, command]


def probe(t: Transport) -> None:
    """Refuse before the expensive stage if the host cannot be reached."""
    t.check()
    r = subprocess.run(_ssh(t, "true"), stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RegisterError(f"cannot reach {t.host} over ssh")


def load(t: Transport, kind: str, paths, expect_collection: str | None = None,
         dryrun: bool = False, log=print) -> int:
    """Upsert JSON files into pgstac on the host. Returns the number loaded.

    `paths` is a list, never argv: 102k filenames is ~6 MB against a ~2 MB ARG_MAX.
    The payload is assembled completely to a local file before ssh starts, so a refusal
    half way through (`expect_collection`) sends nothing at all.
    """
    t.check()
    paths = [str(p).rstrip("\n") for p in paths if str(p).strip()]
    if not paths:
        log(f"nothing to register (0 {kind})")
        return 0
    if kind == "collections" and len(paths) != 1:
        raise RegisterError(f"one collection per load, got {len(paths)}")
    with tempfile.TemporaryDirectory(prefix="stacs_load.") as work:
        payload = Path(work) / f"{kind}.ndjson"
        written = ndjson_write(paths, payload, expect_collection)
        if written != len(paths):
            raise RegisterError(f"assembled {written} line(s) from {len(paths)} path(s) "
                                f"-- refusing to load")
        log(f"{kind:<8}: {written}")
        log(f"payload : {payload.stat().st_size} bytes")
        log(f"target  : {t.db} db on {t.host}")
        if dryrun:
            log("[dryrun] nothing sent")
            return 0
        probe(t)
        with open(payload, "rb") as fh:
            r = subprocess.run(_ssh(t, "bash -c " + shlex.quote(
                remote_script(t, kind, written))), stdin=fh, stdout=subprocess.PIPE,
                text=True, errors="replace")
        out_lines = r.stdout.splitlines()
        for line in out_lines:
            if not line.startswith(LOADED_MARK):
                log(line)
        if r.returncode != 0:
            raise RegisterError(
                f"load of {written} {kind} failed on {t.host} (exit {r.returncode}). "
                + ("Nothing was loaded." if kind == "collections" else
                   "Some of these items may have been committed before the failure "
                   "(pypgstac commits per chunk); re-running is safe, every load is "
                   "an upsert."))
        if f"{LOADED_MARK} {written} {kind}" not in out_lines:
            raise RegisterError(f"load of {written} {kind} on {t.host} exited 0 without "
                                f"confirming it loaded; treat it as failed")
        log(f"loaded   : {written} {kind}")
    return written


# =============================================================================
# Orchestration
# =============================================================================

def _write_list(out_dir, name, ids) -> None:
    if out_dir is not None:
        Path(out_dir, name).write_text("".join(f"{i}\n" for i in ids), encoding="utf-8")


def _read_ids_file(path) -> list[str]:
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        raise RegisterError(f"ids file missing or empty: {path}")
    ids = sorted({line.strip() for line in p.read_text(encoding="utf-8").splitlines()
                  if line.strip()})
    if not ids:
        raise RegisterError(f"no ids in {path}")
    return ids


def describe_rules(target: Target) -> str:
    forbid = parse_asset_keys(target.forbid_assets)
    if target.require_asset or forbid:
        return f"require={target.require_asset or '-'} forbid={','.join(forbid) or '-'}"
    return "none (no require_asset / forbid_assets declared)"


def run(target: Target, mode: str, ids_file=None, dryrun: bool = False,
        out_dir=None, log=print, warn=None) -> int:
    """Run one mode against one catalogue. Returns the exit status.

    Every refusal is a RegisterError, raised before the first write wherever the check
    allows; it is printed and returns 1.
    """
    warn = warn or (lambda m: print(m, file=sys.stderr))
    try:
        return _run(target, mode, ids_file, dryrun, out_dir, log, warn)
    except RegisterError as e:
        warn(f"ERROR: {e}")
        return 1


def _run(target, mode, ids_file, dryrun, out_dir, log, warn) -> int:
    if mode not in MODES:
        raise RegisterError(f"unknown mode {mode!r}; one of {', '.join(MODES)}")
    if mode == "ids" and not ids_file:
        raise RegisterError("mode 'ids' needs an ids file")
    target.check()
    writes = mode != "verify"
    if writes:
        if target.transport is None:
            raise RegisterError(f"mode {mode!r} writes, and no transport is configured")
        target.transport.check()
    if out_dir is not None:
        Path(out_dir).mkdir(parents=True, exist_ok=True)

    log(f"collection : {target.collection_id}")
    log(f"mode       : {mode}")
    log(f"asset audit: {describe_rules(target)}")

    with tempfile.TemporaryDirectory(prefix="stacs.") as work:
        work = Path(work)

        # --- the published set ------------------------------------------------
        coll_url = target.bucket_url.rstrip("/") + "/collection.json"
        log("fetching published collection.json ...")
        coll_file = work / "collection.json"
        try:
            coll_file.write_bytes(_read_url(coll_url, 300))
            coll = json.loads(coll_file.read_bytes())
        except Exception as e:  # noqa: BLE001 -- any way of not reading it is a refusal
            raise RegisterError(f"could not read {coll_url}: {e}") from e
        if not isinstance(coll, dict):
            raise RegisterError(f"{coll_url} is not a JSON object")
        # The configured id and the bucket name two different things, so neither can be
        # checked against the other by name. The id INSIDE the fetched file reconciles
        # them. An API answers an unknown collection with 200 and zero features, so a
        # mismatch would report every item missing and register them under an id the
        # fetch never came from.
        if coll.get("id") != target.collection_id:
            raise RegisterError(
                f"collection id mismatch: expecting {target.collection_id!r}, "
                f"collection.json at {target.bucket_url} is {coll.get('id')!r}. Either "
                f"the published catalogue has not been migrated to the expected id yet "
                f"(publish it; do not change the expected id to make this pass), or "
                f"bucket_url points at a different catalogue.")
        try:
            links = collection_item_links(coll_file)
        except ValueError as e:
            raise RegisterError(str(e)) from e
        # Relative hrefs (normal in a self-contained catalogue) resolve against the
        # collection's own URL. The id is still the basename.
        links = [(i, urllib.parse.urljoin(coll_url, h)) for i, h in links]
        log(f"published  : {len(links)}")

        # --- what to fetch ----------------------------------------------------
        by_id = dict(links)
        if mode == "ids":
            todo = _read_ids_file(ids_file)
            unknown = [i for i in todo if i not in by_id]
            if unknown:
                raise RegisterError(f"{len(unknown)} requested id(s) have no item link in "
                                    f"the published collection, e.g. {unknown[:3]}")
            fetch = [(i, by_id[i]) for i in todo]
        else:
            fetch = list(links)
            todo = sorted(by_id) if mode == "all" else None
        hrefs = [h for _, h in fetch]
        if len(set(hrefs)) != len(hrefs):
            raise RegisterError("two item links share one href")

        if mode in ("all", "ids"):
            log(f"to register: {len(todo)}")
            if dryrun:
                log(f"[dryrun] would fetch {len(todo)} item(s) and upsert them")
                for i in todo[:3]:
                    log(f"  {i}\t{by_id[i]}")
                return 0

        # Before the expensive stage, in every mode that can write: the host, and the
        # API the write will be verified against. A wrong API URL would otherwise first
        # surface in the read-back, after the upsert.
        if writes and not dryrun:
            _api_probe(target)
            probe(target.transport)

        # --- fetch ------------------------------------------------------------
        fetch_dir = work / "items"
        fetch_dir.mkdir()
        log(f"fetching {len(fetch)} item JSON(s) with {target.fetch_workers} workers ...")
        failed = fetch_bodies(hrefs, fetch_dir, workers=target.fetch_workers)
        # A set gate on what is on disk, not the fetcher's report of itself.
        want = {f"{fetch_key(h)}.json" for h in hrefs}
        have = {p.name for p in fetch_dir.glob("*.json")}
        log(f"fetched    : {len(want & have)} of {len(want)} ({len(failed)} failed)")
        if want != have:
            raise RegisterError(
                f"fetched {len(want & have)} of {len(want)} -- nothing sent to the "
                f"database. Re-run; upsert makes this safe to repeat. Failed: "
                f"{failed[:5]}")

        # --- what differs (drift / verify) -----------------------------------
        coll_state = None
        published = None
        if mode in ("drift", "verify"):
            log("comparing every body with the API ...")
            published = _digests(fetch, fetch_dir)
            registered = _registered(target)
            missing, orphaned, changed = content_diff(published, registered)
            for label, ids in (("published", published), ("registered", registered),
                               ("missing", missing), ("orphaned", orphaned),
                               ("changed", changed)):
                log(f"{label:<10} : {len(ids)}")
            coll_state = _collection_state(coll_file, target)
            log(f"collection : {coll_state}")
            todo = sorted(set(missing) | set(changed))

        if mode == "verify":
            for name, ids in (("missing.txt", missing), ("orphaned.txt", orphaned),
                              ("changed.txt", changed)):
                _write_list(out_dir, name, ids)
            if out_dir is not None:
                Path(out_dir, "collection_state.txt").write_text(coll_state + "\n")
            rc = 0
            for ids, what in ((missing, "published item(s) are not registered"),
                              (changed, "registered item(s) differ from the published "
                                        "body"),
                              (orphaned, "registered item(s) are no longer published")):
                if ids:
                    warn(f"DRIFT: {len(ids)} {what}")
                    for i in ids[:5]:
                        warn(f"  {i}")
                    rc = 1
            if coll_state == "changed":
                warn("DRIFT: the registered collection body differs from collection.json")
                rc = 1
            elif coll_state == "missing":
                warn("DRIFT: the collection is not registered")
                rc = 1
            if rc == 0:
                # Absence of drift is an affirmative result and is said out loud.
                log(f"IN SYNC: {len(published)} published, all registered with the "
                    f"published body, no orphans")
            return rc

        if mode == "drift":
            log(f"to register: {len(todo)}")
            if dryrun:
                log(f"[dryrun] would upsert {len(todo)} item(s) (collection: "
                    f"{coll_state})")
                for i in todo[:5]:
                    log(f"  {i}")
                return 0
            if not todo and coll_state == "same":
                log("nothing to register -- already in sync")
                return 0

        # --- audit, then register: collection first, then items ---------------
        todo_links = [(i, by_id[i]) for i in todo]
        # Every body about to be sent: fetched by this run, parseable, and naming the id
        # its link does. A link whose body names another item would upsert over THAT
        # item. Checked here, before the first write, in every mode.
        sent = _digests(todo_links, fetch_dir)
        todo_paths = [str(fetch_dir / f"{fetch_key(h)}.json") for _, h in todo_links]
        if todo_paths:
            audit = audit_items(todo_paths, target.collection_id, target.require_asset,
                                target.forbid_assets, expect_ids=todo)
            log(f"audit      : {audit.checked} item(s) against {target.collection_id} "
                f"({audit.rules})")
            if not audit.ok:
                raise RegisterError("audit refused the load -- nothing written: "
                                    + "; ".join(audit.failures))

        # pgstac.items.collection REFERENCES collections(id): items with no collection
        # row fail outright.
        load(target.transport, "collections", [coll_file], log=log)
        if todo_paths:
            load(target.transport, "items", todo_paths,
                 expect_collection=target.collection_id, log=log)

        # --- verify -----------------------------------------------------------
        log("verifying by set equality and content ...")
        after = _collection_state(coll_file, target)
        if after != "same":
            raise RegisterError(f"after registering, the collection reads {after!r}, "
                                f"not 'same'")
        log("OK: the collection is served with the published body")

        # pgstac serves items hydrated against their collection, so a collection whose
        # body changed can change how UNTOUCHED items read back. When it may have, and
        # every published body is on disk, re-compare the whole catalogue.
        full = mode == "all" or (mode == "drift" and coll_state != "same")
        if full:
            published = published if published is not None else _digests(fetch, fetch_dir)
            missing, _orphaned, changed = content_diff(published, _registered(target))
            if missing or changed:
                raise RegisterError(
                    f"after registering, {len(missing)} published item(s) are not "
                    f"served and {len(changed)} are served with a different body, e.g. "
                    f"{(missing + changed)[:5]}")
            # Orphans are not this run's failure: nothing here deletes.
            log("OK: every published item is served with the published body")
        elif todo:
            try:
                got = bodies_serving(todo, target.collection_id, target.api,
                                     chunk=target.chunk)
            except (RuntimeError, ValueError) as e:
                raise RegisterError(f"could not read back what was registered: "
                                    f"{e}") from e
            not_served = sorted(set(todo) - set(got))
            _, _, differ = content_diff(sent, {k: got[k] for k in sent if k in got})
            if not_served or differ:
                raise RegisterError(
                    f"after registering, {len(not_served)} id(s) are not served by "
                    f"{target.collection_id} and {len(differ)} are served with a body "
                    f"that differs from the one sent, e.g. {(not_served + differ)[:5]}")
            log(f"OK: all {len(todo)} registered id(s) are served with the body sent")
        if mode == "ids":
            log("note: 'ids' checks only the ids it registered; run 'verify' if "
                "collection.json changed")
        log(f"DONE: {len(todo)} item(s) registered to {target.collection_id}")
        return 0


def _api_probe(target) -> None:
    """One read of each endpoint the post-write verification uses, before any write."""
    import requests

    from stacs.verify import _post
    try:
        _post(requests.Session(), f"{target.api.rstrip('/')}/search",
              {"collections": [target.collection_id], "limit": 1,
               "fields": {"include": ["id"]}})
        root = requests.get(f"{target.api.rstrip('/')}/collections", timeout=60)
        root.raise_for_status()
    except (RuntimeError, requests.RequestException) as e:
        raise RegisterError(f"the API at {target.api} does not answer: {e}") from e


def _digests(links, fetch_dir):
    try:
        return published_digests(links, fetch_dir)
    except (OSError, ValueError) as e:
        raise RegisterError(str(e)) from e


def _registered(target):
    try:
        return bodies_registered(target.collection_id, target.api,
                                 page_size=target.page_size)
    except (RuntimeError, ValueError) as e:
        raise RegisterError(str(e)) from e


def _collection_state(coll_file, target):
    try:
        state = collection_state(coll_file, target.collection_id, target.api)
    except (RuntimeError, ValueError) as e:
        raise RegisterError(f"could not compare the registered collection: {e}") from e
    if state not in ("same", "changed", "missing"):
        raise RegisterError(f"unexpected collection state {state!r}")
    return state
