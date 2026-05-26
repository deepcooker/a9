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

- Finish the current managed-flow negative auto-next test, then return to the
  five communication blocks: node state machine, Redis Streams production
  governance, multi-machine onboarding, SSE replay, and communication
  metrics/soak.
