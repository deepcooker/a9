# A9 Session Causal Memory

This document is the rolling causal spine for A9. It is not a raw transcript and
not a normal summary. It records how the project changed, why it changed, which
branches are still valid, and which branches should no longer steer workers.

## Source Of Truth

- raw operator session:
  `/root/.codex/sessions/2026/05/21/rollout-2026-05-21T11-20-49-019e488c-d5f9-7501-835a-bf6e8ff6d8a2.jsonl`
- close reading:
  `docs/session-raw-close-reading.md`
- rolling extract summary:
  `docs/session-raw-summary.md`
- original idea spine:
  `原始想法需求.md`

Every causal claim below should be traceable to a turn/line in the raw close
reading or summary. If a later close-reading batch contradicts this file, update
this file first before starting new worker execution.

## Current Causal State

Current effective mainline:

```text
original trading/philosophy idea
-> need a private Codex-like agent platform before finance work
-> copy mature projects instead of inventing
-> build a 24-hour execution machine as infrastructure
-> discover context/session loss as the core long-run risk
-> add raw session governance and deterministic memory refresh
-> discover remote/mobile control is needed for operator continuity
-> pull back from UI polish to stable communication/runtime governance
-> discover monitor quality depends on a real methodology, not score labels
-> refactor MoE monitor into a lightweight requirements review council
-> lock product acceptance as data first, performance second
```

Immediate active constraint:

```text
Communication work may resume only as bounded slices observed by the new
requirements-review monitor. Each slice must prove data/state/event/schema
correctness first and performance/stability second.
```

## Causal Timeline

### 1. Original End Goal Became Infrastructure First

- Original intent: build a private financial/quant model and eventually a
  financial Codex.
- Problem discovered: without a stable Codex-like runtime, the project cannot
  continuously copy, test, validate, and generate training evidence.
- Resulting decision: first build A9 as a private agent client/runtime and
  24-hour execution machine.
- Evidence: `docs/session-raw-summary.md` Batch 1, `原始想法需求.md`.

Current status:

- Still valid.
- Finance/quant work remains downstream.
- Any worker task that starts doing trading strategy before platform/runtime is
  stable is off-mainline.

### 2. "Copy Copy Copy" Became The Engineering Law

- Original instinct: do not rely on our own cleverness; first copy the best
  mature projects.
- Problem discovered: one project is not enough; Codex, OpenClaw/Lobster,
  Aider, LangGraph, mem0, Barter-rs and others each cover different mechanisms.
- Resulting decision: reference_scan -> mechanism_extract -> vendor_import ->
  implement -> test -> record -> repair is mandatory.
- Evidence: `AGENTS.md`, `docs/vendor-strategy.md`,
  `docs/reference-selection-reassessment.md`.

Current status:

- Still valid.
- Claude Code and Antigravity remain product references unless an open source
  repo/license is confirmed.
- Aider is not Lobster/OpenClaw; OpenClaw/Lobster is the runtime/workflow
  reference.

### 3. Page Monitoring Was Downgraded From Architecture To Fallback Entry

- Original idea: monitor the current Codex interaction page and continue when
  it stops.
- Problem discovered: the current external Codex window cannot be strongly
  controlled, and page monitoring is fragile and hard to govern.
- Resulting decision: page/TUI monitoring is a fallback entrance only. The real
  controllable architecture must be A9 runtime: tasks, runs, Redis/MySQL state,
  evidence, and deterministic commands.
- Evidence: `docs/session-raw-summary.md` turns 186-257.

Current status:

- Still valid.
- Mobile/control plane is important, but not because UI polish is the runtime.
  It matters because it carries the operator session and command surface.

### 4. Session Governance Split Into Two Different Problems

- Problem discovered: Codex `/compact` helps the next conversation continue,
  but it can lose causal details needed by a long-running machine.
- Resulting decision: split sessions:
  - external Codex/operator session: raw JSONL, close reading, causal memory,
    compact drift, continuation.
  - A9 runtime session: tasks, runs, flow, patches, checks, evidence.
- Evidence: `docs/session-raw-summary.md` turns 112-131 and 186-190.

Current status:

- Still valid.
- Raw session does not go directly into mem0.
- mem0-shaped memory should store extracted memories with evidence references.
- The missing piece was this causal memory layer.

### 5. 24-Hour Worker Became Execution Engine, Monitor Became Mainline Guard

- Problem discovered: a worker can execute but will drift without active
  product/architecture/test/business supervision.
- Resulting decision: worker executes bounded copy tasks; monitor reads intent,
  prompt, session-query behavior, exec behavior, token/log growth, diff, tests,
  and intervenes.
- Evidence: `docs/session-raw-summary.md` turns 258-283.

Current status:

- Still valid.
- Do not let worker continuously run if its prompt, query method, or next task
  is not aligned with the current causal state.

### 6. Communication Governance Became The Next Runtime Slice

- Problem discovered: mobile and multi-terminal control are useless if the
  underlying connection/reconnect/heartbeat/state path is unstable.
- Resulting decision: communication governance should copy mature gateway
  mechanisms, especially Rust + Redis + Barter-rs-style reconnect/error
  handling, with SSH/Tailscale/tmux as onboarding/fallback.
- Evidence: `docs/session-raw-summary.md` turns 246-257 and 263-283,
  `docs/communication-governance-framework.md`.

Current status:

- Still valid, but temporarily blocked behind monitor methodology.
- The queued communication handler task should not run until MoE review can
  evaluate drift and acceptance properly.

### 7. MoE Review Changed From Score To Requirements Review Council

- Problem discovered: a "MoE score" with several labels is not a methodology.
  It misses product manager, mainline, progress, test, architecture, business,
  exception, and execution-governance perspectives.
- Trigger: user stopped worker and pointed to the 20-year financial systems
  requirements guide.
- Resulting decision: A9 monitor must become a lightweight requirements review
  council with hard gates, not an average score.
- Evidence: `docs/session-raw-summary.md` turns 287-292,
  `docs/requirements-guide-close-reading.md`,
  `docs/moe-review-methodology.md`.

Current status:

- Implemented as `requirements_review_council_v1`.
- Current monitor includes product mainline, external learning, product
  pressure, data model, performance depth, test verifiability, security,
  exception, and execution governance gates.

### 8. Product Standard Became Data First, Performance Second

- Problem discovered: product/architecture judgment cannot be reduced to code
  shape. Real business structure is primarily reflected by data, tables, state,
  events and schema; UI/API are projections of that structure.
- Resulting decision: A9 acceptance order is data first, performance second.
  Other engineering concerns are subordinate.
- Important nuance: data structure is the main business skeleton, but not the
  whole product. Permissions, workflow, exceptions, timing and user behavior
  still need coverage.
- Evidence: latest operator instruction after MoE refactor.

Current status:

- Active hard rule.
- Tests must validate data/schema/state/event structure when a task is data
  sensitive.
- Performance/stability/latency/budget is the second standard and must not hide
  a wrong data model.

### 9. Gate Discipline Was Reframed As Observe First, Block Later

- Problem discovered: repeated fixed numeric gates and token/line limits slowed
  the project while the business/data/architecture shape was still moving.
  The user repeatedly challenged why a number such as 80, 100, or 120 should be
  trusted without a standard.
- Resulting decision: before the product shape is stable, gates should observe,
  explain, and collect intervals. They become hard blockers only for fact-source
  corruption, unsafe/destructive operations, scope/license violations, missing
  declared tests, or unrecoverable state.
- Evidence: `docs/session-raw-summary.md` turns 313-322, 333-342, 363-370,
  391-395.

Current status:

- Active hard rule in `AGENTS.md`.
- This also explains why audit/review should be async sidecar by default:
  collect evidence without slowing the hot path.

### 10. Communication Control Stage Reached Summary Boundary

- Problem discovered: A9 kept drifting between feature work and methodology
  work. The user asked to finish the communication/control slice and then
  summarize before continuing.
- Resulting decision: the communication/control slice is usable enough to stop
  feature expansion and summarize. Completed capabilities include canonical
  communication status, action plan, bounded repair, recovery-loop observation,
  suggestion queue, async suggestion review, and mobile controls.
- Evidence: `docs/session-raw-summary.md` turns 443-452,
  `docs/stage-handoff-2026-06-01.md`,
  `docs/communication-observation-log.md` entries 88-96.

Current status:

- Active summary boundary.
- Do not continue adding communication features until session memory and causal
  consolidation are updated.

### 11. Session Close Reading Became The Required Next Mainline

- Problem discovered: after many implementation turns, the primary risk was no
  longer a missing endpoint. It was idea drift: old directions, new features,
  gate debates, mobile control, communication runtime, and future Hermes-like
  automation were mixing in context.
- Resulting decision: before the next implementation slice, A9 must run
  external Codex/operator session incremental close reading, then manually
  curate causal memory, idea iteration details, observed problem analysis, and
  noise removal.
- Evidence: `docs/session-raw-summary.md` turns 453-454.

Current status:

- Deterministic extraction now covers turns 293-454 with approximate line
  anchors in `docs/session-raw-summary.md` and
  `docs/session-raw-close-reading.md`.
- This deterministic extraction is only an index. The monitor still has to
  curate causal changes and decide which roles see which memory.

### 12. Role Knowledge Is Not Automatic

- Problem discovered: the user asked whether the things extracted by close
  reading are actually known by the different roles. The answer is no: a role
  only knows what its prompt, repo map, task packet, memory retrieval, or control
  API explicitly injects.
- Resulting decision: close-reading output must become role-scoped memory, not
  just markdown. Roles need a memory distribution layer:
  - product/mainline role sees causal memory, original idea doctrine, current
    summary boundary, and expired branches.
  - architecture role sees data shape, runtime state, communication/session
    boundaries, and reference mechanisms.
  - test role sees acceptance contracts, schema/state evidence, declared checks,
    and known failure modes.
  - execution worker sees only bounded task, relevant doctrine, selected
    evidence, allowed paths, and reference slices.
  - monitor role sees all of the above plus drift/quality observations.
- Evidence: `docs/session-raw-summary.md` turn 454.

Current status:

- Not implemented as a routing layer yet.
- Until this exists, the monitor must explicitly inject the needed summary and
  causal anchors into each worker task. Otherwise roles will repeat old errors.

### 13. Resident Goal Continuation Can Fight Session Governance

- Problem discovered: while running the session mini-flow for turns 293-454, the
  resident supervisor started a `goal-continuation` worker that consumed model
  tokens and ignored the immediate instruction to finish close reading first.
- Resulting decision: session governance and summary tasks need an exclusive
  mode or pause flag for resident goal continuation. Running close-reading with
  another auto-next loop alive can create duplicate close-reading tasks and
  unrelated worker execution.
- Evidence: current run on 2026-06-01 paused
  `.a9/tasks/paused/goal-continuation-goal-A9-24h-agent-runtime-Codex-Herme-09ec03f5c3-20260601T100112Z.*`.

Current status:

- Operationally mitigated by pausing the queued/running goal-continuation task.
- Needs a real fix before Hermes-like旁路 automation: scheduler lanes must be
  explicit, and session-refresh lanes must suppress unrelated goal continuation.

## Expired Or Downgraded Branches

- "Just build the finance model now": expired for current phase. Finance is a
  downstream vertical layer.
- "Page monitoring is the main architecture": expired. It is a fallback/control
  entrance.
- "Mobile is just approval UI": expired. Mobile must cover operator session,
  supervisor status, run summary, command submission, and continuation.
- "A single MoE score can judge worker quality": expired. Need multi-role
  gates and explicit reasons.
- "Raw session summary is enough": expired. Need raw evidence + close reading +
  causal memory + decision updates.
- "Let worker run continuously by default": downgraded. Continuous execution is
  allowed only when the current causal state, task scope, and monitor gates are
  aligned.
- "Every role automatically knows close-reading results": false. Role prompts
  and memory retrieval must explicitly receive the scoped memory they need.
- "Goal continuation can run during any summary operation": downgraded. Session
  governance needs an exclusive/priority lane to avoid drift and duplicate work.

## Active Decisions

1. A9 is currently an infrastructure project, not a trading strategy project.
2. Reference-first copying is mandatory.
3. External operator session and A9 runtime session stay separate.
4. `session_refresh` and `session_close_reading` produce evidence, but causal
   memory must be curated after each meaningful batch.
5. Monitor/MoE methodology is upgraded; use it to observe next worker slices.
6. Communication governance remains the next large runtime slice, but each task
   must satisfy data-first and performance-second acceptance.
7. Mobile/control plane remains product-critical but should not pull the current
   engineering line back into UI polish.
8. Close-reading outputs are not role knowledge until routed into role-scoped
   prompt/memory packets.
9. Hermes-like automation should be designed as sidecar lanes with explicit
   scheduler priority and memory routing, not as another free-running worker.

## Required Post-Close-Reading Procedure

After each incremental close-reading batch:

1. Update `docs/session-raw-summary.md` with extract coverage and turn/line
   anchors.
2. Update this file with causal changes:
   - what changed
   - why it changed
   - which old branch expired
   - what is now active
   - what worker must not do next
3. Update `docs/project.md`, `AGENTS.md`, or `docs/collaboration.md` only when
   a causal change affects execution rules.
4. If the current queue conflicts with this file, pause or rewrite the queued
   task before running worker.
5. Commit the close-reading, causal memory, and rule changes before resuming
   worker execution.

## Next Bounded Task

Discuss and design the Hermes-like sidecar automation and role-memory routing
before resuming feature implementation:

```text
close-reading evidence
-> causal memory
-> role-scoped memory packets
-> async sidecar evaluators/reviewers
-> monitor decision
-> bounded worker task
```

Only after that should A9 resume communication governance or multi-machine
SSH/Tailscale/tmux stability work.
