# A9 最高形态架构聚合稿

> 状态：aggregation_draft，不是最终定案。
>
> 用途：把 A9 过去讨论、已做产物、需求方法论、参考项目、算力调度、Agent OS
> 和 NZX RWA 第一业务主线聚合到一份文件，供后续多轮博弈和 GPT 网页端重构。
>
> 日期：2026-06-04

## 给 GPT / 外部评审模型的使用说明

请把本稿当作“决策输入”，不是宣传稿，也不是已批准的执行计划。

评审目标：

1. 找出 A9 最高形态里的逻辑断点、层级混淆、过度设计、缺失角色和错误优先级。
2. 重构成更强的 architecture decision packet，明确哪些应定案、哪些应继续博弈、
   哪些应删除或降级为长期候选。
3. 检查 A9 是否仍服务于根主线：交易哲学、成熟机制复制、数据验证、24h 执行、
   session 因果治理、监控纠偏、训练闭环。
4. 不要直接建议“马上实现全部功能”。必须先完成需求/架构博弈闭环，再切
   `execution_next` 给 24h worker。

评审红线：

- 不要把 A9 简化成手机 App、普通后台、普通量化策略、普通 VPN、普通交易所或单个 AI
  worker。
- 不要把 NZX RWA 和 A9 Agent OS 混成同一层。NZX RWA 是第一重业务主线，
  A9 Agent OS 是底层控制面和执行基础设施。
- 不要把 Agent/AI 放入交易撮合热路径。
- 不要把 Redis 当交易权威账本。
- 不要把 compute RWA/tokenomics 当成已经验证的算力技术选型。
- 不要把参考项目“已下载”理解成“源码都可以直接复制”。复制源码前必须核验
  source/commit/license 并写 vendor manifest。

期望输出：

- 一份更清晰的 A9 最高形态架构图和分层说明。
- 一份“定案 / 待博弈 / 暂不做 / 删除噪音”清单。
- 一份第一刀 `execution_next` 建议，并说明为什么它比其他候选优先。
- 一份参考项目抄袭/魔改路线：抄机制、抄边界、抄失败治理，哪些不能抄源码。

## 0. 一句话

A9 不是单个机器人、单个页面、单个网关，也不是先做量化策略。

A9 的最高形态是：

```text
私有 Agent OS
+ 金融交易基础设施控制面
+ 私有算力/模型调度层
+ 交易 ResearchOps/训练数据闭环
```

NZX RWA Orderbook Appchain 是第一条重业务主线。当前 24 小时执行机器、
mobile/control、session governance、通信网关和参考项目复制流水线，都是为了
构建这套生态的基础设施。

## 1. 原始核心思想与因果变迁

A9 的原始核心不是“做一个页面”或“做一个后台 worker”，而是把一套交易工程哲学
变成可持续运行的 Agent OS。

最早的核心公式来自 `原始想法需求.md`：

```text
交易哲学
-> 交易逻辑
-> 风险边界
-> 数据验证
-> 最小策略闭环
-> 工程架构
-> TDD / 压测 / 监控
-> 小资金实盘
-> 归因优化
-> AI 辅助迭代
```

工程方法公式：

```text
找对标
-> 抽机制
-> 能抄绝不手搓
-> 多项目融合
-> 小步魔改
-> Diff / Git / Sandbox 管住
-> 数据验证
-> 压测
-> 监控
-> 轨迹入库
-> 训练/蒸馏私有模型
```

这套思想可以压缩成一句：

```text
交易哲学优先
+ 成熟逻辑复制
+ 多项目融合
+ 数据验证第一
+ 压测第二
+ 监控和全自动化
```

### 1.1 为什么会从类 Codex 变成 24h Agent OS

因果链：

```text
想做类 Codex 的 A9 智能体
-> 发现工程化抄项目都是一段段人工推动
-> 需要交互监控 + 24 小时智能执行机器
-> 做 24h 机器又必须先工程化它自己
-> 发现 Codex 交互 session 和 codex exec 机制不同
-> 交互窗口依赖 raw session / compact，exec 任务依赖外部 task/run/evidence
-> session 细节会在压缩和长上下文里丢失
-> 需要增量 session 精读、因果变迁、memory commit
-> 参考 mem0、LangGraph、OpenClaw、Hermes、Aider、Codex
-> 形成 A9 runtime 的统一路由、证据、任务、记忆和评审机制
-> 桌面限制又暴露远程控制痛点
-> mobile/control 从审批页升级为 GPT/Codex-like 主控入口
-> 多机器、私有网络、Rust/Redis/Tailscale/SSH/tmux 成为 Agent OS 基础设施
-> 最终收敛为私有 Agent OS + 金融交易基础设施控制面
```

### 1.2 当前理解

当前所有工作都是产品形态的一部分，但层级不同：

- 类 Codex client 是人机交互和代码执行入口。
- 24h worker 是持续执行机器。
- 主监控是方向、评审、纠偏和验收。
- session governance 是长期不丢因果细节的记忆底座。
- mobile/control 是随时接管主控入口和交易工作台。
- Rust/Redis/私有网络是稳定、快速、高并发、多机器接入的基础设施。
- NZX RWA 是第一条重业务主线。
- 私有模型训练是运行轨迹和验证数据沉淀后的结果。

这段因果变迁必须持续保留。后续任何 GPT 重构、24h worker 任务、代码实现或文档清理，
都要检查自己是否服务于这条主线，而不是被 UI、工程门禁、算力叙事或单点参考项目带偏。

### 1.3 增量精读后的新增因果

本稿已吸收最新 external Codex session 增量精读：

- extract:
  `/root/a9/.a9/external_sessions/019e488c-d5f9-7501-835a-bf6e8ff6d8a2/turns-455-577.json`
- raw source:
  `/root/.codex/sessions/2026/05/21/rollout-2026-05-21T11-20-49-019e488c-d5f9-7501-835a-bf6e8ff6d8a2.jsonl`
- approximate JSONL lines: `53562-71933`

新增变化：

- 需求分析方法论是根，不是产品角色的附属备注。每个 agent/role 都必须通过它理解
  真实问题、业务目标、数据模型、状态流、异常流和验收。
- `planning-with-files` 只能参考文件化工作记忆、中断恢复、PreCompact/Stop、并行隔离
  和 attestation；不能照搬它的 agent-owned plan 模型。A9 的 plan contract 由
  human/product/requirements/monitor 拥有，worker 只追加 findings/progress/mistakes/
  change_request。
- GBrain/GraphRAG/Graphify/LLM-Wiki 是长期 wiki/graph/brain 派生索引参考，不替代
  raw session、run evidence、git/test 和 curated causal memory。
- role memory 不是“所有角色都读全部精读”，而是统一事实源 + role-scoped packet。
  新接管的主控 Codex 窗口也必须按接手顺序读，不会天然知道全局。
- 最高形态从单纯 Agent runtime 扩展成生态：私有 Agent OS、顶级私有网络网关、
  弹性私有网络、私有智能层、交易底座、24h worker、mobile app、私有算力/模型调度。
- mobile 不只是 chat 或审批。chat/control 层远程连入私有网络服务器，菜单层承载交易、
  节点、策略、资产、风控、合规、算力、模型和数据等真实 workspace。
- `弹性算力选型.md` 被归类为 compute RWA/tokenomics 候选商业模型，不是严格技术选型；
  不能把 6 个月回本、100 倍 PE、质押借贷等当作架构事实。

## 2. 总架构分层

```text
用户 / 交易员 / 研发 / 运维 / 合规 / 做市商 / 机构 API
        |
Web / Mobile / CLI / API Client
        |
顶级入口与网关层
  Pingora/Rust Gateway, Auth, Rate Limit, Policy, REST, SSE, WebSocket
        |
私有网络与多机器接入层
  Headscale/NetBird/WireGuard, SSH/tmux fallback, node onboarding
        |
私有 Agent OS 智能层
  A9 supervisor, 24h worker, Codex-like client, OpenClaw-like workflow,
  session governance, memory commit, MoE review, evidence store
        |
私有算力与模型调度层
  GPU node pool, image/cache orchestration, inference/training jobs,
  model gateway, eval/datagen, 1-2x 4090 local path, cloud burst path
        |
金融交易业务服务层
  Rust CLOB, WAL, Risk, Account, Market Maker, Broker Adapter, Market Data
        |
Appchain 与资产结算层
  Arbitrum Orbit + Stylus/Rust, Vault, wNZX, Settlement, proof
        |
数据与审计层
  MySQL/PostgreSQL, Redis/Valkey/Dragonfly, Databend, Object Store,
  OpenTelemetry, Prometheus/Grafana/Loki/Tempo
```

关键边界：

- Agent/AI 不进交易热路径。
- 交易热路径必须是确定性系统：`Gateway -> Risk -> Rust CLOB -> WAL -> Settlement`。
- AI 做旁路：研发、评审、监控、异常归因、策略研究、做市参数建议、合规材料整理、
  运维辅助、训练数据沉淀。
- Mobile 是控制面入口，不是稳定性架构。
- 私有网络是基础设施，不是最终金融产品卖点。

## 3. 24 小时执行机器与主监控入口

A9 的核心产品形态不是普通后台任务系统，而是：

```text
人类/主监控 Codex 负责方向、需求博弈、架构判断、任务拆解、干预和验收
24h worker 负责执行：看参考项目、抄机制、魔改、测试、记录证据、继续下一步
mobile/control 负责把这条主控入口随时放到手机上
```

这里有一个关键产品要求：手机端不是单纯后台管理页，也不是审批入口。它首先要承接
“你和 Codex 当前交互窗口”的主控模型，同时也要成为 A9 交易工作台和私有网络能力的
移动入口。

### 3.1 24h + monitor 的交互模型

目标交互不是：

```text
后台列表 -> 点按钮 -> 看日志
```

而是更接近：

```text
Codex-like chat/control session
-> 主监控下达方向、纠偏、确认
-> A9 生成 bounded task
-> 24h worker 执行
-> monitor 看到意图、prompt、参考项目、执行链、diff、tests、session evidence
-> 发现偏航时强行介入、暂停、改任务、要求 repair
```

必须能看到：

- operator session tail：人类和主监控当前对话尾部。
- compact/session summary：压缩摘要和 raw session 索引。
- worker intent：worker 准备做什么，为什么做。
- worker prompt：bounded prompt 和引用的参考项目切片。
- execution chain：命令、文件、diff、测试、失败、修复。
- context/token pressure：上下文压力、缓存命中、真实 token 消耗。
- monitor intervention：人工/主监控什么时候介入，为什么介入。
- next task：下一步是 debate_next 还是 execution_next。

### 3.2 手机端产品选型

手机端是 Agent OS 的第一入口，也是未来交易功能的移动工作台。它要抄 GPT
mobile/chat 产品体验，而不是自己发明一个传统后台；但它不能只有对话层。

产品边界：

- 对话层：远程连入私有网络里的 A9/Codex-like server，承接主控对话、任务拆解、
  24h monitor 和 intervention。
- 功能层：菜单里可以挂载交易、节点、策略、资产、风控、合规、算力、模型、数据等
  workspace。
- 网络层：手机不直接理解服务器细节，通过 A9 gateway / private network / node
  registry 连接私有网络内的服务。
- 权限层：不同菜单功能按身份、设备、节点、资金权限和操作风险分级。

明确产品参考：

- GPT mobile / ChatGPT Web mobile：主聊天区、底部输入栏、左侧滑入菜单、会话列表、
  新会话、模型/工具状态、流式输出、输入中断和继续。
- Codex CLI/TUI：任务执行、工具调用、diff、状态、权限、compact、resume、agent/fork/side
  的交互心智。
- OpenClaw/Lobster：managed flow、approval wait/resume、strict envelope、policy attestation。

手机端必须包含的 tab / 面：

- `Chat / Command`：主控入口，类似 GPT 的交流沟通页面。
- `Runs`：24h worker 队列、运行中、完成、失败、repair。
- `Evidence`：run summary、diff、tests、logs、session close reading。
- `Nodes`：多机器、SSH/tmux、Tailscale/Headscale/NetBird 状态。
- `Trading Workspace`：交易工作台入口，不只是壳；后续承接行情、订单、持仓、资产、
  NZX RWA、做市、风控、对账和告警。
- `Compute / Models`：GPU 节点、推理服务、训练任务、模型网关和算力资源。
- `Settings/Policy`：模型、权限、网络、provider、token、approval 策略。

UI 原则：

- 首屏应该像 GPT chat，而不是传统 dashboard。
- 移动端菜单不要做透明侧栏。要抄 GPT mobile 的实测 drawer/overlay 体验：
  主菜单是非透明面板横向滑入，主内容被让位或遮罩；用户/账号信息可以用 bottom sheet。
- 交易工作台、算力、节点、策略都可以是固定菜单项，但不要抢主控 chat 入口。
- 页面只是控制面；canonical state 仍来自 A9 API、Redis/MySQL、run evidence 和 session
  evidence，不来自浏览器内存。
- 手机端可以执行真实交易/运维/算力功能，但高风险操作必须走权限、二次确认、
  policy attestation、审计和必要的人工确认。

## 4. 需求方法论是最高层

A9 不能靠“继续”驱动长期质量。大型任务进入执行前，必须先完成需求博弈和评审闭环。

来自 `docs/requirements-guide-close-reading.md` 和 `docs/worker-method-packet.md` 的核心：

```text
识别真实业务问题
-> 区分用户需求和系统需求
-> 业务对象/数据模型
-> 状态流/异常流
-> 参考项目机制
-> 架构边界
-> 验收标准
-> out_of_scope
-> 执行切片
```

核心判断：

- 需求讨论和同步占质量的 70% 以上，执行只是后半段。
- 产品/业务/架构/测试角色必须先同频，再让 24h worker 连续执行。
- 数据第一，性能第二。数据模型代表真实业务结构；性能代表系统厚度和深度。
- 门禁不应在业务和数据形态未定时写死。早期应以观测、证据和异常分类为主。
- 成本和 token 优化应来自架构、上下文治理、缓存和任务切片，不是随意数字限制。

### 4.1 Plan Ownership

计划文件是 A9 需求方法论落地的工具，不是替代方法论本身。

```text
human / product / requirements / monitor
  owns: problem, goal, scope, acceptance, out_of_scope, authority

execution worker
  may append: findings, progress, mistakes, evidence, change_request
  must not silently change: goal, scope, acceptance, product definition
```

`planning-with-files` 的可抄机制是文件化工作记忆、中断恢复、hooks 重注入、
并行隔离和 attestation。它的“同一 agent 可改 plan 目标/决策”的角色模型不抄。

### 4.2 角色职责

Product / Mainline：

- 保持主线，不让 UI、工程优化、模型训练、交易业务互相污染。
- 逼问“真实问题是什么”，能推翻普通方案。
- 查资料、看竞品、找成熟项目，决定抄、改、缝合或拒绝。
- 强调业务逻辑优先于工程实现。

Business：

- 给真实场景、角色、规则、权限、外部流程。
- 验证数据模型是否反映真实业务。

Architecture：

- 数据第一：对象、字段、状态、事件、权威源。
- 性能第二：延迟、吞吐、稳定性、恢复、成本。
- 审计旁路，除非审计本身就是核心业务状态。

Test / Acceptance：

- 验数据模型和状态流，不只验接口。
- 覆盖正常流、异常流、权限、审计、超时、重试、回滚。

Execution Worker：

- 只执行已决定的切片。
- 先看参考项目，抄机制，魔改实现，跑测试，记录证据。
- 不自行改产品定义、数据合同、验收标准。

## 5. A9 当前已经做了什么

当前 A9 已完成的是 24h agent runtime MVP，不是最终产品。

已实现能力：

- `scripts/a9_supervisor.py`：队列、run-loop、auto-next、worktree、检查、状态分类、
  prompt budget、repo map、event summary、context pressure、patch/scope guard、
  deterministic SEARCH/REPLACE apply、git governance、rollback-aware repair。
- `scripts/a9_checkpoint.py`：checkpoint lineage、channel history、copy-session。
- `scripts/a9_memory.py`：mem0 形状 memory adapter。
- `scripts/a9_session_refresh.py`：外部 Codex/operator session 索引和 bounded turn 抽取。
- `phase: session_close_reading`：把外部 session extract 转成 raw 精读证据。
- `scripts/a9_control_api.py`：最小 HTTP control API，暴露 status、run summary、
  operator session tail、submit command。
- `crates/a9-gateway`：Redis Streams submit/lease/ack/fail/heartbeat/status 原型。
- `crates/a9-worker`：Rust worker wrapper。
- `crates/a9-client`：Rust 客户端入口。
- 24h supervisor MVP 状态：可用，但应该按 `bounded_ready` 小步执行，不等于生产级无人值守。

当前文档主线：

- `原始想法需求.md`：原始想法主线。
- `docs/project.md`：A9 项目说明。
- `docs/worker-method-packet.md`：worker 方法包。
- `docs/requirements-review-closure.md`：需求评审闭环。
- `docs/communication-governance-framework.md`：通信治理框架。
- `docs/reference-selection-reassessment.md`：参考项目优先级重评。
- `docs/session-raw-close-reading.md` / `docs/session-raw-summary.md`：session 精读与总结。
- `docs/private-model-strategy.md`：私有模型路线。

## 6. 最终业务主线：NZX RWA Orderbook Appchain

外部文件：

- `/mnt/e/WSL_Share/NZX_RWA_Orderbook_Appchain_最终方案 (3).md`
- `/mnt/e/WSL_Share/NZX_RWA_技术实现全景图.svg`

第一阶段不是普通 DEX、不是普通券商、不是纯 VPN 网关，也不是高杠杆合约，而是：

```text
NZX 真实股票/ETF
-> SPV/信托/托管账户
-> 1:1 wNZX RWA 代币
-> Appchain 资金托管与结算
-> Rust CLOB 订单薄
-> 做市商二级市场深度
-> 券商 API 异步对冲/补库存
-> Databend 留痕审计
```

业务关键：

- 用户第一阶段买 `wNZX-XXX` RWA，不是直接登记在自己 CSN 名下的 NZX 股票。
- Orderbook 和做市商是核心，否则只是代购/申购赎回平台。
- Rust CLOB 是权威交易状态机。
- Redis/Valkey/Dragonfly 是可重建热缓存、状态镜像、行情分发、KYT 缓存、限流、
  非最终事件缓冲，不是撮合核心。
- 不改官方 Redis 源码作为主线。
- 不做暗箱 VIP 插队、不透明 Last Look、CRDT 双活订单薄。

交易热路径建议：

```text
用户链上入金
-> 可用余额镜像
-> 用户签名订单
-> Pingora Gateway
-> Risk Engine
-> Rust CLOB
-> Semantic WAL
-> Batch Settlement on Appchain
```

灾备：

```text
单主撮合
-> 热备重放 WAL
-> epoch fencing
-> 故障切换
```

## 7. 顶级网关与私有网络

A9 的网关不是单纯 HTTP server，而是 Agent OS 和金融交易系统共同的入口。

目标栈：

```text
Phone / Web / CLI operator
-> HTTPS REST typed commands
-> SSE event tail first
-> WebSocket later for terminal/chat
-> Rust a9-gateway hot path
-> Redis Streams / Functions / JSON / TimeSeries / Search / Bloom
-> Python supervisor/model/business logic
-> MySQL/PostgreSQL canonical durable state
-> Headscale/NetBird/WireGuard private network
-> SSH/tmux fallback takeover
```

抄的方向：

- Codex：事件是事实源，compact 是派生提示态。
- OpenClaw/Lobster：managed flow、expected revision、approval wait/resume、strict envelope、
  policy attestation。
- Barter-rs：重连 backoff、typed stream/connect error action、reconnecting stream lifecycle、
  audit state replica、external command boundary、disconnect strategy。
- Redis ecosystem：Streams、Functions、JSON、TimeSeries、Search、Bloom。

通信状态机：

```text
online -> stale -> offline -> degraded -> reconnecting -> online
```

命令必须有：

```text
command_id
target_node
expected_revision
ttl
created_by
policy_attestation
idempotency_key
evidence_path
```

## 8. 私有算力与模型调度层

这是当前 A9 架构里缺的一层，必须进入最高形态。

需求不是“能跑一个模型”，而是：

```text
私有 GPU 节点池
-> 秒级/近秒级拉起可复用推理服务
-> 训练/微调/评审/数据生成任务可调度
-> 1 台 4090 可跑，2 卡可扩展
-> 本地优先，云端可突发
-> 大镜像/大权重有预热、缓存、分层和节点亲和
```

### 8.1 候选技术选型

当前建议的最高形态候选：

| 层 | 候选 | 作用 | A9 初步判断 |
| --- | --- | --- | --- |
| GPU 节点管理 | Kubernetes + NVIDIA GPU Operator | GPU driver、device plugin、container toolkit、DCGM monitoring | 生产级主线候选 |
| GPU 调度 | KAI Scheduler / Run:ai lineage | AI/ML workload GPU allocation、fairness、gang/topology scheduling | 多 GPU/多任务后重点评估 |
| 推理服务 | vLLM / SGLang / NVIDIA NIM / Dynamo | batching、prefix cache、OpenAI-compatible API、分布式推理 | MVP 可 vLLM，生产对比 NIM/Dynamo |
| 任务编排 | Ray/KubeRay / Argo Workflows / Kubernetes Jobs | 训练、评测、数据生成、批任务 | 训练/datagen 层候选 |
| 镜像/权重缓存 | registry mirror、pre-pull daemonset、lazy image、local NVMe cache | 解决 200GB+ 镜像/权重启动慢 | 必须专项评估 |
| 模型网关 | A9 model gateway | provider 路由、成本、缓存、fallback、policy | A9 自己做控制面 |
| 本地单机 | systemd/docker compose + GPU runtime | 1x4090 开发、低成本推理、judge/editor | 第一阶段现实路线 |

外部公开依据：

- NVIDIA GPU Operator 官方文档说明它在 Kubernetes 中自动管理 NVIDIA driver、
  device plugin、container toolkit、DCGM monitoring 等 GPU 软件组件。
- KAI Scheduler README 说明它是 Kubernetes 原生 AI workload scheduler，
  面向大规模 GPU cluster、动态分配 GPU、兼顾 training/inference 和 fairness。
- NVIDIA NIM 是 NVIDIA 的模型推理/部署产品线候选。
- Dynamo 是 datacenter scale distributed inference serving framework 候选。
- vLLM 是开源推理 serving 主候选之一。

### 8.2 A9 的算力原则

- 4090 路线不是裸模型通杀 GPT-5.5，而是在 A9 的金融工程闭环里系统胜利。
- 4090 先承担本地低延迟推理、judge/editor、小模型、LoRA/QLoRA/蒸馏、快速试错。
- 两卡扩展要先验证真实任务：并行 worker、推理吞吐、评审模型、训练小批次。
- 大镜像不能每次冷拉。必须做：
  - 节点预热。
  - 权重本地缓存。
  - 镜像分层优化。
  - 常驻 warm pool。
  - 任务 admission。
  - GPU memory health/fragmentation 观测。
- 算力调度不能影响交易热路径。模型和 agent 任务走旁路。

### 8.3 算力资产金融化候选

外部文件：

- `/mnt/e/WSL_Share/弹性算力选型.md`

这份文件不是严格的弹性算力技术选型，而是一个 DePIN / 算力 RWA / 交易所飞轮的
商业设想。核心想法：

```text
物理 GPU/机房资产
-> 算力使用权 token / 算力币
-> Appchain 发售或流通
-> 交易所手续费回购/销毁
-> 算力币质押借贷
-> 反哺算力资产扩张
```

可以保留的启发：

- 算力不只是成本中心，也可能成为 RWA 资产层。
- A9 的 Appchain / Agent OS / GPU 调度 / 交易基础设施可以形成一套生态。
- 算力使用权、模型推理额度、训练额度、GPU node capacity 都可以被建模、审计和计量。
- 如果未来做 DePIN/RWA，算力资产需要 proof-of-compute、proof-of-capacity、
  SLA、折旧、能耗、位置、机器序列号、权属、托管和审计。

必须谨慎或暂不采纳的部分：

- “6 个月回本”“100 倍 PE”“首月收回 10 年租金”不能作为 A9 架构假设。
- 交易所手续费回购 token、算力币公开发售、质押借贷都可能触发证券、衍生品、
  借贷、托管、市场运营、AML/KYC/KYT 和税务问题。
- “影子银行”式表达不能进入合规产品叙事。
- 算力币不能替代真实算力服务质量，不能用金融叙事掩盖硬件折旧、电费、故障率、
  供需波动和模型生态变化。

因此这条线暂定为：

```text
compute_rwa_candidate
-> legal/compliance review
-> asset/data model
-> proof-of-capacity/proof-of-compute design
-> tokenomics stress test
-> small private pilot
```

它不是当前第一刀 execution_next。当前第一刀仍应先把 A9 的私有算力调度技术底座和
Agent OS 控制面定清楚。

## 9. 私有模型与训练闭环

A9 的私有模型路线不是先训练大模型，而是先造数据机器：

```text
顶级参考项目机制
-> A9 worker 执行轨迹
-> diff / tests / failures / repair / monitor intervention
-> session close reading / causal memory commit
-> role review / MoE verdict
-> eval store / training label
-> 私有金融交易工程模型
```

目标模型不是通用聊天模型，而是金融交易工程 agent：

- RepoReader
- DiffEditor
- RiskAuditor
- TradeInfraEngineer
- DataValidationAgent
- MarketMakerOpsAgent
- ComplianceEvidenceAgent

训练数据必须包含：

- 原始任务。
- 参考项目来源。
- 抄的机制。
- 数据/状态模型。
- patch。
- 测试和失败日志。
- 修复过程。
- monitor 介入原因。
- 最终验收和残留风险。

## 10. 参考项目池和候选底座

本地参考项目已下载到 `reference-projects/`。当前扫描到：

| 项目 | 本地 commit | 本地 license 文件 | 主要用途 |
| --- | --- | --- | --- |
| codex | `0b4f86095c80` | Apache-2.0 | coding agent loop、context、compact、sandbox、tool execution |
| openclaw | `229490a48924` | MIT | always-on gateway、managed flow、policy、memory、plugin |
| aider | `6435cb8b1e88` | Apache-2.0 | repo map、SEARCH/REPLACE、diff/edit 纪律 |
| barter-rs | `33e56188e209` | MIT | 交易级 Rust 通信治理、做市/行情/对冲参考 |
| hermes-agent | `a1eaad2fc0bf` | MIT | trajectory、self-improvement、datagen、agent runtime |
| ecc | `99baa8250096` | MIT | cross-harness operator、plugins、contexts、skills、token optimization |
| langgraph | `aa322c13cd5f` | MIT | checkpoint、channel history、graph workflow |
| mem0 | `606ede7c0aed` | Apache-2.0 | memory add/search/get/history API shape |
| gbrain | `eefe8b5741c2` | local license present, needs review | skill/agent knowledge structure reference |
| graphrag | `6d02c2355c3f` | local license present, needs review | graph memory / retrieval reference |
| graphify | `4b17f199afd3` | local license present, needs review | graph extraction/reference |
| llm-wiki | `7e9bd0adf0eb` | local license present, needs review | wiki-style knowledge organization |
| planning-with-files | `6f94643bd2b7` | MIT | file-based planning reference |
| cline | `2a351ffdd5cb` | local license present, needs review | IDE/webview agent UX, tool boundary |
| continue | `cb273098d968` | local license present, needs review | IDE assistant, context/provider abstraction |
| roo-code | `b867ec914575` | local license present, needs review | coding agent UX/workflow reference |
| openhands | `9a7e3edd67eb` | local license present, needs review | execution harness, coding agent runtime |
| swe-agent | `0f4f3bba990e` | local license present, needs review | issue-to-patch eval harness |
| aichat | `82976d349ad9` | MIT/Apache-2.0 | Rust CLI/provider/tools |
| opencode | `7566cfe602e8` | local license present, needs review | terminal agent product/reference |
| gemini-cli | `906f8a31513d` | local license present, needs review | CLI agent/product reference |
| autogen | `027ecf0a379b` | local license present, needs review | multi-agent orchestration |

注意：

- 参考项目不是 prompt 原料库，不能整仓塞给 worker。
- 复制源码必须记录 source/commit/license。
- 表格里的 license 是本地快速核验结果，只能用于“能否进入下一轮评估”的初筛；
  真正复制源码前必须逐文件核验许可证、NOTICE、依赖许可证和是否存在 generated/vendor
  代码。
- 未确认开源许可证的产品只能作产品参考，不可复制源码。
- `planning-with-files` 只作为 A9 plan lane 的机制参考，不能覆盖 A9 的需求方法论和
  角色边界。
- GBrain/GraphRAG/Graphify/LLM-Wiki 只作为长期知识/图谱/引用/缺口/矛盾索引参考，
  不进入 worker 热路径。
- Claude Code 和 Antigravity 仍是顶级产品对标，但当前未作为可复制源码底座。它们可用于
  产品交互、agent 心智、权限/计划/恢复体验的对标，不可当作 vendor source。

## 11. 底座选择建议

### 11.1 Agent OS 底座

主底座不应该只选一个项目。A9 应缝合：

```text
Codex local coding loop
+ OpenClaw managed gateway/workflow
+ Aider edit/repo-map discipline
+ LangGraph checkpoint lineage
+ mem0/OpenClaw memory governance
+ Hermes trajectory/datagen
+ planning-file recovery without worker plan ownership
+ graph/wiki derived memory sidecar
+ Redis hot control plane
```

第一刀底座建议：

- Codex：agent loop/context/compact/tool execution。
- OpenClaw：flow/revision/approval/policy/envelope。
- Aider：deterministic edit apply。
- Redis：hot event bus and state transitions。

### 11.2 通信/网关底座

```text
Pingora/Rust gateway
+ Redis Streams/Functions/JSON/TimeSeries/Search/Bloom
+ Barter-rs reconnect/error/audit mechanism
+ OpenClaw policy and flow envelope
+ Headscale/NetBird/WireGuard private network
+ SSH/tmux fallback
```

Barter-rs 在这里不是“普通参考”，而是交易级通信稳定性和异常治理的强参考。

### 11.3 交易底座

NZX RWA 交易底座应以 Rust CLOB 为权威状态机：

```text
Rust CLOB
+ semantic WAL
+ account/risk engine
+ market maker engine using barter-rs mechanisms
+ broker adapter
+ Appchain settlement
+ Redis mirror
+ Databend audit
```

Barter-rs 更适合做：

- market data stream。
- reconnecting socket。
- strategy/market maker framework。
- broker/exchange adapter 思路。
- audit state replica。

不建议直接把 barter-rs 当 CLOB 内核。

### 11.4 算力/模型底座

阶段化：

```text
Stage A: 单机 4090
  Docker/systemd + NVIDIA container runtime + vLLM/SGLang + A9 model gateway

Stage B: 2 卡 / 多任务
  pre-pull image + local NVMe weight cache + model warm pool + job admission

Stage C: 私有 GPU cluster
  Kubernetes + NVIDIA GPU Operator + KAI Scheduler/Run:ai lineage
  + vLLM/NIM/Dynamo + Ray/KubeRay/Argo
```

## 12. 当前不要混淆的边界

不要混成一坨：

- 24h worker 是执行基础设施，不是最终金融交易产品。
- Mobile 是入口，不是稳定性架构。
- 私有网络是节点连接和控制面基础设施，不是合规金融产品卖点。
- Redis 是 hot control/cache/event mirror，不是交易权威账本。
- AI/Agent 是研发和运营旁路，不是撮合热路径。
- 私有模型是数据闭环结果，不是第一天先训练。
- NZX RWA 是第一条业务主线，不代表 A9 只能做这一条。
- 算力币/DePIN/RWA 是候选商业飞轮，不是当前已验证的弹性算力技术选型。
- 手机端控制面必须像 GPT/Codex 主控交互，不是普通后台管理系统。
- 手机端也是交易和私有网络功能入口，不只是 chat；chat 负责远程连接和主控，
  菜单承载真实业务 workspace。
- A9 的根主线是交易哲学、成熟机制复制、数据验证、24h 执行、session 因果治理、
  监控纠偏和训练闭环，不是某个单独页面、网关或模型。

## 13. 给 GPT 网页端重构的问题清单

请基于本聚合稿做顶级重构，重点博弈。请先输出“问题诊断”，再输出“重构方案”，
最后输出“第一刀建议”，不要直接进入代码实现：

1. 上面“交易哲学 -> 数据验证 -> 24h Agent OS -> session 因果治理 -> 私有模型”的因果链是否完整？
2. A9 最高形态是否应定义为“私有 Agent OS + 金融交易基础设施控制面 + 私有算力调度层”？
3. NZX RWA 作为第一业务主线是否合理？它和 A9 Agent OS 如何分层？
4. 参考项目底座应该如何选：Codex、OpenClaw、Aider、Barter-rs、Hermes、ECC、LangGraph、mem0 哪些进入第一刀？
5. `planning-with-files`、role memory、graph/wiki references 应该如何进入 A9，而不让 worker 越权改 plan？
6. Barter-rs 应作为交易/通信/做市哪一层的主参考？哪些不能直接抄？
7. GPU/算力层应该选 Kubernetes + NVIDIA GPU Operator + KAI/Run:ai lineage，还是先用单机 Docker/systemd + vLLM？
8. 200GB+ 训练/推理镜像和大权重如何做秒级/近秒级启动？需要哪些缓存、预热、镜像和节点调度机制？
9. 需求方法论如何落入每个 agent/worker prompt，而不是只存在文档里？
10. MoE 评审角色是否应按 Product/Business/Architecture/Test/Security/Ops/Cost/Data 建模？
11. 当前 A9 已实现的 24h runtime 哪些保留、哪些重构、哪些删除？
12. 手机端是否应明确抄 GPT mobile + Codex CLI 交互模型，而不是后台 dashboard？
13. 24h worker 的 monitor view 应该暴露哪些意图、prompt、session、执行链和介入证据？
14. 手机端交易工作台应该先做哪些真实功能：行情/订单/持仓/资产/风控/告警/做市监控？
15. 算力币/DePIN/RWA 这条商业飞轮是否进入长期候选？如果进入，法律/合规/资产审计前置条件是什么？
16. 哪些内容是过期噪音、重复文档、错误假设或应该归档的临时实现？
17. 下一刀应该是继续通信治理、算力调度底座、手机主控入口，还是先统一文档和任务合同？

## 14. 推荐下一步

下一步不是马上写大代码，而是做一次需求/架构博弈闭环：

```text
本聚合稿
-> GPT 网页端重构
-> 人类/主监控评审
-> 形成 A9 最高形态 decision packet
-> 切出第一刀 execution_next
-> 交给 24h worker 小步实做
```

第一刀候选。默认优先级不是“哪个功能更酷”，而是哪一刀最能降低后续返工和跑偏：

1. `architecture_decision_packet`：定 A9 最高形态、分层、边界、底座选择。
2. `reference_baseline_scan`：针对 Codex/OpenClaw/Aider/Barter-rs/Hermes/ECC 做底座候选评审。
3. `compute_scheduler_research`：只评估 GPU Operator/KAI/vLLM/NIM/Dynamo/Ray/KubeRay 和 4090 路线。
4. `mobile_control_product_packet`：明确 GPT-like chat/control、Codex-like execution view、
   24h monitor view、Trading Workspace tab、Compute/Models tab 和私有网络远程连接模型。
5. `compute_rwa_candidate_review`：只评审算力币/DePIN/RWA 商业模型的合法性、资产模型、
   proof 和风险，不进入执行。
6. `noise_cleanup_plan`：删除/归档过期文档和代码噪音，但必须先有保留清单。

## 15. 外部资料索引

- NVIDIA GPU Operator: <https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/index.html>
- KAI Scheduler: <https://github.com/kai-scheduler/KAI-Scheduler>
- NVIDIA NIM: <https://docs.nvidia.com/nim/index.html>
- NVIDIA Dynamo: <https://github.com/ai-dynamo/dynamo>
- vLLM docs: <https://docs.vllm.ai/>
