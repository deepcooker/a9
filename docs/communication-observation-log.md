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
