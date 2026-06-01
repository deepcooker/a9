# A9 Role Memory Governance

## Decision

Close-reading, causal memory, and requirements analysis do not automatically
raise worker quality. They only help when each role receives the right memory
projection before it acts.

A9 should use one unified evidence/cache layer, but not one shared prompt.

```text
raw evidence / session / run / git / tests
-> memory commit
-> role-scoped memory packet
-> role action
-> sidecar review / curator
-> updated memory commit
```

The product/mainline role receives the broadest context. Other roles receive a
compact overview plus their own responsibility slice.

## Why This Exists

During real implementation, A9 accumulated real working rules:

-需求分析方法论 is not only a product-manager method. It is the project method.
- Product/mainline must keep pulling work back to the real business objective.
- Business logic is higher priority than engineering elegance.
- Architecture must validate data first, then performance.
- Data means business objects, tables, schema, state, events, and relationships.
- State is the core business logic carrier.
- Audit/review should be async sidecar by default.
- Fixed gates and token numbers should observe before they block.

These rules came from observing worker errors. They must become role memory, not
just human recollection.

## Reference Mechanisms To Copy

### Codex

Copy:

- raw ordered session/thread history as evidence
- explicit compaction, not silent forgetting
- compact summary as handoff, not truth
- thread/goal lifecycle as state, not hidden chat memory

A9 interpretation:

- raw session stays immutable
- compact/summary is only an index
- role packets must cite evidence paths, turns, run ids, or commits

### Hermes

Copy:

- background review as sidecar, not hot-path blocker
- curator that promotes, archives, consolidates, and reports memory/skills
- trajectory records for review and future training data
- context compressor that protects head/tail and important tool evidence

A9 interpretation:

- sidecar reviewers can inspect after the main action
- curator updates memory commits and role packets
- product/mainline role decides which memories become doctrine
- execution worker does not read full trajectory unless tasked to review it

### OpenClaw / Lobster

Copy:

- managed flow with explicit state
- approval/wait/resume envelope
- policy attestation
- tool/extension boundary

A9 interpretation:

- role memory injection is part of managed flow state
- approval/review is stateful and auditable
- no role should silently mutate shared memory

### Aider

Copy:

- repo map instead of dumping files
- recent tail preservation
- edit-context discipline

A9 interpretation:

- execution worker gets repo map and bounded evidence, not full memory
- role packets must fit the task budget

## Role Packets

### Operator / Main Codex Window

This role is the interactive brain with the human. It is not the same as the
24h execution worker.

It also does not automatically know the project. A new Codex window only knows
what is in its current prompt/context and what it reads from disk.

Receives first:

- `AGENTS.md`
- `docs/README.md`
- `docs/stage-handoff-2026-06-01.md`
- `docs/session-causal-memory.md`
- tail of `docs/session-raw-summary.md`
- tail of `docs/session-raw-close-reading.md`
- `docs/role-memory-governance.md`
- `docs/mistakes.md` tail

Responsibilities:

- reconstruct current mainline before taking action
- distinguish external operator session from A9 runtime session
- decide whether to run session mini-flow before coding
- build role packets for worker tasks
- keep human discussion, product direction, and implementation lanes aligned
- stop resident workers when session governance needs exclusive priority

Required questions:

- What is the current stage and why?
- What did the last handoff say?
- What changed in causal memory since the last implementation?
- Which branches are expired or downgraded?
- Are queue/running services consistent with the current instruction?
- What role packet is required before the next worker task?

Minimum handoff read order:

```bash
python3 scripts/a9_service.py ps
python3 scripts/a9_supervisor.py status
sed -n '1,260p' AGENTS.md
sed -n '1,120p' docs/README.md
sed -n '1,220p' docs/stage-handoff-2026-06-01.md
sed -n '1,420p' docs/session-causal-memory.md
tail -n 220 docs/session-raw-summary.md
tail -n 260 docs/session-raw-close-reading.md
sed -n '1,260p' docs/role-memory-governance.md
tail -n 120 docs/mistakes.md
```

If raw session has advanced beyond the last close-reading turn, run the
deterministic session mini-flow before making a new implementation decision.

### Product / Mainline Role

This role should know the most.

Receives:

- original idea doctrine
- current business objective
- requirements-analysis method
- causal memory
- current summary boundary
- expired/downgraded branches
- progress and priority
- observed worker drift
- user corrections and reasons

Responsibilities:

- pull work back to the mainline
- distinguish real need from proposed solution
- decide must/should/could
- challenge weak plans
- approve major direction changes
- decide when engineering is over-optimizing too early

Required questions:

- What problem are we solving?
- Is this task aligned with the current stage?
- Is this a requirement or just a proposed implementation?
- What is the smallest useful product slice?
- What should be rejected or delayed?

### Requirements Analysis Role

This is project-wide, not only product.

Receives:

- user request
- background and purpose
- current causal memory
- system boundary
- dependency map
- known failure modes

Responsibilities:

- translate user need into system requirement
- define normal flow and exception flow
- record scope, dependencies, and acceptance
- ensure requirements are unambiguous, complete, testable, consistent,
  traceable, and modifiable

Required questions:

- What is the background and purpose?
- What must/should/could be done?
- Which systems, modules, and roles are involved?
- What are inputs, outputs, state, errors, permissions, and audit needs?

### Architecture Role

Receives:

- product/mainline summary
- system requirement
- data model expectations
- state/event contracts
- reference mechanisms
- performance and reliability targets

Responsibilities:

- design data shape first
- design state machine and event flow
- decide canonical store versus cache versus view
- compare schemes by coupling, complexity, risk, and extensibility
- keep audit/review off the hot path unless required for safety

Required questions:

- What data/table/schema/state/event represents the real business structure?
- Which state transition is the core logic?
- What is canonical and what is cache/projection?
- What is hot path, and what is sidecar?
- What performance level proves product depth?

### Test / QA Role

Receives:

- system requirement
- data/state/event contracts
- acceptance criteria
- declared checks
- failure modes and incident notes

Responsibilities:

- verify data structure, not only endpoint success
- classify tests as small/medium/large
- ensure exception and permission paths are covered
- validate evidence and reproducibility

Required questions:

- Does the test check schema/table/state/event correctness?
- Does it prove the business behavior, not just HTTP 200?
- Which abnormal flow is covered?
- Is the declared check sufficient and reproducible?

### Execution Worker Role

Receives least context.

Receives:

- one bounded task
- selected doctrine
- selected evidence paths
- allowed files
- declared checks
- selected reference slices
- strict output contract

Does not receive by default:

- full raw session
- full close-reading documents
- all causal memory
- broad project history

Responsibilities:

- execute the task
- copy reference mechanism when relevant
- implement small patch
- run declared checks
- produce evidence and next slice

Required questions:

- What exact file or behavior do I change?
- What mature mechanism am I copying?
- What check proves this slice?
- What should I not touch?

### Monitor Role

Receives:

- all role packet summaries
- current task/run evidence
- session causal memory
- worker event/command chain
- token/context pressure
- git/test/guard state

Responsibilities:

- detect drift
- intervene and pause
- decide whether to accept, repair, or discard
- write mistakes and memory commits
- keep role packets current

Required questions:

- Did the worker follow the shaped requirement?
- Did it over-engineer or ignore business logic?
- Did it touch the right data/state model?
- Did it run the right checks?
- What should be promoted to memory?

## Unified Cache Layer

A9 should have one canonical memory/evidence layer with multiple views.

Canonical:

- raw external session
- A9 runtime runs
- git commits/diffs
- tests/checks
- reference-source extracts
- causal memory commits
- mistake records

Hot cache:

- Redis Streams for events/tasks
- RedisJSON for current flow/session state
- Redis Search/Tag index for retrieval
- Redis TimeSeries for token/latency/error metrics

Long-term:

- MySQL canonical session, run, evidence, checkpoint, memory_commit tables
- files for large artifacts

Prompt view:

- generated per role and task
- bounded by budget
- cited by evidence id/path/turn/commit

## Memory Commit

Every meaningful close-reading or sidecar review should produce a memory commit:

```json
{
  "memory_commit_id": "mem-20260601-001",
  "source": "external_session",
  "evidence_refs": [
    "session:019e...:turn:454",
    "doc:docs/session-causal-memory.md"
  ],
  "changes": [
    {
      "type": "role_rule",
      "role": "product_mainline",
      "summary": "Product role receives broadest causal context and owns mainline."
    }
  ],
  "expired": [
    "All roles automatically know close-reading output."
  ],
  "role_packets_to_refresh": [
    "product_mainline",
    "requirements",
    "architecture",
    "test",
    "monitor",
    "execution_worker"
  ]
}
```

## Sidecar Automation Shape

Hermes-like sidecar automation should be旁路 and async:

```text
main action completes
-> event/trajectory written
-> sidecar reviewer reads evidence
-> proposes memory_commit / mistake / role_packet update
-> product/mainline or monitor approves promotion
-> curator archives stale memory and pins active doctrine
```

Sidecar must not block hot paths such as communication status or worker command
execution. It may block only promotion into doctrine or role packet refresh.

## Immediate Rule

Before giving any non-trivial worker task, A9 must build a role packet:

```text
task
-> product/mainline reason
-> requirement card
-> architecture data/state contract
-> test acceptance
-> execution boundaries
-> selected evidence refs
```

If this packet cannot be built, the task is not ready for execution.
