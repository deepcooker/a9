# A9 减负专项台账

## 目标

A9 当前需求边界已经清楚：A9 负责稳定通讯、CLI/control API、网关感知器、
24 小时任务编排、任务上下文环境和证据落盘；A3B / A?B 负责更底层的认知、
元激活和未来训练 trace。

本专项目标不是丢失历史，而是降低主仓噪音，让新窗口、worker 和监控者能快速
找到主线、事实源和可执行入口。

## 不动边界

- `/root/a9/a3b_moe_cognition/`：A3B 底层认知系统，只读参考，除非人类明确授权。
- `/root/a9/model-lab/`：模型/数据集实验目录，不属于 A9 runtime 清理范围。
- `reference-projects/`：本地参考项目，不进 prompt，不在本专项删除；后续只做索引。
- `vendor-src/`：已复制源码切片和 license/source 证据，不能随意删除。
- `.git/`、`target/`、`.a9/runtime/` 当前服务状态文件：不能粗暴删除。

## 主线保留文档

这些文档保留在顶层或核心目录，作为当前事实入口：

- `AGENTS.md`
- `README.md`
- `docs/project.md`
- `docs/current-mainline.md`
- `docs/worker-method-packet.md`
- `docs/requirements-review-closure.md`
- `docs/requirements-guide-close-reading.md`
- `docs/role-memory-governance.md`
- `docs/communication-governance-framework.md`
- `docs/production-daemon.md`
- `docs/mistakes.md`
- `docs/session-causal-memory.md`
- `docs/session-raw-summary.md`
- `docs/session-raw-close-reading.md`
- `docs/reference-adoption-decision.md`
- `docs/reference-selection-reassessment.md`

## 候选归档文档

这些更像阶段产物、历史评审或专项记录。先移动到 `docs/archive/`，不删除。
第一批已经移动的文件在后面的“第一批已归档”记录中列出；未移动的候选继续保留
原路径直到代码/测试硬引用解除。

- `docs/a9-current-decision-packet.md`
- `docs/a9-current-review-packet.md`
- `docs/a9-current-role-review.md`
- `docs/a9-24h-two-lane-review-closure.md`
- `docs/a9-runtime-review-closure-2026-06-03.md`
- `docs/a9-worker-cost-discipline-closure-2026-06-03.md`
- `docs/agent-runtime-observations.md`
- `docs/communication-runtime-*.md`
- `docs/runtime-governance-review-2026-05-29.md`
- `docs/runtime-auto-next-review.md`
- `docs/stage-handoff-2026-06-01.md`
- `docs/memory-graph-wiki-reference-scan.md`
- `docs/role-memory-reference-scan.md`
- `docs/requirements-plan-file-reference-scan.md`
- `docs/patch-diff-discipline.md`
- `docs/context-governance.md`
- `docs/moe-review-methodology.md`
- `docs/vendor-strategy.md`

## 运行态清理候选

当前观测：

- `.a9/runs` 约 2340 个 run 目录。
- `.a9/worktrees` 约 691 个 worktree。
- `.a9/tasks` 约 2243 个任务/租约/历史文件。

清理规则：

- 保留最近 50 个 run 和最近 20 个 worktree，直到实现确定性归档脚本。
- 旧 run 只移动到 `.a9/archive/runs/YYYYMMDD/`，不直接删除。
- 旧 worktree 清理前必须确认不在 `.a9/tasks/running`、不在 `git worktree list` 活跃列表。
- `queue` 和 `running` 永远不批量移动；只能人工确认后处理。
- `blocked`、`done`、`interrupted` 可按日期归档。

## 第一批动作

1. `.gitignore` 忽略 `a3b_moe_cognition/` 和 `model-lab/`。
2. 建立本台账。
3. 建立 `docs/archive/2026-06-history/`，第一批归档阶段性文档。
4. 再写 deterministic runtime archive 脚本，先 dry-run，再执行。

## 第一批已归档

移动到 `docs/archive/2026-06-history/`：

- `docs/communication-runtime-bootstrap-execute-boundary.md`
- `docs/communication-runtime-bootstrap-reference-scan.md`
- `docs/communication-runtime-live-smoke.md`
- `docs/communication-runtime-readiness-review.md`
- `docs/communication-runtime-role-review.md`
- `docs/communication-governance-worker-task.md`
- `docs/mobile-control-source.md`
- `docs/private-model-strategy.md`
- `docs/agent-governance-research.md`

暂不移动：

- `docs/communication-runtime-data-contract-v1.md`：`scripts/a9_control_api.py`
  仍作为 evidence 字符串引用。
- `docs/communication-runtime-model-closure.md`：`scripts/a9_control_api.py`
  仍作为 evidence 字符串引用。
- `docs/communication-runtime-decision-packet.md`：`tests/test_supervisor.py`
  仍有任务/allowed_paths 检查引用。
- `docs/agent-runtime-observations.md`、`docs/context-governance.md`、
  `docs/stage-handoff-2026-06-01.md`：代码/测试/AGENTS 仍硬引用。
