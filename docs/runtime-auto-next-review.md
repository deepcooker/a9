# A9 Runtime Auto-Next Governance Review

Date: 2026-06-02

## Review Question

Did A9 complete enough review to let the 24h worker continue automatically?

Answer: partially.

What was completed is a focused engineering review of `auto-next` governance:
worker continuation, strict envelope behavior, supervisor-declared checks, and
operator handoff blocking.

What was not completed is the larger product/requirements debate for
communication runtime, multi-machine access, mobile control, or full Agent OS
shape. Those areas still require requirements modeling and role review before
execution.

## Current Boundary

This review covers only:

- `auto-next` scheduling behavior.
- Worker strict-output contract.
- Supervisor-declared check authority.
- Operator handoff stopping conditions.
- Observation-first process governance for broad reads, undeclared checks, and
  event drift.

This review does not approve:

- new communication-runtime implementation;
- SSH/Tailscale/tmux/Redis multi-node architecture implementation;
- mobile UI/product expansion;
- hard numeric token/line gates;
- fully autonomous execution from vague recommendations.

## Evidence Reviewed

Recent commits:

- `e67b9b4 docs: record unprefixed auto-next validation`
- `68d7397 a9 supervisor: require phase-prefixed auto-next slices`
- `4922d22 a9 supervisor: block operator handoff auto-next slices`
- `3f3e9ef a9 supervisor: clarify outer declared check execution`
- `9e45fdd a9 supervisor: separate worker and supervisor check reporting`
- `52db6fa docs: record heredoc drift validation observation`
- `adf8705 a9 supervisor: observe python heredoc validation drift`
- `6a2e89f docs: record no-diff test pass observation`
- `e2281e6 a9 supervisor: let test phase pass without diffs`
- `e60f45c a9 supervisor: clarify strict envelope JSON contract`
- `b2804bc a9 supervisor: compact decision routing for test tasks`
- `4509121 docs: record exact command planning drift`

Key run evidence:

- `010-verify-exact-evidence-plan-commands`: exposed command abbreviation and
  undeclared-check drift.
- `011-verify-compact-test-decision-route`: fixed compact test routing conflict;
  exposed Markdown-in-JSON envelope failure.
- `013-verify-test-no-diff-pass-status`: proved pure test phase can pass without
  a diff; exposed ad-hoc Python validation blind spot.
- `014-verify-heredoc-validation-drift-observation`: proved heredoc detector
  through supervisor checks and showed worker/supervisor check self-report
  ambiguity.
- `015-verify-worker-supervisor-check-reporting`: proved nested supervisor
  command blocking after ambiguous wording caused a `run-one` attempt.
- `016-verify-outer-check-execution-wording`: worker obeyed outer-supervisor
  wording and separated worker commands from supervisor checks.
- `auto-reference_scan-016-verify-outer-check-execution-wording`: noisy failure
  sample; handoff-style recommendation became a costly auto reference scan.
- `018-live-unprefixed-next-recommended-task-fixed`: proved unprefixed
  `next_recommended_task` is preserved as evidence but blocked from enqueue.

Primary detailed log:

- `docs/agent-runtime-observations.md`

## What Is Proven

- A pure `test` phase may pass without repository diffs when declared checks,
  process governance, and strict worker output are acceptable.
- Compact `test` and `repair` tasks no longer need a full production decision
  packet; production `implement` still does.
- Python heredoc validation with assertion markers is observable as undeclared
  check drift.
- Worker self-report can be separated into `worker_commands_run` and
  `supervisor_declared_checks`.
- Workers are explicitly told not to run nested supervisor/worker loops, and
  command-bound governance blocks nested `a9_supervisor.py run-one`.
- Handoff-style recommendations stop for monitor review.
- Unprefixed `next_recommended_task` no longer schedules a new task.
- Automatic continuation now requires an explicit phase prefix such as
  `reference_scan:`, `mechanism_extract:`, `implement:`, `test:`, `repair:`, or
  `record:`.

## What Is Not Proven

- Long-soak stability with many real model runs.
- Stable communication runtime over SSH/Tailscale/tmux/Redis.
- Multi-machine discovery, reconnect, replay, and repair behavior.
- Mobile control as a true operator entrypoint.
- Full MoE-style role review on the communication architecture.
- Whether the worker can consistently obey deterministic SEARCH/REPLACE output
  without monitor salvage.
- Token cost under diverse tasks. We have evidence of high token waste, but not
  a mature architecture-level cost solution.

## Role Review

Product / Mainline:

- Pass with condition.
- The new rule restores monitor authority: vague worker recommendations cannot
  silently become new work.
- Condition: do not mistake this for approval of the next product area.
  Communication runtime still needs requirements modeling first.

Requirements:

- Partial pass.
- The engineering loop was validated before a full requirements debate. That is
  a process mistake.
- Future large slices must start with problem, data contract, state flow,
  exception flow, acceptance, out-of-scope, and role disagreement.

Architecture:

- Pass for this scope.
- Phase-prefixed continuation is a clear deterministic boundary.
- Run summaries, queue/running directories, and `auto_next_block` evidence
  remain the authority; progress views are only views.

Test / Data:

- Partial pass.
- Focused tests and fake-worker validation prove the failure class that caused
  the noisy reference scan is blocked.
- This is not a full live-model soak test.

Cost / Token:

- Partial pass.
- The high-cost `auto-reference_scan` run proves the cost failure mode.
- The fix addresses that exact cause.
- Broader cost control must come from task shaping, bounded evidence plans,
  context indexing, smaller source slices, and better architecture, not fixed
  numeric gates.

Runtime Governance:

- Pass.
- Nested supervisor execution, handoff continuation, unprefixed auto-next, and
  ambiguous check ownership are now visible and controlled.

## Decisions

D1. Auto-next may execute only explicit phase-prefixed next slices.

D2. `next_recommended_task` without a phase prefix is evidence only. It is not
executable backlog.

D3. Operator handoff language must stop for monitor review.

D4. Worker must not invoke nested supervisor, nested worker, or nested Codex
loops. The outer A9 supervisor owns declared-check execution.

D5. Worker output should separate worker-run commands from supervisor-declared
checks. Missing fields remain warn-only at this stage.

D6. Process warnings remain observation-first unless they violate authority,
license, security, scope, declared checks, or deterministic apply facts.

D7. No hard numeric token/line gate is approved from this review. Cost is a
design problem first, not a magic threshold problem.

## Rejected For Now

- Page/TUI monitoring as the core architecture.
- Fully autonomous continuation from vague text.
- Hard line-count or token-count blocking as the main quality mechanism.
- Letting a worker self-promote undeclared checks into active task checks.
- Moving into communication implementation before a communication decision
  packet.
- Calling the current state "24h production ready."

## Next Allowed Work

Next work should be a communication-runtime decision packet, not code.

Required next packet:

- Problem: stable multi-terminal/multi-server control for A9 operator and
  worker runtime.
- Data model: node, ssh identity, tailscale identity, tmux session, command,
  stream cursor, result, heartbeat, reconnect state, repair action, audit event.
- State flow: discover -> connect -> attach -> execute -> stream -> ack ->
  reconnect -> replay -> repair -> audit.
- Exception flow: network loss, SSH failure, tmux detach, Redis stream pending
  stuck, stale command, duplicate result, mobile disconnection, service restart.
- References to scan first: Codex event/session loop, OpenClaw/Lobster workflow,
  Redis Streams patterns, tmux control-mode practices, mature SSH gateway
  patterns, Barter-style typed recovery.
- Acceptance: no implementation until role review says the model, states,
  route authority, and recovery semantics are clear enough.

## Progress Statement

Auto-next governance slice: about 85% complete for MVP use.

Why not 100%:

- no long-running real-model soak;
- strict envelope reliability still needs observation;
- worker direct file-change behavior still appears;
- cost behavior is improved for one failure class, not solved globally.

24h service overall: still MVP.

Communication/multi-machine runtime: not approved for coding yet. It needs a
decision packet and role review first.

## Final Verdict

Auto-next governance is accepted for current-stage MVP use under monitor
supervision.

The next correct move is not to keep coding random communication features. The
next correct move is to produce the communication-runtime decision packet, run
role debate against it, remove stale/noisy context, and only then enqueue a
phase-prefixed execution slice for the 24h worker.
