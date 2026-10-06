"""Build a file:// copy of a fetched catalogue with ONE body edited.

Both tools, run against the live API with this copy as the published side, must report
exactly that id as changed and nothing else. Empty sets on the live catalogue prove
nothing on their own; this shows the comparison can see a difference.

Usage: positive_control.py <ref_dir> <out_dir>   -> prints the edited id
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path


def main(ref_dir, out_dir):
    ref, out = Path(ref_dir), Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    coll = json.loads((ref / "collection.json").read_text())
    edited = None
    for link in coll["links"]:
        if link.get("rel") != "item":
            continue
        body = json.loads((ref / "items" / f"{hashlib.md5(link['href'].encode()).hexdigest()}.json").read_bytes())
        if edited is None:
            body.setdefault("properties", {})["stacs:positive_control"] = 1
            edited = body["id"]
        name = body["id"] + ".json"
        (out / name).write_text(json.dumps(body))
        link["href"] = "file://" + str(out) + "/" + name.replace(" ", "%20")
    (out / "collection.json").write_text(json.dumps(coll))
    print(edited)


if __name__ == "__main__":
    main(*sys.argv[1:3])
