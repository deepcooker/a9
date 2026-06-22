#!/usr/bin/env python3
"""Own one Codex active turn and relay A9 operator deliveries to it.

This is a thin runtime bridge, not a new supervisor state machine. It keeps the
Codex app-server WebSocket connection that started the active turn and consumes
the existing A9 active-run delivery queue through the same connection.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTROL_API_PATH = ROOT / "scripts" / "a9_control_api.py"
RELAYS_DIR = ROOT / ".a9" / "runtime" / "active_run_relays"


def load_control_api():
    spec = importlib.util.spec_from_file_location("a9_control_api_for_relay", CONTROL_API_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {CONTROL_API_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stable_relay_id(prefix: str = "relay") -> str:
    stamp = utc_now().replace(":", "").replace("+00:00", "Z")
    return f"{prefix}-{stamp}-{os.getpid()}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def state_path(relay_id: str) -> Path:
    return RELAYS_DIR / f"{relay_id}.json"


def update_state(path: Path, **updates: Any) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except json.JSONDecodeError:
        payload = {}
    payload.update(updates)
    payload["updated_at"] = utc_now()
    write_json(path, payload)
    return payload


def matching_delivery(row: dict[str, Any], *, run_id: str, thread_id: str, task_id: str) -> bool:
    if str(row.get("status") or "") not in {"queued", "pending"}:
        return False
    target = row.get("target") if isinstance(row.get("target"), dict) else {}
    target_run = str(target.get("run_id") or "")
    target_thread = str(target.get("thread_id") or "")
    target_task = str(target.get("task_id") or "")
    if target_run and target_run != run_id:
        return False
    if target_thread and target_thread != thread_id:
        return False
    if target_task and target_task != task_id:
        return False
    return bool(target_run or target_thread or target_task)


def consume_matching_deliveries(
    mod: Any,
    *,
    session: Any,
    config: dict[str, Any],
    state: dict[str, Any],
    root: Path,
) -> list[dict[str, Any]]:
    queue_path = mod.active_run_delivery_queue_path(root)
    rows, skipped = mod.read_jsonl(queue_path)
    if skipped:
        update_state(Path(state["state_path"]), last_event=f"delivery_queue_skipped_bad_lines:{skipped}")
    run_id = str(state.get("run_id") or "")
    thread_id = str(state.get("thread_id") or "")
    task_id = str(state.get("task_id") or "")
    target_run = {
        "run_id": run_id,
        "thread_id": thread_id,
        "task_id": task_id,
        "current_turn_id": str(state.get("current_turn_id") or ""),
        "status": str(state.get("status") or "running"),
        "is_active": True,
    }
    processed: list[dict[str, Any]] = []
    updated_rows: list[dict[str, Any]] = []
    for row in rows:
        if matching_delivery(row, run_id=run_id, thread_id=thread_id, task_id=task_id):
            try:
                delivered = mod.active_run_transport_deliver(
                    row,
                    target_run=target_run,
                    config=config,
                    jsonrpc_session=session,
                )
            except Exception as exc:
                delivered = {
                    "status": "rejected",
                    "reason": "active_run_relay_transport_error",
                    "error": mod.compact_text(str(exc), 1000),
                }
            result = {
                "delivery_id": row.get("delivery_id"),
                "operator_command_id": row.get("operator_command_id"),
                "command": row.get("command"),
                "action": row.get("action"),
                "transport": str(config.get("transport") or ""),
                "target": row.get("target") if isinstance(row.get("target"), dict) else {},
                **delivered,
                "relay_id": state.get("relay_id"),
                "thread_id": thread_id,
                "turn_id": target_run["current_turn_id"],
            }
            updated_rows.append({**row, "status": result["status"], "consumed_at": utc_now(), "delivery_result": result})
            mod.append_active_run_delivery_result(result, root=root)
            processed.append(result)
        else:
            updated_rows.append(row)
    if processed:
        mod.write_active_run_delivery_queue(updated_rows, root=root)
    return processed


def start_relay(args: argparse.Namespace) -> int:
    mod = load_control_api()
    config = mod.active_run_transport_config(ROOT)
    if args.endpoint:
        config = {**config, "endpoint": args.endpoint, "enabled": True, "transport": "codex_app_server_jsonrpc"}
    if args.token_file:
        config = {**config, "token_file": args.token_file}
    if args.auth_token:
        config = {**config, "auth_token": args.auth_token}
    if args.timeout_seconds:
        config = {**config, "timeout_seconds": args.timeout_seconds}
    if str(config.get("transport") or "") != "codex_app_server_jsonrpc":
        raise SystemExit("active-run relay currently supports codex_app_server_jsonrpc only")
    endpoint = str(config.get("endpoint") or config.get("url") or "")
    if not endpoint:
        raise SystemExit("active-run relay requires endpoint")
    auth_token = str(config.get("auth_token") or "").strip()
    token_file = str(config.get("token_file") or "").strip()
    if not auth_token and token_file:
        auth_token = Path(token_file).read_text(encoding="utf-8").strip()

    relay_id = args.relay_id or stable_relay_id()
    path = state_path(relay_id)
    base_state = {
        "schema": "a9.active_run_relay_state.v1",
        "relay_id": relay_id,
        "active_run_id": mod.stable_runtime_id("active_run", "relay", relay_id)
        if hasattr(mod, "stable_runtime_id")
        else f"active_run_relay_{relay_id}",
        "run_id": args.run_id or relay_id,
        "task_id": args.task_id or "",
        "phase": "active_run_relay",
        "status": "starting",
        "transport": "codex_app_server_jsonrpc",
        "endpoint": endpoint,
        "pid": os.getpid(),
        "started_at": utc_now(),
        "state_path": str(path),
        "last_event": "starting",
    }
    write_json(path, base_state)

    with mod.CodexWebsocketJsonRpcSession(
        endpoint,
        timeout_seconds=float(config.get("timeout_seconds") or 5),
        auth_token=auth_token,
        client_name="a9-active-run-relay",
    ) as session:
        if args.attach_thread_id and args.attach_turn_id:
            thread_id = args.attach_thread_id
            turn_id = args.attach_turn_id
        else:
            if not args.prompt:
                update_state(path, status="blocked", last_event="prompt_required_for_new_turn")
                raise SystemExit("prompt is required unless --attach-thread-id and --attach-turn-id are provided")
            thread = session.request("thread/start", {"cwd": args.cwd, "ephemeral": bool(args.ephemeral)})
            thread_id = str(thread.get("result", {}).get("thread", {}).get("id") or "")
            turn = session.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": args.prompt, "text_elements": []}],
                },
            )
            turn_id = str(turn.get("result", {}).get("turn", {}).get("id") or "")
        state = update_state(
            path,
            status="running",
            thread_id=thread_id,
            current_turn_id=turn_id,
            last_event="active_turn_owned",
            evidence={"relay_state_path": str(path)},
        )

        deadline = time.monotonic() + max(1, int(args.max_seconds))
        poll_seconds = max(0.1, float(args.poll_seconds))
        processed_count = 0
        while time.monotonic() < deadline:
            processed = consume_matching_deliveries(mod, session=session, config=config, state=state, root=ROOT)
            if processed:
                processed_count += len(processed)
                state = update_state(path, delivered_count=processed_count, last_event="delivery_processed")
            time.sleep(poll_seconds)
        update_state(path, status="stopped", delivered_count=processed_count, last_event="max_seconds_elapsed")
    print(json.dumps({"status": "stopped", "relay_id": relay_id, "state_path": str(path)}, ensure_ascii=False, indent=2))
    return 0


def status_relay(args: argparse.Namespace) -> int:
    relays = []
    if RELAYS_DIR.exists():
        for path in sorted(RELAYS_DIR.glob("*.json")):
            try:
                relays.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                relays.append({"status": "degraded", "state_path": str(path), "reason": "invalid_json"})
    print(json.dumps({"schema": "a9.active_run_relay_status.v1", "relays": relays}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="A9 Codex active-run relay")
    sub = parser.add_subparsers(dest="cmd", required=True)
    start = sub.add_parser("start", help="start or attach one relay loop")
    start.add_argument("--relay-id", default="")
    start.add_argument("--run-id", default="")
    start.add_argument("--task-id", default="")
    start.add_argument("--endpoint", default="")
    start.add_argument("--token-file", default="")
    start.add_argument("--auth-token", default="")
    start.add_argument("--timeout-seconds", type=float, default=5.0)
    start.add_argument("--cwd", default=str(ROOT))
    start.add_argument("--prompt", default="")
    start.add_argument("--attach-thread-id", default="")
    start.add_argument("--attach-turn-id", default="")
    start.add_argument("--ephemeral", action="store_true")
    start.add_argument("--max-seconds", type=int, default=60)
    start.add_argument("--poll-seconds", type=float, default=1.0)
    start.set_defaults(func=start_relay)

    status = sub.add_parser("status", help="print relay state files")
    status.set_defaults(func=status_relay)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
