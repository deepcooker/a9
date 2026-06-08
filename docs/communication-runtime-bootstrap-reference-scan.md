# A9 Communication Runtime Bootstrap / Takeover Reference Scan

## Scope
- Bounded reference scan only; no implementation changes.
- Focus: SSH/Tailscale/tmux bootstrap and takeover governance.
- Hard constraints for this slice:
  - No remote execution.
  - No SSH command execution.
  - No Tailscale mutation.
  - No tmux command execution.
- Objective: identify copy-ready mechanisms and define one smallest next implementation slice.

## Data-first checkpoint
- `docs/communication-runtime-data-contract-v1.md` already defines the object/state surface (operator_session, node, ssh_identity, tmux_session, command, command_result, cursor, heartbeat, reconnect_state, repair_action, audit_event).
- The contract explicitly blocks SSH/tmux feature start before contract readiness and requires durable state + Redis evidence.
- `docs/communication-governance-framework.md` already marks Redis Streams/SSE as primary ordered event plane and labels SSH/tmux as bootstrap/manual takeover fallback.

## Mechanism scan and adaptation decisions

### 1. Barter-rs typed reconnect / error domain
- `reference-projects/barter-rs/barter-integration/src/socket/on_connect_err.rs`
  - Copy: `ConnectErrorAction = Reconnect | Terminate` behavior.
- `reference-projects/barter-rs/barter-integration/src/socket/on_stream_err.rs`
  - Copy: `StreamErrorAction = Continue | Reconnect` behavior.
- `reference-projects/barter-rs/barter-integration/src/socket/backoff.rs`
  - Copy: bounded exponential backoff shape.
- `crates/a9-gateway/src/main.rs`
  - Already has `GatewayReconnectDecision` rows (`phase`, `action`, `error_class`, `attempt`, `delay_ms`, `policy_budget_remaining`) and emits typed reconnect decision events.
- `scripts/a9_node.py`
  - Already maps reconnect outputs in `classify_node_connection_state` into state/action (`retry`, `observe`, `continue`, `quarantine`, `escalate`).

Decision: adopt typed action plus evidence pattern; do not duplicate stream mechanics blindly.

### 2. OpenClaw / Lobster managed-flow revision + approval controls
- `reference-projects/openclaw/extensions/lobster/src/lobster-taskflow.ts`
  - Copy: expected-revision guarded `runManagedLobsterFlow` and `resumeManagedLobsterFlow`, and `setWaiting` on `needs_approval`.
- `reference-projects/openclaw/extensions/lobster/src/lobster-taskflow.test.ts`
  - Validates expected behavior: `needs_approval` -> `await_lobster_approval`, resume token flow, resume success/failure.
- `reference-projects/openclaw/extensions/lobster/src/lobster-runner.ts`
  - Copy: strict envelope normalization and approval payload (`resumeToken` / `approvalId`).

Decision: mirror envelope + approval state semantics for bootstrap admission and manual takeover handoff.

### 3. Codex / architecture boundary
- Requested file `reference-projects/codex/codex-rs/core/src/tasks/mod.rs` is missing in this worktree.
- Closest usable local reference: `reference-projects/codex/codex-rs/app-server-transport/src/transport/remote_control/mod.rs` for remote-control enable/status guard patterns.

Decision: keep Codex copy boundary to long-running control session concepts only; no blind local implementation.

## Bootstrap / Takeover Vs Primary Redis Bus
Primary control plane:
- REST typed command plane.
- Redis Streams for ordered command/control/audit event evidence (`a9:events`, `a9:operator_events`, `a9:reconnect_events`, `a9:repair_events`) and replay.
- SSE tailing for operator observation.

Fallback plane:
- SSH/Tailscale/tmux used only for bootstrap handoff or explicit manual takeover, and only as controlled fallback.

## Proposed Next Implementation Slice
Slice: `reconnect-governed-bootstrap-admission-v1`

1. Add a managed admission step for bootstrap takeover that writes only state/evidence, with no actuation.
2. On reconnect terminal events, transition to `await_bootstrap_takeover` with `expected_revision` checks.
3. Reuse managed-flow style:
   - wait object includes `{prompt, items, resumeToken|approvalId}`.
   - resume transitions require revision match and are audit-logged.
4. Preserve primary bus: all transitions must emit `gateway_reconnect_decision`-typed evidence and operator replay events.
5. Hard acceptance: no SSH/Tailscale/tmux command execution in this slice.
