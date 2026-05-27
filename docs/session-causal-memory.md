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
```

Immediate active constraint:

```text
Do not resume broad communication feature work until the MoE/monitor gate is
method-driven enough to block drift and shallow worker execution.
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

- Current top priority.
- Existing `a9_monitor.py` MoE observer is only a prototype and should be
  refactored before broad worker continuation.

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

## Active Decisions

1. A9 is currently an infrastructure project, not a trading strategy project.
2. Reference-first copying is mandatory.
3. External operator session and A9 runtime session stay separate.
4. `session_refresh` and `session_close_reading` produce evidence, but causal
   memory must be curated after each meaningful batch.
5. Monitor/MoE methodology must be upgraded before resuming broader worker
   automation.
6. Communication governance remains the next large runtime slice after the MoE
   gate is fixed.
7. Mobile/control plane remains product-critical but should not pull the current
   engineering line back into UI polish.

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

Refactor the monitor/MoE implementation according to
`docs/moe-review-methodology.md`:

```text
requirements-review experts
-> hard gates
-> explicit reasons and evidence refs
-> block/continue decision
-> tests proving shallow score-only behavior is no longer accepted
```

Only after that should A9 resume the queued communication governance handler
test and the multi-machine SSH/Tailscale/tmux stability line.
