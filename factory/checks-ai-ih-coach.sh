# The server runs on Node's native type stripping, which removes types without
# checking them. Nothing in server/src was ever verified until this ran.

check "web typecheck"     fast npm run --silent typecheck --workspace=web
check "server typecheck"  fast npm run --silent typecheck --workspace=server
check "unit tests"        fast npm test

# The two Workers deploy to Cloudflare and share one D1 database, so a type
# error here is a production error. They are not npm workspaces, hence --prefix.
check "auth typecheck"    full npm --prefix auth   run --silent typecheck
check "intake typecheck"  full npm --prefix intake run --silent typecheck
