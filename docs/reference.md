# A9 Reference And Copy Policy

A9 copies mature open-source mechanisms first, then adapts them locally with
tests and evidence.

## Copy Rules

1. Verify license before copying source.
2. Record project, commit, path, license, destination and purpose.
3. Preserve required notices.
4. Prefer mechanism copy before source copy.
5. Do not copy non-open-source product references.

## Use-Through Rule

Reference projects are not architecture decisions by themselves. A9 must not
adopt a mechanism just because its README, demo or public reputation looks
strong.

Correct order:

```text
download locally
-> run or inspect enough to understand the real behavior
-> use it against an A9-shaped task
-> identify duplicate/overlapping mechanisms
-> write the failure modes and tradeoffs
-> build a small local spike/eval
-> decide whether to join A9, stay as reference, or be rejected
```

This is intentionally slower up front. Architecture quality matters more than
early feature velocity. A mechanism that has not been locally tried, compared
and evaluated is only a candidate, not part of the A9 architecture.
One day spent using the right reference deeply can save hundreds or thousands
of later correction loops.

Selection standards:

- Keep the best mechanism per layer; do not merge duplicate ideas just because
  multiple projects implement them.
- Prefer projects that have runnable behavior, tests, clear boundaries and
  recoverable failure modes.
- If a copied mechanism only works after A9-specific patches, the patch and the
  reason must be recorded.
- A reference can be downgraded or removed after local trial.
- Passing a small spike does not make it production; it only allows bounded
  integration behind tests/evidence.

## Rust And Gateway Baseline

A9 is not a Python-only automation script. Python remains useful for model,
business and personalization logic, but the stable control/runtime skeleton
must be selected and tested around Rust-first gateway and interaction behavior.

Required use-through baselines:

- Codex is the primary interaction/runtime reference. A9 must deeply test its
  CLI loop, tool protocol, context/compact/resume behavior, apply discipline,
  sandbox/approval model and long-running goal/session handling before claiming
  equivalent interaction quality.
- Barter-rs is the trading-grade event/service gateway reference. A9 must
  deeply test its reconnect/backoff/error-action/stream handling patterns
  before designing market-facing or high-volume service-event gateways. It is
  not the layer directly "below" Codex.
- OpenClaw/Lobster remains the managed-flow/tool-envelope reference, but it
  does not replace Codex for interaction quality or Barter-rs for low-latency
  gateway reliability.

The intended architecture is layered and partly parallel, not `Codex ->
Barter-rs`:

```text
mobile/control gateway
+ SSH/Tailscale/tmux/private node connectivity
+ Codex-like agent execution runtime
+ OpenClaw-like active-run control plane
+ Barter-rs-like event/service gateway for trading or high-volume streams
+ MemPalace/Headroom context and memory gateways
-> Redis/MySQL state and evidence plane
-> Python model/business logic where it has leverage
```

Any communication/runtime choice must be evaluated for latency, reconnect,
idempotency, observability, recoverability and bounded context behavior. UI
convenience is not allowed to define the runtime architecture.

Codex use-through correction:

- Codex is materially more relevant to A9's agent runtime than to the network
  gateway. Barter-rs answers "how to keep receiving and reconnecting"; Codex
  answers "how to keep an agent thread, tool call, patch, history and goal
  recoverable." Latest Codex also has a serious exec-server/environment layer,
  so it can be called an agent execution gateway, but its center of gravity is
  still agent tool execution and session recovery rather than market/event
  stream ingestion.
- Local source paths inspected:
  Latest local commit `eb8c1ee85` (`code-mode: preserve initial yield at
  completion (#29289)`) after fast-forwarding from `1b24ba912`.
  `codex-rs/code-mode/src/service.rs`,
  `codex-rs/code-mode/src/cell_actor/{mod,types,callbacks,conversions}.rs`,
  `codex-rs/code-mode/src/session_runtime/{mod,types}.rs`,
  `codex-rs/apply-patch/src/parser.rs`,
  `codex-rs/apply-patch/src/invocation.rs`,
  `codex-rs/app-server-protocol/src/protocol/thread_history.rs`,
  `codex-rs/app-server/src/request_processors/thread_processor.rs`,
  `codex-rs/thread-store/src/live_thread.rs`,
  `codex-rs/thread-store/src/local/live_writer.rs`,
  `codex-rs/thread-store/src/local/search_threads.rs`,
  `codex-rs/message-history/src/lib.rs`,
  `codex-rs/state/src/runtime/recovery.rs`,
  `codex-rs/state/src/runtime/goals.rs`, and
  `codex-rs/state/src/runtime/agent_jobs.rs`,
  `codex-rs/state/src/runtime/threads.rs`,
  `codex-rs/exec-server/src/client_recovery.rs`,
  `codex-rs/exec-server/src/environment_registry.rs`,
  `codex-rs/exec-server/src/file_read.rs`,
  `codex-rs/exec-server/src/remote_file_stream.rs`,
  `codex-rs/core/src/session/rollout_budget.rs`, and
  `codex-rs/protocol/src/compacted_item.rs`.
- Local tests with isolated Rust `1.95.0`:
  `codex-code-mode --lib` passed `47/47`;
  `codex-app-server-protocol thread_history` passed `40/40`;
  `codex-state runtime::threads` passed `22/22`;
  `codex-message-history` passed `5/5`;
  `codex-exec-server --lib` passed `146/147` on the full run, with
  `client::tests::initial_connection_is_shared_by_all_waiters` passing when
  rerun alone `1/1`, so this is recorded as a timing/cleanup flake;
  `codex-apply-patch` passed `67/69`. The two apply-patch failures were
  permission-fixture tests that expect writes/removes to fail under
  chmod-protected directories; A9 runs as root, so root could still write. This
  is an environment warning, not a parser failure.
- Mechanisms A9 should copy: cell/session registry, execute-to-pending,
  wait-to-pending, pending frontier, yield/resume, cancellation token,
  callback cleanup before completion response, graceful shutdown, pending
  tool-call tracking, session-scoped stored values, V8/code-mode sandbox
  boundaries, JSONL rollout as live fact source, rollout-to-turn history
  projection, incremental change sets, rollback removal, late completion
  assignment to the original turn, compaction-only turn preservation, dynamic
  tool reconstruction, SQLite/state DB as index, thread recency monotonicity,
  parent/child spawn edges, metadata atomic preservation, append-only message
  history with file locking and soft-cap trimming, corruption detection with
  per-runtime-DB backup/rebuild, goal id/version protection, in-flight usage
  accounting, atomic job item result reporting, stale report rejection by
  assigned thread id, exec-server environment registry, ordered event recovery,
  reconnect retry/backoff, retained-byte replay bounds, remote file streaming,
  Noise relay handshake validation and bounded reordering.
- Mechanisms A9 must not copy as-is: Codex's full Rust workspace is large and
  dependency-heavy; latest targeted tests pulled V8, app-server protocol,
  exec-server, SQLite/sqlx, network proxy and telemetry stacks. A9 should copy
  the protocol/state/persistence patterns first, while keeping Barter-style
  bounded ingress and Redis/MySQL evidence persistence for high-volume context.
- Current decision: Codex is the primary reference for A9's 24h agent runtime
  and operator session governance. Its system-level gain can be `>10` for
  pending/resume, durable history, deterministic apply, remote execution
  recovery and stale-result prevention. It does not replace MemPalace for
  recall, Headroom for context shaping, or Barter-rs for trading/event-stream
  gateway transport.

Barter-rs use-through correction:

- Barter-rs is materially more relevant to A9's first layer than Headroom.
  Headroom helps the selected context enter a model safely; Barter-rs addresses
  the earlier question: can the gateway keep receiving high-volume streams,
  survive disconnects and expose a controllable audit plane?
- Local source paths inspected:
  `barter-data/src/streams/reconnect/*`,
  `barter-integration/src/socket/on_connect_err.rs`,
  `barter-integration/src/socket/on_stream_err.rs`,
  `barter-integration/src/socket/backoff.rs`,
  `barter-integration/src/stream/ext/*`,
  `barter-integration/src/stream/util/merge.rs`,
  `barter/src/engine/audit/state_replica.rs`,
  `barter/src/system/mod.rs`, and `barter/src/engine/command.rs`.
- Local tests with isolated Rust `1.95.0`:
  `barter-integration on_stream_err` passed `6/6`,
  `on_connect_err` passed `3/3`, `backoff` passed `6/6`,
  `forward_by` passed `3/3`, `forward_clone_by` passed `3/3`,
  `merge` passed `1/1`, `barter trading` passed `2/2`, and
  `test_engine_process_engine_event_with_audit` passed `1/1`.
- Mechanisms A9 should copy: explicit reconnect events, capped exponential
  backoff, connect-error action (`Reconnect` vs `Terminate`), stream-error
  action (`Continue` vs `Reconnect`), event stream split/forward/merge,
  external command envelope, trading/processing enabled-state toggle,
  audit stream and state-replica manager with sequence validation.
- Mechanisms A9 must not copy as-is: Barter's common channel abstraction is
  `UnboundedTx`/`UnboundedRx`; that is reasonable in selected trading examples
  but unsafe as A9's large-context/session ingress. A9 needs bounded queues,
  backpressure, spill-to-disk/Redis Streams, byte/token accounting and explicit
  overload actions.
- Current decision: Barter-rs is not a memory or context-pack solution, and it
  should not be modeled as Codex's lower layer. It is the strongest current
  candidate for A9's Rust event/service gateway when the problem is
  high-volume stream intake, market connectivity, reconnect/backoff, command
  envelopes and audit state. Mobile/control gateway and Codex execution runtime
  remain separate A9 layers that can share Redis/MySQL evidence and transport
  primitives.

OpenClaw/Lobster use-through correction:

- OpenClaw is materially more relevant to A9's multi-channel control plane than
  to the low-level transport or memory layer. Codex answers how an agent thread
  persists; Barter-rs answers how streams reconnect; OpenClaw answers how an
  active agent run is controlled from external channels and plugins.
- Local source paths inspected:
  `packages/agent-core/src/agent-loop.ts`,
  `packages/agent-core/src/agent-loop.test.ts`,
  `src/talk/agent-run-control.ts`,
  `src/talk/agent-run-control-shared.ts`,
  `src/talk/agent-run-control.test.ts`,
  `src/agents/embedded-agent-runner/runs.ts`,
  `src/agents/embedded-agent-runner/run/attempt.queue-message.ts`,
  `src/agents/embedded-agent-runner/run/attempt.session-lock.ts`,
  `src/agents/embedded-agent-runner/context-engine-maintenance.ts`,
  `src/agents/embedded-agent-runner/compact.ts`,
  `src/agents/embedded-agent-runner/compact.runtime.ts`,
  `src/agents/embedded-agent-runner/compaction-successor-transcript.ts`,
  `extensions/codex/src/app-server/thread-lifecycle.ts`,
  `extensions/codex/src/app-server/session-binding.ts`,
  `extensions/codex/src/app-server/session-history.ts`,
  `extensions/codex/src/app-server/context-engine-projection.ts`,
  `extensions/codex/src/app-server/dynamic-tools.ts`,
  `extensions/codex/src/app-server/dynamic-tool-execution.ts`,
  `extensions/codex/src/app-server/transport-{stdio,websocket}.ts`,
  `src/gateway/reconnect-gating.ts`,
  `src/config/config.gateway-tailscale-bind.ts`,
  `src/config/gateway-dispatch-config.ts`,
  `src/plugin-state/plugin-state-store.ts`,
  `src/plugin-state/plugin-state-store.test.ts`,
  `packages/media-core/src/read-byte-stream-with-limit.ts`,
  `packages/media-core/src/read-byte-stream-with-limit.test.ts`, and
  `packages/tool-call-repair/src/{payload,promote,stream-normalizer}.ts`.
- Latest local reference commit tested: `0842cb71eb` after fast-forwarding
  OpenClaw from `c45c87acca`. A9 installed an isolated Node `v24.16.0` under
  `.a9/node/node-v24.16.0-linux-x64` and pnpm `11.2.2` in that toolchain, so
  OpenClaw tests no longer depend on the system Node `20.11.1`.
- Local tests with Node `v24.16.0` / pnpm `11.2.2`:
  `pnpm install --frozen-lockfile --ignore-scripts` passed for all `155`
  workspace projects. Targeted OpenClaw evidence now totals `60` test files /
  `1519` tests passed:
  active-run/control/agent-loop/byte-limit `26`, plugin-state `30`, Codex
  app-server/thread/session/context/dynamic-tool/transport subset `234`,
  embedded-runner compaction/maintenance/session-lock/idle-recovery subset
  `699`, SDK/gateway/session-control subset `195`, and context-engine
  boundary/gateway-dispatch/tool-result subset `335`. The dependency install
  took about `4m30s` and pulled `1177` packages, confirming that OpenClaw is a
  rich reference but too heavy to import wholesale into A9's hot path.
- Correct opening: OpenClaw is a control-plane around active agent runs, not a
  single gateway and not a Codex replacement. Its shape is four-layered:
  Codex app-server adapter, embedded agent runner, SDK/gateway control surface,
  and plugin/tool/state boundary. A9 should copy the protocol/state/test ideas
  into Rust/Redis/MySQL hot paths instead of adopting the full Node workspace.
- Mechanisms A9 should copy: terminal failure messages for stream errors,
  steering/follow-up injection into active runs, explicit active-run
  `status/cancel/steer/followup` modes, conservative intent classification
  where ambiguous text defaults to read-only status, queue outcomes with
  machine-readable reasons (`no_active_run`, `not_streaming`, `compacting`,
  `runtime_rejected`), run lookup by session key and session file,
  abandonment tracking, plugin-state namespaces with stable limits, JSON-only
  values, TTL, consume/register-if-absent semantics, per-plugin isolation,
  byte-stream hard caps that destroy/cancel upstream producers, and bounded
  plain-text tool-call repair for model/provider leakage.
- Additional mechanisms A9 should copy after the deeper run: delivery proof for
  steering messages by waiting for the matching user `message_end` transcript
  commit; stale queued-message cleanup when steering times out or the active
  session ends; physical session-file write lock with fingerprint/fence/drain;
  transcript ownership and prompt-release detection; quoted context projection
  with duplicate trailing prompt drop, payload elision/redaction and reserved
  model budget; overflow-triggered compaction with loop guards; compaction
  checkpoint snapshots, before/after hook metrics, safety timeout, model
  fallback and successor transcript rotation; deferred context-engine
  maintenance in a per-session lane with superseded-rerun coalescing,
  shutdown cancellation and visible long-running progress.
- Mechanisms A9 must not copy as-is: the full JS/Node workspace is too heavy
  and currently requires a newer Node toolchain than this A9 box. A9 should
  copy protocol shapes and tests first, then reimplement the hot control path
  in the Rust/Redis/MySQL control plane.
- Current decision: OpenClaw is the primary reference for external control of
  active runs. Its system-level gain is high for A9 mobile/operator takeover:
  monitor commands should become typed `status`, `cancel`, `steer` and
  `followup` actions instead of a generic text submit. This complements Codex
  pending/resume and Barter-rs transport; it does not replace either.
- A9 implication: 24h monitor intervention must be an active-run operation with
  delivery evidence, not a blind text append. Session/memory governance must
  preserve pre-compaction evidence, post-compaction transcript location and
  checkpoint lineage so MemPalace/causal memory can reconstruct why a branch
  changed after `/compact` or overflow compaction.

Hermes use-through correction:

- Hermes is materially more relevant to A9 than a generic "self-improvement"
  reference. It is a runnable agent product with CLI/TUI, gateway, sessions,
  memory providers, skills/plugins, Codex app-server adapter, context
  compression, trajectory compression and session handoff tests.
- Latest local reference commit tested: `e448b21` in
  `reference-projects/hermes-agent-latest`. The previous
  `reference-projects/hermes-agent` remote had a forced update/unrelated
  history, so A9 kept the old checkout intact and cloned the latest tree into
  a sibling directory rather than resetting it destructively.
- Local environment: uv `0.11.23` installed under `/root/.local/bin`; isolated
  Python `3.11.15` venv at
  `reference-projects/hermes-agent-latest/.venv`; installed
  `hermes-agent==0.17.0` editable with `[dev]` dependencies. CLI smoke passed:
  `hermes --help` exposed chat/model/gateway/cron/hooks/skills/plugins/memory/
  sessions/insights/claw/acp/dashboard surfaces; `hermes-agent --help`
  correctly failed closed because no LLM provider is configured.
- Local tests passed:
  context/memory/trajectory/gateway-session slice `410/410`;
  skills/plugin slice `189/189`;
  gateway session boundary/race/max-concurrent/handoff slice `55/55`;
  Codex app-server/session hygiene slice passed `90/90` before
  `tests/test_lazy_session_regressions.py` hit the runner's 140s per-file
  timeout. Rerunning that file directly passed `17/17` in `58.01s`, so this is
  a test-runner timeout observation, not a functional failure.
- Deeper local use-through added:
  memory/session/gateway diagnostics slice mostly passed; `prompt-size` hit
  the same 140s batch-runner timeout but direct rerun passed `7/7`;
  curator/session-switch/memory-interrupt/skill-improvement slice passed
  `109/109`; cron/gateway/profile slice passed `224/232`, with the `8` failures
  isolated to this WSL/container not having user-systemd D-Bus and Hermes
  refusing to install a system service as root without an explicit
  `--run-as-user root` override. Those are deployment preflight signals, not
  core gateway logic failures.
- Correct opening: Hermes should be used as a long-lived product architecture,
  not as a bag of isolated functions. Its own docs state two load-bearing
  principles: per-conversation prompt caching is sacred, and the core is a
  narrow waist while capabilities live at the edges. For A9 this means the hot
  runtime should stay small and stable; memory, skills, curator, model routing,
  gateway surfaces and review loops should attach as profile-scoped sidecars or
  plugins, not be stuffed into every worker turn.
- Prompt-size finding: in A9's repo, Hermes `prompt-size --json` reported
  `AGENTS.md` truncation and about `74KB` fixed system prompt, with about
  `55KB` from project context and about `46KB` of tool schemas. In a clean
  workspace with no project context and no bundled skills, the same diagnostic
  reported about `9.5KB` system prompt and the same `46KB` tool schema payload.
  This is hard evidence that A9's current entry doctrine is too large for a
  hot-path prompt. The Hermes-aligned solution is profile/task-specific
  doctrine hydration plus searchable evidence/role packets, not one giant
  always-injected AGENTS file.
- Product-layer finding: Hermes profiles are isolated state directories
  (`config.yaml`, `.env`, `SOUL.md`, memory, skills, sessions, cron, gateway).
  This maps directly to A9 role lanes: product, architecture, test, monitor and
  execution workers should not share one undifferentiated memory/prompt heap.
  They need role/profile-scoped prompt packs and session stores.
- Long-running work finding: Hermes `delegate_task` is intentionally
  synchronous and non-durable. Durable multi-agent work is Kanban: SQLite board,
  task rows, comments as the inter-agent protocol, profile lanes, dispatcher,
  heartbeat, block/complete/crash/reclaim and logs. A9's 24h worker should copy
  this durable board/lane shape more than the short-lived subagent primitive.
- Sidecar intelligence finding: Hermes self-improvement is not the foreground
  agent editing itself mid-turn. It increments memory/skill counters, then
  spawns a background review fork with a restricted memory/skill tool whitelist,
  inherited cached prompt for provider cache hits, no compression, no external
  memory writes from the review harness, non-interactive dangerous-command
  deny, and compact user-visible summaries. The curator is slower still:
  deterministic stale/archive is default, LLM consolidation is opt-in, and
  snapshots make skill maintenance reversible. This is the strongest local
  evidence for A9's "audit/review as async旁路, not hot-path gate" rule.
- Codex-runtime finding: Hermes can wrap Codex app-server as an opt-in runtime.
  In that mode Codex owns shell/apply_patch/update_plan/sandbox and Hermes
  stays around it as session DB, gateway, slash commands, memory/skill review
  and extra tools via MCP callback. Hermes explicitly documents that some
  agent-loop tools (`memory`, `session_search`, `todo`, `delegate_task`) are
  unavailable inside the Codex runtime and are recovered by event projection
  and background review. This is close to the A9 target split: Codex-like
  execution runtime plus A9 sidecar control/memory/governance.
- Mechanisms A9 should copy: explicit `MemoryProvider` lifecycle
  (`initialize`, prompt block, background prefetch, async turn sync, tool
  schemas, session-end extraction, session-switch hook, pre-compress hook and
  delegation observation); external-memory one-provider policy to avoid tool
  bloat; session_id switch hooks for resume/branch/reset/compression; context
  compressor wording that makes compacted summaries reference-only and keeps
  the latest user message authoritative; historical/stale heading names that
  prevent old work from being treated as active; tail/head protection plus
  middle compression; trajectory compression with metrics and protected first
  and last turns; gateway foreground/background/service split; session store
  list/export/delete/prune/repair/stats/rename/browse; skills/plugins with
  reload and improvement tests; Codex app-server adapter that projects Codex
  events back into Hermes messages while recording usage and approval events.
- Mechanisms A9 must not copy as-is: Hermes is Python-heavy and provider/app
  surface-heavy; many optional extras are lazy-installed or platform-specific.
  A9 should not import the whole workspace or make Hermes the A9 hot runtime.
  Copy the protocols, tests and lifecycle boundaries into A9's Rust/Redis/MySQL
  control plane and Python business/model sidecars.
- Current decision: Hermes is a strong reference for A9's sidecar intelligence
  and quality loop: skills, memory-provider lifecycle, compression hygiene,
  session handoff, gateway session behavior and self-improvement/wrongbook
  direction. It complements Codex/OpenClaw/MemPalace: Codex remains the primary
  thread/runtime reference, OpenClaw remains active-run external-control
  reference, MemPalace remains evidence/recall reference, and Hermes adds the
  clearest tested product layer for memory hooks, skills, profile isolation,
  prompt budgeting, durable Kanban-style work lanes and async review.

## Priority References

- MemPalace: verbatim-first raw storage, per-message drawer, palace hierarchy,
  semantic + hybrid retrieval, wakeup/bootstrap packs, temporal KG,
  precompact/save hooks, provider/backend abstraction and rebuildable indexes.
- Codex: loop, tools, sandbox, approval, context and compaction.
- OpenClaw/Lobster: managed flow, approval/wait/resume, policy attestation,
  plugin/extension shape, memory governance and tool envelope.
- Hermes: self-improving agent product layer, skills/plugins, explicit memory
  provider lifecycle, compression/session hygiene, gateway sessions, session
  handoff and Codex app-server projection.
- Barter-rs: reconnect, backoff, error action and trading-grade gateway
  reliability.
- Aider: repo map, token budgeting, diff/edit discipline and architect/editor
  split.
- Headroom: context-efficiency control plane, CCR, live-zone compression,
  content routing, cache-stability observability, Codex/OpenClaw wrapping and
  proxy metrics.
- LangGraph: checkpoint, parent lineage and channel history.
- mem0: memory add/search/get/history semantics.
- OpenHands, Continue, Cline, Roo, SWE-agent, opencode, aichat: terminal UX,
  provider abstraction, tool boundary and execution harness.

Claude Code and Antigravity are product references only unless an open-source
repo/license is verified.

## Active Copied Mechanisms

Keep this section small. New direct source copies must update
`vendor-src/MANIFEST.jsonl`.

MemPalace is the default mechanism reference for A9 session/memory/context
governance, but recall must not be treated as truth. Any recalled item entering
worker, monitor or operator context must keep source path, line/message id,
hash, role and timestamp.

Current local integration uses `reference-projects/mempalace` as the mechanism
source and `scripts/a9_mempalace_provider.py` as an A9 facade. Native MemPalace
collection access is enabled only when its Python dependencies are present;
otherwise A9 uses the source-preserving drawer JSONL fallback.

## Current Decision Matrix

This is the bounded evidence matrix for A9 session/memory governance and 24h
execution quality. It exists to prevent local invention from replacing
reference-first copying.

| Reference | Local evidence | Mechanism to copy | A9 status | Current gap / next cut |
| --- | --- | --- | --- | --- |
| Codex | Latest local commit `eb8c1ee85`; inspected latest `code-mode` cell actor/session runtime, app-server-protocol `thread_history`, app-server thread processors, thread-store local search/list/write, message-history, state runtime threads/goals/jobs/recovery, exec-server recovery/environment/file streaming, rollout budget and compacted item paths. Targeted tests: code-mode `47/47`, thread_history `40/40`, state runtime threads `22/22`, message-history `5/5`, exec-server full lib `146/147` with the only failure passing alone `1/1` as a timing/cleanup flake, apply-patch `67/69` with root-only permission fixture failures. | Cell/session runtime, pending frontier, yield/resume, callback cleanup, shutdown/termination race discipline, session-scoped stored values, rollout-to-turn projection, rollback/late-completion/dynamic-tool reconstruction, thread recency and spawn edges, JSONL-first live persistence, history lock/soft-cap lookup, deterministic patch grammar, exec-server environment registry, ordered recovery, retained-byte replay bounds, remote file streaming and Noise relay validation. | A9 has supervisor queue, worktrees, strict envelope, deterministic apply, Redis managed flow, policy attestation, patch/scope/git governance and MemPalace session evidence. | A9 still lacks a Codex-grade unified runtime state model: operator session tail, 24h worker task item, active run control, thread graph, rollout projection, remote execution recovery and stale-result rejection are split across scripts. Next cut: port the Codex state model shape into A9 task/run/session records without importing the whole workspace. |
| MemPalace | `reference-projects/mempalace/README.md`, `reference-projects/mempalace/CHANGELOG.md`, `reference-projects/mempalace/examples/cursor/README.md` | Verbatim drawers, source metadata, hybrid retrieval, wakeup packs, preCompact/sessionStart hooks, temporal KG and idempotent resumable mining. | A9 uses MemPalace-first drawer/evidence/index, native recall where available, fallback drawer JSONL, causal candidate compiler and review-only eval candidates. | Recall is still not final truth. Next cut: compile drawer evidence into time-valid facts, stale invalidations and role packets with explicit evidence refs before worker execution. |
| planning-with-files | `reference-projects/planning-with-files/templates/task_plan.md`, `reference-projects/planning-with-files/templates/loop.md`, `reference-projects/planning-with-files/README.md`, `reference-projects/planning-with-files/MIGRATION.md` | Filesystem working memory, progress/findings/task plan loop, hooks re-read before work, attestation and parallel plan isolation. | A9 has active plan, progress/findings/mistakes/change_request and managed backlog. | A9 must not add more planning docs. Next cut: make plan/backlog items stricter as contracts: exact files, exact commands, validated checks, and no broad aliases. |
| OpenClaw/Lobster | Latest local commit `0842cb71eb`; inspected active-run control, Codex app-server adapter, embedded runner, context-engine maintenance, compaction, session lock, gateway config, plugin-state, byte-limit and tool-call-repair paths. Isolated Node `v24.16.0` + pnpm `11.2.2`; install passed for `155` workspace projects / `1177` packages; targeted tests passed `1519/1519` across `60` files. | Active-run control modes, steering/follow-up queueing with transcript delivery proof, stale queued-message cleanup, conservative control intent classifier, machine-readable queue rejection reasons, session-file lock/fingerprint/fence/drain, context projection with redaction/reserve budget, overflow compaction and successor transcript rotation, deferred context-engine maintenance, plugin-state contract, byte-stream overflow destroy/cancel, bounded tool-call repair and terminal stream failure messages. | A9 has Redis managed-flow revision checks, approval/wait/resume, policy attestation and runtime monitor contract, but mobile/operator control is still too generic and steering lacks delivery proof. | Next cut: model A9 monitor actions as typed `status/cancel/steer/followup` active-run commands with queue outcome reasons, delivery evidence, stale steering cleanup and active-run/session-file lookup. Do not import the OpenClaw Node workspace into A9 hot path. |
| Hermes | Latest local commit `e448b21`; isolated uv/Python `3.11.15` venv; editable `[dev]` install passed. CLI smoke passed; runner failed closed without provider as expected. Targeted tests passed: context/memory/trajectory/gateway-session `410/410`, skills/plugin `189/189`, handoff/concurrency `55/55`, Codex/session hygiene `90/90`, lazy-session direct `17/17`, curator/session-switch/memory-interrupt/skill-improvement `109/109`, prompt-size direct `7/7`. Cron/profile/gateway slice passed `224/232`; the 8 failures are WSL/container systemd/root service preflight cases. Real CLI probes: `status`, `skills list`, `memory status`, `sessions stats`, `profile list`, `curator status`, `curator run --dry-run`, `prompt-size --json`. | Narrow-waist architecture, profile isolation, prompt-size diagnostics, MemoryProvider lifecycle, background prefetch and async sync, session-switch/pre-compress/delegation hooks, one-external-provider policy, reference-only compaction prompts, stale-task headings, protected middle compression, trajectory compression metrics, session store management, gateway service/foreground split, skills/plugins reload/improvement tests, curator deterministic prune + opt-in LLM consolidation, durable Kanban board/profile lanes, Codex app-server event projection and usage accounting. | A9 has MemPalace evidence and its own supervisor/control plane, but still over-injects doctrine and lacks role/profile-scoped sidecar contracts. A9's 24h loop is closer to Hermes Kanban than to delegate_task: it needs durable task rows, comments, heartbeat, block/complete, crash/reclaim and per-role prompt packs. | Copy Hermes protocols/tests and product opening into A9 sidecar quality layer. Do not import the whole Python-heavy workspace into the A9 hot runtime. Next cut: slim A9 hot prompt doctrine, define role/profile prompt packs, add prompt-size/evidence budget diagnostics, then model 24h work as durable board/lane records rather than a bare forever loop. |
| Aider | `reference-projects/aider/aider/repomap.py`, `reference-projects/aider/aider/coders/architect_prompts.py`, `reference-projects/aider/aider/coders/udiff_prompts.py` | Repo map instead of full repo reads, architect/editor split, explicit edit format and git-friendly diff discipline. | A9 has repo map, bounded context, deterministic apply and git governance. | Worker still broad-searches (`scripts`, `tests`) after task generation. Next cut: generated backlog must include exact rg/sed commands or anchors, not just a file list. |
| Headroom | `reference-projects/headroom/README.md`, `reference-projects/headroom/docs/content/docs/ccr.mdx`, `reference-projects/headroom/headroom/ccr/*`, `reference-projects/headroom/headroom/transforms/content_router.py`, `reference-projects/headroom/crates/headroom-core/src/ccr/mod.rs`, `reference-projects/headroom/crates/headroom-core/src/transforms/live_zone.rs`, `reference-projects/headroom/headroom/providers/codex/*`, `reference-projects/headroom/headroom/providers/openclaw/*` | Compress-Cache-Retrieve with source hash, retrieval tool injection, workspace-scoped context tracker, content-type router, live-zone byte-range surgery, cache volatility observation, proxy health/stats/metrics, Codex/OpenClaw wrapper config hygiene. | Source build passed in A9-isolated venv/toolchain; Python CCR/router/proxy/wrapper tests mostly pass; proxy smoke passed. Extra A9-shaped tests now cover cache stability, byte-faithful forwarding, system-prompt immutability, Codex WS lifecycle/timing, memory project isolation, learn analyzer/writer, compression failure action and streaming resilience. Real A9 replay showed good savings on a run prompt and summary, but zero savings and high latency on a 594 KB node-worker JSONL tail. This is still a use-through candidate, not a final architecture decision. | Primary strength appears to be context-gateway accident prevention and observability, not only token compression. It is not yet proven as a universal big-log reducer. Continue using it against real A9 worker/session logs before deciding what to copy. Do not put ML/ONNX Rust deps on A9 hot path yet. |

Headroom use-through correction:

- A9's earlier Headroom trial was too close to "call `compress()` and judge".
  That is not Headroom's strongest opening.
- The better opening is persistent gateway usage: `headroom proxy` or
  `headroom wrap codex/claude` with the `agent-90` profile, proxy metrics,
  CCR, cache-zone protection, retrieval hashes and provider-specific wrapper
  hygiene.
- A broader local matrix passed `2629` tests and failed `14`. The failures
  split into environment/setup classes: optional memory bridge tests defaulted
  to `sentence-transformers`, observability tests need OTEL/Langfuse extras,
  two Codex wrap tests assume Python 3.11 `tomllib`, one persistent wrapper
  test collided with A9's own port `8787`, and a direct env-path failure did
  not reproduce in isolation.
- Do not install Headroom's default `local` embedder casually. Its own config
  marks it as `sentence-transformers` / torch-heavy. A9 should use the official
  `onnx` embedder path for local memory trials unless a task explicitly asks
  for the heavy backend.
- A real ONNX memory-bridge smoke imported a small A9 memory file into
  Headroom LocalBackend with `embedder_backend="onnx"`, producing `4` memories.
  Cold init/import took about `21s`, but scoped semantic search returned in
  about `0.05s` and found the A9 mainline plus "data before performance/gates".
- Headroom's memory backend supports `user_id` and `session_id` scoping. A9
  should never query a global memory heap by default; operator session, worker
  session, project, role and run evidence must stay scoped and then be merged
  by an explicit context pack.
- The ONNX path emits an `onnxruntime` GPU discovery warning in this WSL
  environment because `/sys/class/drm/card0/device/vendor` is missing. It is
  not fatal for CPU execution, but deployment logs should suppress or classify
  it so monitors do not treat it as memory failure.
- Current Headroom conclusion: it is a serious context gateway/memory
  candidate, but A9 still needs its own event folding and causal-memory
  compiler. Raw A9 JSONL logs should be folded into meaningful events before
  Headroom-style compression/retrieval; otherwise token savings can be zero.

Latest commercial-readiness read:

- The commercial-grade reference point from the operator is roughly
  `200万-500万 token` and about `10MB/10兆` scale context processing. This is a
  sizing lens, not a hard gate. Do not misread it as `10min` throughput or as a
  fixed prompt-pack token budget.
- The intended A9/A3B scenario is: A9 can receive a large context/data payload
  from A9's own smaller model or upstream worker, hold that scale without
  losing evidence, then split it into high-quality batches, filter noise, fold
  repeated events, preserve source refs and feed refined context to A3B. The
  target is not merely shrinking one prompt; it is controlled large-context
  intake and staged cognition handoff.
- A9 should not choose Headroom as the raw large-context ingestion engine. Its
  local ONNX path is useful for pure embedding on small warmed batches, but full
  `save_memory` + SQLite/vector indexing is far slower in the current default
  path.
- Measured on A9 operator session slices: pure ONNX embedding reached about
  `236万`, `133万` and `81万` estimated-token rough throughput extrapolations
  in short synthetic slices. These are only probes, not proof that Headroom can
  handle the operator's large-context target end to end.
- Measured full local memory path: clean 30-message operator sample took about
  `6.8s` init and `57.3s` save/index, while each scoped recall query returned
  in about `0.05s`. The quality was good only after A9 filtered out tool-output
  noise and AGENTS/context injection. Without that filter, retrieval returned
  curl/help/tool-output noise.
- Therefore Headroom's A9 role is: context gateway, cache/live-zone protection,
  scoped recall, memory budget, CCR/retrieve tool protocol and observability.
  It optimizes the selected recall/context slice that enters a worker prompt,
  not the raw evidence lake. The final prompt budget must be task-dependent,
  not a fixed 200-500 token rule.
- A9 must keep the high-throughput layer itself: stream parse raw session and
  worker JSONL, fold repeated events, drop tool-output noise, deduplicate
  context injection, classify role/session/project/run, then asynchronously
  index only high-value memory packets into MemPalace/Headroom-style storage.
  Worker hot path should consume a bounded, task-shaped recall pack plus
  explicit evidence refs.

Decision:

- The earlier high-quality debate came from durable context plus human
  correction plus repeated requirements shaping; it was not enough as a
  production mechanism.
- A9 should keep the debate quality by turning it into reference-backed plan,
  evidence and memory contracts.
- The next code cut is not another gate. It is task-contract shaping:
  backlog-generation output must be narrow enough that the worker does not need
  broad discovery commands.

## Runtime Selection Review Round 1

This is not a final architecture decision. It records the first external and
local evidence pass for `Codex CLI + 24h coding` versus adding OpenClaw/Hermes
as product layers.

External OpenAI Codex evidence:

- Codex's official app-server surface already exposes the primitives A9 needs
  for a product client/runtime: JSON-RPC transport, thread start/resume/fork,
  turn start/steer/interrupt, streamed item events, approvals and conversation
  history. This makes Codex the strongest primary execution-runtime reference,
  not just a CLI to shell out to.
- Codex official remote connections validate A9's mobile-control direction:
  remote devices can start/continue threads, steer active work, approve
  actions, review diffs/tests/terminal output, switch hosts and connect SSH
  projects. A9 should not reinvent this as a page-monitor hack; it should copy
  the host/thread/control model and use Tailscale/SSH/tmux as our private
  network fallback.
- Codex official automations and subagents also validate the two-lane idea:
  long-running/background work should be isolated in worktrees or dedicated
  runs, while noisy parallel exploration should return summaries to the main
  thread. This matches A9's monitor + worker split.

OpenClaw/Lobster evidence:

- OpenClaw is local-first personal agent infrastructure. Its own security
  policy says Gateway callers are trusted operators, Gateway is control plane,
  Node is an execution extension, and remote access should prefer loopback plus
  SSH tunnel or Tailscale. This is extremely close to A9's current private
  network and mobile/operator-control need.
- OpenClaw should not replace Codex as A9's execution brain. Its strongest
  copied layer is active-run governance: typed status/cancel/steer/followup,
  session binding, delivery proof, queue outcome reasons, plugin state,
  compaction/session locks and channel/gateway routing.
- OpenClaw's own vision rejects heavy default manager-of-managers frameworks
  and keeps core lean with plugin expansion. A9 should copy this restraint.

Hermes evidence:

- Hermes is a runnable product shell: CLI/TUI, messaging gateway, profiles,
  cron, tools, skills, memory, session search, trajectory compression and
  Codex runtime integration. Its README and local tests show a real
  self-improvement/product layer, not just a paper idea.
- Hermes is stronger than OpenClaw for profile isolation, prompt-size
  diagnostics, skills/memory lifecycle, curator/background review and durable
  board/lane work. It is weaker as A9's hot runtime because it is Python-heavy
  and provider/product-surface-heavy.
- Hermes explicitly supports migrating from OpenClaw and wrapping Codex
  runtime, which is evidence that the ecosystem is converging toward a layered
  architecture instead of one monolith.

Current first-round judgment:

- MVP path: `Codex primary runtime + A9 24h supervisor/control API +
  MemPalace memory` is enough to keep moving if the goal is simply reliable
  24-hour coding.
- Product path: use two layers, not one giant framework:
  `Codex-like execution runtime` as the inner loop, and
  `OpenClaw/Hermes-like operator control, profiles, memory, skills, board lanes
  and async review` as sidecars around it.
- Do not put Barter-rs directly under Codex. Barter-rs belongs to the
  trading/high-volume Rust event gateway layer and can share Redis/MySQL
  evidence with the agent control plane.
- Next review round should map exact A9 records to these concepts:
  `thread`, `turn`, `item`, `active_run`, `operator_command`,
  `worker_task`, `profile/role lane`, `memory packet`, `approval`, `handoff`
  and `remote host`. Only after that mapping is stable should implementation
  continue.

Round-2 mapping target:

| Concept | Primary reference | A9 current surface | Decision / next cut |
| --- | --- | --- | --- |
| `thread` | Codex app-server/thread-store | `scripts/a9_runtime_thread_view.py` projects `.a9/runs/*/summary.json` into `thread_id`, `turns` and `items`. Operator chat still lives in raw Codex JSONL and MemPalace drawers. | Keep Codex semantics: thread is a durable conversation/run lane, not a UI tab. Next cut: one index that links operator session thread, worker run thread and worktree/git state. |
| `turn` | Codex turn lifecycle | A9 run summaries and event summaries approximate one worker turn; operator raw JSONL has actual Codex turn records. | Preserve Codex ordering: turn starts, emits items/tool events, then completes/fails/interrupted. Next cut: normalize A9 worker events into `turn.started/item.started/item.completed/turn.completed` envelopes. |
| `item` | Codex streamed item/event model | `event_summaries.jsonl`, summary files, MemPalace drawer rows and control API outputs are split. | Do not invent a new event vocabulary. Next cut: project worker output, commands, patches, approvals and memory writes into item records with source refs. |
| `active_run` | OpenClaw active-run control | `scripts/a9_control_api.py` has run summary, monitor intervention, latest status and service loops, but control is still too generic. | Copy OpenClaw typed actions: `status`, `cancel`, `steer`, `followup`. Add queue outcome reasons and delivery evidence. |
| `operator_command` | OpenClaw Gateway operator model + Codex remote control | Mobile/control API can submit commands and read operator tail, but it is not yet a first-class command ledger. | Every mobile/operator action should become an append-only command envelope with actor, target thread/run, intent, result and evidence path. |
| `worker_task` | A9 supervisor + Hermes Kanban lanes | `.a9/tasks/*`, `.a9/runs/*`, managed flow and backlog already exist. | Keep A9 task files for now, but move toward durable board/lane records: task row, comments, heartbeat, blocked/completed/crashed/reclaimed states. |
| `profile/role lane` | Hermes profiles and Kanban profile lanes | A9 roles exist mostly in prompts/docs; MemPalace recall is not automatically role-scoped. | Define role packets for product, architecture, test, monitor and execution. Hot worker prompt gets only its role packet plus task contract. |
| `memory packet` | MemPalace drawer + Hermes MemoryProvider lifecycle | `.a9/mempalace/operator-session-drawers.jsonl`, native collection, causal eval candidates. | Memory is evidence-backed context, not truth. Next cut: packet schema with source ids, valid time, stale invalidation and role audience. |
| `approval` | Codex approvals + OpenClaw approval/wait/resume | Redis managed flow has approval/wait/resume and policy attestation. | Keep current mechanism. Next cut: link approvals to `active_run` and `operator_command`, not only task/flow ids. |
| `handoff` | Codex remote handoff + Hermes session handoff | A9 has handoff docs and session refresh, but host/thread handoff is not unified. | Treat handoff as moving thread/run/git/session state between local, SSH and mobile-control contexts. Do not model it as a plain text summary. |
| `remote host` | Codex remote connections + OpenClaw Node + A9 SSH/Tailscale/tmux | A9 has service process, control API, Tailscale/SSH/tmux direction and node worker loop. | One trust boundary per host/user. Prefer loopback service plus SSH/Tailscale exposure. Remote host is execution environment, not just display endpoint. |

Implementation guardrail:

- The next implementation should not import OpenClaw or Hermes wholesale.
- First concrete code cut completed: `scripts/a9_runtime_thread_view.py` now
  emits `a9.runtime_projection.v1` with stable top-level arrays for the mapped
  concepts. It is projection-only and keeps raw evidence authoritative.
- Second concrete code cut completed: control API now exposes compact/full
  runtime projection and an append-only `operator_command` ledger. Monitor
  interventions append to that ledger, so mobile/operator actions can be joined
  with worker runs in the same projection.
- Third concrete code cut completed: `operator_command` now has
  OpenClaw-style active-run actions (`status`, `cancel`, `steer`, `followup`)
  through `/api/runtime/active-run-command`. The first cut records target,
  queue outcome, phone-control gate result and delivery evidence. `status` is
  delivered by projection lookup; mutating commands now write a transport
  outbox row in `.a9/runtime/active_run_delivery_queue.jsonl`, exposed in
  runtime projection as `active_run_deliveries`.
- Fourth concrete code cut completed: active-run delivery outbox has tail and
  stale cleanup endpoints. This copies OpenClaw's queue outcome / stale
  delivery governance shape without claiming live transport delivery.
- Fifth concrete code cut completed: active-run delivery consumer framework
  reads the outbox, revalidates target active-runs, updates queued rows, and
  writes immutable delivery results. Until the live transport adapter is
  enabled, mutating commands are consumed as explicit
  `active_run_transport_disabled` rejections instead of fake success.
- Sixth concrete code cut completed: live transport is now a configurable
  adapter contract, not a hardcoded claim. A9 supports
  `codex_app_server_jsonrpc` (`turn/steer`, `turn/interrupt`) copied from
  Codex/OpenClaw active-run steering, and `hermes_session_jsonrpc`
  (`session.steer`) copied from Hermes gateway semantics. The adapter is
  enabled only through `.a9/runtime/active_run_transport.json`; missing/disabled
  config produces explicit rejection proof.
- Seventh concrete code cut completed: A9 now supports the real Codex
  WebSocket transport handshake. The helper suppresses browser `Origin`, sends
  optional bearer capability tokens, performs `initialize -> initialized`, and
  can probe `model/list`. A local authenticated Codex app-server on
  `ws://127.0.0.1:8791` passed live probe and is visible as
  `codex-app-server` in A9 service observation.
- Eighth concrete code cut completed: Codex active-turn control was tested
  against an isolated app-server pointed at Codex's mock Responses provider.
  A9 reused a connection-aware WebSocket JSON-RPC session, started a real
  `turn/start`, delivered `turn/steer` through `active_run_transport_deliver`,
  and the mock provider recorded the follow-up user input. This copies the
  OpenClaw/Codex steering mechanism more accurately than short per-request
  sockets.
- Ninth concrete code cut completed: `scripts/a9_active_run_relay.py` turns the
  session helper into a minimal active-run owner. It writes relay state files,
  keeps the active Codex WebSocket connection, consumes A9 delivery queue rows
  matching the relay run/thread/task, writes delivery results, and is indexed by
  runtime projection plus `/api/runtime/active-run-relays`. A controlled
  mock-provider relay smoke proved queue delivery into real Codex
  `turn/steer`.
- Tenth concrete code cut completed: control API can start a relay-owned Codex
  turn with `/api/runtime/active-run-relay/start`, protected by the runtime
  phone-control gate. The prompt is stored in a private prompt file and passed
  by path, so `ps` does not expose operator instructions. A controlled API
  smoke proved the end-to-end operator path: phone-control arm, relay start,
  active-run steer command, delivery queue consumption by the relay, and real
  Codex `turn/steer`.
- Eleventh concrete code cut completed: relay lifecycle governance now has
  control API stop and cleanup endpoints. `/api/runtime/active-run-relay/stop`
  sends SIGTERM/SIGKILL to the relay pid and writes stop evidence back to the
  relay state file. `/api/runtime/active-run-relay/cleanup` is dry-run by
  default and removes only stopped/old relay state, prompt and log files when
  `commit=true`. Next concrete cut: production worker binding to relay-owned
  runs.
- Remaining candidate projects (`ECC`, `MiroFish`, `Superpowers`, `gstack`,
  deeper `Headroom`) continue as旁路评审. They can improve role debate,
  planning or context shaping, but they should not block the MVP spine.

## Trial Queue

This queue is deliberately small and should be updated only when a reference
has been used locally, not when it is merely mentioned.

| Reference | Local state | Trial target | Current decision |
| --- | --- | --- | --- |
| MemPalace | Downloaded, native/fallback recall tested against real operator session, recall-quality eval added. | Commercial-grade memory: recall quality, causal compiler, role packets, wrongbook loop. | Adopted for memory layer, still not truth authority. Next: role packet eval and contradiction repair. |
| Codex | Updated to `eb8c1ee85`, Apache-2.0, source inspected and targeted tests run under isolated Rust `1.95.0`: code-mode `47/47`, thread_history `40/40`, state runtime threads `22/22`, message-history `5/5`, exec-server full lib `146/147` plus failed item rerun `1/1`, apply-patch `67/69` with the two failures caused by root bypassing permission-denied fixtures. | Agent execution runtime, cell/session registry, pending/resume/yield, deterministic apply, JSONL rollout projection, thread graph/recency, history lookup, goal/job accounting, stale job-result rejection, exec-server recovery/environment/file-streaming and remote execution gateway mechanics. | Primary A9 agent-runtime reference. Copy the state/protocol/persistence and execution-gateway mechanisms, not the whole dependency-heavy workspace. Next: map Codex thread/job/goal/history/exec-server concepts onto A9 operator session + 24h worker records. |
| OpenClaw/Lobster | Updated to `0842cb71eb`, MIT licensed, key active-run control, Codex app-server adapter, embedded-runner compaction/session-lock/context-maintenance, gateway config, plugin-state, byte-limit and tool-call-repair paths inspected. A9 now has an isolated Node `v24.16.0`; `pnpm install --frozen-lockfile --ignore-scripts` passed and targeted tests passed `1519/1519` across `60` files. | Active-run external control, channel/operator steering with transcript delivery proof, session-file ownership/locking, compaction checkpoint/rotation, deferred context maintenance, plugin-state contracts, bounded byte ingestion and tool-call repair. | Primary A9 reference for mobile/operator takeover and active-run governance. Copy typed control, queue-outcome, delivery-proof and session-lock mechanisms; do not import the whole Node workspace into the hot path. |
| Barter-rs | Downloaded, MIT licensed, source inspected and targeted tests passed under isolated Rust `1.95.0`: stream/connect error actions, backoff, stream forward/merge, trading state and engine audit integration. | Rust gateway reconnect, backoff, stream error action, audit state and low-latency transport discipline. | Primary A9 Rust gateway/control hot-path candidate. Copy the stream/reconnect/audit/control mechanisms, not the unbounded channel design. Next: build an A9-shaped large-context ingress spike with bounded backpressure and Redis/MySQL evidence persistence. |
| Aider | Downloaded, repo map and architect/editor prompts inspected. | Repo map, bounded edit discipline, architect/editor split. | Partially adopted; next proof is reducing worker broad reads through exact read commands. |
| planning-with-files | Downloaded, templates and hook flow inspected. | File-backed task memory and resume. | Mechanism reference only; A9 will not import its role model or add extra doc sprawl. |
| Hermes | Latest clone in `reference-projects/hermes-agent-latest` at `e448b21`; uv/Python `3.11.15` venv created; editable `[dev]` install passed; CLI/docs/source/test use-through now covers prompt-size, status, skills, memory provider setup, sessions, curator, cron, gateway service, profile gateway, Codex runtime docs, Kanban docs, background review and compression/session hooks. | Sidecar self-improvement, MemoryProvider lifecycle, role-scoped recall hooks, compression/session hygiene, skills/plugins, profile isolation, prompt budgeting, gateway sessions, durable Kanban/profile lanes, trajectory compression and wrongbook/eval feedback loop. | Promoted from untested candidate to strong product-architecture reference. Next: copy the opening, not just code: narrow hot core, profile/role sidecars, async review, prompt-size budget diagnostics, durable board/lane worker governance, and Codex execution runtime wrapping. |
| ECC | Downloaded, not yet use-through tested. | Multi-agent/tool ecosystem shape and cross-IDE agent conventions. | Candidate; must be compared against A9 role model before inclusion. |
| Headroom | Downloaded and source-run in A9 isolated environment. `headroom._core` build/import passed with Rust 1.95.0 under `.a9/rustup`; CCR tests passed `88/88`; content-router/decision/policy/cache-aligner/Codex/OpenClaw wrapper subset passed `225/227` with the two failures caused by Python 3.10 missing stdlib `tomllib`; proxy smoke passed `/livez`, `/readyz`, `/stats`, `/metrics`; proxy/cache/Codex-WS/memory/learn A9-shaped subset passed `226/226`; byte-faithful/system-prompt/failure-action/streaming/scalability/safety subset passed `134/134`; broader matrix passed `2629` and failed `14` mostly from optional/heavy deps, OTEL/Langfuse extras, Python 3.10 compatibility and A9 port `8787` collision; real A9 replay: run prompt `5688 -> 1649` tokens, run summary `1044 -> 491`, node-worker log tail `171653 -> 171653`; ONNX LocalBackend memory bridge smoke passed with `4` stored memories and `0.05s` scoped search; Rust `headroom-core` full test hit Ubuntu 22.04 glibc vs ONNX Runtime `__isoc23_*` link incompatibility. | Compression, token savings, Codex/Claude/OpenAI proxy behavior, model-aware context reduction, local memory bridge, scoped semantic retrieval and observability. | Not decided yet, but stronger than a plain compression library. Current hypothesis: Headroom's strongest value is context-gateway governance: keep unmutated bytes byte-faithful, protect system/cache hot zones, compress only safe live zones, preserve original evidence behind retrieval hashes, scope memory by workspace/session, surface metrics, and learn repeat failure patterns. Weakness seen so far: raw repetitive A9 JSONL logs need pre-aggregation/event folding before Headroom-style compression. Next use-through must replay real A9 worker/session payloads through proxy-shaped boundaries and ONNX memory before A9 copies or replaces any existing context path. |
| MiroFish | Downloaded, not yet use-through tested. | Multi-agent prediction/simulation ideas and parallel-world evaluation flow. | Candidate; must prove it improves A9 debate/review quality before inclusion. |
| Superpowers | Downloaded, not yet use-through tested. | Spec-first workflow, design confirmation, subagent execution discipline and agentic skills. | Candidate requirements/plan reference; must be run against an A9-shaped requirement before inclusion. |
| gstack | Downloaded, not yet use-through tested. | Skillized roles, plan reviews, QA/benchmark/retro discipline. | Candidate role-review reference; only mechanisms that improve A9's own method roles should be copied. |
