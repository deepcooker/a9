# Requirements Guide Active Checklist

Full close-reading archive:

`docs/archive/2026-06-noise-reduction/requirements-guide-close-reading-full-20260613.md`

Source extract:

`docs/source-extracts/requirements-management-analysis-guide.txt`

## Core Method

Requirements analysis is the project method, not documentation polish.

Minimum checklist before execution:

- What is the real problem and why now?
- Is the user giving a requirement or a proposed solution?
- What is must / should / could?
- What is explicitly out of scope?
- What are the business objects, fields, state, events and exception flows?
- What are the permissions, audit needs, non-functional requirements and
  acceptance criteria?
- How will this be verified by data/state/tests, not just by UI or text?

## A9 Rule

`debate_next` continues until the task shape is clear. `execution_next` starts
only after the task has a contract that a worker can execute without inventing
business logic.

