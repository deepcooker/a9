# A9 Runtime Governance Review 2026-05-29

## Decision

本轮评审结论：A9 24h runtime 的执行通路已经打通，但治理方法有偏差，不能继续按“补功能”惯性推进。

必须先把三件事纳入主流程：

1. reference-first review gate：每个非平凡任务先证明看了正确参考项目。
2. goal / session / execution-chain governance：抄 Codex goal 和 Hermes self-improvement / trajectory，而不是只做队列。
3. token/cost architecture：token 不是靠固定数字门禁优化，而是靠上下文架构、缓存、压缩、分层事实源和可观测执行链优化。

当前可以保留的通路：

```text
worker strict envelope
-> deterministic SEARCH/REPLACE apply
-> guard / test / git governance
-> accepted worker commit integration
```

但它只能算执行通路，不等于合格的 24 小时无人值守治理。

## Evidence

本次评审读取了这些本地事实源：

- `AGENTS.md`：已经写明 A9 是 24 小时执行机器，核心是 reference_scan -> mechanism_extract -> vendor_import -> implement -> test -> record -> repair。
- `docs/session-causal-memory.md`：已经写明当前主线是 session governance、monitor 方法论、通信 runtime；页面和金融策略都不是当前主线。
- `docs/session-raw-summary.md` / `docs/session-raw-close-reading.md`：用户明确要求观察 worker 意图、提示词、查询 session 方式、exec 行为和“思维链路/执行链”。
- `reference-projects/codex/codex-rs/core/src/goals.rs`：Codex 有 persisted thread goals、goal runtime events、token/wall-clock accounting、idle continuation、budget limit steering、blocked audit。
- `reference-projects/codex/codex-rs/core/templates/goals/continuation.md`：Codex goal 明确要求保留完整 objective，不把目标缩成容易完成的小子集；完成必须 requirement-by-requirement audit。
- `reference-projects/hermes-agent/agent/background_review.py`：Hermes 在每轮对话后 fork review agent，复盘对话并把有效信号写入 memory / skill，主会话和 prompt cache 不被污染。
- `reference-projects/hermes-agent/agent/curator.py`：Hermes curator 周期性维护 agent-created skills，做 stale/archive/consolidate/pin，且保留 dry-run/report/structured summary。
- `reference-projects/hermes-agent/batch_runner.py`：Hermes batch runner 把 agent run 变成 trajectory、tool stats、reasoning coverage、checkpoint 和可恢复批处理。
- `reference-projects/hermes-agent/agent/trajectory.py`：Hermes 保存 trajectory，区分 completed / failed，用于后续训练和回放。
- `reference-projects/hermes-agent/agent/context_compressor.py`：Hermes compression 不是简单截断，而是保护 head/tail、工具输出预处理、结构化 summary、remaining work、summary budget、图片 token 成本。
- `reference-projects/hermes-agent/datagen-config-examples/trajectory_compression.yaml`：Hermes 对 trajectory compression 有独立数据处理配置，保护 first system / first human / first gpt / first tool / tail turns，并记录 metrics。
- `scripts/a9_monitor.py`：已有 requirements_review_council_v1，但 reference evidence、goal fidelity、execution-chain observation 还不够硬。
- `scripts/a9_supervisor.py`：已有 event summaries、context pressure、actual token usage、context router，但 token governance 仍偏预算截断。

## What Went Off Mainline

### 1. Reference Review 没有成为硬流程

问题：

- 文档里写了“抄抄抄”，但最近几刀主要在修 A9 自己的 supervisor。
- Hermes 已在本地，却没有纳入优先参考。
- Codex goal 已在本地，却没有被抽成 A9 的 long-goal runtime。

判断：

- 这不是“完全没参考”，而是“参考没有变成每刀验收条件”。
- 后续非平凡任务如果没有明确 source paths、机制、边界、不能抄的部分，应直接 block。

### 2. Goal Runtime 缺失

Codex goal 的核心不是普通 task queue，而是：

- persisted objective。
- status lifecycle。
- token / wall-clock accounting。
- idle continuation。
- budget limit steering。
- blocked audit threshold。
- completion audit：逐项证明目标完成，不能把目标缩小。

A9 当前只有 queue/run-loop/auto-next，没有同等级 goal runtime。现在的“24h”更像连续跑任务，不像持续追一个真实目标。

结论：

- 必须抄 Codex goal，把 A9 的长期目标从任务队列提升为 goal 对象。
- queue task 只是 goal 的执行切片，不是目标本身。

### 3. Token 问题被误解成数字门禁

用户纠偏正确：token 成本不能靠固定数额硬控质量。

当前已有：

- prompt section budgets。
- repo map。
- context router。
- event bytes budget。
- actual token usage。
- cached/uncached token observation。

但还缺：

- Hermes-style context engine lifecycle。
- compression feasibility check。
- prompt caching strategy。
- tool output / image / log pruning。
- trajectory-driven compression/eval。
- goal-level token accounting，而不是单 run 预算。

结论：

- 固定数字只能做观测和熔断，不能做质量标准。
- 真正优化路径是架构：context engine + cache + evidence store + goal accounting + replayable trajectory。

### 4. 执行链观测没有产品化

用户要求观测“思维链路”的真实可做版本不是读取隐藏 chain-of-thought，而是外显执行链：

```text
worker prompt
-> reference files touched
-> commands
-> read windows
-> tool/event summaries
-> patch
-> checks
-> guard findings
-> monitor findings
-> token usage
-> next_slice
```

当前 A9 已经保存 event summaries，但没有把它升级成 first-class execution chain report。

结论：

- 不能也不应该要求隐藏思维链。
- 应该把外显执行链做成可评分、可回放、可训练的数据结构。

### 5. Hermes 被误读成普通上下文系统

用户纠偏正确：Hermes 值得抄的主线不是“它也会压缩”，而是它有自我进化闭环雏形：

```text
conversation snapshot
-> background review fork
-> memory / skill write
-> curator consolidate / archive / pin
-> trajectory / stats / checkpoint
-> datagen / compression / replay
```

这套机制的关键不是单次总结，而是把一次 run 的经验变成未来 agent 的可检索能力、可维护 skill、可训练 trajectory。

A9 当前对应关系：

- 已有：session 精读、因果变迁、worker evidence、monitor review、git commit。
- 缺失：自动把 evidence 归因为 memory commit / skill doctrine / task rule / eval sample。
- 缺失：周期性 curator，把碎片规则合并成 umbrella doctrine，避免文档和规则爆炸。
- 缺失：trajectory dataset 与回放评估，让 24h worker 的执行链能反哺下一轮。

结论：

- A9 的 MoE + 精读 session + 外显执行链 + 24h worker 可以比 Hermes 更强，但前提是自动化闭环落地。
- 不能再只把 session refresh 当“总结文档”；它必须升级为 causal memory commit。

## What To Keep

保留：

- strict worker envelope。
- deterministic apply。
- patch/scope/test/git governance。
- worker accepted commit -> main integration。
- external session refresh / close-reading 与 A9 runtime session 分离。
- requirements_review_council_v1 作为方向，但需要升级专家和 hard gate。
- 数据第一、性能第二。

## What To Overturn Or Refactor

### 推翻：用 capability percent 表示 24h 完成

`100% supervisor-mvp` 只能表示 MVP 通路完成，不能表示 24h 生产可用。

改成三层状态：

```text
execution_path_ready
goal_runtime_ready
24h_unattended_ready
```

### 推翻：任务队列就是长期目标

task 是执行切片，goal 才是持续目标。必须引入 A9 goal object。

### 推翻：monitor 只看 run 后结果

monitor 必须看执行链：

- prompt 是否含真实问题、数据模型、性能边界、参考来源。
- worker 是否真的查了对应参考项目。
- 是否产生可追踪 evidence。
- 是否把下一步缩小成更容易的伪完成。

### 推翻：token 数字门禁作为质量控制

event bytes / token budget 只做 stop-loss 和观测。质量来自：

- context engine。
- prompt cache。
- evidence indexing。
- compression audit。
- goal accounting。
- task slicing。

## Revised Architecture

```text
A9 Goal Runtime
  objective / status / budget / blocked audit / completion audit
  |
  v
Reference Review Gate
  Codex / Hermes / OpenClaw / Aider / Barter-rs / Redis source evidence
  |
  v
Bounded Task Slice
  strict envelope + allowed paths + declared checks
  |
  v
Execution Chain Recorder
  prompt / commands / reads / events / patch / checks / token / next_slice
  |
  v
Requirements Review Council
  data first + performance second + reference evidence + goal fidelity
  |
  v
Git / Evidence / Memory Commit
  accepted commit + causal memory + trajectory dataset
  |
  v
Self-Evolution Curator
  memory commit -> doctrine / skill / eval sample / next task
```

## Codex Goal Mechanism To Copy

Codex goal 能持续工作的原因不是“多跑几轮”，而是 runtime 持有目标状态：

- `thread_goals` 持久化 objective、status、token_budget、tokens_used、time_used_seconds。
- `GoalRuntimeEvent` 在 turn start/tool complete/turn finish/usage limit/external mutation/thread resume 时统一结算。
- `maybe_start_goal_continuation_turn` 只在空闲、无 queued input、goal 仍 active 时注入 continuation turn。
- `continuation.md` 明确要求保留完整 objective，不能把目标缩小成更容易完成的版本。
- completion 必须逐项 audit 当前文件、命令、测试、运行态等 authoritative evidence。
- blocked 不能第一次失败就标记，必须连续多轮同一 blocker 才允许 blocked。

A9 要抄的是这个结构：

```text
goal object
-> task slices
-> continuation prompt
-> accounting
-> completion/block audit
-> persisted status
```

不是简单 while-loop，也不是靠页面监控手动续命。

## Hermes Self-Evolution Mechanism To Copy

Hermes 的自我进化有三层：

1. Turn-level review：`background_review.py` fork review agent，只开放 memory/skill 工具，把用户纠偏、工作流修正、技术经验写成持久能力。
2. Library-level curator：`curator.py` 周期性审查 skill collection，按 umbrella class 合并、归档、保护 pinned，不让经验库碎片化。
3. Trajectory/datagen：`batch_runner.py` 和 `trajectory.py` 保存 completed/failed trajectories、tool stats、reasoning coverage、checkpoint，后续可压缩、回放、训练。

A9 要抄但要改造：

- Hermes 是 agent skill/memory 自我维护；A9 要扩展成工程执行治理：reference evidence、execution chain、git evidence、test evidence、session causal memory。
- Hermes background review 是后台 fork；A9 可以用 24h worker 做执行，用主监控做验收，但必须有 deterministic memory commit，不允许只靠自然语言自评。
- Hermes curator 维护 skill；A9 curator 要维护 doctrine、需求主线、错题本、reference gate、eval case。
- Hermes trajectory 面向训练数据；A9 trajectory 要同时支持回放评审、worker 质量评分、未来私有模型数据闭环。

## Data First Acceptance

后续评审不是先问“代码是否优雅”，而是先问数据结构是否代表真实业务：

- goal 表 / 状态：objective、status、budget、blocked_count、completion_audit。
- task 表 / 状态：goal_id、slice_id、phase、reference_sources、acceptance。
- execution_chain 表 / JSONL：prompt、commands、reads、patch、checks、tokens、findings。
- reference_evidence 表 / JSONL：project、path、commit、license、mechanism、copied_boundary。
- performance/cost：cached_input、uncached_input、event_bytes、latency、retry_count。

没有这些数据对象，UI/API/worker 都只是表面。

## Performance Second Acceptance

性能不是“少给 token”，而是：

- prompt cache 命中。
- uncached token 降低。
- event/log 输出可控。
- compression 成本可预测。
- worker 不重复读相同参考。
- Redis/MySQL 查询不阻塞热路径。
- 长目标可以跨 turn 续跑，不丢 objective。

## Immediate Next Steps

下一刀不要继续通讯功能，先做治理重构切片。顺序调整为先让 24h worker 具备“持续目标 + 自我进化证据”的骨架：

1. 新增 A9 goal runtime 最小数据模型：
   `goal_id/objective/status/token_budget/tokens_used/blocked_count/completion_audit`.
2. 增加 execution chain summary：
   每个 run 生成机器可读 `execution_chain.json`，记录 prompt、reference reads、commands、patch、checks、tokens、next_slice。
3. 新增 self-evolution memory commit：
   把 execution chain + session 精读归因为 doctrine / skill / eval sample / next task，保留原始 evidence path。
4. 新增 `docs/reference-review-gate.md`：
   定义每个任务必须记录 reference source、mechanism、boundary、license。
5. 升级 `scripts/a9_monitor.py`：
   增加 `reference_evidence_expert`、`goal_fidelity_expert`、`execution_chain_expert`。
6. 再恢复通讯五大块：
   node 状态机 -> Redis Streams 生产治理 -> 多机器接入 -> SSE replay -> 指标/soak。

## Current Verdict

A9 当前不是“不能跑”，而是：

```text
execution path can run
governance is not yet strong enough for unattended 24h
```

估算：

- 执行通路：80%+
- 参考优先治理：55%
- goal runtime：25%
- token/cost 架构治理：45%
- execution-chain observation：55%
- 真 24h unattended：65%-70%

所以必须先补治理，再继续长跑。
