# A9 项目说明

## 背景

A9 要先做的不是金融量化模型本身，而是一个私有的 24 小时执行机器。

这个 24 小时执行机器是基建脚手架，不是最终产品。它把高效工作方法跑成
稳定系统：

```text
找对标 -> 分析 -> 抄机制 -> 微调/魔改 -> 测试验证 -> 记录证据 -> 下一轮
```

这个机器对标 Codex CLI、Claude Code、OpenClaw/Lobster、Aider、Cline、OpenHands、SWE-agent、aichat 等成熟系统。核心不是“问一句答一句”，而是持续完成：

```text
看成熟项目 -> 抄机制 -> 魔改实现 -> 跑测试 -> 记录证据 -> 继续下一步
```

最终产品不是“监控页面”或“24 小时机器人”本身，而是 A9 自己的综合
agent：类 Codex CLI + OpenClaw 的私有 agent client/runtime，能完成目标、
能写代码、能治理上下文、能接工具和工作流。金融/量化 Codex 是这个综合
agent 稳定后的垂直化训练和数据项目。

当前阶段先把 agent 基建做扎实。没有稳定执行机器，后续业务模型、交易研究、
训练数据闭环都没有可靠来源。

## 目标

做出 A9 自己的 agent client + supervisor stack：

- Rust 做稳定客户端、网关、worker、治理热路径。
- Python 做快速变化的大模型逻辑、prompt、业务策略、个性化逻辑。
- MySQL 做长期 canonical state。
- Redis Stack 做热路径 stream、JSON、Bloom、TimeSeries、worker runtime。
- 每个任务一个 git worktree。
- 每次运行保存 prompt、events、patch、checks、summary、state、evidence。

目标形态：

```text
人类/监控者给方向
  -> A9 client/supervisor 建任务
  -> worker 看参考项目
  -> worker 抄机制并魔改
  -> 跑测试和检查
  -> 保存证据/状态/进度
  -> 自动生成下一任务
```

控制面目标：

```text
手机/浏览器/CLI control plane
  -> 承接人类和主监控 Codex 的当前交互窗口
  -> 查看 flows、runs、logs、diff、token、checks、queue
  -> submit / pause / resume / stop / retry / approve / reject
  -> 触发 session_refresh / close_reading / compact / continuation
  -> Redis/MySQL/A9 supervisor 执行确定性状态推进
  -> host/worktree/worker 继续做真实计算和代码修改
```

`原始想法需求.md` 里保留的 Codex mobile/automation 线索提醒 A9：
这类产品形态拆成两层：手机是完整控制面，host 是执行面。审批只是控制面里的
一个动作，不能把 mobile 设计窄成 approval entry。

更重要的是，手机端必须包含当前“人类 <-> 主监控 Codex”这条交互主线。
否则 worker 可以 24 小时跑，但主监控窗口仍然被电脑、上下文压缩和断线限制，
无法真正不停。A9 mobile 的第一等对象不是 approval，而是 operator session：

- 查看当前主监控对话尾部、压缩摘要、raw session 索引和最近决策。
- 把手机输入写成 operator command，再由 A9 生成 bounded task。
- 触发外部 session 的 `session_refresh -> session_close_reading`，把你我当前
  对话继续变成可治理 evidence。
- 当主监控窗口上下文过长或断开时，用手机端基于 raw evidence 恢复下一条 continuation。
- 保留“主监控对话”和“A9 runtime run”两类 session 的链接，但不混存。

阶段边界：

- 当前基建：主监控 + 自动化执行机器，目标是高质量、可验证地连续抄和改。
- 平台产品：类 Codex CLI/OpenClaw 的综合 agent，目标是可交互、可路由、
  可工作流、可写代码、可治理上下文。
- 垂直产品：金融 Codex，目标是基于平台 agent 和金融场景数据训练/沉淀能力。

2026-06-04 增量精读后最高形态已经扩展为：

```text
私有 Agent OS
+ 金融交易基础设施控制面
+ 私有算力/模型调度层
+ 交易 ResearchOps / 训练数据闭环
```

当前讨论入口已经升级为：

- `docs/a9-ultimate-architecture-aggregation.md`：A9 内部最高形态聚合草案。
- `docs/external-gpt/2026-06-04/A9_AgentOS_金融交易环境重构决策包.md`：
  GPT/web 外部重构后的决策包输入。
- `docs/external-gpt/2026-06-04/intake.md`：A9 对 GPT 决策包的吸收结论。

这些文件仍不是直接开工许可。它们把几个层级统一到一张图：

- 原始根主线：交易哲学优先、成熟机制复制、数据验证第一、压测第二、监控和自动化。
- 运行时基建：24h worker、session governance、role-scoped memory、plan ownership。
- 移动入口：GPT/Codex-like 主控对话 + 交易/节点/策略/资产/风控/算力 workspace。
- 私有网络/网关：Rust/Redis/Headscale/NetBird/WireGuard/SSH/tmux 的稳定连接底座。
- 算力调度：4090、本地/多卡/集群、模型 serving、镜像/权重缓存和 warm pool。
- 第一重业务线：NZX RWA Orderbook Appchain。
- 高风险候选：compute RWA/tokenomics，只能进入法律、合规、资产审计和压力测试评审。

下一步不是直接实现所有层，而是先把 GPT 决策包和 A9 聚合稿做成 ADR decision
packet，再切 `execution_next` 给 24h worker。默认优先级已经调整为：

```text
P0 Architecture Decision Packet
P1 Reference Baseline Scan + Vendor Manifest
P2 A9 Core Contract
P3 Gateway / Bus refactor
P4 AgentOS Runtime
P5 Mobile / Remote Control Packet
P6 Compute Stage A
P7 NZX Technical MVP
```

## 已做背调和分析

已经分析和复制过这些机制：

- Codex：上下文历史、压缩、结构化事件、本地 agent loop。
- OpenClaw/Lobster：已下载完整仓库到 `reference-projects/openclaw`。重点看
  `extensions/lobster`、`extensions/policy`、`extensions/memory-core`、
  `extensions/memory-wiki` 和 `skills/`，用于 agent workflow、插件/技能协议、
  policy gate、机器可读 CLI、长期记忆和多 agent 隔离。重评后 OpenClaw/Lobster
  升级为 24 小时 runtime/gateway/managed-flow 的主参考，见
  `docs/reference-selection-reassessment.md`。
- ECC：已下载到 `reference-projects/ecc`，来源
  `https://github.com/affaan-m/ECC`，commit
  `99baa8250096f2d295583572399a5c9aba2ce312`，license `MIT`。重点参考
  cross-harness operator system、session adapter contract、plugin/hook/agent skills、
  token optimization 和 continuous learning 设计。ECC 目前只作为 reference
  source；未来复制源码切片时必须单独走 `vendor_import` 并记录 source/commit/license。
- Mobile Agent UI：只作为控制入口和产品壳保留。当前主线不是继续抠页面，
  入口细节不要干扰通讯治理和 24 小时 runtime。
- Barter-rs：已下载到 `reference-projects/barter-rs/`，作为通讯治理和
  交易级 Rust gateway 的主参考，见 `docs/communication-governance-framework.md`。
- Aider：repo map、最近上下文保真、SEARCH/REPLACE edit/diff 纪律。Aider 不是“龙虾”主参考。
- LangGraph：checkpoint、parent lineage、channel history、copy-session。
- mem0：memory add/search/get/history 形状。
- Cline / OpenHands / Continue / Roo / SWE-agent / aichat / opencode：浏览器/TUI 边界、终端客户端、队列 harness、产品行为。

可复制的源码切片放在 `vendor-src/`，并记录 manifest/license。大型参考仓库可以留在本地，但不能直接变成 prompt 的原始上下文。

## 当前架构

已实现：

- `scripts/a9_supervisor.py`：队列、run-loop、auto-next、worktree、检查、状态分类、证据/状态写入、prompt budget、repo map、event summary、context pressure、patch/scope guard、deterministic SEARCH/REPLACE apply、git governance、rollback-aware repair prompt。
- `scripts/a9_checkpoint.py`：checkpoint lineage、channel history、copy-session。
- `scripts/a9_memory.py`：mem0 形状的 memory adapter。
- `scripts/a9_session_refresh.py`：外部 Codex/operator session 索引和 bounded
  turn 抽取，用于把当前窗口 JSONL 变成可治理 evidence；supervisor 已有
  `phase: session_refresh` 确定性路由，不调用 worker/model，也不进入抄项目流水线。
- `phase: session_close_reading`：消费 bounded extract，把 turn/line/原话预览、
  assistant/tool 证据和路径追加到 raw 精读文档；确定性浅层落盘，不冒充深度理解。
- `session_refresh -> session_close_reading -> next session_refresh`：外部 Codex
  session 的 managed mini-flow 已接入 `--auto-next`，按批次连续跑，到尾自动停。
- `scripts/a9_soak.py`：fake worker 的无人值守 soak 测试。
- `scripts/a9_service.py` 和 `infra/systemd/a9-supervisor.service`：服务化。
- `scripts/a9_control_api.py`：最小 control HTTP JSON API，暴露
  operator session tail、supervisor status、latest run summary 和 submit command。
- `crates/a9-gateway`：Redis Streams submit/lease/ack/fail/heartbeat/status。
- `crates/a9-worker`：Rust worker wrapper。
- `crates/a9-client`：第一个 Rust 客户端入口，支持 init/config/submit/status/resume。

控制面边界：

- 现在已有 CLI/service/status 能看 queue、run、progress、worker token 和进程。
- 最小 HTTP control API 已有；当前通讯治理框架见
  `docs/communication-governance-framework.md`。
- 下一步的 mobile/control plane 不应该直接接管 raw Codex TUI，也不应该只做审批页。
- 正确入口是 A9 API/CLI/gateway：读取 `.a9/runs`、Redis flow、MySQL checkpoint、
  policy attestation、checks、diff 和 token usage，再发出确定性 command。
- tmux/SSH/Tailscale 可以作为早期远程兜底，但不是 canonical state。

运行时状态：

- `.a9/tasks/queue`
- `.a9/tasks/running`
- `.a9/tasks/done`
- `.a9/runs`
- `.a9/progress.json`
- `.a9/daemon_heartbeat.json`
- `.a9/client/sessions`
- `.a9/external_sessions`
- `.a9/soak/latest.json`

## 当前进度

24 小时自动化 MVP 闭环已经完成，但只能按 `bounded_ready` 小步实跑：

总体 capability progress: `100.0%`。这是“主监控 + AI 自动化执行机器”的 MVP 进度，不代表生产级长跑已经完成。

分层进度：

- runtime: `100.0%`，MySQL/Redis 中间件探测、Rust gateway、supervisor queue loop、Rust worker wrapper、systemd/service helper 已有。
- context: `100.0%`，证据/状态/deep marks、checkpoint lineage、channel history、memory adapter、上下文压缩、repo map、event summary、copy-session 已有。
- automation: `100.0%`，auto-next、copy pipeline templates、soak test 已有。
- governance: `100.0%`，patch guard、scope guard、deterministic SEARCH/REPLACE apply、already-applied detection、rollback-aware repair prompt 已有。

已具备的主线能力：

- queue execution 可用。
- auto-next copy pipeline 可用。
- soak test 可用。
- Rust client front door 已有。
- readiness 可输出 `not_ready` / `bounded_ready` / `daemon_ready`。
- 真实 Codex worker 可用 `.a9/codex-home` / `.a9/tmp` 隔离运行。
- worker event/byte budget gate 可截断过度探索和错误事件增长。
- worker `turn.completed` usage 会聚合为 `actual_token_usage`，写入 summary、
  context pressure、Redis session payload 和 MySQL checkpoint token_usage。Spark
  可做低成本候选模型监控，但无人值守默认 worker 使用稳定 `gpt-5.3-codex`，避免
  toolset 不兼容中断 auto-loop。
- accepted worker diff 会在隔离 worktree 里原子 commit。
- failed/repair worker diff 会先留证据再 rollback 到 base。
- worker 可只输出 `SEARCH/REPLACE`，由 supervisor deterministic apply 后再进入 guard、test、git governance。
- `SEARCH` 找不到但 `REPLACE` 已唯一存在时，会标记 `already_applied`，避免 repair loop 重复发块。
- repair prompt 会结合 patch apply 和 git governance：保留 worktree 时不重发成功块，已 rollback 时先检查当前文件内容。
- 当前测试/build 通过。

## 还要做什么

MVP 完成不代表生产级完成，也不代表最终产品完成。

当前最高优先级不是继续堆功能，而是把需求评审闭环做完。评审闭环以
`docs/requirements-review-closure.md` 为准：没有明确的 `decision_status:
decided`、数据/状态合同、异常流、验收证据、out_of_scope、allowed_execution
和角色 signoff，就不能把 review/analysis 产物当成 `execution_next`。

当前状态：

- 24 小时 worker 执行能力可用，后台 supervisor/control API 可运行。
- 最近 ECC 机制抽取已经完成，但它仍暴露出 review 与 execution 边界不够强：
  worker 能写分析文档，但不等于下一步执行已经定案。
- 当前 24 小时机器 idle 的直接原因是 queue 为空；根因是还没有 closed decision
  packet 生成下一条 `execution_next`。

下一步只保留高优先级：

- 先产出当前 24 小时 runtime 主线的 review closure / decision packet，确认下一条
  可执行切片。
- 只有 closure 完成后，再把任务投给 24 小时 worker 小步执行。
- 如果 closure 未完成，worker 只能做 `debate_next` 的资料精读、参考扫描、数据/状态
  建模、角色评审和 change request。

- `docs/runtime-governance-review-2026-05-29.md` 已确认一次主线偏差：
  最近执行通路修得较快，但 reference review、Codex goal runtime、Hermes context
  engine/trajectory、执行链观测和 token/cost 架构治理没有进入硬流程。下一步先补
  reference-review gate、A9 goal 最小数据模型、execution chain summary 和 monitor
  专家，再继续通讯五大块。

- 错误模式 gate 已开始落地：worker budget stop、网络重连/连接重置、app-server
  初始化失败、Broken pipe 会从普通 worker failure 拆成机器可读状态，并写入
  run summary 的 `worker_failure`。
- 继续扩展错误模式 gate：把更多真实 Codex/app-server 事件样本纳入分类和 retry 策略。
- RedisJSON + Redis Functions revisioned managed flow 第一版已落地：
  `a9_middleware.py flow-create / flow-transition / flow-get`，`transition_flow`
  要求 `expected_revision`，旧 revision 会被拒绝，防止双监控/双 worker 同时推进。
- OpenClaw/Lobster approval/wait/resume 第一版已落地：
  `a9_middleware.py flow-wait / flow-resume` 会把 flow 原子推进到 `waiting`，
  写入 `approval_request` envelope，再用 `approval_id` 或 `resume_token` 恢复到
  `running`/`rejected`，全程受 Redis revision 保护。
- OpenClaw/Lobster strict worker envelope 第一版已落地：
  任务 prompt 写 `strict_worker_envelope: true` 时，supervisor 会从 worker final
  中解析 `protocolVersion/ok/status/output/error/requiresApproval` JSON envelope；
  缺失或错误会进入 `needs-repair`，`needs_approval` 会进入 `needs-approval`。
- `needs-approval -> Redis flow-wait` 第一版已落地：
  当 strict envelope 返回 `needs_approval` 且任务携带 `flow_id` /
  `flow_expected_revision` 时，supervisor 会调用 Redis `set_waiting_flow`，把 managed
  flow 原子停到 `waiting`，等待后续 `flow-resume`。
- `session_refresh -> session_close_reading -> next session_refresh` mini-flow 和普通
  copy pipeline 都已开始接入 Redis managed flow：任务可携带 `flow_id` /
  `flow_expected_revision`，run 成功后通过 Redis Function 推进 revision，并把
  `flow_transition` 写回 summary；如果 revision transition 失败，会阻断 auto-next。
- OpenClaw policy attestation 第一版已落地：
  supervisor 会按 OpenClaw `policy-state.ts` 的形状计算 `policy_hash`、
  `workspace_hash`、`findings_hash`、`attestation_hash`，写入
  `policy_attestation.json`、run summary、evidence/state channel 和 Redis session
  payload；managed flow transition/wait 会带上 attestation hash 短引用。
- 用 Redis Functions 做 revisioned flow transition，避免双监控/双 worker 竞争同一个 flow。
- 把 worker 输出收敛成 strict envelope，而不是自由文本结果。
- 下一步用 strict task 模板跑真实小任务长跑，观察 approval、repair、policy hash、
  token budget 和 auto-next 是否稳定。
- 把 Redis/MySQL 状态机更多迁到 Rust，但 Python 继续负责 prompt、模型业务和快速变化逻辑。
- 做更长时间的 bounded soak 和真实小任务试炼，再决定是否进入 `daemon_ready`。
- 区分核心文档和运行时文档，避免文档膨胀。

当前通讯/control 阶段已收口，见 `docs/stage-handoff-2026-06-01.md`。
下一轮不要继续堆功能，先做外部 Codex/operator session 增量精读、因果链
统筹、想法迭代细节、观测问题分析和噪音去除。原因是当前最大风险已经从
“代码缺一块”变成“主线记忆漂移、旧想法和新实现混在一起”。

业务领域模板，比如量化/金融，等执行机器稳定后再做。

## 文档事实源

- 文档入口/噪音分层：`docs/context-governance.md`
- 原始 session：`/root/.codex/sessions/2026/05/21/rollout-2026-05-21T11-20-49-019e488c-d5f9-7501-835a-bf6e8ff6d8a2.jsonl`
- 原始想法：`原始想法需求.md`
- raw 精读：`docs/session-raw-close-reading.md`
- raw 总结：`docs/session-raw-summary.md`
- 因果变迁总线：`docs/session-causal-memory.md`
- session 治理：`session-governance.md`
- 参考重排：`docs/reference-selection-reassessment.md`
- 通讯治理：`docs/communication-governance-framework.md`

旧 `docs/session-close-reading.md` 和 `docs/session-summary.md` 已删除；历史事实以
raw session、`docs/session-raw-close-reading.md` 和 `docs/session-raw-summary.md`
为准。

Session 分两类：

- 外部 Codex/operator session：当前人机协作窗口产生的 JSONL。用途是精读、恢复
  原始意图、保留变迁原因、生成 doctrine 和后续任务。
- A9 runtime session：A9 24 小时执行机器自己产生的 `.a9/tasks`、`.a9/runs`、
  未来 managed flow 和 worker evidence。用途是执行治理、patch/check/guard、
  retry/repair/approval。

两类 session 只能通过 evidence/task/flow 引用关联，不能混成一个 mem0 记忆库。

`docs/session-causal-memory.md` 是精读后的统筹层。`session_refresh` 和
`session_close_reading` 只产出 bounded evidence 和索引；每次有 meaningful
增量后，必须把“为什么从 A 变成 B、哪些旧想法过期、当前 worker 不该做什么”
写入 causal memory，再恢复 24 小时 worker。
mem0 只存抽取后的长期事实、决策、风险、流程，并必须带 evidence 引用。
