# A9 Session Governance

## Position

The core strategy is copying mature mechanisms, not inventing from scratch. The session system should not rely on a single browser conversation, a single markdown summary, or a single vector-memory database. The stable design is a hybrid:

- Codex-style raw event history and compaction.
- LangGraph-style checkpointed state with parent/fork lineage.
- Aider-style repo map, token budget, tail preservation, and edit context.
- mem0-style long-term memory with add/search/get/history APIs.
- OpenHands/Continue-style event streams and UI state only as adapters.

## Why Simple Summaries Are Not Enough

Summaries lose details. The correct invariant is:

> Never discard raw evidence. Summaries are indexes and handoff aids, not the source of truth.

Every model-visible context packet must be reproducible from durable artifacts:

- event log
- tool calls and outputs
- file reads
- patches
- checks
- repo map
- decision records
- memory facts with citations

If a summary omits a detail, the system must be able to retrieve the original evidence by ID.

## Reference Mechanisms To Copy

### Codex

Source paths:

- `reference-projects/codex/codex-rs/core/src/context_manager/history.rs`
- `reference-projects/codex/codex-rs/core/src/compact.rs`
- `reference-projects/codex/codex-rs/core/templates/compact/prompt.md`
- `reference-projects/codex/codex-rs/core/templates/compact/summary_prefix.md`

Mechanisms to copy:

- Keep raw history items ordered oldest to newest.
- Maintain `history_version` whenever history is rewritten.
- Normalize history before prompt construction.
- Preserve function call / function output pair invariants.
- Track token usage and estimate token pressure.
- Run compaction as an explicit task with its own status and hooks.
- Reinject initial context after compaction.
- Treat compaction output as a handoff, not truth.

### Aider

Source paths:

- `reference-projects/aider/aider/history.py`
- `reference-projects/aider/aider/prompts.py`
- `reference-projects/aider/aider/repomap.py`

Mechanisms to copy:

- Keep the recent tail with high fidelity.
- Summarize older head only when token pressure requires it.
- Force summaries to include filenames, function names, libraries, packages, and code-block referenced files.
- Maintain a repo map instead of dumping the entire repository into context.
- Tune repo map tokens separately from chat history tokens.

### LangGraph

Source paths:

- `reference-projects/langgraph/libs/checkpoint/langgraph/checkpoint/base/__init__.py`
- `reference-projects/langgraph/libs/langgraph/tests/test_delta_channel_migration.py`

Mechanisms to copy:

- State is stored in checkpoints.
- Each checkpoint has an ID, timestamp, channel values, channel versions, updated channels, parent config, and pending writes.
- Use `thread_id` as the stable session key.
- Support fork and time-travel by retaining parent checkpoint lineage.
- Use delta channels plus periodic snapshots to avoid unbounded replay.
- Allow human-in-the-loop state updates as explicit checkpoint writes.

### mem0

Source paths:

- `reference-projects/mem0/AGENTS.md`
- `reference-projects/mem0/LLM.md`
- `reference-projects/mem0/evaluation/prompts.py`

Mechanisms to copy:

- Memory APIs: `add`, `search`, `get`, `get_all`, `update`, `delete`, `history`.
- Scope memory by `user_id`, `agent_id`, `run_id`, metadata, and filters.
- Store change history for memory records.
- Use search for relevant recall and `get_all` for audit/export.
- Prefer most recent memory when contradictions exist.
- Attach timestamps and evidence so temporal reasoning is possible.

### OpenHands / Continue

Source paths:

- `reference-projects/openhands/frontend/src/types/v1/type-guards.ts`
- `reference-projects/continue/binary/test/binary.test.ts`
- `reference-projects/continue/gui/src/util/editOutcomeLogger.ts`

Mechanisms to copy:

- Treat frontend/browser state as event streams, not as canonical state.
- Validate event shape with typed guards.
- Persist chat/session history through explicit APIs.
- Log edit outcomes with prompt, completion, model, file path, previous code, new code, and apply state.

## A9 Session Data Model

### Session

```json
{
  "session_id": "uuid",
  "project_id": "a9",
  "root": "/root/a9",
  "created_at": "iso8601",
  "status": "running|paused|blocked|complete",
  "current_checkpoint_id": "uuid",
  "parent_session_id": null,
  "source": "browser|codex_exec|native_agent|import"
}
```

### Checkpoint

```json
{
  "checkpoint_id": "uuid",
  "session_id": "uuid",
  "parent_checkpoint_id": "uuid|null",
  "step": 42,
  "source": "input|loop|tool|compact|human_update|fork",
  "created_at": "iso8601",
  "channels": {
    "task": "snapshot-or-delta-id",
    "messages": "snapshot-or-delta-id",
    "tool_events": "snapshot-or-delta-id",
    "repo_state": "snapshot-or-delta-id",
    "patches": "snapshot-or-delta-id",
    "checks": "snapshot-or-delta-id",
    "memories": "snapshot-or-delta-id"
  },
  "updated_channels": ["messages", "tool_events"],
  "token_usage": {},
  "evidence_ids": []
}
```

### Evidence

```json
{
  "evidence_id": "uuid",
  "session_id": "uuid",
  "checkpoint_id": "uuid",
  "kind": "message|tool_call|tool_output|file_read|patch|check_log|browser_snapshot|reference_note",
  "path": ".a9/evidence/...",
  "sha256": "...",
  "created_at": "iso8601",
  "metadata": {}
}
```

### Memory

```json
{
  "memory_id": "uuid",
  "scope": {
    "project_id": "a9",
    "agent_id": "planner",
    "run_id": "task-001"
  },
  "memory": "Aider keeps recent tail and summarizes older head under token pressure.",
  "type": "preference|decision|fact|procedure|risk|reference_mechanism",
  "confidence": 0.91,
  "created_at": "iso8601",
  "updated_at": "iso8601",
  "evidence_ids": ["..."],
  "supersedes": []
}
```

## Prompt Assembly Algorithm

The prompt builder should assemble context from channels, not from a monolithic transcript.

1. Load session and current checkpoint.
2. Load hard doctrine: `需求.md`, `codex.md`, `TRADE_AGENTS.md`, `AGENTS.md`.
3. Load task state and last N high-fidelity events.
4. Load exact failed check logs and latest patch if present.
5. Load repo map slice for affected files.
6. Search memory for relevant decisions, procedures, risks, and reference mechanisms.
7. Add compaction summary only as a navigation aid.
8. Add citations to evidence IDs for every memory and summary claim.
9. Enforce token budget:
   - Doctrine: fixed cap.
   - Recent tail: high priority.
   - Failed checks and current patch: high priority.
   - Repo map: medium priority.
   - Reference notes: medium priority.
   - Long-term memories: retrieved by score and recency.
   - Old raw transcript: never included wholesale unless explicitly requested.

## Detail Preservation Rules

1. Raw events are append-only.
2. Summaries must cite evidence IDs.
3. Compaction cannot delete evidence.
4. Every patch must be stored as a diff and linked to checks.
5. Every check result must store command, exit code, stdout/stderr path, and duration.
6. Every human update is a checkpoint with source `human_update`.
7. Every browser/page snapshot is evidence, not state.
8. Every memory must have history and can be superseded, not silently overwritten.
9. Contradictory memories are both retained; prompt builder chooses by recency, confidence, and scope.
10. If a task depends on a detail that is only in a summary and has no evidence citation, it must be treated as uncertain.

## Current A9 Implementation

The supervisor MVP has started moving from summary-only continuity to evidence-backed continuity:

- `scripts/a9_supervisor.py` writes `evidence.jsonl` for each run.
- Evidence records include kind, path, SHA-256, size, timestamp, run ID, checkpoint ID, and metadata.
- `scripts/a9_supervisor.py` writes `state.json` for each run.
- State records use checkpoint-style channels: task, messages, tool events, repo state, patches, checks, and future memories.
- `summary.json` remains convenient UI/status data, but it is no longer the only continuity artifact.
- `scripts/a9_supervisor.py` builds bounded context packets with `A9_CONTEXT_TOKEN_BUDGET`.
- `docker-compose.yml` provides MySQL for canonical session data and Redis for queue/lease/heartbeat state.

## Token Explosion Controls

A9 must not solve continuity by stuffing everything into prompts.

Copied constraints:

- Codex-style prompt-time assembly: construct the prompt from normalized current state, not from unbounded raw logs.
- Codex-style compaction boundary: summaries are handoff items, while raw events remain separately stored.
- Aider-style tail preservation: keep the latest task context with higher fidelity than older material.
- Aider-style repo-map discipline: use selected reference notes and repo maps instead of dumping full repositories.
- Channel budgets: doctrine, task, previous context, reference mechanisms, checks, patches, and memories are budgeted separately.
- Deep context marks: every evidence item is parsed into structured marks, not sampled.
- Evidence citations: when a detail falls out of the prompt budget, the worker can retrieve it from evidence/state storage by ID/path.

## Redis Hot Path

MySQL is the cold canonical store. Redis Stack is the hot runtime.

Use Redis for:

- `a9:tasks` stream: task queue and consumer group distribution.
- `a9:events` stream: worker events, tool events, status transitions.
- `a9:deep_marks` stream: every extracted mark from every evidence item.
- Redis Functions: atomic lease/ack/retry/dead-letter/heartbeat operations.
- RedisJSON: current session/checkpoint state documents.
- RediSearch: low-latency search over deep marks and memory text.
- Vector indexes: semantic recall over marks and memories.
- Bloom/Cuckoo filters: dedupe evidence hashes, repeated facts, repeated proposed tasks.
- TimeSeries: worker heartbeat, latency, token budget, token usage, retries, and cost signals.

The prompt builder should hit Redis first for speed, then follow evidence IDs back to MySQL/files only when exact detail is needed.

## Page Monitor In The Stable Architecture

Page monitoring is still useful as step one, because it can keep a live browser conversation moving.

But it must write into the same session store:

```text
page monitor
  -> browser_snapshot evidence
  -> transcript_delta evidence
  -> optional continuation prompt
  -> checkpoint(source=browser)
  -> prompt builder
  -> worker/supervisor
```

It should not be allowed to execute shell commands, apply patches, or mark tasks complete. Those actions must go through the supervisor and create typed evidence.

## MVP Upgrade From Current Supervisor

The current `scripts/a9_supervisor.py` already has run traces and context summaries. Next upgrades:

1. Replace plain `context.md` with checkpoint records.
2. Store raw event lines as evidence rows with hashes.
3. Add per-run `state.json` with channels.
4. Add `memory.jsonl` for scoped memories with evidence IDs.
5. Add `reference-notes/` extracted from Codex, Aider, LangGraph, mem0, OpenHands, Continue.
6. Add prompt builder that assembles from state, not from a single summary.
7. Add page monitor as an importer that writes browser snapshots into evidence.

This gives us stable 24-hour operation while still preserving the "copy the best mature systems" strategy.
