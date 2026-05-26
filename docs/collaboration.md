# A9 协作文档

## 角色分工

我们有两个核心角色。

人类/监控者：

- 负责业务方向。
- 负责架构判断。
- 负责跟模型讨论战略和目标。
- 负责给执行机器下明确任务。
- 负责监控 worker 是否跑偏、烧 token、质量差。
- 负责验收、打回、停机、接手修。

24 小时执行机器：

- 接任务。
- 看参考项目。
- 抄成熟机制。
- 魔改代码。
- 跑测试。
- 记录证据。
- 生成下一步。

执行机器有代码工程能力，因为它是 agent；但它本质上仍是执行机器，不是唯一大脑，不负责最终业务判断。

## 工作方式

标准协作方式：

1. 人类/监控者定义目标。
2. supervisor 入队一个边界清楚的任务。
3. worker 按 copy pipeline 执行。
4. 监控者看 events、diff、测试、token/log 大小和方向。
5. worker 跑偏就停。
6. 好的半成品留下，弱的部分丢掉或修掉。
7. 合格结果提交并推送。
8. 教训写入错题本。

关系是：

```text
人类/监控者 = 大脑 + 架构/产品判断 + 验收门
24h worker = 执行引擎
```

## Mobile Control Plane

手机端不是只做审批入口，而是 A9 的轻量控制面。

它应该能做：

- 承接当前人类和主监控 Codex 的对话，不让主控只能绑在电脑窗口里。
- 看 operator session tail、raw session 索引、close-reading 摘要和最近决策。
- 看 queue/running/done。
- 看 flow revision、run summary、event tail、stderr、checks、diff。
- 看 token usage、budget stop、policy attestation、worker failure 分类。
- 下发 submit、pause、resume、stop、retry、approve、reject、continue。
- 触发 `session_refresh`、`session_close_reading`、compact、handoff、生成下一任务。
- 接收需要人类处理的 inbox，但不把 inbox 当唯一入口。

它不应该做：

- 在手机上承载完整 IDE。
- 直接把 raw Codex TUI 当唯一状态源。
- 绕过 Redis/MySQL/supervisor 直接改任务状态。
- 把 mobile 简化成 `needs-approval` 的按钮页。
- 只监控 worker，却不接入主监控/operator conversation。

早期可以用 `Tailscale + SSH + tmux` 连接服务器查看 Codex CLI 或 A9
运行状态，但这只是远程兜底。最终产品应该走 A9 自己的 control API：
所有状态来自 Redis flow、MySQL checkpoint、`.a9/runs` evidence 和 git diff，
所有动作变成确定性 command，再由 supervisor 执行。

对你和主监控 Codex 的当前交互，mobile 需要走单独通道：

```text
operator chat / Codex JSONL
  -> session_refresh 抽取 bounded evidence
  -> session_close_reading 写 turn/line/原话预览/决策索引
  -> mobile 显示当前主线、最近决策、下一步候选
  -> 用户在手机继续输入
  -> A9 生成 bounded task 或 continuation prompt
```

这样手机端不是旁路看板，而是把“你和主监控 Codex 的工作入口”也迁过去。
目标是：电脑窗口断开、上下文压缩或人不在机器前时，主控仍能继续。

## 当前边界

当前默认工作只服务于“主监控 + AI 自动化执行机器”基建。

- 不直接做金融策略或量化模型。
- 不把页面/TUI monitor 当主架构；旧 page-monitor 路线不再维护。
- 不把 OpenClaw 的最终产品形态和 A9 当前脚手架混在一起。
- 不把 Aider 当 Lobster/OpenClaw 参考线。

下一层平台产品才是类 Codex CLI + OpenClaw/Lobster 的综合 agent。
金融 Codex 是再下一层垂直化数据和训练项目。

## 什么时候要停 worker

出现这些情况就停：

- 一直读文件，不实现。
- events/log/prompt 增长太快。
- 忘了“先抄成熟项目”。
- 开始做业务发散，而不是当前基础设施任务。
- 改无关文件。
- 测试失败却没有进入修复路径。
- 只输出自信总结，没有 durable artifact。
- 触发 worker event/byte budget。
- 出现网络重连、app-server 初始化失败、Broken pipe 等错误事件连续增长。
- 尝试嵌套启动 `codex exec` 或 `a9_supervisor.py run-loop/run-one`。

停掉不是失败。停掉是控制系统的一部分。

## 验收标准

一个任务合格，至少要满足：

- 范围可控。
- 能说清抄了什么机制，或者说明为什么这次没抄源码。
- 如复制源码，记录 license/source。
- 代码/文档改动符合目标。
- 跑了测试，或者明确说明为什么不能跑。
- 没有 stale queue/running 状态。
- commit 后工作树干净。
- 对 raw session / 大日志的结论必须能回到文件路径、turn 和大概行号。

## A9 Strict Task Template

严格任务提交遵循 OpenClaw/Lobster 风格的 worker envelope 与 policy attestation：

- 任务约定：在 prompt 顶部写 `strict_worker_envelope: true`，并在需要时附带 `flow_id` 与 `flow_expected_revision`，用于受控续航。
- 诊断、smoke、只读验证任务要写 `expected_file_changes: false` 或 `allow_no_diff: true`；
  这种任务在 envelope/check 通过且无 diff 时可以直接判定 `pass`。
- 结束输出必须返回 JSON envelope，不是纯文本；字段包括 `protocolVersion`、`ok`、`status`、`output`、`error`、`requiresApproval`。
- `status=needs_approval` 时必须带 `requiresApproval.type=approval_request`，并提供 `resumeToken` 或 `approvalId`。
- `policy_attestation.json` 只把 policy、workspace、findings 和最终 attestation 的 hash 放进摘要与 flow。
- `attestationHash` 来源于 `ok + policyHash + workspaceHash + findingsHash` 的稳定哈希，作为 evidence/flow 的短引用。

最小成功 envelope：

```json
{
  "protocolVersion": 1,
  "ok": true,
  "status": "ok",
  "output": ["strict task completed"]
}
```

## 事实源顺序

1. 原始文件、运行证据、测试输出、参考项目源码。
2. `docs/session-raw-close-reading.md` 和 `docs/session-raw-summary.md`。
3. `docs/project.md`、`AGENTS.md`、`docs/communication-governance-framework.md`。
4. 旧总结或聊天记忆。

如果 2 和 4 冲突，以 raw 精读为准。

## 怎么用

健康检查：

```bash
scripts/a9_service.py ps
scripts/a9_supervisor.py status
scripts/a9_soak.py run --tasks 1 --fake-worker
```

停止真实后台 worker：

```bash
scripts/a9_service.py stop --dry-run
scripts/a9_service.py stop
```

通过 Rust client 提交任务：

```bash
cargo run -p a9-client -- submit --task-id next-copy-task \
  --phase reference_scan \
  --check "cargo build --workspace" \
  "copy the next mature client/session mechanism into A9"
```

跑一个有边界的 supervisor 任务：

```bash
scripts/a9_supervisor.py run-loop --auto-next --keep-going-on-error --max-tasks 1
```

长时间无人值守要从小开始。先看 soak report、queue/running 状态、测试结果、token/log 大小都正常，再放大运行时间。

## Codex 接手步骤

每次 Codex/监控者接手时，不要只依赖当前聊天压缩后的记忆。

先执行：

```bash
python3 scripts/a9_service.py ps
python3 scripts/a9_supervisor.py status
tail -n 180 docs/session-raw-summary.md
tail -n 220 docs/session-raw-close-reading.md
```

如果发现 raw session 已经落后当前聊天，就先跑外部 session mini-flow：

```bash
python3 scripts/a9_supervisor.py enqueue refresh-current \
  $'source_session_path: /root/.codex/sessions/2026/05/21/rollout-2026-05-21T11-20-49-019e488c-d5f9-7501-835a-bf6e8ff6d8a2.jsonl\nfrom_turn: <start>\nto_turn: <end>\nbatch_size: 1\nauto_continue: true\nauto_close_reading: true\nclose_reading_doc: docs/session-raw-close-reading.md\nsummary_doc: docs/session-raw-summary.md' \
  --phase session_refresh --timeout-seconds 120 --idle-timeout-seconds 120 --max-attempts 1

python3 scripts/a9_supervisor.py run-loop --auto-next --max-tasks 4 --keep-going-on-error
```

使用规则：

- `<start>/<end>` 必须来自 `scripts/a9_session_refresh.py index ...` 的 turn 索引。
- 一批默认 1-10 个 user turn，遇到长输出或压缩风险就缩到 1。
- mini-flow 只治理外部 Codex/operator session，不启动 worker，不烧模型 token。
- 跑完要看 `.a9/tasks/queue`、`.a9/tasks/running`，不能留下半截队列。
- 如果 flow 暴露运行 bug，先修 route/test，再继续项目任务。

根据当前 raw 精读，下一步工程任务是：

1. 错误模式 gate 第一版已落地：`Connection reset by peer`、`Reconnecting...`、
   app-server 初始化失败、Broken pipe、worker budget stop 会分类成
   `retryable-worker-network` / `retryable-worker-startup` /
   `retryable-worker-broken-pipe` / `retryable-worker-budget` 等机器状态。
2. RedisJSON + Redis Functions 的 revisioned transition 第一版已落地：
   `flow-create` 创建 `a9:flow:<id>`，`flow-transition` 必须带
   `--expected-revision`，旧 revision 会被拒绝。
3. Session mini-flow 已开始写入 `a9:flow:<id>`：任务 prompt 可带
   `flow_id` / `flow_expected_revision`，run summary 会记录 `flow_transition`。
   如果 Redis revision transition 失败，auto-next 会被阻断。
4. 普通 copy pipeline 也已开始接入 managed flow：`reference_scan` 等 worker run
   会用 `flow_id` / `flow_expected_revision` 推进 Redis flow，并把下一 revision
   传给 auto-next 任务。
5. OpenClaw/Lobster approval/wait/resume 第一版已落地：
   `flow-wait` 会写入 `approval_request` envelope，`flow-resume` 用
   `approval_id` 或 `resume_token` 恢复，旧 revision 会被拒绝。
6. OpenClaw/Lobster strict worker envelope 第一版已落地：任务 prompt 写
   `strict_worker_envelope: true` 后，worker final 必须带
   `protocolVersion/ok/status/output/error/requiresApproval` JSON envelope。
7. `needs-approval -> Redis flow-wait` 第一版已落地：有 `flow_id` /
   `flow_expected_revision` 的 strict task 会自动停到 Redis `waiting`，后续用
   `flow-resume` 恢复。
8. OpenClaw policy attestation 第一版已落地：summary/evidence/state/Redis session
   payload 会记录 policy/workspace/findings/attestation hash，managed flow 也会带
   attestation hash 短引用。
9. 下一步不是继续堆架构，而是用 strict task 模板跑真实小任务长跑，观察哪里坏。
