# A9 Docs Index

只从这里进入文档，避免被旧草稿带偏。

默认入口现在只有三份：

1. `AGENTS.md`
2. `docs/context-governance.md`
3. `docs/project.md`

worker 不能把 `docs/` 下所有 markdown 都当主线读。大日志、raw session、研究草稿、
归档原始想法只能按任务包指定的 bounded slice 读取。

## Core

- `AGENTS.md`: 执行机器规则和当前主线。
- `docs/context-governance.md`: 文档分层、噪音清理、worker 读上下文纪律。
- `原始想法需求.md`: A9 原始哲学、产品脉络和需求源头。
- `docs/project.md`: 项目状态和分层目标。
- `docs/stage-handoff-2026-06-01.md`: 当前通讯/control 阶段收口和下一轮 session 精读任务包。
- `docs/role-memory-governance.md`: 主控窗口和各角色如何读取/接收精读记忆。
- `docs/role-memory-reference-scan.md`: 角色记忆/旁路治理的参考项目证据和临时决策边界。
- `docs/requirements-plan-file-reference-scan.md`: 需求分析方法论与 plan-file agent 工作流参考扫描。
- `docs/worker-method-packet.md`: analysis worker / execution worker 共用方法包，规定定案前博弈、定案后执行。
- `docs/memory-graph-wiki-reference-scan.md`: GBrain/GraphRAG/Graphify/LLM-Wiki 长期记忆和图谱参考扫描。
- `docs/reference-adoption-decision.md`: 多轮博弈后的参考机制取舍，哪些现在进、哪些暂缓。
- `docs/collaboration.md`: 人类/监控者与 24 小时机器的协作方式。
- `docs/communication-governance-framework.md`: 当前主线，通讯治理架构。
- `docs/communication-runtime-decision-packet.md`: 通讯运行时当前决策包，规定先做数据/状态模型校验，再允许实现。
- `docs/communication-runtime-role-review.md`: 通讯运行时第二轮角色评审，批准先做 data contract v1，不准直接做 SSH/tmux 功能。
- `docs/communication-runtime-data-contract-v1.md`: 通讯运行时对象、状态、Redis/MySQL/evidence 合同，后续实现必须对齐。
- `docs/communication-runtime-readiness-review.md`: 通讯运行时对象级就绪评审，按 data-first 维度给出下一对象实现优先级。
- `docs/communication-runtime-model-closure.md`: 运营闭包切片（`operator_session`、`event_cursor`、`reconnect_state`）的对象字段、状态、异常门控、持久化键与执行建议。
- `docs/runtime-auto-next-review.md`: auto-next 治理评审，规定 phase-prefixed 才能自动续跑。
- `docs/communication-governance-worker-task.md`: 下一刀 worker 任务模板。

## Evidence

证据文档不是默认 prompt。只有任务包点名路径和 slice 时才读。

- `docs/session-raw-summary.md`: raw session 滚动总结。
- `docs/session-raw-close-reading.md`: raw session 精读索引，含 turn/line。
- `docs/copied-mechanisms.md`: 已抄机制、来源、commit、license。
- `docs/reference-selection-reassessment.md`: 参考项目优先级重排。
- `docs/mistakes.md`: 错题本。

## Supporting

- `docs/production-daemon.md`: 服务化和运行方式。
- `docs/patch-diff-discipline.md`: patch / SEARCH-REPLACE / guard 纪律。
- `docs/vendor-strategy.md`: license 和 vendor 规则。
- `docs/agent-governance-research.md`: agent 治理研究决策。
- `docs/private-model-strategy.md`: 私有模型方向，当前不是第一执行主线。
