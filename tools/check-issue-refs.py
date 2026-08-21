#!/usr/bin/env python3
"""Every issue id cited in the docs must exist.

GRAPH.md holds itself to a rule: no forward-looking claim without an issue behind
it. That rule was being enforced by hand, which means it was going to rot. This
turns it into a check — a document that promises work must point at work that
exists, and a closed issue cited as future work is a document that has drifted
past the backlog.
"""
import json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ["GRAPH.md", "README.md"]
REF = re.compile(r"\bcp-[a-z0-9-]+-[a-z0-9]{3}\b")

# Read the committed JSONL rather than shelling out to `br`. It is the artifact
# git carries, it needs no daemon, and it is what the control plane will read
# anyway. `br` auto-flushes on write, so it is current.
JSONL = ROOT / ".beads" / "issues.jsonl"
if not JSONL.exists():
    print(f"check-issue-refs: no backlog at {JSONL}", file=sys.stderr)
    sys.exit(2)

issues = {}
for n, line in enumerate(JSONL.read_text().splitlines(), 1):
    line = line.strip()
    if not line:
        continue
    try:
        o = json.loads(line)
    except json.JSONDecodeError as e:
        print(f"check-issue-refs: {JSONL}:{n}: {e}", file=sys.stderr)
        sys.exit(2)
    if o.get("deleted") or o.get("tombstone"):
        continue
    issues[o["id"]] = o.get("status", "?")

if not issues:
    print("check-issue-refs: backlog is empty", file=sys.stderr)
    sys.exit(2)

bad = []
for name in DOCS:
    p = ROOT / name
    if not p.exists():
        continue
    for i, line in enumerate(p.read_text().splitlines(), 1):
        for ref in REF.findall(line):
            if ref not in issues:
                bad.append(f"{name}:{i}: {ref} does not exist")
            elif issues[ref] == "closed":
                bad.append(f"{name}:{i}: {ref} is closed — cited as work still to do")

if bad:
    print("\n".join(bad), file=sys.stderr)
    sys.exit(1)

cited = {r for n in DOCS if (ROOT / n).exists()
         for r in REF.findall((ROOT / n).read_text())}
print(f"{len(cited)} issue references, all open and resolving")
