# A9 Agent Runtime Observations

## 2026-06-02: auto-next recovered, then entered a local repair loop

Context:
- The 24h worker previously stalled when `pass` plus `next_slice` did not produce `next_task_path`.
- Several repair/test slices fixed real issues around `schedule_next_task`, runtime pre-gate false positives, and `monitor_blocked_repair_checks`.
- The auto loop recovered: queue -> running -> done -> next task was observed across multiple cycles.

Useful behavior observed:
- Worker found concrete causes from run evidence instead of only guessing.
- Worker added focused tests and usually repaired failing tests before final output.
- `next_slice` routing correctly moved failed focused tests into repair phases.
- Supervisor kept raw run evidence, summaries, process governance, patches, and commits.

Quality problems observed:
- Worker repeatedly ran undeclared checks. Current policy records this as warning, which is acceptable for observation-first governance, but it creates noisy repair prompts.
- Worker started expanding one local boundary (`monitor_blocked_repair_checks` test-runner promotion) into many small edge-case slices.
- A monitor-inserted correction task hung on a simple `ls -la` tool call and had to be terminated.
- After that termination, A9 returned to the queued auto-generated test instead of prioritizing the operator correction outcome.

Monitor decision:
- Do not keep expanding test-runner boundary cases unless they block the main runtime.
- Treat this as evidence that A9 needs an explicit operator correction / priority override lane.
- Next high-value direction should return to the main runtime line: reference-first session governance or multi-machine SSH/Tailscale/tmux/Redis communication governance.

Next recommended slice:
- `reference_scan`: inspect local Codex and Aider session/context mechanisms first, then compare with OpenHands/Continue event-stream adapters.
- Goal: design a small, testable operator correction lane so monitor interventions are durable and do not get buried behind auto-generated local repair loops.

## 2026-06-02: reference scan for operator priority correction lane

Reference paths inspected:
- `reference-projects/codex/codex-rs/core/src/goals.rs` (continuation candidate gating around queued input and mailbox triggers)
- `reference-projects/codex/codex-rs/core/templates/goals/objective_updated.md` (user objective supersedes previous objective)
- `reference-projects/openclaw/extensions/lobster/src/lobster-taskflow.ts` (revision-guarded waiting/resume flow mutation)

Smallest mechanism to copy:
- Copy Codex continuation gating rule: when any higher-priority input is queued, skip auto-continuation immediately.
- In Codex terms this is `has_queued_response_items_for_next_turn` / `has_trigger_turn_mailbox_items` -> do not continue goal turn.
- Adapt to A9 supervisor queueing: if an operator correction task exists (or is newly enqueued), auto-generated `next_slice` tasks must not be scheduled/selected until correction lane is drained or explicitly cleared.

Why this fits A9:
- It is a minimal deterministic rule, not a new planner/state machine.
- It directly solves the observed failure mode: valid human correction being buried by self-expanding auto-next slices.
- It composes with existing A9 managed-flow/revision work: queue ordering stays explicit and auditable, and can later add revision checks similar to Lobster flow mutations.

Exact next implement slice:
- `implement`: add deterministic operator priority lane behavior in `scripts/a9_supervisor.py` and `tests/test_supervisor.py` only.
- Required behavior for that slice:
  - Before auto-next scheduling/dispatch, check for pending operator correction lane items.
  - If present, suppress/defer auto-generated `next_slice` enqueue/dispatch in this cycle.
  - Emit explicit evidence/status field showing auto-next was skipped due to operator priority.
  - Add focused tests proving operator correction preempts auto-next and that auto-next resumes after correction lane is cleared.

## 2026-06-02: declared checks context-cost observation (interrupted worker reproduction)

Reference basis used (no re-scan):
- `reference-projects/codex/codex-rs/core/src/context_manager/history.rs`
- `reference-projects/codex/codex-rs/core/src/compact.rs`
- `reference-projects/codex/codex-rs/core/templates/goals/budget_limit.md`
- `reference-projects/aider/aider/history.py`
- `reference-projects/aider/aider/repomap.py`
- `reference-projects/aider/aider/prompts.py`

Observation:
- The interrupted worker reproduced the exact governance failure mode under repair: it executed undeclared `python3 -m unittest tests.test_supervisor`.
- This confirms the issue is process-governance drift, not missing test coverage.

Mechanism alignment to record:
- Codex keeps explicit budget state and enters budget-limited wrap-up instead of continuing substantive work when limits are hit.
- Codex/Aider build bounded context and summarization views rather than repeatedly replaying large raw history.
- A9 should treat declared checks as the executable test plan for the current slice; undeclared tests should be logged as governance observations or proposed in the next task, not executed immediately in the active run.

Bounded next slice:
- `implement`: enforce declared-check execution boundary in `scripts/a9_supervisor.py` with focused behavior tests in `tests/test_supervisor.py`.

## 2026-06-02: compare result for declared-check execution boundary

Bounded evidence reviewed:
- `scripts/a9_supervisor.py` (`monitor_blocked_repair_checks` + `schedule_next_task` call site)
- `tests/test_supervisor.py` (current monitor-blocked repair check promotion tests)

Compare result:
- Current `repair` auto-next path still promotes `process_governance.findings[kind=undeclared_check]` into runnable `checks` for the next task.
- This behavior conflicts with the scoped requirement that undeclared checks remain governance observations/proposals and are not executed inside the active run.

Why this matters:
- It keeps reproducing the same contract violation pattern: undeclared checks move from observation into execution without an explicit task-level declared-check contract update.
- It also increases context/test-cost noise in repair loops by expanding execution scope implicitly.

Bounded implement next slice:
- `implement` (only `scripts/a9_supervisor.py` and `tests/test_supervisor.py`):
  - Stop promoting undeclared checks into active run `checks` in monitor-blocked repair scheduling.
  - Keep undeclared checks as findings/proposals in process governance evidence.
  - Update focused supervisor tests to assert observation-only behavior and prevent regression.

## 2026-06-02: next-slice test suggestion and declared checks are still unsynchronized

Bounded evidence reviewed:
- `scripts/a9_supervisor.py::next_task_prompt`
- `scripts/a9_supervisor.py::checks_for_next_phase`
- `scripts/a9_supervisor.py::schedule_next_task`

Observation:
- Supervisor task execution boundary is `checks_for_next_phase(...)` (task-declared checks, with reference-scan override).
- `next_task_prompt(...)` still injects prior `output.next_slice` text directly into the next worker prompt as informational context.
- When `next_slice` contains a concrete test command, worker behavior can drift into executing that command ad hoc even if it is not present in task `checks`.

Why this matters:
- This recreates the same contract break in a new path: suggestion text can act like execution intent without task-level declared-check synchronization.

Bounded implement next slice:
- `implement` (only `scripts/a9_supervisor.py` and `tests/test_supervisor.py`):
  - On next-task generation, if `next_slice` includes a concrete test command, either:
  - add it explicitly into generated task `checks`; or
  - rewrite prompt wording to mark it as proposal-only and explicitly non-executable unless declared in `checks`.
  - Add focused tests to lock the chosen behavior and prevent undeclared test execution drift.

## 2026-06-02: communication worker produced useful patch but failed full declared check

Run evidence:
- `.a9/runs/000-implement-node-result-replay-contract-20260602-20260601T200026Z-a1`

Observation:
- Worker stayed on the communication mainline and copied the right mechanism:
  `/api/events` cursor replay plus Codex reconnect cursor carry-over and
  Barter-style typed recovery actions.
- Patch and scope guard passed, but the run ended `needs-repair` because
  `python3 -m unittest tests.test_control_api.ControlApiTests` failed.
- Worker ran several undeclared checks first (`pytest`, `python3 -m pytest`,
  wrong `TestControlAPI` class path, and a malformed `rg` check). Process
  governance logged them as warnings, but the real rollback cause was the
  failing declared full test.
- The implementation was mostly correct. The missing point was compatibility:
  an existing test wrapper around `node_command_result_by_command_lookup` did
  not accept the new `result_last_id` keyword, causing the handler path to
  return 500.
- The worker also emitted empty/noop web search events again. This is noise,
  not useful reference_scan evidence.

Monitor intervention:
- Reapplied the worker patch from `patch.diff`.
- Fixed the compatibility wrapper.
- Ran declared checks:
  `python3 -m py_compile scripts/a9_control_api.py` and
  `python3 -m unittest tests.test_control_api.ControlApiTests` (206 tests).
- Committed the accepted patch as
  `846b6f2 a9 control: add node result replay cursor contract`.

Governance lesson:
- Worker quality was acceptable on direction and mechanism extraction, but
  still weak on execution discipline.
- For implement tasks, full declared checks must run before final envelope.
  Targeted checks are useful as local debugging, but cannot substitute for the
  task contract.
- Empty/noop web actions should be blocked or downgraded into a visible
  process-governance finding.
