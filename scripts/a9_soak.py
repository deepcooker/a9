#!/usr/bin/env python3
"""A9 unattended soak runner.

Runs a bounded copy-pipeline loop and writes a durable report. The default fake
worker exercises supervisor scheduling, worktrees, evidence, checks, progress,
and auto-next without spending model tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".a9"
SOAK_DIR = STATE_DIR / "soak"
REPORTS_DIR = SOAK_DIR / "reports"
PROGRESS_PATH = STATE_DIR / "progress.json"
HEARTBEAT_PATH = STATE_DIR / "daemon_heartbeat.json"
RUNS_DIR = STATE_DIR / "runs"
QUEUE_DIR = STATE_DIR / "tasks" / "queue"
SUPERVISOR = ROOT / "scripts" / "a9_supervisor.py"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"error": f"invalid json: {path}"}


def run_cmd(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def seed_prompt() -> str:
    return """Run one A9 copy-pipeline soak iteration.

Goal:
- Exercise the 24-hour automation loop, not domain business logic.
- Follow the copy pipeline: reference_scan, mechanism_extract, vendor_import,
  implement, test, record, repair.
- Keep changes bounded and testable.
- Record enough durable evidence for the next worker to continue.
"""


def fake_worker_cmd() -> str:
    return (
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "import json\n"
        "print(json.dumps({'type':'soak.start'}))\n"
        "print(json.dumps({'type':'thread.started','thread_id':'soak-thread'}))\n"
        "Path('soak-output.txt').write_text('soak pass\\n', encoding='utf-8')\n"
        "Path('{run_dir}/final.md').write_text('soak pass\\n', encoding='utf-8')\n"
        "print(json.dumps({'type':'item.completed','item':{'id':'soak-file','type':'file_change','changes':['soak-output.txt']}}))\n"
        "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}))\n"
        "PY"
    )


def enqueue_seed(task_id: str, phase: str) -> Path:
    result = run_cmd(
        [
            str(SUPERVISOR),
            "enqueue",
            task_id,
            seed_prompt(),
            "--phase",
            phase,
            "--check",
            "test -f soak-output.txt",
            "--timeout-seconds",
            "120",
            "--idle-timeout-seconds",
            "30",
            "--max-attempts",
            "1",
        ]
    )
    if result.returncode != 0:
        raise SystemExit(result.stdout)
    return Path(result.stdout.strip())


def latest_run_summaries(limit: int) -> list[dict[str, Any]]:
    summaries = sorted(RUNS_DIR.glob("*/summary.json"), key=lambda path: path.stat().st_mtime)
    out: list[dict[str, Any]] = []
    for path in summaries[-limit:]:
        data = read_json(path)
        guard_summary = {}
        for guard_name in ("patch_guard", "scope_guard"):
            guard = data.get(guard_name)
            if isinstance(guard, dict):
                touched_files = guard.get("touched_files", guard.get("changed_files", []))
                guard_summary[guard_name] = {
                    "status": guard.get("status"),
                    "kind": guard.get("kind"),
                    "touched_files": touched_files,
                    "findings_count": len(guard.get("findings", [])),
                    "output_path": guard.get("output_path"),
                }
        out.append(
            {
                "task_id": data.get("task_id"),
                "status": data.get("status"),
                "phase": data.get("task", {}).get("phase") or data.get("phase"),
                "run_dir": data.get("run_dir"),
                "guards": guard_summary,
                "checks": [
                    {
                        "command": item.get("command"),
                        "return_code": item.get("return_code"),
                    }
                    for item in data.get("checks", [])
                ],
            }
        )
    return out


def cleanup_next_tasks(task_id: str) -> list[str]:
    removed: list[str] = []
    for path in sorted(QUEUE_DIR.glob(f"auto-*-{task_id}-*.md")):
        removed.append(str(path))
        path.unlink(missing_ok=True)
    return removed


def refresh_progress_after_cleanup(cleaned_paths: list[str]) -> dict[str, Any]:
    progress = read_json(PROGRESS_PATH)
    if not progress:
        return progress
    progress["updated_at"] = utc_now()
    progress["queued_tasks"] = len(list(QUEUE_DIR.glob("*.md")))
    if progress.get("next_task_path") in cleaned_paths:
        progress["next_task_path"] = ""
        progress["auto_next_scheduled"] = False
    PROGRESS_PATH.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return progress


def refresh_heartbeat_after_cleanup() -> dict[str, Any]:
    heartbeat = read_json(HEARTBEAT_PATH)
    if not heartbeat:
        return heartbeat
    heartbeat["updated_at"] = utc_now()
    heartbeat["queued_tasks"] = len(list(QUEUE_DIR.glob("*.md")))
    heartbeat["running_tasks"] = len(list((STATE_DIR / "tasks" / "running").glob("*.json")))
    HEARTBEAT_PATH.write_text(json.dumps(heartbeat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return heartbeat


def write_report(payload: dict[str, Any]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"soak-{timestamp()}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = SOAK_DIR / "latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run_soak(args: argparse.Namespace) -> int:
    task_id = args.task_id or f"soak-copy-pipeline-{timestamp()}"
    seed_path = enqueue_seed(task_id, args.phase)
    env = os.environ.copy()
    if args.fake_worker:
        env["A9_SUPERVISOR_WORKER_CMD"] = fake_worker_cmd()
    started_at = utc_now()
    result = run_cmd(
        [
            str(SUPERVISOR),
            "run-loop",
            "--auto-next",
            "--keep-going-on-error",
            "--sleep-seconds",
            str(args.sleep_seconds),
            "--max-tasks",
            str(args.tasks),
        ],
        env=env,
    )
    finished_at = utc_now()
    queued_after_run = sorted(path.name for path in QUEUE_DIR.glob("*.md"))
    cleaned_next_tasks = [] if args.keep_next else cleanup_next_tasks(task_id)
    progress = refresh_progress_after_cleanup(cleaned_next_tasks) if cleaned_next_tasks else read_json(PROGRESS_PATH)
    heartbeat = refresh_heartbeat_after_cleanup() if cleaned_next_tasks else read_json(HEARTBEAT_PATH)
    queued = sorted(path.name for path in QUEUE_DIR.glob("*.md"))
    payload = {
        "started_at": started_at,
        "finished_at": finished_at,
        "task_id": task_id,
        "seed_path": str(seed_path),
        "tasks_requested": args.tasks,
        "fake_worker": args.fake_worker,
        "return_code": result.returncode,
        "stdout_tail": result.stdout.splitlines()[-80:],
        "queued_after_run": queued_after_run[-20:],
        "cleaned_next_tasks": cleaned_next_tasks,
        "progress": progress,
        "heartbeat": heartbeat,
        "queued_tail": queued[-20:],
        "latest_runs": latest_run_summaries(max(1, args.tasks)),
    }
    report_path = write_report(payload)
    print(json.dumps({"report_path": str(report_path), **payload}, ensure_ascii=False, indent=2))
    return result.returncode


def status(_: argparse.Namespace) -> int:
    print((SOAK_DIR / "latest.json").read_text(encoding="utf-8") if (SOAK_DIR / "latest.json").exists() else "{}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 unattended soak runner")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--tasks", type=int, default=1)
    run_parser.add_argument("--sleep-seconds", type=float, default=0.0)
    run_parser.add_argument("--task-id", default="")
    run_parser.add_argument("--phase", default="reference_scan")
    run_parser.add_argument("--fake-worker", action="store_true", default=True)
    run_parser.add_argument("--real-worker", action="store_false", dest="fake_worker")
    run_parser.add_argument("--keep-next", action="store_true")

    sub.add_parser("status")
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_soak(args)
    if args.command == "status":
        return status(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
