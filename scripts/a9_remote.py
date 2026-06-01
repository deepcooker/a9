#!/usr/bin/env python3
"""A9 remote-node bootstrap helper.

Remote machines should not adapt themselves to A9. The controller reaches them
over SSH, probes capabilities, and installs the worker runtime contract.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REMOTE_DIR = "~/a9-worker"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def quote(value: str) -> str:
    return shlex.quote(value)


def split_ssh_target(target: str) -> tuple[str, str]:
    raw = target.strip()
    if not raw:
        raise ValueError("ssh target is required")
    if raw.endswith("]") or ":" not in raw:
        return raw, ""
    before_colon, after_colon = raw.rsplit(":", 1)
    if after_colon.isdigit() and before_colon:
        return before_colon, after_colon
    return raw, ""


def ssh_base(target: str, *, connect_timeout: int = 10, identity_file: str = "") -> list[str]:
    ssh_target, port = split_ssh_target(target)
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if identity_file:
        cmd.extend(["-i", identity_file])
    if port:
        cmd.extend(["-p", port])
    cmd.append(ssh_target)
    return cmd


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)


def remote_probe_script() -> str:
    return r"""
set -eu
printf 'host=%s\n' "$(hostname 2>/dev/null || true)"
printf 'user=%s\n' "$(id -un 2>/dev/null || true)"
printf 'kernel=%s\n' "$(uname -sr 2>/dev/null || true)"
for bin in bash git python3 curl docker redis-cli systemctl tmux tailscale codex; do
  if command -v "$bin" >/dev/null 2>&1; then
    printf '%s=%s\n' "$bin" "$(command -v "$bin")"
  else
    printf '%s=\n' "$bin"
  fi
done
""".strip()


def parse_probe(text: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        payload[key.strip()] = value.strip()
    return payload


def classify_probe_result(return_code: int, output: dict[str, str]) -> dict[str, Any]:
    required_tools = ("git", "python3", "curl")
    optional_tools = ("tmux", "tailscale")
    required_missing = [name for name in required_tools if not output.get(name, "").strip()]
    optional_missing = [name for name in optional_tools if not output.get(name, "").strip()]
    if return_code != 0:
        return {
            "probe_action": "retry",
            "probe_action_reason": "ssh_exec_error",
            "required_missing": required_missing,
            "optional_missing": optional_missing,
        }
    if required_missing:
        return {
            "probe_action": "repair",
            "probe_action_reason": "missing_required_tools",
            "required_missing": required_missing,
            "optional_missing": optional_missing,
        }
    if optional_missing:
        return {
            "probe_action": "continue",
            "probe_action_reason": "optional_tools_missing",
            "required_missing": required_missing,
            "optional_missing": optional_missing,
        }
    return {
        "probe_action": "continue",
        "probe_action_reason": "probe_ok",
        "required_missing": required_missing,
        "optional_missing": optional_missing,
    }


def summarize_node_connection_state(
    *,
    node_id: str,
    return_code: int,
    output: dict[str, str],
    attempt: int = 0,
    policy_budget_remaining: int = 3,
) -> dict[str, Any]:
    ssh_status = "connected" if return_code == 0 else "unreachable"
    required_missing = [name for name in ("git", "python3", "curl") if not output.get(name, "").strip()]
    optional_missing = [name for name in ("tmux", "tailscale") if not output.get(name, "").strip()]
    if return_code != 0:
        classification = classify_probe_result(return_code, output)
        decision = gateway_reconnect_decision(
            phase="connect",
            error_class=classification["probe_action_reason"],
            attempt=attempt,
            policy_budget_remaining=policy_budget_remaining,
            node_id=node_id,
            origin="probe",
        )
        return {
            "node_id": node_id,
            "ssh_status": ssh_status,
            "tailscale_status": "unknown",
            "tmux_status": "unknown",
            "connection_state": "disconnected",
            "action": decision["action"],
            "action_reason": classification["probe_action_reason"],
            "retry_delay_ms": decision["delay_ms"],
            "required_missing": required_missing,
            "optional_missing": optional_missing,
        }

    if required_missing:
        return {
            "node_id": node_id,
            "ssh_status": ssh_status,
            "tailscale_status": "present" if output.get("tailscale", "").strip() else "missing",
            "tmux_status": "present" if output.get("tmux", "").strip() else "missing",
            "connection_state": "needs_repair",
            "action": "repair",
            "action_reason": "missing_required_tools",
            "retry_delay_ms": 0,
            "required_missing": required_missing,
            "optional_missing": optional_missing,
        }

    if optional_missing:
        return {
            "node_id": node_id,
            "ssh_status": ssh_status,
            "tailscale_status": "present" if output.get("tailscale", "").strip() else "missing",
            "tmux_status": "present" if output.get("tmux", "").strip() else "missing",
            "connection_state": "degraded",
            "action": "continue",
            "action_reason": "optional_tools_missing",
            "retry_delay_ms": 0,
            "required_missing": required_missing,
            "optional_missing": optional_missing,
        }

    return {
        "node_id": node_id,
        "ssh_status": ssh_status,
        "tailscale_status": "present" if output.get("tailscale", "").strip() else "missing",
        "tmux_status": "present" if output.get("tmux", "").strip() else "missing",
        "connection_state": "connected",
        "action": "connected",
        "action_reason": "probe_ok",
        "retry_delay_ms": 0,
        "required_missing": required_missing,
        "optional_missing": optional_missing,
    }


def capped_reconnect_backoff_seconds(attempt: int, *, base_seconds: int = 1, cap_seconds: int = 30) -> int:
    safe_attempt = max(0, int(attempt))
    return min(cap_seconds, base_seconds * (2**safe_attempt))


def connect_error_action(error_kind: str) -> str:
    healthy = {"probe_ok", "optional_tools_missing"}
    reconnectable = {
        "ssh_exec_error",
        "ssh_connect_timeout",
        "ssh_connection_refused",
        "tailscale_down",
        "tmux_probe_timeout",
        "tmux_session_missing",
    }
    normalized = str(error_kind)
    if normalized in healthy:
        return "connected"
    return "reconnect" if normalized in reconnectable else "terminate"


def stream_error_action(error_kind: str) -> str:
    reconnectable = {"broken_pipe", "stream_io_error", "stream_timeout", "stream_reset"}
    nonfatal_continue = {"decode_error", "heartbeat_gap", "optional_event_parse_error"}
    normalized = str(error_kind)
    if normalized in reconnectable:
        return "reconnect"
    if normalized in nonfatal_continue:
        return "continue"
    return "reconnect"


def lifecycle_update(event: str, *, node_id: str = "", at: str = "", details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "event": event,
        "node_id": node_id,
        "at": at or utc_now(),
        "details": details or {},
    }


def gateway_reconnect_decision(
    *,
    phase: str,
    error_class: str = "",
    attempt: int = 0,
    node_id: str = "",
    origin: str = "gateway",
    policy_budget_remaining: int = 0,
    attempt_cap: int = 8,
    at: str = "",
) -> dict[str, Any]:
    normalized_phase = str(phase or "").strip() or "stream"
    normalized_error = str(error_class or "").strip()
    safe_attempt = max(0, int(attempt))
    safe_budget = max(0, int(policy_budget_remaining))
    safe_cap = max(0, int(attempt_cap))
    action = "terminate"
    kind = "error"
    delay_ms = 0

    if normalized_phase == "success":
        action = "connected"
        kind = "lifecycle"
        safe_attempt = 0
    elif safe_budget <= 0:
        action = "terminate"
    elif normalized_phase == "connect":
        action = connect_error_action(normalized_error)
    elif normalized_phase == "stream":
        action = stream_error_action(normalized_error)
    else:
        action = "terminate"

    if action == "reconnect":
        if safe_attempt >= safe_cap:
            action = "terminate"
        else:
            delay_ms = capped_reconnect_backoff_seconds(safe_attempt) * 1000
            safe_attempt += 1

    return {
        "kind": kind,
        "phase": normalized_phase,
        "action": action,
        "error_class": normalized_error,
        "attempt": safe_attempt,
        "delay_ms": delay_ms,
        "policy_budget_remaining": safe_budget,
        "node_id": node_id,
        "origin": origin,
        "ts": at or utc_now(),
    }


def build_bootstrap_script(args: argparse.Namespace) -> str:
    remote_dir = args.remote_dir
    repo = args.repo
    controller_url = args.controller_url
    worker_name = args.worker_name or "$(hostname)-a9-worker"
    heartbeat_script = heartbeat_loop_script(args)
    lines = [
        "set -eu",
        f"REMOTE_DIR={quote(remote_dir)}",
        f"REPO={quote(repo)}",
        f"CONTROLLER_URL={quote(controller_url)}",
        f"WORKER_NAME={quote(worker_name)}",
        'mkdir -p "$REMOTE_DIR"',
        'if [ ! -d "$REMOTE_DIR/.git" ]; then git clone "$REPO" "$REMOTE_DIR"; fi',
        'cd "$REMOTE_DIR"',
        "git pull --ff-only || true",
        "python3 -m compileall scripts >/dev/null",
        "mkdir -p .a9/remote-node",
        'cat > .a9/remote-node/config.json <<EOF',
        "{",
        '  "controller_url": "$CONTROLLER_URL",',
        '  "worker_name": "$WORKER_NAME",',
        '  "bootstrap_mode": "ssh_bootstrap_only",',
        '  "runtime_mode": "redis_api_runtime",',
        '  "remote_dir": "$REMOTE_DIR",',
        '  "heartbeat_script": ".a9/remote-node/heartbeat.sh",',
        '  "heartbeat_tmux_session": "a9-heartbeat",',
        '  "installed_at": "' + utc_now() + '"',
        "}",
        "EOF",
        "cat > .a9/remote-node/heartbeat.sh <<'EOF'",
        heartbeat_script,
        "EOF",
        "chmod +x .a9/remote-node/heartbeat.sh",
        'printf "A9 remote node prepared: %s -> %s\\n" "$WORKER_NAME" "$CONTROLLER_URL"',
    ]
    return "\n".join(lines)


def heartbeat_loop_script(args: argparse.Namespace) -> str:
    controller_url = args.controller_url
    worker_name = args.worker_name or "$(hostname)-a9-worker"
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            f"CONTROLLER_URL={quote(controller_url)}",
            f"WORKER_NAME={quote(worker_name)}",
            'NODE_ID="${WORKER_NAME}"',
            'HOSTNAME="$(hostname 2>/dev/null || true)"',
            'USERNAME="$(id -un 2>/dev/null || true)"',
            'if [ -z "$NODE_ID" ]; then',
            '  if [ -n "$HOSTNAME" ] && [ -n "$USERNAME" ]; then',
            '    NODE_ID="${HOSTNAME}-${USERNAME}"',
            "  elif [ -n \"$HOSTNAME\" ]; then",
            "    NODE_ID=\"$HOSTNAME\"",
            "  else",
            "    NODE_ID=unknown",
            "  fi",
            "fi",
            'HEARTBEAT_INTERVAL="${A9_HEARTBEAT_INTERVAL:-30}"',
            'if [ -z "$HEARTBEAT_INTERVAL" ]; then',
            '  HEARTBEAT_INTERVAL="30"',
            "fi",
            "send_once() {",
            "  STATUS=\"${A9_HEARTBEAT_STATUS:-online}\"",
            "  CURRENT_TASK=\"${A9_HEARTBEAT_CURRENT_TASK:-${CURRENT_TASK:-}}\"",
            "  MESSAGE=\"${A9_HEARTBEAT_MESSAGE:-${NODE_MESSAGE:-}}\"",
            "  LOAD=\"${A9_HEARTBEAT_LOAD:-$(cat /proc/loadavg 2>/dev/null | awk '{print $1\",\"$2\",\"$3}' || true)}\"",
            "  CAPABILITIES=\"${A9_HEARTBEAT_CAPABILITIES:-worker}\"",
            "  export NODE_ID STATUS CURRENT_TASK MESSAGE LOAD CAPABILITIES",
            "  PAYLOAD=$(python3 - <<'PY'",
            'import json, os',
            "print(json.dumps({",
            '    "node_id": os.environ.get("NODE_ID", "unknown"),',
            '    "status": os.environ.get("STATUS", "online"),',
            '    "current_task": os.environ.get("CURRENT_TASK", ""),',
            '    "message": os.environ.get("MESSAGE", ""),',
            '    "load": os.environ.get("LOAD", ""),',
            '    "capabilities": os.environ.get("CAPABILITIES", "worker"),',
            "}, separators=(\",\", \":\")))",
            "PY",
            "  )",
            "  if ! RESPONSE_CODE=$(curl -sS -o /dev/null -w \"%{http_code}\" -H \"Content-Type: application/json\" -d \"$PAYLOAD\" \"$CONTROLLER_URL/api/nodes/heartbeat\" 2>&1); then",
            '    >&2 printf "heartbeat failed node_id=%s error=%s\\n" "$NODE_ID" "$RESPONSE_CODE"',
            "  else",
            '    if [ "$RESPONSE_CODE" -lt 200 ] || [ "$RESPONSE_CODE" -ge 300 ]; then',
            '      >&2 printf "heartbeat non-2xx node_id=%s status=%s\\n" "$NODE_ID" "$RESPONSE_CODE"',
            "    fi",
            "  fi",
            "}",
            'if [ "${A9_HEARTBEAT_ONCE:-0}" = "1" ]; then',
            "  send_once",
            "  exit 0",
            "fi",
            'while :; do',
            "  send_once",
            '  sleep "$HEARTBEAT_INTERVAL"',
            "done",
            "",
        ]
    )


def plan(args: argparse.Namespace) -> int:
    payload = {
        "status": "planned",
        "target": args.target,
        "controller_url": args.controller_url,
        "repo": args.repo,
        "remote_dir": args.remote_dir,
        "worker_name": args.worker_name,
        "steps": [
            "ssh probe remote host",
            "ensure git/python3/curl are present",
            "clone or update A9 repo on remote host",
            "write remote-node config with controller URL",
            "install heartbeat loop script at .a9/remote-node/heartbeat.sh",
            "later supervise/start heartbeat script and worker daemon",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def probe(args: argparse.Namespace) -> int:
    cmd = ssh_base(args.target, connect_timeout=args.connect_timeout, identity_file=args.identity_file)
    proc = run([*cmd, remote_probe_script()])
    parsed_probe = parse_probe(proc.stdout)
    classification = classify_probe_result(proc.returncode, parsed_probe)
    connection_summary = summarize_node_connection_state(
        node_id=args.target,
        return_code=proc.returncode,
        output=parsed_probe,
    )
    payload: dict[str, Any] = {
        "checked_at": utc_now(),
        "target": args.target,
        "return_code": proc.returncode,
        "raw": proc.stdout,
        "probe": parsed_probe,
        "probe_action": classification["probe_action"],
        "probe_action_reason": classification["probe_action_reason"],
        "required_missing": classification["required_missing"],
        "optional_missing": classification["optional_missing"],
        "connection_summary": {
            "node_id": connection_summary["node_id"],
            "ssh_status": connection_summary["ssh_status"],
            "tailscale_status": connection_summary["tailscale_status"],
            "tmux_status": connection_summary["tmux_status"],
            "connection_state": connection_summary["connection_state"],
            "action": connection_summary["action"],
            "action_reason": connection_summary["action_reason"],
            "retry_delay_ms": connection_summary["retry_delay_ms"],
            "required_missing": connection_summary["required_missing"],
            "optional_missing": connection_summary["optional_missing"],
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if proc.returncode == 0 else proc.returncode


def bootstrap(args: argparse.Namespace) -> int:
    script = build_bootstrap_script(args)
    if args.dry_run:
        print(script)
        return 0
    cmd = ssh_base(args.target, connect_timeout=args.connect_timeout, identity_file=args.identity_file)
    proc = run([*cmd, script])
    print(proc.stdout, end="")
    return proc.returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 SSH remote-node bootstrap")
    parser.add_argument("target", help="SSH target, for example root@host or user@tailscale-ip")
    parser.add_argument("--controller-url", default="http://127.0.0.1:8787", help="A9 controller URL visible from the remote node")
    parser.add_argument("--repo", default="git@github.com:deepcooker/a9.git", help="A9 git repository URL for the remote node")
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR, help="remote install directory")
    parser.add_argument("--worker-name", default="", help="stable worker name; default is hostname-derived")
    parser.add_argument("--identity-file", default="", help="optional SSH private key")
    parser.add_argument("--connect-timeout", type=int, default=10)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    sub.add_parser("probe")
    bootstrap_parser = sub.add_parser("bootstrap")
    bootstrap_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "plan":
        return plan(args)
    if args.command == "probe":
        return probe(args)
    if args.command == "bootstrap":
        return bootstrap(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
