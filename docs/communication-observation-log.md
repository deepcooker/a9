# A9 Communication Observation Log

## 2026-05-27: Gateway Reconnect Transcript Monitoring

Scope:

- Communication line only.
- Observe worker quality, intervene when it drifts, and record issues before
  continuing broader communication work.
- Keep one worker active at a time until parallel session governance is explicit.

Rounds observed:

1. `auto-reference_scan-auto-test-auto-implement-typed-reconn-cb279a008f-20260526T154804Z`
   - Status: `pass`
   - Run: `.a9/runs/auto-reference_scan-auto-test-auto-implement-typed-reconn-cb279a008f-20260526T154804Z-20260526T162850Z-a1`
   - Good: selected Barter-rs `OnConnectErr` / `OnStreamErr` / `OnStreamErrFilter`
     as the next mechanism and made no file changes.
   - Problem: auto-next scheduled `mechanism_extract` even though worker
     `next_slice` clearly asked for a test hardening slice.
   - Intervention: changed queued phase to `test` and narrowed checks to
     `cargo test -p a9-gateway`.

2. `auto-test-gateway-reconnect-decision-socket-transcript-20260526T163120Z`
   - Status: `pass`
   - Run: `.a9/runs/auto-test-gateway-reconnect-decision-socket-transcript-20260526T163120Z-20260526T163232Z-a1`
   - Good: added a fake Redis socket transcript test asserting
     `XADD gateway_reconnect_decision` ordering for retryable failure:
     `connect/reconnect`, `stream/continue`, then retry-scheduled
     `connect/reconnect`.
   - Commit merged to main: `6b05ac1`
   - Test count moved to `15`.

3. `auto-test-gateway-terminal-transcript-ordering-20260526T163605Z`
   - Status: `pass`
   - Run: `.a9/runs/auto-test-gateway-terminal-transcript-ordering-20260526T163605Z-20260526T164031Z-a1`
   - Good: added terminal failure transcript coverage asserting
     `connect/terminate` and `stream/reconnect`.
   - Commit merged to main: `5027a7b`
   - Test count moved to `16`.
   - Problem repeated: auto-next scheduled `reference_scan` while worker
     `next_slice` asked for terminal stop-path test hardening.
   - Intervention: changed queued task to focused test
     `auto-test-gateway-terminal-stop-path-no-retry-20260526T164308Z`.

Observed issues:

1. Reference-scan noise can explode.
   - Manual broad `rg` across full OpenClaw/Codex references produced too much
     output.
   - Rule: future reference scans must name the exact reference slice first.

2. Auto-next phase routing is too mechanical.
   - It follows fixed pipeline phase order after deterministic record.
   - Worker `next_slice` can be more precise than the phase table.
   - Need: scheduler should detect `next_slice` prefixes like `test:` /
     `implement:` / `repair:` and route accordingly, with policy bounds.

3. Deterministic record is working but confusing.
   - Supervisor writes deterministic records and then queues the next phase.
   - Worker final messages sometimes still say `record:` as next step.
   - Need: prompt should tell workers that `record` is supervisor-owned after
     pass, unless docs explicitly need manual edits.

4. Parallel session governance is not ready.
   - Codex can support multiple threads/subagents, but A9's current Python queue
     should still be treated as single-active-worker unless each flow has
     `flow_id`, `expected_revision`, and isolated write scope.
   - Do not run multiple `run-one` workers against the same queue until Redis
     flow lease/revision is mandatory for normal copy-pipeline tasks.

5. Token usage remains high.
   - Latest real worker runs still consume large cached input and meaningful
     uncached input.
   - Need: stricter phase prompts and smaller reference snippets before any
     24-hour unattended run.

6. Deep-mark Redis persistence can delay completion.
   - `auto-test-auto-implement-supervisor-flow-sequen-0be8c09108-20260526T173025Z`
     finished worker/check/git quickly, then spent extra time writing many
     `deep_mark` records through per-record `docker exec ... redis-cli JSON.SET`.
   - It eventually completed, but this is a runtime hot-path smell.
   - Need: batch Redis writes or move deep-mark persistence out of the blocking
     `run-one` finish path before unattended multi-hour loops.

7. Auto-next phase routing repeated on supervisor sequence tests.
   - Worker `next_slice` asked for `test: add negative auto-next coverage...`.
   - Supervisor queued `reference_scan`.
   - Intervention: changed the queued task back to `phase: test` and narrowed
     checks to `python3 -m unittest tests/test_supervisor.py tests/test_middleware.py`.

8. Raw-session tail reads can still trip worker budget.
   - The corrected negative-test task still began by reading
     `docs/session-raw-summary.md` and `docs/session-raw-close-reading.md`.
   - It exceeded the worker event byte budget before producing a final envelope:
     `retryable-worker-budget`, `event_bytes=131092`.
   - Intervention: requeued a hard-bounded repair task that explicitly forbids
     raw session docs, service status probing, and reference scans for this slice.

9. Spark completed the patch but failed strict envelope.
   - Hard-bounded `gpt-5.3-codex-spark` repair avoided raw-doc explosion and
     added the right negative test.
   - It wrote `status: "pass"` instead of the allowed `ok`, so worker envelope
     validation failed and git governance rolled the diff back.
   - The declared supervisor/middleware checks still passed with `72` tests.
   - Intervention: monitor manually applied the verified minimal patch and
     recorded that Spark is useful for small edits but unreliable for strict
     envelope protocol unless the supervisor can auto-normalize or repair it.

10. Reference projects are not visible inside worker worktrees by default.
   - `implement-worker-envelope-normalization-20260526T175650Z` was told to read
     `reference-projects/openhands/frontend/src/types/v1/type-guards.ts`.
   - The worker worktree did not contain that path, so the read failed.
   - The implementation still succeeded from the selected mechanism, but this
     weakens the "copy first" loop.
   - Need: supervisor should hydrate selected reference slices into worker
     worktrees, or pass absolute read-only reference paths that are available
     outside the git worktree.

11. Envelope normalization fixed one real rollback class.
   - Worker commit `c7a0400` normalizes safe aliases `pass/success -> ok` only
     when `ok=true`, records an info finding, and leaves invalid statuses failing.
   - This directly addresses the Spark `status: "pass"` rollback without making
     the envelope guard loose.

12. Broad approval/wait/resume test target tripped worker budget.
   - `auto-test-implement-worker-envelope-normalizati-49e6db0b8c-20260526T181508Z`
     attempted to inspect large portions of `tests/test_supervisor.py` and
     `tests/test_middleware.py`.
   - It exceeded the worker event byte budget before final output:
     `retryable-worker-budget`, no patch, no final envelope.
   - Intervention: do not retry this broad test target as-is. Split into exact
     harness-sized tasks, or first fix the scheduler/prompt to turn `next_slice`
     into narrowly scoped work.

13. Even a narrowed test task can blow the event budget when the worker uses
    wide file reads.
   - `auto-test-implement-next-slice-phase-routing-20-9a2b4b7e9f-20260526T182928Z`
     was manually narrowed to `python3 -m unittest tests/test_supervisor.py` and
     only the `needs-followup` `next_slice` routing regression.
   - The worker still read multiple broad `sed` ranges from
     `tests/test_supervisor.py` and `scripts/a9_supervisor.py`.
   - It exceeded the worker event byte budget before final output:
     `retryable-worker-budget`, `event_bytes=124875`, no diff and no envelope.
   - Intervention: monitor added the missing minimal regression test directly.
     The targeted three-test slice passed.

14. Barter reference hydration patch was valid, but invalid envelope caused a
    rollback.
   - `hydrate-barter-reference-slices-20260526T184000Z` correctly extended
     worker reference hydration to include bounded Barter-rs communication
     slices.
   - Guard and scope passed, but the worker wrote `protocolVersion: "1.0"` and
     `status: "completed"`.
   - Supervisor rolled back the patch; monitor reviewed and manually applied
     the tested diff.

15. Node connection action patch was valid, but protocolVersion drift caused a
    second rollback.
   - `implement-node-connection-action-20260526T185100Z` copied Barter-rs typed
     action boundaries into `connection_state -> connection_action`.
   - `python3 -m unittest tests/test_control_api.py` passed with 37 tests.
   - Worker still used invalid `protocolVersion:
     "a9.strict_worker_envelope.v1"`, so git governance rolled back.
   - Intervention: monitor manually applied the patch and kept the generated
     repair task out of the queue.

16. ProtocolVersion normalization repaired the repeated rollback class.
   - `implement-envelope-protocol-normalization-20260526T185800Z` added a
     bounded protocolVersion alias normalizer near the status alias normalizer.
   - Accepted aliases are intentionally narrow and recorded as info findings:
     numeric `1`, string `1`, string `1.0`, and
     `a9.strict_worker_envelope.v1`.
   - Follow-up test workers added no-error and dual-alias regressions.
   - Targeted strict-envelope tests passed locally; the auto-generated pytest
     follow-up was superseded because pytest is not installed in this runtime.

17. Prompt discipline improved, but workers still use broad file windows and
    envelope aliases outside the current whitelist.
   - `implement-node-heartbeat-action-hotpath-20260526T192600Z` followed the new
     no-raw-session/no-pytest discipline and ran only unittest checks.
   - It still opened broad `sed -n '1,260p'` windows before using the exact
     anchor.
   - It produced a valid patch and passing `tests/test_control_api.py`, but the
     final envelope used `protocolVersion: "openclaw/1"` and
     `status: "completed"`, so supervisor rolled it back.
   - Intervention: monitor manually applied the valid patch and superseded the
     repair task.

18. `record:` next_slice was not routed because the prefix table missed record.
   - The replay worker correctly returned
     `next_slice: record: append run evidence...`.
   - `PHASE_ORDER` includes `record`, but `NEXT_SLICE_PHASE_PREFIXES` did not.
   - Supervisor therefore queued another `test` task instead of a record task.
   - Intervention: added `record -> record` to the prefix table and covered it
     with a needs-followup routing regression. The incorrectly queued test task
     was superseded.

19. Redis pending/lag worker patch passed tests but used an unrealistic Redis
    model.
   - `auto-implement-auto-mechanism_extract-auto-reference-d5193c1c17...`
     implemented a useful `XINFO GROUPS` + `XPENDING` probe and passed
     `tests/test_control_api.py`.
   - The patch also treated `XINFO GROUPS` rows as if they contained individual
     consumer names and pending counts. Redis `XINFO GROUPS` exposes group-level
     fields; per-consumer evidence requires `XINFO CONSUMERS` or extended
     `XPENDING`.
   - Intervention: monitor did not cherry-pick that commit. The valid parts were
   manually reimplemented without fake per-consumer projection, and tests now
   cover healthy, missing-group, and `XPENDING` failure paths.

20. XINFO CONSUMERS malformed-success probe validated the monitor/worker split.
   - The worker added a focused regression for successful but malformed
     `XINFO CONSUMERS a9:tasks a9-worker` output.
   - It did not broaden into references or unrelated suites. It returned
     `needs_approval` with the exact missing behavior when the test failed:
     group-level `status/reason/lag/pending` must stay usable while only
     `consumer_probe_*` degrades.
   - Intervention: monitor implemented the missing subprobe malformed guard in
     `scripts/a9_control_api.py` and kept the worker's test in
     `tests/test_control_api.py`.
   - Result: `python3 -m unittest tests/test_control_api.py` passes with `43`
     tests.

21. Reference scan still needs stricter context governance.
   - `auto-reference_scan-auto-test-implement-xinfo-consumers-p-74e...` failed
     as `retryable-worker-budget` with `event_bytes=1075032`, no final envelope,
     and no diff.
   - Root cause: free-form `reference_scan` over mature projects invites large
     output even when the task says bounded.
   - Intervention: monitor recorded the failure in `docs/mistakes.md` and
     replaced the broad scan with a narrow test task using explicit anchors.

22. Redis task stream action thresholds now produce machine-routable decisions.
   - Implemented `thresholds_version=redis_streams_v1`,
     `stream_action`, and `stream_action_reason` on successful
     `a9:tasks` consumer-group probe output.
   - Action domain is intentionally small:
     `continue`, `watch`, `intervene`.
   - Copied threshold contract from the Redis Streams evidence notes:
     `lag_warn >= 100`, `lag_critical >= 1000`,
     `pending_idle_critical_ms >= 30000`, and
     `pending_skew_ratio >= 0.8`.
   - Current control API tests cover healthy continue, lag warning watch,
     lag critical intervene, pending skew intervene, pending stuck intervene,
     malformed consumer output, `XPENDING` failure, invalid pending parse, and
     missing group.

23. Worker/monitor split found and repaired two real threshold bugs.
   - First bug: pending-stuck detection used idle from the highest-pending
     consumer only. A worker-generated regression showed that a lower-pending
     consumer can be stuck longer and still require `intervene`.
   - Repair: compute stuck idle from consumers with `pending > 0`, not just the
     pending-ranked first entry.
   - Second bug: the first repair still computed from capped `top_consumers`.
     A follow-up worker regression showed that the fourth consumer can be
     hidden from the API response cap while still needing intervention.
   - Repair: compute threshold inputs from all parsed consumer rows before
     applying `TASKS_STREAM_TOP_CONSUMERS_LIMIT`; keep `top_consumers` capped
     only for response size.
   - Result: `python3 -m unittest tests/test_control_api.py` passes with `51`
     tests.

24. Auto-next still generates overly broad checks after successful slices.
   - After narrow Redis tasks stream slices, generated follow-ups repeatedly
     included unrelated supervisor/memory/checkpoint suites and `cargo build`.
   - Monitoring intervention was required to rewrite those tasks back to
     `python3 -m unittest tests/test_control_api.py`.
   - Next governance repair should update auto-next check selection so phase
     follow-ups inherit the previous focused test surface instead of falling
     back to broad default checks.

25. Auto-next focused-check inheritance repaired.
   - Added supervisor check selection so non-reference-scan follow-ups inherit
     the previous task's declared checks when present.
   - `reference_scan` remains special-cased to the lightweight supervisor
     py_compile check.
   - Regression added for `implement -> test` routing: the next task keeps
     `python3 -m unittest tests/test_control_api.py` and does not reintroduce
     `cargo build --workspace`.
   - Verification:
     `python3 -m unittest tests.test_supervisor.SupervisorTests.test_schedule_next_task_routes_to_test_phase_from_next_slice_prefix`,
     `python3 -m unittest tests/test_control_api.py`, and
     `python3 -m unittest tests/test_supervisor.py` all passed.

26. Soak reports now carry communication action snapshots.
   - Added `scripts/a9_soak.py::communication_snapshot()` to load the control
     API locally and copy bounded communication health into soak reports:
     `nodes_count`, `redis`, and `tasks_stream`.
   - Soak report tests now cover healthy, degraded
     (`consumer_group_missing -> watch`), and unavailable
     (`redis_unavailable -> intervene`) tasks stream action payloads.
   - `redis_tasks_stream_probe()` now emits
     `thresholds_version/stream_action/stream_action_reason` for early
     degraded/unavailable branches, not only healthy/probe-complete branches.
   - Real bounded fake-worker smoke passed:
     `python3 scripts/a9_soak.py run --fake-worker --tasks 1 --sleep-seconds 0 --task-id communication-snapshot-smoke-2`.
     The resulting `.a9/soak/latest.json` had `return_code=0`,
     empty `queued_tail`, Redis hot path status `ok`, and
     `tasks_stream.reason=consumer_group_missing`,
     `stream_action=watch`,
     `stream_action_reason=consumer_group_missing`.
   - Verification suites:
     `python3 -m unittest tests/test_control_api.py tests/test_soak.py`
     passed with `63` tests before the final soak assertion, and
     `python3 -m unittest tests/test_soak.py` passed with `11` tests after it.

Current communication state after this observation:

- `crates/a9-gateway` has typed reconnect decision evidence.
- Fake Redis transcript coverage exists for retryable and terminal paths.
- Terminal stop-path coverage exists: terminal failure classification emits no
  `RetryScheduled` lifecycle event.
- `cargo test -p a9-gateway` passes with `17` tests.
- Middleware and supervisor managed-flow sequence gates are implemented and
  covered by `python3 -m unittest tests/test_supervisor.py tests/test_middleware.py`
  with `71` tests.

Next monitoring target:

- Treat "wide-read budget failure in tiny test tasks" as a supervisor prompt
  governance bug. Next slices should either provide exact line anchors or make
  the worker output SEARCH/REPLACE directly from a smaller context packet.
- ProtocolVersion drift is now covered by supervisor tests. The remaining
  governance issue is worker prompt discipline: even bounded test tasks still
  sometimes read overly broad file windows. Workers also still emit common
  envelope aliases outside the current whitelist, especially `openclaw/1` and
  `completed`.
- Then return to the five communication blocks: node state machine, Redis
  Streams production governance, multi-machine onboarding, SSE replay, and
  communication metrics/soak.

27. Tmux action contract worker was useful, but monitor intervention was required.
   - Task:
     `implement-tmux-action-contract-20260527T053300Z`.
   - Run:
     `.a9/runs/implement-tmux-action-contract-20260527T053300Z-20260527T054014Z-a1`.
   - Worker intent was correct: map tmux status/ensure results to deterministic
     machine actions (`continue`, `repair`, `retry`, `wait_for_approval`) so
     phone/control-plane consumers do not infer behavior from free text.
   - Good behavior: it used targeted `rg`/bounded `sed`, avoided raw session
     close-reading files, avoided service/process status, changed only
     `scripts/a9_control_api.py` and `tests/test_control_api.py`, and the
     supervisor-declared checks passed with `58` tests.
   - Drift observed: it triggered a `web_search` event even though the task did
     not request internet research. This is prompt discipline drift, not an
     implementation need.
   - Drift observed: it self-ran only `python3 -m unittest tests.test_control_api`
     while the declared checks also included `tests/test_remote.py`. Supervisor
     checks caught this and passed, but worker self-report was narrower than the
     authoritative check surface.
   - Monitor intervention: cherry-picked worker commit `154e6d2`, added explicit
     `tmux_action_reason` fields for status/ensure/blocked outcomes, kept the
     existing `reason` alias for compatibility, and added a supervisor prompt
     rule forbidding web search/browsing unless the task explicitly asks for
     internet research.
   - Verification:
     `python3 -m unittest tests/test_control_api.py tests/test_remote.py`
     passed with `58` tests, and
     `python3 -m unittest tests/test_supervisor.py` passed with `79` tests.

28. Follow-up worker obeyed no-web discipline and added node-level tmux aggregation.
   - Task:
     `auto-test-implement-tmux-action-contract-20260527T053300Z-20260527T054343Z`.
   - Run:
     `.a9/runs/auto-test-implement-tmux-action-contract-20260527T053300Z-20260527T054343Z-20260527T060902Z-a1`.
   - Prompt inspection confirmed the queued task carried the new rule:
     no web search/browsing unless explicitly requested.
   - Good behavior: no `web_search` event, no raw session reads, no service
     status reads, touched only allowed files, strict envelope passed without
     alias drift, and supervisor-declared checks passed.
   - Implemented mechanism: `/api/nodes` now enriches each node with latest
     tmux evidence action fields:
     `tmux_action`, `tmux_action_reason`, `tmux_status`, and
     `tmux_evidence_path`.
   - Remaining discipline issue: worker still used noisy/wide reads, including
     `ls -la`, `sed -n '1210,1360p'`, and
     `sed -n '1180,1415p'`. This did not break the task, but it shows the next
     supervisor improvement should enforce or score read-window size instead of
     relying only on prompt text.
   - Verification after cherry-pick:
     `python3 -m unittest tests/test_control_api.py tests/test_remote.py`
     passed with `59` tests.

29. Multi-machine reference scan stayed bounded after monitor rewrote the task.
   - Task:
     `reference_scan-multimachine-ssh-tailscale-tmux-governance-20260527T062000Z`.
   - Run:
     `.a9/runs/reference_scan-multimachine-ssh-tailscale-tmux-governance-20260527T062000Z-20260527T062110Z-a1`.
   - Monitor intervention: replaced the auto-generated tmux follow-up with a
     focused multi-machine SSH/Tailscale/tmux reference scan using only A9
     `scripts/a9_remote.py`, `tests/test_remote.py`, and OpenHands
     SSH/tmux bounded anchors.
   - Good behavior: no web search, no raw session reads, no `ls -la`, no file
     changes in `reference_scan`, strict envelope passed, and declared
     `py_compile` check passed.
   - Copied mechanism selected: OpenHands-style preflight contract before
     install, tmux as optional-but-visible governance signal, SSH hygiene
     diagnostics, and A9's existing `plan -> probe -> bootstrap` split.
   - Concrete next slice selected: deterministic remote probe action contract in
     `scripts/a9_remote.py` with focused tests in `tests/test_remote.py`.
   - Remaining issue: relative `reference-projects/openhands/...` paths failed
     inside the worker worktree. Worker recovered via absolute
     `/root/a9/reference-projects/openhands/...`, but future reference tasks
     should use absolute reference paths directly to avoid wasted events.
   - Cost/behavior evidence: `event_count=22`, `event_bytes=21042`,
     `prompt_approx_tokens=6660`, and actual uncached input was `17896`.

30. Mechanism extract drifted into docs and was rolled back by scope guard.
   - Task:
     `auto-mechanism_extract-reference_scan-multimachine-ssh-tails-c9aefaf119-20260527T062318Z`.
   - Run:
     `.a9/runs/auto-mechanism_extract-reference_scan-multimachine-ssh-tails-c9aefaf119-20260527T062318Z-20260527T062626Z-a1`.
   - Worker produced a useful implementation contract, but wrote
     `docs/remote-probe-contract.md` even though allowed paths were only
     `scripts/a9_remote.py`, `scripts/a9_control_api.py`,
     `tests/test_remote.py`, and `tests/test_control_api.py`.
   - Scope guard correctly failed and git governance rolled the patch back.
   - Monitor intervention: deleted the auto repair task and replaced it with a
     direct implement task constrained to `scripts/a9_remote.py` and
     `tests/test_remote.py`.

31. Remote probe action contract implemented by worker, with remaining read-discipline issues.
   - Task:
     `implement-remote-probe-action-contract-20260527T063000Z`.
   - Run:
     `.a9/runs/implement-remote-probe-action-contract-20260527T063000Z-20260527T063036Z-a1`.
   - Implemented:
     `classify_probe_result(return_code, output)` with
     `probe_action`, `probe_action_reason`, `required_missing`, and
     `optional_missing`.
   - `probe(args)` now always parses probe output and emits classification
     fields in JSON.
   - Contract:
     nonzero SSH -> `retry/ssh_exec_error`; missing required
     `git/python3/curl` -> `repair/missing_required_tools`; optional missing
     `tmux/tailscale` -> `continue/optional_tools_missing`; all present ->
     `continue/probe_ok`.
   - Verification after cherry-pick:
     `python3 -m unittest tests/test_remote.py tests/test_control_api.py`
     passed with `63` tests.
   - Behavior issue: worker still opened full 260-line windows before `rg`.
     This violated prompt discipline but stayed within event budget. The next
     governance improvement should make command-window violations a machine
     finding.
   - Communication issue observed: Codex stream reset four times and recovered
     automatically before test execution. This is useful evidence for A9's own
     reconnect/governance design.

32. Auto-test drifted into control API integration and required monitor takeover.
   - Task:
     `auto-test-implement-remote-probe-action-contrac-648cc80a2e-20260527T063407Z`.
   - Run:
     `.a9/runs/auto-test-implement-remote-probe-action-contrac-648cc80a2e-20260527T063407Z-20260527T063623Z-a1`.
   - Worker violated two rules:
     it triggered `web_search` again despite the no-web rule, and it read
     service/process status via `python3 scripts/a9_service.py ps`.
   - Worker also modified `scripts/a9_control_api.py` and
     `tests/test_control_api.py` while allowed paths were only
     `scripts/a9_remote.py` and `tests/test_remote.py`.
   - Scope guard correctly failed and rolled back the worker patch.
   - The patch idea was still correct: propagate `probe_action` and
     `probe_action_reason` from remote probe classification into the control API
     response. Monitor manually reapplied a tightened version that always parses
     probe output, including nonzero SSH return codes.
   - Verification:
     `python3 -m unittest tests/test_control_api.py tests/test_remote.py`
     passed with `64` tests.
   - Governance lesson: auto-test phases can discover missing integration, but
     they must not silently broaden allowed paths. The supervisor should either
     schedule a new implement task with expanded allowed paths or stop for
     monitor review.

33. Probe action routing patch was good, but long supervisor test caused idle timeout.
   - Task:
     `implement-probe-action-routing-20260527T064200Z`.
   - Run:
     `.a9/runs/implement-probe-action-routing-20260527T064200Z-20260527T070032Z-a1`.
   - Worker followed the intended direction and wrote a small patch:
     `probe_action_to_followup()` in supervisor, `supervisor_followup` in
     control API probe responses, and focused tests.
   - `tests/test_control_api.py` passed inside the worker, but
     `tests/test_supervisor.py` produced no output long enough for the worker
     idle timeout and the run ended as `retryable-timeout`.
   - Because final envelope was missing, git governance rolled back the patch
     despite scope and patch guards passing.
   - Monitor reapplied the patch manually and verified:
     `python3 -m unittest tests.test_supervisor.SupervisorTests.test_probe_action_to_followup_maps_continue_repair_retry tests/test_control_api.py tests/test_remote.py`
     passed with `65` tests, and full
     `python3 -m unittest tests/test_supervisor.py` passed with `80` tests in
     `131.735s`.
   - Governance lesson: declared checks that can run for ~130s with sparse
     output need a longer idle timeout or heartbeat output. Otherwise good
     patches are rolled back as retryable-timeout.

34. Worker idle timeout now accounts for long supervisor suite.
   - Implemented `effective_worker_idle_timeout_seconds(task)`.
   - If declared checks include `tests/test_supervisor.py`, worker idle timeout
     is raised to at least `420s`; other tasks keep their declared idle timeout.
   - `run_worker()` records the effective `idle_timeout_seconds` in the worker
     summary for future diagnosis.
   - Verification:
     targeted supervisor idle-timeout tests passed, `python3 -m unittest
     tests/test_control_api.py tests/test_remote.py` passed with `64` tests,
     and full `python3 -m unittest tests/test_supervisor.py` passed with `81`
     tests in `132.361s`.

35. Remote probe state now survives into the node list.
   - Task:
     `implement-node-last-probe-action-20260527T074000Z`.
   - Run:
     `.a9/runs/implement-node-last-probe-action-20260527T074000Z-20260527T073815Z-a1`.
   - Worker implemented a small control-plane state contract: `/api/nodes/probe`
     stores `last_probe_action`, `last_probe_action_reason`,
     `last_probe_required_missing`, `last_probe_optional_missing`, and
     `last_probe_checked_at` on the canonical node record.
   - Monitor cherry-picked worker commit `9523d6b...` as `1060bbf` and verified
     `python3 -m unittest tests/test_control_api.py tests/test_remote.py`
     passed with `64` tests.
   - Quality note: worker initially tried an exact test name that did not exist,
     then corrected to the declared control API suite. This is acceptable but
     should be counted as command-friction in future run scoring.

36. Auto-test added handler-level evidence for persisted probe state.
   - Task:
     `auto-test-implement-node-last-probe-action-2026-e98bdb766a-20260527T074046Z`.
   - Run:
     `.a9/runs/auto-test-implement-node-last-probe-action-2026-e98bdb766a-20260527T074046Z-20260527T075137Z-a1`.
   - Worker added a focused HTTP handler test: `POST /api/nodes/probe` followed
     by `GET /api/nodes` must expose the persisted `last_probe_*` fields.
   - Monitor cherry-picked worker commit `0b1e526...` as `6a734df` and verified
     `python3 -m unittest tests/test_control_api.py tests/test_remote.py`
     passed with `65` tests.
   - Drift note: the worker read previous run context and used a broad directory
     listing even though the task only needed local control API tests. This did
     not break scope, but the next worker prompt should be narrower and should
     avoid automatic `reference_scan` when the next slice is explicitly a test.

37. Monitor rewrote the next task and caught declared-check drift.
   - Task:
     `test-node-probe-retry-handler-20260527T081000Z`.
   - Run:
     `.a9/runs/test-node-probe-retry-handler-20260527T081000Z-20260527T080612Z-a1`.
   - Worker added the intended negative-path HTTP handler test for persisted
     retry probe state and stayed inside `tests/test_control_api.py`.
   - Scope and patch guards passed. Supervisor's declared check
     `python3 -m unittest tests/test_control_api.py` passed with `57` tests;
     monitor then verified `python3 -m unittest tests/test_control_api.py
     tests/test_remote.py` passed with `66` tests.
   - Monitor cherry-picked worker commit `ccce31d...` as `d1864f0`.
   - Quality issue: the worker ignored the "run only declared check" bound,
     attempted pytest, and then proposed installing pytest even though the
     supervisor check already passed. The next queued task was rewritten away
     from this wrong next_slice.

38. Broad multi-reference scan exceeded event budget and violated task bounds.
   - Task:
     `reference-scan-multimachine-ssh-tailscale-tmux-20260527T082000Z`.
   - Run:
     `.a9/runs/reference-scan-multimachine-ssh-tailscale-tmux-20260527T082000Z-20260527T081137Z-a1`.
   - Status:
     `retryable-worker-budget`; worker event bytes reached `1067843`, above the
     `120000` event budget, and no final envelope was produced.
   - Worker violated explicit bounds before scanning references: it read service
     process status and session summary/close-reading docs even though the task
     forbade service status and raw/session docs.
   - Worker then launched broad `rg` scans across four large reference projects;
     the Aider fixture output alone was enough to blow the event budget.
   - Monitor conclusion:
     multi-machine reference work must be split into one reference project and
     one mechanism per task. The next task is narrowed to Barter-rs reconnect
     action/backoff files only.

39. Barter-rs reconnect contract extraction bounded to 5 socket files.
   - Scope:
     `backoff.rs`, `on_connect_err.rs`, `on_stream_err.rs`, `update.rs`, `mod.rs` only.
   - Mechanism note:
     keep reconnect as explicit lifecycle events (`Connected -> Item* -> Reconnecting`) and separate connect-failure action (`Reconnect|Terminate`) from stream-failure action (`Continue|Reconnect`) so multi-machine SSH/Tailscale/tmux orchestration can decide retry vs. hard-stop deterministically.

40. Reconnect governance implementation required monitor repair.
   - Task:
     `implement-remote-reconnect-governance-contract-20260527T084000Z`.
   - Run:
     `.a9/runs/implement-remote-reconnect-governance-contract-20260527T084000Z-20260527T082504Z-a1`.
   - Worker produced a scoped patch but hit `retryable-worker-budget` after the
     declared tests failed. Scope/patch guards passed, but git governance rolled
     the patch back because final envelope was missing.
   - Failure cause:
     `probe_node()` hard-called new `FakeRemote` helper methods, breaking older
     handler tests whose fakes only implemented the probe contract.
   - Monitor reapplied the patch, added compatibility fallbacks, corrected
     non-reconnect backoff to `0`, and verified:
     `python3 -m py_compile scripts/a9_remote.py scripts/a9_control_api.py
     scripts/a9_supervisor.py && python3 -m unittest tests/test_remote.py
     tests/test_control_api.py` passed with `69` tests.

41. Redis command ACK-once needed monitor takeover after worker produced no final.
   - Task:
     `node-command-ack-once-20260529T1348`.
   - Run:
     `.a9/runs/node-command-ack-once-20260529T1348-20260529T134512Z-a1`.
   - Status:
     `retryable-worker-failed`.
   - Worker failure mode:
     no `final.md`, no strict envelope, no SEARCH/REPLACE patch, and no git
     diff. The monitor score did not block, so this is an execution-output
     failure rather than a task-quality finding.
   - Monitor takeover:
     implemented `node_command_ack_once()` and CLI `command-ack-once` directly,
     following the existing claim-once Redis Streams boundary and Barter-style
     external command separation. ACK is now a bounded XACK-only action; it
     never executes a task action.
   - Verification:
     `python3 -m unittest tests.test_node tests.test_control_api
     tests.test_remote` passed with `178` tests; `python3 -m unittest
     tests.test_control_api tests.test_node tests.test_remote tests.test_monitor`
     passed with `196` tests; `python3 -m py_compile scripts/a9_node.py`
     passed. Real Redis smoke enqueued command `smoke-ack-once-20260529T1353`,
     claimed stream id `1780062705420-0`, and `command-ack-once` returned
     `status=ok`, `acked_count=1`.
   - Governance lesson:
     worker can still fail before emitting an envelope even when prompt budget
     is low. Supervisor should eventually distinguish "no final/no patch" as a
     prompt or exec-channel issue and schedule a narrower retry before burning a
     full run.

42. Redis command work-once passed but showed context-discipline drift.
   - Task:
     `node-command-work-once-20260529T1358`.
   - Run:
     `.a9/runs/node-command-work-once-20260529T1358-20260529T135424Z-a1`.
   - Status:
     `pass`.
   - Worker outcome:
     added `node_command_work_once()` and CLI `command-work-once`. The loop
     claims at most one Redis command, executes only built-in `status`, writes a
     `node_command_result` event to `a9:events`, and ACKs only after XADD
     succeeds.
   - Verification:
     worker ran `python3 -m unittest tests.test_node tests.test_control_api
     tests.test_remote` and `python3 -m py_compile scripts/a9_node.py`. Monitor
     then ran a real Redis smoke: enqueue `smoke-work-once-20260529T1402`,
     `command-work-once`, read `a9:events` by result event id
     `1780063270699-0`; result was `status=ok`, claimed id
     `1780063270513-0`, and ACK returned `xack=1`.
   - Quality findings:
     the worker initially failed tests twice, first returning XADD error output
     as `result_event_id`, then introducing a `NameError`. It repaired both.
     It also read `docs/communication-observation-log.md` and used a broad `rg`
     that hit `vendor-src/codex`, exceeding the intended reference scope. Event
     bytes reached `123180`, slightly above the `120000` observation budget.
   - Governance lesson:
     Spark can complete bounded implementation after self-repair, but monitor
     must keep policing reference scope and event growth. Future prompts should
     explicitly forbid broad `rg` roots and ask for line-window reads only.

43. Result-event reader passed but needed monitor field repair.
   - Task:
     `node-command-result-reader-20260529T1406`.
   - Run:
     `.a9/runs/node-command-result-reader-20260529T1406-20260529T144227Z-a1`.
   - Status:
     `pass`.
   - Worker outcome:
     added `parse_node_command_result_event()`,
     `node_command_result_read_once()`, and CLI `command-result-read-once`.
     The reader uses bounded `XRANGE event_stream id id` and normalizes
     `node_command_result` fields into a stable JSON contract.
   - Monitor repair:
     after supervisor pass, review found a duplicate `error_code` key in
     `parse_node_command_result_event()` that caused missing `error_code` input
     to return an empty string instead of `ok`. Monitor removed the duplicate
     key and added a focused regression test.
   - Verification:
     `python3 -m py_compile scripts/a9_node.py` passed.
     `python3 -m unittest tests.test_node tests.test_control_api
     tests.test_remote` passed with `192` tests. Real Redis smoke enqueued
     `smoke-result-read-20260529T1455`, ran `command-work-once`, then
     `command-result-read-once 1780066510627-0`; output returned
     `status=ok`, `error_code=ok`, and the expected command id.
   - Quality findings:
     worker read `scripts/a9_control_api.py` despite the task explicitly
     forbidding control API changes/reads, had multiple apply-patch context
     failures, and exceeded observation budgets (`event_count=108`,
     `event_bytes=243613`). Implementation was useful, but context discipline
     degraded again.
   - Governance lesson:
     reference-scope enforcement should become more explicit for worker file
     reads. Until then, monitor must inspect event logs, not just scope_guard,
     because scope_guard only covers changed files.

44. Control API result lookup required monitor takeover after worker capacity failure.
   - Task:
     `control-api-node-command-result-20260529T1500`.
   - Run:
     `.a9/runs/control-api-node-command-result-20260529T1500-20260529T145648Z-a1`.
   - Worker status:
     `retryable-worker-failed`; Codex Spark returned "Selected model is at
     capacity" before final/envelope/patch. The run stayed bounded by file
     scope, but event bytes reached `191833`, so this is another observation
     point for context growth under failures.
   - Monitor outcome:
     manually added control API exposure for `node_command_result_read_once()`.
     `GET /api/node-command-results/{result_event_id}` now validates Redis stream
     ids, accepts optional `event_stream` and `timeout`, delegates parsing to
     `scripts/a9_node.py`, and returns stable
     `node_command_result_lookup` JSON.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py` passed.
     `python3 -m unittest tests.test_control_api tests.test_node
     tests.test_remote` passed with `195` tests. Real Redis smoke read
     `1780066510627-0` through `node_command_result_lookup()` and returned
     `status=ok`, `error_code=ok`, command
     `smoke-result-read-20260529T1455`.
   - Governance lesson:
     worker capacity failures need a narrower retry or monitor takeover path,
     not more gates. The useful invariant is flow continuity plus evidence:
     submit command, worker writes result event, API reads result event, then
     mobile/remote can close the command loop.

45. By-command result lookup exposed an exec-tool compatibility failure.
   - Task:
     `control-api-node-command-result-by-command-20260529T1515`.
   - Run:
     `.a9/runs/control-api-node-command-result-by-command-20260529T1515-20260529T150732Z-a1`.
   - Worker status:
     `retryable-worker-failed` before implementation. The raw event error was
     `Tool 'image_generation' is not supported with
     gpt-5.3-codex-spark-1p-codexswic-ev3`, so the issue was Codex exec/tool
     configuration for Spark, not task complexity or code quality.
   - Monitor outcome:
     manually added `node_command_result_by_command_lookup()` and
     `GET /api/node-command-results/by-command/{command_id}`. The helper uses a
     bounded `XREVRANGE ... COUNT N` scan on the event stream, matches
     `kind=node_command_result` plus `command_id`, then delegates normalization to
     `node_command_result_lookup()` rather than duplicating result parsing.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py` passed.
     `python3 -m unittest tests.test_control_api tests.test_node
     tests.test_remote` passed with `199` tests. Real Redis smoke queried
     command `smoke-result-read-20260529T1455` and found result event
     `1780066510627-0` with `status=ok`.
   - Governance lesson:
     Spark execution must be configurable without unsupported tools before it
     can run continuously. Until that is fixed, the monitor should continue to
     intervene on exec-channel failures and keep the communication flow moving.

46. Worker default model corrected back to stable Codex.
   - Trigger:
     repeated 24h worker startup failures on `gpt-5.3-codex-spark`, including
     unsupported `image_generation` tool injection and model-capacity failures.
   - Evidence:
     `docs/mistakes.md` already recorded that Spark must not be the unattended
     default and that the default should return to `gpt-5.3-codex`.
   - Change:
     `scripts/a9_supervisor.py` now defaults `DEFAULT_WORKER_MODEL` to
     `gpt-5.3-codex`. Spark remains usable only when explicitly selected via
     `A9_SUPERVISOR_MODEL` for controlled smoke or cost experiments.
   - Governance lesson:
     flow continuity beats cheap-model optimization. Cost tuning belongs after
     the worker can reliably start, execute, test, and report.

47. Real worker smoke confirmed default-model path after restore.
   - Scope:
     bounded smoke after restoring `DEFAULT_WORKER_MODEL` to
     `gpt-5.3-codex`; verification limited to observation-log tail and
     `scripts/a9_supervisor.py` default-model references.
   - Observation:
     this run used the default worker model path (`A9_SUPERVISOR_MODEL` unset,
     resolved via `DEFAULT_WORKER_MODEL`), and the worker outcome was positive:
     could start, edit within scope, and run a lightweight check.
   - Lightweight check:
     `python3 -m py_compile scripts/a9_supervisor.py` passed.

48. Mobile control now exposes node-command submit and result polling.
   - Scope:
     external mobile workspace `/mnt/d/root/a9_mobile_agent_lab`; this is outside
     the supervisor worktree, so monitor implemented directly instead of routing
     through the 24h worker.
   - Change:
     mobile Remote control can submit a bounded node `status` command through
     `/api/nodes/command-submit`, then poll
     `/api/node-command-results/by-command/{command_id}` and show queued/noop/ok
     state in the Agent chat.
   - Verification:
     `npx tsc --noEmit` passed in the mobile workspace. `npm run smoke:mobile`
     passed after restarting the Expo web server. A Playwright mobile smoke
     clicked `Node status command` and saw the submit/result card. Real Redis
     smoke consumed `mobile-node-status-1780068352032` with
     `python3 scripts/a9_node.py command-work-once --block-ms 1000`; by-command
     lookup returned result event `1780068403702-0` and `status_ok`.
   - Governance lesson:
     supervisor task results and Redis node-command results are different
     channels. The UI must not pretend a normal `/api/submit` task can be read
     via node-command result lookup; use the by-command result API only for
     commands written to `a9:tasks`.

49. Node-command worker loop became a real local daemon path.
   - Change:
     added `scripts/a9_node.py command-work-loop`, a bounded/infinite Redis
     Stream consumer loop that repeatedly calls `node_command_work_once()`,
     emits JSON-lines results, and summarizes processed/noop/degraded counts.
   - Service wiring:
     added `infra/systemd/a9-node-worker.service`, wired it into
     `scripts/a9_service.py unit/install-hint/process detection`, and added it
     to `scripts/a9_stack.sh start|stop|status|logs` so local WSL operation now
     starts control-api, node-worker, and mobile-web together.
   - Runtime bug found by smoke:
     the first stack worker used `--block-ms 5000` with a 3 second subprocess
     timeout, so long-polling falsely degraded as `redis_unavailable`. The loop
     now raises effective timeout above block time, and service/stack pass
     `--timeout 10`.
   - Verification:
     `python3 -m py_compile scripts/a9_node.py scripts/a9_service.py` and
     `bash -n scripts/a9_stack.sh` passed. `python3 -m unittest
     tests.test_node tests.test_service tests.test_control_api tests.test_remote`
     passed with `211` tests. Real stack smoke submitted
     `stack-node-worker-smoke-1780069227`; background node-worker consumed
     stream id `1780069228062-0`, wrote result event `1780069228128-0`, ACKed
     it, and by-command lookup returned `status_ok`.
   - Governance lesson:
     daemon settings must be tested under their real blocking behavior. A green
     `work-once` is not enough when the service wrapper changes timing.

50. Node-command worker now recovers stale Redis Stream pending entries.
   - Trigger:
     real Redis observation showed `XPENDING a9:tasks a9-worker` had `3`
     orphaned entries across old consumers, while the daemon only read new
     messages with `XREADGROUP ... >`. After crash/restart, old claimed work
     could stay stuck forever.
   - Mechanism copied:
     Redis Streams consumer-group recovery via `XAUTOCLAIM`; A9 now reads new
     commands first, then reclaims pending entries older than `min_idle_ms` when
     no new event is available.
   - Change:
     `scripts/a9_node.py` added `parse_xautoclaim_output()`,
     `node_command_claim_stale_once()`, and `recover_pending/min_idle_ms`
     wiring in `node_command_work_once()` and `command-work-loop`. The stack and
     systemd node-worker command run with `--min-idle-ms 30000`.
   - Verification:
     `python3 -m py_compile scripts/a9_node.py scripts/a9_service.py` passed.
     `bash -n scripts/a9_stack.sh` passed. `python3 -m unittest
     tests.test_node tests.test_service tests.test_control_api tests.test_remote`
     passed with `215` tests. Real Redis smoke reclaimed all `3` stale pending
     entries with `claim_source=pending` and reduced `XPENDING` to `0`. After
     restarting the stack, command `daemon-status-1780070211` was consumed by
     the background node-worker, result event `1780070211610-0` returned
     `status_ok`, and `XPENDING` stayed `0`.
   - Governance lesson:
     stable communication needs recovery semantics, not only fast transport.
     Pending recovery is an observation-backed mechanism and should stay
     evidence-driven rather than becoming a hard gate.

51. Node recovery cycle API added for multi-machine SSH/Tailscale/tmux repair.
   - Trigger:
     after command/result and pending recovery were stable, the next missing
     operational link was a single controller route that can inspect node
     connection summary and propose the next repair step without making the
     phone or UI guess which endpoint to call.
   - Mechanism copied:
     mature control-plane pattern: reconcile current state into an action plan,
     keep dry-run/planning as the default, execute only through existing gated
     actions, and record evidence for every cycle.
   - Change:
     `scripts/a9_control_api.py` now exposes
     `GET/POST /api/nodes/recovery-cycle`. It reads `node_status()` plus each
     node `recovery_plan`, emits bounded steps, prepares tmux/heartbeat plan
     evidence when needed, and only executes when `execute=true`. Execution
     still goes through existing phone-control/gated remote paths. Offline
     nodes now surface as `manual_required` quarantine steps rather than a fake
     successful noop.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py` passed.
     `python3 -m unittest tests.test_control_api tests.test_remote
     tests.test_node tests.test_service` passed with `219` tests. After stack
     restart, real `GET /api/nodes/recovery-cycle` returned
     `status=needs_attention`, `step_count=3`, and marked the three currently
     registered offline nodes as `manual_required` with SSH/Tailscale/tmux
     verification steps. `XPENDING a9:tasks a9-worker` remained `0`.
   - Governance lesson:
     multi-machine repair should be a controller reconciliation loop, not UI
     branching logic. The phone can call one route, while A9 keeps endpoint
     selection, gate status, evidence, and next action in the backend.

52. Mobile Agent UI now surfaces node recovery cycle.
   - Trigger:
     after `/api/nodes/recovery-cycle` existed, the phone still had to inspect
     separate node/tmux/probe state. That violated the mobile-control goal:
     phone users should see the controller decision, not rebuild backend logic.
   - Change:
     external mobile workspace `/mnt/d/root/a9_mobile_agent_lab` now reads
     `GET /api/nodes/recovery-cycle` during normal refresh, stores
     `lastNodeRecoveryCycle`, shows a recovery summary in the mobile Remote
     card, and renders an assistant recovery card with step status, manual
     required nodes, evidence link, refresh, arm remote, and execute actions.
     `POST /api/nodes/recovery-cycle` is wired for explicit execution with
     operator scope; execution remains backend-gated.
   - Verification:
     `npx tsc --noEmit` passed in `/mnt/d/root/a9_mobile_agent_lab`.
     `npm run smoke:mobile` passed after adding recovery summary/card/button
     checks to `scripts/mobile-ui-smoke.js`. Stack remains running with
     `control-api`, `node-worker`, and `mobile-web`; `XPENDING a9:tasks
     a9-worker` remained `0`.
   - Governance lesson:
     recovery routing belongs in A9 backend, while mobile is the takeover
     console. This keeps UX simple and prevents endpoint-selection logic from
     drifting between phone and controller.

53. Recovery-cycle execution now has a top-level phone-control gate.
   - Trigger:
     real `execute=true` observation showed subactions were gated, but the
     recovery cycle itself did not first check `nodes.recovery.cycle`. That
     made the API contract weaker than the mobile button implied.
   - Change:
     `node_recovery_cycle()` now checks `command_gate("nodes.recovery.cycle")`
     before any executable branch. When disarmed, it returns `status=blocked`,
     `step_count=0`, the gate payload, summary evidence, and does not call
     probe/tmux/heartbeat subactions. Planning mode remains ungated.
   - Verification:
     `python3 -m unittest tests.test_control_api tests.test_remote
     tests.test_node tests.test_service` passed with `220` tests. Real API
     smoke after stack restart: disarmed `POST /api/nodes/recovery-cycle`
     returned `status=blocked`, `gate.reason=phone_control_disarmed`, and
     `step_count=0`; armed remote execution returned `status=needs_attention`
     with one `manual_required` quarantine step. Phone control was disarmed
     after the smoke and `XPENDING a9:tasks a9-worker` remained `0`.
     Mobile type/display was also updated to surface the top-level recovery
     gate; `npx tsc --noEmit` and `npm run smoke:mobile` passed in
     `/mnt/d/root/a9_mobile_agent_lab`.
   - Governance lesson:
     one-click recovery needs a coarse-grained gate before route-specific
     gates. This gives the operator a stable mental model: plan is safe by
     default; execute requires an armed remote control window.

54. Recovery-loop daemon added for planning-only automation.
   - Trigger:
     the recovery-cycle API and mobile controls were usable, but A9 still only
     checked node recovery when an operator clicked. That was not yet a 24h
     service shape. The next safe automation step was continuous observation,
     not automatic repair.
   - Mechanism copied:
     control-plane reconcile loops: poll current state, produce a bounded
     plan, persist latest state for other surfaces, emit machine-readable
     observations, and keep mutation behind a separate explicit execution
     path.
   - Change:
     `scripts/a9_recovery_loop.py` runs a bounded or continuous planning-only
     loop against `GET /api/nodes/recovery-cycle`, writes
     `.a9/services/recovery-loop-latest.json`, and emits JSONL observations.
     `infra/systemd/a9-recovery-loop.service`, `scripts/a9_stack.sh`, and
     `scripts/a9_service.py` now manage it beside `control-api`,
     `node-worker`, and `mobile-web`.
   - Verification:
     `python3 -m py_compile scripts/a9_recovery_loop.py
     scripts/a9_service.py scripts/a9_control_api.py` passed. `bash -n
     scripts/a9_stack.sh` passed. `python3 -m unittest
     tests.test_recovery_loop tests.test_service tests.test_control_api
     tests.test_remote tests.test_node` passed with `224` tests.
     `bash scripts/a9_stack.sh status` showed `control-api`, `node-worker`,
     `recovery-loop`, and `mobile-web` running. A real one-shot loop produced
     `status=ok`, `cycle_status=needs_attention`, `step_count=2`,
     `risk_count=3`, and `execute=false`. Phone control remained disarmed and
     `XPENDING a9:tasks a9-worker` stayed `0`. A real GET smoke confirmed
     `max_actions=2` is honored by `/api/nodes/recovery-cycle`.
   - Governance lesson:
     the first automation layer should make drift visible before it changes
     machines. Auto-execution should wait until stale smoke nodes, real remote
     nodes, archive policy, and false-positive recovery risk are separated by
     evidence.

55. Node hygiene separates smoke noise from real remote risk.
   - Trigger:
     the recovery-loop was stable, but real observations showed a stale
     `local-service-smoke` registry entry mixed with two Tailscale remote
     candidates. That polluted the recovery signal and could mislead the
     monitor into chasing test residue.
   - Mechanism copied:
     mature controller hygiene: classify inventory records before acting on
     them, keep noisy records visible as evidence, and filter operational
     decisions by risk scope instead of deleting data.
   - Change:
     `scripts/a9_control_api.py` now adds `node_hygiene()` classification to
     node status. `node_connection_summary()` reports `hygiene_categories`,
     `skipped_noise_count`, and `skipped_noise_nodes`; default
     `/api/nodes/recovery-cycle` skips smoke/noise nodes while
     `include_noise=true` or a direct `node_id` can still inspect them.
     `communication_followup` now ignores smoke noise, so the main monitor
     follows real remote risk first.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py
     scripts/a9_recovery_loop.py` passed. `python3 -m unittest
     tests.test_control_api tests.test_recovery_loop tests.test_service
     tests.test_remote tests.test_node` passed with `227` tests. Real API
     smoke after stack restart showed `hygiene_categories={test_smoke: 1,
     remote_candidate: 2}`, `risk_count=2`, `skipped_noise_count=1`, default
     recovery `step_count=2`, and `include_noise=true` recovery `step_count=3`.
   - Governance lesson:
     data quality comes before automation. Keeping smoke nodes as evidence but
     excluding them from default recovery makes the 24h monitor less noisy
     without hiding facts or inventing a hard gate.

56. Recovery planning dedupes node aliases by canonical SSH target.
   - Trigger:
     after smoke noise was filtered, real observations still showed two
     Tailscale registry records pointing at the same `root@100.74.166.86:2200`
     target. That would make a 24h monitor repeat the same recovery work under
     two node ids.
   - Mechanism copied:
     inventory reconciliation from mature control planes: preserve raw records,
     derive a canonical resource key, select one primary by freshness, expose
     aliases as evidence, and run default repair once per real resource.
   - Change:
     `scripts/a9_control_api.py` now derives `target_key` with
     `canonical_ssh_target()`, reports `duplicate_target_groups`,
     `duplicate_node_count`, and `duplicate_nodes` in
     `/api/nodes/connection-summary`, and skips duplicate aliases in default
     `/api/nodes/recovery-cycle`. `include_duplicates=true` still exposes the
     full set, and `communication_followup` now follows only the primary node.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py
     scripts/a9_recovery_loop.py` passed. `python3 -m unittest
     tests.test_control_api tests.test_recovery_loop tests.test_service
     tests.test_remote tests.test_node` passed with `230` tests. Real API
     smoke after stack restart showed `risk_count=1`,
     `duplicate_node_count=1`, default recovery `step_count=1`, and
     `skipped_duplicate_count=1` while preserving the duplicate alias evidence.
   - Governance lesson:
     24h automation must act on real resources, not registry aliases. Raw
     events remain visible, but reconciliation decides what the executor should
     touch by default.

57. Offline remote candidates now route to gated SSH probe first.
   - Trigger:
     after node hygiene and target dedupe, the remaining primary Tailscale node
     still produced a generic manual quarantine step. That was too coarse for a
     24h recovery loop: the next useful action is to diagnose SSH reachability,
     then decide whether to repair tmux/heartbeat or require operator network
     intervention.
   - Mechanism copied:
     mature remote recovery pipelines split `observe -> probe -> repair`:
     offline inventory is not immediately treated as irrecoverable, but the
     first mutating/remote command stays behind the existing phone-control gate.
   - Change:
     `node_recovery_plan()` now maps offline `remote_candidate` nodes to a
     `probe` recovery action with route `POST /api/nodes/probe` and command
     `nodes.probe.execute`. Local smoke/noise and unclassified offline nodes
     still use manual quarantine. Default recovery remains planning-only unless
     explicitly executed through the gated path.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py
     scripts/a9_recovery_loop.py` passed. `python3 -m unittest
     tests.test_control_api tests.test_recovery_loop tests.test_service
     tests.test_remote tests.test_node` passed with `231` tests. Real API
     smoke after stack restart showed `risk_count=1`, default recovery
     `step_count=1`, `skipped_duplicate_count=1`, and the single step planned
     `/api/nodes/probe` for `root-100.74.166.86-2200` without executing SSH.
   - Governance lesson:
     recovery should narrow uncertainty before escalating to humans. The loop
     now has a deterministic next diagnostic step, while execution remains
     controlled by phone-control.

58. Remote heartbeat recovery loop reached observe after repair/start.
   - Trigger:
     real recovery execution showed the probe path worked, but heartbeat tmux
     was missing after start. Full bootstrap then timed out in git/bootstrap
     work, so the recovery path needed a smaller repair action focused only on
     the heartbeat contract.
   - Mechanism copied:
     staged control-plane repair: diagnose SSH, repair the smallest broken
     runtime contract, restart the agent heartbeat, then verify state before
     declaring the node healthy.
   - Change:
     `scripts/a9_control_api.py` now supports gated
     `/api/nodes/heartbeat-repair` through `nodes.remote.repair`, reads
     heartbeat-repair evidence, uses evidence timestamps to avoid stale
     tmux-status loops, and routes recovery through
     `probe -> heartbeat_start -> tmux_status -> heartbeat_repair ->
     heartbeat_start -> observe`. `scripts/a9_remote.py` heartbeat script
     generation now passes `sh -n`; the missing here-doc close was fixed.
     Home-path expansion for `~/a9-worker` now uses `$HOME` correctly in
     remote shell commands.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py
     scripts/a9_recovery_loop.py scripts/a9_remote.py` passed.
     `python3 -m unittest tests.test_control_api tests.test_recovery_loop
     tests.test_service tests.test_remote tests.test_node` passed with `243`
     tests. Real gated smoke: `nodes.probe.execute` returned `probe_ok`;
     `nodes.heartbeat.tmux.start` initially started but tmux session vanished;
     `nodes.remote.repair` wrote `/root/a9-worker/.a9/remote-node/heartbeat.sh`;
     after restart, `/api/nodes/status` showed
     `last_heartbeat_at=2026-05-29T19:02:55+00:00` and recovery plan
     `observe`. Final `/api/nodes/recovery-cycle` returned `step_count=0`,
     summary `risk_count=0`, phone-control `disarmed`, and Redis pending `0`.
   - Governance lesson:
     executing the loop exposed two real failure modes that static planning
     missed: a too-heavy bootstrap path and a generated shell syntax bug.
     Keeping every step gated but runnable let the controller converge without
     guessing or hiding the failed intermediate evidence.

59. Recovery observability now exposes loop latest and compact evidence chain.
   - Trigger:
     the phone/control surface could refresh a recovery cycle, but it could not
     see the real probe/repair/tmux chain without opening raw evidence files
     one by one. That weakens monitoring quality because the operator cannot
     quickly verify whether the automation converged through the expected
     sequence.
   - Mechanism copied:
     mature control planes keep raw evidence on disk and expose bounded
     summaries for dashboards: the UI reads a compact timeline while detailed
     files remain the source of truth.
   - Change:
     `scripts/a9_control_api.py` now exposes
     `/api/nodes/recovery-loop/latest` and enriches `/api/nodes/evidence` with
     compact `action`, `reason`, `return_code`, `timed_out`, and `step_count`
     fields without returning large raw output. The mobile control UI reads the
     new latest endpoint and renders a recovery evidence timeline beside the
     recovery card.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py
     scripts/a9_recovery_loop.py scripts/a9_remote.py` passed.
     `python3 -m unittest tests.test_control_api tests.test_recovery_loop
     tests.test_service tests.test_remote tests.test_node` passed with `246`
     tests. Real stack smoke showed all four services running and
     `/api/nodes/recovery-loop/latest` returning `cycle_status=ok`,
     `risk_count=0`, while `/api/nodes/evidence?node_id=root-100.74.166.86-2200`
     showed `tmux-status missing -> heartbeat-repair ok ->
     heartbeat-tmux-start ok`. Mobile `npx tsc --noEmit` and
     `npm run smoke:mobile` passed.
   - Governance lesson:
     monitoring should observe the execution chain directly. This keeps phone
     control useful for intervention while raw evidence files remain available
     for deeper audit and repair.

60. Multi-machine reconnect governance still needs a unified action transcript.
   - Trigger:
     this round focused on multi-machine access and link-recovery governance
     (`SSH + tmux + Tailscale + Redis`) as a bounded reference scan only.
     Current docs already define typed reconnect and flow-wait/resume behavior,
     but operator-side evidence is still split across node probe/tmux actions,
     gateway reconnect decisions, and Redis stream health snapshots.
   - Mechanism copied:
     keep typed action boundaries and replayable lifecycle evidence instead of
     free-form logs. Reference anchors checked in this slice:
     `reference-projects/barter-rs/barter-integration/src/socket/on_connect_err.rs`
     (`Reconnect|Terminate`), 
     `reference-projects/barter-rs/barter-integration/src/socket/on_stream_err.rs`
     (`Continue|Reconnect`),
     `reference-projects/barter-rs/barter-data/src/streams/consumer.rs`
     (reconnect stream + backoff reset semantics), and
     `reference-projects/codex/codex-rs/core/src/compact.rs`
     (explicit compact task/hook lifecycle as governance pattern).
   - Observation interval + reason + repair:
     in short disconnect windows, A9 can recover individual steps, but monitor
     diagnosis still requires stitching multiple evidence surfaces manually.
     Root reason is not missing APIs; it is missing one compact cross-surface
     transcript keyed by node/flow that preserves ordered
     `probe -> reconnecting -> stream-health -> resume/observe` transitions.
     Repair candidate for next slice: add a bounded observation endpoint/doc
     view that joins existing evidence IDs (without changing current execution
     routing), so phone/control can determine whether recovery is converging or
     bouncing without opening raw files one by one.
   - Governance lesson:
     for communication governance, first improve observability composition, then tune
     retry policy. Typed actions already exist; the current gap is transcript
     assembly across machines and transports.
