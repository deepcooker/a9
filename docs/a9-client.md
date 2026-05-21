# A9 Client

`crates/a9-client` is the first A9-owned Codex-like client front door. It is a
thin Rust binary that submits work into the existing supervisor instead of
becoming a second canonical agent loop.

Copied product boundaries:

- Codex: durable local session state and derived prompt/context boundaries.
- Aider: bounded task prompts instead of dumping whole repositories.
- LangGraph: stable session IDs and continuation lineage.
- Cline/OpenHands: UI/client events are adapters, not canonical state.

Commands:

```bash
cargo run -p a9-client -- init --api-url http://127.0.0.1:8080/v1 --model gpt-5.5
cargo run -p a9-client -- config
cargo run -p a9-client -- submit --task-id copy-client --phase reference_scan --check "cargo build --workspace" "copy the next client mechanism"
cargo run -p a9-client -- status latest
cargo run -p a9-client -- resume latest "tighten the client session model"
```

Use `--run` on `submit` or `resume` only when you want the client to immediately
invoke `scripts/a9_supervisor.py run-one`. Long-running unattended work should
still use the supervisor daemon or `run-loop --auto-next`.

Runtime files:

- `.a9/client/config.json`
- `.a9/client/latest`
- `.a9/client/sessions/<session_id>/session.json`
- `.a9/client/sessions/<session_id>/prompt.md`
