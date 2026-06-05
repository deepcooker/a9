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

61. Local stack now runs supervisor loop, but idle goal continuation needs priority control.
   - Trigger:
     after adding recovery observability, local development still did not have
     the same always-on supervisor behavior as the systemd unit. The stack ran
     control API, node worker, recovery loop, and mobile web, but not the
     primary `a9_supervisor.py run-loop`.
   - Mechanism copied:
     reuse the existing `infra/systemd/a9-supervisor.service` shape:
     `run-loop --auto-next --sleep-seconds 10 --keep-going-on-error`, with the
     local stack acting as a development daemon wrapper.
   - Change:
     `scripts/a9_stack.sh` now starts/stops/reports `supervisor-loop` and tails
     `supervisor-loop.log`. `tests/test_service.py` locks that local stack
     behavior. After the trial, local stack startup now sets
     `A9_IDLE_GOAL_CONTINUATION=0`, so it consumes queued/subsequent tasks but
     does not invent idle goal-continuation work by default. A real trial
     consumed one existing goal-continuation task and one submitted
     communication reference-scan task.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py scripts/a9_supervisor.py
     scripts/a9_recovery_loop.py scripts/a9_remote.py` passed.
     `python3 -m unittest tests.test_control_api tests.test_recovery_loop
     tests.test_service tests.test_remote tests.test_node` passed with `247`
     tests. Stack status showed `control-api`, `supervisor-loop`, `node-worker`,
     `recovery-loop`, and `mobile-web` running. The submitted worker task
     passed and was integrated as commit `a152f37`.
   - Observation:
     auto-next generated/ran a goal-continuation task before the manually queued
     task. That proves continuous execution works, but it also exposed a token
     and priority risk: idle goal continuation can occupy the worker and read a
     large context packet before a human-directed task. The stale running lease
     was copied to `.a9/tasks/interrupted/` before removal, and local stack
     now disables idle goal generation until priority/context policy is tightened.
   - Governance lesson:
     24h mode should not mean unbounded idle goal work. Next slice should add
     explicit priority and context policy: human/submitted tasks first, idle
     goal continuation only when queue is empty and within a bounded context
     budget, with the chosen model recorded.

62. Recovery transcript now composes node, gateway, Redis, and loop evidence.
   - Trigger:
     entry 60 identified the core observability gap: recovery evidence existed,
     but monitor/mobile still had to stitch node evidence, gateway reconnect
     decisions, Redis stream health, and recovery-loop state by hand.
   - Mechanism copied:
     Barter-rs keeps reconnect action domains explicit (`connect`, `stream`,
     `Reconnect`, `Terminate`, `Continue`) and Codex treats compact output as a
     handoff over raw history, not the fact source. A9 now follows the same
     pattern: compact transcript rows point back to raw `evidence_path` or
     Redis `event_id`.
   - Change:
     `scripts/a9_control_api.py` adds read-only
     `/api/nodes/recovery-transcript`. It emits
     `a9.node_recovery_transcript.v1` rows with unified
     `source/phase/action/reason/status/node_id/flow_id/evidence_path/event_id`
     fields. Sources include node evidence, latest gateway reconnect decision,
     Redis task stream health, communication followup, and recovery-loop latest.
     Current state is judged from the newest followup/stream/loop signals, so
     historical repair evidence remains visible without keeping the node
     permanently in `needs_attention`.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py
     scripts/a9_supervisor.py scripts/a9_recovery_loop.py scripts/a9_remote.py`
     passed. `python3 -m unittest tests.test_control_api
     tests.test_recovery_loop tests.test_service tests.test_remote
     tests.test_node` passed with `250` tests. Real API smoke after stack
     restart returned `status=ok`, `conclusion=converging`,
     `current_action=continue`, and latest rows
     `heartbeat_repair_ok -> heartbeat_tmux_start_ok -> observe ->
     tasks_stream:none`. Mobile `npx tsc --noEmit` and
     `npm run smoke:mobile` passed after wiring the unified timeline.
   - Governance lesson:
     this is the first real cross-surface recovery transcript. Next useful
     slice is not another UI card; it is priority/model governance for the
     24h worker and then a transcript-backed intervention policy.

63. Worker model governance is now explicit and recorded.
   - Trigger:
     operator asked whether the system is truly 24h. Runtime was resident and
     queue-consuming, but model choice was still easy to misunderstand because
     previous Spark experiments had failed and the current worker command only
     implied the resolved model at process launch.
   - Mechanism copied:
     Codex-style runtime configuration must be explicit and observable. Aider
     style cost control should be policy-driven, not hidden by ad-hoc command
     changes. OpenClaw-style envelopes should preserve the policy snapshot used
     by each worker run.
   - Change:
     `scripts/a9_supervisor.py` now resolves worker model through a small
     policy function: `A9_SUPERVISOR_MODEL` overrides all tasks,
     `A9_SUPERVISOR_REFERENCE_MODEL` can override only `reference_scan`, and
     otherwise the stable `DEFAULT_WORKER_MODEL` remains `gpt-5.3-codex`.
     Worker outputs and policy attestations now record `worker_model` and
     `worker_model_source`; service progress exposes the latest worker model.
   - Verification:
     `python3 -m py_compile scripts/a9_supervisor.py scripts/a9_control_api.py`
     passed. Targeted model tests and `python3 -m unittest
     tests.test_supervisor tests.test_service` passed with `163` tests. The
     background stack stayed resident, and after test selftasks drained the
     controller reported `queued=0`, `running=0`.
   - Governance lesson:
     current A9 is a controlled 24h executor: it consumes queued work
     continuously, but local idle goal generation remains disabled to avoid
     unbounded token spend. Spark can be tested by setting
     `A9_SUPERVISOR_REFERENCE_MODEL=gpt-5.3-codex-spark` for low-risk
     reference scans, while implementation keeps the stable default.

64. Transcript-backed intervention policy was extracted and documented.
   - Trigger:
     entry 62 delivered unified recovery transcript rows, but intervention
     decisions still relied on monitor habit instead of a minimal typed policy.
   - Mechanism copied:
     Barter-rs action-domain boundaries (`connect/stream`,
     `Reconnect|Terminate|Continue`), Codex compact-as-handoff boundary,
     OpenClaw typed workflow envelope, and Redis Streams consumer-group health
     evidence.
   - Change:
     `docs/communication-governance-framework.md` now defines a minimal
     transcript-backed intervention policy with:
     `observe|watch|repair|intervene|quarantine` action ladder,
     required transcript input fields, and bounded machine output
     `{action, reason, evidence_refs}`.
   - Observation interval + reason + repair:
     policy keeps "observation window + typed reason + repair/intervention"
     semantics and does not add new token-number gates. It escalates by
     cross-surface conflict and apply-safety risk, not by prose heuristics.
   - Governance lesson:
     next implementation slice should consume this policy directly in control
     API followup generation, so intervention routing is transcript-native and
     reproducible from evidence references.

65. Recovery transcript now emits machine-readable intervention decision.
   - Trigger:
     entry 64 defined policy, but `/api/nodes/recovery-transcript` did not yet
     expose stable machine-readable intervention output.
   - Mechanism copied:
     reused A9 typed followup/stream-health action domain in
     `scripts/a9_control_api.py` and kept OpenClaw-style typed envelope shape
     (`action/reason/evidence_refs`) for deterministic routing.
   - Change:
     `scripts/a9_control_api.py` adds
     `transcript_intervention_decision(items, tasks_stream, followup, loop)`,
     normalizes actions to `observe|watch|repair|intervene|quarantine`, and
     publishes `intervention_decision` in
     `a9.node_recovery_transcript.v1` response.
     The implementation keeps "observation window + typed reason +
     repair/intervention" semantics and does not add token-number hard gates.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py` passed.
     `python3 -m unittest tests.test_control_api` passed with `178` tests.
     New coverage includes healthy -> `observe`, lag/pending pressure ->
     `watch|repair`, and unsafe terminal sequence conflict -> `quarantine`.
   - Governance lesson:
     intervention output is now transcript-native and evidence-referenced, so
     followup/recovery routing can be consumed by monitor/mobile without
     re-parsing mixed human text.

66. Followup now carries the same intervention decision boundary.
   - Trigger:
     entry 65 made transcript decisions machine-readable, but
     `communication_followup_intent()` still had a separate action surface.
     That risked transcript and followup telling monitor/mobile different
     intervention stories for the same evidence.
   - Mechanism copied:
     Barter-rs typed action domains, OpenClaw-style envelope payload,
     Codex compact/handoff evidence boundary, and Redis Streams typed health
     reasons.
   - Change:
     `communication_followup_intent()` now keeps its existing followup action
     domain stable and attaches
     `intervention_decision={action,reason,evidence_refs}` using
     `transcript_intervention_decision(...)`. `recovery_transcript()` prefers
     the embedded decision and recalculates only when it is missing or invalid.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py` passed.
     `python3 -m unittest tests.test_control_api` passed with `179` tests.
   - Governance lesson:
     this is a business-routing consistency fix, not token engineering. Token
     and context pressure remain observation signals unless a low-risk noise
     removal is obvious.

67. Supervisor deterministic apply now accepts strict envelope nested search/replace blocks.
   - Trigger:
     worker strict JSON envelope carried `output.search_replace_blocks` in
     nested shape (`file + blocks[]`), but supervisor only parsed flat
     `path+block`/`path+search+replace`, so apply was skipped.
   - Mechanism copied:
     Aider SEARCH/REPLACE deterministic patch discipline, OpenClaw typed
     envelope compatibility, and Codex deterministic handoff boundary between
     worker output and patch apply.
   - Change:
     `scripts/a9_supervisor.py` now normalizes both flat and nested
     `search_replace_blocks` into `model_patch.search_replace` text; malformed
     items are no longer silent and emit machine-readable findings with
     `code/scope/index/block_index`.
   - Verification:
     `python3 -m py_compile scripts/a9_supervisor.py` passed.
     `python3 -m unittest tests.test_supervisor` passed with `154` tests.
   - Governance lesson:
     this is execution-chain reliability repair, not token/context policy work;
     existing plain-text SEARCH/REPLACE compatibility is preserved.

68. Nested envelope SEARCH/REPLACE selftest.
   - Trigger:
     need a second end-to-end proof that deterministic apply accepts strict
     worker envelope nested `output.search_replace_blocks` and supervisor can
     auto-persist/govern without manual file edits.
   - Mechanism copied:
     Aider SEARCH/REPLACE anchor discipline, OpenClaw typed strict envelope,
     and Codex worker handoff/apply boundary.
   - Change:
     this log entry is delivered through strict result JSON nested
     `search_replace_blocks` (`file + blocks[]`) so supervisor deterministic
     apply path, check path, and git governance path are exercised together.
   - Verification:
     selftest run prepared with stable tail-anchor search and append-only
     replacement against `docs/communication-observation-log.md`.
   - Governance lesson:
     keep patch intent deterministic and typed at the worker boundary; do not
     mix this execution reliability check with token/context gate changes.

69. Node command receipt lookup now returns typed recovery diagnostics.
   - Trigger:
     node command submit could return "submitted" while receipt was missing or
     node heartbeat was stale, which left phone/control clients with no
     machine-readable next step.
   - Mechanism copied:
     OpenClaw/Lobster control-plane boundary (typed envelope for state/action),
     Barter-rs + Redis Streams typed status/receipt tracking, and Codex handoff
     rule (structured state instead of natural-language guess).
   - Change:
     `scripts/a9_control_api.py` adds `recovery_hint` on
     `enqueue_node_command`, `node_command_result_lookup`,
     `node_command_result_by_command_lookup`. Hint shape is
     `{action,reason,evidence_refs,next_endpoint}` and covers
     `redis_unavailable`, `command_result_found`, `result_missing/pending`,
     `heartbeat_stale/timeout`, and `node_unknown`.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py` passed.
     `python3 -m unittest tests.test_control_api` passed.
   - Governance lesson:
     receipt and recovery become the same typed control-plane contract, so
     mobile can drive `probe/wait/reconnect/tmux` routing without parsing free text.

70. Monitor transcript now consumes node command recovery hints as typed evidence.
   - Trigger:
     hint contract existed in node command lookup responses, but monitor/control
     transcript endpoints still required clients to infer next action from mixed
     followup prose and stream state.
   - Mechanism copied:
     OpenClaw/Lobster typed envelope boundary (`ok/status/output` style machine
     contract), Barter-rs reconnect lifecycle modeling (typed action/reason over
     prose), and existing A9 `recovery_transcript + intervention_decision`
     evidence linking.
   - Change:
     `scripts/a9_control_api.py` adds transcript-local hint ingestion helpers that
     normalize `node_command_recovery_hint()` into transcript items
     (`details.recovery_hint`) and merge hint `evidence_refs` into final
     `intervention_decision.evidence_refs`. `recovery_transcript` now emits hint
     items for `redis_unavailable` and node stale/missing-result recovery paths,
     and `controller_discovery.runtime` exposes
     `node_command_recovery_hint_contract=true`.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py` passed.
     `python3 -m unittest tests.test_control_api` passed.
   - Monitor intervention:
     the 24h worker implementation and tests were valid, but supervisor rolled
     the attempt back because the final envelope was not compliant. I manually
     applied the same bounded change to main and kept this as an execution
     discipline finding instead of blocking useful runtime progress.
   - Governance lesson:
     monitor contract should consume typed runtime evidence directly and route by
     explicit action/reason/evidence refs, not by natural-language interpretation.

71. HTTP control-plane contract test now proves typed recovery hint consumption.
   - Trigger:
     node command recovery hint contract was implemented in transcript/discovery,
     but HTTP `/api/nodes/recovery-transcript` needed a direct endpoint-level
     proof that mobile/remote clients can consume typed hint entries and
     `intervention_decision.evidence_refs` without parsing prose.
   - Mechanism copied:
     OpenClaw/Lobster typed control-plane boundary (HTTP machine-readable
     action/reason/evidence refs), Barter-rs reconnect lifecycle typed next
     action (no prose routing), and Codex handoff discipline (bounded evidence
     over raw log dumping).
   - Change:
     added HTTP-layer tests in `tests/test_control_api.py`:
     `test_api_recovery_transcript_endpoint_exposes_node_command_hint_contract`
     validates `/api/nodes/recovery-transcript?node_id=node-a&limit=20` returns
     `source=node_command_recovery_hint` items and
     `intervention_decision.evidence_refs` contains redis and node evidence
     refs; `test_api_discovery_endpoint_exposes_runtime_recovery_hint_flag`
     validates discovery runtime contract flag remains visible at HTTP endpoint.
   - Verification:
     `python3 -m unittest tests.test_control_api.ControlApiTests.test_api_recovery_transcript_endpoint_exposes_node_command_hint_contract`
     passed.
     `python3 -m unittest tests.test_control_api.ControlApiTests.test_api_discovery_endpoint_exposes_runtime_recovery_hint_flag`
     passed.
   - Governance lesson:
     previous worker envelope over-heaviness is kept as an observation item and
     should not be promoted into a new hard gate that blocks data-model-first
     delivery.

72. Queued communication handler now has discovery->transcript typed recovery contract proof.
   - Trigger:
     phone-control/queued handler path still lacked a single endpoint-chain proof
     that recovery action routing can start from `/api/discovery` and consume
     typed recovery transcript fields without prose parsing.
   - Mechanism copied:
     Codex handoff discipline (explicit action/scope/evidence contract),
     OpenClaw/Lobster workflow boundary (typed envelope consumption only), and
     Barter-rs recovery routing by state/action/reason/next endpoint.
   - Change:
     added `test_api_discovery_to_recovery_transcript_typed_contract_for_handler`
     in `tests/test_control_api.py`. The test first calls `/api/discovery`, then
     uses discovered `endpoints.node_recovery_transcript` to call
     `/api/nodes/recovery-transcript?node_id=node-a&limit=20`, and asserts typed
     contract payload: transcript includes `source=node_command_recovery_hint`
     with `details.recovery_hint`, and
     `intervention_decision.evidence_refs` contains redis and node evidence refs.
   - Verification:
     baseline related tests passed before patch apply:
     `python3 -m unittest tests.test_control_api.ControlApiTests.test_api_recovery_transcript_endpoint_exposes_node_command_hint_contract tests.test_control_api.ControlApiTests.test_api_discovery_endpoint_exposes_runtime_recovery_hint_flag`.
     run the new single test after apply:
     `python3 -m unittest tests.test_control_api.ControlApiTests.test_api_discovery_to_recovery_transcript_typed_contract_for_handler`.
   - Governance lesson:
     keep mobile/control entry as typed contract consumer; do not add new hard
     gate or token/line ceilings when data contract and recovery behavior are the
     acceptance target.

73. Node command lifecycle now has discovery->submit->by-command typed recovery routing proof.
   - Trigger:
     communication handler still lacked one minimal HTTP lifecycle proof that a
     client can start from discovery, submit a node command, and on missing
     result/stale node receive machine-routable recovery hints (`next_endpoint`).
   - Mechanism copied:
     Codex command/result handoff contract (`command_id + action/reason + evidence`),
     OpenClaw/Lobster typed control boundary (consumer reads typed envelope only),
     and Barter-rs/Redis recovery modeling for missing receipt and stale heartbeat.
   - Change:
     add endpoint-chain test
     `test_api_discovery_submit_and_by_command_missing_result_exposes_routable_recovery_hint`
     in `tests/test_control_api.py`:
     discover `node_command_submit`/`node_command_result_by_command`/`node_recovery_transcript`,
     submit `/api/nodes/command-submit`, then call
     `/api/node-command-results/by-command/{command_id}` with stale node context;
     assert typed `recovery_hint` and routable `next_endpoint` in
     `{ /api/nodes/probe, /api/node-command-results/by-command/{command_id} }`.
   - Verification:
     pre-checks passed:
     `python3 -m unittest tests.test_control_api.ControlApiTests.test_api_nodes_command_submit_writes_to_tasks_stream tests.test_control_api.ControlApiTests.test_api_node_command_results_by_command_endpoint_returns_lookup_payload tests.test_control_api.ControlApiTests.test_api_discovery_to_recovery_transcript_typed_contract_for_handler`.
     runtime script proof passed for the full chain (discovery=200, submit=ok,
     by-command=no_result with recovery_hint.next_endpoint routable).
   - Governance lesson:
     keep recovery orchestration in typed contract/action routing; do not move
     fallback logic into page parsing or prose heuristics.

74. Node command submit recovery_hint now encodes submitted/await_result instead of result_found.
   - Trigger:
     `/api/nodes/command-submit` success path returned
     `recovery_hint.reason=command_result_found` right after XADD enqueue, which
     mismatched actual lifecycle state and could misroute mobile/control clients.
   - Mechanism copied:
     Codex state naming discipline (`submitted` vs `result_found`),
     OpenClaw/Lobster typed envelope routing stability (`action/reason/next_endpoint`),
     and Redis Streams command lifecycle semantics (enqueue means queued/submitted,
     next step is by-command wait/observe).
   - Change:
     `enqueue_node_command` success now calls `node_command_recovery_hint` with
     `result_status=submitted`; `node_command_recovery_hint` maps
     `{submitted,queued} -> action=wait, reason=await_result,
     next_endpoint=/api/node-command-results/by-command/{command_id}`.
     Existing result lookup found path keeps `reason=command_result_found`.
     Added test assertions for submit success hints and preserved found semantics.
   - Verification:
     worker attempt produced the right patch idea but used absolute paths in
     `search_replace_blocks`, so supervisor rejected apply. Monitor intervention
     applied the bounded relative-path patch and ran targeted tests.
   - Governance lesson:
     recovery hint reasons are contract fields, not presentation text; lifecycle
     stages must not be conflated at submit boundary.

75. Node worker consume->result event->ack lifecycle now has control-plane by-command recovery proof.
   - Trigger:
     current contract had submit/by-command endpoint coverage, but lacked one
     minimal test proving real lifecycle evidence continuity:
     `command-submit fields -> worker work_once consume -> node_command_result
     event -> by-command lookup parse`.
   - Mechanism copied:
     Codex command handoff facts (`command_id/result_event_id/action/reason/evidence`),
     OpenClaw/Lobster typed worker/controller boundary, and Redis Streams
     lifecycle (`claim -> process -> XADD result -> XACK`).
   - Change:
     added
     `test_node_command_lifecycle_submit_worker_result_by_command_lookup` in
     `tests/test_node.py`. The test uses `enqueue_node_command` to build tasks
     stream fields, runs `node_command_work_once` to consume and emit
     `kind=node_command_result`, asserts `XACK` after result emit, then calls
     `node_command_result_by_command_lookup` to confirm by-command lookup
     resolves the same `command_id` result via typed parser path.
   - Verification:
     `python3 -m unittest tests.test_node.NodeHelperTests.test_node_command_lifecycle_submit_worker_result_by_command_lookup`
     and
     `python3 -m unittest tests.test_node.NodeHelperTests.test_node_command_work_once_supported_status_executes_and_acks tests.test_control_api.ControlApiTests.test_node_command_result_by_command_lookup_finds_latest_result`
     passed.
   - Next:
     run one real SSH/tmux node smoke: submit real command through
     `/api/nodes/command-submit`, execute `scripts/a9_node.py command-work-once`,
     then verify `/api/node-command-results/by-command/{command_id}` returns the
     emitted `result_event_id` and status.

76. Real Redis/API node-command smoke proved background node-worker consumes and result lookup is command-id based.
   - Trigger:
     after entry 75 added deterministic lifecycle tests, the next risk was real
     stack behavior with the long-running node worker, Redis consumer group, and
     HTTP control API all active.
   - Smoke:
     posted `/api/nodes/command-submit` with
     `command_id=smoke-real-work-once-20260601-0528`, `node_id=smoke-node`,
     `action=status`. Submit returned `status=ok`,
     `stream_id=1780291436594-0`, and
     `recovery_hint={action:wait, reason:await_result,
     next_endpoint:/api/node-command-results/by-command/smoke-real-work-once-20260601-0528}`.
   - Observation:
     a manual `scripts/a9_node.py --node-id smoke-node command-work-once`
     returned `noop/no_events` because the background worker had already claimed
     and processed the command. The by-command lookup returned
     `status=ok`, `result_event_id=1780291436648-0`,
     `claimed_id=1780291436594-0`, `node_id=DESKTOP-92A9ATS-0`, and
     `result.result=status_ok`.
   - Verification:
     `docker exec a9-redis redis-cli XPENDING a9:tasks a9-worker` returned `0`.
     `python3 scripts/a9_service.py ps` showed supervisor, node-worker,
     recovery-loop, and control-api still running.
   - Governance lesson:
     multi-consumer runtime must not assume the manually requested node is the
     consumer. Control UI and recovery routing must track `command_id`,
     `claimed_id`, and `result_event_id`, then render the actual consuming
     `node_id`. This matches Redis Streams consumer-group semantics and avoids
     fake certainty in mobile/operator views.

77. By-command recovery hint now prefers actual result node identity over requested submit target.
   - Trigger:
     in `node_command_result_by_command_lookup`, `recovery_hint` used
     `node_id or lookup.result.result.node_id`, which preferred request context
     when a caller passed `node_id`. In multi-consumer Redis Streams this can
     mask the actual consuming node observed in result events.
   - Mechanism copied:
     Redis Streams consumer-group fact model (claimed/result event node is source
     of execution truth), plus Codex/OpenClaw typed handoff separation between
     routing intent and execution fact.
   - Change:
     `scripts/a9_control_api.py` now computes `actual_node_id` from
     `lookup.result.result.node_id` and passes `actual_node_id or requested_node`
     into `node_command_recovery_hint`.
     Added regression test
     `test_node_command_result_by_command_lookup_prefers_actual_result_node_id_over_requested_node`
     in `tests/test_control_api.py` to prove by-command lookup preserves actual
     result node identity even when request uses a different submit target.
   - Verification:
     `python3 -m py_compile scripts/a9_node.py scripts/a9_control_api.py`
     and
     `python3 -m unittest tests.test_node tests.test_control_api`
     passed in the worker worktree before timeout rollback; monitor reapplied the
     bounded diff to main for final verification.
   - Next:
     extend control API payload contract with explicit
     `requested_node_id`/`result_node_id` top-level fields so UI can render
     intent vs fact without parsing nested result payloads.

78. By-command result payload now exposes requested vs actual node identity as top-level contract fields.
   - Trigger:
     entry 77 fixed `recovery_hint` semantics, but mobile/control consumers still
     had to parse nested result payloads to render routing intent (`node_id`
     request arg) versus execution fact (`node_command_result` event node_id).
   - Mechanism copied:
     Redis Streams multi-consumer fact model from entries 76-77: submitted
     `node_id` is routing intent; result-event `node_id` is execution fact.
     Keep typed contract explicit so clients do not infer semantics from nesting.
   - Change:
     `scripts/a9_control_api.py` now includes top-level
     `requested_node_id` (from by-command lookup `node_id` argument) and
     `result_node_id` (from parsed `lookup.result.result.node_id`) in
     `node_command_result_by_command_lookup` payloads. Nested `result` shape is
     unchanged.
     `tests/test_control_api.py` extends
     `test_node_command_result_by_command_lookup_finds_latest_result` and
     `test_node_command_result_by_command_lookup_prefers_actual_result_node_id_over_requested_node`
     to assert the explicit intent-vs-fact fields and preserved recovery hint behavior.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py`;
     `python3 -m unittest tests.test_control_api.ControlApiTests.test_node_command_result_by_command_lookup_prefers_actual_result_node_id_over_requested_node tests.test_control_api.ControlApiTests.test_node_command_result_by_command_lookup_finds_latest_result`;
     `python3 -m unittest tests.test_control_api`.
   - Governance lesson:
     control-plane contracts should expose intent-vs-fact explicitly at top level
     to reduce UI ambiguity and prevent nested-field coupling across clients.

79. Remote bootstrap/status contract now separates SSH setup from Redis/API runtime and exposes routable recovery actions.
   - Trigger:
     after local node-command lifecycle worked, the next multi-machine risk was
     ambiguity between SSH/Tailscale/tmux bootstrap and the real runtime channel.
     Remote machines should be reached by SSH for install/repair/tmux takeover,
     while normal work and heartbeat flow through controller API and Redis
     Streams.
   - Mechanism copied:
     existing A9 remote recovery lessons from entries 31-58, the production
     daemon split in `docs/production-daemon.md`, and the local Hermes
     daemon-style separation observed in
     `reference-projects/hermes-agent/tui_gateway/event_publisher.py`.
   - Change:
     remote bootstrap config and `/api/nodes/bootstrap-plan` now expose
     `bootstrap_mode=ssh_bootstrap_only`, `runtime_mode=redis_api_runtime`,
     heartbeat script path, heartbeat tmux session, and controller heartbeat
     endpoint. Bootstrap execution persists the same `runtime_contract` into
     its evidence payload.
     `node_command_recovery_hint` now prefers actionable `node_recovery_plan`
     routes when available and includes `next_method`, `next_command`, and
     `next_requires_arm`, so clients can route stale/tmux/repair cases without
     prose parsing.
   - Verification:
     run `python3 -m py_compile scripts/a9_remote.py scripts/a9_control_api.py`
     and `python3 -m unittest tests.test_remote tests.test_control_api`.
   - Governance lesson:
     remote control contracts must separate install transport from runtime
     transport. SSH is bootstrap/repair/takeover; Redis/API is the steady-state
     control plane.

80. Local controller clients now bypass environment proxies for control-plane calls.
   - Trigger:
     after restarting the control API, direct API checks returned HTTP 502 even
     though no local controller error was logged. The machine had
     `HTTP_PROXY=http://127.0.0.1:7890`, and Python `urllib` did not reliably
     honor the wildcard-style `no_proxy=127.*` value for `127.0.0.1:8787`.
   - Mechanism copied:
     production gateway/client practice: localhost control-plane calls should
     use an explicit direct transport instead of ambient proxy settings.
   - Change:
     `scripts/a9_node.py` and `scripts/a9_recovery_loop.py` now use a
     `ProxyHandler({})` opener for controller HTTP requests. Added regression
     tests proving local controller calls still succeed when `HTTP_PROXY` points
     at a dead local proxy and `NO_PROXY` is empty.
   - Verification:
     `python3 -m py_compile scripts/a9_node.py scripts/a9_recovery_loop.py scripts/a9_control_api.py`;
     `python3 -m unittest tests.test_recovery_loop tests.test_node`.
   - Governance lesson:
     communication stability should remove hidden ambient dependencies first.
     Proxy bypass is not a hard gate; it is a deterministic transport invariant
     for local A9 control loops.

81. Local service helper now has a detached start path for the A9 control stack.
   - Trigger:
     during recovery from the proxy issue, manual `nohup ... &` launches from
     the current tool shell did not reliably keep `control-api`, `node-worker`,
     and `recovery-loop` alive. The stable processes were those detached under
     the parent service/session.
   - Mechanism copied:
     systemd-style daemon separation already documented in `infra/systemd/*`:
     one stable entrypoint owns each long-running service, with logs written to
     service-specific files.
   - Change:
     `scripts/a9_service.py start` now starts the local control stack through
     `setsid -f`, with `--dry-run`, `--only`, and `--all` modes. The default
     non-systemd start set is `control-api`, `node-worker`, and `recovery-loop`;
     supervisor can be included with `--all` when needed.
   - Verification:
     `python3 scripts/a9_service.py start --dry-run --only control-api recovery-loop`;
     `python3 -m py_compile scripts/a9_service.py scripts/a9_node.py scripts/a9_recovery_loop.py scripts/a9_control_api.py`;
     `python3 -m unittest tests.test_service tests.test_recovery_loop tests.test_node tests.test_control_api`.
   - Governance lesson:
     phone/control reliability needs a single operational start contract. Manual
     shell incantations are acceptable for diagnosis, not for the repeated 24h
     runtime path.

82. Service start now reports post-launch observed state with bounded retry and typed failure routing.
   - Trigger:
     `scripts/a9_service.py start` previously returned `status=started` right
     after spawn, but it did not prove the target process entered running state.
     This made start/readiness evidence ambiguous in monitor-blocked repair
     loops.
   - Mechanism copied:
     systemd readiness intent from `infra/systemd/a9-supervisor.service` and
     peers: start and active state are distinct, and restart/repair decisions
     require observed runtime state instead of launch intent alone.
   - Change:
     `start` now records `start_contract` (`verify_attempt_budget`,
     `verify_sleep_seconds`, `verify_timeout_seconds`, `failure_taxonomy`) and
     per-service `command_status` with phase transitions:
     `planned|already_running|running|start_timeout`. For timeout, it emits
     `failure_kind=timeout` and `recovery_action=retry`, aligned with typed
     recovery routing.
   - Verification:
     `python3 -m unittest tests.test_service.ServiceTests.test_service_start_dry_run_returns_detached_commands tests.test_service.ServiceTests.test_start_cmd_sets_running_status_after_verify tests.test_service.ServiceTests.test_start_cmd_timeout_maps_to_retry_action`.
   - Governance lesson:
     data-first service contracts should expose observed state transitions and
     failure taxonomy explicitly before adding stricter start gates.

83. Monitor salvaged the service-start contract after worker test drift.
   - Trigger:
     the worker produced the right service-start contract shape, but full
     `tests.test_service` failed because its dry-run assertion assumed
     `phase=planned`. In a live controller session the correct observed phase is
     `already_running`.
   - Intervention:
     monitor applied the useful worker patch, changed the dry-run test to accept
     the real observed phase set (`planned` or `already_running`), strengthened
     the mocked running-state assertion, and reran the declared and broader
     related checks.
   - Verification:
     `python3 -m py_compile scripts/a9_service.py`;
     `python3 -m unittest tests.test_service`;
     `python3 -m unittest tests.test_service tests.test_recovery_loop tests.test_node tests.test_control_api`;
     live `scripts/a9_service.py start --dry-run --only control-api recovery-loop`
     now reports `command_status.phase=already_running` for active services.
   - Governance lesson:
     tests for operational state must model real live-state branches. A worker
     can build the mechanism, but monitor must reject tests that only pass in an
     artificial stopped environment.

84. `/api/status` now exposes service intent vs observed process state for phone-side supervision.
   - Trigger:
     mobile control currently needs SSH + manual `ps` to answer whether
     `control-api`/`node-worker`/`recovery-loop`/`supervisor` are actually
     running. This violates data-first communication governance.
   - Mechanism copied:
     `scripts/a9_service.py` start contract split:
     service start intent is separate from observed runtime state, with typed
     follow-up action (`observe` vs `start_missing_services`).
   - Change:
     `scripts/a9_control_api.py` `supervisor_status()` now includes
     `service_observation`:
     `intent.services[]` (unit path + start intent) and
     `observed.services[]` (`observed_running`, `process_count`,
     `observation_status`, `next_action`, `observed_processes`), plus
     `missing_services`, `missing_count`, and top-level observed `next_action`.
     Probe is bounded `ps -eo pid,ppid,etime,cmd` only; no blocking gate added.
   - Verification:
     `python3 -m unittest tests/test_control_api.py`.
   - Governance lesson:
     control-plane API should publish runtime truth directly. Phone is an
     observer/dispatcher adapter; canonical state remains process evidence.

85. Mobile control now renders A9 service observation before operator history.
   - Trigger:
     `/api/status` exposed `service_observation`, but the phone UI still only
     showed node/recovery/runtime cards. Also, compact mode auto-scrolled to the
     latest operator turns, pushing the remote control surface out of the first
     viewport.
   - Change:
     `/mnt/d/root/a9_mobile_agent_lab/store/useA9ControlStore.ts` now types
     `service_observation`. `/mnt/d/root/a9_mobile_agent_lab/app/(tabs)/agent.tsx`
     renders an `A9 services` card showing each service's observed phase, pid,
     uptime, missing count, and next action. In mobile compact mode the remote
     control card and service observation render before operator history, and
     compact mode no longer auto-scrolls to the bottom on content changes.
   - Verification:
     in `/mnt/d/root/a9_mobile_agent_lab`, `npx tsc --noEmit` and
     `npm run smoke:mobile` passed.
   - Governance lesson:
     the phone is a control surface, not just a chat transcript. Runtime control
     and service truth must be first-viewport signals on mobile.

86. Control API adds gated `services.start` action with real `a9_service.py` start evidence.
   - Trigger:
     phone-side `/api/status` can already detect `missing_services`, but could
     not trigger a bounded service start from control API.
   - Mechanism copied:
     `scripts/a9_service.py` start contract:
     start intent command + short verify budget + observed running state +
     typed timeout recovery (`failure_kind`, `recovery_action`).
   - Change:
     `scripts/a9_control_api.py` adds `service_start_action()` and
     `POST /api/services/start`, gated by existing phone-control soft gate
     (`operator.admin` + `command_gate("services.start")`). The action calls
     `python3 scripts/a9_service.py start --only ...` for missing services and
     returns parsed helper JSON as `start_result`, including
     `command_status/observed_running/failure_kind/recovery_action`, plus
     before/after `service_observation`.
   - Verification:
     `python3 -m unittest tests.test_control_api.ControlApiTests.test_service_start_action_requires_runtime_gate tests.test_control_api.ControlApiTests.test_service_start_action_runs_helper_and_returns_start_json tests.test_control_api.ControlApiTests.test_api_services_start_route_calls_handler`.
   - Governance lesson:
     use existing soft gate semantics for remote control mutations; keep action
     runtime bounded and return raw service evidence instead of inferred labels.

87. Mobile service card can now trigger gated missing-service recovery.
   - Trigger:
     `/api/services/start` existed, but the phone card was still observation-only.
     That meant a remote operator could see a missing service yet still needed
     SSH or shell access to perform the first recovery action.
   - Mechanism copied:
     the existing phone-control runtime group and service start contract are
     reused instead of adding a separate mobile approval model. The phone sends
     `operator.admin`, the control API checks `command_gate("services.start")`,
     and `a9_service.py` remains the deterministic starter.
   - Change:
     `/mnt/d/root/a9_mobile_agent_lab/store/useA9ControlStore.ts` adds
     `A9ServiceStartResult` and `startMissingServices()`. The mobile A9 services
     card in `/mnt/d/root/a9_mobile_agent_lab/app/(tabs)/agent.tsx` now renders
     a `Start missing` action when `missing_count > 0`, sends only the observed
     missing service list, and shows the last start status/reason on the card.
     Healthy services stay read-only with `All services observed`.
   - Verification:
     in `/mnt/d/root/a9_mobile_agent_lab`, `npx tsc --noEmit` and
     `npm run smoke:mobile` passed. Live A9 service process observation still
     reports `control-api`, `node-worker`, `recovery-loop`, and `supervisor`
     running.
   - Governance lesson:
     phone control should close the smallest useful loop: observe canonical
     service truth, trigger the bounded deterministic recovery action, then
     reread canonical truth. It should not become its own service manager.

88. Control API now exposes a unified communication status read model.
   - Trigger:
     node health, Redis tasks stream lag, Tailscale state, service process
     observation, and recovery-loop transcript were readable, but clients and
     workers had to stitch them together themselves. That makes phone control
     and 24-hour worker intervention fragile.
   - Mechanism copied:
     Barter-rs-style typed lifecycle decisions and A9's existing
     `communication_followup` pattern: each layer emits a bounded action, then
     the read model picks the highest-priority action without performing the
     mutation.
   - Change:
     `scripts/a9_control_api.py` adds `communication_status()` and
     `GET /api/communication/status`. The payload includes candidates from
     `tailscale`, `services`, `nodes`, `tasks_stream`, and `recovery_loop`, the selected
     `action/reason/priority_source`, plus raw `layers` for evidence. Discovery
     now advertises the endpoint as `communication_status`.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py`;
     `python3 -m unittest tests.test_control_api` passed with 196 tests.
     After restarting control-api, live `GET /api/discovery` returned
     `/api/communication/status`, and live `GET /api/communication/status`
     returned `status=ok`, `action=continue`, `priority_source=tailscale`, with
     candidate sources `tailscale/services/nodes/tasks_stream/recovery_loop`.
   - Governance lesson:
     communication stability needs one canonical read model before adding more
     buttons or recovery automations. The model observes and ranks; mutations
     remain behind existing gated endpoints.

89. Mobile control now consumes the unified communication status.
   - Trigger:
     `/api/communication/status` was available, but phone control still showed
     separate service/node/Tailscale cards without the ranked top-level action.
   - Change:
     `/mnt/d/root/a9_mobile_agent_lab/store/useA9ControlStore.ts` now fetches
     `GET /api/communication/status` during refresh and stores
     `communicationStatus`. `/mnt/d/root/a9_mobile_agent_lab/app/(tabs)/agent.tsx`
     renders a first-viewport `Communication` card before remote control,
     showing `action`, `reason`, selected `priority_source`, and each candidate
     layer action. `/mnt/d/root/a9_mobile_agent_lab/scripts/mobile-ui-smoke.js`
     now asserts the card is visible.
   - Verification:
     in `/mnt/d/root/a9_mobile_agent_lab`, `npx tsc --noEmit` passed. Expo web
     was restarted on port `8199`, then `npm run smoke:mobile` passed with the
     new `a9-communication-status-card` assertion.
   - Governance lesson:
     the phone should read the same canonical communication decision as the
     worker. Layer-specific cards stay useful, but the operator needs the
     highest-priority action first.

90. Communication status now has deterministic action routing.
   - Trigger:
     `/api/communication/status` exposed the ranked action, but operators and
     the 24-hour worker still needed to know which existing endpoint should
     handle that action.
   - Change:
     `scripts/a9_control_api.py` adds `communication_action_plan()` with
     `GET /api/communication/action-plan`, and `communication_repair_one()` with
     `POST /api/communication/repair-one`. The plan maps
     `services/start_missing_services` to `/api/services/start` under the
     `runtime` arm group, maps node/recovery-loop `reconnect/intervene` actions
     to `/api/nodes/recovery-cycle` under the `remote` arm group, maps
     tasks-stream watch/intervene to `/api/gateway/health-refresh`, and marks
     Tailscale install/login/reconnect as manual-required. The repair endpoint
     dispatches only through these existing bounded endpoints.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py`;
     `python3 -m unittest tests.test_control_api` passed with 200 tests.
     After restarting control-api, live `GET /api/communication/action-plan`
     returned `plan_status=noop` for healthy communication, and live
     `POST /api/communication/repair-one` returned `status=noop` instead of
     performing an unnecessary mutation.
   - Governance lesson:
     routing belongs between observation and mutation. The phone and worker can
     share the same plan, while the actual effects remain behind the existing
     phone-control gates.

91. Mobile control now shows communication action plan and repair-one entry.
   - Trigger:
     the backend could produce a deterministic communication action plan, but
     the phone still displayed only the observed status.
   - Change:
     `/mnt/d/root/a9_mobile_agent_lab/store/useA9ControlStore.ts` now fetches
     `GET /api/communication/action-plan` during refresh and adds
     `repairCommunicationOne()` for `POST /api/communication/repair-one`.
     `/mnt/d/root/a9_mobile_agent_lab/app/(tabs)/agent.tsx` extends the
     `Communication` card with `Arm <group>` and `Repair one` controls, route
     evidence, last repair status, and a loading placeholder so slow status
     reads do not remove the first-viewport control surface.
   - Verification:
     in `/mnt/d/root/a9_mobile_agent_lab`, `npx tsc --noEmit` passed. Expo web
     was restarted on port `8199`; `npm run smoke:mobile` passed. Live backend
     checks returned `GET /api/communication/action-plan -> plan_status=noop`
     and `POST /api/communication/repair-one -> status=noop` in the healthy
     current state.
   - Governance lesson:
     the phone is now a dispatcher for the same route plan the worker sees. It
     still does not invent recovery logic; it arms the required group and calls
     the bounded backend repair endpoint.

92. Recovery loop now records the unified communication action plan.
   - Trigger:
     the always-on recovery loop only observed `/api/nodes/recovery-cycle`.
     That missed the new canonical communication plan for service recovery,
     Tailscale/manual states, Redis stream health, and gateway refresh.
   - Change:
     `scripts/a9_recovery_loop.py` now reads
     `/api/communication/action-plan` before `/api/nodes/recovery-cycle` on
     each planning iteration, and writes `communication_plan_status`,
     `communication_action`, `communication_priority_source`,
     `communication_route`, and the raw plan into
     `.a9/services/recovery-loop-latest.json`. It remains planning-only; no
     mutation is executed by the loop.
   - Verification:
     `python3 -m py_compile scripts/a9_recovery_loop.py`;
     `python3 -m unittest tests.test_recovery_loop` passed. A live one-shot
     recovery loop wrote `communication_plan_status=noop`,
     `communication_action=continue`, `communication_priority_source=tailscale`.
     The resident `recovery-loop` service was restarted so future background
     observations use the new code.
   - Governance lesson:
     24-hour monitoring and phone control now share the same route-plan
     evidence. The loop observes the plan continuously; execution remains a
     separate gated action.

93. Recovery loop now keeps an observe-only communication action streak.
   - Trigger:
     before enabling any automatic `repair-one`, A9 needs evidence that an
     unhealthy communication action is stable across observations. A single
     transient status must not trigger automation.
   - Change:
     `scripts/a9_recovery_loop.py` now writes
     `.a9/services/communication-observation.json` on every iteration. The file
     records `current_key = priority_source:action:plan_status`, `streak`,
     `first_seen_at`, `last_seen_at`, `recommendation`, `route`, and
     `auto_execute=false`. Healthy/noop states keep
     `recommendation=continue_observation`; repeated non-healthy ready states
     become `candidate_for_repair_one`, but still do not execute.
   - Verification:
     `python3 -m py_compile scripts/a9_recovery_loop.py`;
     `python3 -m unittest tests.test_control_api tests.test_recovery_loop`
     passed with 204 tests. A live two-iteration run wrote
     `current_key=tailscale:continue:noop`, `streak=2`,
     `recommendation=continue_observation`, `auto_execute=false`. The resident
     `recovery-loop` service was restarted onto the new code.
   - Governance lesson:
     thresholds are evidence, not hard gates. The loop now builds a stable
     observation trail before any future auto-repair policy is considered.

94. Communication observation streak is now visible through API and mobile.
   - Trigger:
     `.a9/services/communication-observation.json` existed, but operators and
     phone control could not see the streak/recommendation without shell access.
   - Change:
     `scripts/a9_control_api.py` now includes
     `communication_plan_status`, `communication_action`,
     `communication_priority_source`, `communication_route`, and
     `communication_observation` in `GET /api/nodes/recovery-loop/latest`.
     `/mnt/d/root/a9_mobile_agent_lab/store/useA9ControlStore.ts` types these
     fields, and `/mnt/d/root/a9_mobile_agent_lab/app/(tabs)/agent.tsx` renders
     the observation key, streak, recommendation, `auto_execute`, and route in
     the recovery card. Mobile smoke now asserts
     `a9-communication-observation` when the recovery detail card is present.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py scripts/a9_recovery_loop.py`;
     `python3 -m unittest tests.test_control_api tests.test_recovery_loop`
     passed with 205 tests. Live `GET /api/nodes/recovery-loop/latest` returned
     `observation_key=tailscale:continue:noop`, `streak=8`,
     `recommendation=continue_observation`, `auto_execute=false`. In the mobile
     project, `npx tsc --noEmit` and `npm run smoke:mobile` passed.
   - Governance lesson:
     observe-only policy is now inspectable from the same control surface that
     can later execute repair. This keeps automation pressure visible before it
     becomes action.

95. Candidate communication repairs now have a read-only suggestion queue.
   - Trigger:
     `candidate_for_repair_one` was visible as a streak recommendation, but
     there was no bounded queue object for phone, worker, or monitor review.
   - Change:
     `scripts/a9_recovery_loop.py` writes
     `.a9/services/communication-repair-suggestions.json` on every observation.
     Healthy/currently non-candidate states clear pending suggestions while
     preserving `last_observation`; candidate states write a pending suggestion
     with `suggestion_id`, route, streak, evidence refs, operator action, and
     `auto_execute=false`. `scripts/a9_control_api.py` exposes this through
     `GET /api/communication/repair-suggestions` and embeds it inside
     `GET /api/nodes/recovery-loop/latest`. The mobile recovery card now shows
     suggestion count and first suggestion id when present.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py scripts/a9_recovery_loop.py`;
     `python3 -m unittest tests.test_control_api tests.test_recovery_loop`
     passed with 207 tests. Live API returned `pending_count=0` for the current
     healthy `tailscale:continue:noop` state, with `auto_execute=false`.
     In the mobile project, `npx tsc --noEmit` and `npm run smoke:mobile`
     passed.
   - Governance lesson:
     this is the handoff point between observation and action. A9 can now
     accumulate repair pressure as reviewable evidence without crossing into
     automatic mutation.

96. Communication suggestion review is an async sidecar, not part of the hot path.
   - Trigger:
     operators need to approve, ignore, or resolve communication repair
     suggestions from phone control, but review/audit must not slow down the
     main communication status path or turn observation into execution.
   - Change:
     `scripts/a9_control_api.py` now exposes
     `POST /api/communication/repair-suggestions/review`. It requires phone
     admin scope, moves the selected pending suggestion into `approved` or
     `closed`, preserves `auto_execute=false`, and enqueues the audit write on
     a daemon thread. `GET /api/communication/repair-suggestions` returns
     pending, approved, and closed lists. The mobile recovery card now exposes
     `Approve`, `Ignore`, and `Resolve` controls for the first pending
     suggestion; these controls only review the suggestion and refresh state.
   - Verification:
     `python3 -m py_compile scripts/a9_control_api.py`;
     `python3 -m unittest tests.test_control_api tests.test_recovery_loop`
     passed with 209 tests. Live no-admin review was rejected; live admin
     review for a missing suggestion returned `status=not_found` with
     `audit_async=true`. In the mobile project, `npx tsc --noEmit` and
     `npm run smoke:mobile` passed, including the three suggestion review
     controls.
   - Governance lesson:
     audit and evaluation are sidecar paths. They produce evidence and
     operator state, but the fast communication read/repair path remains
     bounded and does not wait on audit I/O.

97. Mobile monitor control now closes the pause/resume intervention loop.
   - Trigger:
     phone control could show runtime, node, and recovery state, but it could
     not yet operate the typed monitor-intervention contract exposed by
     `/api/monitor/control`. A stale control-api process also proved that a
     running service is not enough; the process must be restarted onto the
     current code before mobile can consume new contracts.
   - Change:
     `/mnt/d/root/a9_mobile_agent_lab/store/useA9ControlStore.ts` now reads
     `GET /api/monitor/control` during refresh and exposes
     `submitMonitorIntervention(action, reason)`. The Agent tab renders a
     `MonitorControlCard` showing `next_action`, runtime pause state, latest
     run, queue counts, failed checks, token pressure, recent interventions,
     and action buttons for arm runtime, pause/resume, repair, and
     route-to-debate. The mobile smoke script now waits for
     `domcontentloaded` instead of `networkidle` and asserts
     `a9-monitor-control-card`; Expo dev mode keeps connections open and made
     `networkidle` a false failure.
   - Verification:
     `npx tsc --noEmit` passed in `/mnt/d/root/a9_mobile_agent_lab`.
     `npm run smoke:mobile` passed after adding the monitor card assertion.
     The current `/root/a9` control API was restarted in tmux as
     `a9-control-api`, and the mobile web service was restarted in tmux as
     `a9-mobile-agent-lab`. Live API smoke returned
     `schema=a9.monitor_control.v1`.
   - Live closed-loop evidence:
     phone-control was armed for the `runtime` group, then
     `POST /api/monitor/intervention` recorded `pause` and `resume` actions.
     `STATUS_AFTER_PAUSE` showed `runtime_control.paused=true`;
     `STATUS_AFTER_RESUME` showed `runtime_control.paused=false`.
     Both events were written to `.a9/monitor/interventions.jsonl` and mirrored
     to Redis stream `a9:monitor:interventions` with ids
     `1780579059834-0` and `1780579061515-0`. The smoke arm was then disarmed,
     and `GET /api/phone-control/status` returned `armed=false`.
   - Governance lesson:
     mobile is now a real monitor control plane, not a passive status page.
     Execution is still gated by short-lived phone-control arm, while
     observation, audit, and Redis replay stay available for recovery and
     later evaluator/worker consumption.

98. Repair intervention exposed missing task-shape decision closure.
   - Trigger:
     a live `repair` monitor intervention was submitted for a
     `monitor-blocked` run after the mobile control loop was wired. The
     intervention gate passed, audit and Redis mirror worked, and supervisor
     queued an `operator-repair-*` task, but the worker returned a
     `change_request` instead of repairing. The generated task packet lacked
     `decision_status`, so the worker method packet routed it to
     `debate_next`.
   - Change:
     `scripts/a9_supervisor.py` now adds `decision_status: decided`,
     bounded `problem`, `system_requirement`, `out_of_scope`, and
     `allowed_execution` lines to monitor repair tasks. `route_to_debate`
     remains intentionally undecided. The repair queue task now enters
     `execution_next` while still staying bounded to the supplied evidence
     refs and deterministic SEARCH/REPLACE output.
   - Verification:
     `python3 -m py_compile scripts/a9_supervisor.py` passed.
     Targeted tests passed:
     `test_monitor_intervention_repair_enqueues_repair_task_with_evidence`,
     `test_run_worker_event_budget_enforce_ignores_non_json_stdout_for_budget_accounting`,
     `test_worker_event_budget_defaults_to_observation_not_kill`, and
     `test_run_worker_real_subprocess_non_json_stdout_lines_are_ignored_by_event_counters`.
     Full `python3 -m unittest tests.test_supervisor` passed with 328 tests.
     Live API shape validation stopped supervisor-loop, armed runtime,
     submitted repair, confirmed the queued task contained
     `decision_status: decided` and `allowed_execution:`, removed that
     validation-only queue task to avoid model spend, disarmed phone-control,
     and restarted supervisor-loop.
   - Extra repair:
     the full supervisor suite initially failed a pre-existing event-budget
     case because enforce mode killed a subprocess that had already naturally
     finished after emitting the over-budget JSON event. `run_worker` now
     checks `proc.poll()` before killing on event-count or event-byte budget
     enforcement, preserving `return_code=0` for already-completed workers
     while still killing long-running over-budget workers.
   - Governance lesson:
     monitor repair is an execution command, not a new requirements debate.
     If the task-shaping packet is not closed, the 24-hour machine will obey
     governance correctly but make no progress. This is the right failure
     mode, and the fix belongs in task formation, not in weakening gates.

99. Worker transport exhaustion now releases the 24-hour running slot quickly.
   - Trigger:
     after repair task shaping was fixed, a real monitor repair smoke queued a
     correctly decided `operator-repair-*` task. The worker entered
     `execution_next`, but nested Codex emitted `Reconnecting... 5/5 (timeout
     waiting for child process to exit)` and stderr reported `failed to refresh
     available models: timeout waiting for child process to exit`. The task
     shape was no longer the problem; the worker transport could hold the
     running slot until the broader idle timeout.
   - Change:
     `scripts/a9_supervisor.py` now detects transport-exhausted worker events
     in both the JSON event stream and the stderr side channel, stops the
     subprocess with a short grace period, and returns `transport_stopped` /
     `transport_reason`. Worker failure classification reports
     `retryable-worker-transport` with category `transport`, separate from
     token/event budget and command-boundary governance. The same short grace
     helper is used for event-budget enforce stops so workers that already
     naturally exited are not misreported as killed.
   - Verification:
     `python3 -m py_compile scripts/a9_supervisor.py` passed. Targeted tests
     passed for transport-exhausted event stop, transport-exhausted stderr
     stop, event-budget enforce accounting, and monitor repair task shaping.
     Full `python3 -m unittest tests.test_supervisor` passed with 330 tests.
   - Governance lesson:
     this is transport failure governance, not a new quality gate. The worker
     should not be allowed to block 24-hour execution after the underlying
     Codex transport has already declared reconnect exhaustion. The right
     action is to preserve evidence, classify the failure as retryable
     transport, and let the monitor/supervisor continue repair or model-policy
     decisions.

100. Worker model routing is now phase-aware instead of one global bet.
   - Trigger:
     the transport-exhaustion repair proved that model availability and
     stability are runtime facts. Earlier evidence also conflicted over the
     right default: stable `gpt-5.3-codex` was preferred for unattended work,
     but the current ChatGPT-backed Codex account reported it unsupported,
     while Spark can run but has startup/tool/transport instability.
   - Change:
     `scripts/a9_supervisor.py::resolved_worker_model()` now supports layered
     routing. `A9_SUPERVISOR_MODEL` remains the global override. A
     phase-specific variable such as `A9_SUPERVISOR_PHASE_MODEL_REPAIR`
     overrides one phase. `A9_SUPERVISOR_CRITICAL_MODEL` applies to `repair`
     and `test` only. `A9_SUPERVISOR_REFERENCE_MODEL` remains limited to
     `reference_scan`. If none are set, the current default model is unchanged.
   - Verification:
     targeted model-routing tests cover global override, phase-specific repair
     override, critical repair/test override, reference-scan override, and
     default fallback.
   - Governance lesson:
     model choice should be a control-plane policy, not a hardcoded ideology.
     Cheap-model optimization is useful for observation/reference work, but
     repair/test reliability must be switchable without editing code or
     changing the whole worker fleet.

101. Monitor control now exposes the effective worker model policy.
   - Trigger:
     phase-aware routing only helps operators if the current control plane can
     show what will actually happen. Without visibility, a phone/operator
     monitor could see `repair` as the next action but not know whether repair
     will run on the cheap default, a critical override, or a phase-specific
     override.
   - Change:
     `GET /api/monitor/control` now includes `worker_model_policy` with the
     global override env, critical-model env, reference-model env, phase-model
     env prefix, configured env values, and resolved model/source/disabled
     features for each copy-pipeline phase. The API reuses supervisor
     `resolved_worker_model()` and `worker_disabled_features_for_model()` so
     the displayed policy matches worker command construction.
   - Verification:
     targeted control-api tests cover monitor-control aggregation and
     supervisor-backed phase override resolution. Full
     `python3 -m unittest tests.test_control_api tests.test_supervisor` passed
     with 597 tests.
   - Governance lesson:
     model policy is part of runtime observability. The monitor should not have
     to infer model routing from old docs, stale session memory, or command
     scrollback.

102. Real 24-hour smoke exposed orphaned-interruption visibility.
   - Trigger:
     a live queued record task was consumed by `a9-supervisor-loop`. The first
     run used the default Spark model and failed before reasoning with
     `retryable-worker-transport`; the new transport exhaustion handling made
     this visible quickly with zero token usage. A retry with
     `A9_SUPERVISOR_PHASE_MODEL_RECORD=gpt-5.5` avoided the Spark model policy
     path but the nested Node/Codex process crashed during startup/teardown
     before producing a final worker summary.
   - Change:
     orphaned running-task reconciliation now writes a minimal `summary.json`,
     `state.json`, and `evidence.jsonl` beside `orphaned_interruption.json`.
     The summary uses `retryable-worker-interrupted` and
     `worker_failure.category=interrupted`, so monitor/control surfaces can see
     the latest failed run instead of silently showing an older summary.
     Supervisor model routing also has a persistent
     `.a9/runtime/worker_model_policy.json`; when the default worker model hits
     `retryable-worker-transport`, `schedule_next_task()` writes a phase-level
     fallback model and queues an `auto-retry-model-fallback-*` task with the
     same scope and declared checks. Worker subprocesses now start in their own
     process group and timeout/transport/budget stops kill the whole group, so
     native Codex children do not remain after the wrapper process exits.
   - Verification:
     targeted supervisor tests cover summary/state/evidence creation during
     orphaned running-task reconciliation, persistent phase model policy
     resolution, automatic fallback retry task creation, and process-group
     startup for worker subprocesses.
   - Governance lesson:
     automatic execution is blocked less by business logic now and more by
     runtime failure observability. Every lease-ending path must leave a
     monitor-visible summary, even when the worker crashes before emitting
     events or final output.

103. Worker transport is now a control-plane policy, not only a Codex exec assumption.
   - Trigger:
     the live fallback smoke proved that changing worker model is not enough.
     The default Spark path failed with `retryable-worker-transport`, and the
     `gpt-5.5` phase fallback still hit Codex exec model-refresh/child-process
     transport instability before doing useful work. That means A9 needs a
     worker transport seam before it can claim stable 24-hour execution.
   - Change:
     `scripts/a9_supervisor.py` now has persistent
     `.a9/runtime/worker_transport_policy.json`. The default backend remains
     `codex_exec`; `custom_command` can be selected by persistent policy or
     env (`A9_SUPERVISOR_WORKER_CMD` / `A9_SUPERVISOR_WORKER_TRANSPORT_BACKEND`
     plus `A9_SUPERVISOR_WORKER_CMD_TEMPLATE`). Worker runs now record
     `worker_transport`, `worker_transport_backend`, and
     `worker_transport_source`. `GET /api/monitor/control` exposes
     `worker_transport_policy`, so phone/control surfaces can see whether A9 is
     still on Codex exec or has switched to a custom/remote worker.
   - Verification:
     full `python3 -m unittest tests.test_supervisor tests.test_control_api`
     passed with 600 tests. The running control API returned
     `worker_transport_policy.resolved.backend=codex_exec`, queue `0`, running
     `0`.
   - Governance lesson:
     A9 should keep using Codex first when it works, but the runtime must not
     be trapped behind one CLI transport. OpenHands/aider/remote self-hosted
     workers can now plug in through a deterministic transport policy instead
     of requiring supervisor rewrites.

104. Worker transport policy is now operator-controlled through the runtime gate.
   - Trigger:
     exposing `worker_transport_policy` was not enough for phone/control use.
     If switching from Codex exec to a backup worker requires SSH edits or hand
     editing `.a9/runtime/worker_transport_policy.json`, the mobile operator
     still cannot recover the 24-hour loop cleanly during a transport incident.
   - Change:
     `POST /api/worker/transport-policy` updates the persistent worker
     transport policy, but only after `phone-control` arms the `runtime` group.
     The new registered command is `worker.transport.update`. The endpoint
     records `before`, `after`, resolved policy, and an async audit event. It
     validates backend values and requires a custom command template before
     allowing `custom_command`.
   - Verification:
     `python3 -m unittest tests.test_control_api` passed with 270 tests.
     A live blocked smoke against `http://127.0.0.1:8787/api/worker/transport-policy`
     returned `phone_control_disarmed`, and `/api/monitor/control` still showed
     `worker_transport_policy.resolved.backend=codex_exec`, queue `0`, running
     `0`.
   - Governance lesson:
     switching worker backends is a runtime control action, not a background
     implementation detail. It should be available to the monitor/phone control
     plane, but only through the same arm/audit path as other high-impact
     runtime changes.

105. Custom worker transport has a real non-Codex smoke path.
   - Trigger:
     policy and API controls still did not prove that A9 could finish a worker
     run without Codex exec. The live blocker was transport startup, so the next
     proof had to run through supervisor `run-one`, not only unit tests.
   - Change:
     added `scripts/a9_local_envelope_worker.py`, a deterministic local worker
     that reads the bounded prompt, extracts the Task Declared Checks section,
     writes a strict worker envelope to `final.md`, and emits compact JSONL
     lifecycle events. It does not pretend to be an LLM and does not edit files;
     its job is to prove the transport/envelope/check/summary path.
   - Verification:
     targeted supervisor tests cover the local worker through
     `A9_SUPERVISOR_WORKER_CMD`. A first live smoke failed because the custom
     command used a relative script path and worker cwd is the isolated
     worktree. A second live smoke with absolute script path passed:
     `local-envelope-worker-smoke-abs-20260605`, run
     `.a9/runs/local-envelope-worker-smoke-abs-20260605-20260605T061553Z-a1`,
     `worker_transport_backend=custom_command`, `worker_envelope=pass`, declared
     check return code `0`.
   - Governance lesson:
     custom transport is real now, but command templates are execution
     contracts. They must account for cwd, path visibility, final output path,
     and declared checks. The next backend can be LLM-capable, but it should
     keep the same strict envelope boundary.

106. OpenAI-compatible custom worker exists as the first LLM-capable backup backend.
   - Trigger:
     the local envelope worker proved A9 can bypass Codex exec, but it was
     deterministic and not capable of doing agent work. The next useful backup
     must speak a standard model-serving protocol so it can point at OpenAI,
     vLLM, SGLang, NIM, or an internal model gateway.
   - Change:
     added `scripts/a9_openai_compatible_worker.py`. It reads the supervisor
     bounded prompt, extracts declared checks, calls an OpenAI-compatible
     `/chat/completions` endpoint with a strict-envelope system instruction,
     validates that the model response contains an A9 worker envelope, and
     writes that envelope to `final.md`. It uses only the Python standard
     library. Required configuration is `A9_LLM_WORKER_API_KEY` or
     `OPENAI_API_KEY`, plus `A9_LLM_WORKER_MODEL` or `--model`; base URL can be
     changed with `A9_LLM_WORKER_BASE_URL` or `--base-url`.
   - Verification:
     `python3 -m unittest tests.test_openai_compatible_worker` passed. A CLI
     missing-key smoke returned code `70` and still wrote a strict error
     envelope, so configuration failures are visible to supervisor artifacts.
   - Governance lesson:
     the backup path should use the same A9 strict envelope as Codex/custom
     workers. Model providers are replaceable; the durable interface is prompt
     in, envelope out, deterministic apply/check/governance after that.

107. Worker transport presets make the LLM backup selectable from the control plane.
   - Trigger:
     `a9_openai_compatible_worker.py` was usable from shell, but phone/mobile
     control should not have to hand-compose fragile shell templates. The
     operator needs discoverable presets and a guarded apply path.
   - Change:
     `GET /api/worker/transport-presets` now exposes `codex_exec`,
     `local_envelope_smoke`, and `openai_compatible`. The OpenAI-compatible
     preset uses an absolute script path and keeps `{prompt_file}`,
     `{final_path}`, `{task_id}`, and `{phase}` for supervisor expansion.
     `POST /api/worker/transport-policy` now accepts
     `preset=openai_compatible` and writes the generated custom command through
     the existing runtime arm/audit gate.
   - Verification:
     targeted control-api tests cover preset discovery, preset application, GET
     route handling, and controller discovery. A live GET returned all three
     presets; a live unarmed `preset=openai_compatible` update returned
     `phone_control_disarmed`; `/api/monitor/control` still showed
     `transport=codex_exec`, queue `0`, running `0`.
   - Governance lesson:
     the mobile control plane should select named, reviewed transport presets
     rather than accepting ad hoc shell strings as the normal operator path.
     Raw custom templates remain available for engineering, but product control
     should prefer presets.

108. OpenAI-compatible worker configuration is now checkable before switching transport.
   - Trigger:
     adding an `openai_compatible` preset made it easy to switch the worker
     backend, but switching before confirming key/model/base URL would just move
     failure from Codex exec startup to model-gateway configuration.
   - Change:
     added `POST /api/worker/transport-check`. By default it performs a
     non-mutating configuration check for the selected preset and reports
     missing `A9_LLM_WORKER_API_KEY`/`OPENAI_API_KEY`, model, base URL, and
     timeout. If `execute=true`, it is treated as a runtime action and requires
     `phone-control` arm for `worker.transport.check`; this keeps live probes
     behind the same operator gate as transport updates.
   - Verification:
     targeted control-api tests cover not-configured, ready, execute blocked,
     execute armed, POST routing, and discovery. A live check in the current
     environment returned `not_configured` with missing key/model. A live
     `execute=true` request returned `phone_control_disarmed`. Queue remained
     `0`, running `0`, transport `codex_exec`.
   - Governance lesson:
     configuration visibility should be cheap and safe, but active probes that
     may call a model endpoint are runtime actions. This gives the mobile
     operator a preflight step before switching the 24-hour worker fleet.

109. Mobile control now surfaces worker transport presets and preflight state.
   - Trigger:
     transport presets and preflight checks existed in the control API, but the
     phone operator still could not see whether the 24-hour worker was on
     Codex exec, whether the OpenAI-compatible backup was configured, or which
     guarded action would switch presets.
   - Change:
     updated `/mnt/d/root/a9_mobile_agent_lab` to load
     `/api/worker/transport-presets` and `/api/worker/transport-check` during
     refresh. The Agent tab now includes a Worker transport card below Monitor
     control. It displays current backend/source, OpenAI-compatible preflight
     status, missing key/model details, and buttons for Check, Arm runtime,
     Apply OpenAI, Smoke worker, and Back to Codex. The card uses the existing
     phone-control/runtime gate rather than a separate permission path.
   - Verification:
     `npx tsc --noEmit` passed in the mobile project. `npm run smoke:mobile`
     passed after restarting Expo with `--offline` because Expo dependency
     validation attempted an external fetch. The smoke now asserts the worker
     transport card and key buttons.
   - Governance lesson:
     worker backend switching is now visible where the operator actually
     controls the system. The mobile page should show readiness and missing
     configuration before asking the operator to arm and mutate runtime state.

110. Controlled 24-hour loop smoke proved the supervisor loop, and exposed two governance edges.
   - Trigger:
     the main line needed a real answer to whether the 24-hour worker loop can
     run unattended instead of only being manually driven through `run-one`.
   - Change:
     armed runtime, switched worker transport to `local_envelope_smoke`, and
     enqueued three no-edit strict-envelope smoke tasks:
     `controlled-24h-loop-smoke-20260605-1`,
     `controlled-24h-loop-smoke-20260605-2`, and
     `controlled-24h-loop-smoke-20260605-3`. The existing
     `a9-supervisor-loop` tmux session consumed them automatically.
   - Verification:
     all three controlled tasks passed with `worker_transport_backend=custom_command`
     and declared check `rc=0`. The loop then generated and ran one
     `auto-reference_scan` follow-up, which also passed. Queue returned to
     `queued=0`, `running=0`. Runtime was resumed, phone-control was disarmed,
     and worker transport was restored to `codex_exec`.
   - Findings:
     the loop is alive for controlled tasks, but `--auto-next` can expand after
     a smoke task unless the task or loop has a clear goal boundary. Deep-mark
     RedisJSON writes were also visible as a latency point after worker
     completion. The first restore to `codex_exec` left the old local smoke
     command template in policy state; `update_worker_transport_policy` now
     treats preset values as authoritative even when the preset template is an
     empty string.
   - Verification after repair:
     live `/api/monitor/control` shows `transport.backend=codex_exec`,
     `custom_command_template=""`, queue `0`, running `0`, runtime `running`,
     and phone-control `disarmed`. Regression coverage:
     `test_update_worker_transport_policy_codex_preset_clears_custom_template`.
   - Governance lesson:
     24-hour mode is not just "keep running". It needs bounded task expansion,
     visible transport readiness, and fast side-path persistence so observation
     does not become the bottleneck.

111. Auto-next now has a task-level stop boundary for bounded smokes and operator slices.
   - Trigger:
     the controlled loop smoke proved that `run-loop --auto-next` can continue
     automatically, but it also showed that smoke tasks can still expand into a
     follow-up `auto-reference_scan` when the worker emits a valid next slice.
   - Change:
     task frontmatter now supports `auto_next: false` and the enqueue CLI
     supports `--no-auto-next`. `parse_task` carries this into
     `Task.auto_next_allowed`, and `schedule_next_task` records
     `auto_next_block.reason=task_auto_next_disabled` instead of enqueuing a
     follow-up. Normal tasks keep `auto_next: true` by default, so active goals
     and phase-prefixed continuation still work.
   - Verification:
     targeted supervisor tests passed for frontmatter parsing, task-level
     auto-next blocking, and existing positive auto-next behavior. Full
     `python3 -m unittest tests.test_supervisor` passed with 334 tests after
     stopping the live supervisor loop during the suite.
   - Runtime observation:
     the first full test run failed because the live `a9-supervisor-loop`
     consumed a temporary `selftest` auto-next queue file before the test could
     read it. The queue/running selftest artifacts were cleaned, and the suite
     passed after isolating tests from the daemon.
   - Governance lesson:
     long-running A9 services and repository tests share the same runtime
     queue. Production loop validation is good, but full test suites need daemon
     isolation or a dedicated test queue namespace.

112. Requirements debate is now a first-class runtime stage, not just a document rule.
   - Trigger:
     the operator corrected the direction: A9's 24-hour flow is not only
     execution. The intended flow is automated requirements debate/review/decision
     first, then execution backlog generation and continuous worker execution.
   - Change:
     `plan.json` now carries a `requirements_debate` state, and
     `requirements_debate_progress()` derives the current open stage from the
     active plan contract. The stages follow the requirements-analysis guide:
     demand audit, preparation/reference scan, system requirement translation,
     data/state/exception modeling, and acceptance/backlog shaping.
   - Runtime command:
     added `python3 scripts/a9_supervisor.py plan-debate-next`. It reads the
     active plan, picks the current debate stage, and enqueues a bounded
     `decision_status: not_decided` / `route: debate_next` task with
     `auto_next: false`. The task is analysis work only: it may append findings,
     progress, and change requests, and it may draft execution_next slices, but
     it may not implement production code.
   - Verification:
     targeted tests passed for debate progress exposure and debate task
     generation. Full `python3 -m unittest tests.test_supervisor` passed with
     336 tests. A live smoke generated and then removed
     `live-debate-next-smoke-20260605`; the active plan currently reports
     `requirements_debate_status=ready_for_execution_backlog`, so the generated
     debate task targets execution backlog shaping rather than production code.
   - Governance lesson:
     the hard part is automating the 70%-80% requirements communication/debate
     work. This commit is the first runtime hook for that lane; it does not yet
     auto-generate thousands of execution_next tasks.

113. Ready requirements can now generate bounded execution_next backlog tasks.
   - Trigger:
     after `plan-debate-next`, the next missing runtime step was converting a
     plan whose requirements debate is ready into concrete worker tasks instead
     of asking the worker to invent execution scope from chat context.
   - Change:
     added `python3 scripts/a9_supervisor.py plan-backlog-next`. It requires
     `requirements_debate_status=ready_for_execution_backlog`, then generates a
     deterministic execution pipeline: `reference_scan`, `mechanism_extract`,
     `implement`, `test`, and `record`. Each task carries
     `decision_status: decided`, `route: execution_next`, the plan contract,
     and task frontmatter `allowed_paths` extracted from `allowed_execution`.
   - Verification:
     targeted tests passed for not-ready plans and ready backlog generation.
     Full `python3 -m unittest tests.test_supervisor` passed with 338 tests. A
     live smoke generated two `live-smoke-exec-*` tasks from
     `a9-plan-lane-runtime`, verified their decided packet and allowed paths,
     then removed them without running workers.
   - Governance lesson:
     this is the first mechanical bridge from requirements debate into worker
     execution. It is intentionally deterministic and small; future work should
     let debate outputs append richer candidate backlog slices before generating
     large task batches.

114. Structured execution backlog can now persist in the plan before queueing.
   - Trigger:
     the default five-phase backlog was only a fallback. The real 24h workflow
     needs requirements debate to decide concrete execution slices first, persist
     them, and let the supervisor enqueue only those decided slices.
   - Change:
     added `execution_backlog.items` to plan payloads plus
     `python3 scripts/a9_supervisor.py plan-backlog-add`. `plan-backlog-next`
     now prefers structured plan backlog items, wraps each slice with the
     decided plan contract, enqueues it as `route: execution_next`, then writes
     `status=queued`, `queued_task_id`, `queued_task_path`, and
     `generated_task_ids` back to the plan. If structured backlog exists but no
     item is ready, the supervisor stops instead of falling back to generic
     phases.
   - Verification:
     targeted tests covered backlog add, queue generation, status writeback, and
     repeat-run no-op behavior. Full `python3 -m unittest tests.test_supervisor`
     passed with 339 tests. A live smoke added one structured backlog item to
     the active plan, generated one `live-structured-smoke-*` task, verified the
     path, then removed the smoke task and plan residue.
   - Governance lesson:
     this fixes a real drift risk discovered by testing: after all structured
     items were queued, the older fallback would have generated generic work.
     For the mainline, decided backlog must override defaults; fallback is only
     for plans that have not yet adopted structured execution backlog.

115. Debate worker final output can now append structured execution backlog.
   - Trigger:
     `plan-backlog-add` proved the storage model, but the 24h requirements
     debate lane still needed an automatic bridge from a debate worker's final
     decision artifact into durable `execution_backlog.items`.
   - Change:
     `plan-debate-next` now asks workers to include one JSON object shaped as
     `{"execution_backlog":{"items":[...]}}` when proposing execution slices.
     `update_active_plan_from_run()` now only for `route: debate_next` parses
     the worker final artifact, extracts backlog items, de-duplicates them by
     title/phase/prompt, and appends ready items to the active plan with
     `source=debate_final_json` and `source_run`.
   - Verification:
     targeted tests cover automatic append from a debate final and refusal to
     mutate backlog from an `execution_next` final. Full
     `python3 -m unittest tests.test_supervisor` passed with 341 tests. A live
     smoke created a temporary debate final JSON, confirmed one ready backlog
     item appeared in `a9-plan-lane-runtime`, then restored the active plan and
     removed the smoke run directory.
   - Governance lesson:
     this is a narrow bridge, not free-form self-evolution. Requirements debate
     may propose execution backlog, but only via a machine-readable final
     artifact and only on the debate route; execution workers cannot mutate the
     backlog by mentioning future work.
