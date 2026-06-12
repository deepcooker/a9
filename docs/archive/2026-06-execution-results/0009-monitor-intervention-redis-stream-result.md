# 0009 Monitor Intervention Redis Stream Result

## Scope

Mirror monitor intervention audit events into Redis Stream so mobile/multi-machine control can subscribe to interventions without polling JSONL files.

## Implemented

- Added Redis Stream key:
  - `a9:monitor:interventions`
- Added `publish_monitor_intervention_redis(event)`.
- `monitor_intervention()` now:
  - builds the same audit event
  - publishes a compact Redis Stream event when Redis is available
  - embeds `redis_mirror` status in the JSONL audit event and API response
  - keeps file audit as the durable fallback
- `/api/discovery` now exposes:
  - `runtime.monitor_intervention_redis_stream = a9:monitor:interventions`

## Failure Behavior

Redis is not a hard dependency for monitor intervention:

- Redis unavailable: command still records file audit and returns `redis_mirror.status = skipped`.
- Redis XADD failure: command still records file audit and returns `redis_mirror.status = failed`.

This matches the current A9 rule: Redis is the fast hot path, not the only fact store.

## Verification

Passed:

```bash
python3 -m py_compile scripts/a9_control_api.py
python3 -m unittest tests.test_control_api
```

Result:

- `tests.test_control_api`: 261 tests passed.

## Next Slice

Expose this stream through mobile/control realtime status:

- add an endpoint to replay `a9:monitor:interventions`
- optionally add SSE format with `Last-Event-ID`
- connect mobile control tab to `recent_interventions` first, then stream replay
