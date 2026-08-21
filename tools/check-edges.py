#!/usr/bin/env python3
"""An edge has to be an edge.

The graph rests on edges being deterministic scripts whose exit code selects the
branch. That is cheap to state and easy to erode — an edge that shells out to a
model, or that returns a code nothing routes, breaks the property the whole
design is built on while still looking like a working script.

Checked here rather than in the suite alone, because these are exactly the
mistakes that would go green for weeks.
"""
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
g = json.loads((ROOT / "nodes" / "graph.json").read_text())
EDGES = ROOT / "bin" / "edges"
bad = []

# A model on an edge is a model in the router, which is the one thing this design
# exists to remove. Checked over the files, not asserted in a comment.
MODEL = re.compile(r"\b(claude|anthropic|openai|llm|gpt-)\b", re.I)

for name, spec in g["edges"].items():
    run = spec.get("run") or []
    if not run:
        bad.append(f"edge {name}: no script to run")
        continue

    script = run[0]
    if spec.get("cwd") != "factory":
        p = ROOT / script
        if not p.exists():
            bad.append(f"edge {name}: no script at {script}")
            continue
        if not os.access(p, os.X_OK):
            bad.append(f"edge {name}: {script} is not executable")
        body = p.read_text()
        if MODEL.search(body):
            bad.append(f"edge {name}: {script} mentions a model — "
                       "an edge that asks a model is a router that is not deterministic")
        if "_lib.sh" not in body:
            bad.append(f"edge {name}: {script} does not source _lib.sh, "
                       "so it has its own idea of what an exit code means")

    exits = spec.get("exits")
    if not exits:
        bad.append(f"edge {name}: declares no exits — nothing says what it can return")
        continue
    routes = spec.get("routes") or {}
    for code in exits:
        if str(code) not in routes:
            bad.append(f"edge {name}: can exit {code} but nothing routes it — "
                       "a token would stop somewhere nobody designed")
    # The one conflation the contract names explicitly.
    if 1 in exits and 2 in exits and routes.get("1") == routes.get("2"):
        bad.append(f"edge {name}: exit 2 routes where exit 1 does ({routes.get('1')}) — "
                   "a broken gate must not look like a red one")

# Every file in bin/edges is scanned, not only the ones graph.json names. The
# shared library is a file every edge sources, so a model call in there is a
# model call on every edge — and it is exactly the file the reference-following
# version of this check would skip.
for p in sorted(EDGES.iterdir()):
    if not p.is_file():
        continue
    if MODEL.search(p.read_text()):
        bad.append(f"bin/edges/{p.name}: mentions a model — "
                   "an edge that asks a model is a router that is not deterministic")
    if p.name.startswith("_"):
        continue                     # shared library, sourced rather than crossed
    used = any((spec.get("run") or [""])[0].endswith(p.name) for spec in g["edges"].values())
    if not used:
        bad.append(f"bin/edges/{p.name}: no edge in graph.json runs it — "
                   "a script nobody crosses is a script nobody tests")

if bad:
    print("\n".join("  " + b for b in bad), file=sys.stderr)
    sys.exit(1)
print(f"{len(g['edges'])} edges — all scripted, all exits routed, none asks a model")
