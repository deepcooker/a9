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
   error-class counters.
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

Adaptation target for A9 gateway/node stack:

- Map `Reconnecting(origin)` into Redis Stream event envelopes and flow summary
  metadata.
- Keep reconnect policy deterministic now (125ms * 2 capped at 60000ms); add
  jitter only after baseline behavior is proven in soak runs.
- Bind terminal/recoverable classification to existing typed failure buckets so
  repair routing is automatic.

Verification note:

- This repository currently lacks local `reference-projects/barter-rs/*`
  content. Mechanism text above is captured from the bounded task packet's
  selected mechanism list; next `reference_scan` slice should import or mount
  the declared paths and append exact line-level evidence.

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
