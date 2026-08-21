# Pure TypeScript over YAML/NDJSON state files — everything runs anywhere,
# in well under a second. There is no reason for this repo to ever be red.

check "typecheck"      fast npm run --silent typecheck
check "unit tests"     fast npm test

# `fcc validate` reads the actual portfolio state: lot arithmetic, price
# staleness, deadlines that have passed. A code change that breaks the data
# contract shows up here rather than in a wrong number three weeks later.
check "data integrity" full ./fcc validate
