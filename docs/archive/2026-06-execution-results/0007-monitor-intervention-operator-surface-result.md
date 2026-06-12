# 0007 Monitor Intervention Operator Surface Result

## Scope

Make monitor intervention usable from mobile/control surfaces without requiring the operator to remember payload shapes or call multiple endpoints.

## Implemented

- Added `GET /api/monitor/intervention/examples`.
- Added discovery entry:
  - `endpoints.monitor_intervention_examples`
  - `runtime.monitor_intervention_examples`
- Added reusable payload examples for:
  - `pause`
  - `resume`
  - `repair`
  - `route_to_debate`
  - `approve`
  - `reject`
- `/api/monitor/status` now embeds the latest monitor intervention audit tail as `recent_interventions`.

## Behavior

The examples endpoint uses the latest monitor status to fill:

- `task_id`
- `run_id`
- compact evidence refs

Approve/reject examples include the flow fields needed by managed flow governance:

- `flow_id`
- `flow_expected_revision`
- `evidence_id`

## Verification

Passed:

```bash
python3 -m py_compile scripts/a9_control_api.py
python3 -m py_compile scripts/a9_supervisor.py
python3 -m unittest tests.test_control_api
```

Result:

- `tests.test_control_api`: 256 tests passed.

## Next Slice

Continue operator usability:

- add a minimal CLI helper for `monitor-intervention pause|resume|repair|approve|reject`
- surface `recent_interventions` in the mobile app control tab
- add Redis Stream mirror for monitor interventions after the file/audit contract remains stable
