# A9 Session

This is the human-readable session snapshot. It is not the canonical memory
store and not the canonical evidence store.

Raw external Codex/operator session:

`/root/.codex/sessions/2026/05/21/rollout-2026-05-21T11-20-49-019e488c-d5f9-7501-835a-bf6e8ff6d8a2.jsonl`

## Current Causal State

1. Financial/quant ambition became infrastructure first.
2. A9 is the execution/control layer, not A3B and not the trading model.
3. Page monitoring is stale; durable runtime is supervisor, control API,
   Redis/MySQL, SSH/tmux/Tailscale, worktrees and evidence.
4. Session governance has two lanes:
   external operator session and A9 runtime session. Link by evidence, do not
   mix storage.
5. MemPalace-first is the session/memory/context governance mainline.
6. A9 markdown close-reading is downgraded to adapter, fallback, audit view,
   evaluator baseline and human snapshot.
7. Requirements debate is part of the 24h workflow.
8. Data first, performance second.
9. Noise cleanup is part of requirements analysis.

## Current Mainline

```text
24h worker + monitor runtime
-> stable communication/control plane
-> evidence, trace, wrongbook and task context
-> private Agent OS
-> later financial/quant Codex and A3B data loops
```

## Use

- Default workers do not read raw session.
- `session_refresh` and `session_close_reading` are legacy/fallback routes.
- New session initialization should use Codex raw JSONL -> MemPalace-compatible
  per-message drawer records first.
- Recall is not truth. Raw evidence, source refs and hashes remain canonical.
- When this file grows, fold the durable fact into this causal state and delete
  process noise.

## Active Appends

Append only bounded deltas below this line.
