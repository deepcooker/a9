# Live Smoke: communication data-contract report endpoint

## Target
- Endpoint: `GET /api/communication/data-contract-report`
- Route helper: `communication_data_contract_report` in `scripts/a9_control_api.py`
- Contract: non-mutating report slice (read-only). This endpoint aggregates runtime contract metadata and does not alter persistence state.
- Last observed endpoint payload shape (control-api restarted, local check): `status: ok`, `kind: communication_data_contract_report`, 11 `objects`.

## Live contract checklist (operator evidence)
- HTTP: `GET /api/communication/data-contract-report`
- Required top-level response:
  - `status == ok`
  - `kind == communication_data_contract_report`
  - `contract_version == v1_draft`
  - `runtime_root` present
  - `required_fields` present
  - `objects` is an array
- Per-object required fields:
  - `object`
  - `status`
  - `current_surface`
  - `current_mapping`
  - `mysql_target`
  - `redis_target`
  - `required_fields`
  - `missing_fields_or_gap`
  - `evidence`
- Invariant checks observed in tests and implementation:
  - `len(objects) == len(COMMUNICATION_DATA_CONTRACT_OBJECTS)`
  - `objects` contains expected contract names from `COMMUNICATION_DATA_CONTRACT_OBJECTS`
  - object status values are one of `missing`, `partial`, `implemented`
  - when `object` query is passed, response contains only that object
  - unknown `object` returns single `missing` object row
- Expected known check token: `communication_data_contract_report` appears in `controller_discovery` endpoints list with route `/api/communication/data-contract-report`

## Non-mutating policy
- No SSH/tmux execution
- No MySQL migration
- This is explicitly a read/report endpoint and should stay read-only unless scope changes in decision packet

## Evidence source
- `scripts/a9_control_api.py`
  - Route dispatch in `ControlHandler.do_GET` includes `/api/communication/data-contract-report`
  - `communication_data_contract_report` constructs the response contract fields above
- `tests/test_control_api.py`
  - Endpoint contract tests validate `status`, `kind`, `contract_version`, object keys, and non-mutating response behavior

## Declared checks to pass
```bash
python3 - <<'PY'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8787/api/communication/data-contract-report', timeout=5) as r:
    payload = json.load(r)
assert payload['status'] == 'ok'
assert payload['kind'] == 'communication_data_contract_report'
assert len(payload['objects']) == 11
required = {'object', 'status', 'mysql_target', 'redis_target', 'required_fields', 'evidence', 'current_mapping'}
for row in payload['objects']:
    assert required <= set(row), row
print('communication_data_contract_report_live_smoke_ok')
PY

rg -n "communication_data_contract_report_live_smoke_ok|No SSH/tmux execution|No MySQL migration|11 objects|mysql_target|redis_target|required_fields" docs/communication-runtime-live-smoke.md
```

## Next recommended implementation slice
- Add/refresh a stable smoke-gate task for this endpoint in runtime evidence capture so the declaration can be asserted during regular `execution` phase checks.
- Add an explicit negative check for mutation attempts (e.g., ensure `GET` path is the only supported method in smoke harness).
- Keep an evidence-only update when contract field set changes.
