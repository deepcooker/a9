# Copied Mechanisms

## First Vendor Batch

A9 has copied selected open-source source slices into `vendor-src/` for direct
study and future modification.

### Codex

Copied files:

- `vendor-src/codex/codex-rs/core/src/context_manager/history.rs`
- `vendor-src/codex/codex-rs/core/src/compact.rs`

Mechanisms to adapt:

- Ordered raw history as the source of truth.
- `history_version` on rewrites.
- Prompt-time normalization.
- Function call/output pair invariants.
- Token pressure estimation.
- Explicit compaction task lifecycle.
- Recent user-message retention after compaction.
- Summary reinjection as handoff, not truth.

### mem0

Copied files:

- `vendor-src/mem0/mem0/memory/main.py`
- `vendor-src/mem0/mem0/configs/prompts.py`
- `vendor-src/mem0/mem0/utils/scoring.py`

Mechanisms to adapt:

- `add/search/get_all/history` memory shape.
- Scoped filters by user/agent/run metadata.
- Fact extraction prompt families.
- Memory update operation semantics.
- Semantic + keyword + entity boost rank fusion.
- Rerank hook after initial retrieval.

### OpenClaw / Lobster

Local references:

- `reference-projects/openclaw/`
- `reference-projects/mem0/openclaw/`

License status:

- `reference-projects/openclaw` is the full OpenClaw repository, MIT licensed,
  cloned from `https://github.com/openclaw/openclaw.git` at commit
  `229490a4892460fd439fcde3b94265ae68b5e779`.
- `reference-projects/mem0/openclaw` is the mem0 OpenClaw plugin slice,
  Apache-2.0 licensed.

Mechanisms to adapt:

- Lobster taskflow and runner contracts:
  `reference-projects/openclaw/extensions/lobster/src/`.
- Policy gate state and CLI:
  `reference-projects/openclaw/extensions/policy/src/`.
- OpenClaw extension/plugin shape:
  `reference-projects/openclaw/extensions/*/openclaw.plugin.json`.
- Memory-core budgets, recall tracking, dreaming, repair, citations, and
  prompt sections:
  `reference-projects/openclaw/extensions/memory-core/src/`.
- Memory-wiki corpus, claim health, query, apply, and prompt-section patterns:
  `reference-projects/openclaw/extensions/memory-wiki/src/`.
- Agent-friendly CLI commands with JSON output.
- Skills-mode memory protocols: triage, recall, and dream.
- Auto-recall before prompt construction and auto-capture after agent turns.
- Per-agent and subagent namespace isolation.
- Tool/event telemetry around memory operations.

Correction:

- Aider remains the edit/repo-map reference.
- OpenClaw/Lobster is the lobster reference line.

### Barter-rs

Local reference:

- `reference-projects/barter-rs/`

License status:

- `reference-projects/barter-rs` is MIT licensed, cloned from
  `https://github.com/barter-rs/barter-rs.git` at commit
  `33e56188e2095781331f85aa3d7f88e251eec65a`.

Mechanisms to adapt:

- Reconnect backoff:
  `reference-projects/barter-rs/barter-integration/src/socket/backoff.rs`.
- Typed connect error actions:
  `reference-projects/barter-rs/barter-integration/src/socket/on_connect_err.rs`.
- Typed stream error actions:
  `reference-projects/barter-rs/barter-integration/src/socket/on_stream_err.rs`.
- Reconnecting socket lifecycle events and timeouts:
  `reference-projects/barter-rs/barter-integration/src/socket/mod.rs` and
  `reference-projects/barter-rs/barter-integration/src/socket/update.rs`.
- Audit state replica:
  `reference-projects/barter-rs/barter/src/engine/audit/state_replica.rs`.
- External command boundary:
  `reference-projects/barter-rs/barter/src/engine/command.rs`.
- Disconnect strategy:
  `reference-projects/barter-rs/barter/src/strategy/on_disconnect.rs`.

A9 adaptation target:

- Communication governance, not trading logic.
- Rust gateway retry/backoff and Redis roundtrip hardening.
- First slice implemented typed retry-classification (`RedisFailureKind`) and a
  `ReconnectBackoff`/`DefaultReconnectBackoff` shape in
  `crates/a9-gateway/src/main.rs`, copied from Barter-rs typed
  backoff/error-action structure.
- Node heartbeat state machine and reconnect evidence.
- Controller node connection helper (`scripts/a9_control_api.py`):
  `connection_state -> connection_action` deterministic mapping adapted from
  Barter-rs typed error-action boundaries:
  `online -> continue`, `stale -> reconnect`, `offline -> quarantine`.
  Boundary note: A9 controller record governance uses `quarantine` (not
  immediate terminate) for offline nodes so operator/supervisor can decide
  resume/repair policy with evidence.
- Node-side connection state classifier (`scripts/a9_node.py`):
  `classify_node_connection_state` keeps the same typed-action discipline for
  local helper and future mobile/control status. Heartbeat freshness maps to
  `online -> continue`, `stale/degraded -> observe`, `offline -> escalate`;
  reconnect evidence can override with `reconnecting -> retry` or terminal
  reconnect failure -> `quarantine/escalate`. Offline heartbeat age wins over a
  self-reported degraded status so stale local reports cannot hide a real
  disconnect.
- SSE replay slice exposes Redis Stream `a9:events` through `/api/events` as
  JSON or `text/event-stream`, copying the mature stream-ID/last-event replay
  pattern while keeping WebSocket for later.
- Future WebSocket layer should use Barter-rs-style lifecycle events:
  connected, item, reconnecting, stream error, terminated.
- Reconnecting stream contract (barter-data):
  `reference-projects/barter-rs/barter-data/src/streams/reconnect/stream.rs`,
  `reference-projects/barter-rs/barter-data/src/streams/reconnect/mod.rs`,
  `reference-projects/barter-rs/barter-data/src/streams/consumer.rs`.
  Mechanism contract:
  `init_reconnecting_stream` initializes one live stream first, then reuses the
  same init future for each reconnection cycle.
  `with_reconnect_backoff` applies exponential backoff on failed re-init,
  resets delay after successful re-init, and caps delay growth.
  `with_termination_on_error` terminates the current inner stream on terminal
  errors so outer reconnect loop is forced to re-init; recoverable errors are
  still emitted to downstream consumers.
  `with_reconnection_events` emits explicit `Reconnecting(origin)` events so
  observers can distinguish reconnect transitions from normal data items.
  Default consumer policy uses `125ms` initial backoff, multiplier `2`, max
  backoff `60000ms`.

Failure modes to preserve in A9 adaptation:

- Initial stream init failure loops forever without hard stop unless upper-layer
  budget/approval policy intervenes.
- Backoff reset bugs can create permanent slow recovery after one successful
  reconnect.
- Terminal error misclassification can trap dead inner streams and block
  re-init.
- Missing reconnect lifecycle events hides degraded state from control plane.

Typed reconnect action contract extracted for A9:

- Connect path uses `ConnectErrorAction` only:
  `Reconnect | Terminate`.
- Stream path uses `StreamErrorAction` only:
  `Continue | Reconnect`.
- Controller node record action domain is intentionally narrower and
  deterministic: `continue | reconnect | quarantine`, derived only from
  `connection_state`.
- A9 evidence should always record `phase` and `action` together so the
  action-domain is auditable and machine-routable.
- Minimum reconnect evidence keys:
  `kind, phase, action, error_class, attempt, delay_ms, policy_budget_remaining,
  flow_id, flow_revision, origin, ts`.

Redis Streams pending/lag evidence contract extracted for A9:

- Source mechanism family: Redis Streams consumer-group observability via
  `XINFO GROUPS` + `XPENDING` on the same stream/group sample window.
- First bounded scope: `a9:tasks` stream, configured task consumer group.
- Required evidence keys:
  `stream, group, sampled_at, status, reason, lag, pending_total, consumers,
  oldest_pending_id, newest_pending_id, pending_by_consumer, thresholds_version`.
- Typed degraded reasons:
  `lag_warn | lag_critical | pending_stuck | pending_skew | no_group | redis_unavailable`.
- First threshold profile to implement:
  `lag_warn >= 100`, `lag_critical >= 1000`,
  `pending_idle_critical_ms >= 30000`, `pending_skew_ratio >= 0.8`.
- Cost-control rule:
  probe uses exactly two Redis reads per sample (`XINFO GROUPS`, `XPENDING`),
  and per-consumer payload is capped (top-N) in control API output.

Failure modes to preserve in A9 adaptation:

- Group exists but `last-delivered-id` not advancing while pending grows.
- Healthy lag hides stuck pending ownership without idle-age checks.
- Consumer imbalance causes hidden starvation unless skew ratio is surfaced.
- Missing threshold versioning breaks cross-run comparability.

Source evidence:

- `reference-projects/barter-rs` is present locally in the controller repo.
- The mechanism above was checked against bounded snippets from
  `barter-data/src/streams/reconnect/stream.rs`,
  `barter-data/src/streams/reconnect/mod.rs`, and
  `barter-data/src/streams/consumer.rs`.
- Next implementation slice should copy only the behavior, not Barter-rs
  trading-domain code.
- Next implementation slice:
  implement node/control status exposure for this contract in
  `scripts/a9_control_api.py` (new helper and `/api/nodes` payload extension),
  add typed threshold/config plumbing in `scripts/a9_supervisor.py` if needed,
  and cover with `tests/test_control_api.py` plus
  `tests/test_supervisor.py` threshold-shape checks.

### Aider

Copied files:

- `vendor-src/aider/aider/history.py`
- `vendor-src/aider/aider/repomap.py`

Mechanisms to adapt:

- History summarization once token pressure crosses a soft limit.
- Recent-tail preservation before summarizing old context.
- Recursive compression when summary plus tail still exceeds budget.
- Summary prompt rules that keep filenames, functions, libraries, and package
  names explicit.
- Ranked repository map built from symbols and file relevance under a token
  budget instead of inlining full source files.

### LangGraph

Copied files:

- `vendor-src/langgraph/libs/checkpoint/langgraph/checkpoint/base/__init__.py`
- `vendor-src/langgraph/libs/checkpoint/langgraph/checkpoint/memory/__init__.py`
- `vendor-src/langgraph/libs/checkpoint-sqlite/tests/test_get_delta_channel_history.py`

Mechanisms to adapt:

- Stable `thread_id` with checkpoint IDs.
- Channel values and channel versions.
- Pending writes.
- Parent checkpoint lineage.
- Delta channel history.
- Fork/time-travel-ready checkpoint lookup.
- Per-channel history conformance: empty channel short-circuit, seed snapshot,
  ordered writes, root behavior, and async parity.

## A9 Modification Targets

1. Rust gateway copies the stability model: stable session ID, checkpoint IDs,
   channel state, pending writes, and event status.
2. Python memory layer copies mem0's extraction/search/update semantics but uses
   A9 MySQL + Redis Stack storage.
3. Context builder copies Codex compaction and history invariants but keeps raw
   evidence and deep marks queryable outside the prompt.

## Implemented Adaptations

- `scripts/a9_checkpoint.py`: A9 checkpoint adapter inspired by LangGraph. It
  writes stable session IDs, checkpoint IDs, parent lineage, channels, updated
  channels, token usage, and evidence IDs into MySQL and RedisJSON. It also
  supports `channel-history`, copying LangGraph's delta-channel lookup idea so
  a worker can rebuild only the relevant context channel from a parent chain.
- `scripts/a9_memory.py`: A9 memory adapter inspired by mem0. It keeps the
  `add/search/get-all/history` shape while using A9 MySQL and Redis Stack.
- `scripts/a9_supervisor.py`: A9 run evidence/state/deep-mark writer inspired by
  Codex raw history and LangGraph checkpoint channels.
- `scripts/a9_supervisor.py`: Aider-style deterministic context compression:
  split old head from recent tail, summarize old details into explicit
  file/symbol/status references, preserve the latest tail verbatim, and record
  compression metadata in checkpoint token usage.
- `scripts/a9_supervisor.py`: LangGraph-style checkpoint lineage for repeated
  task runs. Each new run reads the previous completed checkpoint and writes it
  as `parent_checkpoint_id`, enabling channel-history reconstruction across
  supervisor attempts and 24-hour continuations.
- `scripts/a9_supervisor.py`: Noise-gated context compression and mark
  extraction. Obvious command/test/client warnings, truncation markers, repeated
  lines, and duplicate events are filtered from prompt summaries and long-term
  deep marks while raw evidence files remain untouched.
- `scripts/a9_supervisor.py`: Aider-inspired repo map in each bounded context
  packet. A9 ranks tracked files by task terms and important paths, extracts
  lightweight symbols, excludes vendor/reference/build noise, and records repo
  map metadata in checkpoint token usage.
- `scripts/a9_supervisor.py`: Codex exec JSONL event normalization. Raw event
  streams are still stored, but A9 also writes `event_summaries.jsonl` with
  typed turn, tool, command, file-change, and token-usage summaries for durable
  monitoring and future recovery.
- `scripts/a9_checkpoint.py copy-session`: LangGraph copy-thread capability
  adapted for A9. It copies all checkpoints from one session into another,
  rewrites checkpoint IDs and parent links, preserves channel/token/evidence
  JSON, leaves the source untouched, and publishes RedisJSON hot state.
- `scripts/a9_supervisor.py run-loop --auto-next`: supervisor record-to-next
  loop. Each completed task can schedule the next compare/implement/test/record
  or repair task, and every run writes `.a9/progress.json` with stable 24-hour
  automation capability progress.
- `scripts/a9_supervisor.py:write_deterministic_record`: supervisor-owned
  record phase. After a passing test phase, A9 writes a bounded JSON record
  from existing run evidence and schedules the next `reference_scan` directly,
  avoiding an extra model call that can reread context and trip budget gates.
- `infra/systemd/a9-supervisor.service` and `scripts/a9_service.py`: production
  daemon packaging inspired by mature service practices. The unit uses
  middleware preflight, restart policy, journal output, and the helper exposes
  unit rendering, install hints, heartbeat/progress status, and health checks.
- `crates/a9-worker`: Redis Streams worker wrapper shaped after mature queue
  workers: lease one task from a consumer group, heartbeat lifecycle state,
  execute a bounded worker command, emit started/completed/failed events, and
  ack the stream entry so production orchestration is Rust-first.
- `scripts/a9_supervisor.py`: explicit copy-pipeline templates for the default
  24-hour loop. The scheduler now cycles through reference scan, mechanism
  extraction, vendor import, implementation, test, and record phases, with a
  repair phase for failed checks.
- `crates/a9-client`: minimal Rust client entry inspired by Codex session
  governance, Aider context boundaries, LangGraph thread/checkpoint lineage,
  and Cline/OpenHands adapter boundaries. It keeps user-facing session state
  under `.a9/client/sessions`, loads `.a9/client/config.json`, submits work to
  the existing supervisor queue, refreshes status from durable done-state, and
  creates continuation tasks instead of treating chat text as canonical state.
- `scripts/a9_patch_guard.py` and `docs/patch-diff-discipline.md`: Aider-inspired
  patch discipline prototype. A9 now has a small validator for structured
  `SEARCH/REPLACE` edits and unified diff path sanity, enforcing exact unique
  matches, repository-relative paths, read-only vendor/reference boundaries, and
  Aider's documented path-before-markdown-fence edit-block variant before patch
  execution is trusted.
- `scripts/a9_supervisor.py`: patch guard evidence integration. Every recorded
  worker diff is validated into `patch_guard.json`, stored as durable evidence
  in the checkpoint patch channel, and failed validation forces `needs-repair`
  before a run can be marked `pass`.
- `scripts/a9_scope_guard.py` plus `scripts/a9_supervisor.py`: METR-style
  sandbox/task-boundary discipline adapted into a local diff gate. Tasks can
  declare `allowed_paths`; every captured worker diff is checked into
  `scope_guard.json`, recorded as guard evidence, added to deep marks as
  `scope_guard_result`, and failed scope validation forces `needs-repair`.
- `scripts/a9_soak.py`: Codex/LangGraph-style derived run summary for guard
  evidence. Raw run `summary.json`, `patch_guard.json`, and `scope_guard.json`
  remain the source of truth, while unattended soak reports copy only compact
  guard channel fields: status, diff kind, touched files, findings count, and
  output path. This lets the next record/test worker see whether patch and
  scope gates passed without replaying raw event logs.
- `scripts/a9_supervisor.py`: the same derived guard evidence view is now
  written into each run `summary.json` as `guard_summary` and surfaced through
  `.a9/progress.json` as `latest_guards`. This copies the Codex/LangGraph
  boundary again: raw guard files stay canonical, while operator-facing status
  receives only bounded channel status, changed paths, finding counts, and
  evidence paths.
- `scripts/a9_supervisor.py`: Codex/Aider-style context pressure is now a
  compact channel. Each run records `context_pressure` with prompt token count,
  budget, ratio, remaining tokens, section budgets, previous-context
  compression metadata, and repo-map metadata. The raw prompt stays on disk;
  `.a9/progress.json.latest_context_pressure` is only an operator index.
- `scripts/a9_supervisor.py`: Git governance now copies Aider's commit
  discipline and SWE-agent's reset-to-base environment contract. Accepted
  worker diffs are committed inside the isolated worktree as an atomic snapshot;
  failed or repair-needed diffs are preserved as evidence and then rolled back
  with `restore`, `reset --hard`, and `clean -fdq`. Each run writes
  `git_governance.json` so long-running automation can audit whether the
  worktree was committed, rolled back, or left needing operator intervention.
  Reused worktrees are also reset to the current base before a new attempt, so
  stale worker commits cannot make a repeated task look like it produced no
  diff.
- `scripts/a9_patch_apply.py`: Aider SEARCH/REPLACE edit blocks are now
  executable in A9. The apply engine requires exact unique matches, rejects
  ambiguous/missing targets without writing, supports empty-SEARCH new files,
  and exposes `--dry-run` JSON evidence before mutation.
- `scripts/a9_supervisor.py`: worker final messages can now carry
  SEARCH/REPLACE blocks instead of mutating files directly. The supervisor
  applies clean-worktree edit blocks deterministically, records
  `patch_apply.json`, then sends the resulting diff through patch guard, scope
  guard, checks, and git governance.
- `scripts/a9_patch_apply.py` plus `scripts/a9_supervisor.py`: failed
  SEARCH/REPLACE applies now produce Aider-style repair hints. The hint includes
  the failed block, exact match error, nearby actual file lines when available,
  and is injected into the next repair task instead of forcing the worker to
  infer what went wrong.
- `scripts/a9_patch_apply.py`: partial success is explicit. Multiple edit
  blocks can report `successful_blocks` and `failed_blocks`, with repair hints
  warning not to duplicate successful edits when a retained worktree already has
  them.
- `scripts/a9_patch_apply.py`: controlled fuzz copies Aider's leading
  whitespace recovery only. Exact match still wins; indentation-only recovery is
  recorded as `match_strategy=leading_whitespace`, `fuzz_level=1`, with a
  warning. Edit-distance fuzzy matching stays disabled.
- `scripts/a9_patch_apply.py`: wrapped edit blocks now copy Aider's filename
  and fence cleanup. A leading target filename and one outer triple-backtick
  fence pair can be stripped before matching, with `normalizations` recorded in
  the block evidence.
- `scripts/a9_patch_guard.py`: Aider-style path-line cleanup is shared by guard
  and apply. Lightweight wrappers such as `# file.py`, ``file.py``, `file.py:`,
  and ```python file.py are normalized before the existing repository path
  checks run.
- `scripts/a9_patch_apply.py`: basename disambiguation copies Aider's valid
  filename idea with stricter A9 rules. A basename such as `demo.py` resolves
  only when exactly one safe repository file has that basename; ambiguous
  basenames fail with candidate paths.
- `scripts/a9_patch_apply.py`: repeated repair loops now copy Aider's
  already-applied intuition as structured evidence. If `SEARCH` is gone but
  `REPLACE` exists exactly once, the block is marked `already_applied` and
  succeeds without writing; multiple `REPLACE` occurrences remain a failed,
  ambiguous edit.
- `scripts/a9_supervisor.py`: patch-apply repair prompts now carry structured
  block metadata instead of only prose. `already_applied_count`, successful
  block lines, and failed block lines tell the next worker which edits are
  already handled and which ones still need a fixed SEARCH/REPLACE block.
- `scripts/a9_supervisor.py`: repair prompts now combine patch-apply metadata
  with git governance. A retained failed worktree tells the worker not to resend
  successful blocks; a rolled-back failed worktree tells it to inspect current
  file content before deciding whether those blocks must be resent.
- `scripts/a9_supervisor.py`: monitor/process-governance blocks now route into
  an explicit repair takeover task instead of silently stopping or continuing
  the normal copy pipeline. The repair prompt carries the blocked run's patch
  diff path, process-governance findings, monitor block summary, declared-check
  rule, and data-first/performance-second acceptance constraint. This copies the
  mature agent-runtime pattern that hard failures become bounded recovery work
  with evidence, not free-form self-justification by the same worker.
- `scripts/a9_supervisor.py`: process governance now turns task-level command
  bounds into deterministic checks. If a prompt forbids `ls` or `rg --files`,
  those commands become blocking findings. `sed windows <= N lines` is now an
  observable read policy instead of a mechanical 120-line trap: the effective
  soft window is at least 180 lines, read-heavy phases may use larger bounded
  batches when the worker first explains the reason, and only hard-window
  violations block live execution. This copies the Codex-style principle that
  prompt policy must become runtime policy, while keeping enough flexibility
  for real reference reading and monitor observation.
- `crates/a9-gateway`: Codex app-server transport backpressure semantics are now
  captured as A9's first in-memory communication contract. The copied mechanism
  is asymmetric queue handling: request messages on a full inbound queue return
  an explicit overload retry error, response messages wait for inbound capacity,
  and a full writer queue drops only the overload feedback without blocking or
  corrupting the existing writer queue. This is a test contract before the
  production WS/Redis/SSH transport grows around it.
- `crates/a9-gateway` plus `scripts/a9_control_api.py`: the backpressure contract
  is now a runnable gateway health check, not only a unit test. `a9-gateway
  transport-contract` emits machine-readable JSON, and the mobile/control status
  includes `gateway.reason=gateway_contract_pass|gateway_contract_failed` so
  phones and supervisors can verify the Rust communication contract without
  Redis or a live remote node.
- `crates/a9-gateway`: the same contract can now be promoted from local health
  check to replayable runtime evidence with `a9-gateway transport-contract
  --emit-event`. The command writes a `gateway_transport_contract` entry to
  Redis Stream `a9:events` with the pass/fail status, queue capacity, overload
  code, and the three backpressure booleans, then returns the stream `event_id`
  in its JSON output. The default command remains side-effect free.
- `scripts/a9_control_api.py`: control status now reads the latest
  `gateway_transport_contract` event back from Redis Stream `a9:events` and
  exposes it under `gateway.latest_event`. This closes the loop from Rust
  gateway check -> Redis replay evidence -> mobile/supervisor status, while
  preserving `/api/status` as a read-only view.
- `scripts/a9_control_api.py`: gateway contract status now includes a
  `runtime_evidence` decision channel. A local pass with missing or stale Redis
  evidence returns `action=emit_runtime_event`; a failed runtime event returns
  `action=block`; a fresh pass returns `action=continue`. This gives the
  supervisor and mobile UI a deterministic input for deciding whether
  multi-machine rollout can continue.
- `scripts/a9_supervisor.py`: auto-next scheduling now consumes the gateway
  runtime evidence channel for communication-sensitive tasks. Gateway, Redis,
  stream, WebSocket, SSH, Tailscale, tmux, mobile, control-plane, and remote
  tasks are blocked unless `gateway.runtime_evidence.action=continue`; ordinary
  docs/session tasks skip the gate. This makes the runtime evidence actionable
  instead of only visible.
- `crates/a9-gateway`: Barter-rs reconnect/backoff lifecycle evidence now
  includes `reset_on_success`. The gateway already copied typed connect and
  stream action domains, retry classification, bounded backoff, and Redis Stream
  `gateway_reconnect_decision` evidence. The new field records the success path
  explicitly: failed/retry/terminal decisions emit `reset_on_success=false`,
  while `AttemptSucceeded` emits a `connect_success` decision with
  `reset_on_success=true`. This keeps long-running gateway state machine
  recovery auditable instead of inferring reset behavior from missing errors.
- `scripts/a9_control_api.py`: control status now reads the latest
  `gateway_reconnect_decision` Redis Stream event and exposes it under
  `gateway.reconnect.latest_event`. This gives the mobile/control plane the
  same data-first view as the supervisor: phase, action, error class, attempt,
  delay, remaining retry budget, origin, and `reset_on_success`.
- `scripts/a9_control_api.py`: the same reconnect decision evidence is also
  available as a direct read-only endpoint:
  `/api/gateway/reconnect-decision`. This keeps the phone UI from depending on
  the full `/api/status` payload when it only needs the latest gateway
  reconnect/reset state.
- `scripts/a9_control_api.py`: `/api/gateway/health-refresh` now performs the
  operator-facing refresh action for communication health. It emits a fresh
  transport-contract runtime event and returns reconnect decision freshness
  separately. Missing reconnect evidence is `degraded/action=observe`, not
  faked as success, because reconnect evidence must come from real gateway
  lifecycle events.
- `crates/a9-gateway` plus `scripts/a9_control_api.py`: a bounded
  `reconnect-diagnostic --success` path now emits a real
  `gateway_reconnect_decision` event with `origin=diagnostic_success` and
  `reset_on_success=true`. The control API exposes this as
  `/api/gateway/reconnect-diagnostic?success=1`; the explicit success flag keeps
  diagnostic evidence separate from organic gateway reconnect lifecycle events.
- `scripts/a9_remote.py`: remote SSH/Tailscale/tmux governance now has the same
  typed reconnect-decision evidence shape as the Rust gateway. The copied
  mechanism comes from Barter-rs `on_connect_err.rs`, `on_stream_err.rs`, and
  `backoff.rs`: connect errors map to `reconnect|terminate`, stream errors map
  to `continue|reconnect`, retry delay is a capped function of attempt, and a
  success phase resets the attempt baseline. A9 adapts this into
  `gateway_reconnect_decision(...)` with bounded fields
  `phase/action/error_class/attempt/delay_ms/policy_budget_remaining/node_id/origin/ts`.

## Client Skeleton Reference Notes

Local source slices reviewed before implementing `crates/a9-client`:

- Codex: `vendor-src/codex/codex-rs/core/src/context_manager/history.rs` and
  `vendor-src/codex/codex-rs/core/src/compact.rs`. Borrowed the boundary that
  raw ordered history/session state is durable, prompt construction is a
  derived view, and compaction/continuation should be explicit work with status.
- Aider: `vendor-src/aider/aider/history.py` and
  `vendor-src/aider/aider/repomap.py`. Borrowed the token-control rule that the
  client should pass bounded task prompts and rely on repo maps/supervisor
  context assembly rather than dumping reference source into the CLI.
- LangGraph: `vendor-src/langgraph/libs/checkpoint/langgraph/checkpoint/base/__init__.py`.
  Borrowed stable thread/session IDs, parent lineage, and durable status lookup
  as the resume model.
- Cline/OpenHands boundary, represented locally by
  `vendor-src/cline/src/core/task/tools/handlers/BrowserToolHandler.ts`: UI or
  tool streams are adapters. The A9 client therefore submits to the supervisor
  and reads canonical `.a9/tasks/done` state instead of becoming the canonical
  agent loop itself.

License obligations for these local references remain the existing vendored
ones: Codex, Aider, Cline, and mem0 are Apache-2.0 slices in this repository;
LangGraph is MIT. Keep the corresponding license files in `vendor-src/*` and
preserve notices when copying source-level code. The `a9-client` implementation
is an adaptation of mechanisms, not a pasted source copy.
