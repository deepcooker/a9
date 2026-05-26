# A9 Private Model Strategy

## Position

A9's private model target is not a general model that beats frontier models on
all tasks. The target is narrower and harder to fake:

```text
A 1-2 consumer-GPU deployable financial trading engineering agent system that
beats a frontier model used naked on A9's own task suite.
```

This is a system target, not only a weight target. The model wins together with
A9 runtime, repo maps, mature-reference retrieval, patch guards, tests,
backtests, risk gates, and trajectory memory.

## Original Thesis

The core operating philosophy from `原始想法需求.md` is:

- Find the strongest comparable mature project.
- Copy mature mechanisms before inventing.
- Extract the "bone marrow" of top projects, not surface code.
- Use AI for search, reading, extraction, adaptation, glue code, and diff.
- Avoid hand-rolled core logic when mature logic exists.
- Force every result through data validation.
- Prefer stable observable collapse: a model answer only matters once it becomes
  an applicable patch, passing test, backtest result, risk decision, or rejected
  failure record.
- Convert repeated high-quality trajectories into training data.

The short version:

```text
target -> find benchmark -> copy -> adapt -> test -> audit -> record -> train
```

## What "Beat GPT-5.5" Means

The useful goal is not:

```text
small local model has higher general intelligence than GPT-5.5
```

The useful goal is:

```text
A9 local model + A9 tools + A9 private context + A9 validation beats GPT-5.5
naked on A9 financial engineering tasks.
```

The evaluation target must be concrete:

- Repository understanding on A9 and trading reference code.
- SEARCH/REPLACE and unified diff success rate.
- Small patch discipline.
- Test-failure repair.
- Mature project mechanism selection.
- Trading infrastructure architecture choices.
- Risk-audit refusal quality.
- Backtest-to-live parity checks.
- Time-series tool use discipline.
- Cost and latency per accepted patch.

## Model Roles

A9 should not try to train one model to do everything first.

Recommended roles:

- `Teacher`: frontier API or large open model. Generates high-quality traces,
  critiques, comparison reports, and training examples.
- `Student`: 14B/32B/30B-A3B local deployable model. Learns A9's repeated
  behaviors and runs on one or two consumer GPUs.
- `Editor`: optimized for patch format, minimal diffs, and repair loops.
- `RepoReader`: optimized for repo map, symbol graph, call-chain and file-scope
  understanding.
- `RiskAuditor`: optimized for saying no: future leak, data pollution, hidden
  leverage, weak backtest, policy bypass, unsafe patch.
- `ResearchOps`: optimized for hypothesis, data request, TimeFM tool use,
  backtest design, uncertainty, and attribution.

These roles can start as prompts and routing policies, then become LoRA/adapters
or separate small models.

## Training Priority

Do not train a direct trading signal model first.

First train agent behavior:

1. `DiffEditor`
   Output valid small patches, use SEARCH/REPLACE/unified diff, repair failed
   patches, and avoid unrelated files.
2. `RepoReader`
   Pick relevant files, explain architecture boundaries, and respect
   `AGENTS.md` / future `TRADE_AGENTS.md`.
3. `RiskAuditor`
   Refuse unsafe changes and identify trading-system failure modes.
4. `TradeInfra`
   Map Hummingbot, NautilusTrader, Barter-rs and similar systems into mature
   engineering invariants.
5. `ResearchOps`
   Use TimeFM and data tools to create hypotheses and validation plans, not
   direct trading commands.

## What To Put In Weights

Good candidates for training:

- A9 doctrine: copy-first, validate-first, no hand-rolled core logic when a
  mature mechanism exists.
- Patch output grammar.
- Repair behavior from test errors.
- Risk refusal patterns.
- Trading infrastructure invariants.
- How to choose references.
- How to produce structured evidence and next actions.

Bad candidates for blind weight injection:

- Large raw source trees without task framing.
- Copyrighted books or proprietary trading text without permission.
- Exact code memorization as the main mechanism.
- Direct "buy/sell" behavior.
- Unverified strategy folklore.

Raw source and large documents should mostly live in retrieval, repo map,
licensed vendor slices, and evidence stores. Weights should learn behavior,
discipline, and decision boundaries.

## Reference Projects As Bone Marrow

Target projects are not just code examples. They are sources of engineering
invariants.

Examples:

- Codex: local agent loop, configuration, sandbox, approval, context and event
  governance.
- Aider: repo map, SEARCH/REPLACE, edit formats, architect/editor split, repair
  loop.
- SWE-agent: issue -> patch -> test harness and sandbox evaluation.
- Qwen/DeepSeek/MiniMax/Claude/GPT: teacher models and comparison targets.
- Hummingbot: exchange connectors, CEX/DEX strategy layers, bot configuration,
  market making and arbitrage patterns.
- NautilusTrader: event-driven core, research/live parity, order lifecycle,
  deterministic simulation, Rust core with Python control plane.
- Barter-rs: Rust trading ecosystem, live/paper/backtest engines, command and
  event patterns.
- Polars/DuckDB: fast data processing patterns.
- Tokio/Rayon: Rust async and parallel execution patterns.
- vLLM/SGLang: inference serving, prefix cache, speculative decoding, OpenAI
  compatible APIs, and latency control.
- TimesFM: time-series forecast tool, not a standalone trading authority.

The training target is not "recite these projects". The target is:

```text
given a task, identify which mature project has the relevant invariant, extract
the invariant, adapt it minimally, and validate it.
```

## Teacher -> Student Pipeline

The preferred path:

1. Use frontier teachers and strong open teacher models to run A9 tasks under
   supervision.
2. Capture full trajectories:
   - task
   - repo state
   - files read
   - reference mechanisms
   - plan
   - tool calls
   - patch
   - tests
   - backtest
   - risk audit
   - human/controller verdict
   - final outcome
3. Reject low-quality traces.
4. Convert passing and rejected traces into SFT/DPO/RL data.
5. Train local student model/adapters.
6. Re-run the same A9 eval suite against teacher, student, and naked frontier
   model.
7. Keep only measurable wins.

## Training Methods

Use methods by layer:

- CPT: light continued pretraining for A9 vocabulary, docs, logs, and trading
  terminology. Keep it small to avoid damaging general ability.
- SFT: primary behavior training for patching, repo reading, risk refusal, and
  reference selection.
- DPO/KTO: preference training for good vs bad outputs.
- GRPO/RL: only where reward is objective: patch applies, tests pass, risk gate
  passes, no forbidden files, no secret access, smaller diff, lower cost.
- Distillation: teacher traces into student model.
- LoRA/adapters: role-specific skills without collapsing all behavior into one
  brittle model.

The system should not reward persuasive explanations. It should reward verified
outcomes.

## Evaluation Suite

A9 needs private evals before claiming a model beats anything.

Core evals:

- `Repo Understanding`: relevant file selection, call chain, module boundary,
  forbidden zone recognition.
- `Diff Editing`: parse success, apply success, line count, test pass, repair
  pass, unrelated file changes.
- `Risk Audit`: future leak, data pollution, cost/slippage omission, live/backtest
  mismatch, kill switch bypass, unsafe deployment.
- `Reference Selection`: does the model find mature comparable projects instead
  of inventing?
- `Backtest-to-Live Parity`: order state, fill, cancel, reject, latency, fees,
  slippage and capacity assumptions.
- `TimeFM Tool Use`: forecast uncertainty handling, feature generation, refusal
  to convert raw forecast into direct trade.
- `Agent Completion`: task -> plan -> patch -> checks -> repair -> audit ->
  evidence.
- `Cost/Latency`: cost per accepted patch, TTFT, total runtime, GPU time.

The benchmark target is:

```text
A9 local system > GPT-5.5 naked prompt on A9 evals
```

not:

```text
A9 local model > GPT-5.5 on every public benchmark
```

## Pressure And Persuasion Evals

The user mentioned PUA-like logic as a possible source of insight. A9 should not
copy manipulation tactics for use on people.

The safe and useful translation is adversarial pressure evaluation:

- Can the model be pressured to skip tests?
- Can it be persuaded to bypass risk gates?
- Can it be made to change tests instead of code?
- Can it be induced to hide uncertainty?
- Can it be pushed into direct trading advice?
- Can it be made to claim a copied mechanism without evidence?
- Can it be redirected away from the original objective?

This becomes:

```text
pressure_eval / persuasion_resistance_eval
```

The goal is not to manipulate humans. The goal is to make the model resistant to
goal drift, flattery, urgency pressure, false authority, and hidden side tasks.

## TimesFM Position

TimesFM should be treated as a time-series tool.

It can provide:

- forecast
- quantiles
- uncertainty
- regime clues
- feature candidates

It must not directly authorize trades.

A correct ResearchOps response should say:

```text
TimesFM output is a hypothesis input. It must be checked against data quality,
slippage, fees, liquidity, regime, backtest-to-live parity, and risk limits.
```

## Runtime Architecture

Recommended inference/runtime stack:

```text
User / Controller
  -> A9 Client
  -> Task Router
  -> Context Engine
  -> Model Router
  -> Worker / Editor / Auditor
  -> Patch Guard / Scope Guard / Policy Gate
  -> Test / Backtest / Risk Audit
  -> Evidence Store
  -> Trajectory Store
  -> Training Data Builder
```

Model routing:

- 3B-7B: shell helper, FIM, simple local completions.
- 14B/32B/30B-A3B: local financial engineering agent roles.
- Large teacher API/open model: hard planning, data generation, periodic audit.
- TimesFM: time-series tool.
- Judge/auditor: cheap monitor first, strong teacher sampling second.

Serving:

- vLLM/SGLang for OpenAI-compatible APIs, batching, prefix cache, speculative
  decoding.
- llama.cpp/GGUF for very small local deployment.
- Long context is useful, but repo map and retrieval are still required.

## Decision Not Yet Final

This strategy is not the final scheme. It defines the battlefield.

The next decisions still need several rounds of argument:

1. Should A9 first build `scope_guard` / `policy_gate`, or a model gateway for
   side-by-side model comparison?
2. Which student base model should be the first local target?
3. Are role-specific LoRAs enough, or should A9 split models by role?
4. How much "deliberate overfitting" is useful before it damages reasoning?
5. What is the smallest eval suite that can honestly measure "beats GPT-5.5
   naked on A9 tasks"?
6. Which data may legally enter training weights, and which must stay in RAG or
   licensed vendor slices?

## Current Best Bet

The strongest current bet:

```text
Build governed A9 runtime first.
Use teacher models to produce verified trajectories.
Train local student/adapters on behavior, not raw memorization.
Evaluate against A9 private task suite.
Deploy on 1-2 consumer GPUs only after the system has proof.
```

The model is the future engine. The A9 runtime is the lab, road, brakes, crash
recorder, and training data factory.
