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
    five-doc packet plus active plan evidence; do not recreate one-off
    closure documents.
11. 2026-06-16 clarification: earlier debate quality came from long context,
    human correction, repeated requirements shaping and causal memory together.
    It was not a sufficient production mechanism by itself. A9 must preserve
    that quality through reference-backed plan contracts, evidence refs,
    role-scoped packets and task-quality feedback, not by trusting current
    chat context.

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
- Two-lane closure routing is active:
  `session_refresh` / `session_close_reading` for external/operator causal
  commits runs alongside requirements debate and backlog execution lanes. Each
  lane has its own closure packet; stale one-off closure markdowns are not
  recreated.
  - Role-scoped distribution for session-lane outputs:
    - `product/mainline`: scenario pressure, tradeoff framing, and business impact notes.
    - `architecture`: boundary/state-flow deltas, dependency risks, and stale-branch links.
    - `test`: acceptance criteria, negative cases, and reproducible exception checks.
    - `execution`: decided backlog item drafts plus read_commands/checks/allowed paths.
    - `monitor`: stale markers, drift observations, and repair/rollback flags.
  - Stale packets route only to `monitor` and `product/mainline` as review
    inputs; other roles treat stale packets as non-current until a fresh packet
    is emitted.
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
  mutating KG state. Active-plan backlog generation now retries boundedly after
  retryable worker-budget failures or orphaned `no_live_worker_process`
  interruptions by injecting the previous failure reason into a narrower
  generation prompt; non-retryable generation failures still wait for monitor
  review. A subsequent worker reported missing `change_record`/`role_signoff`
  from docs-only evidence; this was a scope defect, so backlog-generation tasks
  now include exact active-plan evidence files in bounded read scope before
  judging contract closure.
  If a backlog-generation result is `needs-followup` or `needs-repair` from an
  older supervisor `repo_head`, current runtime may retry it after code repair
  instead of treating the stale result as permanent closure.
- 2026-06-16 live observation: backlog generation now resumes and appends
  decided items, but execution workers still fail when task packets allow broad
  discovery habits (`scripts`, `tests`) instead of exact file/command anchors.
  This confirms the next mechanism to copy is command-level task contract
  shaping from Codex/Aider/planning-with-files/OpenClaw, not another hard gate.
- When this file grows, fold the durable fact into this causal state and delete
  process noise.
- MemPalace recall protocol is wired into control API and supervisor context packets.
  Session lane and active-plan lane evidence are separated: raw session evidence
  flows only through `session_refresh -> session_close_reading -> causal commit`
  and bounded `docs/session.md` notes, while active-plan execution evidence flows
  through active contract/progress and role-scoped outputs.
  Before execution backlog drains, role-scoped closure outputs and role_signoff
  must be present in the active plan evidence, and no stale one-off closure docs
  are recreated.

## Active Appends

Append only bounded deltas below this line.
