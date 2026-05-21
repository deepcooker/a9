# a9

A9 is a private 24-hour agent service that copies mature open-source agent
mechanisms, adapts them locally, tests them, and records durable evidence.

Useful entry points:

```bash
scripts/a9_supervisor.py status
scripts/a9_soak.py run --tasks 1 --fake-worker
cargo run -p a9-client -- config
```
