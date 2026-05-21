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

Mechanisms to adapt:

- History summarization once token pressure crosses a soft limit.
- Recent-tail preservation before summarizing old context.
- Recursive compression when summary plus tail still exceeds budget.
- Summary prompt rules that keep filenames, functions, libraries, and package
  names explicit.

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
