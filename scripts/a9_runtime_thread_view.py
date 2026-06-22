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
DEFAULT_OUT = ROOT / ".a9" / "runtime" / "runtime_projection.json"
OPERATOR_COMMANDS_REL_PATH = Path(".a9") / "runtime" / "operator_commands.jsonl"
ACTIVE_RUN_DELIVERY_QUEUE_REL_PATH = Path(".a9") / "runtime" / "active_run_delivery_queue.jsonl"
ACTIVE_RUN_DELIVERY_RESULTS_REL_PATH = Path(".a9") / "runtime" / "active_run_delivery_results.jsonl"
ACTIVE_RUN_RELAYS_REL_DIR = Path(".a9") / "runtime" / "active_run_relays"


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


def read_jsonl_tail(path: Path, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    return rows[-max(1, limit):]


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


def first_present(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


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
    ended_at = first_present(summary, "ended_at", "completed_at", "finished_at")
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
            "task_path": str(summary.get("task_path") or ""),
            "worktree": str(summary.get("worktree") or ""),
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


def flatten_projection_threads(threads: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    turns: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for thread in threads:
        thread_id = str(thread.get("thread_id") or "")
        run_id = str(thread.get("run_id") or "")
        for turn in thread.get("turns", []):
            if not isinstance(turn, dict):
                continue
            turn_items = [item for item in turn.get("items", []) if isinstance(item, dict)]
            item_ids = [str(item.get("item_id") or "") for item in turn_items]
            turn_row = {key: value for key, value in turn.items() if key != "items"}
            turn_row["run_id"] = run_id
            turn_row["item_ids"] = item_ids
            turns.append(turn_row)
            for item in turn_items:
                item_row = dict(item)
                item_row["thread_id"] = thread_id
                item_row["run_id"] = run_id
                items.append(item_row)
    return turns, items


def active_run_from_thread(thread: dict[str, Any]) -> dict[str, Any]:
    turns = [turn for turn in thread.get("turns", []) if isinstance(turn, dict)]
    current_turn = turns[-1] if turns else {}
    run_id = str(thread.get("run_id") or "")
    status = str(thread.get("thread_status") or "unknown")
    return {
        "active_run_id": stable_id("active_run", run_id),
        "run_id": run_id,
        "thread_id": str(thread.get("thread_id") or ""),
        "task_id": str(thread.get("task_id") or ""),
        "phase": str(thread.get("phase") or ""),
        "status": status,
        "is_active": status in {"running", "in_progress", "needs-approval", "needs_approval"},
        "current_turn_id": str(current_turn.get("turn_id") or ""),
        "recency_at": str(thread.get("recency_at") or ""),
        "evidence": thread.get("evidence") if isinstance(thread.get("evidence"), dict) else {},
    }


def worker_task_from_thread(thread: dict[str, Any]) -> dict[str, Any]:
    evidence = thread.get("evidence") if isinstance(thread.get("evidence"), dict) else {}
    return {
        "task_id": str(thread.get("task_id") or ""),
        "run_id": str(thread.get("run_id") or ""),
        "phase": str(thread.get("phase") or ""),
        "status": str(thread.get("thread_status") or "unknown"),
        "task_path": str(evidence.get("task_path") or ""),
        "summary_path": str(evidence.get("summary_path") or ""),
        "event_summaries_path": str(evidence.get("event_summaries_path") or ""),
    }


def approval_from_thread(thread: dict[str, Any]) -> dict[str, Any] | None:
    metadata = thread.get("metadata") if isinstance(thread.get("metadata"), dict) else {}
    summary_status = str(metadata.get("summary_status") or thread.get("thread_status") or "")
    if summary_status not in {"needs-approval", "needs_approval"}:
        return None
    run_id = str(thread.get("run_id") or "")
    return {
        "approval_id": stable_id("approval", run_id),
        "run_id": run_id,
        "thread_id": str(thread.get("thread_id") or ""),
        "task_id": str(thread.get("task_id") or ""),
        "status": "pending",
        "evidence": thread.get("evidence") if isinstance(thread.get("evidence"), dict) else {},
    }


def memory_packets(root: Path) -> list[dict[str, Any]]:
    cursor = root / ".a9" / "mempalace" / "operator-session-ingest-cursor.json"
    payload = read_json(cursor)
    if not payload:
        return []
    return [
        {
            "memory_packet_id": stable_id(
                "memory_packet",
                payload.get("session_id", ""),
                payload.get("ordinal", ""),
                payload.get("byte_offset", ""),
            ),
            "kind": "mempalace_operator_session_cursor",
            "session_id": str(payload.get("session_id") or ""),
            "ordinal": payload.get("ordinal"),
            "source_session_path": str(payload.get("source_session_path") or ""),
            "drawers_path": str(payload.get("drawers_path") or ""),
            "updated_at": str(payload.get("updated_at") or ""),
            "evidence": {"cursor_path": str(cursor)},
        }
    ]


def remote_hosts(root: Path) -> list[dict[str, Any]]:
    services_dir = root / ".a9" / "services"
    if not services_dir.exists():
        return []
    pid_files = sorted(path.name for path in services_dir.glob("*.pid"))
    return [
        {
            "remote_host_id": stable_id("remote_host", "local", str(root)),
            "kind": "local_control_host",
            "trust_boundary": "single_operator_host",
            "root": str(root),
            "status": "configured" if pid_files else "unknown",
            "pid_files": pid_files,
            "evidence": {"services_dir": str(services_dir)},
        }
    ]


def operator_commands(root: Path, *, limit: int = 100) -> list[dict[str, Any]]:
    path = root / OPERATOR_COMMANDS_REL_PATH
    commands = read_jsonl_tail(path, limit=limit)
    return [
        {
            "operator_command_id": str(row.get("operator_command_id") or row.get("intervention_id") or ""),
            "at": str(row.get("at") or ""),
            "actor": str(row.get("actor") or ""),
            "command": str(row.get("command") or ""),
            "action": str(row.get("action") or ""),
            "status": str(row.get("status") or ""),
            "thread_id": str(row.get("thread_id") or ""),
            "run_id": str(row.get("run_id") or ""),
            "task_id": str(row.get("task_id") or ""),
            "target": row.get("target") if isinstance(row.get("target"), dict) else {},
            "intent": row.get("intent") if isinstance(row.get("intent"), dict) else {},
            "result": row.get("result") if isinstance(row.get("result"), dict) else {},
            "evidence": row.get("evidence") if isinstance(row.get("evidence"), dict) else {"ledger_path": str(path)},
        }
        for row in commands
    ]


def active_run_deliveries(root: Path, *, limit: int = 100) -> list[dict[str, Any]]:
    path = root / ACTIVE_RUN_DELIVERY_QUEUE_REL_PATH
    deliveries = read_jsonl_tail(path, limit=limit)
    return [
        {
            "delivery_id": str(row.get("delivery_id") or ""),
            "created_at": str(row.get("created_at") or ""),
            "expires_at": str(row.get("expires_at") or ""),
            "status": str(row.get("status") or ""),
            "command": str(row.get("command") or ""),
            "action": str(row.get("action") or ""),
            "operator_command_id": str(row.get("operator_command_id") or ""),
            "actor": str(row.get("actor") or ""),
            "target": row.get("target") if isinstance(row.get("target"), dict) else {},
            "intent": row.get("intent") if isinstance(row.get("intent"), dict) else {},
            "delivery_contract": row.get("delivery_contract") if isinstance(row.get("delivery_contract"), dict) else {},
            "evidence": row.get("evidence") if isinstance(row.get("evidence"), dict) else {"delivery_queue_path": str(path)},
        }
        for row in deliveries
    ]


def active_run_delivery_results(root: Path, *, limit: int = 100) -> list[dict[str, Any]]:
    path = root / ACTIVE_RUN_DELIVERY_RESULTS_REL_PATH
    results = read_jsonl_tail(path, limit=limit)
    return [
        {
            "delivery_id": str(row.get("delivery_id") or ""),
            "operator_command_id": str(row.get("operator_command_id") or ""),
            "recorded_at": str(row.get("recorded_at") or ""),
            "status": str(row.get("status") or ""),
            "reason": str(row.get("reason") or ""),
            "transport": str(row.get("transport") or ""),
            "command": str(row.get("command") or ""),
            "action": str(row.get("action") or ""),
            "target": row.get("target") if isinstance(row.get("target"), dict) else {},
            "evidence": row.get("evidence") if isinstance(row.get("evidence"), dict) else {"delivery_results_path": str(path)},
        }
        for row in results
    ]


def active_run_relays(root: Path) -> list[dict[str, Any]]:
    relays_dir = root / ACTIVE_RUN_RELAYS_REL_DIR
    if not relays_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(relays_dir.glob("*.json")):
        payload = read_json(path)
        if not payload:
            continue
        status = str(payload.get("status") or "")
        thread_id = str(payload.get("thread_id") or "")
        turn_id = str(payload.get("current_turn_id") or payload.get("turn_id") or "")
        relay_id = str(payload.get("relay_id") or path.stem)
        run_id = str(payload.get("run_id") or relay_id)
        rows.append(
            {
                "active_run_id": str(payload.get("active_run_id") or stable_id("active_run", "relay", relay_id)),
                "run_id": run_id,
                "thread_id": thread_id,
                "task_id": str(payload.get("task_id") or ""),
                "phase": str(payload.get("phase") or "active_run_relay"),
                "status": status or "unknown",
                "is_active": status in {"running", "in_progress", "needs-approval", "needs_approval"},
                "current_turn_id": turn_id,
                "recency_at": str(payload.get("updated_at") or payload.get("started_at") or ""),
                "relay": {
                    "relay_id": relay_id,
                    "transport": str(payload.get("transport") or ""),
                    "endpoint": str(payload.get("endpoint") or ""),
                    "pid": payload.get("pid"),
                    "last_event": str(payload.get("last_event") or ""),
                },
                "evidence": {
                    "relay_state_path": str(path),
                    **(payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}),
                },
            }
        )
    return rows


def build_projection(paths: list[Path], *, root: Path = ROOT) -> dict[str, Any]:
    thread_view = build_view(paths)
    threads = [thread for thread in thread_view["threads"] if isinstance(thread, dict)]
    turns, items = flatten_projection_threads(threads)
    approvals = [
        approval
        for thread in threads
        if (approval := approval_from_thread(thread)) is not None
    ]
    command_rows = operator_commands(root)
    delivery_rows = active_run_deliveries(root)
    delivery_result_rows = active_run_delivery_results(root)
    relay_active_runs = active_run_relays(root)
    packet_rows = memory_packets(root)
    host_rows = remote_hosts(root)
    projected_active_runs = [active_run_from_thread(thread) for thread in threads]
    active_runs = projected_active_runs + relay_active_runs
    return {
        "schema": "a9.runtime_projection.v1",
        "generated_at": thread_view["generated_at"],
        "source": "projection_from_a9_run_summaries_and_sidecar_indexes",
        "threads": threads,
        "turns": turns,
        "items": items,
        "active_runs": active_runs,
        "operator_commands": command_rows,
        "active_run_deliveries": delivery_rows,
        "active_run_delivery_results": delivery_result_rows,
        "worker_tasks": [worker_task_from_thread(thread) for thread in threads],
        "profile_role_lanes": [],
        "memory_packets": packet_rows,
        "approvals": approvals,
        "handoffs": [],
        "remote_hosts": host_rows,
        "counts": {
            "threads": len(threads),
            "turns": len(turns),
            "items": len(items),
            "active_runs": len(active_runs),
            "operator_commands": len(command_rows),
            "active_run_deliveries": len(delivery_rows),
            "active_run_delivery_results": len(delivery_result_rows),
            "worker_tasks": len(threads),
            "profile_role_lanes": 0,
            "memory_packets": len(packet_rows),
            "approvals": len(approvals),
            "handoffs": 0,
            "remote_hosts": len(host_rows),
        },
        "notes": [
            "Projection only: raw A9 evidence remains authoritative.",
            "Empty arrays are intentional placeholders until their evidence sources are wired.",
            "Codex supplies thread/turn/item semantics; OpenClaw supplies active-run control; Hermes supplies role/profile lane shape.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build A9 runtime projection")
    parser.add_argument("--runs-dir", default=str(RUNS_DIR))
    parser.add_argument("--summary", action="append", default=[])
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--print", action="store_true", dest="print_stdout")
    args = parser.parse_args()

    paths = [Path(value) for value in args.summary] if args.summary else summary_paths(Path(args.runs_dir), limit=args.limit)
    view = build_projection(paths, root=ROOT)
    if args.print_stdout:
        print(json.dumps(view, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(view, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "written",
                    "out": str(out),
                    "schema": view.get("schema"),
                    "counts": view.get("counts", {}),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
