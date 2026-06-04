# A9 Context Governance

This document is the routing table for A9 context. Its job is to keep the
mainline small enough for workers to follow, while preserving raw evidence for
audit and close reading.

## Core Rule

Workers must not treat every markdown file as current truth.

A9 context has five layers:

1. canonical current context
2. task contracts
3. evidence and logs
4. reference and research
5. archive and noise

Only layers 1 and 2 are default worker context. Layers 3 to 5 are read only
when the task packet names the exact path and explains why it is needed.

## Canonical Current Context

These files define the current mainline:

- `AGENTS.md`: top-level agent rules, phase model, hard constraints.
- `docs/context-governance.md`: this context routing table.
- `docs/project.md`: current A9 product layers, architecture, progress, next work.
- `原始想法需求.md`: original product philosophy and requirement source.
- `docs/worker-method-packet.md`: requirements-analysis and worker method.
- `docs/requirements-review-closure.md`: review completion standard and
  debate-to-execution closure gate.
- `docs/session-causal-memory.md`: causal changes, stale branches, current decision memory.
- `docs/a9-ultimate-architecture-aggregation.md`: current highest-shape
  aggregation draft for human/GPT debate. It is current context for architecture
  discussion, but not an implementation decision packet.

If these files conflict, resolve in this order:

1. newest explicit human direction in the current operator session
2. `AGENTS.md`
3. `docs/context-governance.md`
4. `docs/requirements-review-closure.md`
5. `docs/session-causal-memory.md`
6. `docs/a9-ultimate-architecture-aggregation.md`
7. `docs/project.md`
8. `原始想法需求.md`

Raw session evidence can overturn summaries, but only after close reading and a
recorded causal-memory update.

## Task Contracts

These files shape current work but are not global truth forever:

- `docs/a9-current-decision-packet.md`
- `docs/a9-current-review-packet.md`
- `docs/a9-current-role-review.md`
- `docs/a9-runtime-review-closure-2026-06-03.md`
- `docs/a9-worker-cost-discipline-closure-2026-06-03.md`
- `docs/stage-handoff-2026-06-01.md`
- `docs/communication-governance-worker-task.md`
- `docs/a9-ultimate-architecture-aggregation.md` when the current task is
  architecture debate, GPT/web reconstruction, or highest-shape decision
  closure. It must not be treated as permission to implement every listed
  layer.

Task contracts must state whether the route is `debate_next` or
`execution_next`. If the task contract is stale or contradicts canonical
context, the worker must produce a change request instead of implementing.

## Evidence And Logs

These files are evidence indexes, not default prompt material:

- `docs/session-raw-close-reading.md`
- `docs/session-raw-summary.md`
- `docs/communication-observation-log.md`
- `docs/agent-runtime-observations.md`
- `docs/mistakes.md`
- `docs/copied-mechanisms.md`

Evidence files preserve facts and failure history. They are intentionally large.
Workers may read only bounded slices named by a task packet, such as a section,
line range, run id, turn id, or specific finding.

The rule is: preserve evidence on disk, but do not hydrate it into worker
context by default.

## Reference And Research

These files support decisions and copying strategy:

- `docs/reference-adoption-decision.md`
- `docs/reference-selection-reassessment.md`
- `docs/requirements-plan-file-reference-scan.md`
- `docs/memory-graph-wiki-reference-scan.md`
- `docs/role-memory-reference-scan.md`
- `docs/agent-governance-research.md`
- `docs/private-model-strategy.md`
- `docs/runtime-governance-review-2026-05-29.md`
- `docs/vendor-strategy.md`
- `docs/patch-diff-discipline.md`
- `docs/production-daemon.md`
- `docs/communication-governance-framework.md`
- `docs/moe-review-methodology.md`
- `session-governance.md`
- `THIRD_PARTY_NOTICES.md`

Research is not a command to build. A worker must extract a mechanism, compare
it to A9's current requirement, and cite the exact source before copying.

## Source Extracts And Original Ideas

These are preserved source materials:

- `docs/source-extracts/requirements-management-analysis-guide.txt`
- `docs/source-extracts/original/requirements-management-analysis-guide.doc`
- `archive/original-ideas/*`

They are not stale garbage. They are raw source material and must be routed
through close reading before they change canonical context.

## Noise Policy

Noise is any file, prompt, code path, or log that can bias the worker without
being a current contract or bounded evidence.

Examples:

- root-level scratch outputs
- old plan fragments without date, route, or owner
- broad logs copied into prompt
- stale UI/product branches treated as current runtime direction
- gate experiments that remain after the business shape changed
- unused code paths that no current task, test, or documented runtime uses

Noise handling order:

1. preserve raw evidence if it contains facts
2. label or archive stale material
3. delete trivial scratch files
4. update `docs/README.md` so workers enter through the right file
5. record why a branch became stale in `docs/session-causal-memory.md`

Cleanup is part of requirements analysis. It is not polish. A dirty context
makes the 24 hour worker execute the wrong product faster.

## Worker Read Discipline

Before reading docs broadly, a worker must state a bounded evidence plan:

```text
mainline docs:
  exact canonical files being used.
task docs:
  exact task contract files being used.
evidence slices:
  exact paths and bounded sections or run ids.
reference slices:
  exact project/files/mechanisms being scanned.
not reading:
  large raw logs, archived originals, stale branches, unrelated docs.
```

If a task requires broad close reading, use `debate_next` or
`session_close_reading`; do not disguise it as implementation.
