#!/usr/bin/env python3
"""A9 supervisor service helper.

This is the deployment-facing wrapper for the 24-hour supervisor loop. It keeps
systemd instructions, status inspection, and local service paths in one place.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".a9"
PROGRESS_PATH = STATE_DIR / "progress.json"
HEARTBEAT_PATH = STATE_DIR / "daemon_heartbeat.json"
UNIT_PATH = ROOT / "infra" / "systemd" / "a9-supervisor.service"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"error": f"invalid json: {path}"}


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def unit_text() -> str:
    return UNIT_PATH.read_text(encoding="utf-8")


def status(_: argparse.Namespace) -> int:
    progress = read_json(PROGRESS_PATH)
    heartbeat = read_json(HEARTBEAT_PATH)
    middleware = run([str(ROOT / "scripts" / "a9_middleware.py"), "status"])
    supervisor_status = run([str(ROOT / "scripts" / "a9_supervisor.py"), "status"])
    payload = {
        "checked_at": iso_now(),
        "service": "a9-supervisor",
        "unit_path": str(UNIT_PATH),
        "progress": progress,
        "heartbeat": heartbeat,
        "middleware_status": middleware.stdout.strip().splitlines()[-20:],
        "supervisor_status": supervisor_status.stdout.strip().splitlines()[-20:],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if middleware.returncode == 0 and supervisor_status.returncode == 0 else 1


def print_unit(_: argparse.Namespace) -> int:
    print(unit_text(), end="")
    return 0


def install_hint(_: argparse.Namespace) -> int:
    print(
        "\n".join(
            [
                "sudo cp infra/systemd/a9-supervisor.service /etc/systemd/system/a9-supervisor.service",
                "sudo systemctl daemon-reload",
                "sudo systemctl enable --now a9-supervisor",
                "sudo systemctl status a9-supervisor",
                "journalctl -u a9-supervisor -f",
            ]
        )
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 service helper")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("unit")
    sub.add_parser("install-hint")
    args = parser.parse_args(argv)
    if args.command == "status":
        return status(args)
    if args.command == "unit":
        return print_unit(args)
    if args.command == "install-hint":
        return install_hint(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
