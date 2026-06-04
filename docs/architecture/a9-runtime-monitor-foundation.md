# A9 Runtime Monitor Foundation

> Status: decision packet input
> Date: 2026-06-04
> Route: P0 requirements/ADR closure for `24h worker + monitor + communication foundation`

## Decision

A9's first engineering focus is the stable execution foundation:

```text
24h worker
+ monitor / intervention loop
+ communication foundation
+ evidence / session governance
+ bounded execution contracts
```

The financial AgentOS architecture is the target environment. NZX RWA, mobile
page polish, compute RWA, and broad crate migration are not the first
execution focus.

## Problem

A9 already has many useful MVP pieces:

- Python supervisor, auto-next, task/run evidence.
- session refresh and close-reading.
- patch apply, patch guard, scope guard.
- Redis Streams gateway prototype.
- control API and early mobile/control surface.
- local reference project pool.

The problem is not missing ideas. The problem is that long execution can still
drift when requirements, monitor visibility, task state, communication, and
evidence are not strict enough.

## Requirement Method

No large worker slice can run until it has:

```text
problem
goal
business/data model
state flow
failure/exception flow
reference mechanisms
scope
out_of_scope
acceptance
evidence path
plan revision
```

Business/data first, performance second:

- Data means objects, fields, states, authority source, permissions, audit, and
  exception flow.
- Performance means latency, throughput, reliability, recovery, cost, pressure,
  and observability.

If these are missing, the route is `debate_next`, not `execution_next`.

## Runtime Objects

Minimum shared model:

```text
PlanContract
Task
Run
WorkerIntent
WorkerPrompt
ReferenceSlice
Command
Event
Evidence
SessionLink
MonitorIntervention
RepairRequest
```

Authority:

- `PlanContract`: owned by human/product/requirements/monitor.
- `WorkerIntent`: proposed by worker, visible before execution.
- `Run`: deterministic runtime state.
- `Evidence`: immutable run facts and bounded excerpts.
- `SessionLink`: link from run evidence to operator/raw session evidence.
- `MonitorIntervention`: explicit human/main-monitor action with reason.

Worker may append findings, progress, mistakes, evidence, and change requests.
Worker must not silently change goal, scope, acceptance, or out-of-scope.

## Monitor Must See

Before and during each run:

- task id, plan revision, route, phase.
- worker intent and why it is the next action.
- bounded prompt and context budget.
- reference projects and exact slices read.
- files allowed to write.
- command chain and tool results.
- diff summary.
- tests/checks and pass/fail status.
- evidence paths.
- session links to operator/raw session and close-reading batch.
- token/context pressure indicators.
- retry, repair, pause, approve, reject, rollback actions.

The monitor should be able to intervene with:

```text
pause
resume
repair
change_request
approve
reject
rollback_request
route_to_debate
```

## Communication Foundation

First communication model:

```text
Operator CLI / future Mobile / Web
  -> typed command over REST
  -> event tail over SSE first
  -> Rust gateway / current prototype adapter
  -> Redis Streams hot event bus
  -> Python supervisor and workers
  -> MySQL/PostgreSQL durable state later
  -> SSH/tmux fallback for node repair
```

## Command Envelope

Command envelope must include:

```text
command_id
target_node
expected_revision
ttl
created_by
policy_attestation
idempotency_key
evidence_path
```

Node state machine:

```text
online -> stale -> offline -> degraded -> reconnecting -> online
```

Redis is a hot control/event bus and mirror. It is not the trading ledger and
not the final authority for business state.

## Reference Mechanisms Needed Now

Immediate runtime/communication references:

- Codex: event loop, compact derived from raw evidence, tool execution, resume.
- Aider: deterministic SEARCH/REPLACE and diff discipline.
- OpenClaw/Lobster: managed flow, revision, approval wait/resume, envelope.
- Barter-rs: reconnect backoff, typed stream errors, audit replica, command boundary.
- planning-with-files: file plan recovery and attestation without worker plan ownership.
- mem0/LangGraph: memory API shape and checkpoint lineage as minimal contracts.

Direct source copy is not allowed in this slice. Any direct vendor candidate
must be marked `pending_license_vendor_manifest`.

## Keep / Wrap / Archive Table

| Current asset | Current value | Decision for this phase |
| --- | --- | --- |
| `scripts/a9_supervisor.py` | working 24h MVP loop | keep, wrap with clearer task contracts |
| `scripts/a9_session_refresh.py` | external Codex session indexing | keep, connect as evidence source |
| `scripts/a9_checkpoint.py` | checkpoint lineage prototype | keep, map to runtime contract |
| `scripts/a9_memory.py` | mem0-shaped adapter | keep as prototype |
| `scripts/a9_patch_apply.py` | deterministic apply prototype | keep, later migrate behind edit contract |
| `scripts/a9_control_api.py` | current control API | keep as debug/control adapter |
| `crates/a9-gateway` | Redis Streams prototype | keep, mark as bus/gateway prototype until ADR decides rename |
| `crates/a9-client` | CLI entry | keep, future operator client |
| `crates/a9-worker` | worker wrapper | keep, future node-side worker |
| Mobile page details | useful product shell | freeze for now |
| NZX code | first future business app | out of scope now |

## First Five Execution Tasks

1. `execution_next_0001_runtime_monitor_contract`
   Define task/run/intent/evidence/intervention contracts and update supervisor output to expose them.
2. `execution_next_0002_monitor_visibility_status`
   Add or normalize status endpoints/CLI output for intent, prompt, evidence, tests, context pressure, and intervention history.
3. `execution_next_0003_command_envelope_contract`
   Define typed command envelope and map current control API / Redis prototype to it.
4. `execution_next_0004_reference_mechanism_map_runtime`
   Produce runtime-focused mechanism map from Codex, Aider, OpenClaw, Barter-rs, planning-with-files.
5. `execution_next_0005_noise_cleanup_runtime_safe`
   Archive stale docs/code only after a keep/archive manifest; do not delete evidence.

## Acceptance

This P0 packet is acceptable when:

- A9 vs NZX boundary is explicit.
- runtime/monitor/communication priority is explicit.
- page freeze is explicit.
- worker guarantees and monitor visibility are explicit.
- communication command envelope is explicit.
- current MVP keep/wrap/archive table exists.
- first five execution tasks are listed.
- no source copy or broad code migration is authorized.
