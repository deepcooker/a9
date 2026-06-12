# A9 Current Requirements Review Packet

## current_state_model
- 真实问题：这是一个**24 小时执行机器的半成品治理收尾任务**，不是生产功能新增任务。A9 在 `docs/project.md:109` 已有 runtime、context、automation、governance 的 MVP 组成，但仍处于需先做 requirements 对齐后的讨论阶段（`docs/worker-method-packet.md:23-24`）。
- 当前主线事实：
  - `scripts/a9_supervisor.py` 已具备队列、auto-next、状态写入、patch/check guard、deterministic SEARCH/REPLACE、git governance 等能力（`docs/project.md:111`）。
  - Redis/MySQL/flow 管理与 policy attestation 已有首版，含 `needs-approval -> flow-wait/resume` 与 `expected_revision` 保护（`docs/project.md:198-223`）。
  - 移动/控制 API 已进入治理型功能（重启、审计尾端、控制发现）并附安全门（`docs/project.md:123-124`, `docs/agent-runtime-observations.md:552`）。
  - 运行观察层明确指出：执行质量问题多来自执行边界/契约而非纯能力缺口，例如未声明检查执行、operator 纠偏被 auto-next 继续吞掉、严格 envelope 失败（`docs/agent-runtime-observations.md:53-61`, `docs/agent-runtime-observations.md:92-109`, `docs/agent-runtime-observations.md:435-438`, `docs/agent-runtime-observations.md:678-700`）。
- 当前阶段约束：方法文档明确要求 `debate_next` 仅做 close-read/reverse-model/review；未决问题不能进入生产改动（`docs/worker-method-packet.md:28-51`, `AGENTS.md:20-23`）。

## business_object_map
- `operator_session`（人类/主控窗口）
  - 责任：真实需求输入、业务场景确认、监控者确认与续行指令。
  - 当前证据：`session_refresh -> session_close_reading` mini-flow 已接入 auto-next；`docs/project.md:119`。
- `runtime_session`（A9 24h 执行会话）
  - 责任：`.a9/tasks`/`.a9/runs` 作为执行证据与恢复入口。
  - 当前证据：`.a9/tasks/queue/running/done`、`.a9/runs` 等运行时对象已定义（`docs/project.md:141-149`）。
- `flow`（Redis managed flow）
  - 责任：并发安全推进、审批阻塞恢复、状态一致性。
  - 当前证据：`expected_revision` + `flow_wait`/`flow_resume` + `flow_transition`（`docs/project.md:198-216`）。
- `run`（执行证据条目）
  - 责任：记录 prompt、events、patch、checks、summary、state、policy attestation。
- `task`（执行切片）
  - 责任：承载 `decision_status` 与 `checks`，为 worker 指定允许执行边界。
  - 当前证据：方法路由要求已在 prompt 注入层体现（`docs/project.md:730-744`）。
- `service`（control-plane service）
  - 责任：control-api/recovery-loop/node-worker/supervisor 状态与运维控制。
  - 当前证据：`a9_service.py` 与 `api/services` 功能（`docs/agent-runtime-observations.md:3-23`, `docs/agent-runtime-observations.md:552`）。
- `policy_attestation`（合规与完整性摘要）
  - 责任：监控审计、决策引用、签名与复用能力。
- `governance finding`（治理发现）
  - 责任：记录边界违规与建议，不直接自动阻塞主业务（除安全/破坏性）以便先观测后决策。

## data_model_draft
- 核心对象（高优先级先行，数据优先于性能）：
  - `flow`（Redis JSON）
    - 字段：`id`, `status`, `revision`, `expected_revision`, `attestation_hash`, `policy_hash`, `waiting/approval/resume` 状态元数据。
  - `goal`（A9 goal object）
    - 字段：`objective`, `status`, `token_usage`, `blockers`, `completion_audit`。
  - `task`（队列任务）
    - 字段：`id`, `route`, `phase`, `checks`, `next_slice`, `decision_status`, `strict_worker_envelope`。
  - `run`（执行记录）
    - 字段：`summary`, `state`, `evidence`, `patch`, `checks`, `monitor_findings`, `worker_failure`, `protocol/exit`。
  - `session_payload`
    - 字段：`flow_id`, `flow_expected_revision`, `attestation refs`, `policy hash refs`。
  - `service_audit_event`
    - 字段：`timestamp`, `action`, `command`, `status`, `gate`, `reason`, `payload summary`, `scope`.
  - `raw session / raw close-reading / causal memory`
    - 保持事实原始性；摘要仅为检索索引，不可替代真相来源（`AGENTS.md` 与 `docs/reference-adoption-decision.md:278-295`）。
- 缺失字段/未决草案：
  - `decision`、`out_of_scope`、`change_record` 尚未对每个执行任务形成统一约束（`docs/requirements-guide-close-reading.md:471-499`）。
  - 数据对象与事件缺少统一术语表，当前混用（`docs/requirements-guide-close-reading.md:409-410`）。

## state_flow_draft
- 当前正常流（建议统一）：
  1. 人类/监控者发起任务输入（含问题与边界）。
  2. 任务进入队列（含 decision packet）。
  3. Worker 按 `checks` 获取执行权限执行，生成 diff + 声明检查证据。
  4. Supervisor 通过 guard → patch → 检查 → policy attestation。
  5. 通过后推进 flow 或提交结果；失败进入 `needs-repair`。
- 现状异常流（已观察到）：
  - `process_governance.findings[undeclared_check]` 被错误注入下一任务执行流（待决，不应默认执行）；已反复记录为治理问题（`docs/agent-runtime-observations.md:121-133`, `134-154`）。
  - operator 修正任务被 auto-next 自动切片压过，需优先级通道（`docs/agent-runtime-observations.md:56-61`, `67-90`）。
  - strict envelope 失效导致保存 patch 丢失/回滚，后续靠 reconcile salvage（`docs/agent-runtime-observations.md:388-405`, `423-433`, `719-728`）。
- 流程目标（应保留）：
  - `debate_next` 阶段产生 review/change packet；`execution_next` 才允许实现。

## implementation_gap
- 数据契约缺口：
  - 任务级 `must/should/could`、`out_of_scope`、`change_record` 在多数执行任务中未形成硬性输入；与方法要求偏差（`docs/requirements-guide-close-reading.md:473-499`）。
  - 术语未统一，导致状态/对象语义混淆（`docs/requirements-guide-close-reading.md:398-410`）。
- 状态治理缺口：
  - operator 优先级 lane 和声明检查边界仍是建议级未完成（`docs/agent-runtime-observations.md:67-90`, `114-132`, `134-154`）。
  - 生产路径仍可因未声明测试执行/报告导致上下文/预算噪音（`docs/agent-runtime-observations.md:52-54`, `190-193`）。
- 目标契约缺口：
  - 当前仍有“实现先行”风险入口：缺少明确的、任务级 review packet（本次任务即补齐）。
- 证据路径缺口：
  - raw session 与 runtime session 的边界保持，但需要在任务进入 execution 之前统一注入需求对齐 evidence（`docs/session...` not read now, but project notes it).

## reference_findings
- `Codex` 参考机制：
  - 历史/上下文有序、history_version、budget/compaction、prompt 重建顺序（`docs/session-governance.md` 中已列；`docs/reference-adoption-decision.md:242-246`）。
  - 本地化建议：`continuation` 与优先输入拦截（`docs/agent-runtime-observations.md:69-77`，`reference-projects/codex/...`）。
- `OpenClaw/Lobster`：
  - managed-flow、approval/wait/resume、policy attestation 适配 A9 并已部分落地（`docs/project.md:198-223`, `docs/reference-adoption-decision.md:238-245`）。
  - 本地化建议：将 `needs-approval` 和 `flow-wait/resume` 与 operator 纠偏优先权合并为统一异常边界。
- `Aider`：
  - `repomap` 与搜索替换 discipline 已用于控制成本和上下文污染（`docs/reference-adoption-decision.md:100-103`, `docs/agent-status` via project mention）。
  - 本地化建议：保持 narrow read + repo map-first，避免 broad slice（`docs/agent-runtime-observations.md:621-623`）。
- `Barter-rs`：
  - 作为通信治理与重连治理参考（`docs/project.md:98-99`, `docs/reference-adoption-decision.md:215-216`）。
- `LangGraph / mem0 / Hermes`：
  - 作为 checkpoint/agent 可追溯/检索与 sidecar 参考，不做 hot path 决策核心（`docs/reference-adoption-decision.md:250-258`）。

## open_questions
- 在当前约束下，是否应先只封装一条决策门：
  - operator priority lane（`monitor` 纠偏先于 auto-next）？
  - 或先把 declared-check 边界从 `next_task_prompt` 到任务契约一体化再改？
- `strict_worker_envelope` 的可恢复策略统一为：
  - 只在 parse 成功时自动推进，还是像现状一样保留 `reconcile` 兜底（需成本与误报权衡）？
- 如何把 `change_record` 和 `out_of_scope` 固化为运行时任务字段？
- 在当前阶段，“产品质量”由哪个角色审批该类边界修正（product/mainline 与 requirements）并落入 evidence（需可追溯引用）？
- `service_control_audit` 和 recovery-loop execute-mode 信息是否已足够支撑移动端审批之外的监管闭环？

## decision_options
- Option A（建议优先级高）：不改变大功能，仅补 `debate_next` 级需求成形：
  - 产出决策 packet（业务对象、数据模型、状态流、异常流、未决项）并发布变更请求；
  - 在执行队列中封禁未决项；
  - 风险：短期推进慢，但降低后续误实现概率。
- Option B：把 operator 优先级 lane 与 declared-check 边界作为一个并行实现切片立即执行：
  - 速度快，贴合已观察缺陷；
  - 风险：没有统一问题卡和 out_of_scope 前提，会重演“实现先行”。
- Option C：先继续通信功能扩展：
  - 与当前主线指示冲突（`docs/project.md:230-233`），且已出现需求漂移风险。
- 推荐：选择 Option A，随后 A/B 以顺序式小切片执行。理由：当前任务是“需求对齐缺口”而非功能缺口。

## review_packet
- Product/mainline pressure findings:
  - 当前最大压力不是新增功能，而是主线一致性：防止通信/执行主线再次偏航，保留目标边界。
  - `docs/requirements-guide-close-reading.md` 与 `AGENTS.md` 的核心：缺决策不能执行。
- Review questions（待产品/架构/测试角色确认）：
  - 真实问题是否明确到“人类监控 + runtime 自愈可恢复”而非“更多功能”？
  - 是否接受本次将 `agent-runtime-observations` 中的 `undeclared_check`、`auto-next` 偏航纳入硬边界治理项？
  - 是否将 `plan lane` 作为主要决策面，且禁止 plan 文件改写 contract 字段（沿用现行权责）？
  - 当前 `runtime` 与 `canonical` 数据状态是否足够覆盖 token/故障/审批轨迹，是否还有遗漏字段？
  - 哪些项明确写入 `out_of_scope`，尤其 mobile/control、通信 runtime 与金融垂直。

## execution_backlog_draft
- 该 backog 仅在 `decision_status: decided` 后执行，当前仅作决策草案：
  1. 数据契约修订
    - 明确字段级 `task`、`run`、`flow`、`service_audit_event` schema（最小闭环）。
    - 产出文件：`docs/project.md` 或独立 `docs/data-model.md` + plan 合约引用。
  2. 决策路由强化
    - 实现 operator correction 优先级 lane 与 declared-check 边界统一化（`scripts/a9_supervisor.py`, `tests/test_supervisor.py`）—在任务 packet 通过后再执行。
  3. 产物审计标准
    - 统一 task 成形卡（must/should/could/out_of_scope/change_record）模板并加入产品/mainline、架构、测试评审问题。
  4. 术语治理
    - 建 `docs/glossary.md`，统一对象术语并在 prompt 模板中强制引用。

## what_is_not_decided
- 是否把 `reconcile_worker_envelope_check_conflict` 保留为 salvage-only 或升级为硬阻断。
- 是否将 operator priority lane 设为“仅监控可见”还是入 auto-next 调度主路径。
- 何时将通信主线和 mobile/control 的下一步提上 execution 级别（`docs/project.md` 当前建议仍以 session governance/因果链优先）。
- 统一 `out_of_scope` 的标准清单是否以项目层还是任务层维护。
- 允许的 `allowed_execution` 语义：只读 + 只改文档与 tests 还是允许部分脚本修复（需 product/mainline 决策）。

## next_debate_next
- 下一步应继续以 `debate_next` 运行，不进入功能实现。
- 具体行动：
  1. 把本 packet 附带到本任务的 `review` 路径，要求 requirements/architecture/test 角色各给一句“不同意点”与“可接受点”。
  2. 用 `docs/reference-adoption-decision.md` 的分层标准确认本次引用机制是否全部用于运行核心（其余仅作为 sidecar）。
  3. 在确认后产生变更请求：允许执行的第一小切片应为 `operator correction lane` + `declared-check boundary`，并同步更新 `out_of_scope` 和验收标准。
