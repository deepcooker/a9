# 0010 Monitor Intervention Stream Replay Result

## Scope

Expose Redis Stream replay for monitor interventions so mobile/control clients can read intervention events with cursor-based reconnect.

## Implemented

- Added `read_redis_stream(stream_key, last_id, limit)`.
- Kept `/api/events` behavior by routing it through the generic stream reader.
- Added monitor intervention stream reader:
  - `read_monitor_intervention_events()`
- Added endpoint:
  - `GET /api/monitor/interventions/events`
- Supported response formats:
  - JSON by default
  - SSE with `?format=sse`
- Supported replay cursor:
  - `last_id` query param
  - `Last-Event-ID` request header for SSE clients
- Added discovery entry:
  - `endpoints.monitor_intervention_events`

## Endpoint Examples

```bash
curl 'http://127.0.0.1:8787/api/monitor/interventions/events?limit=20'
curl 'http://127.0.0.1:8787/api/monitor/interventions/events?last_id=1740000000-0&limit=20'
curl -H 'Last-Event-ID: 1740000000-0' 'http://127.0.0.1:8787/api/monitor/interventions/events?format=sse&limit=20'
```

## Verification

Passed:

```bash
python3 -m py_compile scripts/a9_control_api.py
python3 -m unittest tests.test_control_api
```

Result:

- `tests.test_control_api`: 264 tests passed.

## Next Slice

Connect mobile/control UI to:

- `/api/monitor/status.recent_interventions` for initial paint
- `/api/monitor/interventions/events?format=sse` for live updates and reconnect
