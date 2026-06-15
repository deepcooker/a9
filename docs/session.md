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
10. Old one-off closure docs are stale. Current closure state lives in the
    five-doc packet plus active plan evidence.

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
- Current provider entry is `scripts/a9_mempalace_provider.py`; it supports
  `status`, source-preserving `search`, `wakeup` and official-style `recall`
  packets with native search hits, hydrated drawers and fallback evidence refs.
- Recall is not truth. Raw evidence, source refs and hashes remain canonical.
- Current shortfall: KG/diary/causal-change compilation is only at the first
  deterministic candidate layer. A9 can compile recall into candidate current
  facts, stale branches, causal changes, role packets and next-task memory, but
  KG/diary writes now go through a dry-run/approved commit path. Actual writes
  require `approved_by`, `approval_reason` and `commit=true`; the first
  pre-commit drift checker blocks conflicting current KG facts before write, and
  the first post-write causal audit reports duplicate/conflicting current facts
  plus monitor-approved invalidation candidates. Approved invalidation now has
  a dry-run/commit path that uses MemPalace `KnowledgeGraph.invalidate()` and
  keeps old facts as temporal history. A first repair proposal lane now turns
  audit conflicts into side-effect-free stale-branch selections using explicit
  stale markers and temporal ordering, then routes them back through the
  existing monitor-approved invalidation protocol. Fully automatic repair after
  approval and broader contradiction policy remain unfinished. `scripts/a9_mempalace_eval.py`
  now provides a deterministic fixture eval for current/stale/causal labels and
  wrongbook candidates. The fixture now covers 12 cases including same-drawer
  current+stale, fallback-not-mainline, negated stale instructions, mem0 ->
  MemPalace migration, two-stage workflow, mobile-entry-vs-page-monitor, and raw
  evidence authority. It has fixed noisy stale negation, neutral-log current
  promotion, fallback-as-current, and retained-entry current detection. The
  candidate lane now scans bounded MemPalace drawers and writes review-only eval
  candidates with source refs and suggested labels; generated candidates are not
  fixture truth until reviewed. Reviewed candidates enter the fixture only via
  `--merge-reviewed`, which requires `review_status=approved`, `approved_by`,
  `approval_reason`, source refs/hashes, de-dupe checks and explicit `--commit`.
  The same review lane is now exposed through control API for monitor/mobile
  operation: generate latest candidates, inspect latest candidates, and dry-run
  or commit reviewed merges. Runtime backlog `no_items` now carries a bounded
  review-closure diagnostic packet with causal audit counts and repair proposal
  candidates, keeping stale-memory repair visible to monitor/mobile without
  mutating KG state.
- When this file grows, fold the durable fact into this causal state and delete
  process noise.
- MemPalace recall protocol is wired into control API and supervisor context packets.
  The next execution lane is backlog generation/resume under the current
  five-doc contract, not recreation of old closure artifacts.

## Active Appends

Append only bounded deltas below this line.
