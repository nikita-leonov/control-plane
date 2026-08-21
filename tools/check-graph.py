#!/usr/bin/env python3
"""The graph definition has to be a graph.

Every route must land somewhere real, every verdict must select an edge that
exists, and no name may mean two things. These are cheap to check and expensive
to discover at runtime — a route to a node that does not exist is a token that
deadlocks halfway through a factory, at which point the useful information is
gone.
"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
g = json.loads((ROOT / "nodes" / "graph.json").read_text())
nt = json.loads((ROOT / "nodes" / "node-types.json").read_text())
ms = json.loads((ROOT / "nodes" / "manifest.schema.json").read_text())
MANIFEST_INPUTS = set(ms["properties"]["inputs"]["properties"])

nodes = {n for n, s in nt["nodes"].items() if not s.get("verdicts_from_question")}
human = {n for n, s in nt["nodes"].items() if s.get("verdicts_from_question")}
edges = set(g["edges"])
terms = set(g["terminals"])
bad = []

clash = (nodes | human) & edges
if clash:
    bad.append(f"names mean two things at once: {sorted(clash)}")

for e, spec in g["edges"].items():
    if not spec.get("run"):
        bad.append(f"edge {e}: no script to run")
    for code, to in (spec.get("routes") or {}).items():
        if to not in nodes | edges | terms:
            bad.append(f"edge {e}: exit {code} routes to {to!r}, which does not exist")
    if not spec.get("routes"):
        bad.append(f"edge {e}: no routes — a token entering it can never leave")

for n, spec in nt["nodes"].items():
    for v, rule in (spec.get("verdicts") or {}).items():
        if rule.get("parks"):
            continue
        if rule.get("edge") not in edges:
            bad.append(f"{n}/{v} selects edge {rule.get('edge')!r}, which is not in graph.json")

# An agent node with no declared inputs cannot be isolated: there is nothing to
# assemble a manifest from and nothing to strip against. Gated here rather than
# only in the suite, so a node added without a whitelist turns the board red.
for n in nodes:
    if "inputs" not in nt["nodes"][n]:
        bad.append(f"node {n}: declares no inputs — it cannot be isolated")
    for key in nt["nodes"][n].get("inputs", []):
        if key not in MANIFEST_INPUTS:
            bad.append(f"node {n}: input {key!r} is not in manifest.schema.json")

# The two asymmetries, checked through the guard's real decision function rather
# than by looking for strings in a list. Membership can be satisfied while the
# enforcement path disagrees; this cannot.
import importlib.machinery, importlib.util                              # noqa: E402
_gl = importlib.machinery.SourceFileLoader("cp_guard", str(ROOT / "bin" / "cp-guard"))
cpg = importlib.util.module_from_spec(importlib.util.spec_from_loader("cp_guard", _gl))
_gl.exec_module(cpg)

ASYMMETRIES = [
    ("reviewer", "Edit",  None,                "a judge that can edit what it is judging is not a judge"),
    ("reviewer", "Write", None,                "same"),
    ("builder",  "Bash",  "git merge main",    "the Builder cannot cross its own outgoing edge"),
    ("builder",  "Bash",  "git push origin",   "same"),
    ("builder",  "Bash",  "br close cp-x",     "closing the issue is an edge, not the Builder's call"),
]
for n in nodes:
    if "tools" not in nt["nodes"][n]:
        bad.append(f"node {n}: declares no tool policy — deny by default has nothing to deny from")
for node, tool, cmd, why in ASYMMETRIES:
    if node not in nodes or "tools" not in nt["nodes"].get(node, {}):
        continue
    ok, _ = cpg.decide(node, tool, cmd)
    if ok:
        bad.append(f"{node} would be allowed {tool}"
                   f"{'(' + cmd + ')' if cmd else ''} — {why}")

# The tools that grant other tools. One of these in an allowlist makes every
# other denial advisory, so they are checked at every node rather than listed.
for n in nodes:
    if "tools" not in nt["nodes"][n]:
        continue
    for esc in ("ToolSearch", "Task", "Agent"):
        if cpg.decide(n, esc)[0]:
            bad.append(f"node {n}: {esc} is allowed — it grants other tools, "
                       "which makes the rest of the policy advisory")

# Every node must be able to emit a verdict, or it has no way to advance at all.
for n in nodes:
    if "tools" not in nt["nodes"][n]:
        continue
    ok, _ = cpg.decide(n, "Bash", "cp-verdict emit --node x")
    if not ok:
        bad.append(f"node {n}: cannot call cp-verdict — it has no way to return a verdict")

launch = nt.get("launch") or {}
for field in ("banned_flags", "required_flags"):
    if not launch.get(field):
        bad.append(f"node-types.json: launch.{field} is missing — "
                   "the isolation contract has to be data, not a habit")
for f in launch.get("banned_flags", []):
    if f in launch.get("required_flags", []):
        bad.append(f"launch: {f} is both required and banned")

if g.get("entry") not in nodes:
    bad.append(f"entry {g.get('entry')!r} is not a node")

for f, spec in g["factories"].items():
    for e in spec.get("human_before", []):
        if e not in edges:
            bad.append(f"factory {f}: human_before names {e!r}, which is not an edge")

# Every node must be able to reach a terminal, or a token can circle forever.
adj = {}
for n, spec in nt["nodes"].items():
    adj[n] = [r["edge"] if not r.get("parks") else "@park"
              for r in (spec.get("verdicts") or {}).values()]
for e, spec in g["edges"].items():
    adj[e] = list((spec.get("routes") or {}).values())
for start in nodes | edges:
    seen, front = {start}, [start]
    while front:
        cur = front.pop()
        for t in adj.get(cur, []):
            if t not in seen:
                seen.add(t); front.append(t)
    if not (seen & terms):
        bad.append(f"{start} cannot reach any terminal")

if bad:
    print("\n".join("  " + b for b in bad), file=sys.stderr)
    sys.exit(1)
print(f"{len(nodes)} nodes, {len(edges)} edges, {len(terms)} terminals — all routes land, "
      f"every node declares its inputs and its tools, {len(ASYMMETRIES)} asymmetries hold")
