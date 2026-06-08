# A9 Current Decision Packet

## decision_status

decision_status: partial_decision.
route: debate_next

This packet approves only the next requirements-contract slice. It does not
approve production feature expansion.

## problem

problem: A9 can run 24h worker tasks, but undecided analysis outputs were previously
auto-continued into `test` or `repair` tasks. That caused broad runtime/session
reads, stale progress display, and token-heavy loops.

The real problem is not missing code volume. The real problem is missing task
contract closure between `debate_next` and `execution_next`.

## system_requirement

system_requirement: A9 must make the debate-to-execution handoff explicit:

- A task with explicit `decision_status` and route `debate_next` must stop after
  review/change-request evidence until monitor/product decision.
- A task can enter `execution_next` only when the task packet has complete
  `system_requirement`, `data_contract`, `state_flow`, `acceptance`,
  `out_of_scope`, and `allowed_execution`.
- Status/control surfaces must report actual queue/running state, not stale
  progress snapshots.
- Workers must not treat review output as permission to run new code/test
  slices.

## data_contract

data_contract: Minimum task packet fields:

- `decision_status`: `not_decided`, `partial_decision`, or `decided`.
- `route`: derived from decision packet as `debate_next` or `execution_next`.
- `problem`: the real business/system problem, not the proposed solution.
- `system_requirement`: required system behavior.
- `data_contract`: objects, fields, invariants, and evidence keys.
- `state_flow`: normal transitions and authority order.
- `exception_flow`: failure, repair, approval, and monitor intervention paths.
- `acceptance`: declared checks and evidence required for completion.
- `out_of_scope`: explicit exclusions for this slice.
- `allowed_execution`: allowed files, commands, and phase.
- `change_record`: what changed in direction, scope, or authority and why.

Minimum runtime evidence fields:

- task id, phase, decision route, allowed paths, checks.
- run id, status, summary path, events path, context pressure.
- patch/scope/process governance findings.
- next task path only when the queued task file exists.

## state_flow

state_flow: normal flow:

```text
debate_next
-> review_packet
-> role_review
-> decision_packet
-> execution_next task
-> worker patch/check
-> supervisor guard/test/git
-> record progress
```

Authority order:

```text
human/operator decision
-> decision packet / active plan contract
-> task frontmatter allowed_paths/checks
-> run evidence
-> progress/status view
```

`progress.json` is a view, not authority.

## exception_flow

exception_flow:
- Missing decision fields: remain `debate_next`, do not auto-next into
  `test`/`implement`/`repair`.
- Stale next task path: clear progress `next_task_path` unless the file exists.
- Worker broad runtime/session reads: record process-governance finding and
  monitor intervention; do not silently treat self-report as pass.
- Undeclared checks: keep as observation/proposal unless promoted into declared
  task checks by monitor/product decision.
- Strict envelope parse failure: salvage only when deterministic patch/check
  evidence proves the result is acceptable.

## acceptance

acceptance: this decision slice is accepted when:

- `scripts/a9_supervisor.py::schedule_next_task` blocks explicit `debate_next`
  auto-continuation.
- Legacy tasks without explicit `decision_status` still route normally.
- `service_progress()` clears missing `next_task_path`.
- `status()` refreshes progress from actual queue/running state.
- Focused supervisor tests pass.
- CLI status shows `queued=0`, `running=0`, and empty `next=` when queue is
  empty.

## out_of_scope

out_of_scope:
- No mobile UI work.
- No communication/runtime feature expansion.
- No finance/quant strategy work.
- No hard numeric token gate based only on arbitrary counts.
- No new broad gate that blocks exploration before data and state contracts are
  settled.
- No copying additional source code.

## allowed_execution

allowed_execution:
- `docs/a9-current-decision-packet.md`
- `test -s docs/a9-24h-two-lane-review-closure.md`

Allowed checks:

- `test -s docs/a9-24h-two-lane-review-closure.md`

## role_signoff

role_signoff:
Product/mainline:
- Approves stopping undecided tasks before auto-next execution.
- Does not approve feature expansion until the next execution packet is decided.

Business:
- Approves the current object model: task, run, flow, progress view, operator
  decision, governance finding.
- Requires `out_of_scope` and `change_record` on future execution tasks.

Architecture:
- Approves `progress.json` as a view only.
- Requires queue/running directories and run summaries to remain authoritative.

Test/acceptance:
- Requires focused tests for decision routing and stale progress.
- Requires CLI status evidence for actual queue/running state.

## change_record

change_record: monitor closure keeps this packet bounded to decision-record repair; route remains `debate_next` and no production files are to be modified until a decided execution slice is emitted.
change_request: if any required field remains undecided or missing, continue in `debate_next` and return to this packet for closure repair before enqueuing execution.

## next_execution_candidate

Decision status for the next code slice can become `decided` only for:

```text
problem: workers need a deterministic task-contract template so analysis
outputs can produce execution-ready packets without monitor rewriting every
field manually.

system_requirement: add a reusable decision packet/task-shaping template and
inject it into analysis-worker prompts.

data_contract: include decision_status, problem, system_requirement,
data_contract, state_flow, exception_flow, acceptance, out_of_scope,
allowed_execution, change_record, role_signoff.

state_flow: analysis output -> decision packet draft -> monitor review ->
decided execution task.

acceptance: template exists, prompt references it, focused tests prove decided
tasks route execution_next and undecided tasks stay blocked.

out_of_scope: no hard gate enforcement beyond routing signal; no mobile or
communication expansion.

allowed_execution: scripts/a9_supervisor.py, tests/test_supervisor.py,
docs/worker-method-packet.md, docs/agent-runtime-observations.md.
```

## recommended_next_route

Remain `debate_next` until the monitor accepts this packet. After acceptance,
enqueue the `next_execution_candidate` as a `decision_status: decided` task.
