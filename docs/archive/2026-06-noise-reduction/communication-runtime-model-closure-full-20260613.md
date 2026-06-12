# A9 Communication Runtime Model Closure Packet (Operator Session / Event Cursor / Reconnect State)

## Object Models

This document closes the model slice for `operator_session`, `event_cursor`, and `reconnect_state` before any runtime expansion (`tmux`, `ssh_identity`, `repair_action` execution).

### `operator_session`

- MySQL authority: `a9_operator_sessions`
- Redis hot streams / snapshots:
  - Event stream: `a9:operator_events`
  - Per-client event tail: `a9:operator:{operator_id}:{client_id}` (currently not normalized in runtime)
- Canonical source of truth: MySQL
- Owner:
  - create/update status: Runtime auth layer + operator control endpoints (human/operator-approved)
  - audit transitions: monitor/runtime governance
- Required fields:
  - `operator_session_id` (generated)
  - `operator_id`
  - `client_kind` (`phone` / `web` / `cli`)
  - `client_id`
  - `auth_scope` (array or CSV)
  - `connected_at` (first auth-confirmed session start)
  - `last_seen_at`
  - `last_event_id` (cursor of operator visible event stream)
  - `control_permissions` (`command_gate`/policy groups)
  - `status` (`active`, `idle`, `stale`, `revoked`, `disconnected`)
- Evidence surface today:
  - `scripts/a9_control_api.py` currently exposes operator permission and scope signals but no first-class session entity (`PHONE_ADMIN_SCOPE`, `communication_data_contract_report` baseline marks `missing`).

### `event_cursor`

- MySQL authority: `a9_event_cursors`
- Redis hot streams / snapshots:
  - Client cursor replay inputs/outputs are currently surfaced through API headers (`Last-Event-ID`) and query params.
  - Hot stream context: `a9:events` and node result stream inputs for replay APIs.
- Canonical source of truth: MySQL (for durable cursor recovery) + Redis for stream replay window checks.
- Owner:
  - write: operator-control API on successful replay, reconnect, or watch requests
  - read: operator-control surfaces (`/api/events`, `/api/node-command-results/...`)
- Required fields:
  - `stream`
  - `consumer`
  - `last_id`
  - `oldest_id`
  - `newest_id`
  - `cursor_status` (`active`, `gap_detected`, `invalid`, `stale`, `reset_pending`)
  - `updated_at`
- Evidence surface today:
  - `scripts/a9_control_api.py` replay helpers (`read_events`, `read_node_result_replay`) emit `status`, `error_code`, `stream_oldest_id`, `stream_newest_id`, `next_last_id`; this is behavior-level evidence without persisted object state.

### `reconnect_state`

- MySQL authority: `a9_reconnect_states`
- Redis hot streams / snapshots:
  - `a9:reconnect_events`
  - `a9:reconnect:{node_id}`
  - decision events stored in `a9:events` (`gateway_reconnect_decision`)
- Canonical source of truth: MySQL (durable transition record) + Redis for last event + hot state.
- Owner:
  - write: gateway worker/recovery loop decisions + operator/runtime governance paths
  - read: control API diagnostics and runtime governance dashboards
- Required fields:
  - `node_id`
  - `phase` (`connect`, `stream`, `ssh`, `tmux`, `redis`)
  - `attempt`
  - `action` (`continue`, `reconnect`, `terminate`, `quarantine`, `watch`)
  - `backoff_ms`
  - `error_class` (normalized enum)
  - `budget_remaining`
  - `updated_at`
- Evidence surface today:
  - `scripts/a9_control_api.py` parses redis event fields for `phase`, `action`, `error_class`, `attempt`, `delay_ms`, `policy_budget_remaining` via `latest_gateway_reconnect_decision_event()`.
  - `gateway_reconnect_governance` + `gateway_reconnect_evidence_decision` currently consume this behavior.

## State Transitions

### Normal

#### `operator_session`
- `disconnected` -> `active`: operator auth + scope check succeeds.
- `active` -> `idle`: connected but no operator-visible events for configured heartbeat window.
- `active` -> `stale`: last ping/refresh timeout crossed.
- `stale` -> `active`: replay/reconnect accepted and cursor continues.
- `active` -> `revoked`: explicit admin revoke or scope drop.
- `revoked` -> `disconnected`: explicit terminate/logout cleanup.

#### `event_cursor`
- `stale` -> `active`: valid cursor replay returns at least one event or confirms current tip.
- `gap_detected` -> `reset_pending`: response `cursor_gap` with valid `next_last_id`.
- `active` -> `active`: normal append (`next_last_id` monotonic non-decreasing).
- `invalid` -> `reset_pending`: invalid cursor input repaired via `retry_without_cursor` or `reset_cursor`.

#### `reconnect_state`
- `idle` -> `reconnecting`: action `reconnect`.
- `idle` -> `quarantine`: action `quarantine`.
- `reconnecting` -> `idle`: action `continue` with successful stream recovery.
- `reconnecting` -> `reconnecting`: bounded backoff retry after non-terminal error.
- `reconnecting` -> `quarantine`: terminal budget exhaustion or policy stop.
- `reconnecting` -> `terminated`: action `terminate`.

### Exception

- `operator_session`:
  - missing permission scope in a control write -> reject, state remains unchanged.
  - duplicate session claim for same actor/device -> treat as latest-signee wins; previous session transitions to `revoked` once signed.
  - stale recovery conflict -> require manual operator reconciliation; no auto-heal.

- `event_cursor`:
  - replay query with bad cursor syntax -> response `invalid_cursor`, transition to `invalid`.
  - valid syntax but gap outside replay window -> `gap_detected` + reset action.
  - Redis unavailable -> keep last cursor, mark `stale`, do not claim success.

- `reconnect_state`:
  - terminal SSH/auth/host-key failures should not auto-loop; action must become `quarantine` or `terminate` depending on policy.
  - reconnect attempts exceed budget -> forced `quarantine` and explicit evidence requirement.
  - malformed decision event -> evidence fail gate, no state mutation in MySQL until event normalized.

## Exception Gates

- `operator_session` mutation gate
  - Require auth and valid `operator.admin` scope for mutation transitions beyond read-only fields.
  - Any state transition that reduces authority (`revoked`, `disconnected`) requires operator identity evidence and policy attestation reference.
- `event_cursor` gate
  - `reset_cursor`/`retry_without_cursor` is advisory until persisted after successful read.
  - Cursor object should not accept `gap_detected` as terminal success; must persist exception and allow bounded replay policy.
- `reconnect_state` gate
  - transition to `terminated`/`quarantine` requires evidence: `phase`, `error_class`, `attempt`, `backoff_ms`, `budget_remaining`.
  - if evidence row missing or malformed, runtime must emit `degraded` and block command-level auto-flow in observation lane (policy-driven `observe` only).

## Persistence Keys

- MySQL tables:
  - `a9_operator_sessions`
  - `a9_event_cursors`
  - `a9_reconnect_states`
- Redis hot stream/snapshot keys:
  - `a9:events`
  - `a9:tasks`
  - `a9:operator_events`
  - `a9:operator:{operator_id}:{client_id}`
  - `a9:reconnect:{node_id}`
  - `a9:reconnect_events`
- Stream fields that must be preserved for `reconnect_state` evidence:
  - `kind= gateway_reconnect_decision`
  - `phase`, `action`, `error_class`, `attempt`, `delay_ms`, `policy_budget_remaining`, `flow_id`, `flow_revision`, `node_id`, `origin`, `ts`.

## Acceptance

Decision for this slice is model-closure only. Acceptance requires:

- `docs/communication-runtime-model-closure.md` exists and defines:
  - fields + owner + authority store + Redis keys for all 3 objects
  - state enums and normal/exception transitions
  - invariants and evidence mapping to existing API/gateway behavior
  - explicit open questions for unresolved ownership or state semantics
- `docs/README.md` indexes this packet in a bounded location.
- No runtime behavior modifications in this slice.
- No ambiguous field/state with unresolved owner remains unmarked in `Open Questions`.

## Recommended Execution Slice

`execution_next` may start only after this packet is signed and ambiguity cleared.

Next concrete implementation candidate:

1. Add first-class data contract report endpoints/exports for:
   - `operator_session`
   - `event_cursor`
   - `reconnect_state`
2. Add no-op persistence adapters (validation + serialization) for these objects only, behind existing read paths.
3. Add strict acceptance artifacts for transition invariants and evidence continuity checks.

No tmux/ssh command automation in this first slice.

## Open Questions

- Is `operator_session.status` owner-write path constrained to exactly one of {`Runtime`, `RuntimeMonitor`, `Operator`} and which layer is allowed to set `revoked`?
- For `event_cursor`, should `cursor_status` remain independent of `operator_session.status`, or should stale sessions auto-demote all per-client cursors?
- For `reconnect_state`, should `phase` be persisted exactly as gateway phase (`connect|stream|ssh|tmux|redis`) or normalized to `network|stream|runtime`?
- Should `a9:operator_events` and `a9:operator:{operator_id}:{client_id}` be mandated as RedisJSON snapshots immediately, or can they remain stream-only in this slice?

## Reference Mechanisms Borrowed

This packet did not re-read reference repositories. It reuses mechanisms already
captured in local decision documents:

- Codex-style session continuity, compaction, and handoff-as-index governance.
- OpenClaw/Lobster-style strict governance, revisioned waiting, and approval
  envelopes.
- Barter-rs-style reconnect taxonomy, action classification, and backoff model.
