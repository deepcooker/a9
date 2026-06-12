# A9 Worker Cost Discipline Closure - 2026-06-03

This packet closes review only for one narrow observability slice.

It does not approve hard token gates or broad worker rewrites.

## decision_status

decided.

## problem

The 24 hour worker can now execute a closed `execution_next` slice, but the last
run proved its process cost discipline is still weak.

Evidence:

- Run: `.a9/runs/implement-review-closure-status-20260603-20260603T071504Z-a1`
- Result: pass, committed `01b456366bc221280b036e8fd0ddfd032b898f7b`
- Process findings: broad file slice observations and direct file change events
- Usage: input `2284009`, cached input `2188928`, uncached input `95081`, output
  `21623`, reasoning `13536`

The real problem is not that A9 lacks a numeric limit. The real problem is that
cost/process risk is visible only if the monitor manually reads several fields.

## system_requirement

A9 must expose worker cost/process discipline as a compact derived signal:

- summarize actual token usage into a small status object
- summarize process governance findings into a cost/process risk object
- print the risk in `status()`
- keep this observation-first; do not block execution by arbitrary token counts

## product_definition

The operator should be able to see, from one status view, whether the last worker
was acceptable or expensive/noisy.

Expected operator behavior:

```text
latest worker passed
runtime_state: waiting_for_review_closure
worker_cost_risk: high reason=high_input_tokens,broad_reads,direct_file_changes
```

This helps the monitor decide whether the next task should be a repair,
discipline improvement, or normal execution.

## data_contract

Derived object:

```text
worker_cost_risk:
  level: ok | observe | high
  reasons: list[str]
  actual_token_usage:
    input_tokens
    cached_input_tokens
    uncached_input_tokens
    output_tokens
    reasoning_output_tokens
  process_findings:
    findings_count
    by_kind
```

Authority:

- run summary remains authority
- `worker_cost_risk` is a compact view derived from run summary
- no hard gate is introduced

## state_flow

```text
worker run summary
-> compact_context_pressure
-> latest_process_quality
-> worker_cost_risk derived view
-> status/progress output
-> monitor decides next closure or execution slice
```

## exception_flow

- Missing usage fields:
  - risk level can still be `observe` if process findings exist
- No findings and low/empty usage:
  - risk level `ok`
- High usage or noisy process findings:
  - risk level `high` or `observe`, but status remains pass/fail based on
    existing authoritative checks
- If implementation requires new hard gates:
  - stop and return change request

## reference_mechanism

- Codex: token pressure tracking and compact handoff.
- Aider: context discipline through repo map and narrow reads.
- ECC: token optimization is policy and workflow design, not just a raw number.
- A9 observation history: `docs/agent-runtime-observations.md` shows repeated
  broad-read and direct-change issues.

## acceptance

Pass when:

- status output includes `worker_cost_risk`
- the risk is derived from actual token usage and process governance findings
- no arbitrary blocking gate is added
- focused tests cover high-cost/noisy and ok cases
- checks pass:
  - `python3 -m py_compile scripts/a9_supervisor.py tests/test_supervisor.py`
  - focused supervisor tests for the new risk helper/status output
  - `python3 scripts/a9_supervisor.py status`

## out_of_scope

- No hard token limit.
- No line-count hard gate.
- No model/provider routing change.
- No mobile/control UI work.
- No Redis gateway changes.
- No broad prompt rewrite.

## allowed_execution

Allowed files:

- `scripts/a9_supervisor.py`
- `tests/test_supervisor.py`
- `docs/agent-runtime-observations.md`

Allowed implementation:

- add compact helper(s) for cost/process risk
- add status/progress output field if needed
- add focused tests
- record observation after run

## change_record

Changed from manually noticing token/process problems after the run to exposing
them as a compact derived status signal.

Reason:

- The previous worker was functionally successful but too expensive/noisy for
  long unattended operation.
- The user explicitly rejected arbitrary numeric gate-first governance; the
  correct next step is observation and architecture-level signal quality.

## role_signoff

Product/mainline:

- Approves exposing cost/process risk so monitor can protect the mainline.
- Rejects hard numeric gates before data/state and workflow are stable.

Business:

- Accepts that "worker passed but too expensive/noisy" is a real operational
  state operators must understand.

Architecture:

- Accepts the signal as a derived view, not authority.
- Requires run summaries and process governance to remain source evidence.

Test/acceptance:

- Requires focused tests for high/noisy and ok classifications.
- Requires status output evidence.

Monitor:

- Approves one next execution slice: add compact worker cost risk status.
- Does not approve wider worker discipline rewrite yet.

## next_execution_candidate

Task id:

`implement-worker-cost-risk-status-20260603`

Route:

`execution_next`

Phase:

`implement`

Goal:

Add compact `worker_cost_risk` status derived from actual token usage and
process governance findings.
