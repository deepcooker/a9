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
- `原始想法需求.md`: A9 原始哲学、产品脉络和需求源头。
- `docs/project.md`: 项目状态和分层目标。
- `docs/requirements-review-closure.md`: 评审博弈什么时候算完成，以及何时允许进入 `execution_next`。
- `docs/role-memory-governance.md`: 主控窗口和各角色如何读取/接收精读记忆。
- `docs/worker-method-packet.md`: analysis worker / execution worker 共用方法包，规定定案前博弈、定案后执行。
- `docs/reference-adoption-decision.md`: 多轮博弈后的参考机制取舍，哪些现在进、哪些暂缓。
- `docs/collaboration.md`: 人类/监控者与 24 小时机器的协作方式。
- `docs/communication-governance-framework.md`: 通讯治理 active index。
- `docs/communication-runtime-decision-packet.md`: 通讯运行时 active decision index。
- `docs/communication-runtime-data-contract-v1.md`: 通讯运行时 active data-contract index。
- `docs/communication-runtime-model-closure.md`: 运营闭包 active model index。

## Evidence

证据文档不是默认 prompt。只有任务包点名路径和 slice 时才读。

- `docs/session-raw-summary.md`: raw session active summary；全文归档在
  `docs/archive/evidence/session-raw-summary-full-20260613.md`。
- `docs/session-raw-close-reading.md`: raw session 精读 active 索引；全文归档在
  `docs/archive/evidence/session-raw-close-reading-full-20260613.md`。
- `docs/agent-runtime-observations.md`: archived evidence pointer.
- `docs/communication-observation-log.md`: archived evidence pointer.
- `docs/copied-mechanisms.md`: 已抄机制 active 索引；全文归档在
  `docs/archive/evidence/copied-mechanisms-full-20260613.md`。
- `docs/reference-selection-reassessment.md`: 参考项目 active index。
- `docs/mistakes.md`: 错题本 active 索引；全文归档在
  `docs/archive/evidence/mistakes-full-20260613.md`。

## Supporting

- `docs/production-daemon.md`: 服务化和运行方式。
- `docs/patch-diff-discipline.md`: patch / SEARCH-REPLACE / guard 纪律。
- `docs/vendor-strategy.md`: license 和 vendor 规则。
- `docs/requirements-guide-close-reading.md`: 需求方法论 active checklist。
- `docs/moe-review-methodology.md`: MoE/requirements-review active index。

## Archive

阶段性研究、旧评审、旧任务模板和非当前主线文档放在：

- `docs/archive/2026-06-history/`
- `docs/archive/2026-06-noise-reduction/`
- `docs/archive/2026-06-execution-results/`
- `docs/archive/evidence/`

worker 默认不得读取 archive。只有任务包明确点名某个归档文件和 bounded slice 时，
才允许把它作为历史证据。
