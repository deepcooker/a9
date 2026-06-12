# execution_next_0002_monitor_visibility_status Result

> Date: 2026-06-04
> Status: implemented

## Implemented

- Added `GET /api/monitor/status`.
- Added `monitor_status_contract` capability flag to `/api/discovery`.
- Added `monitor_status` endpoint entry to `/api/discovery`.

## Monitor Status View

The endpoint returns `a9.monitor_status.v1` with:

- queue summary: queued, running, done, queue tail, running tasks.
- latest run: task id, run id, status, phase, run directory.
- `next_action`: repair, continue, approve_or_reject, route_to_debate, or observe.
- monitor decision: model, score, block, intervention options.
- evidence refs: runtime monitor contract, summary, execution chain, evidence,
  state paths.
- failed checks and changed files.
- context pressure: prompt tokens, budget, ratio, remaining tokens, over-budget.
- worker intent and worker prompt pointers.
- command envelope.
- guardrails.
- service observation summary.
- node summary.

This gives monitor/mobile/CLI a bounded status view without reading full
`summary.json`, raw events, or evidence files.

## Verification

Passed:

```text
python3 -m py_compile scripts/a9_control_api.py
python3 -m unittest \
  tests.test_control_api.ControlApiTests.test_monitor_status_projects_runtime_contract_for_monitor \
  tests.test_control_api.ControlApiTests.test_api_monitor_status_endpoint_returns_monitor_payload \
  tests.test_control_api.ControlApiTests.test_controller_discovery_exposes_registration_contract \
  tests.test_control_api.ControlApiTests.test_api_status_endpoint_reads_supervisor_status_payload
python3 -m unittest tests.test_control_api
```

## Next Slice

Recommended next task:

```text
execution_next_0003_monitor_intervention_command_contract
```

Goal:

```text
Define and expose typed monitor intervention commands for pause, resume,
repair, change_request, approve, reject, rollback_request, and route_to_debate,
backed by evidence/audit entries instead of ad hoc UI actions.
```

