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

## 什么时候要停 worker

出现这些情况就停：

- 一直读文件，不实现。
- events/log/prompt 增长太快。
- 忘了“先抄成熟项目”。
- 开始做业务发散，而不是当前基础设施任务。
- 改无关文件。
- 测试失败却没有进入修复路径。
- 只输出自信总结，没有 durable artifact。

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

## 怎么用

健康检查：

```bash
scripts/a9_supervisor.py status
scripts/a9_soak.py run --tasks 1 --fake-worker
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
