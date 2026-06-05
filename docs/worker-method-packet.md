# A9 Worker Method Packet

This packet turns the requirements-analysis method into an execution protocol.
It is not a motivational note. It is the minimum method that every non-trivial
A9 task must obey.

## Root Rule

A9 quality comes from requirements alignment before execution.

Before a large task becomes code, A9 must align:

- real business problem
- product definition
- data model
- state flow
- exception flow
- reference mechanisms
- architecture boundary
- acceptance criteria
- out-of-scope items

If these are not clear, the next step is debate, research, modeling, or review.
It is not implementation.

Review closure is defined by `docs/requirements-review-closure.md`. A review
artifact, mechanism extract, or worker recommendation is not enough. Execution
starts only after a closed decision packet approves one bounded slice.

The 24 hour workflow has two automated stages, not one:

```text
requirements debate / review / decision
-> execution backlog generation
-> continuous worker execution
```

Before the debate stage is automated, the current Codex/operator interaction
page may drive it manually as a temporary control surface. After the debate
stage is automated and the requirement is clear, human involvement should drop
to monitoring, drift correction, and exception handling.

## Two Kinds Of Next

### debate_next

Use `debate_next` when the requirement is not decided.

Allowed work:

- close-read original requirements and sessions
- collect market, product, and reference-project evidence
- reverse-model a half-built system
- extract business objects and data objects
- draft tables, fields, states, events, and flows
- list normal and exception scenarios
- compare reference mechanisms
- create open questions
- propose options and tradeoffs
- record decision changes and outdated branches

Not allowed:

- production implementation
- broad feature building
- silently choosing product scope
- treating a reference project as the answer without evaluation

### execution_next

Use `execution_next` only after the requirement is decided.

`decided` means decided for one slice, not globally decided for the whole A9
product. The execution worker must cite the decision packet source and must not
change product definition, data contract, state flow, acceptance, or out of
scope inside the implementation.

Required task packet:

```text
mainline_reason:
  Which A9 mainline this serves.
decision_status:
  decided / not_decided / partial_decision.
problem:
  The real problem, not the proposed solution name.
system_requirement:
  What the system must do.
product_definition:
  User/workflow/product behavior being created or changed.
data_contract:
  Objects, fields, tables, state, events, ownership, and meaning.
state_flow:
  Normal transitions and what each state means.
exception_flow:
  Failure, retry, audit, manual intervention, timeout, rollback.
reference_mechanism:
  Source project/file/mechanism and why it fits A9.
acceptance:
  Business and technical verification points.
out_of_scope:
  What is explicitly not done and why.
allowed_execution:
  Files, commands, checks, and boundaries.
change_record:
  What changed in direction, scope, or authority and why.
role_signoff:
  Product/mainline, business, architecture, and test approvals.
```

If this packet cannot be built, execution must stop and produce a change request.

Decision packet template (reusable for analysis output shaping):

```text
decision_status: decided / not_decided / partial_decision
problem: the real problem, not the proposed solution name.
system_requirement: required system behavior and constraints.
data_contract: objects, fields, tables, state, events, ownership, and meaning.
state_flow: normal transitions and authority order.
exception_flow: failure, repair, timeout, manual intervention, rollback.
acceptance: test, evidence, and run-signed criteria for completion.
out_of_scope: explicit exclusions for this slice.
allowed_execution: files, commands, checks, and boundaries.
change_record: what changed in direction, scope, or authority and why.
role_signoff: explicit approvals from product/mainline, business, architecture, and test roles.
```

Analysis workers must emit this template shape before proposing implementation work, and execution workers must only proceed when `route: execution_next`.

## Role Responsibilities

### Product / Mainline

Product is the product-quality pressure role.

It must:

- keep the mainline visible
- ask why this is a good product, not only whether it can be built
- research market, competitors, and reference products
- challenge weak or average solutions
- request real usage scenarios from business
- pressure architecture for efficiency, stability, and operational quality
- decide whether a mature mechanism should be copied, modified, fused, or rejected
- record what was overturned and why

### Business

Business must:

- state the real business objective
- provide normal and edge scenarios
- define rules, roles, permissions, and responsibilities
- explain what happens outside the system
- validate whether the data model reflects real work

### Architecture

Architecture must:

- start from data first
- map product definition to data, state, events, and boundaries
- keep state transitions explicit
- make audit sidecar unless audit is core business state
- treat performance as product depth after data shape is right
- compare mature architecture mechanisms before inventing

### Test / Acceptance

Test must:

- validate data model and state flow, not only API response
- convert business concerns into tests
- cover normal path, exception path, permissions, audit, timeout, and retry
- reject unverifiable acceptance
- record residual risk when full verification is not possible

### Execution Worker

Execution worker must:

- execute a decided slice
- copy mature mechanisms with source/license evidence when applicable
- keep changes scoped
- run declared checks
- record evidence and next repair
- never silently rewrite product scope, data contract, or acceptance

## Half-Built Systems

Most real product work is not greenfield.

When A9 receives a half-built system, analysis worker must first produce:

```text
current_state_model:
  What exists now.
business_object_map:
  Current objects and responsibilities.
data_model_draft:
  Existing and proposed objects, fields, states, events.
state_flow_draft:
  Current and intended transitions.
implementation_gap:
  Where current code/data/page diverges from product intent.
reference_findings:
  Mature mechanisms that match the problem.
open_questions:
  What must be decided before execution.
decision_options:
  Options, tradeoffs, and recommended decision.
review_packet:
  Product/business/architecture/test questions.
```

Only after review can this become execution backlog.

## Data First, Performance Second

Data first means the model reflects the real business.

For product-centered systems, product definition is the core. Fields carry
business meaning. State changes carry workflow meaning. Tables and events are
not implementation details; they are the product structure.

For commerce/platform layers, mature models usually recur:

- product/package/channel
- supplier/provider
- agent/sales path
- B/C/D-side users and institutions
- order/contract/payment/settlement
- permission/audit/risk

Performance second means stability, latency, throughput, cost, and recovery
prove product depth after data shape is right. Token and cost optimization must
come from architecture and context design, not arbitrary quality-killing limits.

## Copying Mature Projects

Copying is not blind implementation.

Required sequence:

```text
reference_scan
-> mechanism_extract
-> fit_gap_review
-> data/state impact
-> decision
-> implementation slice
-> tests/evidence
```

Ask:

- What problem does the donor mechanism solve?
- What data and state assumptions does it make?
- What failure modes does it handle?
- What costs or complexity does it introduce?
- Which part fits A9?
- Which part must be rejected?
- What will prove the copied mechanism works here?

## Worker Output Requirements

For analysis tasks, output:

- sources read
- business/product/data/state findings
- open questions
- decision options
- recommended debate_next
- what cannot be executed yet
- whether review closure is missing, and which closure fields are missing

For execution tasks, output:

- decision packet source
- decision source
- reference mechanism copied
- files changed
- tests/checks run
- pass/fail
- evidence paths
- next repair or next execution slice

## Non-Negotiable

No decided requirement, no execution backlog.

No review closure, no `execution_next`.

No data/state contract, no serious implementation.

No acceptance criteria, no completion claim.

No source/license evidence, no copied source.

No role alignment, no large feature execution.
