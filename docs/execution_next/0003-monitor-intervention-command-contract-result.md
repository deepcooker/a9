# 0003 Monitor Intervention Command Contract Result

## Scope

Build the first deterministic contract for monitor/operator intervention.

This slice does not make `pause`, `resume`, or `repair` directly mutate the worker loop yet. It records a typed command and async audit event first, so the monitor intent becomes durable evidence before supervisor effect routing is attached.

## Reference Mechanisms Copied

- Codex-style command gating: privileged mutation must pass an explicit control gate instead of trusting plain chat intent.
- Aider/Codex edit discipline: small command envelope with task/run/revision/evidence refs, not a giant prompt blob.
- Runtime audit sidecar pattern: write intervention evidence asynchronously so review does not block the main execution path.
- LangGraph-like checkpoint thinking: keep the command envelope replayable through `task_id`, `run_id`, `expected_revision`, and `idempotency_key`.

## Implemented

- Added control command `monitor.intervention` to the runtime phone-control group.
- Added `POST /api/monitor/intervention`.
- Added `GET /api/monitor/interventions/audit`.
- Added discovery entries:
  - `endpoints.monitor_intervention`
  - `endpoints.monitor_intervention_audit`
  - `runtime.monitor_intervention_contract`
- Added `a9.monitor_intervention.v1` command envelope:
  - `action`
  - `reason`
  - `actor`
  - `task_id`
  - `run_id`
  - `expected_revision`
  - `idempotency_key`
  - `evidence_refs`
  - compact `monitor_status_snapshot`
  - `execution_effect.mode = audit_only`
- Added async JSONL audit at `.a9/monitor/interventions.jsonl`.

## Verification

Commands:

```bash
python3 -m py_compile scripts/a9_control_api.py
python3 -m unittest \
  tests.test_control_api.ControlApiTests.test_monitor_intervention_requires_arm_and_records_async_audit \
  tests.test_control_api.ControlApiTests.test_api_monitor_intervention_post_route_calls_handler \
  tests.test_control_api.ControlApiTests.test_monitor_intervention_audit_tail_bounds_newest_events \
  tests.test_control_api.ControlApiTests.test_api_monitor_intervention_audit_route_passes_limit \
  tests.test_control_api.ControlApiTests.test_controller_discovery_exposes_registration_contract
python3 -m unittest tests.test_control_api
```

Result: pass. Full control API suite: 254 tests.

## Next Slice

Attach `monitor.intervention` to supervisor effect routing:

- `pause`: stop claiming new worker tasks, do not kill current run by default.
- `resume`: clear pause state.
- `repair`: enqueue a repair task with evidence refs.
- `route_to_debate`: enqueue requirements/architecture debate packet.
- `approve/reject`: connect to existing approval command path.

Keep all evaluator/reviewer work async sidecar. Do not turn these commands into hard gates until the business/data model and runtime state machine are stable.
