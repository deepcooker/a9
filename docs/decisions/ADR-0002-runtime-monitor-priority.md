# ADR-0002: Runtime Monitor Priority

> Status: accepted
> Date: 2026-06-04

## Decision

The first execution focus is:

```text
24h worker + monitor + communication foundation
```

Page details, NZX business code, compute RWA, and broad workspace migration are
frozen until this foundation has a closed decision packet and bounded execution
tasks.

## Context

A9 already has a working MVP execution loop, but it can drift if monitor
visibility, task contracts, session evidence, and communication state are not
governed. The system must be able to run many small tasks under supervision
before it can safely execute larger business implementation.

## Required Guarantees

- Every task has route, plan revision, scope, out_of_scope, acceptance, and
  evidence path.
- Worker intent and prompt are visible before execution.
- Reference slices are recorded.
- Diff/tests/logs/evidence are linked to the run.
- Monitor interventions are recorded with reason.
- Failed checks create repair/change_request instead of silent continuation.

## Consequences

- The next task is a runtime/monitor/communication decision and contract slice.
- Worker must not start UI polish or NZX implementation from the GPT decision
  package alone.

