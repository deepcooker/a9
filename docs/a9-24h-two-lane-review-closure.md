# Two-Lane Runtime Closure: Review 2026-06-08

## Active Plan Contract (slice-aligned)
- `plan_id`: `a9-plan-24h-two-lane-runtime`
- `goal_id`: `goal-A9-24h-agent-runtime-Codex-Hermes-OpenClaw-Aider-757c4e4c5d`
- `execution_backlog_id`: `backlog-001-record-two-lane-review-closure`
- `execution_backlog_phase`: `record`
- `execution_backlog_title`: `Record two-lane review closure and next execution contract`
- State gate summary: `requirements debate pipeline reached ready_for_execution_backlog`.

## Two Lanes in this runtime
1. Session lane (operator/session evidence):
   - `session_refresh` evidence index -> `session_close_reading` notes -> causal memory commit -> role-scoped plan packet.
   - This lane is explicit and separate from goal-queue routing.
2. Requirement lane (execution contract):
   - Debate/review lane produces/updates contract and backlog draft.
   - Execution queue is only activated from an active, decided contract.

## Active-Plan Router Rules (operational)
- Empty queue + active plan + ready backlog exists: enqueue `execution_next`.
- Active plan + unresolved contract + no backlog draft: enqueue `debate_next`.
- Active plan + contract unresolved + backlog draft exists: enter `waiting_for_review_closure`; no generic continuation.
- Active plan + fallback condition encountered: block generic goal-continuation and raise monitor finding.
- No generic goal-continuation under active plan.

## Review-Closure Wait and Exception behavior
- If backlog draft appears before contract closure, do **not** continue debating; keep `waiting_for_review_closure` state until closure is recorded.
- Stale broad reads / high token use are treated as monitor findings, never as implicit acceptance.
- Any direct execution before decided contract/review closure is rejected as out-of-contract.

## Observed Failure Modes (this cycle)
- Broad natural-language backlog/regeneration pass repeated.
- Debate restarted without using decided closure gate.
- Token pressure increased in repeated re-opened debate loops.
- Resolution: enforce active-plan fallback block and backlog-draft review-closure gate in router.

## Out of Scope (closure boundaries)
- Generic goal-continuation fallback as a default path under active plans.
- Finance strategy implementation.
- Mobile UI/monitor polish.
- New hard token/line caps.
- Any direct execution before requirements debate closure and acceptance is decided.

## Next Implementation Candidate
- Implement/verify the two-lane gate in the runtime control path so `waiting_for_review_closure` is the only allowed non-fallback state for undecided-but-drafted backlog.
- After this closure artifact is committed, re-open communication handler queued tests only if no new closure drift is found.
