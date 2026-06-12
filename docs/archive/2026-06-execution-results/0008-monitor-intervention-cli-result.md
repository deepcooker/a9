# 0008 Monitor Intervention CLI Result

## Scope

Add a local CLI helper for monitor interventions so SSH/tmux/local operators can use the same control contract as the mobile API.

## Implemented

Added:

```bash
python3 scripts/a9_control_api.py monitor-intervention <action> [flags]
```

Actions:

- `pause`
- `resume`
- `repair`
- `route_to_debate`
- `approve`
- `reject`
- `change_request`
- `rollback_request`

Useful flags:

- `--reason`
- `--task-id`
- `--run-id`
- `--evidence-ref`
- `--flow-id`
- `--flow-expected-revision`
- `--flow-expected-last-seq`
- `--flow-sequence`
- `--evidence-id`
- `--idempotency-key`
- `--arm-duration`
- `--examples`

The CLI still uses the same `monitor_intervention()` path and phone-control gate. `--arm-duration 30s` only arms the existing runtime phone-control group before submitting the command.

## Examples

```bash
python3 scripts/a9_control_api.py monitor-intervention --examples
python3 scripts/a9_control_api.py monitor-intervention pause --reason "operator inspection" --arm-duration 30s
python3 scripts/a9_control_api.py monitor-intervention repair --task-id task-1 --run-id run-1 --evidence-ref .a9/runs/run-1/summary.json --arm-duration 30s
python3 scripts/a9_control_api.py monitor-intervention approve --flow-id flow-1 --flow-expected-revision 3 --evidence-id checkpoint-1 --reason "approved"
```

## Verification

Passed:

```bash
python3 -m py_compile scripts/a9_control_api.py
python3 -m unittest tests.test_control_api
```

Result:

- `tests.test_control_api`: 259 tests passed.

## Next Slice

Wire this CLI contract into the mobile control tab and add a Redis Stream mirror for monitor intervention events after the file/audit path stays stable.
