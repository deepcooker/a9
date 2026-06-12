# A9 Session Causal Memory

This is the active causal-memory index. It is intentionally small.

Full historical causal memory archive:

`docs/archive/evidence/session-causal-memory-full-20260613.md`

## Current Causal State

1. The original financial/quant ambition became infrastructure first.
2. "抄抄抄" became the engineering law: scan mature projects, extract mechanisms,
   adapt locally, test, record evidence, repeat.
3. Page monitoring was downgraded. The durable architecture is supervisor,
   control API, Redis/MySQL state, SSH/tmux/Tailscale, worktrees and evidence.
4. Session governance split into external operator session and A9 runtime
   session. They link through evidence, but do not mix.
5. Requirements/debate is part of the 24h workflow, not a manual afterthought.
   Execution workers only act after task shape/contract is clear.
6. Product standard is data first, performance second. Engineering gates serve
   the business shape.
7. A9 and A3B are separate layers. A9 produces structured execution evidence;
   A3B consumes evidence for meta-cognitive activation, wrongbook and future
   training data.
8. Context cleanup is itself a requirements-analysis duty. Noisy docs can make
   the worker execute the wrong product faster.

## Active Decisions

- Current engineering priority remains 24h worker + monitor reliability and
  communication/control foundation.
- A9 worker prompts should hydrate from small current indexes and bounded
  evidence slices, not from full historical markdown.
- Full archives under `docs/archive/evidence/` and
  `docs/archive/2026-06-noise-reduction/` are evidence, not hot context.
- A9 highest-shape aggregation is debate evidence, not implementation approval.
- `execution_next` requires a task contract; otherwise the route is
  `debate_next`.

## Expired Or Downgraded Branches

- Page-monitor-as-main-architecture.
- Direct financial model/quant implementation before runtime stability.
- Hard token/line gates as early product-quality substitutes.
- Treating teacher/Codex/GPT/A9 output as truth without evidence authority.
- Treating all docs in `docs/` as equal current truth.

## Required Update Procedure

After any new close-reading or major external review:

1. Update `docs/session-raw-summary.md` with only the active distilled state.
2. Update this file with causal changes, stale branches and active decisions.
3. Archive large/full evidence under `docs/archive/`.
4. Update `AGENTS.md`, `docs/project.md` or task packets only when rules or
   execution priority actually changed.
5. Commit the cleanup before resuming long-running worker execution.

