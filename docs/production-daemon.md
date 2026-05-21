# A9 Production Daemon

The first deployable 24-hour service is the supervisor auto-next loop:

```bash
scripts/a9_supervisor.py run-loop --auto-next --sleep-seconds 10 --keep-going-on-error
```

Systemd unit:

```bash
scripts/a9_service.py unit
scripts/a9_service.py install-hint
```

Status:

```bash
scripts/a9_service.py status
scripts/a9_supervisor.py status
```

Bounded soak test:

```bash
scripts/a9_soak.py run --tasks 1 --fake-worker
scripts/a9_soak.py status
```

`a9_soak.py` defaults to the fake worker to avoid model-token spend. Use
`--real-worker` only when deliberately testing the configured worker command.

Runtime files:

- `.a9/progress.json`: durable 24-hour capability progress.
- `.a9/daemon_heartbeat.json`: run-loop heartbeat and queue counts.
- `.a9/tasks/queue`: queued work.
- `.a9/tasks/running`: leased work.
- `.a9/tasks/done`: completed work and rolling contexts.
- `.a9/runs`: per-run evidence, event streams, diffs, checks, and state.
- `.a9/soak/latest.json`: latest bounded unattended soak report.

The service copies mature daemon patterns conservatively: systemd restart
policy, middleware health preflight, journal logs, explicit heartbeat, and a
separate status helper. Raw evidence remains on disk and canonical state remains
in MySQL/Redis.
