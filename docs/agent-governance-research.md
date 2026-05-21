# A9 Agent Governance Research

## Core Question

A9 is trying to build a private 24-hour execution machine. The important
question is not only "which model should run it", but "which runtime can govern
the model while it works".

Deploying a private model matters, but it does not replace governance. A strong
model without a controlled runtime can only produce faster unverified work. A
weaker model inside a runtime with scope checks, policy gates, patch validation,
evidence, and replay is often more useful for building the system.

## Current Boundary

The current Codex/ChatGPT conversation is not a fully controllable runtime.

It can:

- Act as a temporary controller.
- Submit tasks into A9 supervisor.
- Review worker results.
- Merge, test, and push accepted changes.
- Help design the future controlled runtime.

It cannot reliably:

- Let A9 intercept every tool call before it happens.
- Expose hidden reasoning state for complete audit.
- Guarantee that every context detail survives compaction.
- Enforce sandbox, policy, or scope rules on the controller itself.
- Serve as the final production execution surface.

Therefore the target should be:

```text
Current conversation = temporary controller and research interface
A9 runtime = controlled production execution layer
```

## Training-Layer Self-Supervision

Top labs do use AI to supervise AI during training or post-training. That does
not mean runtime self-supervision is solved.

Patterns worth copying:

- Constitutional AI / RLAIF: AI critique and AI preference labels guided by a
  written constitution. A9 needs an explicit doctrine for allowed scope, license
  behavior, token cost, evidence, tests, and unsafe actions.
- Weak-to-strong supervision: weaker or cheaper supervisors can guide stronger
  models when the task and labels are structured. A9 should not rely on a worker
  merely pleasing a weak checker; it must encode the real objective.
- Process supervision: score intermediate steps, not only final answers. In A9,
  tool calls, file reads, patch generation, checks, and repair decisions are the
  process steps.
- Self-critique and self-reward: useful as signals, but unsafe as the only
  authority because self-reward can drift into reward hacking.

Training-layer lesson:

```text
AI feedback is useful only when grounded by rules, evidence, and independent
verification.
```

## Runtime Governance

Runtime governance is the layer A9 can implement now.

Patterns worth copying:

- OpenAI monitorability / scalable control: monitor different views of the
  agent, including actions, traces, and reasoning-like summaries. Treat the
  monitor as a classifier with measurable false positives and false negatives,
  not as a trusted narrator.
- METR-style side-task detection: evaluate whether an agent hides extra work
  while completing the main task. A9 should test for overreach, test cheating,
  hidden file changes, and unauthorized reference copying.
- Claude Code auto-mode style permissioning: block or classify dangerous actions
  before execution, and combine it with sandboxing.
- AlphaEvolve style evaluation loop: generate candidates, score them with
  objective evaluators, keep the best candidates, and continue from measured
  progress instead of subjective completion claims.

Runtime lesson:

```text
Do not trust a worker's statement. Trust bounded actions, evidence, tests,
policy checks, and replayable state.
```

## What A9 Has Already Built

A9 already has the beginning of the controlled runtime:

- Queue and run loop.
- Per-task git worktrees.
- Captured prompts, events, stderr, final messages, diffs, checks, summaries,
  evidence, state, and deep marks.
- Auto-next task scheduling.
- Checkpoint lineage and memory adapters.
- Rust client, gateway, and worker skeletons.
- Patch guard evidence integration for recorded diffs.

This means A9 is closer to a governable runtime than a raw chat window.

## What Is Missing

The current runtime still lacks several governance gates:

- `scope_guard`: verify the diff only touches authorized files and does not
  change tests, vendor code, or production config unless the task explicitly
  allows it.
- `policy_gate`: classify dangerous commands and high-risk file operations
  before execution.
- `license_guard`: detect source-level copying and enforce license/notice
  obligations.
- `budget_guard`: stop or repair runs when prompt, event, log, or file churn
  exceeds task budget.
- `monitor_score`: independent suspicion score over task, trace, diff, checks,
  and final message.
- `eval_store`: durable records for pass, repair, reject, overreach, token
  waste, test cheating, license risk, and unsafe command cases.

## Where Model Deployment Fits

Deploying a private model is important, but it is not the first hard dependency.

There are three stages:

1. Controlled runtime first.
   Build the harness that can run any model safely: queue, sandbox, scope,
   policy, patch, tests, evidence, replay, and monitor scores.
2. Model gateway second.
   Route GPT, Claude, DeepSeek, Qwen, local models, and private models through
   the same A9 protocol so behavior is comparable.
3. Private model training/deployment third.
   Use A9 traces as training and evaluation data. Fine-tune or preference-train
   models on real A9 examples with labels such as pass, repair, overreach,
   unsafe, token waste, and evidence missing.

If a model is deployed before the runtime is governable, A9 gets more throughput
but not more reliability. If the runtime is built first, every later model can
be evaluated, compared, and improved.

## Recommended Decision

Do not make private model deployment the immediate blocker.

The immediate priority should be governance data and runtime control:

```text
scope_guard -> policy_gate -> monitor_score -> eval_store -> model gateway
```

After that, model deployment becomes valuable because A9 will already have:

- A stable task protocol.
- Objective evaluation signals.
- Failure labels.
- Replayable traces.
- A private training dataset.
- A way to compare models under identical tasks.

## Training Data Shape

Every A9 run should gradually become a supervised training example:

```json
{
  "task": "...",
  "phase": "implement",
  "allowed_scope": ["scripts/a9_patch_guard.py", "tests/test_patch_guard.py"],
  "trace_path": ".a9/runs/.../events.jsonl",
  "diff_path": ".a9/runs/.../patch.diff",
  "checks": [{"command": "...", "return_code": 0}],
  "guards": {
    "patch_guard": "pass",
    "scope_guard": "pass",
    "policy_gate": "pass"
  },
  "monitor_score": 0.08,
  "verdict": "pass",
  "failure_type": null
}
```

This is the bridge from runtime governance to private model training.

## Open Questions

- Can a cheaper monitor model reliably catch overreach from a stronger worker?
- Which actions must be blocked before execution instead of repaired afterward?
- What false-positive rate is acceptable for stopping a 24-hour worker?
- How much trace detail is enough for monitorability without exploding tokens?
- Which failures should become fine-tuning data, and which should remain only
  policy/eval data?

## Current Stance

A9 should keep copying mature systems, but the next copied mechanisms should be
governance mechanisms, not interface features.

The private model is the future engine. The controlled runtime is the chassis,
brakes, dashboard, and crash recorder. Building the engine first is not enough
if the system cannot steer, stop, or explain what happened.
