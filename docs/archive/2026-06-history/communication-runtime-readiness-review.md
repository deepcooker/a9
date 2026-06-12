# A9 Communication Runtime Readiness Review

Date: 2026-06-02
Scope: bounded `debate_next` review, no runtime code changes.

## Route And Decision Posture

`decision_status`: partial_decision
`route`: `debate_next`
`status`: no implementation committed in this review; this document records analysis and a recommended next packet.

## Real Problem Restatement

A9 must choose the next communication-runtime implementation object by data/model readiness, not by feature convenience. The control plane now has a v1 data-contract report and discovery endpoint, but object-level readiness is uneven.

## Evidence Window

- `docs/communication-runtime-data-contract-v1.md`
- `docs/communication-runtime-decision-packet.md`
- `docs/communication-runtime-role-review.md`
- `scripts/a9_control_api.py` communication report, discovery, command/result surfaces
- `scripts/a9_node.py` command and heartbeat slices

## Current Conformance

| Object | v1 status | Readiness | Evidence path | Primary gaps |
|---|---|---:|---|---|
| `operator_session` | missing | 0/10 | control service and operator-tail paths exist, but no first-class object | session schema, MySQL table, RedisJSON key, event/capability surface |
| `node` | partial | 4/10 | `node_status()`, registration, heartbeat, node command loop | split authority, weak state transition evidence |
| `ssh_identity` | missing | 0/10 | remote/SSH helpers only | no identity lifecycle entity, no host/key trust state |
| `tmux_session` | missing | 0/10 | tmux plans/routes only | no first-class tmux object, no in-flight command recovery state |
| `command` | partial | 4/10 | command claim/work loop and command endpoints | incomplete persistence contract, `expected_revision` not uniform |
| `command_result` | partial | 3/10 | result lookup/watch and node parsing flows | lifecycle and replay contract incomplete |
| `event_cursor` | partial | 2/10 | `Last-Event-ID` and result cursor handling | no persisted per-consumer recovery object |
| `heartbeat` | partial | 3/10 | heartbeat registration and node heartbeat CLI | partial transition and budget model |
| `reconnect_state` | partial | 2/10 | gateway reconnect decisions visible | no centered state object with phase/action/budget |
| `repair_action` | missing | 0/10 | repair suggestions/payloads only | no lifecycle table, transitions, or before/after audit |
| `audit_event` | partial | 2/10 | service-control audit tails/logs | no canonical actor/command/target/before/after object |

## Next Object Ranking

1. `operator_session` (P0): highest authority gap. Stable operator control, permission scope, and audit cannot be correct without actor/session authority.
2. `event_cursor` (P1): needed for deterministic replay, gap handling, command watch recovery, and operator continuity.
3. `reconnect_state` (P1): needed to normalize reconnect actions, budgets, error classes, and evidence across unstable network/stream states.
4. `repair_action` (P2): needed to turn suggestion -> armed -> executed -> audited into a first-class lifecycle instead of advisory side effects.
5. `tmux_session` + `ssh_identity` (P2/P3): business-relevant, but should wait until operator authority, cursor continuity, and reconnect state are first-class.
6. `audit_event` and `heartbeat` hardening (P2): cross-cutting acceptance quality, but less blocking than the control-continuity objects above.

## Reference Mechanisms

- Codex-style governance-first continuation already summarized in local worker/context docs: explicit continuation state, compact handoff as index, and no raw-log prompt flooding.
- OpenClaw/Lobster-style revision-gated waiting and runner boundaries, as cited in `docs/communication-runtime-decision-packet.md`.
- Barter-rs-style reconnect taxonomy, backoff, stream consumer behavior, and failure classification, as cited in `docs/communication-runtime-decision-packet.md`.
- Redis Streams/JSON/TimeSeries ecology from the decision packet: stream ownership, pending/stale diagnosis, hot snapshots, and health/latency time series.

## Do Not Do

- Do not implement tmux attach/create/streaming until `operator_session`, `event_cursor`, and `reconnect_state` are first-class.
- Do not ship `repair_action` as advisory payload only; it must be entity-shaped with lifecycle state.
- Do not start MySQL migration or multi-node behavior rollout before contract-slice acceptance.
- Do not expand mobile/UI polish before durable data/state contract is stable.

## Data-Readiness Follow-Up

- `a9:operator_events` and `a9:operator:{operator_id}:{client_id}` authority keys are still missing from runtime mapping.
- No first-class table evidence exists for `a9_operator_sessions`, `a9_reconnect_states`, or `a9_repair_actions`.
- `event_cursor` currently behaves as protocol helper via headers/params, not as entity-level state.

These gaps should force another `debate_next` packet before behavior expansion.

## Recommended Next Task Packet

```text
decision_status: partial_decision
route: debate_next
problem: operator_session + event_cursor + reconnect_state readiness is blocking control continuity and replay safety.
system_requirement: define and validate first-class object models for operator_session, event_cursor, and reconnect_state before adding tmux/repair automation.
data_contract: object fields, authority store, Redis keys, state transitions, invariants, and evidence mapping for the three objects.
state_flow: baseline evidence -> object schema proposal -> transition proposal -> exception gates -> role review -> execution slice approval.
exception_flow: if ownership or field semantics remain ambiguous, stop with a follow-up debate packet; reject work that creates command/tmux behavior without operator/session authority.
acceptance: docs-only model closure with object tables, transition states, persistence keys, mapping to existing control/node surfaces, explicit out-of-scope, and role signoff checklist.
out_of_scope: no code mutation, no migration, no mobile UI, no SSH/tmux execution change.
allowed_execution: write a bounded model-closure doc and README index only.
role_signoff: Product/Mainline + Architecture + Test/Data + Runtime Governance.
```

## Monitor Risks

1. `repair` can become command-only workflow without lifecycle object, leaking auditability.
2. tmux automation can drift from plan/evidence scripts into action without `ssh_identity` hardening.
3. command watch/replay confidence will remain low without canonical `event_cursor` persistence and recovery policy.
