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
nodes/       the verdict contract — envelope schema + per-node closed enums
bin/         commands: verify-all, cp-verdict
tools/       checks used by ./verify
state/       generated; what the panel reads
```

The panel gates itself, and runs first in `verify-all` rather than last: it holds
the verdict contract that every node's output in every factory is validated
against, so if this is red, "green" elsewhere means less than it looks like.

`~/git-mirrors/sync` mirrors all three repos onto the NVMe root disk, away from
the `sda1` that `/mnt/projects` lives on. It reports uncommitted files
explicitly, because those are exactly what a mirror does not protect.

## The model

[`GRAPH.md`](GRAPH.md) is the plan of record: judgment lives in nodes,
transitions are deterministic scripts, and **a node has no way to advance except
across an edge.** It also explains why `./verify`'s three-way exit code is
already an edge, and why the autonomy level of a factory is just a question of
which nodes on its path are human-occupied.

## The backlog

`.beads/` holds the program backlog — the operating model across all four repos.
Feature work for a factory lives in that factory's own tracker. The line: if it
changes how work moves, it belongs here; if it changes what the product does, it
belongs there.

```
br ready                 what could be started now
br dep tree cp-execution-graph-yt9    the whole program, as a tree
br blocked               what is waiting, and on what
```

Durability: `origin` is `github.com/nikita-leonov/control-plane`, for storage
only — nothing is validated remotely. `~/git-mirrors/sync` mirrors the factory
repos onto the NVMe root disk, away from the `sda1` that `/mnt/projects` lives
on, and reports uncommitted files explicitly because those are exactly what a
mirror does not protect. control-plane is not in that set yet
(`cp-mirror-control-plane-2xz`).

The rule that keeps this a CEO tool rather than another inbox: **it surfaces
decisions, never diffs.** The decision queue is the set of tokens parked on human
nodes. If a diff gets opened that the panel did not flag, that is a bug in the
panel, and it gets filed as one.
