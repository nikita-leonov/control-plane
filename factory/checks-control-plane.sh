# The panel gates itself. It holds the verdict contract that every node's output
# is validated against, so a break here is a break in all three factories at once.

check "tests"       fast python3 -m unittest discover -s tests -q

# A typo in a schema file is a silent contract change — every .json here is part
# of a contract, so a parse failure must be a gate failure and not a surprise at
# the first node invocation.
check "json"        fast python3 -c "
import json,pathlib,sys
bad=[]
for p in sorted(pathlib.Path('.').glob('**/*.json')):
    if any(x in p.parts for x in ('.git','.beads','state','node_modules')): continue
    try: json.loads(p.read_text())
    except Exception as e: bad.append(f'{p}: {e}')
print('\n'.join(bad) or f'{len(list(pathlib.Path(\".\").glob(\"nodes/*.json\")))} contract files parse', file=sys.stderr if bad else sys.stdout)
sys.exit(1 if bad else 0)"

# GRAPH.md promises that nothing is described without an issue behind it. That
# rule was enforced by hand until it became this.
check "issue refs"  full python3 tools/check-issue-refs.py
