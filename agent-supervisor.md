# A9 Agent Supervisor Plan

## Goal

Build a 24-hour coding/research worker around Codex-like agents. The worker should keep running comparison, copying-by-design, implementation, testing, and validation tasks without waiting for a human after every small step.

The hard problem is context continuity. Page/TUI monitoring is useful because it can keep a live human conversation moving, but it must not be the only source of truth. Durable context has to live outside the model window in task files, JSON logs, git state, summaries, patches, test results, and reference notes.

## Reference Projects

Local source snapshots are stored under `reference-projects/` and ignored by git.

| Project | Local path | Current snapshot | License | Primary ideas to study |
| --- | --- | --- | --- | --- |
| OpenAI Codex CLI | `reference-projects/codex` | `0b4f860` | Apache-2.0 | agent loop, context management, compaction, sandbox, approvals, config, MCP/tools, session logs, retry/timeout handling |
| Aider | `reference-projects/aider` | `6435cb8` | Apache-2.0 | repo map, search/replace edits, diff formats, architect/editor split, git-aware coding loop |
| sigoden/aichat | `reference-projects/aichat` | `82976d3` | MIT OR Apache-2.0 | Rust CLI, providers, REPL, shell assistant, roles, RAG/tools |
| SWE-agent | `reference-projects/swe-agent` | `0f4f3bb` | MIT | issue-to-patch harness, shell/git/docker loop, eval-oriented automation |
| Gemini CLI | `reference-projects/gemini-cli` | `906f8a3` | Apache-2.0 | open coding agent UX, tool routing, provider integration |
| Cline | `reference-projects/cline` | `2a351ff` | Apache-2.0 | plan/act UX, tool approvals, edit previews, browser/editor integration ideas |
| Roo Code | `reference-projects/roo-code` | `b867ec9` | Apache-2.0 | mode system, tool orchestration, project rules, user approval patterns |
| opencode | `reference-projects/opencode` | `7566cfe` | MIT | terminal agent UX, provider abstraction, lightweight agent patterns |

Claude Code and Antigravity are top product references, but they are not treated as open source code references unless a public source repository and license are verified. Use them for observable product behavior and public documentation only.

## Why Codex Is The Main Reference

Codex is the most important source-level reference because the hard parts are not just "call an LLM":

- Context selection and compaction.
- Long-running session state.
- Tool-call observation loops.
- Command timeout and retry behavior.
- Sandbox and approval boundaries.
- Project rules such as `AGENTS.md`.
- Local session logs that can become training traces.
- Configurable model providers and tool surfaces.

The A9 version should copy these mechanisms conceptually, then specialize them for trading engineering: `TRADE_AGENTS.md`, backtests, risk checks, data-leak checks, replay tests, and audit trails.

## Supervisor Design

### Core Rule

Use `codex exec --json` or our own future Rust agent worker for production runs. Do not make UI scraping the only source of truth.

The TUI/page is for humans and emergency continuity. The supervisor should run deterministic jobs and inspect machine-readable outputs.

### Components

1. `tasks/queue/*.md`
   Pending task specs. Each file contains objective, allowed repos, reference projects to compare, success checks, and stop conditions.

2. `tasks/running/*.json`
   The active lease for a task. Includes pid, started_at, timeout, attempt number, worktree path, and current phase.

3. `tasks/done/*.json`
   Final task result: pass, fail, needs-human, abandoned.

4. `runs/<task-id>/`
   Full trace directory: prompt, event stream, stdout/stderr, patch, test logs, review notes, final summary.

5. Git worktree per task
   Each task runs in an isolated worktree. The worker never edits `main` directly.

6. Watchdog
   A small daemon that starts jobs, reads heartbeats, kills stuck workers, retries bounded failures, and schedules the next phase.

7. Context store
   Durable memory outside the model window. It contains doctrine summaries, reference notes, repo maps, task state, traces, patches, check logs, and rolling summaries.

## Context Management

The system must not depend on one long chat context. Each new worker run reconstructs the needed prompt from durable state.

### Context Layers

1. Static doctrine
   `需求.md`, `codex.md`, `TRADE_AGENTS.md`, `AGENTS.md`, architecture docs, and risk rules.

2. Reference notes
   Short extracted notes from `reference-projects/*`, not raw whole repositories. Each note records source project, file path, mechanism, license, and how A9 may adapt it.

3. Repo state
   Current git commit, current diff, selected files, tests, failures, and module map.

4. Task state
   Objective, phase, attempts, previous run summaries, blockers, and decisions already made.

5. Trace memory
   `events.jsonl`, `final.md`, `patch.diff`, `checks/*.log`, plus compact `summary.json` generated after each run.

6. Rolling summary
   A human-readable `context.md` per task that gets updated after every run. The next attempt reads this first.

### Prompt Reconstruction

Each worker run should receive only:

- doctrine summary
- current task objective and phase
- last successful or failed run summary
- relevant reference notes
- relevant repo files or repo map slice
- current patch and test status
- hard stop conditions

This copies Codex's context-compaction spirit without relying on an invisible browser/chat context.

### Page Monitoring Role

Page monitoring is useful for one case: a human is already deep in a live Codex/ChatGPT conversation and wants a watcher to notice that the assistant stopped and submit the next continuation prompt.

Allowed page-monitor behavior:

- Detect idle/stopped state.
- Snapshot visible transcript when possible.
- Append a short continuation prompt.
- Export or copy the conversation into local markdown periodically.
- Hand off exported markdown into the durable context store.

Not allowed as the only architecture:

- Treating the browser transcript as the only memory.
- Depending on DOM selectors as the source of task truth.
- Letting a page monitor execute code or merge patches without supervisor trace.

Best architecture:

```text
Browser/TUI monitor
  -> exports transcript/summary
  -> context store
  -> supervisor task
  -> codex exec/native worker
  -> trace + tests + diff
  -> updated context summary
  -> optional browser continuation
```

The page monitor solves live continuity. The supervisor solves repeatability and 24-hour reliability.

## Task State Machine

1. `compare`
   Read selected reference code. Produce notes on mechanisms worth copying.

2. `design`
   Convert notes into A9-specific design and files to change.

3. `implement`
   Apply patch in a worktree.

4. `test`
   Run unit tests, lint, build, and domain checks.

5. `review`
   Run review agent or static checks. Reject risky edits.

6. `record`
   Save trace, diff, tests, failure modes, and lessons.

7. `next`
   If successful, schedule the next task. If blocked, create a `needs-human` result with exact blocker.

## Continue Logic

The supervisor decides what to do when Codex stops:

- Exit code 0 and tests pass: mark done, create next task.
- Exit code 0 but no patch/test evidence: schedule a more specific follow-up prompt.
- Exit code nonzero due to timeout/network: retry with same task, max 2 attempts.
- Failing tests after patch: schedule repair task with test logs.
- Permission/secrets/prod-risk warning: stop as `needs-human`.
- No output for N minutes: kill, preserve logs, retry once.

## Example Worker Command

```bash
codex exec --json \
  -C /root/a9-worktrees/task-001 \
  --output-last-message runs/task-001/final.md \
  "$(cat tasks/queue/task-001.md)" \
  > runs/task-001/events.jsonl
```

For current Codex, `approval_policy = "never"` and network is enabled in config. For our future A9 agent, the same model should be implemented natively with structured events.

## Prompt Contract

Each task prompt should force evidence:

```text
You are running inside the A9 supervisor.

Phase: compare/design/implement/test/review.
Use reference projects only from /root/a9/reference-projects.
Do not copy code without recording license obligations.
Before editing, write a short plan.
After editing, run the declared checks.
Final answer must include:
- files changed
- reference ideas used
- commands run
- test result
- next recommended task
```

## First MVP

Implemented now:

1. `scripts/a9_supervisor.py init` creates queue, running, done, runs, and worktree directories.
2. `scripts/a9_supervisor.py enqueue ...` creates markdown tasks with timeout, idle timeout, attempts, and checks.
3. `scripts/a9_supervisor.py run-one` runs one task with `codex exec --json`.
4. `scripts/a9_supervisor.py run-loop` keeps consuming queued tasks.
5. Every run stores `prompt.md`, `events.jsonl`, `stderr.log`, `final.md`, `patch.diff`, check logs, and `summary.json`.
6. Each task runs in an isolated git worktree under `.a9/worktrees`.
7. The supervisor classifies results as `pass`, `needs-followup`, `needs-repair`, or retryable failures.

Verified:

- Fake worker end-to-end test passes.
- Real Codex worker can create a file in an isolated worktree after removing the deprecated `use_legacy_landlock` setting from Codex config.

After this works, port the supervisor to Rust and replace `codex exec` with the A9 native agent worker.
