# Reference Adoption Decision

This is the current A9 adoption decision after comparing requirements method,
plan-file workflows, role memory, graph/wiki memory, and runtime governance.

The purpose is not to rank projects by hype. The purpose is to decide which
mechanism enters which A9 layer.

## Decision Standards

A mechanism should enter A9 only when it passes at least one of these tests:

1. It preserves the requirements-analysis method.
2. It prevents goal drift after interruption, compaction, or worker resume.
3. It improves evidence traceability.
4. It reduces token waste structurally, not by arbitrary small limits.
5. It can run in sidecar/batch lanes without slowing the hot path.
6. It can be tested with deterministic artifacts.
7. It does not turn derived memory into canonical truth.

If a mechanism only looks impressive but cannot be tied to these tests, it
stays as reference only.

## Round 1: What Is The Root?

Winner: the user's requirements-analysis guide.

Reason:

- It is the method for understanding work.
- It prevents the agent from mistaking a proposed solution for a real problem.
- It forces background, scope, must/should/could, data shape, exception flow,
  security, performance, audit, and acceptance.
- It is more fundamental than any memory system.

Decision:

- Must enter every non-trivial task.
- Must shape plan files and role packets.
- Must be injected into product, requirements, architecture, test, monitor, and
  execution review.

Not enough:

- A markdown summary of the method is not enough.
- It must become a task-shaping artifact and review criterion.

## Round 2: What Keeps The Current Task Stable?

Winner: A9-owned plan lane.

Mechanism donor: `planning-with-files`.

Reason:

- It externalizes current task state into files.
- Hooks re-inject plan/progress before work.
- PreCompact and Stop behavior directly address A9's interruption problem.
- Parallel plan isolation matches A9's future multi-worker reality.
- Attestation protects against unapproved plan mutation.

Evidence from `planning-with-files` tests:

- `test_resolve_plan_dir.py`: resolver order, invalid active-plan rejection,
  newest valid plan fallback, safe slug checks.
- `test_codex_session_isolation.py`: plan context should not leak across
  sessions unless explicitly attached.
- `test_plan_attestation.py`: SHA-256 attestation, tamper detection, concurrent
  write safety.
- `test_precompact_hook.py`: compaction reminder must fire before context
  compression and surface plan hash when present.
- `test_session_catchup.py`: after session reset, recover conversation after
  the last planning-file update.

Decision:

- Adopt an A9-specific `.a9/plans/<plan-id>/`.
- Adopt A9-specific `plan.md`, `findings.md`, `progress.md`, `mistakes.md`.
- Adopt active plan pointer.
- Adopt recovery restatement before acting after interruption/resume.
- Adopt attestation later, after the basic plan lane proves useful.

Not enough:

- Do not let `planning-with-files` define requirements method.
- Do not use one root `task_plan.md` for all A9 work.
- Do not rely on hooks alone; supervisor and mobile/control must understand
  the plan directory.
- Do not copy its default role model. It assumes the same agent can freely shape
  plan phases and decisions. A9 cannot allow an execution worker to silently
  redefine product goals, requirements, scope, or acceptance.
- Do not copy its completion model. Counting `Status: complete` phases is not
  enough for A9. A9 completion must check acceptance, declared tests, evidence,
  role review, and monitor confirmation.
- Do not copy root fallback behavior. A9 should prefer explicit plan ids and
  fail visibly when the expected plan is missing, because silent fallback can
  bind a worker to the wrong task.
- Do not use hooks as the authority. Hooks are reminders/interceptors; managed
  flow and supervisor state are the authority.

Role conflict resolution:

| Artifact | Owner | Worker permission |
| --- | --- | --- |
| `plan.md` problem/goal/scope/acceptance | human monitor + product/mainline + requirements | read only by default |
| `plan.md` phase status | monitor/supervisor | propose status change only |
| `findings.md` reference evidence | worker can append | append with source refs |
| `progress.md` actions/tests | worker can append | append only |
| `mistakes.md` errors/drift | worker can append | append only |
| `change_request.md` | worker can create | propose plan/goal/scope change |

This preserves A9's role boundary: the worker executes and reports; it does not
become product manager, requirements analyst, or architect by editing the
contract.

A9-specific completion contract:

```text
complete only if:
  plan acceptance is satisfied
  declared checks pass or failures are documented
  evidence refs exist
  no unresolved hard blocker exists
  worker did not change contract fields
  monitor/supervisor records completion audit
```

So the first A9 implementation should copy resolver/isolation/catchup style
tests before it copies hook behavior.

## Round 3: What Becomes Long-Term Memory?

Winner: GBrain conceptually, with LLM-Wiki as the file/wiki implementation
reference.

Reason:

- GBrain has the right memory product shape: synthesized answers with citations,
  gap analysis, schema packs, typed graph edges, contradiction/stale maintenance,
  scoped access, and nightly dream cycles.
- LLM-Wiki has the right agent workflow shape: topic wikis, source ingestion,
  collector catalogs, research/query/resume, archives, lint repair, and
  runtime-neutral behavior with thin wrappers.

Decision:

- Adopt the idea of a durable brain/wiki layer, not as hot path.
- Compile selected evidence into wiki topics with citations and known gaps.
- Add archives for expired/downgraded branches so they are preserved but not
  injected by default.
- Add lint/repair/contradiction sidecars before any "self-evolving" writeback.

Not enough:

- Do not install a full brain stack before A9's plan lane works.
- Do not let wiki/brain summaries replace raw session/run/git/test evidence.
- Do not ingest everything; start from session close-reading, reference scans,
  run reviews, and mistakes.

## Round 4: What Becomes Graph?

Winner: Graphify first, GraphRAG later.

Reason:

- Graphify gives immediate repo/reference orientation: graph.json,
  GRAPH_REPORT.md, confidence tags, query-first behavior.
- It can help workers avoid broad grep and reduce prompt bloat.
- GraphRAG is more powerful for narrative/private-data graph memory, but it is
  heavier and costlier.

Decision:

- Use Graphify-style graph outputs first for repo/reference orientation.
- Treat graph output as a derived index with confidence tags.
- Defer GraphRAG-style full indexing until A9 has enough curated evidence and
  cost metrics.

Not enough:

- Do not graph the whole world now.
- Do not put graph indexing in the worker hot path.
- Do not treat inferred graph edges as facts.

## Round 5: What Controls Runtime?

Winners: Codex, OpenClaw/Lobster, LangGraph, Hermes.

Reason:

- Codex: raw ordered history, compact boundary, goal state, resume/usage-limit
  lifecycle.
- OpenClaw/Lobster: managed flow, approval/wait/resume, policy attestation,
  extension boundaries.
- LangGraph: durable execution, checkpoint, human interrupt/resume, traces.
- Hermes: async background review, curator, trajectory compression, isolated
  sidecar tool surface.

Decision:

- Keep Codex/OpenClaw/Lobster as runtime spine.
- Keep Hermes-like review as sidecar only.
- Keep LangGraph as checkpoint/lineage reference.
- Use mem0 semantics only for scoped extracted memories, not raw evidence.

Not enough:

- Do not let runtime gates outrank requirements method.
- Do not let sidecar review block hot path unless there is a safety/license/data
  corruption issue.

## Final Layering

```text
requirements method
  -> plan directory for current task
  -> role packets
  -> 24h worker execution
  -> run evidence
  -> sidecar review
  -> wiki/brain compilation
  -> graph/search index
  -> contradiction / drift / gap report
  -> next plan
```

Canonical truth remains:

- raw Codex/operator session
- A9 runtime runs/tasks/flow state
- git commits/diffs
- tests/logs/traces
- original reference source paths and licenses

Derived views:

- compact summaries
- plan progress
- memory commits
- wiki articles
- graph indexes
- role packets

Derived views can guide work, but they must cite canonical truth.

## Must Enter Now

- Requirements-analysis task-shaping card.
- A9-owned `.a9/plans/<plan-id>/` isolated plan directory.
- Recovery restatement after interruption/resume.
- Worker prompt generation from plan/finding/progress evidence.
- Missing plan fields as observation, not hard gate.
- Plan contract ownership rules: worker cannot silently change problem, goal,
  scope, out-of-scope, or acceptance.

## Should Enter Soon

- Role packets generated from plan + causal memory + selected evidence.
- Sidecar review proposal lane.
- Wiki topic stubs for session close-reading, reference scans, run reviews, and
  mistakes.
- Graphify-style repo/reference graph experiment for one bounded area.

## Observe First

- Plan attestation.
- Stop/PreCompact enforcement.
- GBrain-like schema packs.
- LLM-Wiki-style lint/repair.
- Contradiction/staleness reports.
- Graph search as worker default.

## Defer

- Full GraphRAG indexing.
- Full GBrain installation as infrastructure.
- Automatic self-evolution writes.
- Pure AI self-review without external evidence.
- Hard gates based on missing plan fields before we have run data.

## First Implementation Slice

Build the smallest plan lane:

1. `.a9/plans/<plan-id>/plan.md`
2. `.a9/plans/<plan-id>/findings.md`
3. `.a9/plans/<plan-id>/progress.md`
4. `.a9/plans/<plan-id>/mistakes.md`
5. `.a9/plans/<plan-id>/change_request.md` only when worker proposes scope or
   acceptance changes.
6. `.a9/plans/.active_plan`
7. A deterministic `plan-create` helper.
8. A deterministic `plan-status` helper that prints the recovery restatement.
9. Supervisor prompt hydration from the active plan.

The first real run should prove whether workers drift less and whether monitor
intervention becomes easier.
