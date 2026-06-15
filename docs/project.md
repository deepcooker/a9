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
