#!/usr/bin/env python3
"""A9 Codex supervisor MVP.

Runs queued markdown tasks through `codex exec --json`, stores traces, captures
git diffs, executes declared checks, and classifies the result without scraping
the interactive UI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".a9"
QUEUE_DIR = STATE_DIR / "tasks" / "queue"
RUNNING_DIR = STATE_DIR / "tasks" / "running"
DONE_DIR = STATE_DIR / "tasks" / "done"
RUNS_DIR = STATE_DIR / "runs"
WORKTREES_DIR = STATE_DIR / "worktrees"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return value.strip("-") or f"task-{int(time.time())}"


def run_cmd(
    args: list[str],
    *,
    cwd: Path = ROOT,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def ensure_dirs() -> None:
    for path in [QUEUE_DIR, RUNNING_DIR, DONE_DIR, RUNS_DIR, WORKTREES_DIR]:
        path.mkdir(parents=True, exist_ok=True)


@dataclass
class Task:
    path: Path
    task_id: str
    prompt: str
    timeout_seconds: int = 3600
    idle_timeout_seconds: int = 300
    max_attempts: int = 2
    checks: list[str] = field(default_factory=list)


def parse_task(path: Path) -> Task:
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, Any] = {}
    body = raw

    if raw.startswith("---\n"):
        end = raw.find("\n---\n", 4)
        if end != -1:
            meta_text = raw[4:end]
            body = raw[end + 5 :]
            current_list_key: str | None = None
            for line in meta_text.splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                if line.startswith("  - ") and current_list_key:
                    meta.setdefault(current_list_key, []).append(line[4:].strip().strip('"'))
                    continue
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                current_list_key = None
                if value == "":
                    meta[key] = []
                    current_list_key = key
                elif value.startswith("["):
                    meta[key] = json.loads(value)
                elif value.isdigit():
                    meta[key] = int(value)
                else:
                    meta[key] = value.strip('"')

    task_id = slugify(str(meta.get("id") or path.stem))
    checks = [str(item) for item in meta.get("checks", [])]
    return Task(
        path=path,
        task_id=task_id,
        prompt=body.strip(),
        timeout_seconds=int(meta.get("timeout_seconds", 3600)),
        idle_timeout_seconds=int(meta.get("idle_timeout_seconds", 300)),
        max_attempts=int(meta.get("max_attempts", 2)),
        checks=checks,
    )


def next_task() -> Task | None:
    tasks = sorted(QUEUE_DIR.glob("*.md"))
    return parse_task(tasks[0]) if tasks else None


def git_head() -> str:
    return run_cmd(["git", "rev-parse", "HEAD"]).stdout.strip()


def create_worktree(task: Task, attempt: int) -> Path:
    worktree = WORKTREES_DIR / f"{task.task_id}-attempt-{attempt}"
    branch = f"a9-supervisor/{task.task_id}-{attempt}"
    if worktree.exists():
        return worktree
    run_cmd(["git", "worktree", "add", "-B", branch, str(worktree), "HEAD"], capture=True)
    return worktree


def build_worker_cmd(task: Task, worktree: Path, run_dir: Path, final_path: Path) -> list[str]:
    override = os.getenv("A9_SUPERVISOR_WORKER_CMD")
    prompt_file = run_dir / "prompt.md"
    if override:
        formatted = (
            override.replace("{prompt_file}", shlex.quote(str(prompt_file)))
            .replace("{run_dir}", shlex.quote(str(run_dir)))
            .replace("{worktree}", shlex.quote(str(worktree)))
        )
        return ["bash", "-lc", formatted]
    return [
        "codex",
        "exec",
        "--json",
        "-C",
        str(worktree),
        "--output-last-message",
        str(final_path),
        task.prompt,
    ]


def classify_event(line: str) -> str | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    event_type = payload.get("type") or payload.get("event") or payload.get("msg", {}).get("type")
    return str(event_type) if event_type else None


def run_worker(task: Task, worktree: Path, run_dir: Path) -> dict[str, Any]:
    prompt_path = run_dir / "prompt.md"
    final_path = run_dir / "final.md"
    events_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    prompt_path.write_text(task.prompt + "\n", encoding="utf-8")

    cmd = build_worker_cmd(task, worktree, run_dir, final_path)
    started = time.monotonic()
    last_output = started
    event_counts: dict[str, int] = {}
    timed_out = False
    idle_timed_out = False

    with events_path.open("w", encoding="utf-8") as events, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr:
        proc = subprocess.Popen(
            cmd,
            cwd=worktree,
            text=True,
            stdout=subprocess.PIPE,
            stderr=stderr,
            bufsize=1,
        )
        assert proc.stdout is not None
        while True:
            now = time.monotonic()
            if now - started > task.timeout_seconds:
                timed_out = True
                proc.kill()
                break
            if now - last_output > task.idle_timeout_seconds:
                idle_timed_out = True
                proc.kill()
                break

            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if ready:
                line = proc.stdout.readline()
                if line:
                    last_output = time.monotonic()
                    events.write(line)
                    events.flush()
                    event_type = classify_event(line)
                    if event_type:
                        event_counts[event_type] = event_counts.get(event_type, 0) + 1
                elif proc.poll() is not None:
                    break
            elif proc.poll() is not None:
                break

        return_code = proc.wait()

    return {
        "command": cmd,
        "return_code": return_code,
        "timed_out": timed_out,
        "idle_timed_out": idle_timed_out,
        "event_counts": event_counts,
        "events_path": str(events_path),
        "stderr_path": str(stderr_path),
        "final_path": str(final_path),
    }


def capture_diff(worktree: Path, run_dir: Path) -> dict[str, Any]:
    run_cmd(["git", "add", "-A"], cwd=worktree)
    diff = run_cmd(["git", "diff", "--cached", "--binary"], cwd=worktree).stdout
    diff_path = run_dir / "patch.diff"
    diff_path.write_text(diff, encoding="utf-8", errors="backslashreplace")
    return {"diff_path": str(diff_path), "diff_bytes": len(diff.encode("utf-8"))}


def run_checks(task: Task, worktree: Path, run_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    checks_dir = run_dir / "checks"
    checks_dir.mkdir(exist_ok=True)
    for index, check_cmd in enumerate(task.checks, start=1):
        started = time.monotonic()
        proc = subprocess.run(
            ["bash", "-lc", check_cmd],
            cwd=worktree,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        output_path = checks_dir / f"{index:02d}.log"
        output_path.write_text(proc.stdout or "", encoding="utf-8", errors="backslashreplace")
        results.append(
            {
                "command": check_cmd,
                "return_code": proc.returncode,
                "duration_seconds": round(time.monotonic() - started, 3),
                "output_path": str(output_path),
            }
        )
    return results


def decide_status(worker: dict[str, Any], diff: dict[str, Any], checks: list[dict[str, Any]]) -> str:
    if worker["timed_out"] or worker["idle_timed_out"]:
        return "retryable-timeout"
    if worker["return_code"] != 0:
        return "retryable-worker-failed"
    failed_checks = [item for item in checks if item["return_code"] != 0]
    if failed_checks:
        return "needs-repair"
    if diff["diff_bytes"] == 0:
        return "needs-followup"
    return "pass"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_one() -> int:
    ensure_dirs()
    task = next_task()
    if not task:
        print("No queued tasks.")
        return 0

    attempt = 1
    while attempt <= task.max_attempts:
        run_id = f"{task.task_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-a{attempt}"
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True)
        worktree = create_worktree(task, attempt)
        lease = {
            "task_id": task.task_id,
            "attempt": attempt,
            "started_at": utc_now(),
            "run_dir": str(run_dir),
            "worktree": str(worktree),
            "repo_head": git_head(),
        }
        lease_path = RUNNING_DIR / f"{task.task_id}.json"
        write_json(lease_path, lease)

        worker = run_worker(task, worktree, run_dir)
        diff = capture_diff(worktree, run_dir)
        checks = run_checks(task, worktree, run_dir)
        status = decide_status(worker, diff, checks)
        summary = {
            **lease,
            "finished_at": utc_now(),
            "status": status,
            "task_path": str(task.path),
            "worker": worker,
            "diff": diff,
            "checks": checks,
        }
        write_json(run_dir / "summary.json", summary)

        retryable = status.startswith("retryable-")
        if retryable and attempt < task.max_attempts:
            attempt += 1
            continue

        done_path = DONE_DIR / f"{task.task_id}.json"
        write_json(done_path, summary)
        lease_path.unlink(missing_ok=True)
        target_task_path = DONE_DIR / task.path.name
        shutil.move(str(task.path), str(target_task_path))
        print(f"{task.task_id}: {status}")
        print(f"run: {run_dir}")
        return 0 if status in {"pass", "needs-followup", "needs-repair"} else 1

    return 1


def run_loop(args: argparse.Namespace) -> int:
    ensure_dirs()
    completed = 0
    while True:
        task = next_task()
        if not task:
            print("No queued tasks.")
            return 0
        code = run_one()
        completed += 1
        if code != 0 and not args.keep_going_on_error:
            return code
        if args.max_tasks and completed >= args.max_tasks:
            return code
        time.sleep(args.sleep_seconds)


def enqueue(args: argparse.Namespace) -> int:
    ensure_dirs()
    task_id = slugify(args.task_id)
    path = QUEUE_DIR / f"{task_id}.md"
    if path.exists():
        raise SystemExit(f"Task already exists: {path}")
    checks = "\n".join(f'  - "{item}"' for item in args.check)
    frontmatter = [
        "---",
        f'id: "{task_id}"',
        f"timeout_seconds: {args.timeout_seconds}",
        f"idle_timeout_seconds: {args.idle_timeout_seconds}",
        f"max_attempts: {args.max_attempts}",
        "checks:",
        checks,
        "---",
        "",
        args.prompt.strip(),
        "",
    ]
    path.write_text("\n".join(frontmatter), encoding="utf-8")
    print(path)
    return 0


def status() -> int:
    ensure_dirs()
    print(f"queued: {len(list(QUEUE_DIR.glob('*.md')))}")
    print(f"running: {len(list(RUNNING_DIR.glob('*.json')))}")
    print(f"done: {len(list(DONE_DIR.glob('*.json')))}")
    latest = sorted(RUNS_DIR.glob("*/summary.json"))
    if latest:
        data = json.loads(latest[-1].read_text(encoding="utf-8"))
        print(f"latest: {data['task_id']} {data['status']} {data['run_dir']}")
    return 0


def init() -> int:
    ensure_dirs()
    print(STATE_DIR)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 supervisor")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("run-one")
    sub.add_parser("status")

    loop_parser = sub.add_parser("run-loop")
    loop_parser.add_argument("--sleep-seconds", type=float, default=5.0)
    loop_parser.add_argument("--max-tasks", type=int, default=0)
    loop_parser.add_argument("--keep-going-on-error", action="store_true")

    enqueue_parser = sub.add_parser("enqueue")
    enqueue_parser.add_argument("task_id")
    enqueue_parser.add_argument("prompt")
    enqueue_parser.add_argument("--check", action="append", default=[])
    enqueue_parser.add_argument("--timeout-seconds", type=int, default=3600)
    enqueue_parser.add_argument("--idle-timeout-seconds", type=int, default=300)
    enqueue_parser.add_argument("--max-attempts", type=int, default=2)

    args = parser.parse_args(argv)
    if args.command == "init":
        return init()
    if args.command == "run-one":
        return run_one()
    if args.command == "run-loop":
        return run_loop(args)
    if args.command == "status":
        return status()
    if args.command == "enqueue":
        return enqueue(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
