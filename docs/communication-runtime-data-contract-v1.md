# A9 Communication Runtime Data Contract v1

Date: 2026-06-02

## Status

`v1_accepted_for_report_slice`.

Approved source:

- `docs/communication-runtime-role-review.md`
- `docs/communication-runtime-decision-packet.md`

Scope:

- Define communication runtime objects, states, stream/key shape, durable target
  tables, and evidence.
- Do not change runtime behavior in this document.
- Do not start SSH/tmux feature implementation until this contract is accepted.

## Design Rule

Data first, performance second.

For communication runtime, "data" means the real business/runtime objects:
operator session, node, ssh identity, tmux session, command, command result,
cursor, heartbeat, reconnect state, repair action, and audit event.

If these objects are wrong, UI and transport code will drift.

## Storage Authority

Canonical durable authority:

- MySQL target tables described below.

Hot runtime authority:

- Redis Streams for ordered events and replay.
- RedisJSON for hot snapshots where available.
- RedisTimeSeries for health metrics where available.

Fallback evidence:

- `.a9/nodes/**`
- `.a9/services/**`
- `.a9/runs/**`

UI/mobile/web:

- view only; never authority.

## Object Contract

| Object | Required Fields | MySQL Target | Redis / Stream Target | Current Code Fit |
| --- | --- | --- | --- | --- |
| `operator_session` | `operator_id`, `client_kind`, `client_id`, `auth_scope`, `connected_at`, `last_seen_at`, `last_event_id`, `control_permissions`, `status` | `a9_operator_sessions` | `a9:operator_events`, `a9:operator:{operator_id}:{client_id}` | missing |
| `node` | `node_id`, `hostname`, `machine_id`, `tailscale_ip`, `ssh_target`, `capabilities`, `status`, `status_reason`, `revision`, `last_seen_at` | `a9_nodes` | `a9:nodes`, `a9:node:{node_id}` | partial |
| `ssh_identity` | `identity_id`, `node_id`, `user`, `host`, `port`, `key_ref`, `known_host_ref`, `state`, `last_probe_at` | `a9_ssh_identities` | `a9:ssh:{identity_id}` | missing |
| `tmux_session` | `tmux_id`, `node_id`, `session_name`, `pane_id`, `attached`, `last_output_id`, `state`, `revision` | `a9_tmux_sessions` | `a9:tmux:{node_id}:{session_name}`, `a9:tmux_events` | missing |
| `command` | `command_id`, `node_id`, `tmux_id`, `created_by`, `expected_revision`, `ttl_ms`, `policy_attestation`, `status`, `created_at`, `started_at`, `finished_at` | `a9_commands` | `a9:tasks`, `a9:command:{command_id}` | partial |
| `command_result` | `command_id`, `stream_id`, `status`, `exit_code`, `stdout_ref`, `stderr_ref`, `summary`, `next_last_id` | `a9_command_results` | `a9:events`, `a9:command_result:{command_id}` | partial |
| `event_cursor` | `stream`, `consumer`, `last_id`, `oldest_id`, `newest_id`, `cursor_status`, `updated_at` | `a9_event_cursors` | client `Last-Event-ID`, replay responses | partial |
| `heartbeat` | `node_id`, `observed_at`, `latency_ms`, `runtime_pid`, `tmux_state`, `redis_state`, `tailnet_state` | `a9_heartbeats` | `a9:heartbeats`, TimeSeries `a9:ts:heartbeat:{node_id}` | partial |
| `reconnect_state` | `node_id`, `phase`, `attempt`, `action`, `backoff_ms`, `error_class`, `budget_remaining`, `updated_at` | `a9_reconnect_states` | `a9:reconnect_events`, `a9:reconnect:{node_id}` | partial |
| `repair_action` | `action_id`, `kind`, `target`, `reason`, `required_arm`, `status`, `evidence_path`, `created_at` | `a9_repair_actions` | `a9:repair_events`, `a9:repair:{action_id}` | missing |
| `audit_event` | `event_id`, `actor`, `command`, `target`, `gate`, `before`, `after`, `evidence`, `created_at` | `a9_audit_events` | `a9:audit_events`, JSONL fallback | partial |

## State Contracts

### Node

Allowed states:

```text
unknown -> registering -> online -> stale -> offline
online -> degraded -> reconnecting -> online
degraded -> quarantine
offline -> reconnecting
```

Required transition evidence:

- `node_id`
- previous state
- next state
- reason
- observed timestamp
- heartbeat age
- actor or detector

### SSH Identity

Allowed states:

```text
unknown -> probing -> verified
probing -> auth_failed
probing -> host_key_failed
probing -> network_failed
verified -> disabled
```

Hard rule:

- `auth_failed` and `host_key_failed` are terminal until operator repair.
- Do not blindly retry terminal SSH identity failures.

### Tmux Session

Allowed states:

```text
unknown -> probing -> attached
probing -> missing
missing -> creating -> attached
attached -> detached
attached -> interrupted
detached -> attached
interrupted -> review_required
```

Hard rule:

- If a command was in flight when tmux became missing/interrupted, result state
  must become `interrupted` and require replay or operator review.

### Command

Allowed states:

```text
queued -> leased -> running -> succeeded
running -> failed
running -> timed_out
running -> interrupted
queued -> expired
leased -> stale_pending
stale_pending -> reclaimed
```

Hard rules:

- `command_id` is idempotency key.
- `expected_revision` must match mutable node/session state when present.
- `ttl_ms` must be enforced before execution.
- Remote mutation requires policy gate evidence.

### Command Result

Allowed states:

```text
pending -> streaming -> complete
pending -> failed
streaming -> interrupted
complete -> replayed
```

Required evidence:

- `command_id`
- result event id / stream id
- status
- stdout/stderr refs or compact summary
- next replay cursor

### Reconnect State

Allowed actions:

```text
continue
reconnect
terminate
quarantine
```

Required evidence:

- phase: `connect | stream | ssh | tmux | redis`
- error class
- attempt
- backoff
- budget remaining
- selected action

### Repair Action

Allowed states:

```text
proposed -> armed -> running -> succeeded
running -> failed
proposed -> rejected
proposed -> expired
```

Hard rules:

- Service restart, stale command recovery, supervisor mutation, and remote
  shell/tmux mutation require explicit command group or phone-control arm.
- Audit must record before and after.

## Stream / Key Contract

Minimum Redis Streams:

- `a9:tasks`: command/task queue.
- `a9:events`: command result and runtime events.
- `a9:heartbeats`: node heartbeat stream.
- `a9:operator_events`: operator control events.
- `a9:audit_events`: mutation audit.
- `a9:repair_events`: repair action lifecycle.
- `a9:reconnect_events`: reconnect decisions.

Minimum RedisJSON snapshots:

- `a9:node:{node_id}`
- `a9:command:{command_id}`
- `a9:command_result:{command_id}`
- `a9:tmux:{node_id}:{session_name}`
- `a9:reconnect:{node_id}`
- `a9:repair:{action_id}`

Minimum TimeSeries:

- `a9:ts:heartbeat:{node_id}`
- `a9:ts:latency:{node_id}`
- `a9:ts:reconnect_attempt:{node_id}`
- `a9:ts:queue_lag:{stream}:{group}`

## Current Code Mapping

Implemented or partly implemented:

- `scripts/a9_node.py`: node payload, command claim/ack/work loop, stale claim,
  command result event writing.
- `scripts/a9_control_api.py`: event replay, cursor gap handling, node
  registration/heartbeat, command result watch, service-control audit.
- `crates/a9-gateway/src/main.rs`: Redis roundtrip retry, reconnect lifecycle
  events, typed connect/stream action helpers, heartbeat/time-series writing.
- `crates/a9-worker/src/main.rs`: Redis `XREADGROUP`, task started/completed/
  failed event writing, ACK.

Missing or incomplete:

- MySQL communication schema.
- `operator_session` entity.
- `ssh_identity` entity.
- `tmux_session` entity.
- `repair_action` as first-class entity.
- uniform `expected_revision` across command/session/node mutation.
- explicit Redis key/index naming contract in code.

## Acceptance For v1

This contract is accepted when:

- product/mainline agrees SSH/tmux implementation waits for this data model;
- architecture agrees the MySQL/Redis split is the target;
- test/data agrees each next feature slice names the affected object and state
  transitions;
- runtime governance agrees remote mutation must be gated and audited.

### Role acceptance

- Product/mainline: accepts no runtime behavior change in this contract and that
  SSH/tmux implementation remains blocked until this data model is accepted.
- Architecture: accepts the object/state contracts and current-code mapping as the
  v1 baseline for next implementation slices.
- Test/data: accepts this contract as the conformance checklist and state
  transition source for future feature tests.
- Runtime governance: accepts remote mutation gating, audit, and revision controls as
  hard prerequisites derived from this contract.

### Residual risks

- Report conformance may be over-confident if future slices add mandatory fields not
  yet declared in MySQL/Redis key mapping.
- A non-mutating report surface can still diverge from truth under stale cache if
  reporting reads miss snapshot freshness controls.

### change_record

- Status changed from `v1_draft` to `v1_accepted_for_report_slice`.
- Object model and current-code mapping are kept unchanged.
- First implementation candidate remains non-mutating report endpoint/helper.

## First Decided Implementation Candidate

```text
decision_status: decided
phase: implement
task: add communication data-contract report
allowed_paths:
  - scripts/a9_control_api.py
  - tests/test_control_api.py
  - docs/communication-runtime-data-contract-v1.md
acceptance:
  - add a non-mutating report endpoint or helper that returns current
    conformance for the v1 objects as missing/partial/implemented
  - no SSH/tmux execution
  - no MySQL migration yet
  - focused tests pass
```

Reason:

- It makes the data contract observable before runtime behavior expands.
- It gives the mobile/control surface a stable readiness view later.
- It prevents feature work from hiding missing entities.

## Explicitly Not Approved Yet

- SSH bootstrap implementation.
- tmux attach/create/stream implementation.
- production MySQL migrations.
- WebSocket terminal streaming.
- multi-node auto-repair without operator arm.
