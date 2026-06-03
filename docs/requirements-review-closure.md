# A9 Requirements Review Closure

This document defines when A9 review is actually finished.

It is the bridge between the requirements-analysis method and the 24 hour
execution machine. If this closure is missing, A9 must stay in `debate_next`.

## Core Rule

Discussion is not closure.

Research is not closure.

A worker-written analysis document is not closure.

Review is closed only when the roles have challenged the plan, the data/state
shape is explicit, the exceptions are explicit, the acceptance evidence is
explicit, and the monitor records a decision packet that allows a specific
`execution_next` slice.

## Why This Exists

A9 already has an execution loop. The failure mode is not that the worker cannot
run. The failure mode is that an undecided idea becomes implementation too soon.

The right order is:

```text
business goal
-> requirements analysis
-> reference scan
-> mechanism extract
-> data/state model
-> role review and pressure
-> decision packet
-> execution backlog slice
-> 24 hour worker execution
```

If the order is reversed, A9 can copy mature projects quickly but still build
the wrong thing.

## Review Stages

### 1. Problem Framing

Required output:

- the real problem, not the proposed implementation
- why this is the current mainline
- what business or runtime pain proves the problem exists
- what is explicitly not being solved now

Exit condition:

- Product/mainline accepts the problem statement.
- Stale or competing branches are named.

### 2. Evidence And Reference Scan

Required output:

- exact local source paths read
- reference projects compared
- mechanisms extracted
- fit/gap notes for A9
- license/source/commit when copying is possible

Exit condition:

- The team knows what is copied conceptually, what can be copied as source, and
  what is rejected.

### 3. Data And State Model

Required output:

- business objects
- system objects
- fields and meanings
- authoritative states
- normal state transitions
- exception transitions
- audit evidence

Exit condition:

- Architecture and test roles can explain the system through data and state,
  not through UI or code names.

### 4. Role Review

Each role must produce both pressure and acceptance.

Product/mainline:

- checks whether the work serves the current mainline
- challenges average solutions
- names better reference mechanisms if available
- decides what to copy, fuse, reject, or postpone

Business:

- validates real scenarios, edge cases, permissions, and responsibilities
- checks whether the data model reflects real work

Architecture:

- validates data ownership, state flow, boundary, performance, recovery, and
  audit shape
- rejects engineering polish that hides a wrong data model

Test/acceptance:

- turns business and state claims into evidence
- validates normal path, exception path, timeout, retry, audit, and residual risk

Monitor:

- records the decision
- blocks premature execution
- creates the next bounded task only after closure

Exit condition:

- Every role records at least one accepted point and one risk, rejection, or
  residual concern.

### 5. Decision Packet

Required fields:

```text
decision_status: decided | partial_decision | not_decided
problem:
system_requirement:
product_definition:
data_contract:
state_flow:
exception_flow:
reference_mechanism:
acceptance:
out_of_scope:
allowed_execution:
change_record:
role_signoff:
```

`decision_status: decided` is per slice. It is never global permission to build
the whole product.

Exit condition:

- Missing fields are resolved or explicitly marked as out of scope.
- `allowed_execution` names files, commands, checks, and write boundaries.
- `role_signoff` names product/mainline, business, architecture, and test
  positions.

### 6. Execution Backlog Slice

The backlog item must be small enough for a worker to execute without inventing
product scope.

Required output:

- one task id
- route `execution_next`
- phase
- allowed paths
- declared checks
- exact acceptance evidence
- next repair condition

Exit condition:

- The task can be enqueued without relying on hidden chat context.

## Closure States

### `not_decided`

Meaning:

- Review has not produced enough agreement.

Allowed next:

- `debate_next`
- close reading
- reference scan
- role review
- data/state modeling

Not allowed:

- production implementation
- broad feature expansion
- automatic next execution

### `partial_decision`

Meaning:

- A direction is emerging, but not enough fields are decided for execution.

Allowed next:

- bounded review or modeling
- a decision packet repair task
- a doc-only review artifact if allowed by task scope

Not allowed:

- treating the analysis artifact as implementation approval

### `decided`

Meaning:

- One narrow execution slice is approved.

Allowed next:

- `execution_next` task
- implementation, tests, evidence, git governance

Not allowed:

- expanding beyond the slice
- changing product/data/state contract inside the worker

## Current A9 Application

For the current 24 hour runtime line, review is not globally finished.

What is closed:

- A9 should use a requirements-first process before execution.
- Data/state shape is the first serious acceptance standard.
- Performance/stability/cost is second and must be solved architecturally, not
  by arbitrary quality-killing limits.
- Gates are observation-first unless facts, authority, license, security,
  declared checks, or irreversible state are at risk.
- Reference-first copying remains the execution method.

What is not closed:

- the exact next `execution_next` slice after ECC mechanism extraction
- the role signoff for that slice
- the concrete data/state contract for review artifacts becoming backlog tasks
- the automatic route from review output to decided execution task

Therefore the 24 hour worker may run only review/modeling tasks until the next
decision packet is closed.

## Monitor Checklist Before Enqueue

Before putting a non-trivial task into `.a9/tasks/queue`, the monitor must check:

- Does the task state `decision_status`?
- If not decided, is it explicitly `debate_next` and doc/research/modeling only?
- If decided, are all decision packet fields present?
- Are allowed paths narrow and tied to the decision?
- Are declared checks listed?
- Is the reference source/license/commit available when copying is involved?
- Is out-of-scope clear enough to stop scope creep?
- Can a new Codex window understand the task without private memory?

If any answer fails, the next task is a review repair task, not implementation.

## Worker Rules

Analysis worker:

- may write review artifacts only when the task explicitly allows doc output
- must list open questions and what cannot be executed yet
- must not create implementation backlog as if it were approved

Execution worker:

- must cite the decision packet source
- must not change product definition, data contract, state flow, acceptance, or
  out-of-scope
- must return a change request if the execution packet is incomplete or stale

## Completion Claim Standard

A9 may say "review is complete for this slice" only when:

- `decision_status: decided`
- all required packet fields are present
- role signoff is explicit
- out-of-scope is explicit
- allowed execution is explicit
- acceptance evidence is explicit
- the next queued task is `execution_next`

Anything less is still review in progress.
