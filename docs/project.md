# A9 Project Current State

This is the active project index. It is intentionally small.

## Current Identity

A9 is currently a private 24-hour agent execution/control foundation.

It is not:

- the final financial/quant model
- A3B/A?B itself
- a mobile UI project
- a trading engine implementation
- a page-monitor workaround

Current runtime role:

```text
supervisor + control API + worker orchestration
+ SSH/Tailscale/tmux/private node connectivity
+ Redis/MySQL state and evidence lanes
+ git worktree/check/guard/governance
+ MemPalace-first session/memory/context governance
+ monitor intervention and recovery
```

## A9 / A3B Boundary

`/root/a9/a3b_moe_cognition` is a separate A3B/A?B meta-cognitive activation
system and is outside A9 runtime default write scope.

A9 provides structured context and execution evidence:

- goals, boundaries, data/state shape, allowed tools, checks and evidence refs
- tool traces, test reports, diffs, failure summaries, wrongbook candidates

A3B may provide intent, mainline, methodology, candidate paths and risk
judgment. A9 turns those into plan/backlog/worker prompts and still governs
execution through queue, worktree, checks, git and monitor.

Interface shape:

```text
A3B -> A9: mainline, execution_goal, methodology, required_data,
allowed_tools, forbidden_actions, success_criteria, risk_boundary.

A9 -> A3B: evidence_pack, tool_trace, test_report, diff_summary,
failure_summary, cost_report, wrongbook_candidate, next_suggestion.
```

## Current Priority

```text
P0 requirements/ADR closure for 24h worker + monitor + communication foundation
P1 24h worker + monitor reliability
P2 communication foundation and private node connectivity
P3 A9 core contracts supporting P1/P2
P4 reference/vendor baseline for P1/P2
P5 mobile/control product packet, UI details frozen
P6 compute stage A
P7 NZX technical MVP
```

## Current Stable Facts

- `scripts/a9_supervisor.py` owns queue, run-loop, auto-next, worktree, checks,
  guards, evidence, session mini-flow and managed-flow integration.
- Active runtime closure follows the two-lane model: external/operator session
  closure lane (`session_refresh` -> `session_close_reading` -> causal commit)
  and requirements-debate-to-execution backlog lane.
- Default workers do not treat raw session as a direct truth source. Raw
  session is evidence for session lanes only and is intentionally bounded.
- Closure state is recorded in the five-doc packet plus active plan evidence;
  stale one-off closure docs are intentionally out-of-scope.
- `scripts/a9_control_api.py` exposes control/mobile-facing status and command
  surfaces.
- `scripts/a9_session_refresh.py` is legacy bounded extraction and snapshot
  fallback for external Codex/operator sessions.
- `scripts/a9_codex_session_adapter.py` converts Codex raw JSONL into
  MemPalace-compatible per-message drawer records without treating recall as
  truth. Large operator sessions must use the incremental path: initialize the
  cursor from the existing drawer once with `init-cursor`, then run
  `incremental` to append only new JSONL rows. Do not run full `convert --out`
  over the 100MB+ operator session unless intentionally rebuilding the drawer.
- `scripts/a9_mempalace_provider.py` exposes the runtime-facing MemPalace
  facade: status, source-preserving search, wakeup and official-style recall
  packets. Native MemPalace is the primary recall path; drawer JSONL remains
  deterministic fallback evidence.
- `scripts/a9_supervisor.py` injects bounded MemPalace recall protocol evidence
  into worker context: search hits, hydrated drawer snippets and fallback raw
  evidence refs stay separated. Recall is a recovery hint, not task authority.
- `scripts/a9_runtime_thread_view.py` is now the first A9 runtime projection
  layer. It reads existing A9 `summary.json` + `event_summaries.jsonl` evidence
  plus sidecar indexes such as MemPalace cursor and service pid files, then
  emits `a9.runtime_projection.v1`: `threads`, `turns`, `items`,
  `active_runs`, `operator_commands`, `worker_tasks`, `profile_role_lanes`,
  `memory_packets`, `approvals`, `handoffs` and `remote_hosts`. Empty arrays
  are intentional placeholders until their evidence sources are wired. This is
  projection-only; it does not replace supervisor, managed flow, MemPalace or
  future gateway work.
- Control API now exposes this projection to mobile/monitor surfaces:
  `/api/status` includes a compact `runtime_projection` summary without forcing
  a rebuild, `/api/runtime/projection` can return compact or full projection
  and optionally refresh it, and `/api/runtime/operator-commands` tails the
  append-only operator command ledger. Monitor interventions now also append to
  `.a9/runtime/operator_commands.jsonl`, so human/mobile control actions can
  join the same projection as worker runs.
- OpenClaw-style active-run operator actions have a first control API cut:
  `/api/runtime/active-run-command` accepts `status`, `cancel`, `steer` and
  `followup`. `status` is a projection-backed observation. Mutating actions are
  phone-control gated and now create an append-only active-run delivery outbox
  entry in `.a9/runtime/active_run_delivery_queue.jsonl`, with queue outcome,
  expiry and delivery evidence. `/api/runtime/active-run-delivery-queue` tails
  this outbox and `/api/runtime/active-run-delivery-cleanup` archives stale
  queued commands. `/api/runtime/active-run-delivery-consume` consumes queued
  rows and writes immutable results to
  `.a9/runtime/active_run_delivery_results.jsonl`. Current mutating commands
  use a configurable active-run transport contract at
  `.a9/runtime/active_run_transport.json`. Supported first adapters are
  `codex_app_server_jsonrpc` (`turn/steer`, `turn/interrupt`) and
  `hermes_session_jsonrpc` (`session.steer`). If no adapter is enabled, consume
  writes explicit `active_run_transport_disabled` proof instead of fake
  delivery.
- A local Codex app-server validation instance now runs on
  `ws://127.0.0.1:8791` with capability-token auth and is managed by
  `scripts/a9_service.py` as `codex-app-server`. A9's transport probe performs
  the real Codex WebSocket `initialize -> initialized -> model/list` handshake
  and currently passes. A controlled Codex mock-provider trial also proved real
  `turn/start -> turn/steer` delivery through A9's transport helper without
  consuming model quota. Important finding: Codex active turn steering is
  connection/subscription sensitive. Short WebSocket calls are fine for probe
  and stateless reads, but reliable active-turn steering needs a connection-aware
  client or relay that keeps the app-server connection for the active run.
  Current projection has no real active run from the operator window yet, so
  production `turn/steer` is still gated on exposing a live
  `thread_id/current_turn_id` and adding the relay.
- `scripts/a9_active_run_relay.py` is the first active-run relay/owner. It can
  start or attach to one Codex active turn, keep the same app-server WebSocket
  connection open, write relay state under
  `.a9/runtime/active_run_relays/*.json`, consume matching active-run delivery
  queue rows, and deliver `turn/steer` through the owned connection. A controlled
  mock-provider smoke proved queue -> relay -> Codex `turn/steer` without
  model quota burn. Control API exposes relay state at
  `/api/runtime/active-run-relays`, and runtime projection indexes relay states
  as `active_runs`. Control API can now start a relay through
  `/api/runtime/active-run-relay/start` under the runtime phone-control gate;
  prompts are written to a private prompt file instead of leaking through
  process argv. A second controlled API smoke proved
  phone-control arm -> relay start -> active-run-command steer -> relay consume
  -> Codex `turn/steer`. Relay stop and cleanup are now exposed through
  `/api/runtime/active-run-relay/stop` and
  `/api/runtime/active-run-relay/cleanup`: stop records operator stop evidence
  in relay state, and cleanup removes stopped/old state, prompt and log files
  only when `commit=true`. Production worker turns can now start through
  `/api/runtime/active-run-relay-worker/start`: the endpoint resolves a bounded
  `.a9/tasks` task or explicit prompt, wraps it with A9 execution doctrine,
  starts a relay-owned Codex turn, and writes binding evidence under
  `.a9/runtime/active_run_relay_bindings/*.json`. Cleanup also removes matching
  or orphan binding files. A controlled mock-provider smoke proved task prompt
  -> relay-owned `turn/start` -> active-run-command steer -> relay-delivered
  `turn/steer` without model quota burn. `plan.backlog.next` can now take
  `dispatch=relay_worker`: it still uses the decided plan/backlog path, then
  atomically moves the first queued task into the relay-owned lane before
  starting the relay worker, so the old supervisor queue cannot double-claim
  it. If relay start fails, the task is moved back to queue. The next gap is
  automatic completion parsing from relay-owned Codex output. The first
  deterministic ingest path now exists at
  `/api/runtime/active-run-relay/ingest`: it reads relay state, binding and
  delivery results, writes `.a9/runs/<run>/summary.json`, and can move the
  running task into `.a9/tasks/done`. Because Codex active-run final output is
  not yet parsed into a strict worker envelope, stopped relays default to
  `needs-repair` instead of fake `pass`. The relay now also preserves
  non-response Codex WebSocket notifications into
  `.a9/runtime/active_run_relays/*.events.jsonl`; ingest extracts final text
  from those relay events and parses strict worker envelopes. A valid envelope
  without outer A9 checks upgrades the run only to `needs-followup` by default,
  not `pass`, unless the operator explicitly trusts the envelope. Ingest now
  also runs the task frontmatter declared checks in the A9 root; `pass` requires
  both a valid worker envelope and passing declared checks. Failed checks become
  `needs-repair`. A real relay-owned Codex smoke exposed one critical false-pass
  risk: the first event parser accepted worker-envelope JSON embedded in the
  user prompt. Ingest now only extracts final text from Codex assistant output
  events (`item/agentMessage/delta` or completed `agentMessage` /
  `assistantMessage`). The second real smoke
  `relay-worker-relay-e2e-smoke-002-2026-06-23T075121-0000` passed with final
  text sourced from relay events and declared check `test -f docs/project.md`.
  Relay ingest now also attempts active-plan reconciliation after summary
  creation: it resolves the task even if the running task has already moved to
  `.a9/tasks/done`, checks that the task belongs to the active plan backlog or
  embedded plan contract, then reuses supervisor plan update logic. Unmatched
  relay tasks are recorded as skipped rather than polluting the active plan.
- Mobile/control gateway remains required. The current Codex thread-view work
  only means Barter-rs is not placed as a direct lower layer under Codex.
  Barter-rs stays as the event/service gateway reference for trading or
  high-volume streams; mobile/control gateway, Codex execution runtime and
  Barter-style event gateway are separate A9 layers.
- MemPalace recall is not yet the full memory governance system. A9 now has a
  first deterministic `recall -> causal memory` compiler that turns recalled
  drawers into candidate time-valid facts, stale-branch invalidation candidates,
  causal-change notes, role-scoped packets and next-task memory packets. These
  outputs remain candidate memory, not truth. A dry-run/approved commit path now
  plans MemPalace-style KG temporal triples and role diary writes; actual writes
  require `approved_by`, `approval_reason` and `commit=true`. The remaining gap
  is fully automated invalidation and contradiction repair. A first pre-commit
  drift checker blocks conflicting current KG facts before write, and a
  side-effect-free causal audit now scans the MemPalace KG after writes for
  duplicate/conflicting current facts and emits monitor-approved invalidation
  candidates. Approved invalidation now has a dry-run/commit path that calls
  MemPalace `KnowledgeGraph.invalidate()` instead of deleting facts, preserving
  temporal history. A first side-effect-free repair proposal policy now ranks
  conflicting current KG facts, selects obvious stale branches by stale markers
  and temporal ordering, and exposes monitor-approved invalidation candidates
  without mutating the KG. The remaining gap is fully automatic repair after
  monitor approval and broader contradiction policy. A deterministic
  fixture-based causal-memory
  eval now checks current/stale/causal labels and wrongbook candidates before
  claiming compiler quality. The fixture has been expanded to cover same-drawer
  current+stale, fallback-not-mainline, negated stale instructions, mem0 ->
  MemPalace migration, two-stage workflow, mobile-entry-vs-page-monitor, and raw
  evidence authority. It has already caught and fixed noisy stale negation,
  neutral-log current promotion, fallback-as-current, and retained-entry current
  detection. `scripts/a9_mempalace_eval.py --generate-candidates` now scans
  bounded MemPalace drawer evidence and writes review-only fixture candidates
  with source refs, scores and suggested labels; candidates are not merged into
  the truth fixture until reviewed. `--merge-reviewed` is the controlled merge
  path: it only accepts candidates marked `review_status=approved`, requires
  `approved_by` and `approval_reason`, preserves source refs/hashes, de-dupes
  existing fixture rows, and defaults to dry-run unless `--commit` is passed.
  Control API now exposes the same lane for monitor/mobile use:
  generate candidates, read latest candidates, and merge reviewed candidates.
  The runtime backlog `no_items` path now also returns review-closure
  diagnostics: MemPalace causal audit summary plus bounded repair proposals, so
  monitor/mobile can see whether closure is blocked by stale/conflicting memory
  before deciding to invalidate or generate more backlog.
- Active-plan backlog generation no longer treats retryable execution-chain
  failures as permanent closure. Budget/read-scope failures and orphaned
  `no_live_worker_process` interruptions now produce a narrower retry prompt
  with the previous failure reason and bounded read scope, while non-retryable
  generation failures still wait for monitor review.
- 2026-06-16 live 24h observation: backlog generation can now resume after
  supervisor fixes, append decided execution items, and auto-run them. The
  remaining quality bottleneck is not memory recall itself; it is task-contract
  precision. Workers repeatedly used broad aliases such as `scripts` or `tests`
  despite file-level `allowed_paths`, which caused retryable worker-budget
  stops. Task-quality blocks are now written back into the active plan instead
  of leaving false `queued` state. Next cut: backlog-generation must emit exact
  read commands or anchors, validated checks, and no broad root aliases.
- 2026-06-16 follow-up: backlog-generation prompts now require each generated
  execution item to include `read_commands` alongside `allowed_paths` and
  checks. Debate-final backlog ingestion records `read_commands` and blocks
  missing, broad, non-bounded, or outside-scope read commands as
  `backlog_item_contract_quality`. Old hand-written backlog items get a safe
  file-level `sed -n '1,120p'` read-command fallback so the schema upgrade does
  not break the current 24h lane.
- Backlog-generation debate tasks now include exact active-plan evidence files
  (`plan.json`, `progress.md`, `change_request.md`, `findings.md`,
  `mistakes.md`) in bounded read scope. Without these files, workers can
  falsely report missing contract fields from docs-only evidence.
  If a `needs-followup` / `needs-repair` backlog-generation result came from
  an older supervisor `repo_head`, the current runtime may retry it after code
  repair rather than freezing on stale review output.
- The old `docs/a9-24h-two-lane-review-closure.md` acceptance path is stale.
  Current two-lane closure must stay inside this five-doc packet and active
  plan evidence.
- `crates/a9-gateway`, `crates/a9-worker` and `crates/a9-client` are Rust-side
  control/runtime pieces.
- `.a9/` contains runtime evidence and archives, not source truth.

## Current Context Entry

Read in this order:

1. `AGENTS.md`
2. `docs/project.md`
3. `docs/method.md`
4. `docs/session.md`
5. `docs/reference.md`
6. task-specific contract / plan / evidence slice

Do not broadly read archive, raw session, full evidence or reference projects
unless the task names a bounded slice.
