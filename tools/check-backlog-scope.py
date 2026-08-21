#!/usr/bin/env python3
"""This backlog is about how work moves, not about what any product does.

The line, from README.md: if it changes how work moves, it belongs here; if it
changes what a product does, it belongs in that factory's own tracker.

That rule was written down and then quietly eroded — three faceoff-finder issues
accumulated here because faceoff-finder had nowhere to put them. So it is a check
now. The tell is mechanical and hard to argue with: an issue that talks about
paths which exist inside a factory and do not exist here is an issue about that
factory's insides.

An issue that legitimately coordinates across factories says so with the
`cross-factory` label. That is an explicit claim by whoever filed it, which is
the point — the escape hatch is visible in the backlog rather than buried here.
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECTS = pathlib.Path("/mnt/projects")
FACTORIES = ["faceoff-finder", "ai-ih-coach", "finance-c-and-c"]

# Labels that say what kind of work this is. Every issue needs one: an unlabeled
# issue is one nobody classified, and this whole check is about classification.
SCOPE_LABELS = {"program", "cross-factory", "meta"}

# Paths that mean nothing on their own — every repo has them, so finding one
# inside a factory proves nothing about which repo an issue belongs to.
UBIQUITOUS = {"README.md", "CLAUDE.md", "CHARTER.md", "verify", "./verify",
              ".beads", ".beads/", "tools/", "tests/", "bin/", "docs/",
              "verify-report.json", ".githooks", "state/", "web/"}

PATHISH = re.compile(r"\b(?:[\w.-]+/)*[\w.-]+\.(?:py|ts|tsx|js|md|json|sh|toml|ya?ml)\b"
                     r"|\b[\w.-]+/(?=[\s`,)]|$)")

# argv[1] lets the tests point this at a synthetic backlog. The check is about a
# rule that erodes quietly, so it needs tests of its own rather than only ever
# being run against a backlog that currently happens to pass.
BACKLOG = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".beads" / "issues.jsonl"

issues = [json.loads(l) for l in BACKLOG.read_text().splitlines() if l.strip()]
issues = [o for o in issues if not (o.get("deleted") or o.get("tombstone"))
          and o.get("status") != "closed"]

bad, waiting = [], []
for o in issues:
    labels = set(o.get("labels") or [])

    if not (labels & SCOPE_LABELS):
        bad.append(f"{o['id']}: no scope label "
                   f"(one of {', '.join(sorted(SCOPE_LABELS))}) — nobody classified it")

    if "cross-factory" in labels:
        continue                       # an explicit, visible claim; taken at its word

    # An acknowledged violation waiting on somewhere to go. The exemption is
    # deliberately self-expiring: it holds only while that factory has no
    # tracker, so the day one exists this check starts failing and the move
    # stops being optional. A permanent exemption is just the rule deleted
    # slowly.
    moving = [l for l in labels if l.startswith("moves-to-")]
    if moving:
        dest = moving[0][len("moves-to-"):]
        if dest not in FACTORIES:
            bad.append(f"{o['id']}: labelled {moving[0]} but {dest!r} is not a factory")
        elif (PROJECTS / dest / ".beads" / "issues.jsonl").exists():
            bad.append(f"{o['id']}: labelled {moving[0]} and {dest} now HAS a tracker — "
                       "move it there; this exemption has expired")
        else:
            waiting.append(f"{o['id']} -> {dest} (waiting on that tracker to exist)")
        continue

    text = f"{o.get('title','')}\n{o.get('description','')}"
    elsewhere = {}
    for m in set(PATHISH.findall(text)):
        p = m.strip("/") if m.endswith("/") else m
        if p in UBIQUITOUS or m in UBIQUITOUS or (ROOT / p).exists():
            continue
        for f in FACTORIES:
            if (PROJECTS / f / p).exists():
                elsewhere.setdefault(f, set()).add(p)
                break
    for f, paths in elsewhere.items():
        bad.append(f"{o['id']}: names {', '.join(sorted(paths))} — "
                   f"{f}'s insides, not this repo's. Move it there, or label it "
                   "cross-factory if it really is about how work moves.")

if bad:
    print("\n".join("  " + b for b in bad), file=sys.stderr)
    sys.exit(1)
for w in waiting:
    print(f"  awaiting a home: {w}")
print(f"{len(issues)} open issues, all about how work moves"
      + (f" ({len(waiting)} queued to move out)" if waiting else ""))
