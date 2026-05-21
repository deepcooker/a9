# A9 项目说明

## 背景

A9 要先做的不是金融量化模型本身，而是一个私有的 24 小时执行机器。

这个机器对标 Codex CLI、Claude Code、Aider、Cline、OpenHands、SWE-agent、aichat 等成熟系统。核心不是“问一句答一句”，而是持续完成：

```text
看成熟项目 -> 抄机制 -> 魔改实现 -> 跑测试 -> 记录证据 -> 继续下一步
```

后面可以把它用于量化/金融研究，但当前阶段先把 agent 基建做扎实。没有稳定执行机器，后续业务模型、交易研究、训练数据闭环都没有可靠来源。

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

## 已做背调和分析

已经分析和复制过这些机制：

- Codex：上下文历史、压缩、结构化事件、本地 agent loop。
- Aider：repo map、最近上下文保真、edit/diff 纪律。
- LangGraph：checkpoint、parent lineage、channel history、copy-session。
- mem0：memory add/search/get/history 形状。
- Cline / OpenHands / Continue / Roo / SWE-agent / aichat / opencode：浏览器/TUI 边界、终端客户端、队列 harness、产品行为。

可复制的源码切片放在 `vendor-src/`，并记录 manifest/license。大型参考仓库可以留在本地，但不能直接变成 prompt 的原始上下文。

## 当前架构

已实现：

- `scripts/a9_supervisor.py`：队列、run-loop、auto-next、worktree、检查、状态分类、证据/状态写入、prompt budget、repo map、event summary、context pressure、patch/scope guard、git governance。
- `scripts/a9_checkpoint.py`：checkpoint lineage、channel history、copy-session。
- `scripts/a9_memory.py`：mem0 形状的 memory adapter。
- `scripts/a9_page_monitor.py`：页面/TUI idle monitor，只做兜底交接。
- `scripts/a9_soak.py`：fake worker 的无人值守 soak 测试。
- `scripts/a9_service.py` 和 `infra/systemd/a9-supervisor.service`：服务化。
- `crates/a9-gateway`：Redis Streams submit/lease/ack/fail/heartbeat/status。
- `crates/a9-worker`：Rust worker wrapper。
- `crates/a9-client`：第一个 Rust 客户端入口，支持 init/config/submit/status/resume。

运行时状态：

- `.a9/tasks/queue`
- `.a9/tasks/running`
- `.a9/tasks/done`
- `.a9/runs`
- `.a9/progress.json`
- `.a9/daemon_heartbeat.json`
- `.a9/client/sessions`
- `.a9/soak/latest.json`

## 当前进度

24 小时自动化 MVP 闭环已经完成：

- capability progress: `100.0%`
- queue execution 可用
- auto-next copy pipeline 可用
- soak test 可用
- Rust client front door 已有
- accepted worker diff 会在隔离 worktree 里原子 commit
- failed/repair worker diff 会先留证据再 rollback 到 base
- worker 可只输出 `SEARCH/REPLACE`，由 supervisor deterministic apply 后
  再进入 guard、test、git governance
- 当前测试/build 通过

关键提交：

- `e58d069 add copy pipeline templates`
- `e3c0fa0 add unattended soak runner`
- `f9ce8fe add a9 client front door`

## 还要做什么

MVP 完成不代表生产级完成。下一步应该做：

- 强化 `a9-client` 的 UX 和安装方式。
- 做更安全的真实 worker 长跑监控。
- 自动识别 token/log 爆炸并停机纠偏。
- 抄 Aider 更强的 diff/patch apply/search-replace 规则。
- 补 stale worktree 清理、主线合并策略、失败 patch 自动 repair 应用。
- 做 provider/model routing。
- 把 Redis/MySQL 状态机更多迁到 Rust。
- 做更长时间的 soak 和失败修复循环。
- 区分核心文档和运行时文档，避免文档膨胀。

业务领域模板，比如量化/金融，等执行机器稳定后再做。
