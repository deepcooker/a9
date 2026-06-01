# Requirements Method And Plan File Reference Scan

This document records why A9 must treat the user's requirements-analysis guide
as the root method, and why plan-file workflows are a better execution boundary
than free-form chat instructions.

Boundary note: `planning-with-files` solves current-task working memory and
interruption recovery. It does not replace the requirements method or the
durable graph/wiki/brain layer described in
`docs/memory-graph-wiki-reference-scan.md`.

## Decision Boundary

Do not let implementation mechanics replace requirements thinking.

For A9:

```text
requirements-analysis method
-> task-shaping card / plan file
-> reference_scan
-> mechanism_extract
-> bounded implementation
-> tests/evidence
-> sidecar review
```

The requirements-analysis method is the dao. Copying mature projects, sidecar
audit, Redis/Rust gateways, deterministic apply, and model routing are shu.

## Internal Source

Local source:

- `docs/source-extracts/original/requirements-management-analysis-guide.doc`
- `docs/source-extracts/requirements-management-analysis-guide.txt`
- `docs/requirements-guide-close-reading.md`

Core extracted rules:

- Understand background and purpose before implementation.
- Distinguish user need from proposed solution.
- Translate user need into system requirement.
- Separate must / should / could.
- Compare solutions by coupling, complexity, risk, and value.
- Write requirements so they are unambiguous, complete, verifiable, consistent,
  modifiable, and traceable.
- Include normal flow, exception flow, security, environment, performance, and
  audit before development.
- Record changes, non-goals, and confirmations.

A9 interpretation:

- Every non-trivial worker task needs a task-shaping card.
- The card is not bureaucracy; it prevents the worker from drifting.
- `reference_scan` must answer the shaped requirement, not browse broadly.
- Sidecar review checks whether the plan and implementation still match the
  original problem.

## Primary External Reference: Planning with Files

Local evidence:

- `reference-projects/planning-with-files`
- local commit: `6f94643`
- license: MIT
- `reference-projects/planning-with-files/skills/planning-with-files/SKILL.md`
- `reference-projects/planning-with-files/docs/codex.md`
- `reference-projects/planning-with-files/docs/workflow.md`
- `reference-projects/planning-with-files/templates/task_plan.md`
- `reference-projects/planning-with-files/templates/findings.md`
- `reference-projects/planning-with-files/templates/progress.md`

Mechanisms worth copying:

- Persistent markdown planning files act as working memory on disk.
- The core files are `task_plan.md`, `findings.md`, and `progress.md`.
- The agent must create a plan before complex tasks.
- The agent must re-read the plan before major decisions.
- Research/browser discoveries are written into `findings.md`, especially after
  repeated view/search operations.
- Progress, files changed, tests, and errors are written into `progress.md`.
- Every error is logged so the agent does not repeat the same failed action.
- The "5-question reboot test" checks whether the agent can recover context:
  where am I, where am I going, what is the goal, what have I learned, what have
  I done.
- Codex integration uses lifecycle hooks: `SessionStart`, `UserPromptSubmit`,
  `PreToolUse`, `PostToolUse`, `Stop`, and `PreCompact`.
- Hooks re-inject active plan and recent progress before work.
- Hooks remind the agent to update progress after edits/tools.
- Stop hooks check incomplete phases before the agent exits.
- PreCompact hooks remind the agent to flush progress before compaction.
- Parallel plan isolation uses `.planning/<plan-id>/` and `.planning/.active_plan`.
- Plan attestation records a SHA-256 and blocks plan injection if the plan has
  changed without re-approval.
- Session catchup recovers context from previous agent session storage.
- `plan-goal` and `plan-loop` compose file plans with long-running goal/loop
  behavior.

A9 interpretation:

- `planning-with-files` is closer to A9's need than a generic task plan. It is
  a context-governance mechanism, not only a planning template.
- Its role model conflicts with A9 if copied directly: it lets the working
  agent reshape plan phases and decisions, while A9 requires plan-contract
  ownership by monitor/product/requirements roles.
- A9 should not start with a single free-form worker prompt for complex tasks.
  It should start from a plan directory.
- A9 needs separate files for:
  - task contract / plan
  - findings / reference evidence
  - progress / run log
  - errors / mistakes
  - optional attestation / approved hash
- A9 should copy the hook idea into its own runtime:
  - before worker prompt generation, inject plan summary and recent progress
  - before tool/apply, re-check active plan
  - after apply/test, update progress
  - before compaction/handoff, flush progress and current phase
  - before stop/complete, verify unfinished phases and acceptance
- Plan files should be treated as structured data, not executable prompt
  instructions, to reduce prompt-injection risk.
- For parallel 24h tasks, A9 should use isolated plan directories instead of one
  shared `task_plan.md`.

What A9 should not copy blindly:

- A9 should not use root-level `task_plan.md` as the long-term default because
  the project runs multiple lanes. Use isolated plan directories.
- A9 should not rely on hooks alone; the supervisor/control API should also
  understand the plan directory.
- A9 should not make missing plan fields hard blockers immediately. First run
  them as observation and monitor drift.
- A9 should not use phase-status counting as completion. Completion needs
  acceptance, tests, evidence, role review, and monitor audit.
- A9 should not allow workers to update contract fields; they must write
  change requests.

## Secondary External References

### GitHub Copilot Plan Agent

Reference:

- https://learn.microsoft.com/en-us/visualstudio/ide/copilot-plan-agent

Mechanisms worth copying as secondary evidence:

- Planning is a separate mode from implementation.
- The planning agent explores with read-only tools.
- Plans are saved as markdown files under `.copilot/plans/`.
- The plan file is the task source of truth.
- The user can edit the plan file directly.
- Implementation starts only after explicit handoff to agent mode.

A9 interpretation:

- A9 should use plan/task files as canonical execution contracts.
- A plan file should be editable by the monitor/human before worker execution.
- Worker execution should reference the plan file id/path, not only chat text.

### Coder Plan Mode

Reference:

- https://coder.com/docs/ai-coder/agents

Mechanisms worth copying as secondary evidence:

- Plan mode can inspect workspace state and execute exploration commands.
- File writes are limited to the chat-specific plan file under `.coder/plans/`.
- The agent can ask structured clarification questions.
- `propose_plan` snapshots the current plan into the transcript.
- Some tools are unavailable in plan mode, keeping planning from becoming hidden
  implementation.

A9 interpretation:

- A9 can allow exploration during task shaping but restrict writes to the plan
  artifact.
- Planning and implementation should have different allowed tool surfaces.
- The plan snapshot should be evidence for later review.

### ralphex

Reference:

- https://github.com/umputun/ralphex
- https://pkg.go.dev/github.com/umputun/ralphex/pkg/plan

Mechanisms worth copying as secondary evidence:

- A plan markdown file drives autonomous execution.
- Tasks are executed one by one in fresh coding sessions.
- Review-only mode can run multi-agent review on existing branch changes.
- The `plan` package provides plan file selection and manipulation.
- Rate-limit waiting and model separation are explicit runtime concerns.

A9 interpretation:

- A9's 24h worker should execute from a stable plan/task file, not from an
  expanding chat tail.
- Fresh worker sessions should receive a bounded packet derived from the plan.
- Review can be run as a separate phase over the branch/diff with the same plan
  as context.

### Aider Architect / Editor

Reference:

- https://aider.chat/docs/usage/modes.html

Mechanisms worth copying:

- Ask/planning mode is separate from code-editing mode.
- Architect mode separates reasoning/planning from concrete file edits.
- Editor mode turns the plan into specific edit instructions.

A9 interpretation:

- A9 should separate product/requirements/architecture reasoning from execution
  editing.
- The execution worker should not silently redefine the plan while editing.

## What This Changes In A9

The current A9 rules say "copy reference projects first." That is still right,
but it is not the first question.

The correct order is:

```text
1. What real problem are we solving?
2. What system behavior should exist?
3. What data/state/event shape represents that behavior?
4. What reference projects have solved a similar mechanism?
5. What minimal slice can prove the behavior?
6. What tests/evidence prove it?
7. What should sidecar review learn after the run?
```

If a worker starts at step 4, it may copy the wrong thing very efficiently.

## A9 Plan File Shape

A9 should introduce isolated plan directories before broad automation. This is
not a direct copy of `planning-with-files`; it is an A9-owned contract with
stricter role boundaries.

```text
.a9/plans/<plan-id>/
  plan.md
  findings.md
  progress.md
  mistakes.md
  change_request.md
  attestation.json
```

Ownership:

- `plan.md` contract fields are owned by human monitor, product/mainline, and
  requirements roles.
- Execution workers read `plan.md` but do not silently change problem, goal,
  scope, out-of-scope, or acceptance.
- Workers append evidence to `findings.md`, actions/tests to `progress.md`, and
  errors/drift to `mistakes.md`.
- If a worker thinks the plan is wrong, it writes `change_request.md` and stops
  for monitor review.

The initial `plan.md` should include:

```text
schema: a9.plan.v1
plan_id:
goal_id:
source:
problem:
why_now:
user_need:
system_requirement:
must_should_could:
out_of_scope:
solution_type:
data_shape:
state_event_contract:
normal_flow:
exception_flow:
security_audit:
performance_nfr:
reference_entries:
implementation_slice:
allowed_paths:
allowed_commands:
declared_checks:
acceptance:
change_record:
monitor_notes:
```

This artifact should become the source for:

- role packets
- worker prompt generation
- monitor review
- sidecar memory commits
- final audit

## Provisional Next Implementation

Do not add another hard gate first.

The next useful implementation should be a small plan-file lane:

1. Add `.a9/plans/<plan-id>/` as the canonical isolated plan artifact location.
2. Add a deterministic helper that creates `plan.md`, `findings.md`,
   `progress.md`, and `mistakes.md` from a task-shaping card.
3. Add a simple active-plan pointer for the supervisor, not for human memory
   only.
4. Add worker prompt generation from the active plan directory.
5. Keep missing fields as observation/warnings at first.
6. Add a change-request path instead of letting workers rewrite plan contract
   fields.
7. Run one 24h worker task from the plan directory and compare quality.
8. Only later add attestation, hooks, and stop/compact enforcement after the
   data shape proves useful.

Only after multiple runs should missing fields become blocking policy.
