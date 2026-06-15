# execution_next_0001_runtime_monitor_foundation_packet

> Status: ready_for_monitor_review
> Route: execution_next
> Phase: decision_packet

## Goal

Convert the clarified A9 mainline into a bounded execution foundation for:

```text
24h worker + monitor + communication foundation
```

## Scope

- Keep page details frozen.
- Do not implement NZX business code.
- Do not vendor source.
- Do not perform broad workspace migration.
- Produce the P0 decision packet and first five runtime execution tasks.

## Inputs

- `docs/project.md`
- `docs/architecture/a9-runtime-monitor-foundation.md`
- `docs/decisions/ADR-0001-a9-highest-form.md`
- `docs/decisions/ADR-0002-runtime-monitor-priority.md`
- `docs/decisions/ADR-0003-communication-foundation.md`
- `docs/decisions/ADR-0004-reference-vendor-selection.md`
- `docs/decisions/ADR-0005-nzx-is-first-business-app.md`
- `docs/communication-governance-framework.md`
- `docs/requirements-review-closure.md`

## Allowed Execution After Monitor Approval

First implementation slice should be:

```text
execution_next_0001_runtime_monitor_contract
```

It should define or normalize the data contracts for:

- Task
- Run
- WorkerIntent
- WorkerPrompt
- EvidenceRef
- SessionLink
- MonitorIntervention
- CommandEnvelope

## Acceptance For This Packet

- ADRs exist for A9 highest form, runtime priority, communication foundation,
  reference selection, and NZX boundary.
- runtime/monitor foundation architecture exists.
- first implementation task is named and bounded.
- no code implementation is included in this packet.
