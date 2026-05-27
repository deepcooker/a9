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


def build_bootstrap_script(args: argparse.Namespace) -> str:
    remote_dir = args.remote_dir
    repo = args.repo
    controller_url = args.controller_url
    worker_name = args.worker_name or "$(hostname)-a9-worker"
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
        '  "installed_at": "' + utc_now() + '"',
        "}",
        "EOF",
        'printf "A9 remote node prepared: %s -> %s\\n" "$WORKER_NAME" "$CONTROLLER_URL"',
    ]
    return "\n".join(lines)


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
            "later install worker daemon and Redis Streams consumer",
            "later register heartbeat back to controller",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def probe(args: argparse.Namespace) -> int:
    cmd = ssh_base(args.target, connect_timeout=args.connect_timeout, identity_file=args.identity_file)
    proc = run([*cmd, remote_probe_script()])
    parsed_probe = parse_probe(proc.stdout)
    classification = classify_probe_result(proc.returncode, parsed_probe)
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
