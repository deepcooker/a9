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
- `infra/systemd/a9-supervisor.service` and `scripts/a9_service.py`: production
  daemon packaging inspired by mature service practices. The unit uses
  middleware preflight, restart policy, journal output, and the helper exposes
  unit rendering, install hints, heartbeat/progress status, and health checks.
- `scripts/a9_page_monitor.py`: Cline/OpenHands-inspired page and TUI monitor.
  Exported transcript text is treated as a non-canonical observation, hashed for
  idle/stopped detection, snapshotted, converted into a continuation prompt, and
  optionally enqueued back into the supervisor loop.
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
