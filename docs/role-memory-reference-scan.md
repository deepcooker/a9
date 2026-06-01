# Role Memory Reference Scan

This document exists because A9 must not finalize role memory, sidecar review,
or 24h agent governance from our own intuition alone.

The rule is reference first:

```text
reference_scan
-> mechanism_extract
-> A9 interpretation
-> provisional decision
-> implementation slice
```

## Current Question

Close-reading the Codex/operator session produced useful causal memory, but it
does not automatically improve every actor.

The real question is:

- What should the main Codex/operator window know?
- What should the 24h worker know?
- What should product, requirements, architecture, test, monitor, and reviewer
  roles know?
- How do we keep long-running work from losing causal details while still
  controlling prompt size?
- How do we keep review/learning async so it does not slow the hot path?

## Reference Evidence

### Hermes

Local evidence:

- `reference-projects/hermes-agent/agent/background_review.py`
- `reference-projects/hermes-agent/agent/curator.py`
- `reference-projects/hermes-agent/datagen-config-examples/trajectory_compression.yaml`

Mechanisms worth copying:

- Background review forks after a turn and replays a conversation snapshot.
- The review fork can write to memory and skill stores.
- The main conversation and prompt cache are not touched.
- The review tool surface is restricted to memory/skill management.
- Memory review saves stable user preferences, behavior expectations, and
  reusable facts.
- Skill review updates class-level reusable skills, not one-off transient
  session tricks.
- The curator periodically promotes, archives, consolidates, pins, and reports
  agent-created skills.
- The curator is inactivity-triggered and uses an auxiliary model/client.
- It archives instead of auto-deleting.
- Compression protects first system/user/assistant/tool evidence and recent
  tail turns, then compresses the middle under budget.

A9 interpretation:

- Sidecar review is the right shape, but it must be旁路 and async.
- The sidecar may propose memory commits, skill updates, or drift reports.
- The sidecar must not mutate the main runtime prompt directly.
- The sidecar needs a restricted tool surface.
- A9 should separate stable doctrine from transient execution tricks.
- Compression should preserve head, tail, tool evidence, and explicit remaining
  work; summary is an index, not the truth.

### Codex

Local evidence:

- `reference-projects/codex/sdk/python/src/openai_codex/api.py`
- `reference-projects/codex/sdk/python/docs/api-reference.md`
- `reference-projects/codex/codex-rs/state/src/runtime/goals.rs`

Mechanisms worth copying:

- Thread APIs expose `read(include_turns=...)`, `compact()`, and turn-level
  summaries.
- Compact is explicit, not invisible.
- Goals are persisted as state with `goal_id`, status, token budget fields, and
  expected-id style update safety.
- Goal lifecycle can pause or mark usage-limit states.

A9 interpretation:

- A9 should keep raw event/thread evidence separate from compact summaries.
- Compact is a handoff artifact, not canonical truth.
- Long-running work needs persistent goal state, pause/resume, usage-limit
  status, and expected revision/identity checks.
- A new main Codex/operator window must read handoff docs and causal memory
  explicitly; it does not inherit project truth from previous chat context.

### LangGraph

Local evidence:

- `reference-projects/langgraph/README.md`

Mechanisms worth copying:

- Durable execution for long-running stateful agents.
- Human-in-the-loop interrupt and resume.
- Short-term working memory and long-term persistent memory.
- Observability/traces for debugging.

A9 interpretation:

- A9 role memory should be tied to managed state/checkpoints, not loose prompt
  text.
- Human intervention is part of the runtime state machine.
- Traces are first-class evidence for later close-reading and training data.

### mem0

Local evidence:

- `reference-projects/mem0/LLM.md`

Mechanisms worth copying:

- `add`, `search`, `get`, `get_all`, `update`, `delete`, `history` memory
  semantics.
- Memory can be scoped by `user_id`, `agent_id`, and `run_id`.
- Multi-agent examples share a memory layer while preserving agent/run scope.

A9 interpretation:

- A9 should not dump raw Codex sessions into mem0-shaped memory.
- mem0-shaped memory should store extracted memories with evidence references.
- `agent_id` and `run_id` style scoping maps well to role packets.
- `history` is useful for causal变迁, not only final facts.

### Aider

Local evidence:

- `docs/copied-mechanisms.md`
- `docs/patch-diff-discipline.md`

Mechanisms worth copying:

- Repo map instead of full repository dump.
- Recent tail preservation.
- Architect/editor separation.
- Strict edit discipline.

A9 interpretation:

- Workers should receive bounded repo maps, relevant source slices, and task
  evidence, not the entire memory lake.
- Product/architecture can hold broader context; execution gets the narrow
  slice needed to act.

### OpenClaw / Lobster

Local evidence:

- `docs/copied-mechanisms.md`
- `docs/runtime-governance-review-2026-05-29.md`
- `docs/session-causal-memory.md`

Mechanisms worth copying:

- Managed flow state.
- Approval/wait/resume envelope.
- Policy attestation.
- Tool and extension boundaries.

A9 interpretation:

- Memory injection must be part of managed flow state.
- A role packet should be auditable: which evidence, which doctrine, which
  role, which task, which expected revision.
- Review and approval should produce state transitions, not hidden comments.

## What We Should Not Copy Blindly

- Hermes background review cannot become a hot-path blocker.
- Codex compact cannot replace raw evidence, memory commits, or causal变迁.
- mem0 memory cannot be treated as the only source of truth.
- LangGraph's conceptual memory/checkpoint model does not by itself solve A9's
  role-prompt budgeting.
- OpenClaw/Lobster-style workflow does not remove the need for product/mainline
  judgment.
- Fixed numeric prompt/token/line gates should not be hard blockers before the
  business shape and data model are stable.

## Provisional A9 Design

The reference scan supports this shape:

```text
raw evidence
  - Codex/operator session JSONL
  - A9 runtime tasks/runs
  - git commits/diffs
  - tests/logs/traces
  - reference slices

memory commit
  - extracted fact
  - causal change
  - evidence refs
  - author/source
  - confidence/status
  - supersedes/expired links

role packet
  - global doctrine needed by all roles
  - role-specific responsibility
  - task-specific evidence
  - known mistakes/drift
  - acceptance checks
  - prompt budget

role action
  - product/mainline decision
  - requirement shaping
  - architecture/data/state design
  - execution patch
  - test/QA review
  - monitor intervention

sidecar review
  - async review
  - memory proposal
  - skill/doctrine proposal
  - drift report
  - curator promotion/archive/consolidation
```

## Role Knowledge Distribution

The main Codex/operator window and Product/Mainline role get the broadest
context because they hold direction, causal变迁, and priority.

Requirements Analysis is not product-only. It is a project method every role
must respect:

- background and purpose
- current system boundary
- normal and exception flows
- data/state/event contracts
- dependencies
- acceptance criteria
- traceability to evidence

Architecture focuses on data first and performance second:

- canonical data shape
- state machine
- event flow
- cache/projection boundary
- hot path versus sidecar
- latency/reliability budget

Test/QA validates more than endpoint success:

- data shape
- state transitions
- exception path
- permission/audit path
- reproducibility

Execution worker receives the narrowest packet:

- task
- repo map
- selected reference slice
- selected doctrine
- concrete checks
- evidence paths

Monitor receives:

- task intent
- prompt packet summary
- worker commands/results
- session/run evidence
- drift signals
- intervention rules

## Decisions Still Not Final

These require another implementation slice or real run evidence:

- exact memory commit schema
- exact role packet file/API format
- whether memory commits live first in files, MySQL, Redis, or a hybrid
- how sidecar review is scheduled without competing with active workers
- which role packet fields are required versus optional
- how much of the requirements-analysis guide becomes machine-checkable

## Next Slice

Do not add more hard gates first.

The next practical slice should be:

1. Define a minimal plan/task artifact from
   `docs/requirements-plan-file-reference-scan.md`.
2. Generate `role_packet` artifacts from that plan, existing docs, and evidence.
3. Generate packets for `operator`, `product_mainline`, `requirements`,
   `architecture`, `test`, `monitor`, and `execution_worker`.
4. Keep sidecar review in observe/propose mode only.
5. Run one 24h worker task using a generated execution packet.
6. Let monitor inspect prompt, commands, output, tests, drift, and memory
   proposal quality.

Only after that run should A9 decide which checks deserve to become hard
runtime policy.
