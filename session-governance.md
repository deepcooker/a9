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
2. Load hard doctrine: `原始想法需求.md`, `TRADE_AGENTS.md`, `AGENTS.md`.
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
- Completed supervisor runs write local files, MySQL canonical rows, and Redis hot-path events/documents.
- Redis `session_id` is stable task/session identity; `run_id` and `checkpoint_id` vary per attempt.

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

## Rust / Python Boundary

A9 should not force everything into one language.

Rust owns the stable governance path:

- API/gateway and process supervision.
- Redis Streams consumer groups.
- Redis Functions/Lua integration.
- Lease, ack, retry, dead-letter, heartbeat, and timeout logic.
- MySQL/Redis consistency writes.
- High-concurrency worker orchestration.
- `crates/a9-gateway` starts this path with Redis Streams submit/lease/ack/fail/heartbeat/status.

## Mem0 Integration Strategy

Mem0 is Apache-2.0 and can be directly introduced or forked. A9's current path is:

- Copy the API shape first: `add`, `search`, `get_all`, `history`, scoped filters, metadata, evidence IDs.
- Keep canonical memory rows in MySQL.
- Keep hot memory documents in RedisJSON and searchable through RediSearch.
- Keep Python as the memory business-logic layer for extraction/update/rerank experiments.
- Later, optionally install `mem0ai` as a Python plugin or vendor a modified fork if its internals need deeper changes.

This avoids putting a heavy Python memory framework inside the Rust governance hot path while still copying Mem0's mature memory semantics.

## Raw Session Refresh Task

Manual raw-session close reading proved the mechanism, but it should not remain
a chat-only habit. A9 needs a dedicated 24-hour task type for it:

```text
session_refresh
  -> locate raw Codex session JSONL
  -> record session path, turn count, and approximate line index
  -> read the next bounded turn range
  -> extract original intent, execution detail, correction, and drift reason
  -> update close-reading and rolling-summary docs
  -> write deep marks and evidence links
  -> stop before context or output becomes too large
```

This task must be bounded. The manual run exposed a failure mode: a long
close-reading turn triggered context compaction and tool/output fragility. The
operator had to run `/compact` and continue. A9 should copy that lesson:

- Do not ask one worker to read an entire long session.
- Default batch size is 10 user turns or less.
- If output is truncated, re-extract only the missing turn range.
- If context pressure crosses the budget, stop and write a continuation task.
- The continuation task must include the raw session path, last completed turn,
  next turn range, and approximate JSONL line numbers.

The session refresh worker is allowed to update docs and evidence. It is not
allowed to infer missing details from memory when the raw JSONL can be read.

Current deterministic route:

```bash
python3 scripts/a9_supervisor.py enqueue raw-refresh \
  --phase session_refresh \
  $'source_session_path: /path/to/rollout.jsonl\nfrom_turn: 110\nto_turn: 114\nbatch_size: 10\nauto_continue: true'
python3 scripts/a9_supervisor.py run-one --auto-next

scripts/a9_session_refresh.py index /path/to/rollout.jsonl
scripts/a9_session_refresh.py extract /path/to/rollout.jsonl --from-turn 110 --to-turn 114
scripts/a9_session_refresh.py refresh /path/to/rollout.jsonl --from-turn 110 --to-turn 114
```

`session_refresh` is a supervisor route, not an AI worker phase. It calls the
deterministic parser, writes run evidence/state, and does not call Codex or any
model API. It also does not schedule `reference_scan -> mechanism_extract -> ...`
follow-ups; project copying remains a separate pipeline. With `--auto-next` and
`auto_continue: true`, it schedules only the next bounded `session_refresh`
range, stopping automatically when `to_turn` reaches the indexed user-turn
count.

Close-reading import is also a separate deterministic route:

```bash
python3 scripts/a9_supervisor.py enqueue raw-close-reading \
  --phase session_close_reading \
  $'extract_path: .a9/external_sessions/<external_session_id>/turns-110-114.json\nclose_reading_doc: docs/session-raw-close-reading.md\nsummary_doc: docs/session-raw-summary.md'
python3 scripts/a9_supervisor.py run-one
```

`session_close_reading` consumes a bounded extract and appends evidence-indexed
notes to the raw close-reading docs. It is intentionally shallow: it preserves
turns, line numbers, raw user wording previews, assistant/tool counts, and
evidence paths. It does not claim deep semantic judgment and does not call a
model. Deeper interpretation remains a separate worker/evaluator step.

With `--auto-next`, the external-session mini-flow is:

```text
session_refresh(turn N-M)
  -> session_close_reading(extract N-M)
  -> session_refresh(turn M+1-K)
  -> ...
  -> stop when M reaches user_turn_count
```

This copies OpenClaw-style routing discipline at A9 scale: every transition is
phase-specific, evidence-backed, and bounded. It never falls through into the
project copying pipeline.

`refresh` writes:

```text
.a9/external_sessions/<external_session_id>/index.json
.a9/external_sessions/<external_session_id>/turns-<from>-<to>.json
```

These files are evidence inputs for close-reading docs and future MySQL/Redis
indexes. They are not mem0 memories.

## Two Session Families

A9 must separate two session families.

### External Codex/Operator Session

This is the session produced by the human + Codex window, for example:

```text
/root/.codex/sessions/2026/05/21/rollout-2026-05-21T11-20-49-019e488c-d5f9-7501-835a-bf6e8ff6d8a2.jsonl
```

Its purpose is governance and doctrine extraction:

- recover original intent after compaction
- preserve why decisions changed
- extract project doctrine, mistakes, next steps, and architecture boundaries
- cite turns and approximate JSONL line numbers

This session is not the A9 worker runtime. It is an external evidence source
imported by a `session_refresh` task.

### A9 Runtime Session

This is the session produced by A9 itself while running 24-hour tasks:

```text
.a9/tasks/queue
.a9/tasks/running
.a9/tasks/done
.a9/runs/<task>-<timestamp>-a<attempt>/
```

Its purpose is execution governance:

- task/flow state
- worker prompt and events
- tool outputs
- patches and apply metadata
- checks, guard findings, git governance
- retry, repair, budget stop, approval/wait/resume

This session is controlled by A9 runtime and must eventually move through
managed flows, Redis Functions, strict worker envelopes, and policy
attestation.

### Relationship

The external Codex/operator session can create doctrine and tasks for A9. A9
runtime sessions execute those tasks and produce new evidence. They should be
linked, not merged:

```text
external_session(turns, decisions)
  -> session_refresh evidence/deep_marks
  -> doctrine/task updates
  -> A9 runtime task/flow/run
  -> runtime evidence/checks/patches
```

Storage should keep separate IDs:

- `external_session_id`
- `operator_turn`
- `source_session_path`
- `a9_task_id`
- `a9_run_id`
- `flow_id`

Do not confuse an imported Codex turn with an A9 worker run.

## Storage Boundary For Sessions And Memory

Raw sessions do not belong in mem0.

The correct split is:

- Raw JSONL session files remain immutable evidence on disk or object storage.
- MySQL is the canonical index for sessions, checkpoints, evidence rows, turn
  ranges, line offsets, source paths, hashes, and close-reading records.
- Redis Stack is the hot control plane and retrieval index: latest session
  state, deep marks, flow state, budgets, retry state, and search indexes.
- mem0-style memory stores only extracted long-term facts, preferences,
  decisions, procedures, risks, and reference mechanisms.

This distinction matters because raw sessions are large, ordered, and
audit-oriented. mem0 memories are small, semantic, supersedable, and
retrieval-oriented. Putting raw sessions into mem0 would mix evidence storage
with memory recall and would recreate the same compaction/detail-loss problem.

Every mem0 memory derived from a session must cite evidence:

```json
{
  "memory": "OpenClaw/Lobster is A9's runtime/managed-flow primary reference.",
  "memory_type": "decision",
  "evidence_ids": ["session:<id>:turn:95"],
  "metadata": {
    "source_session_path": "/root/.codex/sessions/...",
    "turn": 95,
    "approx_line": 8330
  }
}
```

The prompt builder should recall mem0 memories for speed, then follow
`evidence_ids` back to MySQL/files when exact wording or chronology matters.

Python owns the model-facing business path:

- Prompt policy and context assembly experiments.
- Personalized memory extraction and update logic.
- Model/provider adapters.
- Reference project comparison and mechanism extraction.
- Financial quant research logic and fast iteration scripts.

This mirrors the mature-project lesson: stable runtime mechanics need a strict systems layer, while model behavior needs a flexible iteration layer.

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
