# A9 Communication Runtime Decision Packet

Date: 2026-06-02

## Decision Status

`partial_decision`.

This packet approves the next communication-runtime analysis slice. It does not
approve production implementation yet.

Reason: the auto-next review accepted the 24h worker MVP only under monitor
supervision. Communication runtime is a larger product/architecture area and
must start from requirements, data model, state flow, exception flow, and role
review before code.

## Problem

A9 needs a stable operator/runtime communication layer for a 24h execution
machine.

The real problem is not "add one API" or "make the phone page prettier." The
real problem is that A9 must control and observe multiple terminals and servers
without the operator caring about SSH details, network breaks, tmux detach,
Redis pending messages, stale node state, or service restarts.

The operator should see a stable control surface. Underneath, A9 should handle
discovery, connection, command dispatch, streaming, replay, reconnect, repair,
audit, and takeover.

## Business Requirement

Business priority is continuity of the 24h execution machine.

Required behavior:

- The operator can connect from phone/web/CLI and see current worker/runtime
  state.
- A machine can join A9 through a simple SSH/Tailscale/bootstrap path.
- A9 can discover the node, attach or create a tmux session, send commands,
  stream output, replay missed output, and recover after disconnect.
- Network breaks and restarts become normal states with visible evidence, not
  manual mystery failures.
- Worker execution must remain subordinate to product/mainline decisions and
  monitor authority.

Non-goal:

- Do not optimize mobile UI before transport and state are stable.
- Do not build a complex distributed platform before the state model is proven.

## Data Contract

Core objects:

- `operator_session`: `operator_id`, `client_kind`, `client_id`,
  `auth_scope`, `connected_at`, `last_seen_at`, `last_event_id`,
  `control_permissions`.
- `node`: `node_id`, `hostname`, `machine_id`, `tailscale_ip`,
  `ssh_target`, `capabilities`, `status`, `status_reason`, `revision`,
  `last_seen_at`.
- `ssh_identity`: `identity_id`, `node_id`, `user`, `host`, `port`,
  `key_ref`, `known_host_ref`, `state`, `last_probe_at`.
- `tmux_session`: `tmux_id`, `node_id`, `session_name`, `pane_id`,
  `attached`, `last_output_id`, `state`, `revision`.
- `command`: `command_id`, `node_id`, `tmux_id`, `created_by`,
  `expected_revision`, `ttl_ms`, `policy_attestation`, `status`,
  `created_at`, `started_at`, `finished_at`.
- `command_result`: `command_id`, `stream_id`, `status`, `exit_code`,
  `stdout_ref`, `stderr_ref`, `summary`, `next_last_id`.
- `event_cursor`: `stream`, `consumer`, `last_id`, `oldest_id`, `newest_id`,
  `cursor_status`.
- `heartbeat`: `node_id`, `observed_at`, `latency_ms`, `runtime_pid`,
  `tmux_state`, `redis_state`, `tailnet_state`.
- `reconnect_state`: `node_id`, `phase`, `attempt`, `action`,
  `backoff_ms`, `error_class`, `budget_remaining`.
- `repair_action`: `action_id`, `kind`, `target`, `reason`,
  `required_arm`, `status`, `evidence_path`.
- `audit_event`: `event_id`, `actor`, `command`, `target`, `gate`,
  `before`, `after`, `evidence`, `created_at`.

Storage rule:

- MySQL is canonical durable state for entities and decisions.
- Redis Streams are the hot ordered event bus.
- RedisJSON can hold hot snapshots.
- RedisTimeSeries can hold latency/health metrics.
- Local files remain fallback evidence for early MVP and supervisor runs.

## State Flow

Primary flow:

```text
discover
-> register
-> probe
-> connect
-> attach_tmux
-> dispatch_command
-> stream_output
-> ack_result
-> persist_evidence
-> update_status
```

Reconnect flow:

```text
disconnect_detected
-> classify_error
-> choose_action
-> schedule_backoff
-> reconnect_or_quarantine
-> replay_from_cursor
-> reconcile_state
-> audit
```

Operator flow:

```text
operator_connect
-> fetch_status
-> tail_events
-> submit_command
-> receive_command_id
-> watch_result
-> replay_after_disconnect
```

Authority order:

```text
human/operator decision
-> decision packet / active plan
-> policy gate / command group
-> expected revision
-> Redis/MySQL state
-> stream evidence
-> UI view
```

UI is never authority. UI is a view over state, events, and evidence.

## Exception Flow

Network loss:

- Mark node `stale`, then `offline` if heartbeat budget expires.
- Keep last known tmux/session state.
- Replay from stream cursor after reconnect.

SSH failure:

- Classify as `auth`, `host_key`, `network`, `timeout`, or `unknown`.
- Do not retry terminal auth/host-key failures blindly.
- Produce a repair action requiring operator evidence or re-bootstrap.

tmux detach or missing session:

- Try attach if session exists.
- If missing and policy allows, create a new managed session.
- If command was in flight, mark result as `interrupted` and require replay or
  operator review.

Redis stream pending stuck:

- Detect via consumer group pending and idle age.
- Use bounded `XAUTOCLAIM`/recovery action only when command group is armed.
- Audit before and after.

Duplicate command/result:

- Enforce `command_id` idempotency.
- Reject stale `expected_revision`.
- Allow replay of existing result by cursor.

Mobile/client disconnect:

- Client reconnects with `Last-Event-ID` or query cursor.
- Server returns replay, cursor gap, or reset instruction.

Service restart:

- Restart is a typed command with policy gate.
- Supervisor restart needs explicit `allow_supervisor`.
- Audit asynchronously so the hot path is not blocked.

## Reference Scan Evidence

Codex:

- `reference-projects/codex/codex-rs/core/src/tasks/mod.rs`
- `reference-projects/codex/codex-rs/core/src/goals.rs`

Mechanism to copy:

- Do not continue just because a goal exists. Continue only when queued
  next-turn input or mailbox trigger exists and the session is idle.
- Goal runtime keeps continuation accounting, budget steering, and suppresses
  automatic continuation when autonomous activity did not occur.

A9 adaptation:

- Auto runtime should continue only from explicit phase-prefixed work or queued
  operator/worker input.
- Operator corrections must preempt auto-generated work.

OpenClaw / Lobster:

- `reference-projects/openclaw/extensions/lobster/src/lobster-taskflow.test.ts`
- `reference-projects/openclaw/extensions/lobster/src/lobster-runner.ts`

Mechanism to copy:

- Managed flows mutate with `expectedRevision`.
- Approval moves the flow into `waiting` with structured wait JSON and resume
  token.
- Resume requires token or approval id and advances revision.

A9 adaptation:

- Long-running communication actions need revisioned state transitions and
  explicit wait/resume records.
- Human approval and phone-control arm should be first-class flow states.

Barter-rs:

- `reference-projects/barter-rs/barter-integration/src/socket/on_connect_err.rs`
- `reference-projects/barter-rs/barter-integration/src/socket/on_stream_err.rs`
- `reference-projects/barter-rs/barter-integration/src/socket/backoff.rs`
- `reference-projects/barter-rs/barter-data/src/streams/consumer.rs`

Mechanism to copy:

- `ConnectErrorAction = Reconnect | Terminate`.
- `StreamErrorAction = Continue | Reconnect`.
- Backoff is typed and capped; attempt 0 can be immediate.
- Reconnecting events are visible to outer observers.

A9 adaptation:

- Every Redis/SSH/tmux stream failure needs typed action evidence:
  `continue`, `reconnect`, `terminate`, or `quarantine`.
- Do not hide reconnect loops inside implementation.

Redis ecosystem:

- Streams: command/event ordering and replay.
- Consumer groups: work ownership and pending/stale diagnosis.
- Functions: atomic state transitions where Redis is the hot authority.
- JSON: hot snapshots for node/run/session.
- TimeSeries: health, latency, lag, retry count.

A9 current code evidence:

- `crates/a9-gateway/src/main.rs` already has Redis roundtrip retry,
  failure classification, lifecycle event emission, and connect/stream action
  helpers.
- `crates/a9-worker/src/main.rs` already uses `XREADGROUP` and `XADD`.
- `scripts/a9_node.py` already uses Redis stream command claim/replay paths.
- `scripts/a9_control_api.py` already exposes command/result watch and service
  control audit surfaces.

## Role Review Round 1

Product / Mainline:

- Wants an operator experience where phone/web/CLI can take over without
  caring about infrastructure details.
- Rejects UI-first work until transport/state/replay are stable.
- Requires communication runtime to support the bigger A9 goal: 24h execution
  machine plus monitor authority.

Business:

- The real user pain is lost control, broken continuity, and unclear runtime
  state.
- The business object is not "SSH"; it is controllable worker/runtime state.
- Data-first means node, command, cursor, result, heartbeat, reconnect, repair,
  and audit must be modeled before screens.

Architecture:

- Approves Redis Streams as hot event bus and MySQL as canonical durable state.
- Approves SSH/tmux as bootstrap/takeover/fallback, not primary event bus.
- Requires expected revision and idempotent command IDs before execution
  automation expands.
- Requires async audit for mutations so observability does not block hot path.

Test / Acceptance:

- First checks should validate data/state contracts and cursor/replay behavior.
- Real Redis/tmux smoke can come after deterministic unit tests.
- Tests must compare fixtures to real data model, not invent wrapper-only
  contracts.

Cost / Performance:

- Performance is second only after correct data model.
- Token and context cost should be reduced by bounded reference slices,
  canonical context index, and state/evidence compression.
- No arbitrary fixed token gate is approved.

Security / Governance:

- SSH keys, known hosts, command groups, and phone-control arm are authority
  facts, not UI preferences.
- Service restart, remote recovery, and supervisor mutation require explicit
  policy gates and audit.

## Open Questions

These must be resolved before implementation beyond reference/model tests:

- What is the exact canonical MySQL schema for node/session/command/result?
- Which Redis keys and streams are canonical for MVP?
- Does node helper run primarily as Rust gateway, Python node script, or both
  during the first MVP?
- What is the minimal SSH bootstrap contract: add host, verify key, start
  helper, attach tmux, register node?
- What are the exact command groups for phone control and remote recovery?
- What evidence must exist before a reconnect/repair action may execute
  automatically?

## Decisions For Next Slice

D1. Continue with analysis, not implementation.

D2. First execution candidate after this packet is:

```text
reference_scan: communication runtime data/state model validation.
```

D3. The worker must inspect only bounded slices from:

- `docs/communication-governance-framework.md`
- `crates/a9-gateway/src/main.rs`
- `crates/a9-worker/src/main.rs`
- `scripts/a9_node.py`
- `scripts/a9_control_api.py`
- selected reference files named in this packet

D4. The worker output must produce:

- a compact data model table;
- state transition table;
- exception/recovery table;
- first implementation candidate;
- contradictions or stale docs to remove.

D5. The worker must not implement code in that slice.

## Out Of Scope

- Mobile UI polish.
- Financial/quant model work.
- Full Rust rewrite.
- Production daemon hardening.
- New hard gates based on fixed line/token numbers.
- Copying source without license/source record.

## Acceptance For This Packet

This packet is accepted when:

- It exists as the current communication decision artifact.
- `docs/README.md` points to it as the active decision entry.
- The next worker task can be generated from it without reading all docs.
- The packet explicitly blocks implementation until data/state model validation
  is done.

## Next Task Template

```text
decision_status: partial_decision
phase: reference_scan
task: communication runtime data/state model validation
allowed_paths:
  - docs/communication-runtime-decision-packet.md
  - docs/communication-governance-framework.md
  - crates/a9-gateway/src/main.rs
  - crates/a9-worker/src/main.rs
  - scripts/a9_node.py
  - scripts/a9_control_api.py
  - reference-projects/codex/codex-rs/core/src/tasks/mod.rs
  - reference-projects/codex/codex-rs/core/src/goals.rs
  - reference-projects/openclaw/extensions/lobster/src/lobster-taskflow.test.ts
  - reference-projects/openclaw/extensions/lobster/src/lobster-runner.ts
  - reference-projects/barter-rs/barter-integration/src/socket/on_connect_err.rs
  - reference-projects/barter-rs/barter-integration/src/socket/on_stream_err.rs
  - reference-projects/barter-rs/barter-integration/src/socket/backoff.rs
checks:
  - no code changes
  - output includes data model, state flow, exception flow, first implementation candidate, stale/noisy docs list
```

## Progress

Communication-runtime requirements review: about 35%.

Why only 35%:

- data/state model is drafted but not validated against code in a focused
  worker run;
- no role debate round 2 yet;
- no MySQL schema decision;
- no real SSH/Tailscale/tmux smoke contract;
- no long-soak communication test.

Allowed next move:

- Run the bounded reference/model validation slice through the 24h worker and
  monitor its quality.
