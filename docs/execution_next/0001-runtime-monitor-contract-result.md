# execution_next_0001_runtime_monitor_contract Result

> Date: 2026-06-04
> Status: implemented

## Implemented

- Added `a9.runtime_monitor_contract.v1` as a derived run artifact.
- Each normal supervisor run now writes:
  - `runtime_monitor_contract.json`
  - `summary.runtime_monitor_contract`
  - `summary.runtime_monitor_contract_path`
- Control API `latest_run` now exposes a compact `runtime_monitor_contract`
  view for monitor/mobile/CLI consumers.

## Contract Surface

The contract exposes:

- `task`: task id, phase, route, plan revision, allowed paths, declared checks.
- `run`: run id, status, attempt, run dir.
- `worker_intent`: visible phase focus, prompt preview, reference gate status.
- `worker_prompt`: prompt paths, token budget, context router.
- `reference_slices`: declared reference paths and reference gate evidence.
- `command_envelope`: command id, target node, expected revision, idempotency key,
  policy attestation, evidence path.
- `execution`: model, return code, timeout/budget status, event counts.
- `diff_and_checks`: changed files, diff path, guard statuses, checks and failures.
- `monitor`: next action and intervention options.
- `context_pressure`: prompt/context token pressure.
- `session_links`: previous context/session placeholders.
- `evidence_refs`: summary, execution chain, evidence, state, event, final, and
  monitor score paths.
- `guardrails`: page freeze, no NZX code, no compute RWA, no broad workspace
  migration, no source vendor copy.

## Verification

Passed:

```text
python3 -m py_compile scripts/a9_supervisor.py scripts/a9_control_api.py
python3 -m unittest tests.test_control_api
python3 -m unittest \
  tests.test_supervisor.SupervisorTests.test_task_decision_packet_ignores_embedded_template_fields \
  tests.test_supervisor.SupervisorTests.test_task_decision_packet_prompt_includes_decision_shaping_template \
  tests.test_supervisor.SupervisorTests.test_build_context_packet_routes_compact_decided_test_task_to_execution_next \
  tests.test_supervisor.SupervisorTests.test_build_context_packet_injects_task_declared_checks \
  tests.test_supervisor.SupervisorTests.test_runtime_monitor_contract_exposes_worker_monitor_and_command_contract \
  tests.test_supervisor.SupervisorTests.test_execution_chain_artifact_records_prompt_references_commands_checks_and_tokens \
  tests.test_supervisor.SupervisorTests.test_memory_commit_artifact_derives_rules_eval_and_next_task_from_execution_chain
```

Observed:

- Full `tests/test_supervisor.py` was run once and reported unrelated/flaky
  failures caused by live `.a9/tasks/queue` state and auto-next tests using the
  shared runtime directory. The focused supervisor contract/decision tests
  passed after fixing a real decision-packet parsing regression.

## Repair Done

- `task_decision_packet()` now uses the leading task declaration area for
  decision fields and only allows compact `test`/`repair` decision contracts
  when `decision_status` is explicitly declared at the task start.
- This prevents embedded decision templates in previous context from silently
  changing the current task contract.

## Next Slice

Recommended next task:

```text
execution_next_0002_monitor_visibility_status
```

Goal:

```text
Expose runtime_monitor_contract through explicit CLI/control endpoints and add
a monitor status view that highlights next_action, evidence refs, failed checks,
context pressure, and intervention choices without reading full summary.json.
```

