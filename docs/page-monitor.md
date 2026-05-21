# A9 Page Monitor

The page/TUI monitor is only the first continuity layer. It watches exported
transcript text, detects idle/stopped state, writes a snapshot, and can enqueue a
supervisor continuation task.

It must not become the canonical memory. Canonical state remains in supervisor
runs, evidence, checkpoints, MySQL, and Redis.

Commands:

```bash
scripts/a9_page_monitor.py check /path/to/exported-transcript.md --idle-seconds 300
scripts/a9_page_monitor.py watch /path/to/exported-transcript.md --idle-seconds 300 --enqueue-on-idle
scripts/a9_page_monitor.py status
```

`--now` is available for deterministic tests and replayed incident analysis.

Runtime files:

- `.a9/page_monitor/state.json`
- `.a9/page_monitor/latest_snapshot.md`
- `.a9/page_monitor/continuation_prompt.md`

Copied reference pattern:

- Cline browser action handling treats browser output as an observation that is
  summarized and returned to the agent loop.
- OpenHands keeps browser/sandbox resume as explicit lifecycle state, not hidden
  chat memory.
- A9 follows the same boundary: page monitor exports observations into durable
  supervisor tasks.
