"""The `stacs` command.

    stacs verify   --config stacs.toml [--out-dir DIR]
    stacs register --config stacs.toml --mode drift|all|ids [--ids-file F] [--dryrun]
    stacs load collection --config stacs.toml FILE [--dryrun]           # first
    stacs load items      --config stacs.toml [--dryrun] < paths
    stacs audit    [--config stacs.toml] (--dir DIR | paths on stdin) [--expect N]
    stacs validate (--dir DIR | paths on stdin)

Settings come from a TOML file named by `--config` (never looked up implicitly) and
flags override them -- except the asset rules, which a flag may ADD to and never
loosen: a catalogue's declared rules are what stop a half-done rename from loading, and
an override that removed them would reopen exactly that. No setting is a secret; the
database password stays on the STAC host and is named, not given (`password_env`).
"""

import argparse
import json
import sys
import tomllib
from pathlib import Path

from stacs import __version__
from stacs.register import MODES, RegisterError, Target, Transport, load, run
from stacs.validate import audit_items, item_paths_in_dir, parse_asset_keys, validate_items

# Every key the config may carry, by table. Anything else is refused, which is also what
# keeps a `password = ...` line from being silently accepted.
CONFIG_KEYS = {
    "catalogue": {"api", "collection_id", "bucket_url"},
    "assets": {"require", "forbid"},
    "transport": {"host", "db", "env_file", "workdir", "path_prepend", "pg_host",
                  "pg_port", "pg_user", "password_env", "pypgstac"},
    "tuning": {"page_size", "chunk", "fetch_workers"},
}


class ConfigError(Exception):
    pass


def read_config(path) -> dict:
    """The config file as nested dicts, with every table and key checked."""
    if path is None:
        return {}
    try:
        with open(path, "rb") as fh:
            cfg = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"cannot read config {path}: {e}") from e
    for table, values in cfg.items():
        if table not in CONFIG_KEYS:
            raise ConfigError(f"{path}: unknown table [{table}]")
        if not isinstance(values, dict):
            raise ConfigError(f"{path}: {table} must be a table")
        unknown = set(values) - CONFIG_KEYS[table]
        if unknown:
            raise ConfigError(f"{path}: unknown key(s) in [{table}]: "
                              f"{', '.join(sorted(unknown))}")
    return cfg


def merge_asset_rules(cfg: dict, require_flag, forbid_flag):
    """(require, forbid) from config and flags. Flags add; they never loosen.

    `require` is one key: a flag naming a different key from the config's would replace
    the declared requirement, so it is refused. `forbid` is the union of both. Either
    flag may arrive as a list (repeated on the command line); every value counts.
    """
    if isinstance(require_flag, list):
        distinct = sorted(set(require_flag))
        if len(distinct) > 1:
            raise ConfigError(f"--require-asset given more than one key {distinct}; "
                              f"one key is required per catalogue")
        require_flag = require_flag[0] if require_flag else None
    if isinstance(forbid_flag, list):
        forbid_flag = None if not forbid_flag else forbid_flag
    assets = cfg.get("assets", {})
    require = assets.get("require")
    if require is not None and (not isinstance(require, str) or not require.strip()):
        raise ConfigError("[assets] require must be one asset key")
    if require_flag is not None:
        # An empty flag (`--require-asset "$UNSET"`) is refused, never read as "none".
        if not require_flag.strip():
            raise ConfigError("--require-asset is empty")
        if require and require_flag != require:
            raise ConfigError(f"--require-asset {require_flag!r} would replace the "
                              f"declared require = {require!r}; declared rules can be "
                              f"added to, never loosened")
        require = require_flag
    try:
        forbid = parse_asset_keys(assets.get("forbid"))
        # A flag that parses to nothing ("$UNSET", ",") is refused, not read as "none".
        added = []
        for value in (forbid_flag if isinstance(forbid_flag, list) else
                      [] if forbid_flag is None else [forbid_flag]):
            added += parse_asset_keys(value)
    except ValueError as e:
        raise ConfigError(f"forbid: {e}") from e
    if forbid_flag is not None and not added:
        raise ConfigError("--forbid-asset is empty")
    for key in added:
        if key not in forbid:
            forbid.append(key)
    return require, forbid


def _pick(flag, cfg: dict, table: str, key: str, name: str, required=True):
    value = flag if flag is not None else cfg.get(table, {}).get(key)
    if required and (value is None or value == ""):
        raise ConfigError(f"{name} is required (flag, or {key} in [{table}])")
    return value


def build_transport(args, cfg: dict) -> Transport:
    t = dict(cfg.get("transport", {}))
    if args.host is not None:
        t["host"] = args.host
    if args.db is not None:
        t["db"] = args.db
    for key in ("host", "db"):
        if not t.get(key):
            raise ConfigError(f"--{key} is required (flag, or {key} in [transport])")
    if "pypgstac" in t and isinstance(t["pypgstac"], str):
        raise ConfigError("[transport] pypgstac must be a list, e.g. "
                          "[\"uv\", \"run\", \"pypgstac\"]")
    transport = Transport(**t)
    try:
        transport.check()
    except RegisterError as e:
        raise ConfigError(f"[transport] {e}") from e
    return transport


def build_target(args, cfg: dict, needs_transport: bool) -> Target:
    require, forbid = merge_asset_rules(cfg, args.require_asset, args.forbid_asset)
    tuning = cfg.get("tuning", {})
    return Target(
        api=_pick(args.api, cfg, "catalogue", "api", "--api"),
        collection_id=_pick(args.collection_id, cfg, "catalogue", "collection_id",
                            "--collection-id"),
        bucket_url=_pick(args.bucket_url, cfg, "catalogue", "bucket_url", "--bucket-url"),
        transport=build_transport(args, cfg) if needs_transport else None,
        require_asset=require,
        forbid_assets=forbid,
        **{k: tuning[k] for k in ("page_size", "chunk", "fetch_workers") if k in tuning},
    )


def _paths(args) -> list[str]:
    directory = getattr(args, "dir", None)
    if directory is not None:
        # `--dir "$UNSET"` must not fall back to reading stdin.
        if not directory.strip():
            raise ConfigError("--dir is empty")
        try:
            return item_paths_in_dir(directory)
        except OSError as e:
            raise ConfigError(f"cannot read --dir {directory}: {e}") from e
    return [line.rstrip("\n") for line in sys.stdin if line.strip()]


# =============================================================================
# Commands
# =============================================================================

def cmd_verify(args, cfg) -> int:
    return run(build_target(args, cfg, needs_transport=False), "verify",
               out_dir=args.out_dir)


def cmd_register(args, cfg) -> int:
    if args.ids_file is not None and args.mode != "ids":
        # Accepted and ignored would upsert the whole catalogue instead of those ids.
        raise ConfigError(f"--ids-file applies only to --mode ids, not {args.mode}")
    target = build_target(args, cfg, needs_transport=True)
    return run(target, args.mode, ids_file=args.ids_file, dryrun=args.dryrun)


def cmd_load(args, cfg) -> int:
    """Upsert locally built JSON. The catalogue's declared collection and asset rules
    apply here exactly as they do in `register`: pgstac routes each item by its own
    `collection` field, so this is the last place a stale item can be stopped."""
    t = build_transport(args, cfg)
    declared = cfg.get("catalogue", {}).get("collection_id")
    collection = args.expect_collection if args.expect_collection is not None \
        else declared
    if not isinstance(collection, str) or not collection.strip():
        raise ConfigError(f"load {args.kind} needs the collection to check against: "
                          f"--expect-collection, or collection_id in [catalogue]")
    if args.kind == "items":
        require, forbid = merge_asset_rules(cfg, None, None)
        paths = _paths(args)
        if not paths:
            print("FAIL: no item JSONs to load", file=sys.stderr)
            return 1
        audit = audit_items(paths, collection, require, forbid)
        print(f"audit   : {audit.checked} item(s) against {collection} ({audit.rules})")
        if not audit.ok:
            for f in audit.failures:
                print(f"FAIL: {f}", file=sys.stderr)
            return 1
    else:
        try:
            with open(args.file, encoding="utf-8") as fh:
                coll_id = json.load(fh).get("id")
        except (OSError, ValueError, AttributeError) as e:
            print(f"ERROR: cannot read {args.file}: {e}", file=sys.stderr)
            return 1
        if coll_id != collection:
            print(f"ERROR: {args.file} is collection {coll_id!r}, expected "
                  f"{collection!r}", file=sys.stderr)
            return 1
    try:
        if args.kind == "items":
            load(t, "items", paths, expect_collection=collection, dryrun=args.dryrun)
        else:
            load(t, "collections", [args.file], dryrun=args.dryrun)
    except (RegisterError, OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_audit(args, cfg) -> int:
    require, forbid = merge_asset_rules(cfg, args.require_asset, args.forbid_asset)
    collection_id = _pick(args.collection_id, cfg, "catalogue", "collection_id",
                          "--collection-id")
    r = audit_items(_paths(args), collection_id, require, forbid, expect=args.expect)
    # The rules as APPLIED, from the audit itself, not as passed.
    print(f"checked {r.checked} item(s) against {collection_id} ({r.rules})",
          file=sys.stderr)
    for f in r.failures:
        print(f"FAIL: {f}", file=sys.stderr)
    if not r.ok:
        return 1
    print(f"OK: every item agrees with its collection ({r.rules})", file=sys.stderr)
    return 0


def cmd_validate(args, cfg) -> int:
    paths = _paths(args)
    if not paths:
        print("FAIL: no item JSONs to validate", file=sys.stderr)
        return 1
    bad = validate_items(paths)
    for path, err in bad:
        print(f"INVALID: {path}: {err.splitlines()[0] if err else ''}", file=sys.stderr)
    print(f"validated {len(paths)} item(s), {len(bad)} invalid", file=sys.stderr)
    return 1 if bad else 0


# =============================================================================
# Parser
# =============================================================================

def _catalogue_flags(p):
    p.add_argument("--api", help="STAC API base URL")
    p.add_argument("--collection-id")
    p.add_argument("--bucket-url", help="base URL serving collection.json")


def _transport_flags(p):
    p.add_argument("--host", help="ssh target for the STAC host")
    p.add_argument("--db", help="pgstac database name")


def _asset_flags(p):
    p.add_argument("--require-asset", action="append",
                   help="an asset key every item must carry (adds to the config; "
                   "cannot replace a declared one)")
    p.add_argument("--forbid-asset", action="append",
                   help="asset key(s), comma-separated, no item may carry (added to "
                   "the config's; may be repeated)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="stacs", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"stacs {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_config(p):
        p.add_argument("--config", help="stacs.toml (never looked up implicitly)")
        return p

    p = with_config(sub.add_parser("verify", help="compare the API with what is "
                                   "published; write nothing"))
    _catalogue_flags(p)
    _asset_flags(p)
    p.add_argument("--out-dir", help="write missing / changed / orphaned id lists here")
    p.set_defaults(fn=cmd_verify)

    p = with_config(sub.add_parser("register", help="upsert into pgstac, then verify"))
    _catalogue_flags(p)
    _transport_flags(p)
    _asset_flags(p)
    p.add_argument("--mode", required=True, choices=[m for m in MODES if m != "verify"])
    p.add_argument("--ids-file", help="for --mode ids: one id per line")
    p.add_argument("--dryrun", action="store_true")
    p.set_defaults(fn=cmd_register)

    p = sub.add_parser("load", help="upsert JSON files built locally")
    lsub = p.add_subparsers(dest="kind", required=True)
    li = with_config(lsub.add_parser("items", help="item JSON paths on stdin, one "
                                     "per line"))
    li.add_argument("--dir", help="load every item JSON in this directory instead")
    lc = with_config(lsub.add_parser("collection", help="one collection.json"))
    lc.add_argument("file")
    for q in (li, lc):
        q.add_argument("--expect-collection",
                       help="the collection id to check against (default: collection_id "
                            "in [catalogue])")
        _transport_flags(q)
        q.add_argument("--dryrun", action="store_true")
        q.set_defaults(fn=cmd_load)

    p = with_config(sub.add_parser("audit", help="assert every item agrees with its "
                                   "collection and the declared asset rules"))
    p.add_argument("--collection-id")
    _asset_flags(p)
    p.add_argument("--dir", help="directory of item JSONs (default: paths on stdin)")
    p.add_argument("--expect", type=int, help="the number of items there should be")
    p.set_defaults(fn=cmd_audit)

    p = sub.add_parser("validate", help="pystac validation of every item")
    p.add_argument("--dir", help="directory of item JSONs (default: paths on stdin)")
    p.set_defaults(fn=cmd_validate, config=None)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = read_config(getattr(args, "config", None))
        return args.fn(args, cfg)
    except (ConfigError, ValueError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
