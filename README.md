# a9

A9 是一个私有 24 小时 agent 执行机器。核心方法是抄成熟开源项目的机制，魔改成本地能力，跑测试，记录证据，然后继续下一步。

核心文档：

- `AGENTS.md`：执行机器规则和“抄抄抄”核心方法。
- `docs/project.md`：项目背景、目标、架构、进度、下一步。
- `docs/method.md`：需求分析、评审闭包和执行方法。
- `docs/reference.md`：参考项目和复制策略。
- `docs/session.md`：MemPalace-first 后的人类 session 快照；不是事实源。
- `docs/mistakes.md`：错题本。

常用入口：

```bash
scripts/a9_supervisor.py status
scripts/a9_soak.py run --tasks 1 --fake-worker
scripts/a9_codex_session_adapter.py convert /path/to/session.jsonl --out .a9/mempalace/operator-session-drawers.jsonl
scripts/a9_mempalace_provider.py status
scripts/a9_mempalace_provider.py search "A9 MemPalace current mainline" --limit 5
cargo run -p a9-client -- config
```

控制面 MemPalace 入口：

```text
GET  /api/memory/mempalace/status
POST /api/memory/mempalace/search
POST /api/memory/mempalace/wakeup
```
