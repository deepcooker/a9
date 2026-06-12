# A9 Runtime Review Closure - 2026-06-03

This packet closes review only for the next narrow runtime-governance slice.
It does not approve broad feature expansion.

## decision_status

decided.

## problem

A9 can run worker tasks and can inject requirements method guidance, but review
closure is still too implicit.

Recent evidence:

- `docs/a9-current-review-packet.md` produced a useful `debate_next` review.
- `docs/a9-current-role-review.md` kept execution unapproved.
- `docs/agent-runtime-observations.md` records that a debate-next auto-next
  continuation had to be stopped by monitor because it turned review output into
  a follow-up execution/test chain.
- The ECC mechanism extract passed and committed, but the queue then became
  idle because no closed decision packet generated the next `execution_next`.

The real problem is not missing worker capability. The real problem is that
review closure is not yet a first-class handoff artifact and status signal.

## system_requirement

A9 must make review closure visible and enforceable at the task-routing level:

- A non-trivial execution task must cite a closed decision packet.
- `debate_next` output may produce review artifacts, mechanism extracts, and
  change requests, but must not automatically become implementation backlog.
- Supervisor/control status must make "idle because waiting for review closure"
  distinguishable from "idle because all work is complete".
- The next task generator must prefer a closure-repair task when no closed
  `execution_next` exists.

## product_definition

The product behavior is a 24 hour execution machine that waits at the right
boundary instead of building the wrong thing quickly.

The operator experience should be:

```text
review not closed -> A9 says what is missing
review closed -> A9 enqueues one bounded execution slice
worker finishes -> A9 records evidence and returns to review/next-slice decision
```

## data_contract

Objects and fields:

- `review_closure`
  - `id`
  - `decision_status`
  - `decision_packet_path`
  - `problem`
  - `system_requirement`
  - `data_contract`
  - `state_flow`
  - `exception_flow`
  - `acceptance`
  - `out_of_scope`
  - `allowed_execution`
  - `role_signoff`
  - `closed_for_task_id`
- `task`
  - existing fields plus `decision_status`
  - must carry enough prompt fields for `task_decision_packet()`
- `run_summary`
  - existing status plus `auto_next_block`
  - should expose closure-related block reasons
- `progress/status view`
  - must distinguish empty queue from review-waiting state

Invariant:

- `decision_status: decided` is valid only for one slice.
- Closure does not mutate the product contract during execution.
- `progress.json` remains a view; `.a9/tasks` and run summaries remain evidence.

## state_flow

Normal flow:

```text
debate_next task
-> review artifact / role review / mechanism extract
-> monitor closes decision packet
-> execution_next task with closed packet fields
-> worker executes bounded slice
-> supervisor guard/check/git
-> run evidence
-> back to review for next slice
```

Idle states:

```text
queue empty + no closed next slice -> waiting_for_review_closure
queue empty + all accepted goals complete -> complete
queue/running non-empty -> active
```

## exception_flow

- Missing decision fields:
  - stay in `debate_next`
  - report missing fields
  - do not auto-next into implement/test/repair
- Worker proposes implementation from review output:
  - record as change request
  - require monitor decision before enqueue
- Worker changes product/data/state contract during execution:
  - fail or route to repair/change request
- Broad reference/session reads:
  - observation first unless they read forbidden raw session/runtime roots or
    corrupt facts/authority
- Token pressure:
  - observe and redesign context shape; do not use arbitrary fixed limits as the
    main quality control.

## reference_mechanism

- Codex: explicit compact/continuation boundaries and prompt-time context
  reconstruction.
- Aider: repo map and narrow context instead of dumping whole repositories.
- OpenClaw/Lobster: managed flow, approval/wait/resume, policy attestation.
- ECC:
  - `reference-projects/ecc/docs/SESSION-ADAPTER-CONTRACT.md`: versioned session
    snapshot and required-field validation.
  - `reference-projects/ecc/docs/PLAN-PRD-PATTERN.md`: staged PRD/plan artifacts
    consumed by the next command.
  - `reference-projects/ecc/docs/continuous-learning-v2-spec.md`: observation
    loop that promotes lessons only after scoring/evidence.

## acceptance

The next execution slice passes only when:

- `docs/requirements-review-closure.md` is default context for workers.
- `docs/project.md` says the current block is review closure, not missing code.
- Supervisor prompt doctrine includes `docs/requirements-review-closure.md`.
- Status remains accurate: current queue/running state is authoritative.
- A follow-up task can be enqueued with `decision_status: decided` and all
  required fields present.
- Checks pass:
  - `python3 -m py_compile scripts/a9_supervisor.py`
  - `python3 scripts/a9_supervisor.py status`

## out_of_scope

- No mobile UI work.
- No finance/quant work.
- No new broad source copying.
- No production communication gateway expansion.
- No hard arbitrary line/token gate.
- No global product approval.

## allowed_execution

Allowed files for the next execution slice:

- `scripts/a9_supervisor.py`
- `tests/test_supervisor.py`
- `docs/project.md`
- `docs/agent-runtime-observations.md`

Allowed work:

- add or refine status/summary fields that expose review-closure waiting
- add focused tests for closure/waiting state if runtime code changes
- update project/observation docs with evidence

Not allowed:

- implement new mobile/control features
- expand Redis gateway behavior
- rewrite worker method doctrine again unless test evidence requires it

## change_record

Changed from "24h machine is idle, continue worker" to "24h machine is waiting
for closed review decision before execution".

Reason:

- User clarified that review/requirements alignment must finish first because a
  well-reviewed requirement reduces rework far more than premature engineering.
- Recent worker evidence confirmed the system can run but still needs a stronger
  debate-to-execution handoff.

## role_signoff

Product/mainline:

- Accepts that the next product-quality improvement is review closure
  visibility and handoff, not more feature breadth.
- Rejects broad engineering gates that slow business/modeling work before the
  data/state shape is clear.

Business:

- Accepts that the business behavior is "stop at undecided boundary and ask for
  closure" rather than "keep running forever regardless of direction".
- Requires the status view to make this understandable to the operator.

Architecture:

- Accepts `.a9/tasks` and run summaries as authority, progress/status as view.
- Requires closure state to be derived from task/run/decision evidence, not from
  stale chat memory.

Test/acceptance:

- Requires at least py_compile and supervisor status evidence for this doc-only
  closure step.
- Requires focused tests if the next execution slice modifies routing/status
  logic.

Monitor:

- Approves exactly one next `execution_next` candidate: expose
  review-closure waiting state and prevent idle ambiguity.
- Does not approve broader runtime feature expansion.

## next_execution_candidate

Task id:

`implement-review-closure-status-20260603`

Route:

`execution_next`

Phase:

`implement`

Goal:

Make supervisor/status report that A9 is idle because it is waiting for review
closure when queue/running are empty and no closed next execution task exists.

Expected result:

- Operator can tell the difference between "complete" and
  "waiting_for_review_closure".
- 24 hour worker has a concrete, bounded execution slice instead of idle
  ambiguity.
