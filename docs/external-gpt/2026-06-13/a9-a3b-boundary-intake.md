# GPT Review Intake: A9 / A3B Boundary

> Date: 2026-06-13
> Local source files:
>
> - `.a9/archive/operator-inbox/20260613/gpt.md`
> - `.a9/archive/operator-inbox/20260613/gpt-a9-a3b-boundary-20260613.md`
> - `.a9/archive/operator-inbox/20260613/a3b_moe_cognition_codex_current.zip`
> - `.a9/archive/operator-inbox/20260613/a3b_moe_cognition_for_gpt_review.zip`

## Status

Accepted as external review evidence for the A9 / A3B boundary. The source files
stay in `.a9/archive/operator-inbox/` because they are operator-provided review
material and A3B packages, not A9 runtime source.

This intake does not authorize changing `/root/a9/a3b_moe_cognition`.

## Accepted Clarification

A9 and A3B are connected, but they are not the same layer.

```text
A9
  = external execution/control gateway
  = 24h worker runtime
  = data/evidence/trace producer
  = tool, code, test, git, network and communication operator

A3B / A?B
  = meta-cognitive dynamic activation system
  = session, intent, mainline, first-principles, methodology, path, monitor,
    wrongbook and future training trace layer

Training target
  = A3B / A?B activation strategy and evidence-grounded correction behavior
  != A9 itself
```

A9 does not enter model weights and must not become A3B's brain. A9 produces
hard evidence that can later feed A3B's wrongbook, trace store, truth gate and
training dataset pipeline.

## Accepted Decisions

- A9 remains the stable execution control plane and 24h automation runtime.
- A3B remains the lower-level cognition/meta-activation system.
- A9 outputs are not truth. They are evidence packs, tool traces, test reports,
  diff summaries, failure summaries, cost reports and next-suggestion candidates.
- A3B outputs are not direct execution. They are intent, mainline, methodology,
  candidate paths, risk and monitor recommendations that A9 can turn into plans,
  backlog items and worker prompts.
- Teacher/Codex/GPT/A9 outputs are not training truth by default.
- Only evidence-grounded and truth-gated corrected samples can become controller
  positive samples for future A3B training.

## Training Boundary

The reviewed A3B package is currently a pre-training behavior compiler and sample
audit skeleton, not a real model-weight training system.

Accepted sequence before real training:

```text
wrongbook
-> corrected sample
-> truth authority gate
-> controller / monitor structured sample
-> chat messages JSONL
-> tokenizer dry-run
-> tiny overfit
-> LoRA / Adapter smoke
-> larger hardware dry-run
```

Do not jump from mock A3B samples directly to H800 or multi-GPU training.

## A9 / A3B Interface Shape

A3B should send A9 bounded execution tasks:

```json
{
  "goal": "Check whether a proposed mechanism is executable.",
  "mainline": "Current task mainline.",
  "methodology": ["best_practice_transform", "test_driven_validation"],
  "data_needed": ["repo files", "test logs", "benchmark output"],
  "allowed_tools": ["read_repo", "run_tests", "patch_code"],
  "forbidden_actions": ["delete_prod_data", "deploy_without_approval"],
  "success_criteria": ["tests pass", "diff minimal", "evidence recorded"],
  "output_contract": "EvidencePack + ToolTrace + FailureSummary"
}
```

A9 should return bounded evidence, not final truth:

```json
{
  "evidence_pack": [],
  "tool_trace": [],
  "test_report": {},
  "diff_summary": {},
  "failure_summary": {},
  "cost_report": {},
  "next_suggestion": {}
}
```

## Impact On Current A9 Work

This reinforces the existing A9 priority:

1. Keep A9 focused on stable communication, control API, supervisor, worker
   orchestration, evidence, git/worktree/checks, recovery and monitoring.
2. Do not mix A3B training implementation into current A9 runtime cleanup.
3. Keep A3B source/packages as boundary evidence unless a task explicitly grants
   write scope.
4. When A9 runtime emits wrongbook or trace material, keep raw logs on disk and
   pass structured evidence references into A3B-facing packets.

## Not Doing Now

- No A3B code changes from this intake.
- No H800, LoRA, tokenizer or training script work inside A9 runtime.
- No broad prompt injection of GPT review files into worker hot path.
- No claim that A9 evidence is truth without truth-authority review.

