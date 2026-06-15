# A9 Project Current State

This is the active project index. It is intentionally small.

## Current Identity

A9 is currently a private 24-hour agent execution/control foundation.

It is not:

- the final financial/quant model
- A3B/A?B itself
- a mobile UI project
- a trading engine implementation
- a page-monitor workaround

Current runtime role:

```text
supervisor + control API + worker orchestration
+ SSH/Tailscale/tmux/private node connectivity
+ Redis/MySQL state and evidence lanes
+ git worktree/check/guard/governance
+ MemPalace-first session/memory/context governance
+ monitor intervention and recovery
```

## A9 / A3B Boundary

`/root/a9/a3b_moe_cognition` is a separate A3B/A?B meta-cognitive activation
system and is outside A9 runtime default write scope.

A9 provides structured context and execution evidence:

- goals, boundaries, data/state shape, allowed tools, checks and evidence refs
- tool traces, test reports, diffs, failure summaries, wrongbook candidates

A3B may provide intent, mainline, methodology, candidate paths and risk
judgment. A9 turns those into plan/backlog/worker prompts and still governs
execution through queue, worktree, checks, git and monitor.

Interface shape:

```text
A3B -> A9: mainline, execution_goal, methodology, required_data,
allowed_tools, forbidden_actions, success_criteria, risk_boundary.

A9 -> A3B: evidence_pack, tool_trace, test_report, diff_summary,
failure_summary, cost_report, wrongbook_candidate, next_suggestion.
```

## Current Priority

```text
P0 requirements/ADR closure for 24h worker + monitor + communication foundation
P1 24h worker + monitor reliability
P2 communication foundation and private node connectivity
P3 A9 core contracts supporting P1/P2
P4 reference/vendor baseline for P1/P2
P5 mobile/control product packet, UI details frozen
P6 compute stage A
P7 NZX technical MVP
```

## Current Stable Facts

- `scripts/a9_supervisor.py` owns queue, run-loop, auto-next, worktree, checks,
  guards, evidence, session mini-flow and managed-flow integration.
- `scripts/a9_control_api.py` exposes control/mobile-facing status and command
  surfaces.
- `scripts/a9_session_refresh.py` is legacy bounded extraction and snapshot
  fallback for external Codex/operator sessions.
- `scripts/a9_codex_session_adapter.py` converts Codex raw JSONL into
  MemPalace-compatible per-message drawer records without treating recall as
  truth.
- `scripts/a9_mempalace_provider.py` exposes the runtime-facing MemPalace
  facade: status, source-preserving search, wakeup and official-style recall
  packets. Native MemPalace is the primary recall path; drawer JSONL remains
  deterministic fallback evidence.
- `scripts/a9_supervisor.py` injects bounded MemPalace recall protocol evidence
  into worker context: search hits, hydrated drawer snippets and fallback raw
  evidence refs stay separated. Recall is a recovery hint, not task authority.
- MemPalace recall is not yet the full memory governance system. A9 now has a
  first deterministic `recall -> causal memory` compiler that turns recalled
  drawers into candidate time-valid facts, stale-branch invalidation candidates,
  causal-change notes, role-scoped packets and next-task memory packets. These
  outputs remain candidate memory, not truth. A dry-run/approved commit path now
  plans MemPalace-style KG temporal triples and role diary writes; actual writes
  require `approved_by`, `approval_reason` and `commit=true`. The remaining gap
  is fully automated invalidation and contradiction repair. A first pre-commit
  drift checker blocks conflicting current KG facts before write, and a
  side-effect-free causal audit now scans the MemPalace KG after writes for
  duplicate/conflicting current facts and emits monitor-approved invalidation
  candidates. Approved invalidation now has a dry-run/commit path that calls
  MemPalace `KnowledgeGraph.invalidate()` instead of deleting facts, preserving
  temporal history. A first side-effect-free repair proposal policy now ranks
  conflicting current KG facts, selects obvious stale branches by stale markers
  and temporal ordering, and exposes monitor-approved invalidation candidates
  without mutating the KG. The remaining gap is fully automatic repair after
  monitor approval and broader contradiction policy. A deterministic
  fixture-based causal-memory
  eval now checks current/stale/causal labels and wrongbook candidates before
  claiming compiler quality. The fixture has been expanded to cover same-drawer
  current+stale, fallback-not-mainline, negated stale instructions, mem0 ->
  MemPalace migration, two-stage workflow, mobile-entry-vs-page-monitor, and raw
  evidence authority. It has already caught and fixed noisy stale negation,
  neutral-log current promotion, fallback-as-current, and retained-entry current
  detection. `scripts/a9_mempalace_eval.py --generate-candidates` now scans
  bounded MemPalace drawer evidence and writes review-only fixture candidates
  with source refs, scores and suggested labels; candidates are not merged into
  the truth fixture until reviewed. `--merge-reviewed` is the controlled merge
  path: it only accepts candidates marked `review_status=approved`, requires
  `approved_by` and `approval_reason`, preserves source refs/hashes, de-dupes
  existing fixture rows, and defaults to dry-run unless `--commit` is passed.
  Control API now exposes the same lane for monitor/mobile use:
  generate candidates, read latest candidates, and merge reviewed candidates.
  The runtime backlog `no_items` path now also returns review-closure
  diagnostics: MemPalace causal audit summary plus bounded repair proposals, so
  monitor/mobile can see whether closure is blocked by stale/conflicting memory
  before deciding to invalidate or generate more backlog.
- The old `docs/a9-24h-two-lane-review-closure.md` acceptance path is stale.
  Current two-lane closure must stay inside this five-doc packet and active
  plan evidence.
- `crates/a9-gateway`, `crates/a9-worker` and `crates/a9-client` are Rust-side
  control/runtime pieces.
- `.a9/` contains runtime evidence and archives, not source truth.

## Current Context Entry

Read in this order:

1. `AGENTS.md`
2. `docs/project.md`
3. `docs/method.md`
4. `docs/session.md`
5. `docs/reference.md`
6. task-specific contract / plan / evidence slice

Do not broadly read archive, raw session, full evidence or reference projects
unless the task names a bounded slice.
