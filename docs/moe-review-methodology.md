# A9 MoE Review Methodology

## Decision

A9 的 MoE 评审不是“几个 AI 打分”。它是 AI 时代的轻量化需求评审委员会。

流程可以压缩，但关键控制点不能缺失：

```text
真实问题
-> 系统需求
-> 方案权衡
-> 可验证标准
-> 异常/安全/非功能
-> 执行证据
-> 复盘改进
```

这个决策来自三类来源：

- 金融系统需求组方法论：`docs/source-extracts/original/requirements-management-analysis-guide.doc`
- OpenAI agent/evals/monitorability 方法
- Google 测试与 SRE 方法

## Why This Matters

AI 时代的变化是：

- 写代码更快。
- 原型更快。
- 多方案探索更快。
- 自动测试和自动修复更快。

但没有改变的是：

- 用户说的经常是方案，不是真问题。
- 系统需求必须从业务需求翻译而来。
- 金融/自动化系统必须考虑异常、安全、性能、审计。
- 复杂系统不能只看最终结果，还要看过程、动作、证据和失败模式。

所以 A9 不需要传统重流程，但必须保留需求工程的“点”。

## Source Alignment

### 金融需求指南

本地精读文档：

- `docs/requirements-guide-close-reading.md`
- `docs/source-extracts/requirements-management-analysis-guide.txt`

核心规则：

- 先问背景、目的、真实问题。
- 区分用户需求和系统需求。
- 搞清楚必须做、应该做、可以做。
- 方案要比较优缺点、耦合、复杂度和风险。
- 需求必须无歧义、完整、可验证、一致、可追踪。
- 异常、安全、性能、环境是接受条件，不是附加项。

### OpenAI

OpenAI agent evals 明确把 agent 质量放在 traces、graders、datasets、eval runs 上。
trace 捕获模型调用、工具调用、guardrails、handoffs，适合定位 workflow 级问题。

A9 对应：

- worker 的 event summaries 就是 trace。
- MoE expert 就是 grader。
- `.a9/runs` 是 dataset/eval corpus。
- 每轮 run 都应该生成可复盘 eval result。

OpenAI Evals API 也把 eval 定义成一组 testing criteria 和 data source config，
并支持用不同模型和参数运行。A9 应该把任务、trace、diff、checks、monitor_score
组织成可重复评估数据，而不是只看一次聊天结论。

OpenAI monitorability 的方向也支持 A9 的做法：不要只看 final answer，要看
prompt、actions、final output 等可观察表面。A9 不能访问隐藏思维链，所以更应该
治理外显行为链。

### Google Testing

Google 测试方法强调 small / medium / large tests，按 scope 而不是按名称分类：

- small：单函数/单模块，回答“代码是否做了该做的事”。
- medium：相邻功能交互，回答“功能是否互操作”。
- large：真实用户场景，回答“产品是否按用户期待运行”。

A9 对应：

- worker 小改动必须有 small test。
- API/control/mobile/remote 交互必须有 medium test。
- 24h 自动化、多机器接入、手机接管必须有 large scenario/e2e/soak test。
- 需要人工判断的 UI 体验、隐私暴露、业务合理性，不能伪装成自动测试。

### Google SRE

Google SRE 方法把可靠性当成产品能力，并系统化处理：

- SLO。
- 监控。
- 告警。
- incident response。
- postmortem。
- reliability testing。
- release engineering。
- simplicity。

A9 对应：

- 24h agent runtime 必须有 SLO：不中断、不丢证据、不越权、不无限烧 token。
- 告警必须基于用户/系统症状，而不是只看内部日志。
- worker 失败要写 incident/postmortem 风格的错题本。
- 简化是架构原则：任务越宽，越容易爆 token 和偏航。

## A9 MoE Experts

### 1. why_expert

问题：

- 真实问题是什么？
- 用户给的是需求，还是实现方案？
- 为什么现在要做？
- 不做会怎样？

否决：

- 只有方案，没有问题。
- 不能解释业务/系统价值。

### 2. scope_dependency_expert

问题：

- 涉及哪些模块、系统、角色？
- 是否需要拆分？
- 是否存在前置依赖、同步上线、强关联关系？

否决：

- 一单任务跨太多模块。
- 多系统依赖没有显式记录。

### 3. system_requirement_expert

问题：

- 用户需求是否已翻译成系统行为？
- 输入、输出、状态、错误、边界是否明确？
- 是否有功能范围和功能点？

否决：

- worker prompt 只有口号，没有系统行为。

### 4. tradeoff_architecture_expert

问题：

- 有哪些可选方案？
- 每个方案的优点、缺点、复杂度、耦合、风险是什么？
- 是否过度设计？
- 是否优先满足基本诉求？

否决：

- 没有 tradeoff 直接上复杂方案。
- 高耦合、高复杂度但收益不清楚。

### 5. role_boundary_expert

问题：

- 人类、monitor、worker、runtime、UI、Redis、MySQL 的职责是否清楚？
- worker 是否越权做产品/架构决策？
- monitor 是否只旁观而没有验收/纠偏？

否决：

- 执行机器自己决定主线。
- 页面/TUI 被当成主架构事实源。

### 6. test_verifiability_expert

问题：

- 是否可量化、可测试？
- 是否覆盖业务关注点？
- 数据敏感任务是否验收 schema/table/state/event，而不是只验接口返回 200？
- 测试属于 small/medium/large 哪一类？
- 是否只跑声明检查？

否决：

- 无测试。
- 不可验证。
- 数据结构/状态结构没有测试验收。
- 额外测试失败却误导主线，例如未声明 pytest。

### 7. quality_expert

问题：

- 是否无歧义？
- 是否完整？
- 是否一致？
- 是否可修改？
- 是否可追踪？

否决：

- 同一对象多套术语。
- 需求、代码、测试、证据无法追踪。

### 8. exception_governance_expert

问题：

- 正常流之外，异常流是什么？
- 失败怎么分类？
- 是否自动重试、人工介入、通知、恢复？
- 是否有审计和证据路径？

否决：

- 异常无人知晓。
- 失败无法恢复。
- 证据缺失。

### 9. nfr_security_expert

问题：

- 性能、容量、可靠性、环境要求是什么？
- 是否涉及权限、输入检测、敏感数据、审计？
- mobile/control API 是否可能泄漏 session、命令、token、密钥？

否决：

- 敏感数据明文暴露。
- 远程控制没有权限和审计。
- 性能/稳定性无量化目标。

### 10. execution_governance_expert

问题：

- worker 是否遵守 allowed_paths？
- 是否使用声明检查？
- 是否记录 source/license？
- 是否爆 token/event budget？
- 是否有 envelope、patch、checks、evidence？

否决：

- 越权读写。
- 缺 final envelope。
- 爆 event budget。
- 无证据说完成。

### 11. product_mainline_expert

问题：

- 任务是否服务当前主线，而不是被工程细节牵着走？
- 是否体现哲学/业务逻辑优先于工程实现？
- 是否能抓大放小，把 worker 从低价值支线拉回主线？

否决：

- 工程改动成立，但产品主线不成立。
- worker 继续旧队列惯性，忽略最新因果变迁。

### 12. external_learning_expert

问题：

- 需要抄/对标/考证时，是否真的看了参考项目、文档或外部资料？
- 是否记录了参考来源、机制、边界和不能直接抄的部分？

否决：

- 需要外部学习却只凭自己想。
- 没有 evidence/source 就宣称“参考了顶级项目”。

### 13. product_pressure_expert

问题：

- 是否有推翻弱方案、压缩范围、提高验收标准的能力？
- 是否明确 reject/shrink/tradeoff 条件？
- 是否避免“能跑就算好产品”的工程自嗨？

否决：

- 没有压榨标准，弱方案也放行。
- pass 了但没有形成更强的产品能力或证据。

### 14. data_model_expert

问题：

- 数据、表结构、状态、事件是否反映真实业务结构？
- 页面结构是否只是业务数据结构的表现层？
- 数据模型是否能解释权限、流程、异常和时序，而不是只堆字段？

判断：

- “数据对了，业务大概率对”是重要产品架构原则。
- 但不要机械说 99%。数据结构通常能反映大部分业务真实，剩余风险在权限、
  流程、异常、时序、用户心理和组织约束。

否决：

- 数据敏感任务没有 schema/table/state/event 结构。
- 页面/API 做出来了，但数据结构不能代表真实业务对象。

### 15. performance_depth_expert

问题：

- 性能、延迟、吞吐、缓存、超时、预算和稳定性是否被明确考虑？
- 性能是否服务产品厚度和长期可用性，而不是只做跑分快？

否决：

- 通讯/网关/控制面任务没有性能和稳定性边界。
- trace/token/log 异常膨胀却继续放行。

## Council Decision Rules

不能平均分。

正确合议规则：

```text
hard gate:
  why/security/exception/verifiability/data_model 任一失败 -> block

tradeoff gate:
  方案复杂度、耦合、收益不清楚，或缺少产品压榨标准 -> needs_tradeoff

execution gate:
  worker 越权、爆 token、缺证据、测试错跑 -> repair/narrow

progress gate:
  主线清楚、数据结构正确、证据完整、测试通过、异常覆盖、性能边界清楚 -> continue
```

## What Changes In A9

### Worker Prompt

每个非平凡任务必须带：

- 背景和真实问题。
- 系统需求。
- 必须/应该/可以。
- 方案边界。
- 测试要点。
- 风险和异常。
- 非功能/安全要求。
- allowed paths 和 declared checks。

### Monitor Score

`a9_monitor.py` 不能只输出一个总分，应输出：

- `experts[]`
- 每个 expert 的 findings。
- hard gate 状态。
- recommended action。
- evidence path。

### Session Governance

session 精读必须服务于需求变迁：

- 原始想法。
- 为什么变。
- 哪些结论过期。
- 哪些变成系统需求。
- 哪些变成 worker 任务。

### 24h Runtime

24h 机器不只是自动跑任务，而是：

```text
需求方法论
-> MoE 评审
-> worker 执行
-> evidence
-> eval/monitor_score
-> repair/next
```

## Immediate Next Step

不要继续扩功能。

下一刀应重构 `scripts/a9_monitor.py`：

1. 引入本文定义的 expert names。
2. 把 hard gate / tradeoff gate / execution gate / progress gate 做成显式字段。
3. 对 worker task prompt 做需求质量检查。
4. 先用历史坏 run 和好 run 回放验证。

## References

- OpenAI Agent Evals: https://developers.openai.com/api/docs/guides/agent-evals
- OpenAI Evals API: https://platform.openai.com/docs/api-reference/evals
- OpenAI Monitorability paper: https://cdn.openai.com/pdf/d57827c6-10bc-47fe-91aa-0fde55bd3901/monitoring-monitorability.pdf
- Google Testing Blog, small/medium/large tests: https://testing.googleblog.com/2011/03/how-google-tests-software-part-five.html
- Google SRE Book: https://sre.google/sre-book/table-of-contents/
- Google SRE Workbook: https://sre.google/workbook/index/
