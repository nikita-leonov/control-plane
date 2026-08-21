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
print(f"{len(nodes)} nodes, {len(edges)} edges, {len(terms)} terminals — all routes land")
