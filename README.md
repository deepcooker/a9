# a9

A9 是一个私有 24 小时 agent 执行机器。核心方法是抄成熟开源项目的机制，魔改成本地能力，跑测试，记录证据，然后继续下一步。

核心文档：

- `AGENTS.md`：执行机器规则和“抄抄抄”核心方法。
- `docs/context-governance.md`：当前上下文入口和文档分层。
- `docs/project.md`：项目背景、目标、架构、进度、下一步。
- `docs/mistakes.md`：错题本。

常用入口：

```bash
scripts/a9_supervisor.py status
scripts/a9_soak.py run --tasks 1 --fake-worker
cargo run -p a9-client -- config
```
