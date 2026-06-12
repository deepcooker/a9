# 0011 Monitor Control Aggregate Result

## Scope

Add a single monitor control aggregate endpoint for mobile/control clients.

The goal is to reduce mobile startup complexity: one request gives the operator status, intervention examples, recent audit state, and stream reconnect hints.

## Implemented

- Added `monitor_control()`.
- Added endpoint:
  - `GET /api/monitor/control`
- Added discovery entry:
  - `endpoints.monitor_control`
  - `runtime.monitor_control_contract`

The aggregate response includes:

- `monitor_status`
- `intervention_examples`
- `intervention_stream`
  - stream name
  - JSON events endpoint
  - SSE endpoint
  - recent event count
  - next cursor when available
- action endpoint metadata

## Verification

Passed:

```bash
python3 -m py_compile scripts/a9_control_api.py
python3 -m unittest tests.test_control_api
```

Result:

- `tests.test_control_api`: 266 tests passed.

## Next Slice

Connect the mobile control tab to:

- initial load: `GET /api/monitor/control`
- live updates: `GET /api/monitor/interventions/events?format=sse`
