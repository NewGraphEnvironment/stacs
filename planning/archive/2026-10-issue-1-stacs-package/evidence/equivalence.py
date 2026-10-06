"""Verdict equivalence, item by item: does the JCS digest agree with the digest it
replaced about which items are the same?

Over the SAME published bodies (the reference run's fetch dir) and ONE pass over the
API, three digests per item, both sides:
  links_only : sha256(json.dumps(sort_keys)) with only `links` removed -- what a
               comparison without canonicalisation would say
  old        : stac_dem_bc's _canonical (nulls stripped, integral float -> int)
  jcs        : stacs.verify.body_digest (RFC 8785)

Reports: items where old and jcs disagree (must be 0); the class links_only-differs-but-
old-equal (the null / integral-float items) and whether jcs reads all of them equal;
distinct digest counts; NaN / beyond-2^53 / backslash scans of the published bodies.

Usage: equivalence.py <ref_dir> <collection_id> <api>
"""

import hashlib
import json
import math
import sys
from pathlib import Path

import requests

from stacs.catalogue import collection_item_links, fetch_key
from stacs.verify import _search_pages, body_digest


def links_only(doc):
    d = {k: v for k, v in doc.items() if k != "links"}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _old_canonical(x):
    if isinstance(x, dict):
        return {k: _old_canonical(v) for k, v in x.items() if v is not None}
    if isinstance(x, list):
        return [_old_canonical(v) for v in x]
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x


def old(doc):
    canon = _old_canonical({k: v for k, v in doc.items() if k != "links"})
    return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def scan(x, found):
    if isinstance(x, dict):
        for k, v in x.items():
            if "\\" in k:
                found["backslash"] += 1
            scan(v, found)
    elif isinstance(x, list):
        for v in x:
            scan(v, found)
    elif isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        found["nan_inf"] += 1
    elif type(x) is int and abs(x) > 2**53 - 1:
        found["beyond_2_53"] += 1
    elif isinstance(x, str) and "\\" in x:
        found["backslash"] += 1


def main(ref_dir, cid, api):
    ref = Path(ref_dir)
    pub = {}
    found = {"nan_inf": 0, "beyond_2_53": 0, "backslash": 0}
    for item_id, href in collection_item_links(ref / "collection.json"):
        doc = json.loads((ref / "items" / f"{fetch_key(href)}.json").read_bytes())
        scan(doc, found)
        pub[item_id] = (links_only(doc), old(doc), body_digest(doc))
    srv = {}
    body = {"collections": [cid], "limit": 10000}
    for feats in _search_pages(requests.Session(), api, body):
        for f in feats:
            srv[f["id"]] = (links_only(f), old(f), body_digest(f))
    both = pub.keys() & srv.keys()
    disagree = [i for i in both if (pub[i][1] == srv[i][1]) != (pub[i][2] == srv[i][2])]
    canon_class = [i for i in both if pub[i][0] != srv[i][0] and pub[i][1] == srv[i][1]]
    canon_class_jcs_equal = sum(1 for i in canon_class if pub[i][2] == srv[i][2])
    print(json.dumps({
        "collection": cid,
        "published": len(pub), "served": len(srv), "in_both": len(both),
        "old_vs_jcs_verdict_disagreements": len(disagree),
        "disagreement_examples": sorted(disagree)[:5],
        "changed_old": sum(1 for i in both if pub[i][1] != srv[i][1]),
        "changed_jcs": sum(1 for i in both if pub[i][2] != srv[i][2]),
        "links_only_differs_but_old_equal": len(canon_class),
        "of_which_jcs_equal": canon_class_jcs_equal,
        "distinct_published_jcs_digests": len({v[2] for v in pub.values()}),
        "published_scan": found,
    }, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:4])
