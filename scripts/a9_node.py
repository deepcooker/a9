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
import re
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
NODE_CONFIG = ROOT / ".a9" / "node.json"


def redis_cli(args: list[str], *, timeout: int = 2) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "exec", "a9-redis", "redis-cli", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout,
    )


def _compact_output(value: str, limit: int = 500) -> str:
    normalized = " ".join((value or "").strip().split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _looks_like_stream_id(value: str) -> bool:
    return bool(re.fullmatch(r"\d+-\d+", str(value)))


def parse_xreadgroup_output(output: str) -> list[dict[str, Any]]:
    text = (output or "").strip()
    if not text or text == "(nil)":
        return []

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if payload is not None:
        if not isinstance(payload, list):
            return []
        events: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            stream_id = str(item[0])
            fields_raw = item[1]
            fields: dict[str, Any] = {}
            if isinstance(fields_raw, dict):
                fields = {str(key): value for key, value in fields_raw.items()}
            elif isinstance(fields_raw, list):
                for index in range(0, len(fields_raw), 2):
                    if index + 1 >= len(fields_raw):
                        break
                    fields[str(fields_raw[index])] = fields_raw[index + 1]
            events.append({"id": stream_id, "fields": fields})
        return events

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    events: list[dict[str, Any]] = []
    idx = 0
    while idx < len(lines):
        raw_id = lines[idx]
        if not _looks_like_stream_id(raw_id):
            idx += 1
            continue
        idx += 1
        fields: dict[str, Any] = {}
        while idx + 1 < len(lines):
            key = lines[idx]
            if _looks_like_stream_id(key):
                break
            fields[str(key)] = lines[idx + 1]
            idx += 2
        events.append({"id": raw_id, "fields": fields})
    return events


def _safe_node_id(value: str) -> str:
    node_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())[:80].strip(".-")
    if not node_id:
        raise ValueError("node_id is required")
    return node_id


def _plan_invalid_payload(action: str, node_id: str, *, reason: str) -> dict[str, Any]:
    return {
        "status": "degraded",
        "error_code": "invalid_payload",
        "action": action,
        "node_id": node_id,
        "reason": reason,
        "stream": "",
        "group": "",
        "consumer": "",
        "evidence": {"node_id": node_id, "action": action, "reason": reason},
        "commands": [],
    }


def classify_node_connection_state(
    *,
    heartbeat_age_seconds: float | int | None,
    heartbeat_status: str = "",
    reconnect_decision: dict[str, Any] | None = None,
    stale_after_seconds: int = 30,
    offline_after_seconds: int = 90,
) -> dict[str, Any]:
    decision = reconnect_decision or {}
    normalized_status = str(heartbeat_status or "").strip().lower() or "unknown"
    safe_stale = max(1, int(stale_after_seconds))
    safe_offline = max(safe_stale + 1, int(offline_after_seconds))
    if heartbeat_age_seconds is None:
        age_seconds = float("inf")
    else:
        age_seconds = max(0.0, float(heartbeat_age_seconds))

    reconnect_action = str(decision.get("action") or "").strip().lower()
    reconnect_phase = str(decision.get("phase") or "").strip().lower()
    reconnect_error = str(decision.get("error_class") or "").strip().lower()
    policy_budget_remaining = max(0, int(decision.get("policy_budget_remaining") or 0))

    base_state = "online"
    base_reason = "heartbeat_fresh"
    if age_seconds >= safe_offline:
        base_state = "offline"
        base_reason = "heartbeat_timeout"
    elif age_seconds >= safe_stale:
        base_state = "stale"
        base_reason = "heartbeat_stale"

    if normalized_status in {"degraded", "error", "failed"}:
        base_state = "degraded"
        base_reason = "heartbeat_reported_degraded"

    state = base_state
    reason = base_reason
    if base_state == "offline":
        action = "escalate"
    elif base_state in {"stale", "degraded"}:
        action = "observe"
    else:
        action = "continue"

    if age_seconds >= safe_offline:
        state = "offline"
        reason = "heartbeat_timeout"
        action = "escalate"

    if reconnect_action == "reconnect":
        state = "reconnecting"
        reason = "reconnect_requested"
        action = "retry"
    elif reconnect_action == "terminate":
        state = "degraded" if base_state != "offline" else "offline"
        reason = "reconnect_terminated" if policy_budget_remaining <= 0 else "reconnect_not_allowed"
        action = "quarantine" if state == "degraded" else "escalate"
    elif reconnect_action == "continue" and reconnect_phase == "stream":
        if base_state in {"online", "stale"}:
            state = "degraded"
            reason = "stream_error_continue"
            action = "observe"

    evidence = {
        "heartbeat_age_seconds": None if age_seconds == float("inf") else round(age_seconds, 3),
        "heartbeat_status": normalized_status,
        "stale_after_seconds": safe_stale,
        "offline_after_seconds": safe_offline,
        "reconnect_phase": reconnect_phase or "none",
        "reconnect_action": reconnect_action or "none",
        "reconnect_error_class": reconnect_error or "none",
        "policy_budget_remaining": policy_budget_remaining,
    }
    return {"state": state, "action": action, "reason": reason, "evidence": evidence}


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


def node_command_consumer_name(node_id: str) -> str:
    safe = _safe_node_id(node_id)
    return f"{safe}-consumer"


def node_command_claim_plan(
    node_id: str,
    count: int = 1,
    block_ms: int = 5000,
    group: str = "a9-worker",
    stream: str = "a9:tasks",
) -> dict[str, Any]:
    try:
        safe_node_id = _safe_node_id(node_id)
        safe_count = int(count)
        safe_block_ms = int(block_ms)
    except (TypeError, ValueError):
        return _plan_invalid_payload("claim", str(node_id or ""), reason="count_and_block_must_be_ints")
    if safe_count < 1:
        return _plan_invalid_payload("claim", safe_node_id, reason="count_must_be_positive")
    if safe_block_ms < 0:
        return _plan_invalid_payload("claim", safe_node_id, reason="block_ms_must_be_non_negative")
    if not group.strip():
        return _plan_invalid_payload("claim", safe_node_id, reason="group_required")
    if not stream.strip():
        return _plan_invalid_payload("claim", safe_node_id, reason="stream_required")

    consumer = node_command_consumer_name(safe_node_id)
    return {
        "status": "ok",
        "stream": stream.strip(),
        "group": group.strip(),
        "consumer": consumer,
        "node_id": safe_node_id,
        "action": "claim",
        "reason": "claim_next_command",
        "execution_enabled": False,
        "evidence": {
            "stream": stream.strip(),
            "group": group.strip(),
            "consumer": consumer,
            "node_id": safe_node_id,
            "action": "claim",
            "reason": "claim_next_command",
        },
        "commands": [
            ["XGROUP", "CREATE", stream.strip(), group.strip(), "0-0", "MKSTREAM"],
            [
                "XREADGROUP",
                "GROUP",
                group.strip(),
                consumer,
                "COUNT",
                str(safe_count),
                "BLOCK",
                str(safe_block_ms),
                "STREAMS",
                stream.strip(),
                ">",
            ],
        ],
    }


def node_command_ack_plan(
    node_id: str,
    command_stream_id: str,
    group: str = "a9-worker",
    stream: str = "a9:tasks",
) -> dict[str, Any]:
    try:
        safe_node_id = _safe_node_id(node_id)
    except ValueError as exc:
        return _plan_invalid_payload("ack", str(node_id or ""), reason=str(exc))
    if not command_stream_id:
        return _plan_invalid_payload("ack", safe_node_id, reason="command_stream_id_required")
    if not group.strip():
        return _plan_invalid_payload("ack", safe_node_id, reason="group_required")
    if not stream.strip():
        return _plan_invalid_payload("ack", safe_node_id, reason="stream_required")

    consumer = node_command_consumer_name(safe_node_id)
    return {
        "status": "ok",
        "stream": stream.strip(),
        "group": group.strip(),
        "consumer": consumer,
        "node_id": safe_node_id,
        "action": "ack",
        "reason": "ack_completed_command",
        "execution_enabled": False,
        "evidence": {
            "stream": stream.strip(),
            "group": group.strip(),
            "consumer": consumer,
            "node_id": safe_node_id,
            "action": "ack",
            "reason": "ack_completed_command",
        },
        "commands": [
            ["XACK", stream.strip(), group.strip(), str(command_stream_id)],
        ],
    }


def node_command_claim_once(
    node_id: str,
    count: int = 1,
    block_ms: int = 1000,
    group: str = "a9-worker",
    stream: str = "a9:tasks",
    ack: bool = False,
    timeout: int = 3,
) -> dict[str, Any]:
    try:
        safe_node_id = _safe_node_id(node_id)
        safe_count = int(count)
        safe_block_ms = int(block_ms)
        safe_timeout = max(1, int(timeout))
        safe_stream = stream.strip()
        safe_group = group.strip()
        safe_ack = bool(ack)
    except (TypeError, ValueError):
        return {
            "status": "degraded",
            "error_code": "invalid_payload",
            "action": "claim_once",
            "node_id": str(node_id or ""),
            "stream": str(stream or ""),
            "group": str(group or ""),
            "consumer": "",
            "events": [],
            "command_count": 0,
            "acked_ids": [],
            "raw_output": {},
            "reason": "count_block_ms_timeout_must_be_ints",
        }

    if safe_count < 1:
        return {
            "status": "degraded",
            "error_code": "invalid_payload",
            "action": "claim_once",
            "node_id": safe_node_id,
            "stream": safe_stream,
            "group": safe_group,
            "consumer": "",
            "events": [],
            "command_count": 0,
            "acked_ids": [],
            "raw_output": {},
            "reason": "count_must_be_positive",
        }

    if safe_block_ms < 0:
        return {
            "status": "degraded",
            "error_code": "invalid_payload",
            "action": "claim_once",
            "node_id": safe_node_id,
            "stream": safe_stream,
            "group": safe_group,
            "consumer": "",
            "events": [],
            "command_count": 0,
            "acked_ids": [],
            "raw_output": {},
            "reason": "block_ms_must_be_non_negative",
        }

    if not safe_group:
        return {
            "status": "degraded",
            "error_code": "invalid_payload",
            "action": "claim_once",
            "node_id": safe_node_id,
            "stream": safe_stream,
            "group": "",
            "consumer": "",
            "events": [],
            "command_count": 0,
            "acked_ids": [],
            "raw_output": {},
            "reason": "group_required",
        }

    if not safe_stream:
        return {
            "status": "degraded",
            "error_code": "invalid_payload",
            "action": "claim_once",
            "node_id": safe_node_id,
            "stream": "",
            "group": safe_group,
            "consumer": "",
            "events": [],
            "command_count": 0,
            "acked_ids": [],
            "raw_output": {},
            "reason": "stream_required",
        }

    consumer = node_command_consumer_name(safe_node_id)
    command_count = 0
    acked_ids: list[str] = []
    raw_output: dict[str, str] = {}

    read_args = [
        "XREADGROUP",
        "GROUP",
        safe_group,
        consumer,
        "COUNT",
        str(safe_count),
        "BLOCK",
        str(safe_block_ms),
        "STREAMS",
        safe_stream,
        ">",
    ]

    try:
        create_args = ["XGROUP", "CREATE", safe_stream, safe_group, "0-0", "MKSTREAM"]
        create_proc = redis_cli(create_args, timeout=min(2, safe_timeout))
        raw_output["xgroup_create"] = _compact_output(create_proc.stdout, 500)
        if create_proc.returncode != 0 and "BUSYGROUP" not in (create_proc.stdout or "").upper():
            return {
                "status": "degraded",
                "error_code": "redis_command_error",
                "action": "claim_once",
                "node_id": safe_node_id,
                "stream": safe_stream,
                "group": safe_group,
                "consumer": consumer,
                "events": [],
                "command_count": 0,
                "acked_ids": [],
                "raw_output": raw_output,
                "reason": create_proc.stdout.strip() or "xgroup_create_failed",
            }

        read_proc = redis_cli(["--raw", *read_args], timeout=safe_timeout)
        raw_output["xreadgroup"] = _compact_output(read_proc.stdout, 500)
        if read_proc.returncode != 0:
            return {
                "status": "degraded",
                "error_code": "redis_command_error",
                "action": "claim_once",
                "node_id": safe_node_id,
                "stream": safe_stream,
                "group": safe_group,
                "consumer": consumer,
                "events": [],
                "command_count": 0,
                "acked_ids": [],
                "raw_output": raw_output,
                "reason": read_proc.stdout.strip() or "xreadgroup_failed",
            }

        events = parse_xreadgroup_output(read_proc.stdout)
        command_count = len(events)
        if command_count == 0:
            return {
                "status": "noop",
                "error_code": "no_events",
                "action": "claim_once",
                "node_id": safe_node_id,
                "stream": safe_stream,
                "group": safe_group,
                "consumer": consumer,
                "events": [],
                "command_count": 0,
                "acked_ids": [],
                "raw_output": raw_output,
            }

        if safe_ack:
            ack_ids = [str(event["id"]) for event in events]
            ack_proc = redis_cli(["XACK", safe_stream, safe_group, *ack_ids], timeout=safe_timeout)
            raw_output["xack"] = _compact_output(ack_proc.stdout, 500)
            if ack_proc.returncode != 0:
                return {
                    "status": "degraded",
                    "error_code": "redis_command_error",
                    "action": "claim_once",
                    "node_id": safe_node_id,
                    "stream": safe_stream,
                    "group": safe_group,
                    "consumer": consumer,
                    "events": events,
                    "command_count": command_count,
                    "acked_ids": [],
                    "raw_output": raw_output,
                    "reason": ack_proc.stdout.strip() or "xack_failed",
                }
            acked_ids = ack_ids

        return {
            "status": "ok",
            "error_code": "ok",
            "action": "claim_once",
            "node_id": safe_node_id,
            "stream": safe_stream,
            "group": safe_group,
            "consumer": consumer,
            "events": events,
            "command_count": command_count,
            "acked_ids": acked_ids,
            "raw_output": raw_output,
        }

    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "degraded",
            "error_code": "redis_unavailable",
            "action": "claim_once",
            "node_id": safe_node_id,
            "stream": safe_stream,
            "group": safe_group,
            "consumer": consumer,
            "events": [],
            "command_count": 0,
            "acked_ids": [],
            "raw_output": raw_output,
            "reason": str(exc),
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


def command_claim_plan(args: argparse.Namespace) -> int:
    node_id = args.node_id or default_node_id()
    payload = node_command_claim_plan(
        node_id=node_id,
        count=args.count,
        block_ms=args.block_ms,
        group=args.group,
        stream=args.stream,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_ack_plan(args: argparse.Namespace) -> int:
    node_id = args.node_id or default_node_id()
    payload = node_command_ack_plan(
        node_id=node_id,
        command_stream_id=args.command_stream_id,
        group=args.group,
        stream=args.stream,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_claim_once(args: argparse.Namespace) -> int:
    node_id = args.node_id or default_node_id()
    payload = node_command_claim_once(
        node_id=node_id,
        count=args.count,
        block_ms=args.block_ms,
        group=args.group,
        stream=args.stream,
        ack=args.ack,
        timeout=args.timeout_cmd_claim,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
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

    claim_plan_parser = sub.add_parser("command-claim-plan")
    claim_plan_parser.add_argument("--count", type=int, default=1)
    claim_plan_parser.add_argument("--block-ms", type=int, default=5000)
    claim_plan_parser.add_argument("--group", default="a9-worker")
    claim_plan_parser.add_argument("--stream", default="a9:tasks")

    claim_once_parser = sub.add_parser("command-claim-once")
    claim_once_parser.add_argument("--count", type=int, default=1)
    claim_once_parser.add_argument("--block-ms", type=int, default=1000)
    claim_once_parser.add_argument("--group", default="a9-worker")
    claim_once_parser.add_argument("--stream", default="a9:tasks")
    claim_once_parser.add_argument("--ack", action="store_true")
    claim_once_parser.add_argument("--timeout", type=int, default=3, dest="timeout_cmd_claim")

    ack_plan_parser = sub.add_parser("command-ack-plan")
    ack_plan_parser.add_argument("command_stream_id")
    ack_plan_parser.add_argument("--group", default="a9-worker")
    ack_plan_parser.add_argument("--stream", default="a9:tasks")

    args = parser.parse_args(argv)
    if args.command == "discover":
        return discover(args)
    if args.command == "register":
        return register(args)
    if args.command == "heartbeat":
        return heartbeat(args)
    if args.command == "command-claim-plan":
        return command_claim_plan(args)
    if args.command == "command-claim-once":
        return command_claim_once(args)
    if args.command == "command-ack-plan":
        return command_ack_plan(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
