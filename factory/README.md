# factory — the shared parts of a factory repo

Every factory exposes the same `./verify` contract so one control plane can read
any of them without special cases. The machinery is generated from
`verify.template` and copied into each repo rather than shared as a dependency:
the repos stay independent, and drift is detectable rather than impossible.

```
python3 gen-verify.py <repo-name> checks-<repo-name>.sh /mnt/projects/<repo>/verify
```

`verify.template` holds the machinery — flag parsing, the `check` helper, the
evidence writer. `checks-*.sh` holds only that repo's checks, one line each:

```
check "<name>" <fast|full> <command...>
```

## The contract

| | |
|---|---|
| `./verify` | every check; exit 0 = mergeable, 1 = failed, 2 = verify is broken |
| `./verify --fast` | sub-30s subset; what agents and the pre-push hook run |
| `./verify --evidence` | also writes `verify-report.json` (gitignored) |

Output is captured and shown only on failure, so a green run is one line per
check and a red one is impossible to miss.

## Also standard in every factory

- `.githooks/pre-push` runs the **full** `./verify`; enabled with
  `git config core.hooksPath .githooks`. `SKIP_VERIFY=1` overrides.
- `verify-report.json` in `.gitignore`.

There is no CI, by decision. Nothing here is validated on a remote machine:
faceoff-finder needs local footage, the venv and the GPU weights, and a gate
that cannot run where the work happens is not a gate. `bin/verify-all` is the
one place that answers "is everything green", and the pre-push hook is the last
automatic check before history leaves a repo — which is why it runs the full
tier rather than `--fast`.

## When a repo's checks change

Edit `checks-<repo>.sh` here and regenerate, so this directory stays the source
of truth. Editing the repo's `./verify` directly is how the machinery drifts.
