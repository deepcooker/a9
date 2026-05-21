#!/usr/bin/env python3
"""A9 page/TUI monitor.

First-layer live continuity monitor. It watches an exported transcript file,
detects idle/stopped state by content hash age, writes a durable state snapshot,
and can hand off a continuation task to the supervisor queue.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".a9" / "page_monitor"
STATE_PATH = STATE_DIR / "state.json"
SNAPSHOT_PATH = STATE_DIR / "latest_snapshot.md"
CONTINUATION_PATH = STATE_DIR / "continuation_prompt.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_now(value: str | None) -> tuple[float, str]:
    if not value:
        now = datetime.now(timezone.utc)
        return now.timestamp(), now.isoformat(timespec="seconds")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.timestamp(), parsed.isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="backslashreplace")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_transcript(path: Path, tail_chars: int) -> str:
    if not path.exists():
        raise SystemExit(f"transcript does not exist: {path}")
    text = path.read_text(encoding="utf-8", errors="backslashreplace")
    if tail_chars > 0 and len(text) > tail_chars:
        return text[-tail_chars:]
    return text


def classify_transcript(text: str) -> str:
    lowered = text.lower()
    stopped_markers = [
        "task complete",
        "completed",
        "done",
        "需要人工",
        "等待",
        "stopped",
        "finished",
    ]
    if any(marker in lowered for marker in stopped_markers):
        return "possibly_stopped"
    if any(marker in lowered for marker in ["running", "working", "正在", "执行中"]):
        return "active"
    return "unknown"


def build_continuation_prompt(transcript_tail: str, state: dict[str, Any]) -> str:
    return f"""Continue the A9 24-hour automation from the live page/TUI monitor.

Monitor state:
- status: {state['status']}
- transcript_path: {state['transcript_path']}
- unchanged_seconds: {state['unchanged_seconds']}
- content_hash: {state['content_hash']}

Rules:
- Do not treat the page transcript as canonical truth.
- Hand off useful details into durable A9 artifacts: supervisor task, evidence, checkpoint, memory.
- Continue the compare/copy/implement/test/record loop.
- Preserve concrete file paths, commands, failures, and next actions.

Recent transcript tail:

```text
{transcript_tail}
```
"""


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def enqueue_continuation(prompt: str) -> str:
    task_id = f"page-monitor-continue-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    result = run(
        [
            str(ROOT / "scripts" / "a9_supervisor.py"),
            "enqueue",
            task_id,
            prompt,
            "--phase",
            "record",
            "--check",
            "python3 -m unittest tests/test_supervisor.py tests/test_memory.py tests/test_checkpoint.py tests/test_service.py",
            "--check",
            "cargo build --workspace",
            "--timeout-seconds",
            "3600",
            "--idle-timeout-seconds",
            "300",
            "--max-attempts",
            "2",
        ]
    )
    if result.returncode != 0:
        raise SystemExit(result.stdout)
    return result.stdout.strip()


def check_once(args: argparse.Namespace) -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    transcript_path = Path(args.transcript).resolve()
    transcript_tail = read_transcript(transcript_path, args.tail_chars)
    content_hash = sha256_text(transcript_tail)
    previous = read_json(STATE_PATH)
    now, now_iso = parse_now(getattr(args, "now", None))
    previous_hash = previous.get("content_hash")
    first_seen = float(previous.get("first_seen_epoch", now))
    if previous_hash != content_hash:
        first_seen = now
    unchanged_seconds = max(0.0, now - first_seen)
    transcript_class = classify_transcript(transcript_tail)
    is_idle = unchanged_seconds >= args.idle_seconds
    status = "idle" if is_idle else "active"
    if transcript_class == "possibly_stopped" and unchanged_seconds >= min(args.idle_seconds, 30):
        status = "stopped"

    state = {
        "updated_at": now_iso,
        "transcript_path": str(transcript_path),
        "status": status,
        "transcript_class": transcript_class,
        "content_hash": content_hash,
        "content_bytes": len(transcript_tail.encode("utf-8", errors="backslashreplace")),
        "first_seen_epoch": first_seen,
        "unchanged_seconds": round(unchanged_seconds, 3),
        "idle_seconds": args.idle_seconds,
        "tail_chars": args.tail_chars,
        "snapshot_path": str(SNAPSHOT_PATH),
        "continuation_path": str(CONTINUATION_PATH),
    }
    SNAPSHOT_PATH.write_text(transcript_tail, encoding="utf-8")
    continuation = build_continuation_prompt(transcript_tail, state)
    CONTINUATION_PATH.write_text(continuation, encoding="utf-8")
    if args.enqueue_on_idle and status in {"idle", "stopped"} and not previous.get("enqueued_for_hash") == content_hash:
        state["enqueued_task"] = enqueue_continuation(continuation)
        state["enqueued_for_hash"] = content_hash
    elif previous.get("enqueued_for_hash") == content_hash:
        state["enqueued_for_hash"] = content_hash
        state["enqueued_task"] = previous.get("enqueued_task", "")
    write_json(STATE_PATH, state)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def watch(args: argparse.Namespace) -> int:
    while True:
        check_once(args)
        time.sleep(args.poll_seconds)


def status(_: argparse.Namespace) -> int:
    print(json.dumps(read_json(STATE_PATH), ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 page/TUI idle monitor")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check")
    check.add_argument("transcript")
    check.add_argument("--idle-seconds", type=float, default=300.0)
    check.add_argument("--tail-chars", type=int, default=12000)
    check.add_argument("--enqueue-on-idle", action="store_true")
    check.add_argument("--now", help="ISO timestamp for deterministic checks")

    watch_parser = sub.add_parser("watch")
    watch_parser.add_argument("transcript")
    watch_parser.add_argument("--idle-seconds", type=float, default=300.0)
    watch_parser.add_argument("--tail-chars", type=int, default=12000)
    watch_parser.add_argument("--poll-seconds", type=float, default=10.0)
    watch_parser.add_argument("--enqueue-on-idle", action="store_true")
    watch_parser.add_argument("--now", help="ISO timestamp for deterministic checks")

    sub.add_parser("status")
    args = parser.parse_args(argv)
    if args.command == "check":
        return check_once(args)
    if args.command == "watch":
        return watch(args)
    if args.command == "status":
        return status(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
