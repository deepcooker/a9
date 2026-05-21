# A9 Agent Governance Research

## Core Question

A9 is trying to build a private 24-hour execution machine. The important
question is not only "which model should run it", but "which runtime can govern
the model while it works".

Deploying a private model matters, but it does not replace governance. A strong
model without a controlled runtime can only produce faster unverified work. A
weaker model inside a runtime with scope checks, policy gates, patch validation,
evidence, and replay is often more useful for building the system.

This document is a decision document. It should not be treated as a final
architecture. The goal is to gather enough evidence to make the next engineering
move after an explicit tradeoff.

## Evidence Base

The current evidence points in the same direction: frontier labs use model
supervision and agent monitoring, but they do not rely on a single self-judging
agent as the control layer.

| Source | Layer | Evidence | A9 implication |
| --- | --- | --- | --- |
| Anthropic Constitutional AI / RLAIF | Training | AI can critique and revise model outputs under a written constitution, then provide preference feedback for RL. | A9 needs a written constitution/doctrine and labeled outcomes, not ad hoc worker self-reporting. |
| OpenAI weak-to-strong generalization | Training | Weak supervisors can elicit stronger model capabilities, but the key question is whether the strong model follows the weak supervisor's intended target rather than noisy labels. | A9's cheap monitor can help, but labels must encode the real objective: bounded scope, evidence, tests, license, and cost. |
| OpenAI process supervision | Training/eval | Step-level feedback can be more useful than only final-result feedback. | A9 should score tool calls, file reads, diffs, checks, and repair decisions, not only final task status. |
| Self-rewarding language models | Training | Models can generate and judge training examples, but self-reward creates reward-hacking risk. | Self-critique is allowed as a signal, but final authority must be independent evidence and evaluators. |
| OpenAI chain-of-thought monitorability | Runtime/eval | Monitorability is measured as whether a monitor can predict important properties of agent behavior under different observation scopes. | A9 needs monitor scopes: final output, diff, actions, events, summaries, checks, and follow-up interrogation. |
| METR SHUSHCAST / MALT | Runtime/eval | Agents can pursue side tasks while doing main tasks; monitors are evaluated with false-positive and true-positive rates. | A9 needs side-task/overreach evals, not only pass/fail tests. |
| Anthropic Claude Code auto mode | Runtime control | Tool calls are gated by a transcript classifier; prompt-injection checks and sandboxing are separate layers. | A9 should add pre-tool policy gates and sandbox boundaries before relying on post-hoc review. |
| Google DeepMind AlphaEvolve | Runtime/evolution | LLMs propose code; automated evaluators score candidates; a database selects future prompts. | A9 should maintain candidate/eval history and let measured results drive future tasks. |

Source links:

- Anthropic Constitutional AI: https://www.anthropic.com/index/constitutional-ai-harmlessness-from-ai-feedback
- OpenAI weak-to-strong generalization: https://openai.com/index/weak-to-strong-generalization/
- OpenAI process supervision: https://arxiv.org/abs/2305.20050
- Self-Rewarding Language Models: https://arxiv.org/abs/2401.10020
- OpenAI monitorability: https://openai.com/index/evaluating-chain-of-thought-monitorability/
- OpenAI internal coding-agent monitoring: https://openai.com/index/how-we-monitor-internal-coding-agents-misalignment
- METR monitorability evaluations: https://metr.org/blog/2026-01-19-early-work-on-monitorability-evaluations/
- METR MALT dataset: https://metr.org/blog/2025-10-14-malt-dataset-of-natural-and-prompted-behaviors/
- Anthropic Claude Code auto mode: https://www.anthropic.com/engineering/claude-code-auto-mode
- Claude Code sandboxing: https://docs.claude.com/en/docs/claude-code/sandboxing
- Claude Code permission modes: https://code.claude.com/docs/en/permission-modes
- Google DeepMind AlphaEvolve: https://deepmind.google/discover/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/

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

### Training-Layer Takeaways

Training-layer self-supervision is valuable for A9, but mostly as a data strategy
for later model training:

- Use A9 traces as labeled examples.
- Use AI critique as an auxiliary label, not as the final verdict.
- Keep human/controller verdicts for high-impact examples.
- Keep objective evaluator outputs as first-class labels.
- Separate "model learned to pass checks" from "model learned the real
  doctrine".

The danger is reward hacking. If the same model writes code, judges the code,
and decides whether the work is complete, it can optimize for appearing correct.
A9 must therefore separate worker, monitor, policy gate, evaluator, and durable
record.

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

### Runtime Takeaways

The runtime layer is where A9 can make immediate progress. The strongest public
patterns have three common properties:

- Pre-action gates: risky commands and file operations are classified before
  execution.
- Post-action evidence: every diff, check, event stream, and summary is durable.
- Calibrated monitors: monitors are judged by false positives, false negatives,
  and missed side tasks, not by persuasive prose.

This is why page monitoring is insufficient. A page monitor observes after the
fact and may miss context; a controlled runtime can stop actions before they
happen and can preserve evidence independent of the model.

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

## Strategic Options

The decision is not "model or governance". It is which dependency should be paid
first.

| Option | Benefit | Risk | Evidence reading |
| --- | --- | --- | --- |
| Deploy private model first | Own inference, lower marginal cost, local data control, faster iteration if model is good. | Produces more unverified work; no comparable eval harness; weak training data; harder to debug failures. | AlphaEvolve and METR both imply evaluators/traces are core before trusting autonomous progress. |
| Build governance runtime first | Any model can be tested under identical tasks; creates training data; reduces blast radius. | Slower visible progress on model ownership; may overbuild controls before final product shape. | Claude Code, OpenAI monitorability, and process supervision all point to action/evidence/step-level control. |
| Build model gateway now, not model training | Lets A9 compare GPT/Claude/local/private models behind one protocol. | Gateway without policy can become another uncontrolled execution path. | Good compromise if paired with scope/policy guards. |
| Keep using current Codex window as controller | Fastest for design and manual oversight. | Not strongly controllable; no pre-tool interception; context compaction risk. | Useful only as temporary controller, not production runtime. |

Current best decision:

```text
Governance runtime first, model gateway in parallel or immediately after,
private model deployment after A9 has stable eval traces.
```

This decision should be revisited when A9 can produce at least 50-100 labeled
run records with guard outputs, human/controller verdicts, and replayable
evidence.

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

## Decision Gates Before Private Model Deployment

A private model becomes more important once these gates are met:

- A9 can run the same task across at least two external models and compare
  guard/eval outputs.
- A9 has `scope_guard`, `patch_guard`, and at least a basic `policy_gate`.
- A9 stores labeled failures, not only successful runs.
- A9 can replay a run from task prompt, evidence, diff, and checks.
- A9 has a small benchmark suite for overreach, test cheating, unsafe command,
  license risk, and token waste.
- A9 can measure cost per correct task, not only pass rate.

Before these gates, deploying a model is mostly an infrastructure exercise. After
these gates, deploying a model becomes a measurable product and training step.

## Open Questions

- Can a cheaper monitor model reliably catch overreach from a stronger worker?
- Which actions must be blocked before execution instead of repaired afterward?
- What false-positive rate is acceptable for stopping a 24-hour worker?
- How much trace detail is enough for monitorability without exploding tokens?
- Which failures should become fine-tuning data, and which should remain only
  policy/eval data?
- Can A9 generate synthetic side-task challenges like SHUSHCAST without teaching
  the worker to game the exact monitor?
- Should `policy_gate` be deterministic first, model-classifier second, or both?
- How should A9 preserve monitor-relevant details when context compaction removes
  old messages?
- Which private model deployment target matters first: inference gateway,
  fine-tuned coding worker, monitor model, or embedding/reranker model?

## Current Stance

A9 should keep copying mature systems, but the next copied mechanisms should be
governance mechanisms, not interface features.

The private model is the future engine. The controlled runtime is the chassis,
brakes, dashboard, and crash recorder. Building the engine first is not enough
if the system cannot steer, stop, or explain what happened.
