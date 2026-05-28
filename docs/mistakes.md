# A9 错题本

## 2026-05-28：固定 120 行 sed gate 过于机械

现象：

- 监控者指出 `sed windows <= 120 lines` 不一定合理。参考扫描和机制抽取
  本来就需要分批读上下文，机械拦 121/151 行会打断有效工作。
- 真正要防的是吞整文件、无原因扩窗、token 爆炸和 worker 失控，而不是固定行数本身。

修正：

- `scripts/a9_supervisor.py` 把 sed 读取治理改成三层：
  soft window 至少 180 行；超过 soft window 时要求 worker 先说明“为什么要分批读”；
  read-heavy 阶段允许更大的 bounded batch；超过 hard window 才 live block。
- post-run process governance 会记录 `batched_read_with_rationale` 或
  `command_window_missing_rationale`，用于观察 worker 质量；只有 error finding
  才把 run 变成 `monitor-blocked`。

产品判断：

- 当前先做限制和观测，不追求一次把阈值调到最优。
- 这符合 A9 的核心：执行机器可以读参考项目，但必须留下原因、边界和证据。

复盘：

- 实测 `refscan-remote-node-watch-loop-20260528` 后确认：质量大于行数。
  220/260 行 bounded read 有说明原因，不应该成为主要阻断。
- 真正的质量问题是：无关 session/service 读取、rg 输出过大、final envelope
  协议错、next_slice 是否可执行。
- monitor 还误把 Barter-rs 的 `strategy/on_disconnect.rs` 路径当成业务漂移；
  这是评审误伤，已把 `strategy` 从单独业务漂移词中移除。
- 后续 `implement-remote-reconnect-decision-contract-20260528` 又暴露：
  `python3 -m unittest tests.test_remote` 和
  `python3 -m unittest tests/test_remote.py` 是同一测试目标，不能因为表现形式
  不同就回滚有效 patch。已把 unittest module/file 形式做等价归一。

## 2026-05-28：重复 fake Redis 夹具会放大 worker 机械修补

现象：

- `test-node-status-followup-integration-20260528` 要补
  `node_status(root).communication_followup` 集成测试。
- worker 正确发现 helper-only 测试不够，也正确发现 fake Redis 缺 `JSON.SET`、
  `XADD`、`TS.ADD` 分支。
- 但测试文件里存在多段相似 `fake_redis`，worker 多次补错位置，最后用
  `perl -0pi` 做机械替换，插入重复分支，导致 trace 变大并触发
  `retryable-worker-budget`。supervisor 回滚该 worker patch。

修正：

- 监控者接管后只保留有效思想：`communication_followup_intent` 聚合同优先级
  node evidence，并用直接写 node registry JSON 的方式测试 `node_status(root)`。
- 集成测试不再通过 `register_node/heartbeat_node` 制造离线状态，因为
  `heartbeat_node` 当前会覆盖 `last_heartbeat_at=now`，不能表达历史离线心跳。
- 主线提交 `295e5c0` 已通过 `python3 -m unittest tests/test_control_api.py`、
  `python3 -m unittest tests/test_node.py` 和 `git diff --check`。

后续规则：

- 对 control API 测试应抽一个小的 fake Redis helper，避免每个测试复制一段
  `fake_redis`。
- worker prompt 里遇到重复测试夹具时，应优先新增/复用 helper，而不是批量文本替换。
- 如果 worker 使用机械 rewrite 命令修测试，应当视为质量风险，由监控者复核后再合入。

## 2026-05-28：targeted rg 不能只写在 prompt 里

现象：

- `refscan-remote-runtime-governance-clean-20260528` 要求 `sed windows <= 120 lines`，
  worker 多次读取 180-240 行窗口。
- supervisor 修复后能把这类 run 标为 `monitor-blocked`，说明过程治理生效。
- 自动生成的 repair 任务又用 `rg ... docs .` 做宽根搜索，输出超过
  `120000` event bytes，触发 `retryable-worker-budget`。

修正：

- `process_governance` 已扩展：当任务要求 `targeted rg` 时，worker 对 `.` 或
  `docs .` 这类宽根运行 `rg` 会记录 `broad_rg_command`。
- 后续 repair 任务不能把大段 `process_governance` findings 原样塞进 prompt；
  应只传失败种类、前几条样例和证据路径。
- 对 Spark 低成本 worker，参考扫描必须更小：先 `rg -n` 定位，再每次
  `sed <= 120`，不要跨 docs/reference 全面扫。

产品判断：

- 这次没有推进功能，但验证了监控岗位的价值：worker 选出的 Barter-rs
  reconnect/backoff 方向可保留为候选，过程违规不能放行到实现。

## 2026-05-27：supervisor pass 不能覆盖 monitor hard gate

现象：

- `test-reconnect-governance-api-handler-20260527T085000Z` 的代码 patch 有价值，
  声明检查 `python3 -m unittest tests/test_control_api.py` 也通过。
- 但 worker 过程里擅自跑了未声明的 `pytest`，并把环境缺 pytest 写成
  `next_slice`。
- 新 `requirements_review_council_v1` 正确给出：
  `hard_gate=fail`, `failed_experts=["test_verifiability_expert"]`,
  `recommended_action=block_and_rewrite_task`。
- supervisor 仍按 `status=pass` 生成了 auto-next reference_scan，说明 auto-next 还没
  把 monitor hard gate 当成阻断条件。

修正：

- 监控者接管：cherry-pick 有价值 patch，废弃错误 auto-next。
- 后续 supervisor 应在 `monitor_score.gates.hard_gate.status == "fail"` 时阻断
  auto-next，或者强制生成 repair/monitor_review 任务。
- worker prompt 已经写“只跑声明检查”，但仍不足；需要执行层把未声明测试当成
  过程违规，不允许用错误 next_slice 污染队列。

产品标准：

- 本次 patch 满足数据第一：新增 `/api/nodes` response schema/state 对 reconnect
  governance 字段的验收。
- 性能第二的边界也正确：使用 in-process API handler test，没有真实网络和服务探测。

后续复现：

- `expose-monitor-score-in-control-api-20260527` 再次出现同类问题：
  patch 有价值，声明检查通过，但 worker 擅自运行未声明 `pytest`。
- 这次 `block auto next on monitor hard gate` 已生效：run pass 后没有继续生成
  auto-next。
- 监控者继续采用同一策略：保留有价值 patch，过程违规不放行成下一任务。

下一步修正：

- worker prompt 里“只跑声明检查”不够，需要 supervisor 在事件层记录
  `undeclared_check` 为过程违规，并在 hard gate fail 时把 run 标为
  `monitor-blocked` 或生成明确 repair task，而不是仅靠人工阅读 monitor_score。

进展：

- `scripts/a9_supervisor.py` 已新增 `process_governance`：
  从 `event_summaries.jsonl` 读取 worker 命令，测试类命令不在 declared checks
  里时标记 `undeclared_check`。
- `decide_status` 已将 `process_governance.status=fail` 转成 `monitor-blocked`。
- 后续这类 run 不会被当作普通 pass 提交/续跑，patch 需要监控者或 repair 任务接管。

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
- `refscan-codex-transport-backpressure-retry-20260527` 再次暴露 Spark 会输出
  `status=reference_scan_complete`；该类“明确阶段完成 + ok=true”的别名已受限归一到
  `ok`，但任意 `done` 仍保持失败，避免放宽协议边界。
- `refscan-codex-transport-backpressure-pass-20260527` 又暴露
  `protocolVersion=openclaw-lobster-worker-envelope/1.0`；该 OpenClaw/Lobster
  风格版本别名已归一为 `1`，仍保留 info finding。

## 2026-05-27：worker worktree 看不到参考项目路径

现象：

- 任务指定读取 `reference-projects/openhands/frontend/src/types/v1/type-guards.ts`。
- worker 在隔离 worktree 中读不到该路径，`sed` 报 `No such file or directory`。

修正：

- supervisor 不能只在 prompt 里给参考路径；需要 hydrate reference slice，或传入
  主仓绝对路径并允许只读访问。
- 后续 reference_scan 产物要落成可被 worker worktree 读取的 evidence/slice，而不是只靠文字路径。

复发：

- `refscan-codex-transport-backpressure-20260527` 指定
  `reference-projects/codex/codex-rs/app-server-transport/src/transport/mod.rs`，
  但该 Codex transport slice 没有被 hydrate 进 worker worktree。
- worker 找不到路径后扩散到 `rg --files reference-projects`、Barter-rs 和
  OpenClaw，最终 `worker event bytes exceeded 120000`。
- 后续 pass 重跑中，worker 不再扩散，但仍违反 `sed windows <= 120 lines`，
  读取 200/240 行窗口；这说明 prompt 约束不足，必须进入 supervisor
  process governance。

修复：

- `worker_reference_slices()` 增加 Codex app-server transport 小切片。
- reference task 必须优先验证 worker worktree 可见的 reference slice；路径不可见
  时先修 hydrate，不让 worker 自行换参考项目。
- process governance 现在会把任务 prompt 中的 `Do not run ls or rg --files`
  和 `sed windows <= N lines` 转成机器检查；违反时进入 `monitor-blocked`，
  不靠人工读日志才发现。

## 2026-05-27：不要把编排级测试目标一次性丢给 worker

现象：

- `auto-test-implement-worker-envelope-normalizati-49e6db0b8c-20260526T181508Z`
  要验证 strict template + approval/wait/resume + normalization + flow revision。
- worker 开始读 `tests/test_supervisor.py` 和 `tests/test_middleware.py` 的大段片段，
  事件输出超过预算，最终 `retryable-worker-budget`，没有 patch 和 final envelope。

修正：

- 编排级测试必须拆成小 harness：一次只验证一个边界，例如
  `needs_approval -> set_managed_flow_wait`。
- 如果目标涉及 `run_one`，prompt 必须给出已有函数名、行号附近和 monkeypatch 策略，
  禁止通读测试文件。
- 更根本的修复是让 auto-next 根据 `next_slice` 生成窄任务，而不是让 worker 自己解释大目标。

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

## 2026-05-27：小任务也会因为宽读爆掉 event budget

错误：

- `auto-test-implement-next-slice-phase-routing-20-9a2b4b7e9f-20260526T182928Z`
  已经被监控者收窄到一个 regression test。
- worker 仍然用多个大范围 `sed` 读取
  `tests/test_supervisor.py` 和 `scripts/a9_supervisor.py`，最终
  `event_bytes=124875`，触发 `retryable-worker-budget`。
- 没有 final、没有 envelope、没有 patch，说明问题不是代码能力，而是上下文读取纪律。

纠正：

- 监控者直接补最小测试，避免 24 小时队列卡在同一类失败。
- 后续 test/repair worker prompt 要给精确 symbol 或行锚，不要只说“bounded”。

规则：

- 小任务必须小上下文：优先 `rg` 精确定位，再读 80 行以内的窗口。
- 如果 worker 两次在同类窄任务上预算失败，监控者接管补丁，并把失败模式写入
  supervisor prompt/任务模板治理。

## 2026-05-27：只归一化 status 不够，protocolVersion 也会漂移

错误：

- `hydrate-barter-reference-slices-20260526T184000Z` 写出有效代码和测试，但
  envelope 用了 `protocolVersion: "1.0"`、`status: "completed"`。
- `implement-node-connection-action-20260526T185100Z` 的 status 被归一化成功，
  但 envelope 用了 `protocolVersion: "a9.strict_worker_envelope.v1"`。
- 两次 patch/scope/check 都可接受，最终都因为 strict envelope 被回滚。

纠正：

- 监控者审 patch 后手工接管应用，避免 24 小时队列反复 repair 同一类非代码问题。
- 下一刀应该修 supervisor envelope 协议治理：要么极强提示只允许数字 `1`，要么
  在 `ok=true` 且字段语义明确时归一化少量 protocolVersion alias 并记录 info。

规则：

- good patch + bad envelope 是治理问题，不是业务失败。
- 同类 envelope 漂移连续出现时，优先修 supervisor 协议治理，再继续堆功能。

结果：

- `implement-envelope-protocol-normalization-20260526T185800Z` 已修复：
  `protocolVersion` 现在允许窄别名并记录 info finding。
- 覆盖了 `1.0`、`a9.strict_worker_envelope.v1`、非法协议仍失败，以及
  protocol/status 双 alias 同时归一化的回归。

仍未解决：

- worker 仍会在 test 任务里先尝试 pytest；当前运行环境没有 pytest。
- worker 仍会习惯性读取 raw session close-reading，即使任务明确禁止。

## 2026-05-27：prompt 纪律有效但不充分

现象：

- `implement-node-heartbeat-action-hotpath-20260526T192600Z` 没有再读 raw
  session，也没有再跑 pytest，说明 auto-next prompt discipline 有效。
- 但 worker 仍然用 `sed -n '1,260p'` 这类较宽窗口。
- final envelope 又写成 `protocolVersion: "openclaw/1"` 和
  `status: "completed"`，有效 patch 被回滚。

纠正：

- 监控者接管了通过测试的 patch。
- 下一步要继续治理两个点：更严格的“小窗口读取”提示/策略，以及是否把
  `openclaw/1`、`completed` 作为 `ok=true` 下的窄 alias 归一化。

## 2026-05-27：reference_scan 不能让 worker 自由抄大项目

错误：

- `auto-reference_scan-auto-test-implement-xinfo-consumers-p-74e5395946-20260526T201722Z`
  进入 reference_scan 后没有产出 final envelope。
- supervisor 在 `event_bytes=1075032` 时触发 `budget_stopped`，状态为
  `retryable-worker-budget`。
- 这不是业务代码失败，而是“让 worker 自由看参考项目”导致输出事件失控。

纠正：

- 监控者先用 `rg` 给出精选锚点，再把任务收窄成单一测试或单一机制抽取。
- reference_scan 阶段必须限制为：最多 3 个文件锚点、最多 1 个机制、只输出
  `next_slice`，不能展开源码和长文档。

规则：

- 通讯治理参考扫描优先由监控者预筛：`barter-rs` reconnect/backoff、
  `a9-gateway` retry lifecycle、Redis Streams pending/lag。
- worker 不再被要求“自由 inspect local reference projects”；要给它明确文件和
  行锚，否则容易重复触发 event budget。

## 2026-05-27：窄任务也会无意义 web_search

错误：

- `implement-tmux-action-contract-20260527T053300Z` 是本地控制 API 小任务，
  不需要联网，也明确禁止 broaden。
- worker 仍然触发了一次 `web_search` 事件。
- 这会浪费 token、引入不受控外部上下文，并污染“参考项目优先看本地证据”的
  执行纪律。

纠正：

- 监控者没有直接放过该行为；先审查 prompt、event summaries、worker envelope、
  patch 和 supervisor checks。
- 合并可用 patch 后，补 supervisor prompt 纪律：
  不允许 web search/browsing，除非任务明确要求 internet research。

规则：

- 小实现任务默认只看本地 repo、任务文件、精选参考切片和测试失败日志。
- 需要联网研究时，任务必须显式写出 research 目标、来源边界和输出预算。

## 2026-05-27：禁止 web_search 后，宽窗口读取仍然会漂

现象：

- `auto-test-implement-tmux-action-contract-20260527T053300Z-20260527T054343Z`
  没有再触发 web search，也没有读 raw session。
- 但 worker 仍执行了 `ls -la` 和较宽 `sed` 窗口，例如
  `sed -n '1180,1415p'`。

判断：

- prompt 纪律能修一部分行为，但不能完全约束读取成本。
- 后续要把“读窗口大小、噪音命令、未声明命令”变成可机读 finding，
  不只是写在 prompt 里。

规则：

- worker 行为治理要从提示词升级到事件审计：命令事件里出现宽 sed、full
  dump、无意义 `ls`、未授权 web search，都应该进入 run summary finding。

## 2026-05-27：worker worktree 的参考项目路径要用绝对路径

现象：

- `reference_scan-multimachine-ssh-tailscale-tmux-governance-20260527T062000Z`
  被要求读取 `reference-projects/openhands/...`。
- worker 在自己的 `.a9/worktrees/...` 下执行，那里没有相对
  `reference-projects/openhands`，第一次 `sed` 和 `rg` 失败。
- worker 后续改用 `/root/a9/reference-projects/openhands/...` 才恢复。

规则：

- 给 worker 的参考项目锚点必须写绝对路径 `/root/a9/reference-projects/...`。
- 如果任务需要本仓库文件和参考仓库文件混读，二者路径边界要明确：
  worktree 内读 A9 文件，主仓库绝对路径读 reference projects。

## 2026-05-27：mechanism_extract 会忍不住落文档

现象：

- `auto-mechanism_extract-reference_scan-multimachine-ssh-tails-c9aefaf119`
  阶段是 `mechanism_extract`，目标是产出实现合同。
- worker 直接新增 `docs/remote-probe-contract.md`。
- 该文件不在 allowed_paths，scope_guard 失败，git governance 回滚。

规则：

- mechanism_extract 如果允许写文档，必须把文档路径显式加入 allowed_paths。
- 如果目标是下一刀实现，不要让 worker 先写合同文档；让它在 envelope 的
  `next_slice` 里输出合同即可。

## 2026-05-27：Codex exec stream reset 能恢复，但必须被记录

现象：

- `implement-remote-probe-action-contract-20260527T063000Z` 期间出现 4 次
  `stream disconnected before completion: Connection reset by peer`。
- worker 自动 reconnect 并继续完成 patch 和测试。

规则：

- A9 自己的长任务通讯治理必须把 reconnect 次数、阶段、最后成功事件、是否丢
  final envelope 作为一等证据。
- 这类恢复成功不算失败，但应该计入 run quality，用来判断是否要降速、重试或
  缩小 prompt。

## 2026-05-27：auto-test 会擅自升级成 integration implement

现象：

- `auto-test-implement-remote-probe-action-contrac-648cc80a2e` 阶段是 `test`，
  allowed_paths 只有 `scripts/a9_remote.py` 和 `tests/test_remote.py`。
- worker 发现 `probe_action` 没有透传到 control API，于是直接修改
  `scripts/a9_control_api.py` 和 `tests/test_control_api.py`。
- patch 方向正确，但 scope_guard 必须失败并回滚。

规则：

- test phase 发现需要跨模块实现时，应该输出 next_slice，不能直接改未授权路径。
- 监控者可以接管并新建/手工执行 expanded-scope patch，但这要记录为人工介入。
- supervisor 后续应把“正确 patch 但 outside allowed_paths”归为
  `needs-monitor-decision`，不要让 repair worker 在错误 scope 上空转。

## 2026-05-27：长测试无输出会误杀好 patch

现象：

- `implement-probe-action-routing-20260527T064200Z` 写出了正确小补丁。
- `tests/test_control_api.py` 已通过。
- `tests/test_supervisor.py` 本身需要约 131 秒，期间输出稀疏，worker 被
  idle timeout 杀掉，final envelope 缺失。
- patch/scope guard 通过，但 git governance 因最终状态回滚。

规则：

- 对 `tests/test_supervisor.py` 这类长测试，任务 idle timeout 至少要覆盖真实耗时，
  或测试命令需要 heartbeat wrapper。
- “patch guard pass + scope guard pass + check 部分已通过 + idle timeout”应进入
  monitor review，而不是直接让 worker 重跑。

修复：

- `effective_worker_idle_timeout_seconds(task)` 已加入：声明检查包含
  `tests/test_supervisor.py` 时，worker idle timeout 至少 `420s`。
- run summary 现在记录实际使用的 `idle_timeout_seconds`，方便后续判断是否又是
  长测试误杀。

## 2026-05-27：auto-next 会把明确 test next_slice 误包装成 reference_scan

现象：

- `auto-test-implement-node-last-probe-action-2026-e98bdb766a` 通过后输出的
  next_slice 很明确：补一个 `/api/nodes/probe` 非零返回路径的 handler 测试。
- 自动生成的下一单却变成
  `auto-reference_scan-auto-test-implement-node-last-probe-a-0a973d9d72`。
- 这个 phase 名会诱导 worker 去读参考项目、读前序 context，而不是直接补测试。

规则：

- 当 next_slice 明确是测试补强时，监控者应改写为 `phase: test`，只开放测试文件
  和声明的最小检查。
- auto-next 后续应根据 next_slice 动词识别 phase，而不是固定回到
  `reference_scan`。

## 2026-05-27：worker 通过了但仍有轻微上下文噪音

现象：

- handler 级 last-probe auto-test 没有越权改文件，也没有 web/service 查询。
- 但它读取了前序 run context，并执行了目录列表；对这个小测试来说不是必要证据。

规则：

- 小测试任务只给目标文件、失败日志和接口合同，不给前序 run context。
- 监控质量不能只看 pass/fail，还要记录 prompt 是否过宽、命令是否噪音、是否有
  不必要的大范围读取。

## 2026-05-27：worker 会把非声明检查失败误当主线

现象：

- `test-node-probe-retry-handler-20260527T081000Z` 明确要求只跑
  `python3 -m unittest tests/test_control_api.py`。
- worker 额外运行了 `python3 -m pytest ...`，环境没有 pytest，于是失败。
- supervisor 的 declared check 通过，但 worker 的 next_slice 仍然建议安装 pytest。

规则：

- worker 不应运行未声明检查；如果运行了，不能把未声明检查失败升级成项目主线。
- supervisor/monitor 评价任务时以 declared checks 为准，同时把额外命令失败记录为
  worker 纪律问题。
- 下一步不能为了 worker 的误判安装依赖；应回到产品主线和参考项目机制。

## 2026-05-27：多参考项目扫描会瞬间炸 event budget

现象：

- `reference-scan-multimachine-ssh-tailscale-tmux-20260527T082000Z` 要求同时看
  Codex、Cline、Aider、barter-rs。
- worker 先违反边界读取 `scripts/a9_service.py ps` 和 session summary 文档。
- 随后对四个大参考项目发起宽泛 `rg`，Aider fixtures 输出巨大，最终
  `worker event bytes exceeded 120000`。

规则：

- reference_scan 任务必须“一项目一机制”，不要让 worker 同时扫多个大型仓库。
- `rg` 必须带精确路径和更窄关键词，必要时用 `--glob` 排除 `tests/fixtures`、
  `target`、`node_modules`、`dist`。
- task prompt 不能同时要求“看顶级项目”和“不要输出太多”而不给具体文件锚点；
  监控者应先做轻量定位，再把精确 source path 交给 worker。

## 2026-05-27：新增 production helper 会打破旧 FakeRemote 测试契约

现象：

- reconnect governance patch 在 `probe_node()` 里直接调用
  `mod.connect_error_action()`、`mod.capped_reconnect_backoff_seconds()` 等新 helper。
- 旧的 `tests/test_control_api.py` FakeRemote 只实现了 probe 相关方法，导致
  `/api/nodes/probe` handler 测试返回 400。

规则：

- 给生产路径增加 helper 时，要么更新所有旧 fake，要么在生产代码里保持兼容 fallback。
- control API 这种边界层不应该因为测试/插件 fake 缺少新 helper 就整体 400。
- reconnect backoff 只对 `reconnect` 动作有意义；`connected`/`terminate` 应记录
  `reconnect_backoff_seconds=0`，避免 UI/调度误以为还会自动重试。

## 2026-05-27：MoE 评审不能先写代码再补方法论

现象：

- 先实现了 `a9_monitor.py` 的多专家评分雏形，但专家维度主要来自工程直觉：
  product/testing/architecture/business/governance。
- 用户指出金融系统需求组 20 年经验文档才是方法论源头，不能自己拍脑袋做 MoE。

规则：

- MoE reviewer 必须先读需求方法论和外部顶级评审方法，再定义专家角色。
- 专家不是“几个分数”，而是需求评审委员会：
  why、scope/dependency、system requirement、tradeoff architecture、
  role boundary、test verifiability、quality、exception governance、
  NFR/security、execution governance。
- 合议不能平均分，必须有 hard gate、tradeoff gate、execution gate、progress gate。

## 2026-05-28：通过测试的 worker patch 仍可能漏掉 helper 默认值陷阱

现象：

- `implement-probe-node-timeout-governance-20260528` worker 正确识别了
  `probe_node()` 需要把 SSH probe timeout 变成 retry/reconnect 状态。
- 但它调用 `gateway_reconnect_decision()` 时没有传
  `policy_budget_remaining`，而该 helper 默认 budget 为 0，会把真实
  timeout 覆盖成 `terminate`。
- worker 的测试 FakeRemote 没有实现真实 `gateway_reconnect_decision()`，
  所以测试通过但没有覆盖关键默认参数。

规则：

- 复用治理 helper 时必须检查默认参数是否代表“禁止执行/无预算/保守拒绝”。
- 测试 fake 不能只覆盖 happy path；至少要模拟会导致真实默认行为变化的字段。
- monitor 不能只看 pass/fail 和 scope guard；要人工读 patch 中所有决策 helper
  的入参，尤其是 budget、cap、approval、policy 这类默认值。

## 2026-05-28：latest evidence 测试不能只靠 mtime 排序

现象：

- `expose-latest-probe-evidence-in-node-status-20260528` worker 在 worktree 里通过
  112 tests，但 cherry-pick 到主线后同一测试失败。
- 原因是两条 probe evidence 写入太近，文件系统 `st_mtime` 可能相同，按 mtime
  排序会偶发选到旧 evidence。
- `write_node_evidence()` 文件名自带微秒时间戳，应该用文件名末尾时间戳作为
  tie-breaker；不能用完整文件名，因为 `probe-timeout-*` 前缀会压过 `probe-*`。

规则：

- “最新一条”这类测试不能依赖低精度 mtime 单字段。
- 证据文件名已经带时间戳时，排序必须把末尾时间戳纳入稳定 tie-breaker，不要让
  kind 前缀影响“最新”语义。
- 同样的 mtime 陷阱也适用于 `tmux-*.json` 证据；`node_status` 聚合 tmux action
  也必须使用 `(mtime, 文件名末尾时间戳)` 的稳定排序。
- worker 通过后，主控合并到 main 后仍必须重跑声明测试；worktree pass 不是最终验收。

## 2026-05-28：远端 bootstrap heredoc 必须防提前展开

现象：

- `remote-bootstrap-heartbeat-loop-script-20260528` worker 生成了
  `.a9/remote-node/heartbeat.sh`，方向正确，但 bootstrap 用未引用
  `<<EOF` 写脚本。
- 未引用 heredoc 会在 bootstrap 执行时提前展开 heartbeat 脚本里的
  `$NODE_ID`、`$(hostname)`、`$(cat /proc/loadavg ...)` 等内容，导致远端
  安装出来的脚本不再是原始模板。
- 同时 heartbeat 脚本通过 Python `os.environ` 生成 JSON，但 shell 变量
  `NODE_ID/STATUS/...` 未 export，子进程读不到真实值。

规则：

- 生成脚本的脚本必须使用 quoted heredoc：`<<'EOF'`。
- shell 变量要传给 Python/子进程时必须显式 `export`。
- bootstrap 类任务不能只断言字符串存在，还要断言 heredoc quoting 和 env 传递。

## 2026-05-28：tmux new-session 的 shell-command 必须是单个安全参数

现象：

- `harden-heartbeat-tmux-plan-quoting-20260528` worker 正确使用了 `shlex.quote`
  引用 `remote_dir` 和 heartbeat 脚本路径。
- 但它把 `A9_HEARTBEAT_INTERVAL=... heartbeat.sh` 拆成多个 shell 片段直接拼到
  `tmux new-session` 后面。
- `tmux new-session` 的 shell-command 应作为一个命令参数传入；否则真实执行时
  可能出现参数解释不一致，尤其是路径包含空格或分号时。

规则：

- 对嵌套 shell 命令要分两层处理：先 quote 内部路径/env，再把整条 run command
  作为一个 shell-command 再 quote 一次。
- 测试不能只检查危险路径被 quote，还要检查 tmux shell-command 内部嵌套 quote
  是否存在。
- 计划类 patch 在变成执行入口前必须先做 shell 语义审查。

## 2026-05-28：模型容量失败后的半成品不能只交给自动重试

现象：

- `test-api-nodes-status-heartbeat-start-absence-20260528` 使用
  `gpt-5.3-codex-spark` 跑到中途时返回 `Selected model is at capacity`。
- worker 已经产出了合理 patch：补 `/api/nodes/status` alias，并新增 API
  contract 测试；但由于没有 final envelope，supervisor 标记
  `retryable-worker-failed` 并回滚提交。
- run-loop 一度留下 queued/running 双状态，需要主控监控者介入判断 patch
  是否值得接管，而不是盲目让下一轮模型重复烧 token。

规则：

- `retryable-worker-failed` 不等于 patch 无价值；先读 `patch.diff`、
  `events.jsonl` 和失败原因。
- 如果 patch 范围小、方向对、测试可由监控者补跑，就由监控者接管并记录。
- 如果留下 queued/running 双状态，必须先清理 runtime 状态再继续无人值守。
