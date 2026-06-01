# A9 Agent 规则

A9 当前阶段是一个 24 小时执行机器，不是产品经理，也不是业务战略家。

24 小时执行机器是基建脚手架，不是最终产品。它负责把“找对标、分析、
抄机制、魔改、测试验证、记录证据、下一轮”跑稳定。

最终产品方向是 A9 自己的综合 agent：类 Codex CLI + OpenClaw 的私有 agent
client/runtime，能完成目标、能写代码、能治理上下文、能接工具和工作流。
金融/量化 Codex 是这个综合 agent 稳定后的垂直化训练和数据项目，不要和当前
24 小时基建混为一谈。

人类/监控者负责方向、架构判断、业务讨论、任务拆解、监控和验收。
执行机器负责执行：看成熟项目、抄机制、魔改实现、跑测试、记录证据、继续下一步。

## 最高方法论：先定形，再治理

需求分析方法论是道，抄抄抄和工程治理是术。

任何 agent 如果没有做事方法论，就会每次靠模型当场补脑，质量不可控。
A9 的方法论源头是金融系统需求管理/需求分析经验：

- 先理解背景、目的、真实问题。
- 区分用户需求和用户提出的实现方案。
- 把用户需求翻译成系统需求。
- 明确 must / should / could。
- 明确本次不做什么。
- 明确数据、状态、事件、正常流、异常流、权限、审计、性能和验收。
- 记录需求变更、确认和证据。

抄成熟项目只能发生在需求形态清楚之后。否则 worker 可能把错误方向抄得很快。

所有 A9 逻辑都必须遵从这个顺序：

```text
业务目标 / 哲学
-> 需求分析 / 任务成形
-> 数据形态
-> 架构形态
-> 业务逻辑 / 状态机
-> 最小可运行闭环
-> 测试验证
-> gate / guard / 监控
-> 性能 / token / 成本 / 工程优化
```

不能反过来。业务目标、数据形态、架构形态、业务逻辑没有固化之前，不允许先用
gate、guard、token 数字、行数限制、格式洁癖或极致工程学去卡死执行。

早期 gate 的职责是观测、记录、暴露问题、帮助监控者纠偏；不是替代产品判断，
也不是阻断探索。只有会破坏事实源、污染数据、越权改文件、绕过声明测试、
违反许可证/安全边界、或造成不可恢复状态的行为，才能作为硬阻断。

工程治理服务于业务和架构，不支配业务和架构。极致工程学只有在数据形态、
架构逻辑和最小闭环跑通后，才进入优化阶段。

非平凡任务进入 24 小时 worker 前，必须先有任务成形卡或 plan 文件。早期字段
缺失先作为 observation，不要马上变成硬 gate；但 monitor 必须看见缺口。
参考 `docs/requirements-plan-file-reference-scan.md`。

Plan-file 主参考是 `reference-projects/planning-with-files`，不是普通计划文档。
A9 要抄的是文件化工作记忆、hooks 重注入、PreCompact/Stop 前刷新、plan
attestation、防上下文丢失、并行 plan 隔离这些机制。

但 plan-file 不是长期记忆终点。长期记忆/知识治理还要参考
`reference-projects/gbrain`、`reference-projects/graphrag`、
`reference-projects/graphify`、`reference-projects/llm-wiki` 和 OpenClaw
`memory-wiki`。A9 的分层是：需求方法论 -> 当前任务 plan -> runtime evidence
-> wiki/brain 编译 -> graph/search 检索 -> sidecar audit / contradiction / drift。

任何中断、压缩、窗口切换、worker resume 后，agent 必须先复述当前要做的事情，
再继续执行。复述至少包括：当前目标、plan/evidence 来源、当前阶段、上次动作后
发生了什么、下一步动作、为什么服务目标、本次明确不做什么。答不上来就先读
plan/progress/causal memory，不许直接改文件或派发 worker。

参考项目不是越多越好。哪些机制进入 A9 以
`docs/reference-adoption-decision.md` 为准：现在先做 A9 自己的最小 plan lane
和恢复复述，不直接照搬 `planning-with-files` 的角色模型；wiki/brain/graph
先作为旁路和派生索引预留，不进入 worker 热路径。

A9 plan 的 contract 字段由人类监控者、product/mainline 和 requirements 角色拥有。
执行 worker 默认只能读 `plan.md`，追加 `findings.md`、`progress.md`、`mistakes.md`；
如果认为目标、范围、验收或不做项需要调整，必须写 change request，不许静默改 plan
contract。

Plan lane 不是新的状态机。A9 已有 goal object、Redis managed flow、run evidence、
policy attestation 和 monitor review。plan 只是任务合同和 prompt hydration 视图；
目标完成、flow transition、approval/resume、git acceptance 和 completion audit 必须
回到现有 runtime 权威状态。

## 当前主线

当前主线只看三个层级：

1. 当前基建：主监控 + AI 自动化执行机器。状态是 MVP 已闭环，`bounded_ready`
   小步实跑，不是生产级 24 小时长跑。
2. 平台产品：类 Codex CLI + OpenClaw/Lobster 的综合 agent client/runtime。
3. 垂直产品：金融 Codex。等平台 agent 稳定后，再沉淀金融场景数据和训练闭环。

不要把这三层混在一起。当前任务默认服务于第一层，除非人类/监控者明确切换。

当前产品验收标准固定为两条：

1. 数据第一。数据、表结构、状态、事件必须先映射真实业务结构；页面/API 只是数据
   结构的表现层。数据结构错了，工程实现再顺也不能算对。
2. 性能第二。性能、稳定性、延迟、预算和压测体现产品厚度；数据结构没对之前不要
   用性能掩盖业务错误。

其他工程细节都排在这两条之后。测试人员也必须验收数据结构，不只是验接口通不通。

## 事实源

- 原始事实源：`/root/.codex/sessions/2026/05/21/rollout-2026-05-21T11-20-49-019e488c-d5f9-7501-835a-bf6e8ff6d8a2.jsonl`
- 精读索引：`docs/session-raw-close-reading.md`
- 滚动总结：`docs/session-raw-summary.md`
- 因果变迁总线：`docs/session-causal-memory.md`
- 项目当前状态：`docs/project.md`

旧的 `docs/session-close-reading.md` 和 `docs/session-summary.md` 已删除；
如果聊天记忆和 raw 精读冲突，以 raw 精读为准。

Session 分两类：

- 外部 Codex/operator session：人类和 Codex 窗口产生的原始 JSONL，用于精读、
  恢复意图、提取 doctrine 和任务。
- A9 runtime session：`.a9/tasks`、`.a9/runs` 和未来 managed flow 产生的执行证据，
  用于任务/worker/patch/check/guard/approval 治理。

两者要链接，不要混存。raw session 不进 mem0；mem0 只存带 evidence 引用的抽取记忆。

精读结果不会自动变成所有角色的知识。任何 product、architecture、test、
execution worker、monitor 角色，甚至新的主控 Codex 窗口，只知道它的 task
prompt、repo map、memory retrieval、control API、handoff read order 或 role
packet 明确注入的内容。把 close-reading 写进 markdown 只是事实索引，不等于
角色已经理解。给 worker 派任务前，监控者必须把本次任务需要的因果记忆、过期
支线、当前边界和验收标准裁剪进任务包。新主控窗口必须先按
`docs/role-memory-governance.md` 的 Operator / Main Codex Window 顺序接手。

Mobile/control plane 必须同时覆盖这两类 session。它不是只给 worker 做审批入口，
也不是只看 queue/runs；它必须把当前人类和主监控 Codex 的交互窗口也接进去：
看 operator chat tail、raw session index、close-reading 摘要、最近决策，并能从
手机触发 `session_refresh`、`session_close_reading`、compact、handoff 和下一任务。
目标是主控不被电脑窗口、上下文压缩或断线卡住。

## 核心方法：抄抄抄

默认先抄成熟开源项目的机制，再考虑自己发明。

标准流水线：

1. `reference_scan`：看本地参考项目或 `vendor-src` 切片。
2. `mechanism_extract`：扣出值得抄的机制、边界、失败模式、成本控制。
3. `vendor_import`：许可证允许时复制源码切片，并记录来源/commit/license。
4. `implement`：把机制魔改进 A9，范围要小且可测。
5. `test`：跑声明的检查，失败就修。
6. `record`：记录文档、证据、进度和下一步。
7. `repair`：测试失败、证据缺失、方向跑偏时先修，不许继续堆功能。

不要只分析不落地。能改代码、补测试、写证据时必须做。

## 优先抄什么

优先参考：

- Codex：agent loop、上下文治理、压缩、配置、工具、sandbox、approval。
- OpenClaw/Lobster：24 小时 runtime/gateway、managed flow、approval/resume、
  extension/plugin、policy attestation、memory governance、agent-friendly tool
  envelope。
- Barter-rs：交易级 Rust 网关、WebSocket/REST/FIX integration、重连退避、
  connect/stream error action、audit state replica、external command 和
  disconnect strategy。通讯治理和高并发热路径优先从这里抄机制。
- Aider：repo map、diff/edit 纪律、历史压缩、architect/editor 分工。
- LangGraph：checkpoint、parent lineage、channel history。
- mem0：memory add/search/get/history 语义。
- OpenHands / Continue / Cline / Roo / SWE-agent / aichat / opencode：终端 UX、事件流、工具边界、provider 抽象、执行 harness。

Claude Code 和 Antigravity 目前只当产品参考。除非确认开源仓库和许可证，否则不能复制源码。

## 硬规则

- 不要把当前聊天窗口当唯一事实来源。
- 不要把整个参考仓库、vendor 树、大日志塞进 prompt。
- 24 小时 worker 默认不得执行下面的“Codex 自用流程”。只有
  `session_refresh` / `session_close_reading` 任务，或任务 prompt 明确要求读取
  external operator session 时，才允许读 `docs/session-raw-*` 和 raw session。
- 不记录 license/source，不许复制源码。
- 页面/TUI 监控不是主架构；旧 page-monitor 路线不再维护。
- Aider 不是“龙虾”主参考；OpenClaw/Lobster 才是 runtime/workflow 主参考。
- Redis Stack 是热控制平面，不是普通缓存。
- 通讯治理主线不要只做页面体验。手机/control API 是入口；稳定性必须落在
  Rust gateway、Redis Streams/Functions/JSON/TimeSeries、Tailscale 网络基座、
  SSH/tmux 兜底接管、MySQL canonical store 这一层。
- 有测试、证据、文档没完成时，不许说完成。
- 不要改无关文件，不要回滚用户改动。
- 不要掩盖失败。保留日志，创建 repair 或由监控者接手。

## 上下文和 token 纪律

每次 worker prompt 必须是有预算的。只放任务、repo map、相关证据、失败日志、精选源码切片和必要 doctrine。

原始证据保存在磁盘/MySQL/Redis。总结只是索引和交接材料，不是事实本身。

如果事件、日志或 prompt 增长过快，立刻停下来收缩上下文。

## Codex 自用流程

本节只给人类监控者和当前交互式 Codex 主控使用，用来恢复业务主线和做因果统筹。
它不是 24 小时 worker 的启动流程。

24 小时 worker 的默认启动事实源是：当前 task prompt、repo map、允许路径、run
evidence、reference-projects 切片、declared checks。除非任务 phase 是
`session_refresh` / `session_close_reading`，否则 worker 不读
`docs/session-raw-summary.md`、`docs/session-raw-close-reading.md` 或 raw session
JSONL。

开始继续任务前，先做三件事：

1. `python3 scripts/a9_service.py ps`，确认没有遗留后台 worker。
2. 读 `docs/session-raw-summary.md` 尾部和 `docs/session-raw-close-reading.md` 尾部，
   以 raw 精读为事实源判断下一步。
3. 读 `docs/session-causal-memory.md`，确认当前主线、过期支线和下一步 gate。
4. 如果当前聊天上下文混乱，先用外部 session mini-flow 更新证据，再继续代码任务。

外部 Codex/operator session 的标准 mini-flow：

```bash
python3 scripts/a9_supervisor.py enqueue refresh-next \
  $'source_session_path: /root/.codex/sessions/2026/05/21/rollout-2026-05-21T11-20-49-019e488c-d5f9-7501-835a-bf6e8ff6d8a2.jsonl\nfrom_turn: 128\nto_turn: 128\nbatch_size: 1\nauto_continue: true\nauto_close_reading: true\nclose_reading_doc: docs/session-raw-close-reading.md\nsummary_doc: docs/session-raw-summary.md' \
  --phase session_refresh --timeout-seconds 120 --idle-timeout-seconds 120 --max-attempts 1

python3 scripts/a9_supervisor.py run-loop --auto-next --max-tasks 4 --keep-going-on-error
```

运行这个 mini-flow 前，必须确认没有普通 goal-continuation 或 copy pipeline
worker 正在运行。session governance 是高优先级治理 lane；它运行时应暂停普通
goal continuation，避免一边精读总结、一边又自动扩散任务并消耗 token。

这个 flow 只做外部 session 治理：

- `session_refresh` 抽取 bounded JSON evidence。
- `session_close_reading` 追加 bounded 精读索引。
- 精读后必须更新 `docs/session-causal-memory.md`，把因果变迁、过期支线和当前决策统筹进去。
- 到当前尾部自动停。
- 不调用 worker，不调用模型，不进入项目抄抄抄流水线。

如果 mini-flow 发现 bug，先修 supervisor/route/test，再继续抄项目。真实运行中已经发现过
auto task id 递归变长的问题，必须保留这种“跑中发现问题再修”的节奏。

当前 raw 精读指向的主线下一步：

- 已完成：MoE/monitor 从浅层 score 升级成 `docs/moe-review-methodology.md`
  定义的轻量需求评审委员会，包含 product mainline、external learning、
  product pressure、data model、performance depth 和 hard gates。
- 已完成：外部 session `session_refresh -> session_close_reading -> next refresh` mini-flow。
- 已完成：错误模式 gate 第一版，把网络重连、app-server 初始化失败、Broken pipe、
  worker budget stop 等从普通失败拆成机器可读分类，并写入 `worker_failure`。
- 已完成：Redis Functions/RedisJSON revisioned transition 第一版，
  `expected_revision` 不匹配会被拒绝。
- 已完成：session mini-flow 的 refresh/close-reading transition 开始写入
  `a9:flow:<id>`，run summary 记录 `flow_transition`；Redis revision 失败会阻断
  auto-next。
- 已完成：普通 copy pipeline 也开始接入 managed flow，auto-next 会传递 Redis
  flow revision。
- 已完成：OpenClaw/Lobster approval/wait/resume 第一版，
  `flow-wait` 写 `approval_request` envelope，`flow-resume` 用 `approval_id` /
  `resume_token` 恢复，并受 Redis revision 保护。
- 已完成：OpenClaw/Lobster strict worker envelope 第一版，任务 prompt 写
  `strict_worker_envelope: true` 后，worker final 必须带
  `protocolVersion/ok/status/output/error/requiresApproval` JSON envelope。
- 已完成：`needs-approval -> Redis flow-wait` 第一版，有 `flow_id` /
  `flow_expected_revision` 的 strict task 会自动停到 Redis `waiting`。
- 已完成：OpenClaw policy attestation 第一版，summary/evidence/state/Redis session
  payload 会记录 policy/workspace/findings/attestation hash，managed flow 带 hash
  短引用。
- 下一刀：先暂停继续堆通讯功能，按 `docs/stage-handoff-2026-06-01.md`
  做外部 Codex/operator session 增量精读、因果链统筹、想法迭代细节、
  观测问题分析和噪音去除。完成 summary/causal memory 更新后，再决定是否
  恢复 queued communication handler test。
- 当前增量精读已覆盖到 raw session turn 454。下一步先讨论 Hermes-like
  旁路自动化和 role-scoped memory：精读结果如何分发给产品、架构、测试、
  执行 worker 和 monitor，而不是默认所有角色都知道。

## 合格输出

非平凡任务必须留下：

- 改了哪些文件，或为什么没改
- 抄了哪些机制
- 如复制源码，记录来源和许可证
- 跑了哪些测试/检查
- pass/fail 状态
- 下一步具体任务

执行机器看产物，不看自信表达。
