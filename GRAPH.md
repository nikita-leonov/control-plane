# The execution graph

How work moves through a factory, from a groomed issue to a merged commit.

Judgment happens in **nodes**. Transitions happen on **edges**, which are
deterministic scripts. The rule that makes this worth anything:

> **A node has no way to advance except across an edge.**

An agent cannot decide it is done, cannot route itself, and cannot skip ahead.
It produces a value; a script decides what that value means and where it goes.

## Why the router is the thing to protect

This is the shape LangGraph has, with the LLM router removed. That removal is
the entire point. Once a model chooses transitions, the reachable states of the
system stop being enumerable — you can no longer say what your own factory is
able to do, only what it did last time. With scripted edges the state space is
finite, drawable, and checkable, which buys four things that are otherwise
aspirational:

**Resumability.** Kill the runner mid-flight and it continues from the last
crossing. State lives on the edge, not inside a conversation.

**Auditability.** The log of crossings *is* the provenance record. "Why did this
land" is a path, not a 40,000-token transcript nobody is going to read. This is
the difference between a CEO seat and another inbox.

**Testability.** Edges are scripts, so they have unit tests. Record the node
results once and the whole graph replays with zero model calls.

**The Builder cannot talk its way past `./verify`**, because there is no edge
that accepts an argument. The related claim — author is never judge — holds only
in the narrower sense of *information* independence, and only if the runner
enforces it. See "Isolation" below for what that buys and what it does not.

## Nodes return values, not prose

Every node returns a closed enum plus a small payload. The moment an edge has to
read a paragraph to decide where to go, the router is nondeterministic again —
now it is a regex pretending to be a state machine, which is worse than an
honest model call because it fails silently.

`./verify` already gets this right and is the model for the rest: exit 0, 1, 2
is a three-way typed verdict. That is why it already works as an edge.

The payload matters as much as the verdict. If nodes hand each other large prose
blobs, this is a prompt chain wearing a graph costume. The payload is a small
typed record — issue id, commit sha, file list, evidence path, attempt count —
carrying what the next edge needs and nothing else.

### How a typed value actually gets out of an agent

Not by asking it to end with a JSON block. That is parsing prose with extra
steps, and it fails silently the one time it matters.

A node emits its verdict by **calling a command**, `bin/cp-verdict`, which
validates and writes the envelope. Its tool policy grants `Bash(cp-verdict:*)`
and nothing else that can write. Two properties follow, and they are the reason
for the design:

- **A node that produces only prose produces no verdict at all.** There is no
  file, so there is nothing to best-effort parse and no edge is ever tempted to
  interpret a paragraph as a decision. The failure is structural rather than a
  judgement call made by a regex.
- **Malformed output is rejected at emission**, where the node can still fix it,
  rather than downstream where the runner would have to guess.

```
nodes/verdict.schema.json   the envelope shape — the contract of record
nodes/node-types.json       each node's closed verdict enum, and which edge each selects
bin/cp-verdict              emit | check | schema
```

`cp-verdict schema --node reviewer` answers "what may I return?", so a node's
system prompt can be generated from the contract instead of drifting from it.

Validation is two-stage, because shape alone cannot express routing. The
envelope is checked against the JSON Schema; then the verdict is checked against
that node's closed enum, the payload against the shape that verdict declares,
and the question against whether the verdict parks. Unknown fields are
**rejected at emission** and **stripped again at manifest assembly** — the same
rule at two points, because a free-text field is precisely how a Builder would
argue its case to a Reviewer.

The runtime validator hand-implements a subset of JSON Schema and takes no
dependency, since this repo's premise is that it runs with no install step. That
is only defensible if it is not wrong, so `tests/test_verdict.py` pins it against
the real `jsonschema` library over a corpus. If they diverge, the hand-written
one is the bug.

### A human node is a node like any other

A verdict that parks the token must carry the **question** being asked — and the
question's options *are* that human node's outgoing edges:

```json
{ "asks": "LABEL_STATUSES is exported, served nowhere and used nowhere. Serve it or delete it?",
  "context": [ {"ref": "shared/taxonomy.ts:442", "why": "where it is exported"},
               {"ref": "coach-5ao", "why": "the issue filed when the gate found it"} ],
  "options": [ {"value": "serve",  "means": "add it to taxonomyPayload()",     "edge": "repair"},
               {"value": "delete", "means": "remove the unused export",        "edge": "repair-delete"},
               {"value": "keep",   "means": "record why in UNSERVED_BY_DESIGN","edge": "approve"} ] }
```

So a human node needs no special machinery. The only difference from an agent
node is who fills in the verdict; the question is just its edge list rendered for
a person. This is what lets `cp brief` show the actual decision with its options
rather than "something needs you" — the difference between a decision queue and
a notification list, which is the whole thesis of the panel.

The schema enforces that this stays a decision. `asks` is capped at 280
characters, because a decision needing an essay is not ready to be asked.
`context` holds pointers with one line of why, never free text, so context cannot
become an argument aimed at the person. There must be at least two options, and
they must not all cross the same edge.


## Edges are pure functions of their input

An edge is deterministic *as a function of what it is given*, not in the
absolute. The commit chunking plan is judgment and comes from a node; executing
that plan is not judgment and belongs on an edge. Functional core, imperative
shell — the nondeterminism is quarantined in the edge's input, which is what
makes replay testing possible at all.

Edges may carry state across crossings — attempt counts, the lint baseline — but
that state lives on disk and in git, never in an agent's context.

Contract: `cp-edge-contract-vm6`.

## A node's interior is unconstrained

Inside a node, an agent may explore, backtrack, and iterate as freely as it
likes. The discipline governs transitions between *committed units of work*, and
nothing else. This is not a constraint on how agents think; it is a constraint on
how their conclusions become facts.

## Isolation: what a node can see and do

The interior of a node is free; its boundary is not. The boundary is where
"author is never judge" is either real or theatre.

**Isolation is a property of the process, not of the model.** Each node is a
separate `claude -p` invocation with a fresh context window. Nodes cannot share
state, so "will it remember" is the wrong question — the only question is what
bytes the runner puts in. A node never *inherits* context; it *receives a
manifest* assembled by a deterministic script. That is what makes isolation
testable rather than hoped for: you can assert on the exact input set.

```bash
cd "$WORKTREE" && claude -p \                       # cwd is part of the contract
  --system-prompt-file nodes/reviewer/system.md \   # replace, never append
  --allowedTools 'Read,Grep,Glob,Bash(git diff:*),Bash(git show:*)' \
  --disallowedTools 'Edit,Write,Bash(git push:*),Bash(git merge:*),Bash(br *)' \
  --strict-mcp-config \
  --disable-slash-commands \
  --add-dir "$WORKTREE" \
  --settings nodes/reviewer/settings.json \         # PreToolUse hook, the backstop
  --output-format json \
  input-manifest.json
```

`--system-prompt` rather than `--append-system-prompt`: appending leaves the
default agent prompt underneath, with behaviours nobody chose or audited.
`--strict-mcp-config` because otherwise every ambient MCP server is live inside
every node — here that means Gmail, Drive, Calendar and Chrome, and a Reviewer
that can send email is not a Reviewer. **`--resume`, `--continue` and
`--fork-session` are banned outright**; they are the literal
inherit-the-transcript flags, and a node that resumes is not a node.

`cd "$WORKTREE"` is not housekeeping. Auto-memory is keyed by project path, so
the working directory decides whether the operator's memory index is handed to
the node — see "Leaks" below. It is a manifest field with a validator behind it
rather than a line in a launch script, because it is load-bearing.

`--system-prompt-file` is absent from `claude --help` but real, and it validates
the path it is given. That is worth stating because the rest of this section is
a list of flags, and a contract made of flags is worth only as much as the
checking behind it: each one above was probed against the installed CLI rather
than taken from documentation.

The contract is data, not prose: `nodes/node-types.json` holds `launch`
(the banned and required flag lists) and each node's `inputs` whitelist, and
`tests/test_manifest.py` asserts the runner's argv against those lists rather
than against strings copied into the test — so the contract and what runs cannot
drift apart while both look right.

```
nodes/manifest.schema.json   the input manifest — the exact set a node receives
bin/cp-manifest              assemble | check | hash
```

`cp-manifest assemble` is a **whitelist copied out**, never a blacklist deleted:
a forgotten copy omits an input, a forgotten delete forwards one, and only one
of those two mistakes is safe. The manifest hash goes on the transition log at
every node crossing, so *was isolation held* is answerable from the log alone.

### Tools are limited by the launcher, not requested in a prompt

Allowlists are sub-tool scoped — `Bash(git diff:*)` grants exactly that, not
Bash — so the policy is enforceable rather than advisory. Deny by default, with a
`PreToolUse` hook behind the allowlist so a gap in one is not a gap in both.

| Node | Must have | Must not have |
|---|---|---|
| Builder | Edit, Write, `verify --fast` | `git merge`, `git push`, `br close` |
| Reviewer | Read, Grep, `git diff` | Edit, Write, anything mutating |
| Groomer | `br create`, Read | Edit, Write |

Two asymmetries carry the weight. A judge that can edit what it is judging is not
a judge. And the Builder cannot cross its own outgoing edge — the rule the whole
graph rests on stops being rhetorical exactly here.

**An attempted violation is a signal, not just a denial.** It goes on the
transition log carrying `kind: violation` and onto the panel — in the token's
journey, where it reads as what it is: something that happened *at* a vertex
rather than a move between two. It is never counted as a crossing.

The policy lives in `nodes/node-types.json` beside each node's verdict enum, and
`bin/cp-guard` only enforces it. The `--settings` file the launcher passes is
*generated* from that same policy rather than kept next to it: two
hand-maintained copies of one rule is two rules, and the drift shows up on the
day one of them was the lock that mattered.

Two things the guard has to get right that a naive allowlist does not:

**Compound commands.** `Bash(git diff:*)` matched against the head of a command
string would let `git diff && rm -rf .` through. Every segment is matched, and a
segment that cannot be parsed is denied rather than assumed harmless.

**The tools that grant tools.** `ToolSearch`, `Task` and `Agent` are denied at
every node, because a node that can spawn a subagent gets an agent with default
tools — the whole policy bypassed in one call. This is not theoretical: a
Reviewer under this policy, told to edit a file, did not attempt `Edit`. It
attempted `ToolSearch`, to go and fetch `Edit`. Deny-by-default caught it, but
only because nobody had listed `ToolSearch` — which is the kind of safety that
evaporates the first time an allowlist is widened by someone in a hurry. So it
is now an explicit denial and a check in `tools/check-graph.py`.

That probe is also how we know the hook fires at all: a live node under the
generated settings was denied and left a violation row on the log. The gate
itself stays offline — it must run without a model being reachable — so what
`./verify` checks is the policy, the matching, and the shape of the settings the
launcher writes.

### Leaks: blocking the transcript is the easy part

The channels that actually leak are ambient:

| Channel | The leak |
|---|---|
| Working tree | Builder leaves scratch files or notes the Reviewer then reads |
| beads fields | Builder writes issue notes; the Reviewer reads the issue |
| The payload | a free-text field carries an argument for approval |
| `~/.claude` memory | Builder writes a memory; the Reviewer's session loads the index line |
| MCP servers | ambient capability in every node |
| Commit messages | Builder writes prose aimed at the reviewer |
| Code comments | `// reviewer: this is intentional` |

The memory channel is specific to this setup, and it is narrower than it first
looks — but it is real, and it took measuring rather than reading to establish
which. Probed against the installed CLI:

- A headless run **inside the project directory** is handed the operator's
  `MEMORY.md` **index** verbatim — one Builder-authored line per memory. Memory
  *bodies* are not loaded: a canary string living only in a body came back `NO`.
  So the channel is one line of attacker-controlled free text per memory, which
  is narrow, ample, and pointed in exactly the wrong direction.
- `--system-prompt` does not close it. Neither does `--setting-sources ""`.
- `--bare` does close it — it skips auto-memory outright — but it cannot
  authenticate on an OAuth subscription ("Not logged in · Please run /login"),
  and nodes run on Claude Code rather than on an API key. Redirecting
  `CLAUDE_CONFIG_DIR` fails the same way, since the credentials live there too.
- **Changing the working directory out of the project closes it.** Auto-memory
  is keyed by project path; a run from elsewhere reports `NONE`.

So the closer is cwd, not a flag, which is why the runner puts every node in its
own worktree outside `/mnt/projects` and `cp-manifest check` refuses a manifest
whose `cwd` is inside the project. The general lesson is the one the golden set
exists to teach a level up: a control that was never measured is a control that
is not there.

Two of these cannot be closed, only bounded. Commit messages are part of the diff
and cannot be withheld from a reviewer that must read the diff — so they are
treated as **claims to verify**, never as context to trust. Reviewer-addressed
code comments are the same: undetectable in principle, flaggable in practice
(`cp-leak-audit-z57`).

### The limit worth being honest about

Process isolation buys **information independence**. It does not buy **judgment
independence.** Same weights, same priors, same blind spots — a Reviewer running
the same model as the Builder will tend to accept the same flawed reasoning,
because it would have produced it too. No amount of tool restriction touches
correlated failure.

What helps: run the Reviewer on a different model than the Builder, keep its
authority bounded by deterministic checks it cannot override, and calibrate it
against recorded diffs with known verdicts before granting it any.

So the true hierarchy, which is weaker than "author is never judge" and is the
one this design actually supports:

> **`./verify` is the judge. The Reviewer is a second opinion with restricted
> senses, judging what verify cannot see.**

## The graph

Agent nodes in `[brackets]`, human nodes in `(parens)`, edges are the arrows.

```
  br ready ──▶ [Builder] ──▶ verify --fast ──▶ commit-per-plan ──▶ [Reviewer]
                                                                        │
                            merge ◀── verify --full ◀────── approve ◀────┘
                              │
                              ▼
                           br close
```

That is the happy path. Every other outcome is an edge to somewhere else:

| From | Verdict | To | Why |
|---|---|---|---|
| `verify --fast` | exit 1 | `[Repair]` | a check failed; that is work |
| `verify --fast` | exit 2 | `(Human)` | the gate is broken, which is not the same as red |
| `[Repair]` | — | `verify --fast` | retry, attempt count +1 |
| `[Repair]` | budget exhausted | `(Human)` | three tries is a signal, not a reason to try again |
| `[Reviewer]` | `reject` | `[Repair]` | with findings as payload |
| `[Reviewer]` | `charter-question` | `(Human)` | the only sanctioned way to push back on scope |
| `verify --full` | exit 1 | `[Repair]` | |
| `verify --full` | exit 2 | `(Human)` | |
| anywhere | no edge matched | `(Human)` | see below |

**finance-c-and-c runs the same graph with one node inserted:**

```
  ... ── approve ──▶ verify --full ──▶ (Human) ──▶ merge ──▶ br close
```

Nothing else differs. That single inserted node is the whole of "finance always
waits for me" — real money, real tax lots, real wash-sale windows — and it is a
graph fact rather than a policy sentence somebody has to remember.

The definition lives in `nodes/graph.json` and is validated by
`tools/check-graph.py` on every `./verify`: every route must land on something
real, every verdict must select an edge that exists, no name may mean two things,
and every position must be able to reach a terminal. A route to a node that does
not exist is a token deadlocking halfway through a factory, at which point the
useful information is gone.

`bin/cp-run` walks it. It persists token state on every crossing, resumes from a
parked token, and never invokes a model to route — a test asserts that over the
edge scripts rather than trusting the claim. **Live node launch is refused**
until the isolation contract and tool policy exist: a runner that launches nodes
with ambient tools and no manifest is the failure this whole design prevents, and
one that does it quietly is worse than one that will not start
(`cp-runner-3k1`, `cp-graph-def-ans`).

```
bin/cp-run <factory> <token> --dry-run --scenario happy
bin/cp-run --resume <token>              # prints the question
bin/cp-run --resume <token> --answer yes
```

## Autonomy is a property of the graph

This falls out of the model and is the most useful thing in this document:

> **Autonomy level = which nodes on the path are human-occupied.**

"Merge on green, except finance" is not a setting. It means faceoff-finder and
ai-ih-coach have no human node between `verify --full` green and `merge`, and
finance-c-and-c has one. Raising the ceiling for a factory is then a concrete,
reversible operation: **remove one human node from one path, once the edge in
front of it has a track record.** That is measurable — the edge either caught
things or it did not.

It also makes the control plane's founding rule mechanical. *Surfaces decisions,
never diffs* means the decision queue is exactly the set of tokens parked on
human nodes. If a diff reaches Nikita without having sat on a human node first,
that is a missing edge, and the panel is supposed to say so
(`cp-cp-status-khe`).

One consequence worth stating plainly: **faceoff-finder's chosen autonomy level
is not safe yet.** Auto-merge-on-green requires that green means something, and
green there currently means "it imports and it lints". Faceoff detection, clock
reading and jersey identity can each degrade without raising an exception. The
human node stays on that path until the golden set exists
(`cp-golden-set-games-a2f`, `cp-golden-set-harness-f2g`).

## Failure terminals

**No edge matched.** The token stops and reports. An LLM router would have
improvised past the gap and hidden it; a scripted one cannot, so the missing edge
becomes findable. Deadlock here is a feature and is meant to be kept as one
(`cp-deadlock-terminal-3i6`).

**Budget exhausted.** `Repair → verify → Repair` spins forever otherwise. The
attempt count is edge state carried in the token, the budget is declared in the
graph definition, and exhaustion is an edge to a human node — not an exception
(`cp-attempt-budget-8fe`).

**The gate itself is broken.** `./verify` separates exit 2 (unrunnable) from
exit 1 (a check failed), and `bin/verify-all` prints them as different board
lines, because a broken gate must never look like a red gate and must never be
silently retried. Today the graph has no destination for exit 2
(`cp-verify-exit2-destination-3e5`).

## What is already an edge

More of this exists than it looks like. Every one of these is a deterministic
script gating a transition, built before the model above was written down:

| On disk | Role |
|---|---|
| `./verify` (0 / 1 / 2) | the gate edge, with a three-way typed verdict |
| `bin/verify-all` | the same edge across all factories, one exit code |
| `.githooks/pre-push` | the only **enforced** edge |
| `tools/lint_ratchet.py` + baseline | an edge carrying state across crossings |

Two cautions about that table.

`.githooks/pre-push` is enforced against a person, not against a process:
`SKIP_VERIFY=1` and `--no-verify` both bypass it. **The Builder node must run
`bin/verify-all` and check the exit code as an explicit step**, and must never
treat the hook as the gate (`cp-builder-node-0va`).

The lint ratchet keys its nodes by file path — `path/to/file.py::F401`. Rename
that file and the identity breaks: the banked violations vanish rather than
reappearing as regressions, so the ratchet quietly loosens. Stale edges and
broken entity identity are the named failure mode of this entire approach, and
we already have an instance (`cp-lint-ratchet-identity-7or`).

## How this layers with everything else

Three different graphs get conflated constantly. They are not competing:

**The work graph** — beads. What exists, and what order dependencies permit.
`blocks` and `parent-child` edges. A beads issue is the *payload* that travels
the execution graph. Only ai-ih-coach has a real one today: 55 issues, 51 edges,
longest chain 7 deep, zero dangling references. faceoff-finder's equivalent is a
47KB prose file, which is not dispatchable (`cp-beads-faceoff-finder-z7l`,
`cp-beads-finance-c-and-c-a0s`).

**The execution graph** — this document. How one payload moves from ready to
merged.

**Provenance** — needs no separate store. If every transition is a script, the
transition log is the provenance graph, for free (`cp-transition-log-d8r`).

**The code graph** — deliberately not built. faceoff-finder is 73 modules and
129 internal import edges; that is well below the scale where indexing pays for
itself, and grep plus the import smoke test is genuinely fine. Revisit if a
factory grows an order of magnitude. The one place a code-graph query is already
earning its keep is `server/src/invariants.test.ts`, which does an
export-reachability check by regex — and which found `LABEL_STATUSES`
(`coach-5ao`).

The join that is actually missing is between the work graph and the code graph.
33 of 55 ai-ih-coach issues name a file path, but only inside free-text
descriptions, so the Reviewer cannot mechanically check that a diff touched what
the issue claimed it would (`cp-files-edge-e4n`).

## Seeing it

`bin/cp status` is the board; `bin/cp serve` is the same thing in a browser, with
the graph drawn from the definition rather than hand-placed, so the picture
cannot drift from the thing it describes. Tokens light up the vertex they are
sitting on; selecting one highlights its path and lists every crossing; selecting
a node or an edge shows every token that has ever crossed it.

The decision queue is every parked token, across all factories, each rendering
its own question and options — and each answerable in place. That is what makes
*surfaces decisions, never diffs* a thing you can look at rather than a thing to
remember.

Work enters the graph from the panel too: the ready list is dispatchable, and
what may be dispatched is exactly what the tracker calls ready — not any string a
browser can send, and never an epic, because an epic is a container and no single
node can do one.

The picture answers *where is this now* rather than *where has it been*. The full
history drawn over a graph is mostly geometry; every token eventually touches
most of it. So the current position is marked NOW, the vertex it came from is
marked behind it, one arrow is drawn between them, and everything else fades to
context. **The journey is a list** — the order things happened in is the part
worth reading, and a path traced over a diagram only looks like information.
A token can be run again; earlier runs stay in the log but carry their own run
number, because splicing two runs into one path reads as something that never
happened.

A blocked token is meant to be impossible to miss rather than something you go
looking for: a sticky bar across every screen, a count on the factory's tab, a
count in the browser tab title so it reads even when the window is behind
something else, and how long it has been waiting. The bar disappears completely
when nothing is parked — a banner that is always there is one you stop seeing.

Answering from the panel is the only thing in it that changes anything, so it is
the only thing with a surface worth attacking. An answer must be one of the
options that token's own parking node offered; it cannot name an arbitrary edge,
which would be a way to walk a token anywhere in the graph from a browser. And
the answer is recorded with where it came from — months later it matters whether
a person clicked it or a script supplied it.

## What is not in the model yet

Everything above describes the frame. Almost none of it runs:

- **No node runs for real.** The runner walks the graph and records every
  crossing, but only against recorded results — live node launch waits on
  isolation (`cp-runner-3k1`).
- **No node exists.** Reviewer first, deliberately — scaling the author before
  the judge exists is how a factory produces volume nobody can check
  (`cp-reviewer-node-hq3`, then `cp-builder-node-0va`, `cp-groomer-node-pwa`,
  `cp-sweeper-node-rcn`).
- **No charters**, so the Reviewer has nothing to judge "should this exist"
  against and `charter-question` has no referent (`cp-charters-fyn`).
- **Isolation is half enforced.** The manifest exists: what each node may
  receive is declared, assembled by whitelist, hashed onto the transition log,
  and asserted by tests — including that the Builder's payload does not reach
  the Reviewer, and that no node runs where the memory index would reach it.
  The per-node tool policy exists too: declared in the contract, enforced by a
  `PreToolUse` backstop, with denials recorded and surfaced. What is still
  missing is the remaining leak channels — working tree, beads fields, commit
  messages, code comments (`cp-leak-audit-z57`) — and the nodes themselves. The
  refusal in `bin/cp-run` now guards a smaller gap than it did, and dropping it
  is still the last line changed before a live run, not the first.

A note on tooling, since it will come up: **not LangGraph.** It would be a
framework taken on to get conditional edges we would write anyway, and every node
shells out to `claude -p` regardless. A declarative file plus a small runner is a
couple hundred lines and stays inspectable, which is the whole point of the
exercise.

Everything runs on this machine. There is no CI and no remote validation, by
decision — a gate that cannot run where the footage, the venv and the GPU
weights live is not a gate.
