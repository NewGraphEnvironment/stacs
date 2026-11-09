"""Enumerate the candidate set for every mechanism the review exposed.

Parsed, not recalled. Three populations, because the first version's population was too
narrow and round 2b found two instances outside it:

A. "a member read as a mapping without being one" — `X.get("member")` then used as a mapping.
B. "one fact derived twice" — the predicate that selects the receipt-linking asset.
C. "a JSON value consumed as a dict KEY" — `X.get(expr)` / `X[expr]` where expr is data.
D. "a non-mapping walked as if it had no members" — `.items()`/`.keys()`/`.values()` on a
   value that may not be a mapping. This is what hid the collection-arm defect: empty key
   sets read as "nothing differs" rather than "this is not a mapping".
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path("/Users/airvine/Projects/repo/stacs/src/stacs")
FILES = sorted(ROOT.glob("*.py"))

MEMBERS = {"output", "recipe", "result", "context", "properties", "assets", "parts",
           "fingerprint", "summary", "tolerance", "code", "inputs", "config", "files",
           "settings", "columns", "tables", "run", "toolchain", "legacy"}

# Names that are a mapping by construction at every use: a literal, a comprehension, or a
# value this code built. Each is justified in the table of the write-up, not here.
SAFE_RECEIVERS = {"_mapping", "dict", "sorted", "register", "_patterns", "stac_fields"}


def _data_derived(key):
    """Is this key expression read out of a document rather than written here?

    `X[name]` where `name` is a loop variable over our own keys is not the risk; `X[d.get(k)]`
    and `X[d["k"]]` are -- a JSON value used as a dict key, which raises `TypeError:
    unhashable type` for a list or a dict. That is the shape that bit (round 2b).
    """
    for node in ast.walk(key):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get":
            return True
        if isinstance(node, ast.Subscript):
            return True
    return False


def receiver_is_safe(node):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in SAFE_RECEIVERS:
        return True
    if isinstance(node, (ast.Dict, ast.DictComp)):
        return True
    return False


rows = {"A": [], "C": [], "D": []}
for path in FILES:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr, recv = node.func.attr, node.func.value
            if attr == "get" and node.args:
                key = node.args[0]
                if isinstance(key, ast.Constant) and key.value in MEMBERS:
                    rows["A"].append((path.name, node.lineno, ast.unparse(node)[:72],
                                      receiver_is_safe(recv)))
                elif _data_derived(key):
                    rows["C"].append((path.name, node.lineno, ast.unparse(node)[:72], False))
            if attr in ("items", "keys", "values"):
                rows["D"].append((path.name, node.lineno, ast.unparse(node)[:72],
                                  receiver_is_safe(recv)))
        if isinstance(node, ast.Subscript) and _data_derived(node.slice):
            rows["C"].append((path.name, node.lineno, ast.unparse(node)[:72], False))

for pop, label in (("A", "member read as a mapping"),
                   ("C", "value consumed as a dict key / index"),
                   ("D", "non-mapping walked as having no members")):
    print(f"=== Mechanism {pop}: {label} ===")
    for name, line, text, safe in rows[pop]:
        mark = {True: "ok   by construction", False: "CHECK", None: "review"}[safe]
        print(f"  {mark:20} {name}:{line}  {text}")
    unsafe = [x for x in rows[pop] if x[3] is False]
    print(f"  {len(rows[pop])} site(s); {len(unsafe)} needing a stated reason\n")

print("=== Mechanism B: who selects the receipt-linking asset ===")
hits = []
for path in FILES:
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "RECEIPT_ROLE in" in line:
            hits.append(f"  predicate at {path.name}:{i}  {line.strip()[:72]}")
print("\n".join(hits) or "  none")
print(f"  {len(hits)} producer(s) of that predicate\n")

sys.exit(1 if len(hits) != 1 else 0)
