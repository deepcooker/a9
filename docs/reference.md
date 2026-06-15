# A9 Reference And Copy Policy

A9 copies mature open-source mechanisms first, then adapts them locally with
tests and evidence.

## Copy Rules

1. Verify license before copying source.
2. Record project, commit, path, license, destination and purpose.
3. Preserve required notices.
4. Prefer mechanism copy before source copy.
5. Do not copy non-open-source product references.

## Priority References

- MemPalace: verbatim-first raw storage, per-message drawer, palace hierarchy,
  semantic + hybrid retrieval, wakeup/bootstrap packs, temporal KG,
  precompact/save hooks, provider/backend abstraction and rebuildable indexes.
- Codex: loop, tools, sandbox, approval, context and compaction.
- OpenClaw/Lobster: managed flow, approval/wait/resume, policy attestation,
  plugin/extension shape, memory governance and tool envelope.
- Barter-rs: reconnect, backoff, error action and trading-grade gateway
  reliability.
- Aider: repo map, token budgeting, diff/edit discipline and architect/editor
  split.
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
