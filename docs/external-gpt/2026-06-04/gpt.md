根据 2026-06-04 的文档和我刚核对的 A9 GitHub 仓库，我已经把这次重构收敛成一份正式决策包：**A9 不是 NZX 项目本身，而是能承载 NZX、远程控制、24h AI Agent、弹性算力、交易监控和后续金融业务的 AgentOS 金融交易底座**。你上传的聚合稿里也明确写了：A9 的最高形态是“私有 Agent OS + 金融交易基础设施控制面 + 私有算力/模型调度层 + 交易 ResearchOps/训练数据闭环”，NZX RWA Orderbook Appchain 是第一条重业务主线。

我把正式文档和全景图输出好了：

* [下载：A9 AgentOS 金融交易环境重构决策包.md](sandbox:/mnt/data/A9_AgentOS_金融交易环境重构决策包.md)
* [下载：A9 AgentOS 金融交易环境全景图.svg](sandbox:/mnt/data/A9_AgentOS_金融交易环境全景图.svg)

核心结论如下。

## 1. A9 的新定义

**A9 = AgentOS 金融交易环境底座。**

它要同时承载：

```text
高性能交易
+ 弹性服务逻辑
+ 私有 AI Agent 24h 执行
+ 移动端远程控制
+ CLI/TUI 交互监控
+ 私有网络节点管理
+ 私有算力 / 模型调度
+ ResearchOps / 训练数据闭环
+ NZX RWA Orderbook Appchain 第一业务应用
```

所以，A9 不能继续被理解成“一个 worker”“一个手机 App”“一个普通网关”或“一个交易所项目”。你文档里也明确列了红线：不要把 A9 简化成手机 App、普通后台、普通交易所或单个 AI worker；不要把 NZX RWA 和 A9 AgentOS 混成同一层；Agent/AI 不能进入交易撮合热路径；Redis 不能当交易权威账本。

## 2. 我给你的直接 copy 入体清单

不是所有项目都应该 copy。真正能入体的只应该是 license 清晰、边界清晰、能写 vendor manifest 的部分。

**第一批建议直接 copy / vendor 入体：**

| 项目                        | 入体用途                                                           | 方式                                       |
| ------------------------- | -------------------------------------------------------------- | ---------------------------------------- |
| **Codex**                 | agent loop、context/compact、sandbox、tool execution、CLI/TUI 执行心智 | copy 小模块/机制，做 `a9-agent-exec`            |
| **Aider**                 | repo map、SEARCH/REPLACE、deterministic patch、diff/edit 纪律       | copy 编辑/patch 机制，做 `a9-edit`             |
| **barter-rs**             | 行情流、重连、交易网关、信号网关、做市、对冲、异常治理                                    | copy/改造为 `a9-market`、`a9-mm`、`a9-broker` |
| **planning-with-files**   | 文件化计划、中断恢复、attestation                                         | copy 机制，做 `a9-plan`                      |
| **aichat / provider 类项目** | Rust CLI、模型 provider、工具调用抽象                                    | 先 license 核验，再局部吸收                       |

这里特别强调：**barter-rs 是核心，但不是撮合内核。** 它适合做 market data stream、reconnecting socket、strategy / market maker framework、broker/exchange adapter、audit state replica，不建议直接当 CLOB 内核。你上传的 A9 聚合稿也是这个判断。

**第二批只抄机制，不先 copy 源码：**

```text
OpenClaw / Lobster：managed flow、approval、policy、strict envelope
LangGraph：checkpoint lineage、channel history、graph workflow
mem0：memory add/search/get/history API shape
Hermes-agent：trajectory、self-improvement、datagen
ECC：cross-harness operator、plugins、contexts、skills
OpenHands / SWE-agent：eval harness 和 issue-to-patch 参考
Continue / Cline / Roo-Code：IDE / Webview / UX 参考
GraphRAG / Graphify / LLM-Wiki / GBrain：长期知识图谱 sidecar
```

这些不能一股脑整仓塞进 A9。你文档里已经提醒：参考项目不是 prompt 原料库，复制源码前必须核验 source / commit / license，并写 vendor manifest。

## 3. 当前 A9 代码怎么改

我核对了 GitHub 仓库结构。当前 repo 主要是 `crates`、`docs`、`infra`、`scripts`、`tests`、`vendor-src`，并且 Rust workspace 目前只有 `a9-client`、`a9-gateway`、`a9-redis-probe`、`a9-worker` 几个 crate。([GitHub][1]) ([GitHub][2])

### 保留，但降级为 legacy 的东西

这些不要删，先保留为实验成果：

```text
scripts/a9_supervisor.py
scripts/a9_checkpoint.py
scripts/a9_session_refresh.py
scripts/a9_memory.py
scripts/a9_patch_apply.py
scripts/a9_patch_guard.py
scripts/a9_scope_guard.py
scripts/a9_vendor.py
scripts/a9_soak.py
crates/a9-gateway 当前 Redis Streams 原型
crates/a9-redis-probe
```

你现在已经有 24h runtime MVP，包括 supervisor、checkpoint、memory adapter、session refresh、control API、Redis Streams 原型、Rust worker wrapper 等能力；但文档里也说了，这只是 MVP，不是生产级无人值守系统。

### 必须重写的东西

```text
当前 crates/a9-gateway
-> 改名 / 拆成 a9-bus 或 a9-redis-control-prototype
-> 新建真正的 Pingora Rust Gateway

当前 a9-client
-> 重写成 CLI/TUI operator client

当前 a9-worker
-> 重写成 node-side worker runtime

scripts/a9_control_api.py
-> 过渡保留，最终迁移到 Rust a9-gateway

scripts/a9_tailscale.sh
-> 归档或改为 private-net adapter
-> 不绑定商业 Tailscale，目标是 Headscale / NetBird / WireGuard

scripts/a9_remote.py / a9_node.py
-> 迁移到 crates/a9-node
```

### 新 workspace 建议

```text
crates/a9-core
crates/a9-gateway
crates/a9-bus
crates/a9-runtime
crates/a9-agent-exec
crates/a9-edit
crates/a9-plan
crates/a9-memory
crates/a9-node
crates/a9-model-gateway
crates/a9-compute
crates/a9-trading-core
crates/a9-market
crates/a9-mm
crates/a9-nzx
crates/a9-appchain
crates/a9-observability
```

## 4. 明确删除 / 归档噪音

不要立刻物理删除，先归档到 `docs/archive/` 和 `scripts/legacy/`。

第一批归档对象：

```text
A9 = VPN 网关 的叙事
VLESS/REALITY 作为金融系统主卖点的文档
Rust 重写 Redis 作为第一主线的文档
Redis 订单薄作为权威撮合的旧描述
CRDT 订单薄双活描述
暗箱 VIP 撤单 / 不透明 Last Look 描述
6个月回本 / 100倍 PE / 影子银行 算力币叙事
根目录临时 scratch 文档
重复讨论稿、宣传稿、未定案草稿
```

算力币 / DePIN / compute RWA 可以保留为长期候选，但不能当作当前弹性算力技术选型。你的文档也明确指出，“6 个月回本”“100 倍 PE”“首月收回 10 年租金”不能作为 A9 架构假设，并且算力币公开发售、质押借贷、手续费回购都可能触发证券、衍生品、借贷、托管、市场运营和 AML/KYC/KYT 问题。

## 5. 第一优先级

我建议优先级这样排：

```text
P0：Architecture Decision Packet
P1：Reference Baseline Scan + Vendor Manifest
P2：A9 Core Contract
P3：Gateway / Bus 重构
P4：AgentOS Runtime
P5：Mobile / Remote Control Packet
P6：Compute Stage A
P7：NZX 技术 MVP
```

这和你聚合稿里“第一刀不是哪个功能更酷，而是哪一刀最能降低后续返工和跑偏”的判断一致。文档里列出的第一刀候选也是 architecture_decision_packet、reference_baseline_scan、compute_scheduler_research、mobile_control_product_packet、compute_rwa_candidate_review 和 noise_cleanup_plan。

## 6. 最重要的架构边界

最终要硬性写进 ADR：

```text
AI/Agent 不进入交易撮合热路径。
Redis 不做交易权威账本。
barter-rs 不做 CLOB 撮合内核。
NZX 是第一业务应用，不是 A9 底座本身。
Mobile 是控制面入口，不是状态权威源。
算力层旁路服务 AgentOS，不影响交易热路径。
直接 copy 源码前必须有 vendor manifest。
```

NZX 业务仍按之前定案走：NZX 真实资产托管、Appchain 链上资金与 RWA 结算、Rust CLOB 二级市场撮合、做市商动态报价与异步券商对冲、KYC/KYT、多 vault、语义化 WAL、Databend 审计、Pingora 网关和单主撮合热备。

接下来真正该交给 24h worker 的第一刀不是写 NZX 业务代码，而是：

```text
execution_next_0001_architecture_packet
execution_next_0002_vendor_baseline_scan
execution_next_0003_workspace_skeleton
execution_next_0004_core_types
execution_next_0005_gateway_v1
```

这五步跑通，A9 才从“实验产品”变成真正能长期承载金融交易、AI Agent、远程控制和弹性算力的基座。

[1]: https://github.com/deepcooker/a9 "GitHub - deepcooker/a9 · GitHub"
[2]: https://raw.githubusercontent.com/deepcooker/a9/main/Cargo.toml "raw.githubusercontent.com"
