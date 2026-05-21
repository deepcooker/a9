# A9 Native Rust Worker

`crates/a9-worker` is the first Rust execution layer for the 24-hour service.
It does not replace the Python supervisor yet. It wraps the queue boundary that
must stay fast and stable in production.

Copied shape:

- Redis Streams consumer group lease.
- Worker lifecycle heartbeat.
- Bounded command execution.
- Started/completed/failed events.
- Ack after terminal outcome.

Run one leased stream task:

```bash
cargo run -p a9-worker -- run-once \
  --worker-id a9-rust-worker-1 \
  --command 'python3 scripts/a9_supervisor.py run-one --auto-next' \
  --block-ms 1000 \
  --timeout-seconds 3600
```

Task fields are passed to the command through environment variables:

- `A9_STREAM_ID`
- `A9_TASK_ID`
- `A9_PROMPT`

The default Redis address is `127.0.0.1:63799`; override with
`A9_REDIS_ADDR`.
