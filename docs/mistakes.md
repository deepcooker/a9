# A9 错题本

这里记录已经犯过、以后必须改变行为的问题。

## 2026-05-21：不要把执行机器任务误说成量化业务任务

错误：

- 把最后一个 workflow item 写成了 `quant_workflow_templates`。

纠正：

- 当前里程碑是 24 小时执行机器。
- 正确项是 `copy_pipeline_templates`。
- 量化/金融是未来业务域，不应该驱动当前基础设施 MVP。

## 2026-05-21：不要让 worker 一直读文件

错误：

- 真实 worker 做 `a9-client` 任务时，花太多时间读 broad context。

纠正：

- 监控者停掉了它。
- 保留有价值 patch。
- 监控者把默认 phase 改成 `reference_scan`，补文档/测试，只提交合格部分。

规则：

- worker 跑偏就停。
- 好的半成品留下，弱的部分拒收或修掉。
- 把教训写回 prompt/docs，减少下次同类跑偏。

## 2026-05-21：页面监控不是主架构

错误：

- 早期讨论中过度重视监控聊天页面作为 24h 运行方式。

纠正：

- 页面/TUI 监控只是桥接或兜底。
- 核心架构是 supervisor queue、worktree execution、evidence、checkpoint/memory、auto-next。
