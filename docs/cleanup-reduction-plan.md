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
已移动的文件在后面的记录中列出；未移动的候选继续保留原路径直到代码/测试硬引用解除。

- `docs/a9-current-role-review.md`
- `docs/communication-runtime-*.md`
- `docs/stage-handoff-2026-06-01.md`
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

## 运行态归档工具

新增脚本：

```bash
python3 scripts/a9_runtime_archive.py --limit 20
```

默认行为是 dry-run，只输出归档计划，不改文件。默认保留：

- 最近 50 个 `.a9/runs/*`
- 最近 20 个 `.a9/worktrees/*`
- 每类最近 100 个 `.a9/tasks/done|blocked|interrupted` 文件

真实执行必须显式加：

```bash
python3 scripts/a9_runtime_archive.py --apply --limit 20
```

执行规则：

- `runs` 和历史 `tasks` 使用 move，目标是 `.a9/archive/<kind>/<YYYYMMDD>/`。
- `queue` 和 `running` 永远不进入候选。
- Git 注册 worktree 不用 `mv`，只输出/执行 `git worktree remove --force`。
- plain worktree 目录才按 archive move 处理。
- Git 注册但 `.git` 元数据缺失/损坏，或 `git status` 显示 dirty 的 worktree，
  只记录 `skip_reason`，不移动、不强删。
- 单个 `git worktree remove` 失败只记录 stderr 并继续批次，不能中断整个减负流程。
- Git status/remove 都有运行态清理专用短超时；超时记为 skip，不阻断控制面。
- worktree-only 且设置 `--limit` 时，默认只扫描足量候选，不全量扫所有历史 worktree。
- `--write-report <path>` 可把本次 dry-run/apply 计划写成 JSON 证据报告。
- apply 前必须先 dry-run 并检查候选，尤其是 worktree。

## 第一批动作

1. `.gitignore` 忽略 `a3b_moe_cognition/` 和 `model-lab/`。
2. 建立本台账。
3. 建立 `docs/archive/2026-06-history/`，第一批归档阶段性文档。
4. 写 deterministic runtime archive 脚本，先 dry-run，再执行。

## 第一批已归档

移动到 `docs/archive/2026-06-history/`：

- `docs/archive/2026-06-history/communication-runtime-bootstrap-execute-boundary.md`
- `docs/archive/2026-06-history/communication-runtime-bootstrap-reference-scan.md`
- `docs/archive/2026-06-history/communication-runtime-live-smoke.md`
- `docs/archive/2026-06-history/communication-runtime-readiness-review.md`
- `docs/archive/2026-06-history/communication-runtime-role-review.md`
- `docs/archive/2026-06-history/communication-governance-worker-task.md`
- `docs/archive/2026-06-history/mobile-control-source.md`
- `docs/archive/2026-06-history/private-model-strategy.md`
- `docs/archive/2026-06-history/agent-governance-research.md`

暂不移动：

- `docs/communication-runtime-data-contract-v1.md`：`scripts/a9_control_api.py`
  仍作为 evidence 字符串引用。
- `docs/communication-runtime-model-closure.md`：`scripts/a9_control_api.py`
  仍作为 evidence 字符串引用。
- `docs/communication-runtime-decision-packet.md`：`tests/test_supervisor.py`
  仍有任务/allowed_paths 检查引用。
- `docs/agent-runtime-observations.md`、`docs/context-governance.md`、
  `docs/stage-handoff-2026-06-01.md`：代码/测试/AGENTS 仍硬引用。

## 第二批已完成

- 新增 `scripts/a9_runtime_archive.py`。
- 新增 `tests/test_runtime_archive.py`。
- dry-run 验证：当前约 5033 个运行态归档候选。
- 已执行第一批低风险 apply：

```bash
python3 scripts/a9_runtime_archive.py --apply \
  --include-runs --no-include-worktrees --no-include-tasks --limit 50
```

结果：

- `.a9/runs` 从 2339 降到 2289。
- 50 个最旧 run 移动到 `.a9/archive/runs/20260521/`。
- 未触碰 `.a9/tasks/queue`、`.a9/tasks/running`、`.a9/worktrees`。
- 执行后 `python3 scripts/a9_supervisor.py status` 正常，daemon `stale=false`。

## 第三批已完成

继续只处理低风险运行态，不触碰 Git worktree：

```bash
python3 scripts/a9_runtime_archive.py --apply \
  --include-runs --no-include-worktrees --no-include-tasks --limit 200

python3 scripts/a9_runtime_archive.py --apply \
  --no-include-runs --no-include-worktrees --include-tasks --limit 100
```

结果：

- `.a9/runs` 从 2289 降到 2089。
- `.a9/archive/runs` 累计 250 个 run。
- `.a9/tasks` 文件从 2243 降到 2143。
- `.a9/archive/tasks` 累计 100 个 task 文件。
- `.a9/tasks/queue` 和 `.a9/tasks/running` 仍为空。
- 未触碰 `.a9/worktrees`。
- 执行后 `python3 scripts/a9_supervisor.py status` 正常，daemon `stale=false`。

## 第四批已完成

开始处理 `.a9/worktrees` 前，先补强归档工具：

- dirty registered worktree 跳过并记录 `skip_reason=dirty_worktree`。
- Git 注册但 `.git` metadata 缺失/损坏的 worktree 跳过并记录
  `missing_git_metadata` / `invalid_git_metadata`。
- `git worktree remove --force` 单项失败不再中断整批清理。
- Git status/remove 都有运行态清理专用短超时；超时记为 skip，不阻断控制面。
- 单测覆盖上述场景。

执行：

```bash
python3 scripts/a9_runtime_archive.py \
  --no-include-runs --include-worktrees --no-include-tasks --limit 30

python3 scripts/a9_runtime_archive.py --apply \
  --no-include-runs --include-worktrees --no-include-tasks --limit 30

python3 scripts/a9_runtime_archive.py --apply \
  --no-include-runs --include-worktrees --no-include-tasks --limit 20
```

结果：

- `.a9/worktrees` 从 689 降到 663。
- `.a9/archive/worktrees` 新增 13 个 plain worktree 归档。
- 12 个 dirty/invalid registered worktree 被跳过，没有强删。
- 第二个小批次移除 8 个干净 registered worktree。
- `.a9/tasks/queue` 和 `.a9/tasks/running` 仍为空。
- 后台 `supervisor`、`control-api`、`node-worker`、`recovery-loop` 仍在运行。

## 第五批已完成

修复第四批暴露的性能问题：worktree 清理不再默认全量扫描 600+ 历史目录。

实现：

- `worktree_candidates(..., scan_limit=N)` 支持扫描到足量候选即停。
- worktree-only 且带 `--limit` 时，自动使用 `limit` 作为 `worktree_scan_limit`。
- 输出 `scan_truncated: worktree_scan_limit=N`，明确本次不是全量盘点。
- 新增 `--worktree-scan-limit`，需要人工指定扫描窗口时可覆盖默认值。
- 新增 `--write-report`，把计划/执行候选写到 `.a9/archive/reports/*.json`。
- 单测覆盖分页扫描和 auto scan limit。

执行：

```bash
python3 scripts/a9_runtime_archive.py \
  --no-include-runs --include-worktrees --no-include-tasks --limit 20

python3 scripts/a9_runtime_archive.py --apply \
  --no-include-runs --include-worktrees --no-include-tasks --limit 20 \
  --write-report .a9/archive/reports/runtime-archive-worktree-20260612T151558Z.json
```

结果：

- dry-run/apply 都只扫描 20 个候选，不再计算全量 `candidate_count=651`。
- `.a9/worktrees` 从 663 降到 655。
- 本批移除 8 个干净 registered worktree。
- 12 个 dirty/invalid registered worktree 继续跳过。
- `.a9/tasks/queue` 和 `.a9/tasks/running` 仍为空。
- 后台 `supervisor`、`control-api`、`node-worker`、`recovery-loop` 仍在运行。

## 第六批已完成

开始做文档大手术，目标是降低 worker 和新主控窗口的上下文噪音。

归档规则：

- 当前事实入口继续保留在 `AGENTS.md`、`docs/context-governance.md`、
  `docs/project.md`、`docs/requirements-review-closure.md`。
- 阶段性 review/closure/reference-scan 不再留在 `docs/` 顶层。
- execution result 不再堆在 `docs/execution_next/`；该目录只保留活跃任务包。
- 大 observation log 保留为 evidence，但从热路径移走；旧路径只保留小路标，
  兼容代码/测试硬引用。

移动到 `docs/archive/2026-06-noise-reduction/`：

- `a9-24h-two-lane-review-closure.md`
- `a9-current-decision-packet.md`
- `a9-current-review-packet.md`
- `a9-runtime-review-closure-2026-06-03.md`
- `a9-worker-cost-discipline-closure-2026-06-03.md`
- `runtime-auto-next-review.md`
- `runtime-governance-review-2026-05-29.md`
- `memory-graph-wiki-reference-scan.md`
- `role-memory-reference-scan.md`
- `requirements-plan-file-reference-scan.md`

移动到 `docs/archive/2026-06-execution-results/`：

- `docs/archive/2026-06-execution-results/0001-runtime-monitor-contract-result.md`
- `docs/archive/2026-06-execution-results/0002-monitor-visibility-status-result.md`
- `docs/archive/2026-06-execution-results/0003-monitor-intervention-command-contract-result.md`
- `docs/archive/2026-06-execution-results/0004-monitor-intervention-effect-routing-result.md`
- `docs/archive/2026-06-execution-results/0005-supervisor-full-suite-stabilization-result.md`
- `docs/archive/2026-06-execution-results/0006-monitor-approval-and-runtime-status-result.md`
- `docs/archive/2026-06-execution-results/0007-monitor-intervention-operator-surface-result.md`
- `docs/archive/2026-06-execution-results/0008-monitor-intervention-cli-result.md`
- `docs/archive/2026-06-execution-results/0009-monitor-intervention-redis-stream-result.md`
- `docs/archive/2026-06-execution-results/0010-monitor-intervention-stream-replay-result.md`
- `docs/archive/2026-06-execution-results/0011-monitor-control-aggregate-result.md`

移动到 `docs/archive/evidence/`：

- `agent-runtime-observations.md`
- `communication-observation-log.md`

保留小路标：

- `docs/agent-runtime-observations.md`
- `docs/communication-observation-log.md`
- `docs/execution_next/README.md`

同时更新：

- `AGENTS.md`
- `docs/README.md`
- `docs/context-governance.md`
- `docs/project.md`
- `docs/role-memory-governance.md`
- `docs/session-causal-memory.md`

暂不处理：

- `docs/a9-current-role-review.md`：`tests/test_supervisor.py` 有硬引用，下一批要么改测试，
  要么保留路标。
- `docs/stage-handoff-2026-06-01.md`：`AGENTS.md`、`tests/test_supervisor.py` 和
  role-memory 文档仍引用。
- `docs/communication-runtime-*.md`：`scripts/a9_control_api.py` 和测试仍引用。

## 第七批已完成

继续处理剩余大文档，采用“全文归档 + 原路径短索引/热 lane”的方式，避免脚本
硬引用断掉，同时减少默认上下文污染。

归档全文：

- `docs/session-raw-close-reading.md`
  -> `docs/archive/evidence/session-raw-close-reading-full-20260613.md`
- `docs/mistakes.md`
  -> `docs/archive/evidence/mistakes-full-20260613.md`
- `docs/copied-mechanisms.md`
  -> `docs/archive/evidence/copied-mechanisms-full-20260613.md`
- `docs/a9-ultimate-architecture-aggregation.md`
  -> `docs/archive/2026-06-noise-reduction/a9-ultimate-architecture-aggregation.md`

保留原路径短索引：

- `docs/session-raw-close-reading.md`：active close-reading pointer，允许未来
  `session_close_reading` 继续追加小批次；超过 active window 后再轮转。
- `docs/mistakes.md`：active wrongbook lane，兼容测试和 patch/apply 示例。
- `docs/copied-mechanisms.md`：active copied-mechanism/source lane。
- `docs/a9-ultimate-architecture-aggregation.md`：最高形态短索引，全文只作 debate
  evidence。

同时更新：

- `docs/README.md`
- `docs/context-governance.md`
- `docs/project.md`
- `docs/session-causal-memory.md`

结果：

- `docs/session-raw-close-reading.md` 从 9041 行降为 active pointer。
- `docs/mistakes.md` 从 1448 行降为 active pointer。
- `docs/copied-mechanisms.md` 从 701 行降为 active pointer。
- `docs/a9-ultimate-architecture-aggregation.md` 从 838 行降为 active index。

## 第八批已完成

继续收敛剩余主入口大文档，保留路径和写入兼容性，同时把全文移到 archive。

归档全文：

- `docs/session-raw-summary.md`
  -> `docs/archive/evidence/session-raw-summary-full-20260613.md`
- `docs/session-causal-memory.md`
  -> `docs/archive/evidence/session-causal-memory-full-20260613.md`
- `docs/project.md`
  -> `docs/archive/2026-06-noise-reduction/project-full-20260613.md`

保留原路径短索引：

- `docs/session-raw-summary.md`：active rolling summary lane，允许
  `session_close_reading` 追加小摘要；超过 active window 后再轮转。
- `docs/session-causal-memory.md`：active causal-memory index。
- `docs/project.md`：active project current-state index。

结果：

- `docs/session-raw-summary.md` 从 1038 行降为 active summary。
- `docs/session-causal-memory.md` 从 560 行降为 active causal index。
- `docs/project.md` 从 392 行降为 active project index。
