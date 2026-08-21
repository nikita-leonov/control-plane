# This repo had no lint, no tests and no CI while running at five times the
# commit rate of the other two. Everything below is new; see
# docs/verify-findings.md for what it found on the first run and what is still
# missing (chiefly the golden set — the only honest way to verify a CV pipeline).

PY=.venv/bin/python

# Ratchet, not a wall: 27 violations predate the gate, so only regressions fail.
check "lint"          fast $PY tools/lint_ratchet.py check

# 73 modules, imported for real. The single highest-value check here: the entry
# points are a long-running web app and `python -m` scripts, so a broken import
# is otherwise found by running the app and watching it fall over.
check "tests"         fast $PY -m pytest tests -q

# The venv is the runtime; an unsatisfiable pin is a production break.
check "dependencies"  full $PY -m pip check
