# A9 错题本

## 2026-05-27：通讯观察中不要机械相信 auto-next 阶段

现象：

- worker 的 `next_slice` 明确要求 `test:`，但 auto-next 仍按固定
  `record -> reference_scan -> mechanism_extract...` 继续排队。
- 这会让通信治理任务绕回泛扫描，浪费 token，也可能稀释已经明确的测试目标。

修正：

- 监控者需要检查 queued task 是否匹配 worker `next_slice`。
- 对通讯线，已有明确 test/implement slice 时，应强制改队列阶段并收缩 checks。
- 后续 supervisor 应支持从 `next_slice` 的 `test:` / `implement:` /
  `repair:` 前缀推导下一阶段，但必须保留 allowed_paths 和 policy guard。

补充：

- `auto-test-auto-implement-supervisor-flow-sequen-0be8c09108-20260526T173025Z`
  后再次复现：worker 要求 `test:`，auto-next 排成 `reference_scan`。
- 监控者已把队列任务改回 `phase: test`，并收窄到 supervisor/middleware 检查。

## 2026-05-27：deep mark 不应该阻塞 run-one 完成

现象：

- supervisor worker、guard、check、git commit 已完成后，`run-one` 卡在大量
  `docker exec a9-redis redis-cli JSON.SET a9:deep_mark...` 写入上。
- 本次最终完成，但暴露出 per-record docker exec 写 RedisJSON 是阻塞热路径。

修正：

- deep mark 持久化要批量写，或转成异步/后台补写。
- `run-one` 完成路径只应该同步写最小 checkpoint、summary、evidence pointer。
- 多小时无人值守前，必须修这个慢路径，否则长任务会被持久化噪音拖住。

## 2026-05-27：测试切片不要习惯性读 raw session 文档

现象：

- `repair/test` 任务只需要补 supervisor 负向单测，但 worker 先读
  `docs/session-raw-summary.md` 和 `docs/session-raw-close-reading.md` 的大段尾部。
- 输出事件超过 `120000` bytes，触发 `retryable-worker-budget`，最终 envelope 缺失。

修正：

- 代码/测试修复任务默认不读 raw session 文档。
- 只有 session 精读任务才读 raw session 文档，而且必须按 turn/行号小批次读取。
- 监控者应在 repair task 里显式禁止 raw docs、service ps、reference scan，除非任务目标就是这些内容。

## 2026-05-27：Spark 小模型会做对 patch 但写错 strict envelope

现象：

- `gpt-5.3-codex-spark` 在硬边界 repair/test 任务中补出了正确负向测试。
- 但是 final JSON 写成 `status: "pass"`，不是允许的 `ok|needs_approval|cancelled`。
- supervisor 正确判定 `worker_envelope=fail`，并按治理规则 rollback 了 diff。

修正：

- Spark 可以用于低风险小 patch 试跑，但严格协议任务不能直接信任。
- 后续可以抄 OpenClaw/Lobster 的 tool-envelope normalization：在安全条件下把
  `pass/success` 归一到 `ok`，否则自动排 envelope-repair，不浪费已通过测试的 patch。
- 当前由监控者手工接管：只接受已通过 guard/check 的最小 patch。

进展：

- `implement-worker-envelope-normalization-20260526T175650Z` 已实现受限归一化：
  `ok=true` 且 `status in {pass, success}` 时归一为 `ok`，并记录 info finding。
- 非法状态仍失败，`needs_approval/cancelled` 语义不变。

## 2026-05-27：worker worktree 看不到参考项目路径

现象：

- 任务指定读取 `reference-projects/openhands/frontend/src/types/v1/type-guards.ts`。
- worker 在隔离 worktree 中读不到该路径，`sed` 报 `No such file or directory`。

修正：

- supervisor 不能只在 prompt 里给参考路径；需要 hydrate reference slice，或传入
  主仓绝对路径并允许只读访问。
- 后续 reference_scan 产物要落成可被 worker worktree 读取的 evidence/slice，而不是只靠文字路径。

## 2026-05-27：不要在普通队列上并发跑同一类 worker

现象：

- Codex/参考项目支持多 thread/subagent，但 A9 当前普通 copy pipeline 还没有
  对每个任务强制 Redis `flow_id + expected_revision`。
- 如果同时启动多个 `run-one`，可能出现两个 worker 读同一队列或同一方向，
  造成重复推进、上下文交叉、record 覆盖和 token 浪费。

修正：

- 当前默认单 active worker。
- 只有任务具备独立 flow、expected revision、独立 write scope 时才允许并发。
- 并发治理要先抄 Codex thread/session 边界和 OpenClaw/Lobster flow revision。

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

## 2026-05-22：真实 Codex worker 需要可写运行时 home

错误：

- 受控实跑 `auto-mechanism_extract...` 时，worker 在初始化 Codex app-server
  client 阶段失败。
- 失败信息是 `failed to initialize in-process app-server client: Read-only file system`。

纠正：

- supervisor 默认给真实 worker 注入 `.a9/codex-home` 和 `.a9/tmp`。
- worker 命令使用 `CODEX_HOME=.a9/codex-home`、`HOME=.a9/codex-home`、
  `TMPDIR=.a9/tmp` 和 `codex exec --json --ephemeral`。
- 后续真实 smoke `worker-startup-smoke` 已能启动并输出最终消息。

规则：

- 真实 worker 不能继承只读 `/root/.codex` 作为运行时 home。
- 即使是 smoke prompt，worker 仍可能主动读测试或运行命令；长跑前还需要更硬的
  任务边界和工具预算治理。

## 2026-05-22：真实 worker 会把 smoke 扩成探索任务

错误：

- `worker-startup-smoke` 明确要求不改文件、只输出固定答案，但真实 worker 仍读取测试、
  运行命令并扩大了探索范围。

纠正：

- supervisor 增加 worker event/byte budget。
- 命令事件中出现嵌套 `codex exec`、`a9_supervisor.py run-one` 或
  `a9_supervisor.py run-loop` 会被拦截。
- 预算触发时记录 `budget_stopped`、`budget_reason`、`event_count` 和
  `event_bytes`，状态为 `retryable-worker-budget`。

规则：

- 真实长跑前必须用低预算 smoke 验证 worker 是否服从边界。
- prompt 约束不够，必须有运行时预算和命令 gate。

## 2026-05-22：不要把 Aider 当成 OpenClaw/Lobster

错误：

- 早期把“龙虾”参考线混到 Aider 上。

纠正：

- Aider 是 edit/repo-map/SEARCH-REPLACE/diff repair 参考。
- OpenClaw/Lobster 才是 24h runtime、managed flow、approval/resume、policy
  attestation、extension/plugin 和 memory governance 主参考。
- 完整 OpenClaw 已下载到 `reference-projects/openclaw`，MIT license。

规则：

- 讨论 runtime/workflow/approval/policy 时先看 OpenClaw/Lobster。
- 讨论 repo map/edit block/patch repair 时先看 Aider。

## 2026-05-22：旧总结不能替代 raw session

错误：

- 上下文压缩和旧总结会混淆阶段、进度和参考优先级。

纠正：

- 原始 session 文件是事实源。
- `docs/session-raw-close-reading.md` 保存 turn、行号、原始意思、执行细节和变迁原因。
- `docs/session-raw-summary.md` 保存滚动结论。

规则：

- 更新主线前先看 raw 精读和定位索引。
- 旧 `docs/session-close-reading.md` / `docs/session-summary.md` 已删除。需要历史时
  回到 raw session 和 `docs/session-raw-*`。

## 2026-05-22：不要把外部 Codex session 和 A9 runtime session 混在一起

错误：

- 把“精读 Codex 当前窗口 session”和“24 小时机器自己运行产生的 session”都叫
  session，容易误以为它们应该进同一个 mem0 记忆库。

纠正：

- 外部 Codex/operator session 是原始对话证据，用于精读、恢复意图、提取 doctrine。
- A9 runtime session 是执行证据，用于 task/flow/run、worker、patch、check、guard、
  retry、approval 治理。
- 两者通过 evidence/task/flow 引用关联，不混存。

规则：

- raw Codex JSONL 存文件/MySQL canonical index，Redis 只做热索引。
- A9 runtime session 存 `.a9/runs`、MySQL、Redis hot path。
- mem0 只存抽取后的长期记忆，必须带 evidence 引用。

## 2026-05-26：strict worker envelope 不是自由文本协议

错误：

- `comm-governance-slice1-repair-20260526T091313Z` 的代码 patch、scope guard 和
  `cargo test -p a9-gateway` 都通过了，但 worker final 写成
  `protocolVersion: "openclaw-lobster-worker-envelope-v1"`、`status: "pass"`。
- supervisor 要求 `protocolVersion` 必须是 `1`，`status` 必须是 `ok`、
  `needs_approval` 或 `cancelled`，因此正确回滚了 patch。

纠正：

- 监控者接管并只保留通过测试、通过 scope guard 的有效 patch。
- 后续 worker prompt 必须直接给出合法 envelope 示例，不要只说“strict JSON
  envelope”。

规则：

- `strict_worker_envelope: true` 时，合法最小通过格式是：

```json
{"protocolVersion":1,"ok":true,"status":"ok","output":{}}
```

## 2026-05-26：Spark 不能直接当无人值守默认模型

错误：

- `event-replay-gap-20260526T110451Z` 使用 `gpt-5.3-codex-spark` 做 auto-next
  worker 时，任务还没进入代码阶段就失败。
- 失败信息是 `Tool 'image_generation' is not supported with
  gpt-5.3-codex-spark-1p-codexswic-ev3.`。

纠正：

- 无人值守默认 worker 回到稳定 `gpt-5.3-codex`。
- Spark 只作为低成本候选模型或受控 smoke 使用，除非 supervisor 能显式约束
  Codex exec 注入的 toolset。

规则：

- 24h loop 的默认模型优先稳定和工具兼容，不优先省 token。
- 模型/tool 兼容失败不算业务任务失败，修完默认配置后要重置 auto-loop guard，再继续跑。
