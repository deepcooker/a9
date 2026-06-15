# A9 Method

This is the single active method contract.

## Order

```text
discussion / research / modeling / review / decision / execution
```

Do not execute before the requirement is shaped. Debate first, then run many
small execution tasks.

## Requirement Shape

Every non-trivial task must state:

- goal and real problem
- route: `debate_next` or `execution_next`
- data objects, fields and meaning
- state flow and exception flow
- must / should / could
- out of scope
- reference mechanisms to copy
- allowed paths and tools
- checks and acceptance

## Standards

- Data first: schema, state, event and table shape must match real business.
- Performance second: latency, stability and cost matter after data shape is
  correct.
- Gates observe early. They block only destructive, unsafe, unlicensed or
  unrecoverable behavior.
- Product role pressures the mainline and can reject weak solutions.
- Architecture role owns state, boundaries, failure modes and performance.
- Test role turns business concerns into verifiable checks.

## Worker Contract

Execution workers only execute shaped slices. If the task lacks goal, data,
state, acceptance or boundaries, return a change request instead of inventing
business logic.

## Closure

A review is closed only when the decision, evidence, tradeoffs, stale branches,
acceptance and next tasks are explicit. Otherwise it remains debate.
