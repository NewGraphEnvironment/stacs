"""Tests for the `stacs` command: config, the asset-rule merge, and each subcommand's
contract. The register path itself is tested end to end in test_register.py."""

import io
import json
import re

import pytest

from stacs import cli

CONFIG = """
[catalogue]
api = "https://api.example.invalid"
collection_id = "any-collection"
bucket_url = "https://bucket.example.invalid"

[assets]
require = "data"
forbid = ["legacy"]

[transport]
host = "user@host.example.invalid"
db = "stacdb"
password_env = "PG_PASSWORD_VAR"
pypgstac = ["uv", "run", "pypgstac"]
"""


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "stacs.toml"
    p.write_text(CONFIG)
    return p


@pytest.fixture
def captured_run(monkeypatch):
    """Replace register.run as the CLI sees it, keeping what it was called with."""
    calls = []

    def fake(target, mode, **kw):
        calls.append((target, mode, kw))
        return 0

    monkeypatch.setattr(cli, "run", fake)
    return calls


def _item(item_id, collection="any-collection", assets=("data",)):
    return {"type": "Feature", "id": item_id, "collection": collection,
            "assets": {k: {"href": "x"} for k in assets}}


# =============================================================================
# Config
# =============================================================================

def test_config_builds_the_target(cfg_file, captured_run):
    assert cli.main(["verify", "--config", str(cfg_file)]) == 0
    target, mode, _ = captured_run[0]
    assert mode == "verify"
    assert (target.api, target.collection_id, target.bucket_url) == (
        "https://api.example.invalid", "any-collection", "https://bucket.example.invalid")
    assert (target.require_asset, target.forbid_assets) == ("data", ["legacy"])
    assert target.transport is None


def test_register_builds_the_transport(cfg_file, captured_run):
    assert cli.main(["register", "--config", str(cfg_file), "--mode", "drift"]) == 0
    t = captured_run[0][0].transport
    assert (t.host, t.db, t.password_env, t.pypgstac) == (
        "user@host.example.invalid", "stacdb", "PG_PASSWORD_VAR", ["uv", "run", "pypgstac"])


def test_flags_override_the_catalogue_settings(cfg_file, captured_run):
    cli.main(["verify", "--config", str(cfg_file), "--api", "https://other.example.invalid"])
    assert captured_run[0][0].api == "https://other.example.invalid"


def test_the_config_is_never_looked_up_implicitly(tmp_path, monkeypatch, capsys):
    """A stacs.toml in the working directory is not read unless named."""
    (tmp_path / "stacs.toml").write_text(CONFIG)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["verify"]) == 2
    assert "--api is required" in capsys.readouterr().err


@pytest.mark.parametrize("extra, match", [
    ("[secrets]\npassword = \"hunter2\"\n", r"unknown table \[secrets\]"),
    ("[transport]\npassword = \"hunter2\"\n", "unknown key"),
    ("[catalogue]\napi_key = \"x\"\n", "unknown key"),
])
def test_an_unknown_config_key_is_refused(tmp_path, extra, match, capsys):
    """Which is also what keeps a password from being accepted into a config."""
    p = tmp_path / "stacs.toml"
    p.write_text(extra)
    assert cli.main(["verify", "--config", str(p)]) == 2
    assert re.search(match, capsys.readouterr().err)


def test_an_unreadable_config_is_refused(tmp_path, capsys):
    assert cli.main(["verify", "--config", str(tmp_path / "nope.toml")]) == 2
    assert "cannot read config" in capsys.readouterr().err


def test_pypgstac_as_a_string_is_refused(tmp_path, capsys):
    p = tmp_path / "stacs.toml"
    p.write_text(CONFIG.replace('pypgstac = ["uv", "run", "pypgstac"]',
                                'pypgstac = "uv run pypgstac"'))
    assert cli.main(["register", "--config", str(p), "--mode", "all"]) == 2
    assert "must be a list" in capsys.readouterr().err


def test_no_secret_is_accepted_as_a_flag():
    """Secrets through the environment, never argv."""
    flags = set()
    for action in _all_actions(cli.build_parser()):
        flags.update(action.option_strings)
    assert not [f for f in flags if re.search("pass|secret|token|dsn", f)]


def _all_actions(parser):
    for action in parser._actions:
        yield action
        for sub in getattr(action, "choices", None) or {}:
            if isinstance(action.choices, dict):
                yield from _all_actions(action.choices[sub])


def test_no_flag_defaults_to_a_deployment():
    offenders = [a.dest for a in _all_actions(cli.build_parser())
                 if isinstance(a.default, str) and a.default not in ("==SUPPRESS==",)]
    assert offenders == []


# =============================================================================
# Asset rules: flags add, never loosen
# =============================================================================

def test_a_forbid_flag_adds_to_the_declared_list(cfg_file, captured_run):
    cli.main(["verify", "--config", str(cfg_file), "--forbid-asset", "old2,legacy"])
    assert captured_run[0][0].forbid_assets == ["legacy", "old2"]


def test_a_require_flag_cannot_replace_the_declared_one(cfg_file, captured_run, capsys):
    assert cli.main(["verify", "--config", str(cfg_file),
                     "--require-asset", "thumbnail"]) == 2
    assert "never loosened" in capsys.readouterr().err
    assert captured_run == []


def test_a_require_flag_naming_the_declared_key_is_fine(cfg_file, captured_run):
    assert cli.main(["verify", "--config", str(cfg_file), "--require-asset", "data"]) == 0


@pytest.mark.parametrize("flag", ["", "  "])
def test_an_empty_require_flag_is_refused_not_ignored(cfg_file, captured_run, flag, capsys):
    assert cli.main(["verify", "--config", str(cfg_file), "--require-asset", flag]) == 2
    assert "empty" in capsys.readouterr().err and captured_run == []


def test_an_empty_declared_require_is_refused(tmp_path, captured_run, capsys):
    p = tmp_path / "stacs.toml"
    p.write_text(CONFIG.replace('require = "data"', 'require = ""'))
    assert cli.main(["verify", "--config", str(p)]) == 2
    assert "must be one asset key" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["", ",", " , "])
def test_an_empty_forbid_flag_is_refused_not_read_as_none(cfg_file, captured_run,
                                                           flag, capsys):
    assert cli.main(["verify", "--config", str(cfg_file), "--forbid-asset", flag]) == 2
    assert "forbid" in capsys.readouterr().err and captured_run == []


def test_an_empty_declared_forbid_list_means_no_rule(tmp_path, captured_run):
    p = tmp_path / "stacs.toml"
    p.write_text(CONFIG.replace('forbid = ["legacy"]', "forbid = []"))
    assert cli.main(["verify", "--config", str(p)]) == 0
    assert captured_run[0][0].forbid_assets == []


def test_a_different_collection_id_keeps_the_declared_rules(cfg_file, captured_run):
    """The rename window: pointing at the old id must not drop the rules that would
    refuse old-shape items. Rules are declared for the catalogue, not keyed by id."""
    cli.main(["verify", "--config", str(cfg_file), "--collection-id", "some-old-id"])
    target = captured_run[0][0]
    assert target.collection_id == "some-old-id"
    assert (target.require_asset, target.forbid_assets) == ("data", ["legacy"])


# =============================================================================
# audit and validate
# =============================================================================

def test_audit_refuses_a_forbid_list_that_parses_to_nothing(tmp_path, capsys):
    """`--forbid-asset ,` names no key. The source reported "(no asset checks)" and
    passed; now it is refused, like every other way of passing nothing."""
    (tmp_path / "x.json").write_text(json.dumps(_item("x")))
    rc = cli.main(["audit", "--dir", str(tmp_path), "--collection-id", "any-collection",
                   "--forbid-asset", ","])
    assert rc == 2 and "forbid" in capsys.readouterr().err


def test_audit_with_no_rules_says_so(tmp_path, capsys):
    (tmp_path / "x.json").write_text(json.dumps(_item("x")))
    rc = cli.main(["audit", "--dir", str(tmp_path), "--collection-id", "any-collection"])
    assert rc == 0 and "(no asset checks)" in capsys.readouterr().err


def test_audit_dir_skips_the_collection_and_fails_a_mixed_population(tmp_path, capsys):
    (tmp_path / "collection.json").write_text(json.dumps({"id": "any-collection"}))
    (tmp_path / "a.json").write_text(json.dumps(_item("a")))
    (tmp_path / "b.json").write_text(json.dumps(_item("b", collection="old")))
    rc = cli.main(["audit", "--dir", str(tmp_path), "--collection-id", "any-collection"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "checked 2 item(s)" in err and "name another collection" in err


def test_audit_over_nothing_fails(tmp_path, capsys):
    rc = cli.main(["audit", "--dir", str(tmp_path), "--collection-id", "c"])
    assert rc == 1 and "no item JSONs" in capsys.readouterr().err


def test_audit_uses_the_declared_rules(tmp_path, cfg_file, capsys):
    (tmp_path / "a.json").write_text(json.dumps(_item("a", assets=("thumbnail",))))
    rc = cli.main(["audit", "--config", str(cfg_file), "--dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 1 and "lack asset 'data'" in err and "require=data forbid=legacy" in err


def test_audit_expect_fails_a_subset(tmp_path, capsys):
    (tmp_path / "a.json").write_text(json.dumps(_item("a")))
    rc = cli.main(["audit", "--dir", str(tmp_path), "--collection-id", "any-collection",
                   "--expect", "2"])
    assert rc == 1 and "expected 2 item(s), audited 1" in capsys.readouterr().err


def test_audit_reads_paths_from_stdin(tmp_path, monkeypatch, capsys):
    p = tmp_path / "a b.json"
    p.write_text(json.dumps(_item("a")))
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{p}\n\n"))
    assert cli.main(["audit", "--collection-id", "any-collection"]) == 0


def test_validate_over_nothing_fails(tmp_path, capsys):
    assert cli.main(["validate", "--dir", str(tmp_path)]) == 1
    assert "no item JSONs" in capsys.readouterr().err


# =============================================================================
# load
# =============================================================================

def test_load_items_dryrun_assembles_and_sends_nothing(tmp_path, cfg_file, monkeypatch,
                                                       capsys):
    paths = []
    for i in range(2):
        p = tmp_path / f"i{i}.json"
        p.write_text(json.dumps(_item(f"i{i}")))
        paths.append(str(p))
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(paths) + "\n"))
    rc = cli.main(["load", "items", "--config", str(cfg_file), "--dryrun",
                   "--expect-collection", "any-collection"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "items   : 2" in out and "[dryrun] nothing sent" in out


def test_load_items_refuses_another_collection(tmp_path, cfg_file, monkeypatch, capsys):
    p = tmp_path / "x.json"
    p.write_text(json.dumps(_item("x", collection="old")))
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{p}\n"))
    rc = cli.main(["load", "items", "--config", str(cfg_file), "--dryrun",
                   "--expect-collection", "any-collection"])
    assert rc == 1 and "name another collection" in capsys.readouterr().err


def test_load_needs_a_host_and_db(tmp_path, capsys):
    p = tmp_path / "c.json"
    p.write_text("{}")
    assert cli.main(["load", "collection", str(p), "--dryrun"]) == 2
    assert "--host is required" in capsys.readouterr().err


def test_load_items_applies_the_declared_collection_and_rules(tmp_path, cfg_file,
                                                             monkeypatch, capsys):
    """The config's collection_id and asset rules hold on the load path too: an
    old-collection item with a retired key is refused with no --expect-collection."""
    p = tmp_path / "a.json"
    p.write_text(json.dumps(_item("a", collection="old", assets=("data", "legacy"))))
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{p}\n"))
    rc = cli.main(["load", "items", "--config", str(cfg_file), "--dryrun"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "name another collection" in err and "retired asset key" in err


def test_load_items_needs_a_collection_to_check_against(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "t.toml"
    cfg.write_text('[transport]\nhost = "u@h.example.invalid"\ndb = "d"\n')
    p = tmp_path / "a.json"
    p.write_text(json.dumps(_item("a")))
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{p}\n"))
    assert cli.main(["load", "items", "--config", str(cfg), "--dryrun"]) == 2
    assert "needs the collection" in capsys.readouterr().err


@pytest.mark.parametrize("args, stdin", [
    ([], ""),
    (["--dir", "EMPTY"], ""),
])
def test_load_items_that_loads_nothing_fails(tmp_path, cfg_file, monkeypatch, capsys,
                                             args, stdin):
    """`find build/items ... | stacs load items` on an unbuilt path must not succeed."""
    (tmp_path / "empty").mkdir()
    args = [str(tmp_path / "empty") if a == "EMPTY" else a for a in args]
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    assert cli.main(["load", "items", "--config", str(cfg_file), "--dryrun", *args]) == 1
    assert "no item JSONs to load" in capsys.readouterr().err


@pytest.mark.parametrize("cmd", [["audit", "--collection-id", "c"], ["validate"]])
def test_an_empty_dir_flag_is_refused_not_read_as_stdin(cmd, capsys):
    assert cli.main([*cmd, "--dir", ""]) == 2
    assert "--dir is empty" in capsys.readouterr().err


@pytest.mark.parametrize("cmd", [["audit", "--collection-id", "c"], ["validate"]])
def test_a_missing_dir_is_a_refusal_not_a_traceback(tmp_path, cmd, capsys):
    assert cli.main([*cmd, "--dir", str(tmp_path / "nope")]) == 2
    assert "cannot read --dir" in capsys.readouterr().err


def test_load_collection_must_be_the_declared_collection(tmp_path, cfg_file, capsys):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"type": "Collection", "id": "other"}))
    assert cli.main(["load", "collection", "--config", str(cfg_file), str(p),
                     "--dryrun"]) == 1
    assert "expected 'any-collection'" in capsys.readouterr().err


def test_load_collection_needs_a_collection_to_check_against(tmp_path, capsys):
    cfg = tmp_path / "t.toml"
    cfg.write_text('[transport]\nhost = "u@h.example.invalid"\ndb = "d"\n')
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"type": "Collection", "id": "any"}))
    assert cli.main(["load", "collection", "--config", str(cfg), str(p), "--dryrun"]) == 2
    assert "needs the collection" in capsys.readouterr().err


def test_ids_file_outside_ids_mode_is_refused(tmp_path, cfg_file, captured_run, capsys):
    ids = tmp_path / "ids.txt"
    ids.write_text("a\n")
    assert cli.main(["register", "--config", str(cfg_file), "--mode", "all",
                     "--ids-file", str(ids)]) == 2
    assert "only to --mode ids" in capsys.readouterr().err and captured_run == []


@pytest.mark.parametrize("dup", ["same_path", "same_id"])
def test_load_items_refuses_an_id_given_twice(tmp_path, cfg_file, monkeypatch, capsys, dup):
    a = tmp_path / "a.json"
    a.write_text(json.dumps(_item("a")))
    if dup == "same_path":
        stdin = f"{a}\n{a}\n"
    else:
        b = tmp_path / "b.json"
        b.write_text(json.dumps({**_item("a"), "properties": {"other": 1}}))
        stdin = f"{a}\n{b}\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    assert cli.main(["load", "items", "--config", str(cfg_file), "--dryrun"]) == 1
    assert "appear more than once" in capsys.readouterr().err


def test_audit_expect_cannot_be_satisfied_by_one_item_twice(tmp_path, monkeypatch, capsys):
    a = tmp_path / "a.json"
    a.write_text(json.dumps(_item("a")))
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{a}\n{a}\n"))
    assert cli.main(["audit", "--collection-id", "any-collection", "--expect", "2"]) == 1


def test_repeated_forbid_flags_all_count(tmp_path, capsys):
    (tmp_path / "a.json").write_text(json.dumps(_item("a", assets=("data", "legacy"))))
    rc = cli.main(["audit", "--dir", str(tmp_path), "--collection-id", "any-collection",
                   "--forbid-asset", "legacy", "--forbid-asset", "other"])
    err = capsys.readouterr().err
    assert rc == 1 and "forbid=legacy,other" in err


def test_two_different_require_flags_are_refused(tmp_path, capsys):
    (tmp_path / "a.json").write_text(json.dumps(_item("a")))
    rc = cli.main(["audit", "--dir", str(tmp_path), "--collection-id", "any-collection",
                   "--require-asset", "zzz", "--require-asset", "data"])
    assert rc == 2 and "more than one key" in capsys.readouterr().err


@pytest.mark.parametrize("line", ['host = 5', 'db = ["x"]', 'password_env = 1',
                                  'pypgstac = 5', 'pg_port = true', 'pg_port = "5432"',
                                  'env_file = ""'])
def test_a_transport_value_of_the_wrong_type_is_refused(tmp_path, line, captured_run,
                                                         capsys):
    base = {"host": '"u@h.example.invalid"', "db": '"d"'}
    key = line.split(" = ")[0]
    base[key] = line.split(" = ", 1)[1]
    cfg = tmp_path / "t.toml"
    cfg.write_text(CONFIG.split("[transport]")[0] + "[transport]\n"
                   + "".join(f"{k} = {v}\n" for k, v in base.items()))
    assert cli.main(["register", "--config", str(cfg), "--mode", "all"]) == 2
    assert "[transport]" in capsys.readouterr().err and captured_run == []
