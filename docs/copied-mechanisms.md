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

### LangGraph

Copied files:

- `vendor-src/langgraph/libs/checkpoint/langgraph/checkpoint/base/__init__.py`
- `vendor-src/langgraph/libs/checkpoint/langgraph/checkpoint/memory/__init__.py`

Mechanisms to adapt:

- Stable `thread_id` with checkpoint IDs.
- Channel values and channel versions.
- Pending writes.
- Parent checkpoint lineage.
- Delta channel history.
- Fork/time-travel-ready checkpoint lookup.

## A9 Modification Targets

1. Rust gateway copies the stability model: stable session ID, checkpoint IDs,
   channel state, pending writes, and event status.
2. Python memory layer copies mem0's extraction/search/update semantics but uses
   A9 MySQL + Redis Stack storage.
3. Context builder copies Codex compaction and history invariants but keeps raw
   evidence and deep marks queryable outside the prompt.
