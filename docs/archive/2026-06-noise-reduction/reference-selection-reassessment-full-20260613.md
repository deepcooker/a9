# A9 Reference Selection Reassessment

## Decision

After downloading and inspecting the full OpenClaw repository, A9 should change
the copy priority.

This decision is about the A9 infrastructure layer. The 24-hour supervised
execution machine is not the final product; it is the scaffold that repeatedly
runs the method: find references, analyze mechanisms, copy, adapt, test, record,
and continue. The final product remains a private integrated agent similar to
Codex CLI plus OpenClaw: a client/runtime that can pursue goals, write code,
route tools, govern context, and later become the base for a financial Codex.

OpenClaw/Lobster is no longer a side reference. It should be the primary
reference for the 24-hour runtime shape: always-on gateway, extension/plugin
boundaries, managed flows, approval/resume, policy attestation, memory budget,
memory visibility, and agent-friendly tool envelopes.

Codex remains the primary reference for local coding-agent behavior: agent loop,
context management, compaction, event normalization, sandbox/tool execution, and
worker prompt discipline.

Barter-rs is now the primary reference for communication stability and
trading-grade Rust gateway behavior. It should not pull A9 into trading logic at
this stage; it is a mature source for reconnect backoff, typed socket error
actions, audit state replicas, external commands, and disconnect strategy.

Aider remains the primary reference for edit mechanics: repo map, token-aware
source selection, SEARCH/REPLACE discipline, deterministic patch application,
and diff repair. Aider is not the Lobster/OpenClaw reference line.

Redis Stack should be treated as A9's hot control plane, not just a cache. MySQL
can stay the canonical durable store, but task leases, flow transitions,
approval waits, budget stops, health metrics, dedupe, and live monitor events
should move toward Redis Streams, Redis Functions, RedisJSON, RediSearch,
RedisBloom, and RedisTimeSeries.

## Why The Decision Changed

The previous reference order underweighted OpenClaw. The full repository shows a
coherent assistant gateway architecture rather than a small plugin:

- `reference-projects/openclaw/package.json` identifies the project as a
  multi-channel AI gateway, MIT licensed.
- `reference-projects/openclaw/README.md` positions OpenClaw as an always-on
  assistant daemon with channels and `openclaw onboard --install-daemon`.
- `reference-projects/openclaw/extensions/lobster/README.md` describes Lobster
  as a typed JSON-first workflow shell with approvals, resume, and gateway tool
  policy.
- `reference-projects/openclaw/extensions/lobster/src/lobster-taskflow.ts`
  binds workflow execution to managed flows with `createManaged`, `setWaiting`,
  `finish`, `fail`, `expectedRevision`, and approval wait state.
- `reference-projects/openclaw/extensions/lobster/src/lobster-runner.ts`
  normalizes execution into a strict envelope, caps stdout/stderr, rejects cwd
  escape, and models `ok`, `needs_approval`, `cancelled`, and failure.
- `reference-projects/openclaw/extensions/policy/src/policy-state.ts` hashes
  policy, workspace evidence, findings, and final attestations.
- `reference-projects/openclaw/extensions/memory-core/src/memory-budget.ts`
  bounds promoted memory while preserving user-authored content.
- `reference-projects/openclaw/extensions/memory-core/src/session-search-visibility.ts`
  gates session memory search by visibility and agent policy.

That set maps directly onto A9's real problem: a long-running execution machine
with deterministic supervision, resumable waits, bounded context, memory
governance, and auditable policy state.

## Reference Roles

| Area | New primary reference | Secondary references | Copy mode |
| --- | --- | --- | --- |
| 24-hour daemon/runtime | OpenClaw | systemd/service patterns already in A9 | Mechanism first, source-slice when isolated |
| Managed taskflow and approvals | OpenClaw Lobster | LangGraph checkpoints | Mechanism and small source-slice |
| Coding worker loop | Codex | OpenHands, SWE-agent | Mechanism |
| Communication gateway resilience | Barter-rs | Codex event stream, OpenClaw gateway | Mechanism first, small source-slice only with MIT notice |
| Context and compaction | Codex | Aider history, OpenClaw memory-core | Mechanism/source-slice |
| Edit and patch discipline | Aider | Codex apply_patch behavior | Mechanism/source-slice |
| Memory semantics | OpenClaw memory-core + mem0 | LangGraph channel history | Mechanism/source-slice |
| Policy and attestation | OpenClaw policy | METR-style eval discipline | Mechanism |
| Queue/runtime hot path | Redis official ecosystem | OpenClaw taskflow shape | Native A9 implementation |
| Checkpoint lineage | LangGraph | Codex history versioning | Mechanism/source-slice |
| Evaluation harness | SWE-agent, METR, OpenHands | A9 soak runner | Mechanism |
| IDE/product UX | Cline, Roo, Continue | Claude Code/Antigravity as product-only | Mechanism only |

## What To Copy From OpenClaw First

### Managed Flow

Copy the Lobster flow state machine before adding more worker features.

A9 equivalent:

```text
a9:flow:{flow_id}
  status: running | waiting | completed | failed | cancelled
  revision: integer
  controller_id
  goal
  current_step
  wait_json
  state_json
  task_id
  run_id
```

Transitions must require `expected_revision`. This prevents two monitors or
workers from completing/resuming the same flow concurrently.

### Strict Worker Envelope

Workers should not only "modify files". They should return one of a small set of
machine envelopes:

```json
{"ok": true, "status": "ok", "output": [], "patch": "..."}
{"ok": true, "status": "needs_approval", "requiresApproval": {"prompt": "...", "items": []}}
{"ok": false, "error": {"type": "worker_budget", "message": "..."}}
```

The current A9 event summaries and SEARCH/REPLACE apply engine are already close
to this. The missing part is making the envelope the canonical worker contract.

### Approval And Resume

Copy OpenClaw's wait-state model instead of treating approval as a free-form
chat message. A9 should write an approval wait record, pause the flow, and resume
only through a typed approval command that includes `flow_id`,
`expected_revision`, and either approval or rejection.

### Policy Attestation

OpenClaw hashes policy input, workspace evidence, findings, and final
attestation. A9 should copy that idea for:

- allowed paths and scope guard policy
- worker model/provider policy
- network/tool permissions
- patch apply and git governance findings
- test/check results

The important point is not only "pass/fail"; it is proving what was checked
against which policy snapshot.

### Memory Budget And Visibility

OpenClaw memory-core is a stronger runtime memory reference than plain mem0 for
A9 because it includes budget, promotion, recall tracking, citations, and
visibility. mem0 remains useful for memory API shape and extraction/search
semantics, but OpenClaw should drive the governance layer around memory.

## Redis Ecosystem Reassessment

A9 already uses Redis Stack, but the current implementation is still too thin:

- `scripts/a9_middleware.py` creates Streams groups, two Redis Functions,
  RediSearch JSON indexes, Bloom dedupe, and TimeSeries metrics.
- `crates/a9-gateway` uses raw RESP to `XADD`, `XREADGROUP`, `XACK`,
  `TS.ADD`, and `FUNCTION LIST`.

This is enough for a prototype, but not enough for a 24-hour service.

Redis official docs support the direction:

- Redis Streams support consumer groups, `XREADGROUP`, trimming, and replayable
  log-style consumption:
  <https://redis.io/docs/latest/develop/data-types/streams/>
- Redis Functions are database-managed, persisted/replicated, named server-side
  APIs, useful for atomic application logic:
  <https://redis.io/docs/latest/develop/programmability/functions-intro/>
- Redis Stack bundles JSON, Search and Query, Time Series, and probabilistic
  capabilities:
  <https://redis.io/about/redis-stack/>
- RedisJSON works with Search and Query for indexing/querying JSON documents:
  <https://redis-stack.io/docs/data-types/json/>
  <https://redis-stack.io/docs/data-types/json/indexing_json/>

The Redis copy target should be:

| Need | Redis primitive | A9 use |
| --- | --- | --- |
| Durable hot events | Streams | tasks, worker events, monitor events, approvals |
| Atomic transitions | Functions | lease, ack, fail, budget stop, flow transition, retry/quarantine |
| Hot snapshots | RedisJSON | task, run, flow, session, approval, checkpoint indexes |
| Searchable evidence | RediSearch | deep marks, memories, run summaries, policy findings |
| Dedupe | Bloom/Cuckoo | evidence IDs, copied-source hashes, repeated failures |
| Metrics | TimeSeries | tokens, latency, retries, budget stops, health |
| Live UI | Streams first, Pub/Sub optional | monitor dashboard tail without making Pub/Sub canonical |

Redis Functions should remain short and deterministic. They should enforce state
transitions and write small events, not run long model/tool work.

## Communication Governance Reassessment

The mobile/control page exposed the real production issue: user-facing control
must survive network breaks, stale nodes, reconnects, and multi-terminal
onboarding without making the user understand Linux, WSL, Redis, SSH, or tmux.

A9 should therefore treat communication governance as its own runtime layer:

```text
REST typed command plane
-> Redis Streams hot event bus
-> Redis Functions atomic transitions
-> RedisJSON hot snapshots
-> RedisTimeSeries health
-> SSE replay for operator/mobile downlink
-> WebSocket later for terminal/chat when bidirectional low latency is required
-> Tailscale/WireGuard private network substrate
-> SSH/tmux bootstrap and takeover fallback
```

Barter-rs is the new primary local reference for the resilient gateway slice:

- `reference-projects/barter-rs/barter-integration/src/socket/backoff.rs`
- `reference-projects/barter-rs/barter-integration/src/socket/on_connect_err.rs`
- `reference-projects/barter-rs/barter-integration/src/socket/on_stream_err.rs`
- `reference-projects/barter-rs/barter-integration/src/socket/mod.rs`
- `reference-projects/barter-rs/barter/src/engine/audit/state_replica.rs`
- `reference-projects/barter-rs/barter/src/engine/command.rs`
- `reference-projects/barter-rs/barter/src/strategy/on_disconnect.rs`

The first implementation slice should stay narrow: finish tested retry/backoff
and node heartbeat hot-state behavior before adding SSE replay or WebSocket.

## What To Stop Or Downgrade

- Stop treating page/TUI monitor as the main architecture. It remains a fallback
  observation channel for the current Codex window.
- Stop adding more free-form worker prompts before the worker envelope is
  canonical.
- Stop considering Aider a general runtime reference. It is an edit and repo-map
  reference.
- Stop relying on Python-only queue state for production hot paths. Python can
  keep prompt/business logic; Rust + Redis should own runtime governance.
- Do not copy Claude Code or Antigravity source unless an open-source repository
  and license are verified.

## ECC Mechanism Extract (for A9)

Reference source set (license): `reference-projects/ecc/LICENSE` (MIT), commit snapshot tracked in `docs/project.md` (`99baa8250096f2d295583572399a5c9aba2ce312`).

### Cross-harness session adapter contract
- Source: `reference-projects/ecc/docs/SESSION-ADAPTER-CONTRACT.md`
- Mechanism: canonical `ecc.session.v1` snapshot (`schemaVersion`, `adapterId`, `session`, `workers`, `aggregates`) + strict required field validation and fallback duplicate suppression.
- Why it matters: matches A9 need for control-plane-safe, harness-agnostic session/state snapshots between operator and runtime channels.
- Adopt now:
  - Use a similar `schemaVersion`-gated snapshot contract for A9 session/worker records.
  - Keep contract required-field validation and empty/`null` semantics for unknown values.
  - Keep counts/derived aggregates (`workerCount`, state/health maps) as invariant checks.
- Not now:
  - Do not enforce adapter-specific fields (`dmux-tmux`/`claude-session`) as canonical.
  - Do not bind A9 runtime to specific artifact names until adapters are mature.
- Risks:
  - Contract mismatch if A9 flow states and worker health enums are not normalized.
  - Snapshot schema drift with existing `.a9` formats unless migration gate is explicit.

### Cross-harness runtime architecture and adapter strategy
- Source: `reference-projects/ecc/docs/ECC-2.0-REFERENCE-ARCHITECTURE.md`
- Mechanism: adapter matrix + 5-layer operator stack (operator surface → adapter layer → worktree/session runtime → observability/eval loop → security/commercial), and explicit lifecycle events for worktree/session.
- Why it matters: aligns with A9 "session governance + long run" objective and prevents one-harness assumptions.
- Adopt now:
  - Add explicit lifecycle events for `create/resume/pause/stop/close` to A9 session/flow state.
  - Define a stable external payload for operator status/hud snapshots (context/queue/tool/health).
  - Keep adapter layer as contract boundary before UI/product-specific semantics.
- Not now:
  - Avoid porting full UI/HUD stacks, billing/enterprise modules, or hosted telemetry before backend state proof.
- Risks:
  - Extra coupling between adapter matrix and existing Rust gateway if names differ.
  - Potential event explosion before event consumers and retention policy exist.

### Token optimization and context governance
- Source: `reference-projects/ecc/docs/token-optimization.md`
- Mechanism: model-class split, reasoning token caps, subagent model downshift, MCP/tool count control, planned compaction policy, deliberate context-reset/compact points.
- Why it matters: A9 currently prioritizes long-horizon automation stability; token pressure directly affects run quality and repair load.
- Adopt now:
  - Set explicit A9 policy for model selection defaults, context reset points, and hook/summary cadence.
  - Enforce compaction boundaries at stage boundaries (pre/post milestone, debug breaks).
  - Prefer cheaper models for exploration tasks.
- Not now:
  - Avoid fixed env hard-coding to specific provider models until provider policy stabilizes.
- Risks:
  - Aggressive compaction can lose cross-run trace context for later audit.
  - Provider capability differences can make per-task model routing brittle.

### Continuous learning v2 pipeline
- Source: `reference-projects/ecc/docs/continuous-learning-v2-spec.md`
- Mechanism: hook-based observation collection + background analysis loop + scored instincts + persistence + evolution into skills/commands.
- Why it matters: A9 needs mechanism-driven self-improvement while keeping production evidence explicit.
- Adopt now:
  - Introduce A9 observation loop that emits structured lessons to staged review artifacts before any mutation.
  - Require scoring/evidence before any adaptive skill changes.
- Not now:
  - Do not auto-promote evolved behaviors without verifier/rollback proof.
- Risks:
  - Feedback loop instability if low-quality hooks emit noisy signals.
  - Drift if scoring criteria are absent or inconsistent.

### Plan/PRD staged flow
- Source: `reference-projects/ecc/docs/PLAN-PRD-PATTERN.md`
- Mechanism: file-based staged handoff (`.claude/prds/*.prd.md`, `.claude/plans/*.plan.md`) consumed by next command as arguments.
- Why it matters: A9 already separates context and execution; staged artifacts improve reproducible task continuity and handoff across sessions.
- Adopt now:
  - Standardize A9 task package flow with committable PRD/plan artifacts for non-trivial work.
  - Use staged docs to drive role/phase handoff rather than long in-context state.
- Not now:
  - Do not enforce PRD for every task.
- Risks:
  - Operational overhead if artifact generation is required for small routine edits.
  - Artifact staleness if execution diverges without explicit delta updates.

### Plugin / skill / hook packaging references
- Source: `reference-projects/ecc/README.md`
- Mechanism: profile-driven install/module selection; plugin vs manual install parity; install manifests; command surface with strong separation of concerns.
- Why it matters: A9’s future role/hook package model benefits from manifest-level gating and capability boundaries.
- Adopt now:
  - Treat plugin-like A9 capabilities as manifest-scoped packs (worker skill, hooks, channels), imported with explicit scope.
  - Keep duplicate-install prevention and idempotency checks at boundary registration.
- Not now:
  - Do not replicate product/install UX (dashboard, GitHub App, marketing surfaces) in current infrastructure.
- Risks:
  - Incomplete dependency graph resolution across packs causing partial capability loads.
  - Divergence between manifest and runtime state without attested import check.

## Next Implementation Slices

1. Add A9 managed flow records with revisioned transitions.
   - Prototype in `scripts/a9_middleware.py` Redis Functions and Python tests.
   - Then expose through `crates/a9-gateway`.
2. Convert worker outcomes to a strict envelope.
   - Map existing statuses: `pass`, `needs-followup`,
     `retryable-worker-budget`, `needs-repair`, `worker-failed`.
   - Preserve raw Codex JSONL as evidence, but make the envelope the control
     input.
3. Add approval/wait/resume commands.
   - Flow enters `waiting` with typed `wait_json`.
   - Resume requires `flow_id` and `expected_revision`.
4. Add policy attestation evidence.
   - Hash policy snapshot, guard findings, and workspace evidence.
   - Store attestation in run summary and RedisJSON.
5. Upgrade memory governance.
   - Keep mem0-like API shape.
   - Add OpenClaw-style memory budget, recall tracking, visibility, and citation
     metadata before putting more memory into prompts.

## Current Verdict

Yes, the copy logic should be reselected.

The new order is:

```text
OpenClaw/Lobster: 24h runtime, flow, approval, policy, extension, memory governance
Codex: coding agent loop, context, compaction, sandbox, event stream
Barter-rs: communication gateway resilience, reconnect/error governance, audit replica
Aider: repo map, deterministic edit blocks, patch repair
LangGraph: checkpoint lineage and channel history
mem0: memory API and extraction/search semantics
SWE-agent/OpenHands/METR: harness, eval, failure discipline
```

The first code change after this reassessment should be managed flows plus Redis
Function transitions, not another UI monitor or another free-form worker mode.
