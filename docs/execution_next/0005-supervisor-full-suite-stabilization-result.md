# 0005 Supervisor Full Suite Stabilization Result

## Scope

Repair the failures exposed after monitor intervention effect routing.

The goal was not to add new product behavior. It was to keep the 24h runtime execution path testable and prevent advisory/format gates from slowing the mainline.

## Root Causes

- `schedule_next_task` treated unprefixed `next_slice` as a hard blocker too broadly.
- Deterministic record handoff could be blocked even after a pass result with committed git governance.
- Slim monitor-blocked repair prompts lost compatibility cues used by existing regression tests.
- Async audit sidecar writes could race with `TemporaryDirectory` cleanup in control API tests.

## Implemented

- Relaxed `next_slice_missing_phase_prefix`:
  - still blocks explicit unprefixed worker next-slice output in `test` phase
  - does not block fallback phase-order scheduling outside that strict case
  - allows deterministic record handoff when git governance is already committed/skipped
- Restored monitor-blocked repair prompt markers:
  - `Monitor-blocked repair`
  - `compact_monitor_evidence`
  - `Declared checks are authoritative`
  - compact-evidence-first/change-request discipline
- Wrapped async audit append threads for communication/service/monitor audit with `OSError` safety.

## Verification

Passed:

```bash
python3 -m py_compile scripts/a9_supervisor.py scripts/a9_control_api.py
python3 -m unittest tests.test_control_api
python3 -m unittest tests.test_supervisor
```

Results:

- `tests.test_control_api`: 254 tests passed.
- `tests.test_supervisor`: 326 tests passed.

## Runtime Cleanup

Full supervisor tests generated one selftest auto queue artifact under `.a9/tasks/queue`; it was removed after verification so the 24h worker does not accidentally claim a test task.

## Next Slice

Continue from the now-clean runtime base:

- connect `approve/reject` monitor intervention actions to managed flow approval APIs
- add monitor-visible runtime control status to `/api/monitor/status`
- later migrate file runtime control state to Redis Stream after the file contract stays stable
