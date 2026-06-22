#!/usr/bin/env python3
"""Build a Codex-like runtime thread view from A9 run evidence.

This is a projection layer, not a new runtime state machine. Raw A9 summaries
and event_summaries remain the facts; this script creates a compact view that
resembles Codex's latest thread_history/runtime threads shape.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / ".a9" / "runs"
DEFAULT_OUT = ROOT / ".a9" / "runtime" / "thread_view.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def summary_paths(runs_dir: Path = RUNS_DIR, *, limit: int | None = None) -> list[Path]:
    paths = sorted(runs_dir.glob("*/summary.json"), key=lambda path: path.stat().st_mtime)
    if limit is not None and limit > 0:
        return paths[-limit:]
    return paths


def coerce_event_summaries_path(summary: dict[str, Any], summary_path: Path) -> Path:
    worker = summary.get("worker") if isinstance(summary.get("worker"), dict) else {}
    explicit = worker.get("event_summaries_path") or summary.get("event_summaries_path")
    if explicit:
        return Path(str(explicit))
    return summary_path.parent / "event_summaries.jsonl"


def run_id_from_path(summary_path: Path) -> str:
    return summary_path.parent.name


def first_event_value(events: Iterable[dict[str, Any]], event_type: str, key: str) -> str:
    for event in events:
        if event.get("event_type") == event_type and event.get(key):
            return str(event[key])
    return ""


def latest_turn_status(summary: dict[str, Any], events: list[dict[str, Any]]) -> str:
    if any(event.get("event_type") == "turn.failed" for event in events):
        return "failed"
    if any(event.get("event_type") == "turn.completed" for event in events):
        return "completed"
    status = str(summary.get("status") or "")
    if "failed" in status:
        return "failed"
    if "interrupted" in status:
        return "interrupted"
    if status in {"ok", "done", "completed"}:
        return "completed"
    return status or "unknown"


def item_from_event(event: dict[str, Any], *, index: int, turn_id: str) -> dict[str, Any] | None:
    event_type = str(event.get("event_type") or "")
    if not event_type.startswith("item."):
        return None
    item_id = str(event.get("item_id") or f"item_{index}")
    return {
        "item_id": item_id,
        "turn_id": turn_id,
        "event_type": event_type,
        "item_type": str(event.get("item_type") or ""),
        "status": str(event.get("status") or ""),
        "command": str(event.get("command") or ""),
        "exit_code": event.get("exit_code"),
        "text_preview": str(event.get("text_preview") or ""),
        "output_preview": str(event.get("output_preview") or ""),
        "source_index": index,
    }


def project_summary(summary_path: Path) -> dict[str, Any]:
    summary = read_json(summary_path)
    run_id = run_id_from_path(summary_path)
    events_path = coerce_event_summaries_path(summary, summary_path)
    events = read_jsonl(events_path)
    thread_id = first_event_value(events, "thread.started", "thread_id") or stable_id(
        "thread", run_id
    )
    turn_id = first_event_value(events, "turn.started", "turn_id") or f"{run_id}:turn-1"
    started_at = str(summary.get("started_at") or "")
    ended_at = str(summary.get("ended_at") or summary.get("completed_at") or "")
    turn_status = latest_turn_status(summary, events)
    items = [
        item
        for index, event in enumerate(events, start=1)
        if (item := item_from_event(event, index=index, turn_id=turn_id)) is not None
    ]
    error_messages = [
        str(event.get("message") or "")
        for event in events
        if event.get("event_type") in {"error", "turn.failed"} and event.get("message")
    ]
    return {
        "thread_id": thread_id,
        "run_id": run_id,
        "task_id": str(summary.get("task_id") or ""),
        "phase": str(summary.get("phase") or ""),
        "thread_status": turn_status,
        "recency_at": ended_at or started_at or utc_now(),
        "turns": [
            {
                "turn_id": turn_id,
                "thread_id": thread_id,
                "status": turn_status,
                "started_at": started_at,
                "ended_at": ended_at,
                "item_count": len(items),
                "error": error_messages[-1] if error_messages else "",
                "items": items,
            }
        ],
        "evidence": {
            "summary_path": str(summary_path),
            "event_summaries_path": str(events_path) if events_path.exists() else "",
            "execution_chain_path": str(summary.get("execution_chain_path") or ""),
        },
        "metadata": {
            "source": "a9_runtime_thread_view",
            "summary_status": str(summary.get("status") or ""),
            "event_count": len(events),
            "event_types": sorted({str(event.get("event_type") or "") for event in events}),
        },
    }


def build_view(paths: list[Path]) -> dict[str, Any]:
    threads = [project_summary(path) for path in paths]
    threads.sort(key=lambda item: str(item.get("recency_at") or ""))
    return {
        "schema": "a9.runtime_thread_view.v1",
        "generated_at": utc_now(),
        "source": "codex_like_projection_from_a9_run_summaries",
        "thread_count": len(threads),
        "threads": threads,
        "notes": [
            "Projection only: summary.json and event_summaries.jsonl remain authoritative.",
            "Inspired by Codex thread_history/runtime threads; does not replace A9 managed flow.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build A9 Codex-like runtime thread view")
    parser.add_argument("--runs-dir", default=str(RUNS_DIR))
    parser.add_argument("--summary", action="append", default=[])
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--print", action="store_true", dest="print_stdout")
    args = parser.parse_args()

    paths = [Path(value) for value in args.summary] if args.summary else summary_paths(Path(args.runs_dir), limit=args.limit)
    view = build_view(paths)
    if args.print_stdout:
        print(json.dumps(view, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(view, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": "written", "out": str(out), "thread_count": view["thread_count"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
