# Two-Lane Runtime Closure: Review 2026-06-08

## Active Plan Contract (slice-aligned)
- `plan_id`: `a9-plan-24h-two-lane-runtime`
- `goal_id`: `goal-A9-24h-agent-runtime-Codex-Hermes-OpenClaw-Aider-757c4e4c5d`
- `execution_backlog_id`: `backlog-003-record-two-lane-review-closure`
- `execution_backlog_phase`: `repair`
- `execution_backlog_title`: `Repair backlog-003 two-lane review closure and role-scoped commitments`
- State gate summary: `requirements review closure recorded for active contract`.

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
- Any direct execution before decided contract/review closure is rejected as out-of-contract.
- Active plan + missing role-scoped closure fields: `waiting_for_review_closure` blocks all continuation.

## Review-Closure Wait and Exception behavior
- If backlog draft appears before contract closure, do **not** continue debating; keep `waiting_for_review_closure` state until closure is recorded.
- Stale broad reads / high token use are treated as monitor findings, never as implicit acceptance.
- Backlog drift detected during repair is treated as recoverable audit exception and must be re-committed before resume.
- Any direct execution before decided contract/review closure is rejected as out-of-contract.

## Product / Mainline
- Accept:
  - Preserve the two-lane runtime boundary.
  - Require closure artifact update before communication-handler continuation.
- Reject:
  - Debate loop continuation once scope is closed and evidence mismatch is known.
  - Any direct execution that bypasses role-scoped commitments.
- Residual-risk commitments:
  - If any product/mainline role packet conflicts with this closure, monitor must pause runtime and request role re-alignment before resuming.

## Architecture
- Accept:
  - Keep `waiting_for_review_closure` as the only non-fallback state while contract remains unresolved.
  - Keep explicit active-plan ordering: evidence -> contract -> allowed execution gate.
- Reject:
  - Routing with unresolved draft without closure and without change_record.
  - Repair edits outside `allowed_paths` scope.
- Residual-risk commitments:
  - Treat any future allowed-path violation as a blocking architecture exception requiring explicit monitor confirmation.

## Test / Data
- Accept:
  - Closure must always contain `Product / Mainline`, `Architecture`, `Test / Data`, `Monitor / Runtime Governance`, `What cannot execute now`, `Residual risk`, and `change_record`.
  - Add explicit backlog-003 failure trace as data/state fact (allowed-path violation).
  - Keep this file as closure-of-facts evidence, not implementation plan.
- Reject:
  - Non-empty closure lacking role-scoped acceptance/rejection commitments.
  - Implicit acceptance from natural-language logs without structured fields.
- Residual-risk commitments:
  - Monitor checks must be case/heading stable enough for parser-based enforcement.

## Monitor / Runtime Governance
- Accept:
  - Monitor must surface stale reads, token-pressure drift, and scope violations as blocking findings.
  - Recovery path must explicitly document repair scope and re-verify before queued continuation.
- Reject:
  - Silent remediation without closure re-recording.
  - Test runs that do not preserve this closure as closure-of-record.
- Residual-risk commitments:
  - If monitor evidence and closure doc diverge, freeze continuation until the mismatch is fixed and re-attested.

## What cannot execute now and why
- Cannot execute queued communication handler tests now: backlog-003 demonstrated scope/allowed-path violation while writing closure artifacts.
- Cannot execute any new implementation now: this run is a closure repair slice with record-only intent.
- Cannot execute cross-lane fallback now: router must keep runtime in review-closure state until role-scoped commitments are present.
- Cannot execute additional debate loops now: no updated business/scoped decision package was requested for this repair.

## Residual risk
- External role-review source language may still drift against literal acceptance patterns.
- Stale evidence may return between repair write and monitor validation.
- Redis/queue state could race with closure update if external actors resume continuation too early.

## Observed Failure Modes (this cycle)
- Broad natural-language backlog/regeneration pass repeated.
- Debate restarted without using decided closure gate.
- Token pressure increased in repeated re-opened debate loops.
- Backlog-003 violated allowed-path policy by editing `docs/a9-24h-two-lane-review-closure.md` while not in allowed_paths.
- Resolution: enforce active-plan fallback block and backlog-draft review-closure gate in router; tie this repair lane to a role-scoped closure rewrite.

## Out of Scope (closure boundaries)
- Generic goal-continuation fallback as a default path under active plans.
- Finance strategy implementation.
- Mobile UI/monitor polish.
- New hard token/line caps.
- Any direct execution before requirements debate closure and acceptance is decided.
- Changing runtime implementation code in this repair slice.

## change_record
- 2026-06-08T13:00:00Z: Repaired closure document as record-only action for backlog-003, preserved two-lane runtime, added role-scoped accept/reject/residual-risk commitments, added `What cannot execute now`, `Residual risk`, and explicit `change_record`.

## Next Implementation Candidate
- Implement/verify the two-lane gate in the runtime control path so `waiting_for_review_closure` is the only allowed non-fallback state for undecided-but-drafted backlog.
- After this closure artifact is committed, re-open communication handler queued tests only if no new closure drift is found.
