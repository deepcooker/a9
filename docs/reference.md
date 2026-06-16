# A9 Reference And Copy Policy

A9 copies mature open-source mechanisms first, then adapts them locally with
tests and evidence.

## Copy Rules

1. Verify license before copying source.
2. Record project, commit, path, license, destination and purpose.
3. Preserve required notices.
4. Prefer mechanism copy before source copy.
5. Do not copy non-open-source product references.

## Use-Through Rule

Reference projects are not architecture decisions by themselves. A9 must not
adopt a mechanism just because its README, demo or public reputation looks
strong.

Correct order:

```text
download locally
-> run or inspect enough to understand the real behavior
-> use it against an A9-shaped task
-> identify duplicate/overlapping mechanisms
-> write the failure modes and tradeoffs
-> build a small local spike/eval
-> decide whether to join A9, stay as reference, or be rejected
```

This is intentionally slower up front. Architecture quality matters more than
early feature velocity. A mechanism that has not been locally tried, compared
and evaluated is only a candidate, not part of the A9 architecture.
One day spent using the right reference deeply can save hundreds or thousands
of later correction loops.

Selection standards:

- Keep the best mechanism per layer; do not merge duplicate ideas just because
  multiple projects implement them.
- Prefer projects that have runnable behavior, tests, clear boundaries and
  recoverable failure modes.
- If a copied mechanism only works after A9-specific patches, the patch and the
  reason must be recorded.
- A reference can be downgraded or removed after local trial.
- Passing a small spike does not make it production; it only allows bounded
  integration behind tests/evidence.

## Rust And Gateway Baseline

A9 is not a Python-only automation script. Python remains useful for model,
business and personalization logic, but the stable control/runtime skeleton
must be selected and tested around Rust-first gateway and interaction behavior.

Required use-through baselines:

- Codex is the primary interaction/runtime reference. A9 must deeply test its
  CLI loop, tool protocol, context/compact/resume behavior, apply discipline,
  sandbox/approval model and long-running goal/session handling before claiming
  equivalent interaction quality.
- Barter-rs is the trading-grade gateway reference. A9 must deeply test its
  reconnect/backoff/error-action/stream handling patterns before designing
  private-node, worker-transport or market-facing gateway behavior.
- OpenClaw/Lobster remains the managed-flow/tool-envelope reference, but it
  does not replace Codex for interaction quality or Barter-rs for low-latency
  gateway reliability.

The intended architecture is layered, not either/or:

```text
Rust gateway/control hot path
-> Redis/MySQL state and evidence plane
-> Codex-like interaction/runtime
-> Python model/business logic where it has leverage
-> mobile/control and higher product surfaces
```

Any communication/runtime choice must be evaluated for latency, reconnect,
idempotency, observability, recoverability and bounded context behavior. UI
convenience is not allowed to define the runtime architecture.

## Priority References

- MemPalace: verbatim-first raw storage, per-message drawer, palace hierarchy,
  semantic + hybrid retrieval, wakeup/bootstrap packs, temporal KG,
  precompact/save hooks, provider/backend abstraction and rebuildable indexes.
- Codex: loop, tools, sandbox, approval, context and compaction.
- OpenClaw/Lobster: managed flow, approval/wait/resume, policy attestation,
  plugin/extension shape, memory governance and tool envelope.
- Barter-rs: reconnect, backoff, error action and trading-grade gateway
  reliability.
- Aider: repo map, token budgeting, diff/edit discipline and architect/editor
  split.
- LangGraph: checkpoint, parent lineage and channel history.
- mem0: memory add/search/get/history semantics.
- OpenHands, Continue, Cline, Roo, SWE-agent, opencode, aichat: terminal UX,
  provider abstraction, tool boundary and execution harness.

Claude Code and Antigravity are product references only unless an open-source
repo/license is verified.

## Active Copied Mechanisms

Keep this section small. New direct source copies must update
`vendor-src/MANIFEST.jsonl`.

MemPalace is the default mechanism reference for A9 session/memory/context
governance, but recall must not be treated as truth. Any recalled item entering
worker, monitor or operator context must keep source path, line/message id,
hash, role and timestamp.

Current local integration uses `reference-projects/mempalace` as the mechanism
source and `scripts/a9_mempalace_provider.py` as an A9 facade. Native MemPalace
collection access is enabled only when its Python dependencies are present;
otherwise A9 uses the source-preserving drawer JSONL fallback.

## Current Decision Matrix

This is the bounded evidence matrix for A9 session/memory governance and 24h
execution quality. It exists to prevent local invention from replacing
reference-first copying.

| Reference | Local evidence | Mechanism to copy | A9 status | Current gap / next cut |
| --- | --- | --- | --- | --- |
| Codex | `reference-projects/codex/codex-rs/code-mode/src/service.rs`, `reference-projects/codex/codex-rs/apply-patch/src/parser.rs` | Session registry, resume-to-pending, sandbox/approval config, deterministic patch grammar and context matching. | A9 has supervisor queue, worktrees, strict envelope, deterministic apply and patch/scope/git governance. | Worker prompts still allow broad command habits. Next cut: task packets must include exact read-command discipline, not just allowed_paths. |
| MemPalace | `reference-projects/mempalace/README.md`, `reference-projects/mempalace/CHANGELOG.md`, `reference-projects/mempalace/examples/cursor/README.md` | Verbatim drawers, source metadata, hybrid retrieval, wakeup packs, preCompact/sessionStart hooks, temporal KG and idempotent resumable mining. | A9 uses MemPalace-first drawer/evidence/index, native recall where available, fallback drawer JSONL, causal candidate compiler and review-only eval candidates. | Recall is still not final truth. Next cut: compile drawer evidence into time-valid facts, stale invalidations and role packets with explicit evidence refs before worker execution. |
| planning-with-files | `reference-projects/planning-with-files/templates/task_plan.md`, `reference-projects/planning-with-files/templates/loop.md`, `reference-projects/planning-with-files/README.md`, `reference-projects/planning-with-files/MIGRATION.md` | Filesystem working memory, progress/findings/task plan loop, hooks re-read before work, attestation and parallel plan isolation. | A9 has active plan, progress/findings/mistakes/change_request and managed backlog. | A9 must not add more planning docs. Next cut: make plan/backlog items stricter as contracts: exact files, exact commands, validated checks, and no broad aliases. |
| OpenClaw/Lobster | `reference-projects/openclaw/src/node-host/invoke.ts`, `reference-projects/openclaw/src/node-host/invoke-system-run-plan.ts`, `reference-projects/openclaw/src/context-engine/types.ts`, `reference-projects/openclaw/packages/sdk/src/types.ts` | Approval hash/reload safety, flow IDs, plugin command envelope, context engine overflow authority and approval events. | A9 has Redis managed-flow revision checks, approval/wait/resume, policy attestation and runtime monitor contract. | Quality-blocked tasks must update plan state and monitor/mobile must see them. This is now implemented for task-quality blocks; next cut is command-level task generation. |
| Aider | `reference-projects/aider/aider/repomap.py`, `reference-projects/aider/aider/coders/architect_prompts.py`, `reference-projects/aider/aider/coders/udiff_prompts.py` | Repo map instead of full repo reads, architect/editor split, explicit edit format and git-friendly diff discipline. | A9 has repo map, bounded context, deterministic apply and git governance. | Worker still broad-searches (`scripts`, `tests`) after task generation. Next cut: generated backlog must include exact rg/sed commands or anchors, not just a file list. |

Decision:

- The earlier high-quality debate came from durable context plus human
  correction plus repeated requirements shaping; it was not enough as a
  production mechanism.
- A9 should keep the debate quality by turning it into reference-backed plan,
  evidence and memory contracts.
- The next code cut is not another gate. It is task-contract shaping:
  backlog-generation output must be narrow enough that the worker does not need
  broad discovery commands.

## Trial Queue

This queue is deliberately small and should be updated only when a reference
has been used locally, not when it is merely mentioned.

| Reference | Local state | Trial target | Current decision |
| --- | --- | --- | --- |
| MemPalace | Downloaded, native/fallback recall tested against real operator session, recall-quality eval added. | Commercial-grade memory: recall quality, causal compiler, role packets, wrongbook loop. | Adopted for memory layer, still not truth authority. Next: role packet eval and contradiction repair. |
| Codex | Downloaded, selected Rust service/apply-patch paths inspected. | Interaction loop, tool boundary, sandbox/approval, session resume, compact and long-running goal behavior. | Core interaction/runtime reference; needs deeper use-through before A9 claims Codex-like quality. |
| OpenClaw/Lobster | Downloaded, selected flow/context/tool envelope paths inspected. | Runtime managed flow, approval/resume, tool/plugin envelope, context overflow authority. | Candidate runtime/gateway reference; not fully adopted until local flow spike passes. |
| Barter-rs | Downloaded, README/license present, not yet gateway use-through tested in A9. | Rust gateway reconnect, backoff, stream error action, audit state and low-latency transport discipline. | Primary gateway reliability candidate; must run local communication/gateway spike before inclusion. |
| Aider | Downloaded, repo map and architect/editor prompts inspected. | Repo map, bounded edit discipline, architect/editor split. | Partially adopted; next proof is reducing worker broad reads through exact read commands. |
| planning-with-files | Downloaded, templates and hook flow inspected. | File-backed task memory and resume. | Mechanism reference only; A9 will not import its role model or add extra doc sprawl. |
| Hermes | Downloaded, not yet use-through tested. | Sidecar self-improvement, routines, wrongbook/eval feedback loop. | Candidate; must run a local spike before inclusion. |
| ECC | Downloaded, not yet use-through tested. | Multi-agent/tool ecosystem shape and cross-IDE agent conventions. | Candidate; must be compared against A9 role model before inclusion. |
| Superpowers | Not confirmed in local `reference-projects`. | Spec-first workflow, design confirmation, subagent execution discipline. | Must be downloaded and used-through before A9 copies any mechanism. |
| gstack | `gbrain` is local; `gstack` itself is not confirmed in local `reference-projects`. | Skillized roles, plan reviews, QA/benchmark/retro discipline. | Must be downloaded and used-through; only role-review mechanisms may be copied. |
| headroom / mirofish | Not confirmed in local `reference-projects`. | Unknown until source is confirmed. | Do not cite as architecture input until repo/source is provided and locally tested. |
