#!/usr/bin/env python3
"""A9 supervisor service helper.

This is the deployment-facing wrapper for the 24-hour supervisor loop. It keeps
systemd instructions, status inspection, and local service paths in one place.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".a9"
PROGRESS_PATH = STATE_DIR / "progress.json"
HEARTBEAT_PATH = STATE_DIR / "daemon_heartbeat.json"
SUPERVISOR_UNIT_PATH = ROOT / "infra" / "systemd" / "a9-supervisor.service"
CONTROL_API_UNIT_PATH = ROOT / "infra" / "systemd" / "a9-control-api.service"
NODE_WORKER_UNIT_PATH = ROOT / "infra" / "systemd" / "a9-node-worker.service"
RECOVERY_LOOP_UNIT_PATH = ROOT / "infra" / "systemd" / "a9-recovery-loop.service"
PROCESS_MARKERS = {
    "supervisor": "a9_supervisor.py run-loop",
    "control-api": "a9_control_api.py serve",
    "node-worker": "a9_node.py command-work-loop",
    "recovery-loop": "a9_recovery_loop.py",
    "worker": "codex exec --json",
}


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


def parse_process_table(text: str) -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 3)
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        ppid = int(parts[1]) if parts[1].isdigit() else 0
        etime = parts[2]
        cmd = parts[3]
        if "codex-linux-sandbox" in cmd or cmd.startswith("bwrap "):
            continue
        kind = ""
        for name, marker in PROCESS_MARKERS.items():
            if marker in cmd:
                kind = name
                break
        if not kind:
            continue
        if "rg 'a9_supervisor.py run-loop|codex exec --json'" in cmd:
            continue
        processes.append({"pid": pid, "ppid": ppid, "etime": etime, "kind": kind, "cmd": cmd})
    return processes


def running_processes() -> list[dict[str, Any]]:
    proc = run(["ps", "-eo", "pid,ppid,etime,cmd"])
    return parse_process_table(proc.stdout)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def unit_text() -> str:
    return "\n\n".join(
        [
            SUPERVISOR_UNIT_PATH.read_text(encoding="utf-8"),
            CONTROL_API_UNIT_PATH.read_text(encoding="utf-8"),
            NODE_WORKER_UNIT_PATH.read_text(encoding="utf-8"),
            RECOVERY_LOOP_UNIT_PATH.read_text(encoding="utf-8"),
        ]
    )


def status(_: argparse.Namespace) -> int:
    progress = read_json(PROGRESS_PATH)
    heartbeat = read_json(HEARTBEAT_PATH)
    middleware = run([str(ROOT / "scripts" / "a9_middleware.py"), "status"])
    supervisor_status = run([str(ROOT / "scripts" / "a9_supervisor.py"), "status"])
    payload = {
        "checked_at": iso_now(),
        "service": "a9-supervisor",
        "unit_paths": {
            "supervisor": str(SUPERVISOR_UNIT_PATH),
            "control_api": str(CONTROL_API_UNIT_PATH),
            "node_worker": str(NODE_WORKER_UNIT_PATH),
            "recovery_loop": str(RECOVERY_LOOP_UNIT_PATH),
        },
        "progress": progress,
        "heartbeat": heartbeat,
        "processes": running_processes(),
        "middleware_status": middleware.stdout.strip().splitlines()[-20:],
        "supervisor_status": supervisor_status.stdout.strip().splitlines()[-20:],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if middleware.returncode == 0 and supervisor_status.returncode == 0 else 1


def git_writable() -> dict[str, Any]:
    probe = ROOT / ".git" / ".a9-write-probe"
    try:
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return {"status": "pass", "writable": True, "path": str(ROOT / ".git")}
    except OSError as exc:
        return {"status": "fail", "writable": False, "path": str(ROOT / ".git"), "error": str(exc)}


def readiness(_: argparse.Namespace) -> int:
    progress = read_json(PROGRESS_PATH)
    heartbeat = read_json(HEARTBEAT_PATH)
    processes = running_processes()
    middleware = run([str(ROOT / "scripts" / "a9_middleware.py"), "status"])
    supervisor_status = run([str(ROOT / "scripts" / "a9_supervisor.py"), "status"])
    git_probe = git_writable()
    groups = progress.get("capability_groups", {})
    group_percents = {name: item.get("percent", 0) for name, item in groups.items()}
    blockers: list[str] = []
    warnings: list[str] = []
    if middleware.returncode != 0:
        blockers.append("middleware status failed")
    if supervisor_status.returncode != 0:
        blockers.append("supervisor status failed")
    if progress.get("progress_percent", 0) < 100:
        blockers.append("capability progress is below 100%")
    if any(value < 100 for value in group_percents.values()):
        blockers.append("one or more capability groups are below 100%")
    if any(item["kind"] == "worker" for item in processes):
        blockers.append("worker process is already running")
    if any(item["kind"] == "supervisor" for item in processes):
        warnings.append("supervisor run-loop is already running")
    if not git_probe["writable"]:
        warnings.append("git metadata is not writable; code can run but commits/pushes need a writable git environment")
    if progress.get("queued_tasks", 0) == 0:
        warnings.append("no queued tasks")

    if blockers:
        mode = "not_ready"
        recommendation = "Fix blockers before running automation."
    elif warnings:
        mode = "bounded_ready"
        recommendation = "Run bounded automation first, for example: scripts/a9_supervisor.py run-loop --auto-next --max-tasks 1"
    else:
        mode = "daemon_ready"
        recommendation = "Ready for daemon trial: scripts/a9_supervisor.py run-loop --auto-next --sleep-seconds 10 --keep-going-on-error"

    payload = {
        "checked_at": iso_now(),
        "service": "a9-24h-automation",
        "mode": mode,
        "blockers": blockers,
        "warnings": warnings,
        "recommendation": recommendation,
        "progress_percent": progress.get("progress_percent"),
        "capability_groups": group_percents,
        "queued_tasks": progress.get("queued_tasks"),
        "running_tasks": progress.get("running_tasks"),
        "done_tasks": progress.get("done_tasks"),
        "heartbeat_state": heartbeat.get("state", ""),
        "processes": processes,
        "git": git_probe,
        "middleware_return_code": middleware.returncode,
        "supervisor_return_code": supervisor_status.returncode,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if mode in {"bounded_ready", "daemon_ready"} else 1


def ps_cmd(_: argparse.Namespace) -> int:
    payload = {"checked_at": iso_now(), "processes": running_processes()}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def stop_cmd(args: argparse.Namespace) -> int:
    processes = running_processes()
    targets = [item for item in processes if args.all or item["kind"] == "supervisor"]
    stopped: list[dict[str, Any]] = []
    for item in targets:
        result = {**item, "signal": "SIGTERM", "stopped": False, "error": ""}
        if args.dry_run:
            result["stopped"] = False
        else:
            try:
                os.kill(int(item["pid"]), signal.SIGTERM)
                result["stopped"] = True
            except ProcessLookupError:
                result["error"] = "process not found"
            except PermissionError:
                result["error"] = "permission denied"
        stopped.append(result)
    payload = {
        "checked_at": iso_now(),
        "dry_run": args.dry_run,
        "target": "all" if args.all else "supervisor",
        "matched": len(targets),
        "stopped": stopped,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not any(item.get("error") for item in stopped) else 1


def print_unit(_: argparse.Namespace) -> int:
    print(unit_text(), end="")
    return 0


def install_hint(_: argparse.Namespace) -> int:
    print(
        "\n".join(
            [
                "sudo cp infra/systemd/a9-supervisor.service /etc/systemd/system/a9-supervisor.service",
                "sudo cp infra/systemd/a9-control-api.service /etc/systemd/system/a9-control-api.service",
                "sudo cp infra/systemd/a9-node-worker.service /etc/systemd/system/a9-node-worker.service",
                "sudo cp infra/systemd/a9-recovery-loop.service /etc/systemd/system/a9-recovery-loop.service",
                "sudo systemctl daemon-reload",
                "sudo systemctl enable --now a9-supervisor",
                "sudo systemctl enable --now a9-control-api",
                "sudo systemctl enable --now a9-node-worker",
                "sudo systemctl enable --now a9-recovery-loop",
                "sudo systemctl status a9-supervisor",
                "sudo systemctl status a9-control-api",
                "sudo systemctl status a9-node-worker",
                "sudo systemctl status a9-recovery-loop",
                "journalctl -u a9-supervisor -f",
                "journalctl -u a9-control-api -f",
                "journalctl -u a9-node-worker -f",
                "journalctl -u a9-recovery-loop -f",
            ]
        )
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 service helper")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("readiness")
    sub.add_parser("ps")
    stop_parser = sub.add_parser("stop")
    stop_parser.add_argument("--all", action="store_true", help="also stop direct codex worker children")
    stop_parser.add_argument("--dry-run", action="store_true", help="show matched processes without signaling them")
    sub.add_parser("unit")
    sub.add_parser("install-hint")
    args = parser.parse_args(argv)
    if args.command == "status":
        return status(args)
    if args.command == "readiness":
        return readiness(args)
    if args.command == "ps":
        return ps_cmd(args)
    if args.command == "stop":
        return stop_cmd(args)
    if args.command == "unit":
        return print_unit(args)
    if args.command == "install-hint":
        return install_hint(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
