"""Checks on item bodies before they are registered.

Two different questions, kept apart:

- **audit**: does every item agree with the collection it is about to be registered into,
  and with the asset rules the catalogue declares? The property is HOMOGENEITY, not size.
  Item ids do not change during a rename, so id-set equality reads IN SYNC over a fully
  mixed catalogue; pgstac routes each item by its OWN `collection` field, so a stale item
  registers successfully into the old collection; and a count of assets cannot tell
  {image, dsm} from {dem, dsm}.
- **validate**: is each item valid STAC, by `pystac`? Not run by `register`: the code this
  was extracted from never validated at registration, and per-item schema validation of a
  whole catalogue is a cost a caller should choose.

Asset rules are the caller's. Nothing here knows any catalogue's keys.
"""

import json
import os
from dataclasses import dataclass, field


@dataclass
class Audit:
    """The outcome of `audit_items`, with paths rather than counts -- a count of
    offenders is no more use here than a count of items."""
    collection_id: str
    require_asset: str | None
    forbid_assets: list[str]
    checked: int = 0
    ids: list[str] = field(default_factory=list)
    wrong_collection: list[str] = field(default_factory=list)
    missing_asset: list[str] = field(default_factory=list)
    forbidden_asset: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def rules(self) -> str:
        """The asset rules as APPLIED, not as passed: a forbid argument of "," is
        non-empty and parses to no keys, and a caller printing its own flags would
        report a check that never ran."""
        if self.require_asset or self.forbid_assets:
            return (f"require={self.require_asset or '-'} "
                    f"forbid={','.join(self.forbid_assets) or '-'}")
        return "no asset checks"

    @property
    def ok(self) -> bool:
        return not self.failures


def parse_asset_keys(value) -> list[str]:
    """Asset keys from a comma-separated string or a list.

    `None` or an empty list means "no rule". Anything else must name keys, every one of
    them: `""` (an unset variable), `","` or a list holding an empty entry raises rather
    than reading as "forbid nothing" -- the item still carrying a retired key would
    otherwise pass.

    A LIST, not a single key: a rename can retire more than one key, and a single-string
    parameter once meant a comma-joined value matched no real key and the check silently
    stopped checking anything.
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple)):
        if not value:
            return []
        parts = list(value)
    else:
        raise ValueError(f"asset keys must be a string or a list, got {value!r}")
    keys = []
    for part in parts:
        if not isinstance(part, str) or not part.strip():
            raise ValueError(f"empty asset key in {value!r}")
        if part.strip() not in keys:
            keys.append(part.strip())
    return keys


def item_paths_in_dir(directory) -> list[str]:
    """Every item JSON in a directory: `*.json` except `collection.json`, sorted."""
    return sorted(
        os.path.join(directory, f) for f in os.listdir(directory)
        if f.endswith(".json") and f != "collection.json"
    )


def _is_asset(value) -> bool:
    """A required asset is an object with an href, not merely a key: `{"data": null}`
    would otherwise satisfy `require_asset="data"`."""
    return (isinstance(value, dict) and isinstance(value.get("href"), str)
            and bool(value["href"]))


def audit_items(paths, collection_id: str, require_asset: str | None = None,
                forbid_assets=None, expect: int | None = None,
                expect_ids=None) -> Audit:
    """Which items disagree with the collection they are to be registered into.

    `expect` is a count and `expect_ids` a set; pass the set wherever the ids are known,
    because a count is satisfied by the wrong items. Either exists so a run that silently
    processed a SUBSET -- a reused manifest is the way that happens -- fails here rather
    than registering.

    Zero items is never a pass: a loop over an empty set reports nothing, which is
    indistinguishable from "everything checked out".
    """
    # Every way of passing "nothing" refuses rather than disabling a check: an empty
    # collection id would match items with no collection, an empty require key
    # (`--require-asset "$UNSET"`) once failed every item and must not pass them, and
    # forbid keys that parse to nothing raise in parse_asset_keys.
    if not isinstance(collection_id, str) or not collection_id.strip():
        raise ValueError(f"collection_id is required, got {collection_id!r}")
    if require_asset is not None and (not isinstance(require_asset, str)
                                      or not require_asset.strip()):
        raise ValueError(f"require_asset must be an asset key or None, got "
                         f"{require_asset!r}")
    forbid = parse_asset_keys(forbid_assets)
    r = Audit(collection_id, require_asset, forbid)
    for path in paths:
        path = path.rstrip("\n")
        if not path:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            if not isinstance(doc, dict):
                raise ValueError("not a JSON object")
        except (OSError, ValueError) as e:
            r.unreadable.append(f"{path}: {e}")
            continue
        item_id = doc.get("id")
        if not isinstance(item_id, str) or not item_id:
            r.unreadable.append(f"{path}: no id")
            continue
        assets = doc.get("assets")
        if assets is None:          # absent or null: no assets, as in the source
            assets = {}
        if not isinstance(assets, dict):
            # A string or list would answer `key in assets` by substring or membership.
            r.unreadable.append(f"{path}: assets is not an object")
            continue
        r.checked += 1
        r.ids.append(item_id)
        if doc.get("collection") != collection_id:
            r.wrong_collection.append(path)
        if r.require_asset is not None and not _is_asset(assets.get(r.require_asset)):
            r.missing_asset.append(path)
        if any(key in assets for key in forbid):
            r.forbidden_asset.append(path)

    if r.checked == 0 and not r.unreadable:
        r.failures.append("no item JSONs to check")
    for kind, label in (("wrong_collection", "name another collection"),
                        ("missing_asset", f"lack asset {r.require_asset!r}"),
                        ("forbidden_asset", f"still carry a retired asset key {forbid!r}"),
                        ("unreadable", "could not be read")):
        hits = getattr(r, kind)
        if hits:
            r.failures.append(f"{len(hits)} item(s) {label}, e.g. {hits[:3]}")
    # In the audit, not in its callers: a batch naming one id twice is never right
    # (pgstac upserts by id, so one body silently wins, or the load fails half way), and
    # a check left to each caller was missing from the second one written.
    repeated = sorted({i for i in r.ids if r.ids.count(i) > 1}) if \
        len(set(r.ids)) != len(r.ids) else []
    if repeated:
        r.failures.append(f"{len(repeated)} id(s) appear more than once, e.g. "
                          f"{repeated[:3]}")
    if expect is not None and r.checked != expect:
        r.failures.append(f"expected {expect} item(s), audited {r.checked}")
    if expect_ids is not None:
        want, got = set(expect_ids), set(r.ids)
        if want != got or len(r.ids) != len(got):
            r.failures.append(
                f"audited ids differ from the expected set: "
                f"{len(want - got)} missing, {len(got - want)} unexpected, "
                f"{len(r.ids) - len(got)} repeated")
    return r


def validate_items(paths) -> list[tuple[str, str]]:
    """[(path, error)] for every item that is not valid STAC.

    The body is validated AS WRITTEN, with `pystac.validation.validate_dict`. Not via
    `pystac.Item.from_dict(...).validate()`, which validates pystac's re-serialisation:
    it upgrades a 1.0.0 item to 1.1.0 and rewrites a naive datetime, so the body that
    would be registered is never the one checked.

    Every item is checked; failures are collected rather than stopping at the first. A
    schema that cannot be fetched (extension schemas, and core schemas for STAC versions
    pystac does not bundle, are fetched by URL) is a failure, not a pass. Zero items
    raises: an empty result is this function's success value.
    """
    import pystac.validation

    paths = [str(p).rstrip("\n") for p in paths]
    paths = [p for p in paths if p]
    if not paths:
        raise ValueError("no item JSONs to validate")
    bad = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            if not isinstance(doc, dict):
                raise ValueError("not a JSON object")
            pystac.validation.validate_dict(doc)
        except Exception as e:  # noqa: BLE001 -- every reason is a failure, recorded
            bad.append((path, f"{type(e).__name__}: {e}"))
    return bad
