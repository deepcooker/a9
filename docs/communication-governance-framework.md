# A9 Communication Governance Framework

## Decision

Current priority is communication governance for the 24-hour execution machine,
not more mobile UI polish.

The mobile app is the operator entrance. It must make control convenient, but
it cannot be the stability architecture. A9 needs a fast, stable, high-concurrency
control plane where disconnected networks, stale nodes, retries, replay, and
multi-terminal onboarding are normal states rather than manual incidents.

## Session Evidence

The latest external Codex session extract covering this decision is:

- source session:
  `/root/.codex/sessions/2026/05/21/rollout-2026-05-21T11-20-49-019e488c-d5f9-7501-835a-bf6e8ff6d8a2.jsonl`
- latest extract:
  `.a9/external_sessions/019e488c-d5f9-7501-835a-bf6e8ff6d8a2/turns-186-257.json`
- turn range: `186-257`
- approximate JSONL lines: `14338-18319`

Important changes inside this range:

- `turn 186-190`: session governance was pulled back from UI drift into
  raw session, compact boundary, memory commit, and drift repair.
- `turn 192-245`: mobile/control page became a product entrance and remote
  control surface, but repeatedly exposed that stable transport and node
  onboarding matter more than UI details.
- `turn 246-257`: the mainline shifted again from page interaction to world-class
  communication stability: multi-terminal onboarding, Tailscale/SSH/tmux,
  Rust, Redis, fast/high-concurrency behavior, Barter-rs-style gateway
  resilience, and mature exception handling.

This does not invalidate the mobile work. It changes its role: mobile is the
operator console for a robust runtime, not the runtime itself.

## Current State

A9 currently has:

- Python control API with REST/fetch endpoints.
- Tailscale/private IP plus SSH/tmux plans for remote takeover.
- Node discovery, register, and heartbeat endpoints.
- Redis usage for parts of flow/session state, node hot status, and heartbeat
  stream experiments.
- A minimal Rust `a9-gateway` that can talk RESP to Redis streams and
  TimeSeries.

This is enough for a prototype, not enough for a 24-hour multi-node service.

## Target Stack

```text
Phone / Web / CLI operator
  -> HTTPS REST typed commands
  -> SSE event tail first, WebSocket later for bidirectional terminal/chat
  -> Rust a9-gateway hot path
  -> Redis Streams / Functions / JSON / TimeSeries / Search / Bloom
  -> Python supervisor and model/business logic
  -> MySQL canonical durable state
  -> Tailscale/WireGuard network substrate
  -> SSH/tmux fallback takeover
```

Roles:

- REST: typed command plane. Every command needs `command_id`, `node_id`,
  idempotency, policy gate, and durable evidence.
- Redis Streams: canonical hot event bus for tasks, node events, approvals,
  operator events, and replay.
- Redis Functions: short deterministic transitions for lease, ack, retry,
  quarantine, flow transition, and wait/resume.
- RedisJSON: hot snapshots for node, run, flow, session, approval, and command
  status.
- RedisTimeSeries: latency, heartbeat age, retry count, disconnect count,
  queue lag, token spend, and worker health.
- RediSearch/Bloom: searchable evidence indexes and dedupe gates.
- SSE: first mobile/web downlink because it has simple reconnect and
  `Last-Event-ID` replay semantics.
- WebSocket: later, only where true bidirectional low-latency terminal/chat is
  required.
- Tailscale/WireGuard: private network substrate and stable addressing.
- SSH/tmux: bootstrap, repair, and human takeover fallback, not the primary
  event bus.
- Python: model integration, task prompts, session summarization, and
  customizable business logic.
- Rust: gateway, high-concurrency hot path, Redis event transport, and
  deterministic runtime governance.

## References To Copy

Codex:

- `vendor-src/codex/codex-rs/core/src/compact.rs`
- `vendor-src/codex/codex-rs/core/src/context_manager/history.rs`

Copy the idea that ordered events are source of truth, compacted prompt state is
derived, streaming execution has retry/timeout boundaries, and compaction must
not erase raw evidence.

Barter-rs:

- repository: `reference-projects/barter-rs`
- commit: `33e56188e2095781331f85aa3d7f88e251eec65a`
- license: MIT
- `barter-integration/src/socket/backoff.rs`
- `barter-integration/src/socket/on_connect_err.rs`
- `barter-integration/src/socket/on_stream_err.rs`
- `barter-integration/src/socket/mod.rs`
- `barter-integration/src/socket/update.rs`
- `barter/src/engine/audit/state_replica.rs`
- `barter/src/engine/command.rs`
- `barter/src/strategy/on_disconnect.rs`

Copy reconnect backoff, typed connect/stream error actions, reconnecting socket
lifecycle events, audit state replicas, external command boundaries, and
disconnect strategies.

OpenClaw/Lobster:

- `reference-projects/openclaw/extensions/lobster/src/lobster-taskflow.ts`
- `reference-projects/openclaw/extensions/lobster/src/lobster-runner.ts`

Copy managed flow, expected revision, approval wait/resume, strict envelope, and
gateway tool policy.

Redis ecosystem:

- Streams consumer groups for task/event delivery and replay.
- Functions for atomic state transitions.
- RedisJSON for hot snapshots.
- TimeSeries for health and latency.
- Search/Bloom for evidence query and dedupe.

## Mechanisms A9 Should Implement

1. Node connection state machine:
   `online -> stale -> offline -> degraded -> reconnecting -> online`.
2. Barter-rs-style retry policy:
   immediate first attempt, exponential backoff with cap, later jitter,
   typed `reconnect | continue | terminate | quarantine` actions.
   Reconnecting stream extraction contract for A9:
   `init_reconnecting_stream` = init once, then re-init on reconnect loop;
   `with_reconnect_backoff` = fail-path backoff multiply/cap + success-path
   reset; `with_termination_on_error` = terminal inner stream errors force
   stream termination and re-init while recoverable errors continue; and
   `with_reconnection_events` = emit `Reconnecting(origin)` lifecycle events
   for external observers.
   Consumer defaults to `125ms` initial backoff, multiplier `2`, max `60000ms`.
3. Idempotent command plane:
   every command has `command_id`, `target_node`, `expected_revision`, `ttl`,
   `created_by`, and `policy_attestation`.
4. Redis hot heartbeat:
   write RedisJSON snapshot, append heartbeat stream, add TimeSeries metric,
   retain local file fallback if Redis is unavailable.
5. Event replay:
   stream IDs and replay cursor handling for SSE; never rely on volatile UI state.
   First slice exposes `a9:events` through `/api/events` with JSON tail and
   `format=sse` output, using explicit cursor precedence (`last_id` query first,
   then `Last-Event-ID` request header), with degraded output when cursor format
   is invalid or Redis is unavailable. If `last_id` is syntactically valid but
   replay returns empty while stream is non-empty, API returns
   `status=degraded,error_code=cursor_gap` with `stream_oldest_id`,
   `stream_newest_id`, and `next_last_id` for client cursor reset. Control
   clients can use `scripts/a9_control_api.py:event_replay_reset_decision` to
   convert replay responses into bounded actions: `reset_cursor`,
   `retry_without_cursor`, or `keep_cursor`.
6. Backpressure:
   bounded stream reads, trim policy, dead-letter stream, retry budget, and
   error-class counters. Pending/lag evidence contract for Redis Streams
   consumer groups (start with `a9:tasks`):
   `XINFO GROUPS a9:tasks` as group-level snapshot (`name`, `consumers`,
   `pending`, `last-delivered-id`, `entries-read`, `lag`) plus
   `XPENDING a9:tasks <group>` as pending ownership snapshot
   (`total`, `smallest_id`, `largest_id`, per-consumer counts). A9 should emit
   typed status from these raw fields:
   `status=ok|degraded|offline`,
   `reason=none|lag_warn|lag_critical|pending_stuck|pending_skew|no_group|redis_unavailable`,
   and evidence fields:
   `stream`, `group`, `sampled_at`, `lag`, `pending_total`, `consumers`,
   `oldest_pending_id`, `newest_pending_id`, `pending_by_consumer`.
   First thresholds to implement:
   `lag_warn >= 100`, `lag_critical >= 1000`,
   `pending_stuck` when oldest pending idle exceeds `30000ms`,
   `pending_skew` when max consumer pending share exceeds `0.8`.
   Thresholds must be config-backed and versioned in evidence metadata.
7. Multi-terminal onboarding:
   a node helper registers itself, reports capabilities, keeps heartbeat, and
   accepts typed work after policy gate. SSH/tmux is only used for bootstrap or
   manual takeover.
8. Evidence:
   every disconnect, retry, stale heartbeat, command timeout, and replay gap
   writes bounded machine-readable evidence.

## Reconnecting Stream Failure Contract (Barter-rs -> A9)

Reference paths (declared source-of-truth for this mechanism):

- `reference-projects/barter-rs/barter-data/src/streams/reconnect/stream.rs`
- `reference-projects/barter-rs/barter-data/src/streams/reconnect/mod.rs`
- `reference-projects/barter-rs/barter-data/src/streams/consumer.rs`
- `reference-projects/barter-rs/LICENSE`
- `reference-projects/barter-rs/barter-integration/src/socket/on_connect_err.rs`
- `reference-projects/barter-rs/barter-integration/src/socket/on_stream_err.rs`
- `reference-projects/barter-rs/barter-integration/src/socket/backoff.rs`

Typed action contract to copy into A9:

1. Connect error action (from `on_connect_err.rs`):
   `ConnectErrorAction = Reconnect | Terminate`.
2. Stream error action (from `on_stream_err.rs`):
   `StreamErrorAction = Continue | Reconnect`.
3. Backoff contract (from `backoff.rs`):
   reconnect delay is a typed function of `reconnection_attempt`, bounded by a
   max cap; attempt `0` can be immediate.

A9 normalized reconnect decision table:

1. Connect init fails and policy says retry:
   `phase=connect`, `action=Reconnect`, stream keeps waiting for next init.
2. Connect init fails and policy budget exhausted:
   `phase=connect`, `action=Terminate`, flow transitions to failed/waiting.
3. Stream item error is recoverable:
   `phase=stream`, `action=Continue`, keep current stream and emit error item.
4. Stream item error is terminal:
   `phase=stream`, `action=Reconnect`, terminate current stream and trigger
   outer reconnect loop.

A9 machine-readable evidence schema (minimum fields):

```json
{
  "kind": "gateway_reconnect_decision",
  "phase": "connect|stream",
  "action": "reconnect|terminate|continue",
  "error_class": "timeout|io|protocol|auth|rate_limit|unknown",
  "attempt": 0,
  "delay_ms": 0,
  "policy_budget_remaining": 0,
  "flow_id": "optional",
  "flow_revision": 0,
  "node_id": "optional",
  "origin": "connect_error|stream_error|manual_resume",
  "ts": "iso8601"
}
```

Failure modes A9 must keep machine-readable:

1. Re-init failure escalation:
   repeated init failures must increase reconnect delay to capped backoff, with
   explicit evidence fields for `attempt`, `delay_ms`, and `error_class`.
2. Successful re-init reset:
   first successful reconnect must reset backoff baseline; otherwise recovery
   latency drifts upward.
3. Terminal stream error cutover:
   terminal inner-stream errors must force reconnect path, not stay in
   `continue` branch.

4. Reconnect observability:
   reconnect transitions must emit explicit lifecycle events
   (`reconnecting`/origin) so control plane can reflect degraded state and
   approval flows can pause/resume safely.
5. Wrong action-domain mapping:
   `ConnectErrorAction::Terminate` accidentally mapped to stream `continue`, or
   `StreamErrorAction::Reconnect` accidentally mapped to connect terminate path,
   causing silent deadlock or premature task death.

Adaptation target for A9 gateway/node stack:

- Map `Reconnecting(origin)` into Redis Stream event envelopes and flow summary
  metadata.
- Keep reconnect policy deterministic now (125ms * 2 capped at 60000ms); add
  jitter only after baseline behavior is proven in soak runs.
- Bind terminal/recoverable classification to existing typed failure buckets so
  action routing stays deterministic under retry pressure.

## Transcript-Backed Intervention Policy (v1)

Scope:

- This policy is derived from `/api/nodes/recovery-transcript` and is for
  communication governance decisions only.
- It does not replace raw evidence. Transcript rows are compact handoff records
  that must keep `evidence_path` / `event_id` references.
- It keeps observation windows reason-driven; it does not hard-code new token
  gates.

Reference mechanisms copied:

- Barter-rs reconnect action domain:
  `connect/stream + Reconnect|Terminate|Continue`
  (`reference-projects/barter-rs/barter-integration/src/socket/on_connect_err.rs`,
  `reference-projects/barter-rs/barter-integration/src/socket/on_stream_err.rs`,
  `reference-projects/barter-rs/barter-data/src/streams/consumer.rs`).
- Codex compact/handoff boundary:
  compact output is handoff, not truth
  (`vendor-src/codex/codex-rs/core/src/compact.rs`,
  `vendor-src/codex/codex-rs/core/src/context_manager/history.rs`).
- OpenClaw managed workflow/policy envelope:
  typed status, expected revision, wait/resume compatibility
  (`reference-projects/openclaw/extensions/lobster/src/lobster-taskflow.ts`,
  `reference-projects/openclaw/extensions/lobster/src/lobster-runner.ts`).
- Redis Streams consumer-group health:
  lag/pending/no-group/unavailable probe as machine-readable input
  (this doc, `Pending/lag evidence contract` section).

### Input Contract

Minimum input is the latest bounded rows from
`/api/nodes/recovery-transcript` and current stream-health snapshot.

Required fields:

- `ts`
- `node_id`
- `flow_id` (optional but preferred)
- `source` (`node_evidence|gateway_reconnect|tasks_stream|followup|recovery_loop`)
- `phase` (`probe|connect|stream|repair|resume|observe|quarantine`)
- `action` (`continue|watch|repair|intervene|quarantine|reconnect|terminate`)
- `reason` (typed reason code, not prose-only)
- `status` (`ok|degraded|offline|failed|waiting`)
- `evidence_path` (optional)
- `event_id` (optional)

Policy evaluators must also read:

- tasks stream probe: `lag`, `pending_total`, `reason`, and consumer skew/stuck
  fields when available;
- recovery-loop latest: whether loop is converging or bouncing;
- gateway reconnect decision rows: `phase/action/error_class/attempt/delay_ms`.

### Action Levels

1. `observe`
   - Use when newest signals are stable and converging.
   - Typical indicators: `tasks_stream.reason=none`, loop status healthy, latest
     reconnect action is `continue` or no active reconnect.
2. `watch`
   - Use when degradation exists but no immediate manual/system repair is
     required.
   - Typical indicators: lag warning, consumer-group missing, short reconnect
     bursts that still self-recover.
3. `repair`
   - Use when deterministic repair action should run now.
   - Typical indicators: pending stuck/skew, reconnect backoff growing without
     convergence, known repairable node-step failures (tmux/heartbeat/service
     mismatch).
4. `intervene`
   - Use when monitor/operator intervention is required to keep flow continuity.
   - Typical indicators: repeated worker envelope/protocol failures, policy
     mismatch, retry loops that keep bouncing across surfaces.
5. `quarantine`
   - Use when normal apply path must stop and isolate risk.
   - Typical indicators: sequence gap/revision mismatch, irrecoverable terminal
     path (`terminate` with exhausted budget), unsafe/conflicting state writes.

### Output Contract

Every decision output must be machine-readable and bounded:

```json
{
  "action": "observe|watch|repair|intervene|quarantine",
  "reason": "typed_reason_code",
  "evidence_refs": [
    {
      "source": "tasks_stream|gateway_reconnect|node_evidence|recovery_loop|followup",
      "event_id": "optional",
      "evidence_path": "optional"
    }
  ]
}
```

Rules:

- `reason` must be typed and reproducible from input rows, not free-form summary
  text.
- `evidence_refs` must point to the specific transcript rows used for the
  decision.
- If multiple sources disagree, raise level to at least `watch`; if conflict
  implies unsafe apply/revision risk, escalate to `quarantine`.

## Redis Streams Pending/Lag Evidence Contract (XINFO GROUPS + XPENDING)

Reference mechanism intent to copy:

- Redis Streams consumer-group introspection as machine evidence, not logs.
- Two-command bounded probe: `XINFO GROUPS` for lag/pending headline and
  `XPENDING` for ownership/stuck analysis.
- Degraded-state output uses typed thresholds, not ad-hoc text.

Bounded contract (phase-1 stream: `a9:tasks`):

1. Probe inputs:
   `stream=a9:tasks`, `group=<configured task group>`.
2. Probe reads:
   `XINFO GROUPS a9:tasks` then `XPENDING a9:tasks <group>`.
3. Probe output fields:
   `status`, `reason`, `lag`, `pending_total`, `consumers`,
   `oldest_pending_id`, `newest_pending_id`, `pending_by_consumer`,
   `thresholds_version`, `sampled_at`.
4. Degraded thresholds:
   `lag_warn >= 100`, `lag_critical >= 1000`,
   `pending_idle_critical_ms >= 30000`,
   `pending_skew_ratio >= 0.8`.
5. Missing-data policy:
   missing stream/group -> `status=degraded`, `reason=no_group`;
   Redis command failure -> `status=offline`, `reason=redis_unavailable`.

Failure modes to keep machine-readable:

1. Lag-only blind spot: `lag` normal but `pending_total` and idle age rising.
2. Ownership skew: one consumer holds most pending IDs, hiding worker stall.
3. Empty-group false health: stream exists but expected group missing.
4. XPENDING parse drift: shape/field mismatch silently drops stuck evidence.
5. Threshold drift: changed limits without version tags breaks comparability.

Token/cost behavior:

- Fixed two commands per sample keeps probe bounded.
- Keep per-consumer detail bounded to top-N (suggest `N=8`) in API responses;
  full raw command output stays in evidence artifacts, not prompt context.
- On repeated failures, emit summarized counters and sample at backoff cadence,
  not per-request spam.
  repair routing is automatic.
- Keep action domain explicit in evidence (`phase=connect|stream`) so repair
  automation can route failures to retry tuning vs stream error taxonomy fixes.

Verification note:

- `reference-projects/barter-rs` is present locally in the controller repo.
- The mechanism text above was checked against bounded snippets from the
  declared Barter-rs paths. A9 should copy the reconnect/backoff/error-event
  mechanism, not the trading-domain stream implementation.

## Ordered State Replica Contract (Barter `state_replica.rs` -> A9 Reducer)

Reference path:

- `reference-projects/barter-rs/barter/src/engine/audit/state_replica.rs`

Mechanism to copy (bounded to reducer contract, not trading logic):

1. Monotonic sequence gate:
   apply update only when `incoming.sequence > current.sequence`; otherwise
   treat as stale/duplicate and skip.
2. Gap hard-fail:
   if `incoming.sequence != current.sequence + 1`, treat as out-of-order gap
   and stop normal apply path (quarantine/error path).
3. Explicit terminal reason:
   reducer stop reason is explicit and machine-readable (`FeedEnded` vs
   `EngineEvent::Shutdown`) instead of generic failure text.

Field mapping table for A9 node/flow reducer:

| Barter replica field | A9 field |
| --- | --- |
| `context.sequence` (current) | `flow_revision` or per-node `last_applied_seq` |
| `next.sequence` (incoming) | event envelope `sequence` (stream monotonic sequence) |
| `validate_and_update_context` | Redis Function gate with `expected_revision` + `expected_last_seq` |
| stale check `current >= incoming` | `stale_event_skip=true` evidence; no state write |
| gap check `incoming != current + 1` | `status=degraded`, `error_code=sequence_gap`, route to quarantine stream |
| stop reason `FeedEnded` | `terminal_reason=feed_ended` in flow/node summary |
| stop reason `EngineEvent::Shutdown` | `terminal_reason=engine_shutdown` in flow/node summary |

Required event/heartbeat envelope fields (A9):

- `node_id`
- `flow_id`
- `flow_revision` (post-apply)
- `expected_revision` (precondition used by transition)
- `sequence` (event sequence from stream producer)
- `event_type`
- `stale_event_skip` (`true|false`)
- `gap_detected` (`true|false`)
- `terminal_reason` (`none|feed_ended|engine_shutdown|quarantined_gap`)
- `ts`

Failure modes table (must stay machine-readable):

1. Duplicate/stale overwrite:
   missing stale gate lets old heartbeat/event regress hot snapshot.
2. Silent gap apply:
   reducer accepts non-contiguous sequence and corrupts replay invariants.
3. Gap without quarantine:
   system logs error but still advances revision, making repair impossible.
4. Ambiguous terminal reason:
   no explicit stop reason; control plane cannot decide auto-retry vs manual
   resume.
5. Revision/sequence drift:
   `expected_revision` CAS passes but `sequence` is not contiguous, causing
   mixed-order state.

Token/cost behavior for this mechanism extract:

- reducer checks are O(1) per event (`stale`, `gap`, CAS precondition);
  no extra historical prompt expansion is required.
- failure evidence must be bounded key-value envelopes, not raw logs, to keep
  `session_refresh` and worker prompts compact.

## First Worker Slice

The first 24-hour worker task should not add broad new product UI. It should
finish a narrow communication-governance slice:

```text
phase: reference_scan -> mechanism_extract -> implement -> test -> record
goal: copy Barter-rs/Codex communication resilience into A9's gateway/node layer

must inspect:
- reference-projects/barter-rs/barter-integration/src/socket/backoff.rs
- reference-projects/barter-rs/barter-integration/src/socket/on_connect_err.rs
- reference-projects/barter-rs/barter-integration/src/socket/on_stream_err.rs
- reference-projects/barter-rs/barter-integration/src/socket/mod.rs
- reference-projects/barter-rs/barter/src/engine/audit/state_replica.rs
- vendor-src/codex/codex-rs/core/src/compact.rs
- crates/a9-gateway/src/main.rs
- scripts/a9_control_api.py
- scripts/a9_node.py
- tests/test_control_api.py
- tests/test_node.py

deliver:
- Rust gateway retry/backoff tests.
- Node heartbeat hot-state evidence stays Redis-first with file fallback.
- A small documented connection-state policy.
- A next slice for SSE replay or node helper watch loop, but do not combine both.
```

Acceptance:

- Tests pass.
- Source/commit/license for copied mechanisms are recorded.
- No UI-only work.
- No large reference source pasted into prompts.
- If Redis is unavailable, behavior is degraded but does not crash the control
  API.

## Not Now

- Do not optimize GPT-like mobile drawer details in this slice.
- Do not make WebSocket the first event transport without a replay plan.
- Do not treat SSH/tmux as the primary multi-node event bus.
- Do not trust worker self-report without Redis evidence, tests, and guard
  output.
