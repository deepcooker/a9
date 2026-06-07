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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".a9"
SERVICE_PID_DIR = STATE_DIR / "services"
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
SERVICE_COMMANDS = {
    "supervisor": [
        "bash",
        "-lc",
        "cd /root/a9 && while true; do A9_IDLE_GOAL_CONTINUATION=1 python3 scripts/a9_supervisor.py run-loop --auto-next --sleep-seconds 10 --keep-going-on-error; sleep 15; done",
    ],
    "control-api": [
        "bash",
        "-lc",
        "cd /root/a9 && exec python3 scripts/a9_control_api.py serve --host 0.0.0.0 --port 8787 >> .a9/control-api.log 2>&1",
    ],
    "node-worker": [
        "bash",
        "-lc",
        "cd /root/a9 && exec python3 scripts/a9_node.py command-work-loop --block-ms 5000 --timeout 10 --sleep-seconds 1 --min-idle-ms 30000 >> .a9/node-worker.log 2>&1",
    ],
    "recovery-loop": [
        "bash",
        "-lc",
        "cd /root/a9 && exec python3 scripts/a9_recovery_loop.py --controller-url http://127.0.0.1:8787 --interval-seconds 60 --timeout 10 --max-actions 3 >> .a9/recovery-loop.log 2>&1",
    ],
}
SERVICE_START_ORDER = ["control-api", "node-worker", "recovery-loop", "supervisor"]
SERVICE_RESTART_DEFAULT = ["control-api", "node-worker", "recovery-loop"]
START_VERIFY_ATTEMPTS = 5
START_VERIFY_SLEEP_SECONDS = 0.2
START_VERIFY_TIMEOUT_SECONDS = START_VERIFY_ATTEMPTS * START_VERIFY_SLEEP_SECONDS


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
        if "setsid -f bash -lc" in cmd:
            continue
        processes.append({"pid": pid, "ppid": ppid, "etime": etime, "kind": kind, "cmd": cmd})
    return processes


def running_processes() -> list[dict[str, Any]]:
    proc = run(["ps", "-eo", "pid,ppid,etime,cmd"])
    return parse_process_table(proc.stdout)


def service_pid_path(kind: str) -> Path:
    return SERVICE_PID_DIR / f"{kind}.pid"


def observed_pid_for_kind(kind: str, processes: list[dict[str, Any]] | None = None) -> tuple[int | None, int]:
    if processes is None:
        processes = running_processes()
    matching = [item for item in processes if item.get("kind") == kind]
    if not matching:
        return None, 0
    # Deterministic selection across multiple matches: prefer largest pid, then ppid, then command.
    primary = sorted(matching, key=lambda item: (int(item["pid"]), int(item.get("ppid", 0)), str(item.get("cmd", ""))))[-1]
    return int(primary["pid"]), len(matching)


def refresh_service_pidfile(kind: str, processes: list[dict[str, Any]]) -> tuple[int | None, int]:
    pid, count = observed_pid_for_kind(kind, processes)
    if pid is not None:
        path = service_pid_path(kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{pid}\n", encoding="utf-8")
    return pid, count


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


def start_failure_to_action(failure_kind: str) -> str:
    mapping = {
        "timeout": "retry",
        "auth": "repair",
        "network": "retry",
        "protocol": "repair",
        "rate_limit": "quarantine",
    }
    return mapping.get(failure_kind, "repair")


def verify_started_kind(kind: str) -> tuple[bool, int, int]:
    started_at = time.monotonic()
    for attempt in range(1, START_VERIFY_ATTEMPTS + 1):
        current = running_processes()
        if any(item["kind"] == kind for item in current):
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            return True, attempt, elapsed_ms
        if attempt < START_VERIFY_ATTEMPTS:
            time.sleep(START_VERIFY_SLEEP_SECONDS)
    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    return False, START_VERIFY_ATTEMPTS, elapsed_ms


def collect_start_payload(requested: list[str], dry_run: bool, running_processes_snapshot: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    current = running_processes_snapshot if running_processes_snapshot is not None else running_processes()
    running_kinds = {item["kind"] for item in current if item["kind"] in SERVICE_COMMANDS}
    results: list[dict[str, Any]] = []
    for kind in requested:
        command = SERVICE_COMMANDS[kind]
        result = {
            "kind": kind,
            "status": "already_running" if kind in running_kinds else "planned" if dry_run else "started",
            "command": ["setsid", "-f", *command],
            "pid": None,
            "observed_process_count": 0,
        }
        if kind not in running_kinds and not dry_run:
            proc = subprocess.Popen(
                ["setsid", "-f", *command],
                cwd=ROOT,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            result["pid"] = proc.pid
            observed_running, attempts_used, observed_after_ms = verify_started_kind(kind)
            if observed_running:
                observed_pid, observed_count = refresh_service_pidfile(kind, running_processes())
                if observed_pid is not None:
                    result["pid"] = observed_pid
                result["observed_process_count"] = observed_count
                result["command_status"] = {
                    "phase": "running",
                    "observed_running": True,
                    "verify_attempts_used": attempts_used,
                    "observed_after_ms": observed_after_ms,
                    "failure_kind": "",
                    "recovery_action": "",
                }
            else:
                result["observed_process_count"] = 0
                result["command_status"] = {
                    "phase": "start_timeout",
                    "observed_running": False,
                    "verify_attempts_used": attempts_used,
                    "observed_after_ms": observed_after_ms,
                    "failure_kind": "timeout",
                    "recovery_action": start_failure_to_action("timeout"),
                }
        elif kind in running_kinds:
            observed_pid, observed_count = refresh_service_pidfile(kind, current)
            result["pid"] = observed_pid
            result["observed_process_count"] = observed_count
            result["command_status"] = {
                "phase": "already_running",
                "observed_running": True,
                "verify_attempts_used": 0,
                "observed_after_ms": 0,
                "failure_kind": "",
                "recovery_action": "",
            }
        else:
            # Dry-run and planned services must not mutate pidfiles.
            result["observed_process_count"] = 0
            result["command_status"] = {
                "phase": "planned",
                "observed_running": False,
                "verify_attempts_used": 0,
                "observed_after_ms": 0,
                "failure_kind": "",
                "recovery_action": "",
            }
        results.append(result)
    return {
        "checked_at": iso_now(),
        "dry_run": dry_run,
        "requested": requested,
        "start_contract": {
            "verify_attempt_budget": START_VERIFY_ATTEMPTS,
            "verify_sleep_seconds": START_VERIFY_SLEEP_SECONDS,
            "verify_timeout_seconds": START_VERIFY_TIMEOUT_SECONDS,
            "failure_taxonomy": ["timeout", "auth", "network", "protocol", "rate_limit"],
        },
        "started": results,
    }


def start_cmd(args: argparse.Namespace) -> int:
    requested = list(SERVICE_START_ORDER if args.all else args.only)
    payload = collect_start_payload(requested=requested, dry_run=args.dry_run)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def collect_stop_payload(requested: list[str], dry_run: bool, target_mode: str, processes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    current = running_processes() if processes is None else processes
    if target_mode == "all":
        targets = list(current)
        requested_kinds = ["all"]
    else:
        requested_kinds = list(requested)
        targets = [item for item in current if item["kind"] in requested_kinds]

    stopped: list[dict[str, Any]] = []
    stopped_kinds: dict[str, set[int]] = {}
    for item in targets:
        result = {**item, "signal": "SIGTERM", "stopped": False, "error": ""}
        if dry_run:
            result["stopped"] = False
        else:
            try:
                os.kill(int(item["pid"]), signal.SIGTERM)
                result["stopped"] = True
                if item["kind"] in SERVICE_COMMANDS:
                    stopped_kinds.setdefault(item["kind"], set()).add(int(item["pid"]))
            except ProcessLookupError:
                result["error"] = "process not found"
            except PermissionError:
                result["error"] = "permission denied"
        stopped.append(result)

    pidfiles_removed: list[str] = []
    if not dry_run and stopped_kinds:
        post_stop_processes = running_processes()
        post_stop_kinds = {item["kind"] for item in post_stop_processes}
        for kind in sorted(stopped_kinds):
            if kind not in SERVICE_COMMANDS:
                continue
            path = service_pid_path(kind)
            if not path.exists():
                continue
            remove_pidfile = False
            try:
                observed_pid = int(path.read_text(encoding="utf-8").strip())
                if observed_pid in stopped_kinds[kind]:
                    remove_pidfile = True
            except (OSError, ValueError):
                remove_pidfile = True
            if not remove_pidfile and kind not in post_stop_kinds:
                remove_pidfile = True
            if remove_pidfile:
                path.unlink(missing_ok=True)
                pidfiles_removed.append(str(path))

    return {
        "checked_at": iso_now(),
        "dry_run": dry_run,
        "target_mode": target_mode,
        "requested": requested_kinds,
        "matched": len(targets),
        "stopped": stopped,
        "pidfiles_removed": pidfiles_removed,
    }


def stop_cmd(args: argparse.Namespace) -> int:
    processes = running_processes()
    if args.all:
        requested_kinds: list[str] = ["all"]
        target_mode = "all"
    else:
        requested_kinds = list(args.only or ["supervisor"])
        target_mode = "only" if args.only else "default"
    payload = collect_stop_payload(requested=requested_kinds, dry_run=args.dry_run, target_mode=target_mode, processes=processes)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not any(item.get("error") for item in payload["stopped"]) else 1


def restart_cmd(args: argparse.Namespace) -> int:
    if args.all:
        requested = list(SERVICE_START_ORDER)
        stop_target_mode = "all"
    else:
        requested = list(args.only or SERVICE_RESTART_DEFAULT)
        stop_target_mode = "only" if args.only else "default"

    stop_payload = collect_stop_payload(
        requested=requested,
        dry_run=args.dry_run,
        target_mode=stop_target_mode,
    )
    start_payload = collect_start_payload(requested=requested, dry_run=args.dry_run)

    stop_failed = any(item.get("error") for item in stop_payload["stopped"])
    start_failed = any(item.get("command_status", {}).get("failure_kind") for item in start_payload["started"])
    payload = {
        "kind": "service_restart",
        "checked_at": iso_now(),
        "dry_run": args.dry_run,
        "requested": requested,
        "stop": stop_payload,
        "start": start_payload,
        "status": "partial" if (stop_failed or start_failed) else "ok",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if (stop_failed or start_failed) else 0


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
    start_parser = sub.add_parser("start")
    start_parser.add_argument("--all", action="store_true", help="start the local A9 service set")
    start_parser.add_argument(
        "--only",
        nargs="+",
        choices=SERVICE_START_ORDER,
        default=SERVICE_RESTART_DEFAULT,
        help="service kinds to start when --all is not set",
    )
    start_parser.add_argument("--dry-run", action="store_true", help="show start commands without launching them")
    stop_parser = sub.add_parser("stop")
    stop_parser.add_argument("--all", action="store_true", help="also stop direct codex worker children")
    stop_parser.add_argument(
        "--only",
        nargs="+",
        choices=SERVICE_START_ORDER,
        help="stop running services matching these kinds when --all is not set",
    )
    stop_parser.add_argument("--dry-run", action="store_true", help="show matched processes without signaling them")
    restart_parser = sub.add_parser("restart")
    restart_parser.add_argument("--all", action="store_true", help="restart the local A9 service set")
    restart_parser.add_argument(
        "--only",
        nargs="+",
        choices=SERVICE_START_ORDER,
        help="restart only these service kinds when --all is not set",
    )
    restart_parser.add_argument("--dry-run", action="store_true", help="show planned restart without signaling processes")
    sub.add_parser("unit")
    sub.add_parser("install-hint")
    args = parser.parse_args(argv)
    if args.command == "status":
        return status(args)
    if args.command == "readiness":
        return readiness(args)
    if args.command == "ps":
        return ps_cmd(args)
    if args.command == "start":
        return start_cmd(args)
    if args.command == "stop":
        return stop_cmd(args)
    if args.command == "restart":
        return restart_cmd(args)
    if args.command == "unit":
        return print_unit(args)
    if args.command == "install-hint":
        return install_hint(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
