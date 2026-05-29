# A9 Production Services

The first deployable 24-hour runtime has three services:

```text
a9-control-api.service    stable ingress for phone/browser/Linux/WSL clients
a9-supervisor.service     guarded 24-hour executor that consumes queued tasks
a9-node-worker.service    Redis Stream node-command consumer for mobile/remote commands
```

The supervisor auto-next loop is:

```bash
scripts/a9_supervisor.py run-loop --auto-next --sleep-seconds 10 --keep-going-on-error
```

Systemd units:

```bash
scripts/a9_service.py unit
scripts/a9_service.py install-hint
```

Manual install hint prints both:

```text
infra/systemd/a9-supervisor.service
infra/systemd/a9-control-api.service
infra/systemd/a9-node-worker.service
```

The controller host should normally bind `a9-control-api` to Tailscale/WireGuard
or a private network address. Binding `0.0.0.0:8787` is acceptable only inside a
private network until auth is added.

Status:

```bash
scripts/a9_service.py readiness
scripts/a9_service.py status
scripts/a9_service.py ps
scripts/a9_supervisor.py status
```

`readiness` is the main monitor gate before unattended runs. It reports one of:

- `not_ready`: blockers exist; do not start automation.
- `bounded_ready`: run one bounded task first, for example
  `scripts/a9_supervisor.py run-loop --auto-next --max-tasks 1`.
- `daemon_ready`: ready for a longer daemon trial.

Git metadata writability is reported separately. A9 can execute and record
evidence in `.a9/` with read-only git metadata, but commits and pushes require a
writable `.git`.

Nested Codex workers run with a writable ignored home:

```text
CODEX_HOME=.a9/codex-home
HOME=.a9/codex-home
TMPDIR=.a9/tmp
```

The supervisor copies `auth.json` and `config.toml` from the operator Codex home
when they are missing, then invokes `codex exec --json --ephemeral`. This avoids
the read-only app-server initialization failure seen when a worker inherits a
read-only `/root/.codex`.

Worker budget gates:

- `A9_WORKER_MAX_EVENTS` defaults to `80`.
- `A9_WORKER_MAX_EVENT_BYTES` defaults to `120000`.
- Nested `codex exec`, `a9_supervisor.py run-one`, and
  `a9_supervisor.py run-loop` commands are blocked from worker event streams.

If a budget trips, the supervisor kills the worker, records `budget_stopped`,
`budget_reason`, event counts, and classifies the run as
`retryable-worker-budget`. This was verified with `worker-budget-smoke`, where a
low event cap stopped a real worker after it began broad test discovery.

Stop controls:

```bash
scripts/a9_service.py stop --dry-run
scripts/a9_service.py stop
scripts/a9_service.py stop --all
```

`stop` defaults to supervisor run-loop processes. Use `--all` only when a direct
`codex exec --json` worker must also be terminated. This mirrors the Codex
`/ps` and `/stop` operator controls that prevent unattended token burn.

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

Multi-node direction:

- HTTP clients submit bounded tasks to the controller.
- The supervisor consumes local queue tasks today.
- Redis Streams are the hot node-command bus: mobile/API writes to `a9:tasks`;
  `a9-node-worker.service` runs `scripts/a9_node.py command-work-loop`, writes
  `node_command_result` events to `a9:events`, and ACKs only after result
  persistence.
- MySQL should keep canonical sessions, runs, evidence indexes, and governance
  decisions.
- Remote Linux/WSL workers should register/heartbeat through the controller or
  Redis, then claim tasks through consumer groups rather than sharing `.a9/`
  over the filesystem.

SSH bootstrap direction:

A9 should not require every remote machine to adapt manually. The operator
should provide an SSH target, normally reachable through Tailscale or another
private network, and the controller should prepare the node:

```bash
python3 scripts/a9_remote.py root@worker-host \
  --controller-url http://controller-tailscale-ip:8787 \
  plan

python3 scripts/a9_remote.py root@worker-host probe

python3 scripts/a9_remote.py root@worker-host \
  --controller-url http://controller-tailscale-ip:8787 \
  bootstrap --dry-run
```

`a9_remote.py` is the first bootstrap layer. It probes the node, clones/updates
the A9 repo, writes remote-node config, and sets up the contract for a future
worker daemon. The runtime path after bootstrap is still Redis/API, not SSH
polling. SSH is for installation, repair, and emergency control.

tmux is the first takeover surface:

```text
Tailscale/private network
  -> ssh root@node
  -> tmux new-session -Ad -s a9 -c ~/a9-worker
  -> tmux attach -t a9
```

This is simpler than copying OpenClaw Gateway/pairing for the current phase.
OpenClaw remains a mechanism reference for typed flows, approvals, policy, and
bounded command gates. It is not the current network transport.

Discovery-first direction:

The smoother flow is even simpler for the operator:

```text
1. Cloud/controller starts a9-control-api.service.
2. Local Linux/WSL machine runs a tiny helper with A9_CONTROLLER_URL.
3. Helper calls /api/discovery, then /api/nodes/register.
4. Controller sees the node and can SSH/bootstrap it when needed.
5. Runtime work moves to Redis Streams/API once worker claim is enabled.
```

Commands:

```bash
python3 scripts/a9_node.py --controller-url http://controller:8787 discover

python3 scripts/a9_node.py \
  --controller-url http://controller:8787 \
  --node-id local-wsl-1 \
  register --ssh-target user@tailscale-ip

python3 scripts/a9_node.py heartbeat --status online
```

The local helper is not the final worker. It is a discovery/register adapter so
other machines do not need to understand A9 internals before joining.
