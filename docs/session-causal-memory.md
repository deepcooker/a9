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
  API explicitly injects. This also applies to a new interactive Codex control
  window: it does not inherit project truth unless it reads the handoff order.
- Resulting decision: close-reading output must become role-scoped memory, not
  just markdown. Roles need a memory distribution layer:
  - operator/main Codex window reads the handoff order in
    `docs/role-memory-governance.md` before deciding or dispatching work.
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
- For interactive takeover, `docs/role-memory-governance.md` is now the required
  read protocol.

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

### 14. Too Many Docs Can Corrupt The Mainline

- Problem discovered: after repeated session close-reading, runtime experiments,
  mobile/control work, communication governance, MoE review and worker repair,
  the repository accumulated many markdown files. A worker that reads all docs
  broadly can treat raw evidence, old task packets, research drafts, UI detours
  and current requirements as the same authority level.
- Resulting decision: context cleanup is part of requirements analysis, not
  polish. A9 now has an explicit context routing table:
  `docs/context-governance.md`.
- Current worker rule: default context is only `AGENTS.md`,
  `docs/context-governance.md`, `docs/project.md`, and the current task
  prompt/plan/decision packet. Raw session files, observation logs, mistakes,
  research docs and archived original ideas require an explicit bounded slice.
- Noise policy: preserve raw facts, but archive/label stale branches and delete
  scratch files with no factual value. Code noise follows the same rule: unused
  paths become observation/repair first, then deletion only after there is no
  current task, test, runtime evidence, or documented owner.
- Evidence: `worker-output.txt` contained only `done` and was deleted as trivial
  scratch noise. `docs/README.md` was narrowed to route workers through the
  context governance entry instead of broad markdown discovery.

Current status:

- Implemented as documentation and prompt discipline.
- Not yet implemented as a supervisor-enforced doc read policy.
- Next enforcement should make worker task prompts include a bounded evidence
  plan and should observe broad reads against `docs/context-governance.md`.

### 15. Requirements Method Became The Root Of Agent Work

- Problem discovered: even a technically working 24h worker produces poor
  quality if it lacks a method for understanding requirements, product
  intention, data model, state flow, exception flow, and acceptance. The user
  emphasized that enterprise delivery quality often comes from requirements
  discussion and alignment before engineering, not from more code.
- Resulting decision: the 20-year requirements analysis method is A9's root
  method. Copying projects, audit sidecars, Rust/Redis, plan files and graph
  memory are supporting mechanisms, not replacements for requirements
  analysis.
- Evidence: `docs/session-raw-summary.md` turns 455-463 and 489-498,
  `docs/requirements-guide-close-reading.md`,
  `docs/worker-method-packet.md`.

Current status:

- Active.
- Any worker task that starts from a solution name instead of a real problem,
  data/state model, exception flow and acceptance is not execution-ready.

### 16. Role Memory And Plan Ownership Were Reframed

- Problem discovered: close-reading output does not automatically become role
  knowledge. A new main Codex window, product role, architecture role, test
  role and worker all know only what their prompt/handoff/memory packet gives
  them.
- Resulting decision: A9 needs shared evidence but role-scoped packets:
  product/mainline sees the most, architecture sees data/state/boundaries,
  test sees acceptance and failure modes, execution worker sees bounded task
  evidence only, and monitor sees drift/quality/execution chain.
- Further decision: planning-with-files is useful for file-based work memory
  and recovery, but A9 must not copy its agent-owned plan model. Product,
  requirements and monitor own the plan contract; worker may append findings,
  progress, mistakes and change requests.
- Evidence: `docs/session-raw-summary.md` turns 455-465,
  `docs/role-memory-governance.md`,
  `docs/role-memory-reference-scan.md`,
  `docs/requirements-plan-file-reference-scan.md`,
  `docs/reference-adoption-decision.md`.

Current status:

- Active as documentation and task discipline.
- Still missing as a fully enforced supervisor lane.
- Workers must not silently modify goal, scope, acceptance or plan authority.

### 17. Graph/Wiki Memory Is A Derived Layer, Not Hot Context

- Problem discovered: plan files help current task recovery, but they do not
  solve long-horizon knowledge, contradictions, stale branches, wiki topics or
  graph retrieval.
- Resulting decision: GBrain, GraphRAG, Graphify and LLM-Wiki are long-term
  derived-memory references. They may compile facts, citations, gaps, schema
  and contradiction reports from raw evidence. They should not become worker
  hot-path context or replace raw session/run/git/test evidence.
- Evidence: `docs/session-raw-summary.md` turns 461-462,
  `docs/memory-graph-wiki-reference-scan.md`,
  `docs/reference-adoption-decision.md`.

Current status:

- Reference layer accepted.
- Implementation deferred until plan lane and role packets are stable.

### 18. Highest Product Shape Expanded To Agent OS Ecosystem

- Problem discovered: A9 was drifting between mobile UI, communication runtime,
  24h worker and future finance. The user reframed the final product as a
  broader ecosystem: private top-level network gateway, elastic private
  networks, private intelligence layer, trading base, 24h worker, mobile app,
  and compute scheduling.
- Resulting decision: A9's highest shape is now:
  `private Agent OS + financial trading infrastructure control plane + private
  compute/model scheduler + ResearchOps/training data loop`. NZX RWA is the
  first heavy business line.
- Evidence: `docs/session-raw-summary.md` turns 569-571,
  `/mnt/e/WSL_Share/NZX_RWA_Orderbook_Appchain_最终方案 (3).md`,
  `/mnt/e/WSL_Share/NZX_RWA_技术实现全景图.svg`,
  `docs/a9-ultimate-architecture-aggregation.md`.

Current status:

- Active aggregation draft, not final architecture decision.
- Do not let this broaden into feature sprawl before a decision packet closes
  the next execution slice.

### 19. Mobile Became Control Plus Trading Workspace

- Problem discovered: describing mobile as monitor/approval/control is too
  narrow. The phone must carry the Codex-like operator conversation, but it
  also needs real menus for trading, nodes, strategies, assets, risk, compute,
  models and data.
- Resulting decision: mobile has two layers:
  - chat/control layer remotely connects into private-network A9 servers and
    carries the main operator session.
  - workspace/menu layer hosts real trading and Agent OS functions, with
    permission, attestation, audit and confirmation for high-risk actions.
- Evidence: `docs/session-raw-summary.md` turns 572-574,
  `docs/a9-ultimate-architecture-aggregation.md`.

Current status:

- Active product requirement.
- UI should copy GPT mobile/Codex interaction patterns, but canonical state
  stays in A9 API/Redis/MySQL/run/session evidence.

### 20. Compute Scheduler And Compute RWA Split

- Problem discovered: A9 needs a private compute/model scheduler for 4090,
  possible multi-GPU expansion, model serving and 200GB+ image/weight startup.
  Separately, `弹性算力选型.md` introduced a compute-token/DePIN/RWA business
  flywheel.
- Resulting decision:
  - compute scheduler is an infrastructure layer to research: GPU Operator,
    KAI/Run:ai lineage, vLLM/SGLang/NIM/Dynamo, Ray/KubeRay/Argo, warm pools,
    local weight cache and image pre-pull.
  - compute RWA/tokenomics is only a high-risk business candidate requiring
    legal/compliance, asset audit, proof-of-capacity/proof-of-compute and
    tokenomics stress testing.
- Evidence: `docs/session-raw-summary.md` turns 570 and 573,
  `/mnt/e/WSL_Share/弹性算力选型.md`,
  `docs/a9-ultimate-architecture-aggregation.md`.

Current status:

- Compute scheduler belongs in highest architecture research.
- Compute RWA does not enter execution and must not be treated as validated
  revenue/ROI.

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
- "Every markdown file is useful worker context": expired. Docs now need
  canonical/evidence/research/archive/noise routing.
- "planning-with-files can be copied wholesale": expired. A9 copies recovery
  and file-memory mechanisms, not worker ownership of plan goals/acceptance.
- "Graph memory should replace close reading": expired. Graph/wiki memory is a
  derived index over raw evidence and curated causal memory.
- "Mobile is only chat/monitor": expired. Mobile is chat/control plus trading
  and Agent OS workspaces.
- "Compute tokenomics is compute technical selection": false. It is a business
  candidate requiring separate compliance and asset review.

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
10. Context cleanup is a requirements-analysis duty. Noisy docs and stale code
    can bias execution and must be routed, archived, or removed before long-run
    worker execution.
11. Plan contracts are owned by human/product/requirements/monitor roles.
    Execution workers can append findings/progress/mistakes/change requests,
    but cannot silently change goal, scope or acceptance.
12. A9 highest-shape aggregation is now captured in
    `docs/a9-ultimate-architecture-aggregation.md`, but remains a draft for
    debate and GPT/web reconstruction, not a decided implementation plan.
13. The next architecture decision must account for NZX RWA, mobile trading
    workspace, private compute scheduler, role-scoped memory, and the original
    trading-philosophy/data-validation spine together.

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
4. Update `docs/context-governance.md` or `docs/README.md` when a causal change
   changes which documents are current truth, evidence, research, archive, or
   noise.
5. If the current queue conflicts with this file, pause or rewrite the queued
   task before running worker.
6. Commit the close-reading, causal memory, and rule changes before resuming
   worker execution.

## Next Bounded Task

Close the highest-shape architecture decision before resuming feature
implementation:

```text
incremental close-reading evidence
-> causal memory update
-> A9 ultimate architecture aggregation
-> GPT/web reconstruction and human debate
-> decision packet
-> bounded worker task
```

Only after that should A9 resume communication governance, mobile control,
compute scheduler, or multi-machine SSH/Tailscale/tmux stability work.
