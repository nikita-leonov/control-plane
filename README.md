# control-plane

The panel over three factories: `faceoff-finder`, `ai-ih-coach`,
`finance-c-and-c`. It exists so that supervising them is reading one screen
rather than reading three repos.

Everything here runs on this machine. There is no CI and no remote validation,
by decision: faceoff-finder needs local footage, the venv and the GPU weights,
so a gate that cannot run where the work happens is not a gate at all.

## Today

```
bin/verify-all              full gate in every factory, one board, one exit code
bin/verify-all --fast       cheap tier only
bin/verify-all <name>       just one
```

Exit 0 = all green, 1 = something is red, 2 = a factory could not be run at all
(missing repo, missing `./verify`) — a different problem from a failing check,
and it should not look like one.

Every run writes `state/verify-latest.json`: per factory the branch, commit,
dirty-file count, and each check's status and duration.

```
factory/     the shared parts of a factory repo — ./verify template + generator
bin/         commands
state/       generated; what the panel reads
```

`~/git-mirrors/sync` mirrors all three repos onto the NVMe root disk, away from
the `sda1` that `/mnt/projects` lives on. It reports uncommitted files
explicitly, because those are exactly what a mirror does not protect.

## Not built yet

The point of this directory is the seat, not the scripts. What is still missing,
in the order it should arrive:

- **`CHARTER.md` in each factory** — what the company is, its north-star metric,
  what is out of scope. Owned by Nikita; agents may only file a charter question
  against it.
- **beads in all three** — today only ai-ih-coach has a real backlog. Acceptance
  criteria written before code is the thing that makes work dispatchable.
- **`cp status` / `cp brief`** — read-only across all three: ready work, WIP,
  gate state, the decision queue. Visibility before automation.
- **The shift** — Groomer, Reviewer, Builder, Sweeper as headless `claude -p`
  runs, in that order. The judge gets built before the author is scaled.

The rule that keeps this a CEO tool rather than another inbox: **it surfaces
decisions, never diffs.** If a diff gets opened that the panel did not flag,
that is a bug in the panel, and it gets filed as one.
