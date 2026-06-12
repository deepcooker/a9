# A9 Communication Runtime Bootstrap Execute Boundary

## Objective
This document defines the boundary between two control planes after terminal reconnect: `approved takeover` and `armed bootstrap execute`. It is a reference-scan artifact only and does not implement runtime changes.

## Problem
A terminal reconnect can now enter `await_bootstrap_takeover` and move through `bootstrap_takeover_admission`/`bootstrap_takeover_resume`/`bootstrap_takeover_reject`. The remaining risk is that a take-over operator approval and a bootstrap execute permission arm can drift apart, creating ambiguous execution semantics.

## Hard constraints for this slice
- No SSH execution in this scan.
- No tmux execution.
- No Tailscale mutation.
- No Redis/MySQL migration.
- No mobile UI changes.
- No implementation changes in this task.

## References used
- scripts/a9_control_api.py
- tests/test_control_api.py
- docs/communication-runtime-bootstrap-reference-scan.md
- docs/communication-observation-log.md
- reference-projects/openclaw/extensions/lobster/src/lobster-taskflow.ts
- reference-projects/openclaw/extensions/lobster/src/lobster-runner.ts
- reference-projects/barter-rs/barter-integration/src/socket/on_connect_err.rs
- reference-projects/barter-rs/barter-integration/src/socket/on_stream_err.rs

## Core boundary definitions

### Approved takeover
A record is in **approved takeover** when all of the following hold at execution time:
- Node status is `await_bootstrap_takeover`.
- `bootstrap_takeover.state == "approved"`.
- `bootstrap_takeover.decision == "resume_approved"`.
- This state is written by `bootstrap_takeover_resume` only, with `execution_enabled: false` and `no_actuation: true` in its response.
- Admission (`bootstrap_takeover_admission`) is always non-mutating toward remote execution; it increments revision, sets `status: "await_bootstrap_takeover"`, and emits a wait object with `approvalId`, `resumeToken`, `prompt`, and reconnect evidence.
- Resume/reject APIs enforce exact revision matching; stale revision => conflict.

### Armed bootstrap execute
`/api/nodes/bootstrap-execute` is **armed execute** state when:
- `command_gate("nodes.bootstrap.execute")` returns allowed.
- Phone-control arm is valid for the request and the route path is allowed.
- This path is actuation (SSH bootstrap transport in this system), and can return `status=ok`, `failed`, or `timeout`.
- This path is currently blocked even when armed if takeover is still waiting/not approved.

## Current behavior snapshot
From current code/test behavior:
- Terminal reconnect with action in {terminate, quarantine} maps to `await_bootstrap_takeover` in communication planning.
- `bootstrap_takeover_admission`:
  - increments node revision and sets `status: "await_bootstrap_takeover"`.
  - returns `status: "needs_approval"`, `execution_enabled: false`, `no_actuation: true`.
  - stores `wait` with `approvalId`/`resumeToken` and reconnect evidence.
- `bootstrap_takeover_resume`:
  - requires `expected_revision` exact match and waiting state.
  - transitions takeover state to `approved` and `decision: "resume_approved"`.
  - writes `no_actuation: true` and revision-forwarding evidence.
- `bootstrap_takeover_reject`:
  - requires exact revision and waiting state.
  - transitions `state: "rejected"` and records who rejected.
- `bootstrap_execute_node`:
  - still blocks when node record status is `await_bootstrap_takeover` unless takeover state is `approved`.
  - currently blocks on `bootstrap_action: "wait_for_approval"` with reason `bootstrap_takeover_not_approved` when not approved.
  - performs SSH command path only after normal arm+state checks pass.

## OpenClaw/Lobster alignment
- OpenClaw/Lobster flow pattern has strict revision-gated progression and explicit wait envelopes containing approval payloads (`resumeToken` / `approvalId`) when state enters needs-approval.
- This matches A9’s wait semantics and strengthens the boundary by requiring explicit transition checks before moving into execution.

## Barter-rs alignments
- `on_connect_err` distinguishes reconnect action outcomes.
- `on_stream_err` distinguishes continue vs reconnect behavior.
- The takeaway: terminal path should continue to be split by decision domain, while execution path stays separate and state-gated.

## Proposed next implementation slice (smallest possible)
Slice: `bootstrap-execute-approval-bridge-v1` (bounded and smaller than remote build)

Goal:
- Harden the boundary so `approved takeover` remains a pure admission/consent state and is not conflated with the arm-gated execution path.

Scope:
- Single function area: `bootstrap_execute_node` preconditions + tests.

Acceptance target:
1. Keep existing semantics: waiting takeover always returns blocked with `bootstrap_action="wait_for_approval"` and reason `bootstrap_takeover_not_approved`.
2. Add/confirm explicit `expected_revision` handling for execution bridge (if takeover state exists): mismatch must resolve before execution can proceed.
3. Preserve `No SSH execution` boundary in scan-only slice: no code edits made in this task; next implementation slice only.

Suggested test checks for the slice:
- stale execution against approved takeover with old revision should return conflict path before subprocess actuation.
- approved takeover + valid revision + armed path still executes with `bootstrap_action="continue"`.
- rejected or non-wait state continues to follow existing command gate semantics.
