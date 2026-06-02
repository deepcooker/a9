# A9 Agent Runtime Observations

## 2026-06-02: deterministic restart subcommand added for targeted local service refresh

- `scripts/a9_service.py` now supports `restart` with `--only` and `--dry-run`.
- `restart --only <services>` now executes stop then start for each requested service set using existing start/stop governance rules and payload shape.
- `restart` is conservative by default: `--all` is explicit; without flags it restarts `control-api`, `node-worker`, and `recovery-loop` (never supervisor by default).
- `--dry-run` for restart never signals processes and never mutates pidfiles; it returns a single JSON envelope that includes `kind: service_restart`, `stop`, `start`, `requested`, `dry_run`, and `status`.
- Live verification: `python3 scripts/a9_service.py restart --only recovery-loop`
  stopped old recovery-loop pid `1583`, started pid `33642`, refreshed
  `.a9/services/recovery-loop.pid`, and `/api/nodes/recovery-loop/latest`
  still reported `communication_execute_enabled=false` with
  `communication_route_execution.reason=observe_only`.

## 2026-06-02: service stop gains granular `--only` target mode with observed-PID cleanup

- `scripts/a9_service.py stop --only` now supports `control-api`, `node-worker`,
  `recovery-loop`, and `supervisor`; default behavior remains supervisor-only when neither
  `--all` nor `--only` is set.
- Stop path now signals observed processes directly and updates/removes service pidfiles only for
  targeted service kinds; dry-run stays non-mutating for both process signals and pidfiles.
- CLI output now carries explicit stop envelope fields (`target_mode`, `requested`,
  `matched`, `pidfiles_removed`) to make recovery telemetry deterministic.

## 2026-06-02: recovery-loop exposes execute mode in monitor payload

- Recovery-loop monitor now distinguishes observe-only and execute-enabled recovery runs via
  `communication_execute_enabled` and `communication_route_execution` in
  `/api/nodes/recovery-loop/latest`.
- This stays visibility-only: recovery-loop remains default observe-only and service startup is unchanged.

## 2026-06-02: auto-next recovered, then entered a local repair loop

- Observed: `.a9/services/recovery-loop.pid` and `.a9/services/control-api.pid` became stale because `a9_service.py start` returned the launcher `setsid` pid while the actual service pid remained different.
- Patch applied: `scripts/a9_service.py` now writes/refreshes service pidfiles to the observed real process pid from `running_processes()` and uses deterministic primary selection when multiple matches exist.
- Effect: restart/hot-reload can now target real service processes using pidfile content instead of launcher shells.
- Live verification: `python3 scripts/a9_service.py start --only control-api recovery-loop node-worker`
  refreshed pidfiles without restart; pidfiles matched observed real pids for
  all three services.

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

## 2026-06-02: async service-control mutation audit added to mobile/control API

Mechanism copied:
- `append_communication_suggestion_audit` / `enqueue_communication_suggestion_audit` in `scripts/a9_control_api.py` (threaded JSONL append + non-blocking enqueue pattern, compact JSON separators).
- `build_remote_post_audit_receipt` / `guarded_remote_post` shape and fields (`command`, `request/return status`, `gate` metadata) for consistent durable audit envelopes.

Implementation:
- Added `.a9/services/service-control-audit.jsonl` as durable async sink (`SERVICE_CONTROL_AUDIT_REL_PATH`).
- Added `build_service_control_audit_event`, `append_service_control_audit`, and `enqueue_service_control_audit`.
- Wired `service_start_action` and `service_restart_action` to enqueue audit events on `blocked`, `invalid_request`, `degraded`, `failed`, and `ok` outcomes.
- Added `audit_async` marker in returned payloads where async append is enqueued.
- Audit event includes timestamp, action, command, status, reason for blocked/invalid outcomes, target/requested services where present, gate allowed/reason, return_code where available, operator scope presence/count, and available service-observation summary.

Checks run:
- `python3 -m py_compile scripts/a9_control_api.py tests/test_control_api.py`
- `python3 -m unittest tests.test_control_api.ControlApiTests.test_service_start_action_audits_blocked_gate`
- `python3 -m unittest tests.test_control_api.ControlApiTests.test_service_restart_action_audits_invalid_request`
- `python3 -m unittest tests.test_control_api.ControlApiTests.test_service_restart_action_audits_ok_result`
- `python3 -m unittest tests.test_control_api.ControlApiTests.test_append_service_control_audit_writes_jsonl`

Monitor verification:
- Reran the declared focused checks and full
  `python3 -m unittest tests.test_control_api.ControlApiTests`; 229 tests passed.
- Confirmed API responses do not include full `audit_event`; only `audit_async`
  is returned for audited branches.
- Live reloaded `control-api` with `python3 scripts/a9_service.py restart --only
  control-api`; new pid was observed as `80591`.
- Live POST to `/api/services/restart` without phone-control arm returned
  `status=blocked`, `blocked_reason=phone_control_disarmed`, and
  `audit_async=true`.
- `.a9/services/service-control-audit.jsonl` was created and appended one compact
  JSONL event with `action=restart`, `status=blocked`, gate metadata,
  service-observation summary, and operator scope count only.

Worker quality note:
- Direction and mechanism copy were correct. Token cost was high because the
  worker read broad file slices; next worker prompts should ask for narrower
  `rg`/`sed` slices after initial reference anchors are found.

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

## 2026-06-02: watch endpoint worker produced useful design but no applicable patch

Run evidence:
- `.a9/runs/000-implement-node-command-result-watch-20260602-20260601T201318Z-a1`

Observation:
- Worker stayed on the communication mainline and selected the right mechanism:
  cursor-aware bounded `node-command-results/watch`.
- It again emitted an empty/noop web action and ran an undeclared targeted
  unittest.
- Declared supervisor checks passed because no patch was applied to the
  worktree, but the run still ended `needs-repair`: patch apply and patch guard
  both skipped with `no SEARCH/REPLACE patch in final message` /
  `no recorded worker diff`.
- The final response put a strict JSON envelope first, then SEARCH/REPLACE
  blocks after it. The deterministic apply parser did not recognize those
  blocks as the worker patch.

Monitor intervention:
- Manually applied the worker's useful design into:
  `scripts/a9_control_api.py`, `tests/test_control_api.py`,
  `docs/communication-governance-framework.md`.
- Ran declared checks:
  `python3 -m py_compile scripts/a9_control_api.py` and
  `python3 -m unittest tests.test_control_api.ControlApiTests` (211 tests).
- Committed the accepted patch as
  `27572fc a9 control: add node command result watch endpoint`.

Governance lesson:
- A9 needs a stricter worker-output contract: either final envelope must carry
  an explicit machine-readable patch field, or SEARCH/REPLACE blocks must be
  emitted in the exact parser-recognized location.
- Process governance should hard-block or repair empty/noop web actions and
  undeclared checks, because repeated prompt-only warnings did not change the
  behavior.

## 2026-06-02: event-level worker discipline observation

Run evidence:
- `.a9/runs/000-implement-worker-event-discipline-observation-20260602-20260601T202957Z-a1`

Observation:
- Worker correctly identified the gap: `process_governance` inspected
  `command_execution` summaries but did not explicitly observe `web_search`
  or `file_change` event summaries.
- It implemented useful warn-only event findings for empty/noop web search and
  direct `file_change` under deterministic SEARCH/REPLACE tasks.
- The run ended `needs-repair` because the worker invented different focused
  unittest names from the task's declared checks. Patch and scope guards were
  pass, but git governance rolled the worktree back.
- The worker again used direct Codex `file_change` events, confirming this is
  a default execution-path behavior that prompt wording alone does not stop.

Monitor intervention:
- Reverted an accidental selftest snapshot commit created during an operator
  enqueue quoting mistake:
  `3731f42 Revert "a9 worker: selftest-auto-next-gateway-hint-filtering attempt snapshot"`.
- Manually accepted the useful patch with declared test names:
  `test_process_governance_observes_empty_web_search_event` and
  `test_process_governance_observes_direct_file_change_event_without_blocking`.
- Ran:
  `python3 -m py_compile scripts/a9_supervisor.py`,
  `python3 -m unittest tests.test_supervisor.SupervisorTests.test_process_governance_observes_empty_web_search_event tests.test_supervisor.SupervisorTests.test_process_governance_observes_direct_file_change_event_without_blocking`,
  and related process-governance regressions.

Governance lesson:
- Event-level discipline must be first-class evidence, not inferred from final
  status or command logs.
- Warn-only observation is the correct current default: it improves monitor
  visibility without turning prompt drift into a hard business blocker.
- Declared checks remain the contract. Worker-renamed tests can be useful
  debugging evidence, but cannot satisfy the task.

## 2026-06-02: default worker model availability changed

Run evidence:
- `.a9/runs/000-reference-scan-multinode-connection-stability-next-slice-20260602-20260602T051731Z-a1`

Observation:
- The queued multinode reference scan did not reach model reasoning.
- Codex returned HTTP 400:
  `The 'gpt-5.3-codex' model is not supported when using Codex with a ChatGPT account.`
- A direct smoke with `gpt-5.3-codex-spark` succeeded and produced a valid
  strict JSON envelope.

Monitor intervention:
- Changed `scripts/a9_supervisor.py::DEFAULT_WORKER_MODEL` to
  `gpt-5.3-codex-spark`.
- Updated the default-model policy attestation test expectation.

Governance lesson:
- Model availability is runtime state, not a stable architecture fact.
- The 24h loop must record `worker_model` and `worker_model_source` on every
  run, and startup failures from unsupported models should trigger model
  fallback or operator-visible repair rather than silent queue churn.

## 2026-06-02: executable stale Redis Stream recovery worker pass needed monitor hardening

Run evidence:
- `.a9/runs/000-reference-scan-multinode-connection-stability-next-slice-retry-20260602-20260602T052457Z-a1`
- `.a9/runs/000-implement-executable-stale-stream-recovery-action-20260602-20260602T053040Z-a1`

Observation:
- The reference scan picked the right next communication-runtime slice:
  convert `pending_stuck` Redis Stream diagnosis into an executable
  `recover_stale_commands` control action using the existing
  `scripts/a9_node.py::node_command_claim_stale_once` XAUTOCLAIM helper.
- The implementation worker completed and committed useful code/tests, but
  process governance still recorded repeated direct `file_change` events under
  a deterministic SEARCH/REPLACE task. This remains a worker behavior issue,
  but warn-only observation is acceptable while the product lane is still
  wiring core runtime capability.
- Token cost was too high for this slice. The reference scan used about
  1.39M input tokens, and the implementation run used about 5.74M input
  tokens. The main cause is broad local reading and repeated failed patch
  attempts, not business complexity.
- The worker marked the route as requiring remote arm, but did not register
  `nodes.recover.stale_commands` in the remote command group and did not
  enforce the command gate inside the action. The monitor had to harden this
  because it is an execution/safety fact, not an optimization gate.

Monitor intervention:
- Added `nodes.recover.stale_commands` to the remote phone-control command
  group.
- Added a `command_gate("nodes.recover.stale_commands")` check inside
  `recover_stale_commands`.
- Updated the test to arm the remote group before executing stale-command
  recovery.
- Ran:
  `python3 -m py_compile scripts/a9_control_api.py scripts/a9_node.py tests/test_control_api.py tests/test_node.py`,
  targeted recovery tests, and full
  `python3 -m unittest tests.test_control_api.ControlApiTests`.

Governance lesson:
- The worker is now good enough to execute communication-runtime slices under
  monitoring, but monitor review must still check route/command/gate
  consistency.
- Cost control should be architectural and observational first: smaller
  source windows, fewer repeated patch attempts, and better task packets.
  Do not solve this by arbitrary token/line gates that block useful work.
- Direct `file_change` events should remain visible to the monitor until the
  deterministic apply path is fully reliable.

## 2026-06-02: connection summary stream recovery patch was useful but envelope failed

Run evidence:
- `.a9/runs/000-reference-scan-communication-stability-after-stale-recovery-20260602-20260602T054134Z-a1`
- `.a9/runs/000-implement-connection-summary-stream-recovery-next-action-20260602-20260602T054303Z-a1`

Observation:
- The bounded reference scan behaved much better than the previous broad scan:
  about 51k input tokens and no process-governance findings.
- The implementation worker produced a useful patch and passed the declared
  checks, but its final strict JSON envelope contained an unescaped newline in
  a string. `worker_envelope` failed, so git governance rolled the worktree
  back even though `patch_guard` and `scope_guard` passed.
- The saved run patch was still usable:
  `.a9/runs/000-implement-connection-summary-stream-recovery-next-action-20260602-20260602T054303Z-a1/patch.diff`.

Monitor intervention:
- Re-applied the saved patch manually to main.
- Ran:
  `python3 -m py_compile scripts/a9_control_api.py tests/test_control_api.py`,
  the two declared focused tests, and full
  `python3 -m unittest tests.test_control_api.ControlApiTests`.

Governance lesson:
- Strict envelope JSON validity is still a real automation blocker.
- When `patch_guard=pass` but envelope parsing fails, monitor can accept the
  saved `patch.diff` after tests pass; the event should be recorded as protocol
  failure, not code-quality failure.

## 2026-06-02: communication status consumed stream recovery action after monitor acceptance

Run evidence:
- `.a9/runs/000-implement-communication-status-consumes-stream-recovery-next-action-20260602-20260602T055246Z-a1`

Observation:
- The worker correctly identified the next link: `communication_status` was
  still reading raw Redis Stream `stream_action`, while
  `node_connection_summary` now exposes normalized `recovery_next_action`.
- The patch connected `recovery_next_action` into the `tasks_stream` candidate
  and routed `tasks_stream:recover_stale_commands` to
  `/api/communication/repair-one` with `nodes.recover.stale_commands`.
- Declared tests passed in the worker run, but the strict envelope failed again.
  The final output was not parseable as the required worker envelope, so git
  governance rolled the task back.

Monitor intervention:
- Applied the saved run patch:
  `.a9/runs/000-implement-communication-status-consumes-stream-recovery-next-action-20260602-20260602T055246Z-a1/patch.diff`.
- Ran the declared checks and full
  `python3 -m unittest tests.test_control_api.ControlApiTests`.

Governance lesson:
- The 24h worker can now produce useful communication-runtime patches, but
  strict-envelope reliability is the current automation bottleneck.
- The monitor can safely accept saved patches only when `patch_guard=pass`,
  `scope_guard=pass`, and focused plus broader regression tests pass.

## 2026-06-02: supervisor can salvage valid patches after strict envelope parse failure

Observation:
- Two consecutive useful communication-runtime patches were rolled back because
  the worker final message was not parseable as the strict JSON envelope.
- In both cases, `patch_guard=pass`, `scope_guard=pass`, process governance had
  no error findings, and the declared tests passed.

Change:
- `scripts/a9_supervisor.py::reconcile_worker_envelope_check_conflict` now has
  a narrow salvage path for `no worker envelope JSON object found`.
- It only reconciles to pass when supervisor checks pass, patch guard passes,
  scope guard passes, and process governance does not fail.
- Scope failures, patch failures, missing checks, or failing checks still block.

Governance lesson:
- This is not removing the strict envelope rule. It converts a known protocol
  failure into a recorded reconciliation when deterministic evidence proves the
  code patch is acceptable.

## 2026-06-02: worker auto-committed recovery-loop priority tie-break

Run evidence:
- `.a9/runs/000-implement-communication-status-recovery-loop-priority-20260602-20260602T060229Z-a1`

Observation:
- The 24h worker produced a valid strict envelope and supervisor committed the
  patch automatically.
- It added a deterministic tie-break so `recovery_loop` with serious action
  wins over `tasks_stream` when both are priority 4.
- Direct `file_change` events still appeared as warn-only process-governance
  findings, but patch/scope/checks all passed.

Verification:
- Worker declared checks passed.
- Monitor reran full `python3 -m unittest tests.test_control_api.ControlApiTests`
  and 218 tests passed.

Governance lesson:
- The 24h loop can now complete useful communication-runtime tasks end to end
  without manual patch acceptance when the envelope is valid.
- The remaining automation quality issue is worker event discipline, not this
  specific routing capability.

## 2026-06-02: communication repair-one stream recovery e2e fixture passed

Run evidence:
- `.a9/runs/000-implement-communication-repair-one-stream-recovery-e2e-20260602-20260602T062014Z-a1`

Observation:
- The worker added an end-to-end fixture test for
  `communication_repair_one -> recover_stale_commands -> evidence_path ->
  communication_after`.
- It initially hit a fixture bug in `service_observation_status` monkeypatch
  signature, fixed it, reran the declared checks, and then supervisor committed
  automatically.
- The worker still emitted direct `file_change` events, recorded as warn-only.

Verification:
- Worker declared checks passed.
- Monitor reran full `python3 -m unittest tests.test_control_api.ControlApiTests`
  and 219 tests passed.

Governance lesson:
- The Redis Stream recovery path is now covered from status/action-plan through
  repair execution and evidence creation in a deterministic fixture.
- Next communication-runtime work can move from unit-route wiring toward
  runtime command/recovery loop consumption or real Redis/tmux smoke.

## 2026-06-02: monitor corrected recovery-loop route payload contract

Run evidence:
- `.a9/runs/000-implement-recovery-loop-communication-route-dispatch-20260602-20260602T070505Z-a1`

Observation:
- The worker correctly added explicit `--execute-communication-repair` support
  and route dispatch for `/api/communication/repair-one`.
- It passed its tests, but the new fixtures placed `payload` inside `route`.
  The real `communication_action_plan` contract keeps `payload` at the top
  level and `route` only carries method/endpoint/command/arm metadata.

Monitor intervention:
- `execute_communication_route` now reads the POST payload from
  `communication_plan.payload`.
- Tests were corrected to mirror the real action-plan shape.

Verification:
- `python3 -m py_compile scripts/a9_recovery_loop.py tests/test_recovery_loop.py`
- `python3 -m unittest tests.test_recovery_loop.RecoveryLoopTests`

Governance lesson:
- Passing tests are not enough when fixtures drift from the real data model.
  Monitor review must compare worker fixtures against the source contract,
  especially for communication/runtime execution paths.

## 2026-06-02: recovery-loop execution visibility exposed through control API

Run evidence:
- `.a9/runs/000-expose-recovery-loop-communication-execution-status-20260602-20260602T070844Z-a1`

Observation:
- The worker exposed `communication_execute_enabled` and
  `communication_route_execution` from `.a9/services/recovery-loop-latest.json`
  through `recovery_loop_latest()`.
- It did not change service defaults. Recovery loop remains observe-only unless
  an explicit execution flag is used.

Verification:
- Worker declared checks passed.
- Monitor reran full `python3 -m unittest tests.test_control_api.ControlApiTests`
  and 219 tests passed.

Governance lesson:
- Communication monitoring must show both intent and execution mode. Operators
  need to know whether recovery loop only observed a route or actually posted a
  repair action.

## 2026-06-02: mobile control API now exposes gated service restart

- Added runtime phone-control command `services.restart` and POST route
  `/api/services/restart`.
- Implemented `service_restart_action(payload, root=ROOT)` with admin + gate checks,
  explicit `services` list requirement, unknown-service rejection, and
  `allow_supervisor`-guarded supervisor restart behavior.
- Restart path executes `python3 scripts/a9_service.py restart --only <services>` with
  timeout 8s, parses `restart_result`, and returns service observations before and
  after restart.

Verification:
- Worker declared checks passed.
- Monitor added a regression test proving `allow_supervisor: true` is required
  for supervisor restart to pass through the helper path.
- Monitor reran `python3 -m py_compile scripts/a9_control_api.py
  tests/test_control_api.py`, six focused restart route tests, and full
  `python3 -m unittest tests.test_control_api.ControlApiTests`; 225 tests passed.
- Live reloaded `control-api` with `python3 scripts/a9_service.py restart --only
  control-api`; new pid was observed as `59265`.
- Live `/api/discovery` exposed `services_restart: /api/services/restart`.
- Live POST to `/api/services/restart` without phone-control arm returned
  `status=blocked` and `blocked_reason=phone_control_disarmed`; all four services
  remained observed running.

## 2026-06-02: service-control audit tail endpoint exposed to mobile/control

Run evidence:
- Local implementation and tests for bounded JSONL readback from
  `.a9/services/service-control-audit.jsonl`.

Reference mechanism copied:
- JSONL async audit append pattern from `append_service_control_audit` /
  `enqueue_service_control_audit`.
- Bounded payload dispatch style from `controller_discovery` and GET route patterns
  in `ControlHandler`.

Implementation:
- Added `service_control_audit_tail(limit=20, root=ROOT)` in
  `scripts/a9_control_api.py`.
- Added GET route `/api/services/control-audit` with optional `limit`.
- Route uses safe limit clamp `1..100` and returns bounded newest events in
  chronological order.
- Added missing-file contract: `status=missing`, `kind=service_control_audit_tail`,
  `path`, `events=[]`, `event_count=0`, `skipped_bad_lines=0`.
- Malformed JSONL lines are skipped; `skipped_bad_lines` is returned and status is
  `degraded` when any bad line exists.
- Added discovery contract key:
  `services_control_audit: /api/services/control-audit`.

Checks:
- `python3 -m py_compile scripts/a9_control_api.py tests/test_control_api.py`
- `python3 -m unittest tests.test_control_api.ControlApiTests.test_service_control_audit_tail_missing_file`
- `python3 -m unittest tests.test_control_api.ControlApiTests.test_service_control_audit_tail_bounds_newest_events`
- `python3 -m unittest tests.test_control_api.ControlApiTests.test_service_control_audit_tail_skips_bad_jsonl`
- `python3 -m unittest tests.test_control_api.ControlApiTests.test_api_services_control_audit_route_passes_limit`
- `python3 -m unittest tests.test_control_api.ControlApiTests.test_controller_discovery_exposes_registration_contract`

Monitor verification:
- Reran the declared focused checks and full
  `python3 -m unittest tests.test_control_api.ControlApiTests`; 233 tests passed.
- Live reloaded `control-api` with `python3 scripts/a9_service.py restart --only
  control-api`; new pid was observed as `3787`.
- Live GET `/api/services/control-audit?limit=1` returned the latest blocked
  `services.restart` audit event with `reason=phone_control_disarmed`.
- Live `/api/discovery` exposed
  `services_control_audit: /api/services/control-audit`.

Worker quality note:
- Direction and implementation were acceptable, but the worker again read broad
  file ranges during reference scan. Future prompts should require exact `rg`
  anchors before any `sed` range larger than roughly 120 lines.

## 2026-06-02: broad local sed slice observation added to process governance

Reference paths:
- `scripts/a9_supervisor.py` (`sed_window_policy`, `sed_window_governance`)
- `tests/test_supervisor.py` (`test_process_governance_observes_broad_file_slice`,
  `test_process_governance_ignores_narrow_file_slice`)

Mechanism copied:
- Borrowed the existing `sed_window_governance` pattern from current process
  governance code and added a dedicated warn-only `broad_file_slice_observation`
  finding when `sed -n A,Bp` spans more than `BROAD_FILE_SLICE_WARN_LINES` lines.
- Recommendation payload is now recorded with each observation to force a low-cost,
  context-stable reading pattern:
  `use rg anchors plus narrower sed slices`.

Implementation:
- Added `BROAD_FILE_SLICE_WARN_LINES = 240` constant and
  `broad_file_slice_observation` emit path in `scripts/a9_supervisor.py`.
- Added focused tests:
  - `test_process_governance_observes_broad_file_slice` asserts the new warn finding,
    including `line_count`, `read_span`, and recommendation.
  - `test_process_governance_ignores_narrow_file_slice` asserts narrow windows are
    not flagged.

Checks:
- `python3 -m py_compile scripts/a9_supervisor.py tests/test_supervisor.py`
- `python3 -m unittest tests.test_supervisor.SupervisorTests.test_process_governance_observes_broad_file_slice`
- `python3 -m unittest tests.test_supervisor.SupervisorTests.test_process_governance_ignores_narrow_file_slice`

Monitor verification:
- Reran the declared focused checks; they passed.
- Reran adjacent sed-window regressions:
  `test_process_governance_observes_batched_sed_reads_with_rationale`,
  `test_process_governance_warns_on_batched_sed_read_without_rationale`, and
  `test_process_governance_enforces_task_command_bounds`; they passed.
- Full `python3 -m unittest tests.test_supervisor.SupervisorTests` did not pass.
  Failures were concentrated in historical auto-next selftests where
  `next_task_path` resolved to `.` or expected `pass` became `needs-repair`.
  The inspected failed run summaries had `process_governance.status=pass` and
  no process-governance findings, so the new warn-only broad-slice observation
  was not the direct blocker.
- No task queue/running residue remained after the failed full suite; git
  worktree stayed clean before this documentation update.

Governance lesson:
- Warn-only observations are preserved and non-blocking.
- This keeps business continuity while adding a concrete signal for costly broad
  local file reads.

## 2026-06-02: requirements-method packet added before more execution work

Observation:
- The 24h worker can execute bounded slices, but quality is capped if a task is
  sent before requirements are aligned.
- The real enterprise process is discussion, synchronization, role review, data
  modeling, state-flow agreement, and acceptance confirmation before execution.
  That front-loaded work can dominate total quality and reduce rework by an
  order of magnitude.
- A9 must distinguish `debate_next` from `execution_next`. Before decision,
  next steps are research, modeling, review, contradiction, and decision record.
  After decision, next steps become 24h worker execution backlog.

Change:
- `AGENTS.md` now defines the top-level phase rule:
  `discussion / research / modeling / review / decision / execution`.
- Added `docs/worker-method-packet.md` as the shared method packet for analysis
  worker and execution worker.
- `docs/README.md` now lists the method packet under Core.

Governance lesson:
- The 24h worker should not be treated as a product manager by accident.
- Analysis worker may automate close-reading, reference scan, reverse modeling,
  open questions, and review packets. Execution worker may only implement
  decided slices.
- Product/mainline remains the pressure role: market/reference research,
  scenario pressure, solution overturning, and final product decision.
