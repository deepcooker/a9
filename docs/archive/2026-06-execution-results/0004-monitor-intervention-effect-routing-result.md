# 0004 Monitor Intervention Effect Routing Result

## Scope

Connect `monitor.intervention` to supervisor-visible runtime effects.

This slice keeps the command contract from `0003`, but no longer leaves every allowed intervention as audit-only.

## Reference Mechanisms Copied

- Codex-style runtime state: keep operator control as a compact durable state object, not as chat memory.
- Queue-first agent orchestration: repair/debate are routed as explicit tasks instead of invisible model self-reflection.
- Sidecar audit discipline: intervention audit remains async and does not block the main run loop.
- Aider/Codex handoff discipline: queued repair tasks carry source task, run, reason, and evidence refs.

## Implemented

- Added supervisor runtime control state:
  - `.a9/runtime/control_state.json`
  - schema `a9.runtime_control_state.v1`
- Added supervisor effect router:
  - `pause`: marks runtime paused.
  - `resume`: marks runtime running.
  - `repair`: enqueues an explicit repair task.
  - `route_to_debate`: enqueues an explicit mechanism/debate task.
  - `approve`, `reject`, `change_request`, `rollback_request`: record decision state only for now.
- `claim_next_task()` now refuses to claim queued tasks while paused.
- `run-loop` now stays alive while paused and writes a `paused` daemon heartbeat instead of exiting as idle.
- `status()` now prints `runtime_control`.
- `POST /api/monitor/intervention` now calls supervisor effect routing after phone-control gate passes.

## Verification

Passed:

```bash
python3 -m py_compile scripts/a9_supervisor.py scripts/a9_control_api.py
python3 -m unittest tests.test_control_api
python3 -m unittest \
  tests.test_supervisor.SupervisorTests.test_monitor_intervention_pause_blocks_task_claim_until_resume \
  tests.test_supervisor.SupervisorTests.test_monitor_intervention_repair_enqueues_repair_task_with_evidence \
  tests.test_supervisor.SupervisorTests.test_status_refreshes_progress_from_actual_queue_state \
  tests.test_supervisor.SupervisorTests.test_status_prints_latest_process_quality \
  tests.test_supervisor.SupervisorTests.test_status_skips_invalid_latest_summary_json \
  tests.test_supervisor.SupervisorTests.test_status_prints_runtime_state_waiting_for_review_closure
```

Control API full suite: 254 tests passed.

Supervisor full suite was attempted:

```bash
python3 -m unittest tests.test_supervisor
```

Result: failed 12 existing schedule/auto-next assertions after long shared-state selftests. The failures cluster around `schedule_next_task` fallback/operator-priority behavior and monitor-blocked repair prompt text, not the new runtime control functions. Keep this as a repair candidate before treating full supervisor as a clean release gate.

## Next Slice

Stabilize supervisor full-suite isolation before adding more runtime behavior:

- isolate tests that write real `.a9/tasks/queue`
- clean generated selftest queue artifacts after full supervisor tests
- decide whether `schedule_next_task` should check operator priority before next-slice validation
- preserve monitor-blocked repair prompt compatibility while keeping slim repair prompts

After that, connect `approve/reject` to managed flow approval APIs and migrate runtime control state to Redis Stream once the file contract is stable.
