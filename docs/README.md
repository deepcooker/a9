# A9 Docs Index

只从这里进入文档，避免被旧草稿带偏。

默认入口只有四份：

1. `AGENTS.md`
2. `docs/context-governance.md`
3. `docs/project.md`
4. `docs/requirements-review-closure.md`

worker 不能把 `docs/` 下所有 markdown 都当主线读。大日志、raw session、研究草稿、
归档原始想法只能按任务包指定的 bounded slice 读取。

## Core

- `AGENTS.md`: 执行机器规则和当前主线。
- `docs/context-governance.md`: 文档分层、噪音清理、worker 读上下文纪律。
- `docs/project.md`: 项目状态和分层目标。
- `docs/requirements-review-closure.md`: 评审博弈什么时候算完成，以及何时允许进入 `execution_next`。
- `docs/worker-method-packet.md`: analysis worker / execution worker 共用方法包，规定定案前博弈、定案后执行。
- `docs/reference-adoption-decision.md`: 多轮博弈后的参考机制取舍，哪些现在进、哪些暂缓。
- `docs/communication-governance-framework.md`: 通讯治理、运行时决策、数据合同和模型闭包。

## Evidence

证据文档不是默认 prompt。只有任务包点名路径和 slice 时才读。

- `docs/session-raw-summary.md`: raw session active summary。
- `docs/session-raw-close-reading.md`: raw session 精读 active 索引。
- `docs/session-causal-memory.md`: 因果变迁和当前决策索引。
- `docs/copied-mechanisms.md`: 已抄机制 active 索引。
- `docs/mistakes.md`: 错题本 active 索引。

## Supporting

- `docs/vendor-strategy.md`: license 和 vendor 规则。
- `原始想法需求.md`: A9 原始哲学、产品脉络和需求源头。

## Deleted Noise

阶段性研究、旧评审、旧任务模板、归档全文和非当前主线文档已经物理删除。
worker 不得假设还有隐藏归档可读。
