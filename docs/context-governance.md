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
- `docs/current-mainline.md`: current execution priority and freeze points.
- `docs/project.md`: current A9 product layers, architecture, progress, next work.
- `docs/architecture/a9-runtime-monitor-foundation.md`: current P0 foundation
  architecture for runtime, monitor, and communication.
- `docs/decisions/ADR-0001-a9-highest-form.md`
- `docs/decisions/ADR-0002-runtime-monitor-priority.md`
- `docs/decisions/ADR-0003-communication-foundation.md`
- `docs/decisions/ADR-0004-reference-vendor-selection.md`
- `docs/decisions/ADR-0005-nzx-is-first-business-app.md`
- `原始想法需求.md`: original product philosophy and requirement source.
- `docs/worker-method-packet.md`: requirements-analysis and worker method.
- `docs/requirements-review-closure.md`: review completion standard and
  debate-to-execution closure gate.
- `docs/session-causal-memory.md`: causal changes, stale branches, current decision memory.
- `docs/a9-ultimate-architecture-aggregation.md`: current highest-shape
  aggregation draft for human/GPT debate. It is current context for architecture
  discussion, but not an implementation decision packet.
- `docs/external-gpt/2026-06-04/intake.md`: accepted intake of the GPT review
  package. It upgrades the next default route to P0 architecture decision
  packet before further runtime/mobile/communication implementation.

If these files conflict, resolve in this order:

1. newest explicit human direction in the current operator session
2. `AGENTS.md`
3. `docs/context-governance.md`
4. `docs/current-mainline.md`
5. `docs/architecture/a9-runtime-monitor-foundation.md`
6. `docs/decisions/ADR-0002-runtime-monitor-priority.md`
7. `docs/decisions/ADR-0003-communication-foundation.md`
8. `docs/requirements-review-closure.md`
9. `docs/session-causal-memory.md`
10. `docs/external-gpt/2026-06-04/intake.md`
11. `docs/a9-ultimate-architecture-aggregation.md`
12. `docs/project.md`
13. `原始想法需求.md`

Raw session evidence can overturn summaries, but only after close reading and a
recorded causal-memory update.

## Task Contracts

These files shape current work but are not global truth forever:

- `docs/a9-current-role-review.md`
- `docs/stage-handoff-2026-06-01.md`
- `docs/a9-ultimate-architecture-aggregation.md` when the current task is
  architecture debate, GPT/web reconstruction, or highest-shape decision
  closure. It must not be treated as permission to implement every listed
  layer.
- `docs/external-gpt/2026-06-04/A9_AgentOS_金融交易环境重构决策包.md`
  when the current task is P0/P1/P2 route planning. Its implementation
  suggestions are candidates until converted into ADRs and task contracts.
- `docs/current-mainline.md` when the current task could drift into mobile UI,
  NZX implementation, compute RWA, or broad workspace refactor. It is the
  current freeze/priority source.
- `docs/execution_next/0001-runtime-monitor-foundation-packet.md` is the
  current first execution packet for monitor review. It does not authorize code
  implementation until monitor approval creates the next implementation slice.

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

Evidence index files preserve pointers to facts and failure history. Full
historical evidence has been moved under `docs/archive/evidence/`. Workers may
read archived evidence only through bounded slices named by a task packet, such
as a section, line range, run id, turn id, or specific finding.

The rule is: preserve evidence on disk, but do not hydrate it into worker
context by default.

## Reference And Research

These files support decisions and copying strategy:

- `docs/reference-adoption-decision.md`
- `docs/reference-selection-reassessment.md`
- `docs/vendor-strategy.md`
- `docs/external-gpt/2026-06-13/a9-a3b-boundary-intake.md`: accepted external
  review evidence for the A9/A3B boundary. It is not default worker context and
  does not authorize A3B code or training work.
- `docs/patch-diff-discipline.md`
- `docs/production-daemon.md`
- `docs/communication-governance-framework.md`
- `docs/moe-review-methodology.md`
- `session-governance.md`
- `THIRD_PARTY_NOTICES.md`

Archived research and old closures now live under:

- `docs/archive/2026-06-history/`
- `docs/archive/2026-06-noise-reduction/`
- `docs/archive/2026-06-execution-results/`
- `docs/archive/evidence/`

They are not active task contracts or reference commands. Use them only as
bounded evidence when a task names the exact file and reason.

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
