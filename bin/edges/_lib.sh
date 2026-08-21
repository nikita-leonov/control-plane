# _lib.sh — the edge contract, as code every edge sources.
#
# An edge is a script. Its exit code selects the outgoing branch, so the exit
# code is the whole interface and conflating two of them is the only way to
# really get this wrong. Hence three verbs instead of `exit N` scattered around:
#
#   edge_ok               0  proceed
#   edge_failed "why"     1  the work failed — that is work, and it routes to repair
#   edge_broken "why"     2  the EDGE is broken — not the work
#
# 2 must never look like 1. A repair node handed a broken edge would "fix" code
# that was never the problem, and it would look busy doing it.
#
# An edge is a pure function of (node result, repo at a known commit). Both
# arrive in the environment, set by the runner:
#
#   CP_TOKEN CP_FACTORY CP_EDGE CP_RUN   which crossing this is
#   CP_RESULT                            path to the node result envelope
#   CP_WORKTREE                          the repo it may touch
#   CP_BASE                              the commit the work started from
#
# No edge invokes a model. That is asserted by a test rather than left as a rule.
#
# Every mutating edge calls edge_no_dry_run first. The runner already swaps a
# no-op in for these during a dry run, so this is the second lock on the same
# door — and the reason for two is that the first one used to key off the edge's
# working directory, which happened to cover the stubs and would have stopped
# covering them the day they became real.

set -uo pipefail

edge_ok()     { [ $# -gt 0 ] && printf '%s\n' "$*"; exit 0; }
edge_failed() { printf 'edge %s: %s\n' "${CP_EDGE:-?}" "$*" >&2; exit 1; }
edge_broken() { printf 'edge %s: BROKEN: %s\n' "${CP_EDGE:-?}" "$*" >&2; exit 2; }

# An edge that cannot see what it is acting on is broken, not failing. Getting
# this backwards routes a missing input to repair, which cannot fix it.
edge_needs() {
  local v
  for v in "$@"; do
    [ -n "${!v:-}" ] || edge_broken "$v is not set — the runner did not supply it"
  done
}

# A mutating edge reached during a dry run means the runner's guard did not fire.
# That is the guard being broken, not the work failing, so it exits 2 — and it
# exits before touching anything.
edge_no_dry_run() {
  [ -z "${CP_DRY_RUN:-}" ] || edge_broken \
    "reached during a dry run — a dry run must not be able to touch a repo"
}

# Read a field out of the node result. The result is the edge's input; an edge
# that cannot parse it is broken rather than failed.
edge_result() {
  edge_needs CP_RESULT
  [ -f "$CP_RESULT" ] || edge_broken "no node result at $CP_RESULT"
  python3 -c "
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception as e: sys.stderr.write(str(e)); sys.exit(2)
cur=d
for k in sys.argv[2].split('.'):
    if k: cur=cur[k] if isinstance(cur,dict) else None
print(json.dumps(cur) if not isinstance(cur,str) else cur)
" "$CP_RESULT" "$1" 2>/dev/null || edge_broken "node result has no $1"
}
