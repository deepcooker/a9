# 0006 Monitor Approval And Runtime Status Result

## Scope

Connect monitor intervention `approve/reject` actions to managed flow governance, and expose runtime control state to the monitor status API.

This keeps A9's rule: monitor decisions are typed, auditable, and routed through existing runtime governance instead of being treated as chat instructions.

## Reference Mechanisms Copied

- Codex-style compact runtime state: monitor UI reads a durable state object, not a chat summary.
- Managed-flow state transition: approval decisions use the existing Redis-backed flow transition mechanism.
- Sidecar audit discipline: audit remains async for production root, while test/temp roots write synchronously to avoid cleanup races.

## Implemented

- `approve` and `reject` monitor interventions now route to `transition_managed_flow` when the command includes:
  - `flow_id`
  - `flow_expected_revision` or `expected_revision`
  - optional `flow_expected_last_seq`
  - optional `flow_sequence`
  - optional `evidence_id`
- Missing flow contract does not hard-fail execution. It records `decision_only` with `missing_flow_contract`.
- `POST /api/monitor/intervention` command envelopes now carry flow fields.
- `/api/monitor/status` now includes `runtime_control` from `.a9/runtime/control_state.json`.
- Async audit enqueue now writes synchronously for non-production roots, avoiding `TemporaryDirectory` cleanup races in tests.

## Verification

Passed:

```bash
python3 -m py_compile scripts/a9_supervisor.py scripts/a9_control_api.py
python3 -m unittest tests.test_supervisor
python3 -m unittest tests.test_control_api
```

Results:

- `tests.test_supervisor`: 328 tests passed.
- `tests.test_control_api`: 254 tests passed.

## Runtime Cleanup

Verified after full test runs:

- `.a9/tasks/queue` had no leftover test task.
- `.a9/runtime/control_state.json` was not left in a paused or test state.

## Next Slice

Continue runtime control visibility and execution:

- add a small CLI/API example for monitor intervention payloads
- expose latest monitor intervention audit tail in mobile/control status
- then move runtime control state toward Redis Stream once file-contract behavior remains stable
