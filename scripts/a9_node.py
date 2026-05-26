#!/usr/bin/env python3
"""Local A9 node helper.

This is the tiny agent a Linux/WSL machine runs to discover and register with an
A9 controller. The controller remains responsible for later bootstrap and
governance.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
NODE_CONFIG = ROOT / ".a9" / "node.json"


def command_path(name: str) -> str:
    proc = subprocess.run(["sh", "-lc", f"command -v {name} || true"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.stdout.strip()


def default_node_id() -> str:
    return f"{socket.gethostname()}-{os.getuid()}"


def node_payload(node_id: str, *, ssh_target: str = "") -> dict[str, Any]:
    return {
        "node_id": node_id,
        "host": socket.gethostname(),
        "user": os.environ.get("USER") or "",
        "kernel": platform.platform(),
        "ssh_target": ssh_target,
        "capabilities": {
            "git": command_path("git"),
            "python3": command_path("python3"),
            "docker": command_path("docker"),
            "redis_cli": command_path("redis-cli"),
            "systemctl": command_path("systemctl"),
            "codex": command_path("codex"),
        },
        "labels": ["linux-or-wsl"],
    }


def http_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: int = 10) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def save_config(payload: dict[str, Any]) -> None:
    NODE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    NODE_CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def discover(args: argparse.Namespace) -> int:
    try:
        payload = http_json("GET", f"{args.controller_url.rstrip('/')}/api/discovery", timeout=args.timeout)
    except URLError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def register(args: argparse.Namespace) -> int:
    base = args.controller_url.rstrip("/")
    node_id = args.node_id or default_node_id()
    payload = node_payload(node_id, ssh_target=args.ssh_target)
    discovery = http_json("GET", f"{base}/api/discovery", timeout=args.timeout)
    result = http_json("POST", f"{base}/api/nodes/register", payload, timeout=args.timeout)
    save_config({"controller_url": base, "node_id": node_id, "discovery": discovery, "registration": result})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def heartbeat(args: argparse.Namespace) -> int:
    config = json.loads(NODE_CONFIG.read_text(encoding="utf-8")) if NODE_CONFIG.exists() else {}
    base = (args.controller_url or config.get("controller_url") or "").rstrip("/")
    node_id = args.node_id or config.get("node_id") or default_node_id()
    if not base:
        raise SystemExit("controller url is required")
    result = http_json(
        "POST",
        f"{base}/api/nodes/heartbeat",
        {"node_id": node_id, "status": args.status, "message": args.message},
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 local node discovery/register helper")
    parser.add_argument("--controller-url", default=os.environ.get("A9_CONTROLLER_URL", "http://127.0.0.1:8787"))
    parser.add_argument("--node-id", default="")
    parser.add_argument("--timeout", type=int, default=10)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover")
    register_parser = sub.add_parser("register")
    register_parser.add_argument("--ssh-target", default="")
    heartbeat_parser = sub.add_parser("heartbeat")
    heartbeat_parser.add_argument("--status", default="online")
    heartbeat_parser.add_argument("--message", default="")
    args = parser.parse_args(argv)
    if args.command == "discover":
        return discover(args)
    if args.command == "register":
        return register(args)
    if args.command == "heartbeat":
        return heartbeat(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
