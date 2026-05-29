#!/usr/bin/env python3
"""A9 mobile/control-plane HTTP API.

This is intentionally small and stdlib-only. It exposes existing A9 state to a
phone/browser without making the phone a new source of truth.
"""

from __future__ import annotations

import argparse
import ipaddress
import importlib.util
import shlex
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
CODEX_SESSIONS_DIR = Path("/root/.codex/sessions")
SUPERVISOR_PATH = ROOT / "scripts" / "a9_supervisor.py"
SESSION_REFRESH_PATH = ROOT / "scripts" / "a9_session_refresh.py"
REMOTE_PATH = ROOT / "scripts" / "a9_remote.py"
NODE_HELPER_PATH = ROOT / "scripts" / "a9_node.py"
NODES_DIR = ROOT / ".a9" / "nodes"
PHONE_CONTROL_REL_PATH = Path(".a9") / "control" / "phone_control.json"
GATEWAY_BIN_REL_PATH = Path("target") / "debug" / "a9-gateway"
TAILSCALE_SOCKET = "/run/tailscale/tailscaled.sock"
DEFAULT_SSH_IDENTITY_FILE = "/root/id_ed25519"
NODE_ONLINE_TTL_SECONDS = 90
NODE_STALE_TTL_SECONDS = 300
PHONE_ADMIN_SCOPE = "operator.admin"
PHONE_CONTROL_GROUPS = {
    "runtime": [
        "submit.run",
        "session.refresh.trial",
        "flow.resume",
        "approval.approve",
        "approval.reject",
        "eval.override",
    ],
    "remote": [
        "nodes.bootstrap.execute",
        "nodes.probe.execute",
        "nodes.recovery.cycle",
        "nodes.remote.install",
        "nodes.remote.repair",
        "nodes.tmux.ensure",
        "nodes.tmux.status",
        "nodes.heartbeat.tmux.start",
    ],
}
KNOWN_CONTROL_COMMANDS = sorted({cmd for commands in PHONE_CONTROL_GROUPS.values() for cmd in commands})
EVENTS_STREAM_KEY = "a9:events"
EVENTS_STREAM_LIMIT_MAX = 1000
TASKS_STREAM_KEY = "a9:tasks"
TASKS_STREAM_GROUP = "a9-worker"
TASKS_STREAM_TOP_CONSUMERS_LIMIT = 3
GATEWAY_CONTRACT_EVENT_STALE_SECONDS = 300


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def supervisor() -> Any:
    return load_module("a9_supervisor_control_api", SUPERVISOR_PATH)


def session_refresh() -> Any:
    return load_module("a9_session_refresh_control_api", SESSION_REFRESH_PATH)


def remote() -> Any:
    return load_module("a9_remote_control_api", REMOTE_PATH)


def a9_node() -> Any:
    return load_module("a9_node_control_api", NODE_HELPER_PATH)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def compact_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


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


def redis_available() -> bool:
    try:
        proc = redis_cli(["PING"])
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and "PONG" in proc.stdout


def _looks_like_stream_id(value: str) -> bool:
    return bool(re.fullmatch(r"\d+-\d+", value))


def _resolve_event_last_id(query_last_id: str | None, last_event_id_header: str | None) -> str | None:
    if query_last_id:
        return query_last_id
    if last_event_id_header and _looks_like_stream_id(last_event_id_header):
        return last_event_id_header
    return None


def parse_xrange_events(output: str) -> list[dict[str, Any]]:
    text = (output or "").strip()
    if not text:
        return []

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if payload is not None:
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            return []
        events: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, list) or len(item) < 2:
                continue
            fields: dict[str, Any] = {}
            fields_raw = item[1]
            if isinstance(fields_raw, dict):
                fields = {str(key): value for key, value in fields_raw.items()}
            elif isinstance(fields_raw, list):
                for index in range(0, len(fields_raw), 2):
                    if index + 1 >= len(fields_raw):
                        break
                    fields[str(fields_raw[index])] = fields_raw[index + 1]
            events.append({"id": str(item[0]), "fields": fields})
        return events

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    events: list[dict[str, Any]] = []
    idx = 0
    while idx < len(lines):
        event_id = lines[idx]
        idx += 1
        fields: dict[str, Any] = {}
        while idx + 1 < len(lines):
            key = lines[idx]
            if _looks_like_stream_id(key):
                break
            fields[key] = lines[idx + 1]
            idx += 2
        events.append({"id": event_id, "fields": fields})
    return events


def read_events(last_id: str | None = None, *, count: int = 100, limit: int | None = None) -> dict[str, Any]:
    requested_raw = limit if limit is not None else count
    requested = max(1, min(EVENTS_STREAM_LIMIT_MAX, int(requested_raw)))
    if last_id is not None and not _looks_like_stream_id(last_id):
        return {
            "status": "degraded",
            "stream": EVENTS_STREAM_KEY,
            "error": "invalid last_id format, expected stream-id like 1740000000-0",
            "last_id": last_id,
            "requested_count": requested,
            "events": [],
        }

    start = "-" if not last_id else f"({last_id}"
    try:
        proc = redis_cli(["--raw", "XRANGE", EVENTS_STREAM_KEY, start, "+", "COUNT", str(requested)])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "degraded",
            "stream": EVENTS_STREAM_KEY,
            "error": str(exc),
            "last_id": last_id,
            "requested_count": requested,
            "events": [],
        }

    if proc.returncode != 0:
        return {
            "status": "degraded",
            "stream": EVENTS_STREAM_KEY,
            "error": proc.stdout.strip() or "redis command failed",
            "last_id": last_id,
            "requested_count": requested,
            "events": [],
        }

    events = parse_xrange_events(proc.stdout)
    if last_id and not events:
        # Detect replay cursor gaps after stream trim/rotation: client cursor is valid
        # syntax but points outside the currently replayable window.
        try:
            oldest_proc = redis_cli(["--raw", "XRANGE", EVENTS_STREAM_KEY, "-", "+", "COUNT", "1"])
            newest_proc = redis_cli(["--raw", "XREVRANGE", EVENTS_STREAM_KEY, "+", "-", "COUNT", "1"])
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "status": "degraded",
                "stream": EVENTS_STREAM_KEY,
                "error": str(exc),
                "last_id": last_id,
                "requested_count": requested,
                "events": [],
            }
        if oldest_proc.returncode == 0 and newest_proc.returncode == 0:
            oldest_events = parse_xrange_events(oldest_proc.stdout)
            newest_events = parse_xrange_events(newest_proc.stdout)
            if oldest_events and newest_events:
                oldest_id = oldest_events[0]["id"]
                newest_id = newest_events[0]["id"]
                return {
                    "status": "degraded",
                    "stream": EVENTS_STREAM_KEY,
                    "error": "cursor_gap: last_id is outside current replay window",
                    "error_code": "cursor_gap",
                    "last_id": last_id,
                    "requested_count": requested,
                    "events": [],
                    "stream_oldest_id": oldest_id,
                    "stream_newest_id": newest_id,
                    "next_last_id": newest_id,
                }
    return {
        "status": "ok",
        "stream": EVENTS_STREAM_KEY,
        "count": len(events),
        "requested_count": requested,
        "last_id": last_id,
        "events": events,
        "next_last_id": events[-1]["id"] if events else (last_id or ""),
    }


def event_replay_reset_decision(response: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded client action for /api/events replay responses."""
    if response.get("status") == "degraded" and response.get("error_code") == "cursor_gap":
        next_last_id = str(response.get("next_last_id") or "")
        if _looks_like_stream_id(next_last_id):
            return {
                "action": "reset_cursor",
                "reason": "cursor_gap",
                "next_last_id": next_last_id,
            }
        return {
            "action": "retry_without_cursor",
            "reason": "cursor_gap_without_valid_next_last_id",
            "next_last_id": "",
        }
    return {
        "action": "keep_cursor",
        "reason": "no_cursor_reset_needed",
        "next_last_id": str(response.get("next_last_id") or ""),
    }


def events_to_sse(payload: dict[str, Any]) -> bytes:
    chunks = []
    for event in payload.get("events", []):
        chunks.append(f"id: {event.get('id')}\n")
        chunks.append(f"data: {json.dumps(event, ensure_ascii=False)}\n\n")
    return "".join(chunks).encode("utf-8")


def latest_run_summary(root: Path = ROOT) -> dict[str, Any] | None:
    summaries = sorted((root / ".a9" / "runs").glob("*/summary.json"), key=lambda path: path.stat().st_mtime)
    if not summaries:
        return None
    return read_json(summaries[-1])


def compact_summary(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not summary:
        return None
    worker = summary.get("worker", {})
    context_pressure = summary.get("context_pressure", {})
    router = context_pressure.get("context_router")
    if not isinstance(router, dict) or not router:
        fallback_router = worker.get("context_router", {})
        router = fallback_router if isinstance(fallback_router, dict) else {}
    router_sections = router.get("sections", [])
    section_count = len(router_sections) if isinstance(router_sections, list) else 0
    monitor_score = summary.get("monitor_score", {})
    return {
        "task_id": summary.get("task_id"),
        "status": summary.get("status"),
        "phase": summary.get("phase"),
        "run_dir": summary.get("run_dir"),
        "context_path": summary.get("context_path"),
        "evidence_path": summary.get("evidence_path"),
        "state_path": summary.get("state_path"),
        "deep_marks_path": summary.get("deep_marks_path"),
        "started_at": summary.get("started_at"),
        "finished_at": summary.get("finished_at"),
        "worker_failure": summary.get("worker_failure", {}),
        "worker_envelope": {
            "status": summary.get("worker_envelope", {}).get("status"),
            "required": summary.get("worker_envelope", {}).get("required", False),
        },
        "checks": summary.get("checks", []),
        "patch_guard": summary.get("patch_guard", {}),
        "scope_guard": summary.get("scope_guard", {}),
        "git_governance": summary.get("git_governance", {}),
        "policy_attestation": summary.get("policy_attestation", {}),
        "monitor_block": summary.get("monitor_block", {}),
        "monitor_score": {
            "decision_model": monitor_score.get("decision_model"),
            "score": monitor_score.get("score"),
            "recommended_action": monitor_score.get("recommended_action"),
            "gates": monitor_score.get("gates", {}),
            "findings": monitor_score.get("findings", []),
        },
        "context_pressure": context_pressure,
        "context_router": {
            "strategy": router.get("strategy"),
            "blocked_sections": router.get("blocked_sections", 0),
            "section_count": section_count,
        },
        "actual_token_usage": context_pressure.get("actual_token_usage") or worker.get("actual_token_usage", {}),
    }


def supervisor_status(root: Path = ROOT) -> dict[str, Any]:
    state_dir = root / ".a9"
    queued = sorted((state_dir / "tasks" / "queue").glob("*.md"))
    running = sorted((state_dir / "tasks" / "running").glob("*.json"))
    done = sorted((state_dir / "tasks" / "done").glob("*.json"))
    progress_path = state_dir / "progress.json"
    heartbeat_path = state_dir / "daemon_heartbeat.json"
    return {
        "queued": len(queued),
        "running": len(running),
        "done": len(done),
        "queue": [str(path) for path in queued[-20:]],
        "running_tasks": [read_json(path) for path in running[-20:]],
        "latest_run": compact_summary(latest_run_summary(root)),
        "progress": read_json(progress_path) if progress_path.exists() else {},
        "daemon_heartbeat": read_json(heartbeat_path) if heartbeat_path.exists() else {},
        "nodes": node_status(root),
        "gateway": gateway_transport_contract(root),
    }


def gateway_transport_contract(root: Path = ROOT, *, emit_event: bool = False) -> dict[str, Any]:
    binary = root / GATEWAY_BIN_REL_PATH
    if not binary.exists():
        return {
            "status": "missing",
            "kind": "gateway_transport_contract",
            "binary": str(binary),
            "reason": "gateway_binary_missing",
        }
    try:
        cmd = [str(binary), "transport-contract"]
        if emit_event:
            cmd.append("--emit-event")
        proc = subprocess.run(
            cmd,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=2,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "fail",
            "kind": "gateway_transport_contract",
            "binary": str(binary),
            "reason": "gateway_contract_timeout",
        }
    output = (proc.stdout or "").strip()
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {
            "status": "fail",
            "kind": "gateway_transport_contract",
            "binary": str(binary),
            "return_code": proc.returncode,
            "reason": "gateway_contract_invalid_json",
            "output": output[:1000],
        }
    required_true = [
        "request_overload_returns_retry_error",
        "response_waits_on_backpressure",
        "writer_full_preserves_existing_message",
    ]
    passed = (
        proc.returncode == 0
        and payload.get("status") == "ok"
        and payload.get("capacity") == 128
        and payload.get("overload_error_code") == -32001
        and all(payload.get(name) is True for name in required_true)
    )
    latest_event = latest_gateway_transport_contract_event()
    result = {
        **payload,
        "status": "ok" if passed else "fail",
        "binary": str(binary),
        "return_code": proc.returncode,
        "reason": "gateway_contract_pass" if passed else "gateway_contract_failed",
        "latest_event": latest_event,
        "reconnect": {
            "latest_event": latest_gateway_reconnect_decision_event(),
        },
    }
    result["runtime_evidence"] = gateway_runtime_evidence_decision(result, latest_event)
    return result


def gateway_reconnect_diagnostic(root: Path = ROOT, *, success: bool = False) -> dict[str, Any]:
    binary = root / GATEWAY_BIN_REL_PATH
    if not success:
        return {
            "status": "needs_approval",
            "kind": "gateway_reconnect_diagnostic",
            "reason": "diagnostic_success_flag_required",
        }
    if not binary.exists():
        return {
            "status": "missing",
            "kind": "gateway_reconnect_diagnostic",
            "binary": str(binary),
            "reason": "gateway_binary_missing",
        }
    try:
        proc = subprocess.run(
            [str(binary), "reconnect-diagnostic", "--success"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=2,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "fail",
            "kind": "gateway_reconnect_diagnostic",
            "binary": str(binary),
            "reason": "gateway_reconnect_diagnostic_timeout",
        }
    output = (proc.stdout or "").strip()
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {
            "status": "fail",
            "kind": "gateway_reconnect_diagnostic",
            "binary": str(binary),
            "return_code": proc.returncode,
            "reason": "gateway_reconnect_diagnostic_invalid_json",
            "output": output[:1000],
        }
    return {
        **payload,
        "status": "ok" if proc.returncode == 0 and payload.get("status") == "ok" else "fail",
        "kind": "gateway_reconnect_diagnostic",
        "binary": str(binary),
        "return_code": proc.returncode,
        "reason": "gateway_reconnect_diagnostic_pass"
        if proc.returncode == 0 and payload.get("status") == "ok"
        else "gateway_reconnect_diagnostic_failed",
        "latest_event": latest_gateway_reconnect_decision_event(),
    }


def event_age_seconds(event: dict[str, Any], *, now_ms_value: int | None = None) -> int | None:
    raw_ts = event.get("ts") if isinstance(event, dict) else None
    if raw_ts in {None, ""}:
        return None
    try:
        ts_ms = int(str(raw_ts))
    except (TypeError, ValueError):
        return None
    now_value = now_ms_value if now_ms_value is not None else int(utc_now_dt().timestamp() * 1000)
    return max(0, int((now_value - ts_ms) / 1000))


def gateway_runtime_evidence_decision(
    local_contract: dict[str, Any],
    latest_event: dict[str, Any],
    *,
    stale_seconds: int = GATEWAY_CONTRACT_EVENT_STALE_SECONDS,
    now_ms_value: int | None = None,
) -> dict[str, Any]:
    if local_contract.get("status") != "ok":
        return {
            "status": "fail",
            "action": "block",
            "reason": "local_gateway_contract_failed",
        }
    event_status = str(latest_event.get("status") or "")
    if event_status in {"missing", "unavailable"}:
        return {
            "status": "degraded",
            "action": "emit_runtime_event",
            "reason": "gateway_runtime_event_missing",
        }
    if event_status != "ok":
        return {
            "status": "fail",
            "action": "block",
            "reason": "gateway_runtime_event_failed",
            "event_id": latest_event.get("event_id", ""),
        }
    age = event_age_seconds(latest_event, now_ms_value=now_ms_value)
    if age is None:
        return {
            "status": "degraded",
            "action": "emit_runtime_event",
            "reason": "gateway_runtime_event_missing_timestamp",
            "event_id": latest_event.get("event_id", ""),
        }
    if age > stale_seconds:
        return {
            "status": "degraded",
            "action": "emit_runtime_event",
            "reason": "gateway_runtime_event_stale",
            "event_id": latest_event.get("event_id", ""),
            "age_seconds": age,
            "stale_seconds": stale_seconds,
        }
    return {
        "status": "ok",
        "action": "continue",
        "reason": "gateway_runtime_event_fresh",
        "event_id": latest_event.get("event_id", ""),
        "age_seconds": age,
        "stale_seconds": stale_seconds,
    }


def gateway_reconnect_evidence_decision(
    latest_event: dict[str, Any],
    *,
    stale_seconds: int = GATEWAY_CONTRACT_EVENT_STALE_SECONDS,
    now_ms_value: int | None = None,
) -> dict[str, Any]:
    event_status = str(latest_event.get("status") or "")
    if event_status in {"missing", "unavailable"}:
        return {
            "status": "degraded",
            "action": "observe",
            "reason": "gateway_reconnect_event_missing",
        }
    if event_status != "ok":
        return {
            "status": "fail",
            "action": "block",
            "reason": "gateway_reconnect_event_failed",
            "event_id": latest_event.get("event_id", ""),
        }
    age = event_age_seconds(latest_event, now_ms_value=now_ms_value)
    if age is None:
        return {
            "status": "degraded",
            "action": "observe",
            "reason": "gateway_reconnect_event_missing_timestamp",
            "event_id": latest_event.get("event_id", ""),
        }
    if age > stale_seconds:
        return {
            "status": "degraded",
            "action": "observe",
            "reason": "gateway_reconnect_event_stale",
            "event_id": latest_event.get("event_id", ""),
            "age_seconds": age,
            "stale_seconds": stale_seconds,
        }
    return {
        "status": "ok",
        "action": "continue",
        "reason": "gateway_reconnect_event_fresh",
        "event_id": latest_event.get("event_id", ""),
        "age_seconds": age,
        "stale_seconds": stale_seconds,
    }


def gateway_health_refresh(root: Path = ROOT) -> dict[str, Any]:
    contract = gateway_transport_contract(root, emit_event=True)
    reconnect_event = latest_gateway_reconnect_decision_event()
    reconnect_evidence = gateway_reconnect_evidence_decision(reconnect_event)
    status = "ok"
    if contract.get("status") != "ok" or contract.get("runtime_evidence", {}).get("action") == "block":
        status = "fail"
    elif reconnect_evidence.get("status") != "ok":
        status = "degraded"
    return {
        "status": status,
        "kind": "gateway_health_refresh",
        "contract": contract,
        "reconnect": {
            "latest_event": reconnect_event,
            "runtime_evidence": reconnect_evidence,
        },
    }


def gateway_reconnect_governance(root: Path = ROOT) -> dict[str, Any]:
    contract = gateway_transport_contract(root, emit_event=True)
    reconnect_event = latest_gateway_reconnect_decision_event()
    reconnect_evidence = gateway_reconnect_evidence_decision(reconnect_event)

    status = "ok"
    if contract.get("status") != "ok" or contract.get("runtime_evidence", {}).get("action") == "block":
        status = "fail"
    elif reconnect_evidence.get("status") == "fail":
        status = "fail"
    elif reconnect_evidence.get("status") == "degraded":
        status = "degraded"

    recommendation = {
        "status": status,
        "contract_action": contract.get("runtime_evidence", {}).get("action", "observe"),
        "reconnect_action": reconnect_evidence.get("action", "observe"),
        "reason": None,
    }
    recommendation["action"] = "continue" if status == "ok" else "observe"
    if status == "fail":
        recommendation["action"] = "block"
    elif status == "degraded":
        recommendation["action"] = "observe"

    if status == "fail" and not recommendation["reason"]:
        recommendation["reason"] = "gateway_reconnect_governance_failure"
    elif status == "degraded" and not recommendation["reason"]:
        recommendation["reason"] = "gateway_reconnect_governance_degraded"

    return {
        "kind": "gateway_reconnect_governance",
        "schema": "a9.gateway_reconnect_governance.v1",
        "status": status,
        "state": {
            "contract_status": contract.get("status", ""),
            "reconnect_event_status": reconnect_event.get("status", ""),
            "runtime_action": recommendation.get("action", ""),
        },
        "contract": contract,
        "reconnect": {
            "latest_event": reconnect_event,
            "runtime_evidence": reconnect_evidence,
        },
        "runtime": {
            "governance_decision": recommendation,
        },
    }


def bool_field(value: Any) -> bool | None:
    text = str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def latest_gateway_transport_contract_event(limit: int = 50) -> dict[str, Any]:
    try:
        proc = redis_cli(["--raw", "XREVRANGE", EVENTS_STREAM_KEY, "+", "-", "COUNT", str(max(1, limit))])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "unavailable",
            "kind": "gateway_transport_contract",
            "reason": "redis_unavailable",
            "error": str(exc),
        }
    if proc.returncode != 0:
        return {
            "status": "unavailable",
            "kind": "gateway_transport_contract",
            "reason": "redis_command_failed",
            "error": proc.stdout.strip(),
        }
    for event in parse_xrange_events(proc.stdout):
        fields = event.get("fields", {})
        if not isinstance(fields, dict):
            continue
        if fields.get("kind") != "gateway_transport_contract" and fields.get("type") != "gateway_transport_contract":
            continue
        return {
            "status": str(fields.get("status") or "unknown"),
            "kind": "gateway_transport_contract",
            "event_id": event.get("id", ""),
            "capacity": parse_int(fields.get("capacity"), default=0),
            "overload_error_code": parse_int(fields.get("overload_error_code"), default=0),
            "request_overload_returns_retry_error": bool_field(fields.get("request_overload_returns_retry_error")),
            "response_waits_on_backpressure": bool_field(fields.get("response_waits_on_backpressure")),
            "writer_full_preserves_existing_message": bool_field(fields.get("writer_full_preserves_existing_message")),
            "ts": fields.get("ts", ""),
            "source": "redis_stream",
        }
    return {
        "status": "missing",
        "kind": "gateway_transport_contract",
        "reason": "no_gateway_transport_contract_event",
    }


def latest_gateway_reconnect_decision_event(limit: int = 50) -> dict[str, Any]:
    try:
        proc = redis_cli(["--raw", "XREVRANGE", EVENTS_STREAM_KEY, "+", "-", "COUNT", str(max(1, limit))])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "unavailable",
            "kind": "gateway_reconnect_decision",
            "reason": "redis_unavailable",
            "error": str(exc),
        }
    if proc.returncode != 0:
        return {
            "status": "unavailable",
            "kind": "gateway_reconnect_decision",
            "reason": "redis_command_failed",
            "error": proc.stdout.strip(),
        }
    for event in parse_xrange_events(proc.stdout):
        fields = event.get("fields", {})
        if not isinstance(fields, dict):
            continue
        if fields.get("kind") != "gateway_reconnect_decision" and fields.get("type") != "gateway_reconnect_decision":
            continue
        return {
            "status": "ok",
            "kind": "gateway_reconnect_decision",
            "event_id": event.get("id", ""),
            "phase": str(fields.get("phase") or ""),
            "action": str(fields.get("action") or ""),
            "error_class": str(fields.get("error_class") or ""),
            "attempt": parse_int(fields.get("attempt"), default=0),
            "delay_ms": parse_int(fields.get("delay_ms"), default=0),
            "policy_budget_remaining": parse_int(fields.get("policy_budget_remaining"), default=0),
            "flow_id": str(fields.get("flow_id") or ""),
            "flow_revision": parse_int(fields.get("flow_revision"), default=0),
            "node_id": str(fields.get("node_id") or ""),
            "origin": str(fields.get("origin") or ""),
            "reset_on_success": bool_field(fields.get("reset_on_success")),
            "ts": fields.get("ts", ""),
            "source": "redis_stream",
        }
    return {
        "status": "missing",
        "kind": "gateway_reconnect_decision",
        "flow_id": "",
        "flow_revision": 0,
        "node_id": "",
        "reason": "no_gateway_reconnect_decision_event",
    }


def safe_node_id(value: str) -> str:
    node_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())[:80].strip(".-")
    if not node_id:
        raise ValueError("node_id is required")
    return node_id


def ssh_target_host(target: str) -> str:
    raw = str(target or "").strip()
    without_user = raw.split("@", 1)[1] if "@" in raw else raw
    return without_user.rsplit(":", 1)[0].strip("[]")


def split_ssh_target(target: str) -> tuple[str, str]:
    raw = str(target or "").strip()
    if not raw:
        raise ValueError("ssh_target is required")
    if raw.endswith("]") or ":" not in raw:
        return raw, ""
    before_colon, after_colon = raw.rsplit(":", 1)
    if before_colon and after_colon.isdigit():
        return before_colon, after_colon
    return raw, ""


def transport_quality(target: str) -> dict[str, Any]:
    host = ssh_target_host(target)
    tailscale_installed = shutil.which("tailscale") is not None
    quality = "unknown"
    reason = "unclassified_ssh_target"
    recommended = "tailscale"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if host.endswith(".ts.net") or (ip and ipaddress.ip_address("100.64.0.1") <= ip <= ipaddress.ip_address("100.127.255.254")):
        quality = "tailscale"
        reason = "tailscale_target"
    elif host in {"127.0.0.1", "localhost", "::1"} or (ip and ip.is_loopback):
        quality = "degraded-loopback"
        reason = "loopback_is_not_a_real_remote_transport"
    elif ip and ip.is_private:
        quality = "private-ssh"
        reason = "private_network_ssh_target"
    return {
        "quality": quality,
        "reason": reason,
        "host": host,
        "tailscale_installed": tailscale_installed,
        "recommended": recommended,
        "warning": "" if quality in {"tailscale", "private-ssh"} else "prefer Tailscale or a private SSH target for stable phone takeover",
    }


def parse_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def node_hygiene(record: dict[str, Any]) -> dict[str, Any]:
    node_id = str(record.get("node_id") or "").strip().lower()
    labels = [str(item).strip().lower() for item in record.get("labels") or []]
    message = str(record.get("message") or "").strip().lower()
    ssh_target = str(record.get("ssh_target") or "")
    transport = transport_quality(ssh_target) if ssh_target else {
        "quality": "unknown",
        "reason": "missing_ssh_target",
        "host": "",
    }

    if "smoke" in node_id or "smoke" in message or any("smoke" in item for item in labels):
        return {
            "category": "test_smoke",
            "risk_scope": "noise",
            "reason": "smoke_marker",
            "recommended_action": "archive_if_stale",
            "transport_quality": transport.get("quality"),
        }
    if any(item in {"mobile-added", "mobile-probed"} for item in labels) or transport.get("quality") == "tailscale":
        return {
            "category": "remote_candidate",
            "risk_scope": "operational",
            "reason": "mobile_or_tailscale_marker",
            "recommended_action": "repair_or_reconnect",
            "transport_quality": transport.get("quality"),
        }
    if transport.get("quality") == "degraded-loopback":
        return {
            "category": "local_loopback",
            "risk_scope": "local",
            "reason": "loopback_target",
            "recommended_action": "observe_or_replace_with_tailscale",
            "transport_quality": transport.get("quality"),
        }
    return {
        "category": "unknown",
        "risk_scope": "operational",
        "reason": "unclassified_node",
        "recommended_action": "observe",
        "transport_quality": transport.get("quality"),
    }


def canonical_ssh_target(target: str) -> str:
    raw = str(target or "").strip().lower()
    if not raw:
        return ""
    ssh_target, port = split_ssh_target(raw)
    user = ""
    host = ssh_target
    if "@" in ssh_target:
        user, host = ssh_target.split("@", 1)
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        host = str(ip)
    except ValueError:
        host = host.strip("[]")
    if user and port:
        return f"{user}@{host}:{port}"
    if user:
        return f"{user}@{host}"
    if port:
        return f"{host}:{port}"
    return host


def node_freshness_seconds(record: dict[str, Any]) -> float:
    dt = parse_iso_datetime(str(record.get("last_heartbeat_at") or record.get("updated_at") or ""))
    return dt.timestamp() if dt else 0.0


def duplicate_target_groups(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        key = canonical_ssh_target(str(node.get("ssh_target") or ""))
        if not key:
            continue
        buckets.setdefault(key, []).append(node)
    groups = []
    for key, items in sorted(buckets.items()):
        if len(items) < 2:
            continue
        sorted_items = sorted(
            items,
            key=lambda item: (node_freshness_seconds(item), str(item.get("node_id") or "")),
            reverse=True,
        )
        primary = sorted_items[0]
        groups.append(
            {
                "target_key": key,
                "primary_node_id": str(primary.get("node_id") or ""),
                "node_ids": [str(item.get("node_id") or "") for item in sorted_items],
                "count": len(sorted_items),
            }
        )
    return groups


def tailscale_status() -> dict[str, Any]:
    binary = shutil.which("tailscale")
    if not binary:
        return {"status": "missing", "installed": False, "backend_state": "missing", "recommended": "install_tailscale"}
    socket = TAILSCALE_SOCKET if Path(TAILSCALE_SOCKET).exists() else "/var/run/tailscale/tailscaled.sock"
    cmd = [binary]
    if Path(socket).exists():
        cmd.extend(["--socket", socket])
    cmd.extend(["status", "--json"])
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "installed": True,
            "backend_state": "timeout",
            "socket": socket,
            "output": compact_text(str(exc), 1000),
        }
    if proc.returncode != 0:
        return {
            "status": "unavailable",
            "installed": True,
            "backend_state": "unavailable",
            "socket": socket,
            "output": compact_text(proc.stdout, 1000),
        }
    data = json.loads(proc.stdout)
    self_node = data.get("Self") or {}
    ips = data.get("TailscaleIPs") or self_node.get("TailscaleIPs") or []
    backend_state = str(data.get("BackendState") or "")
    return {
        "status": "ok" if backend_state == "Running" else "needs_login" if backend_state == "NeedsLogin" else "stopped",
        "installed": True,
        "version": data.get("Version"),
        "tun": data.get("TUN"),
        "backend_state": backend_state,
        "auth_url": data.get("AuthURL") or "",
        "tailscale_ips": ips,
        "dns_name": self_node.get("DNSName") or "",
        "hostname": self_node.get("HostName") or "",
        "online": bool(self_node.get("Online")),
        "magic_dns_suffix": data.get("MagicDNSSuffix") or "",
        "tailnet": data.get("CurrentTailnet"),
        "socket": socket,
        "health": data.get("Health") or [],
    }


def default_identity_file() -> str:
    path = Path(DEFAULT_SSH_IDENTITY_FILE)
    return str(path) if path.exists() else ""


def ssh_remote_command(target: str, remote_command: str, *, connect_timeout: int = 5, identity_file: str = "") -> list[str]:
    ssh_target, port = split_ssh_target(target)
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    identity = identity_file or default_identity_file()
    if identity:
        cmd.extend(["-i", identity])
    if port:
        cmd.extend(["-p", port])
    cmd.extend([ssh_target, remote_command])
    return cmd


def node_path(node_id: str, root: Path = ROOT) -> Path:
    return root / ".a9" / "nodes" / f"{safe_node_id(node_id)}.json"


def node_evidence_dir(node_id: str, root: Path = ROOT) -> Path:
    return root / ".a9" / "nodes" / "evidence" / safe_node_id(node_id)


def write_node_evidence(kind: str, node_id: str, payload: dict[str, Any], *, root: Path = ROOT) -> Path:
    safe_kind = re.sub(r"[^A-Za-z0-9_.-]+", "-", kind.strip())[:40].strip(".-") or "evidence"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = node_evidence_dir(node_id, root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{safe_kind}-{timestamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def list_node_evidence(node_id: str | None = None, *, root: Path = ROOT, limit: int = 20) -> dict[str, Any]:
    base = root / ".a9" / "nodes" / "evidence"
    if node_id:
        dirs = [node_evidence_dir(node_id, root)]
    else:
        dirs = [path for path in base.glob("*") if path.is_dir()] if base.exists() else []
    items: list[dict[str, Any]] = []
    for directory in dirs:
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            try:
                payload = read_json(path)
            except (json.JSONDecodeError, OSError):
                payload = {}
            stat = path.stat()
            kind = path.name.rsplit("-", 1)[0]
            items.append(
                {
                    "node_id": directory.name,
                    "kind": kind,
                    "status": payload.get("status"),
                    "target": payload.get("target"),
                    "session": payload.get("session"),
                    "path": str(path),
                    "bytes": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
                }
            )
    items.sort(key=lambda item: str(item["mtime"]), reverse=True)
    return {"status": "ok", "count": len(items), "items": items[: max(1, limit)]}


def controller_discovery() -> dict[str, Any]:
    return {
        "service": "a9-controller",
        "version": 1,
        "time": utc_now(),
        "endpoints": {
            "health": "/api/health",
            "status": "/api/status",
            "register_node": "/api/nodes/register",
            "heartbeat_node": "/api/nodes/heartbeat",
            "phone_control_status": "/api/phone-control/status",
            "phone_control_arm": "/api/phone-control/arm",
            "phone_control_disarm": "/api/phone-control/disarm",
            "submit": "/api/submit",
            "runtime_run_one": "/api/runtime/run-one",
            "runtime_session_refresh_trial": "/api/runtime/session-refresh-trial",
            "eval_override": "/api/eval/override",
            "gateway_transport_contract": "/api/gateway/transport-contract",
            "gateway_reconnect_decision": "/api/gateway/reconnect-decision",
            "gateway_reconnect_diagnostic": "/api/gateway/reconnect-diagnostic",
            "gateway_reconnect_governance": "/api/gateway/reconnect-governance",
            "gateway_health_refresh": "/api/gateway/health-refresh",
            "node_command_submit": "/api/nodes/command-submit",
            "node_command": "/api/nodes/command",
            "node_command_result": "/api/node-command-results/{result_event_id}",
            "node_command_result_by_command": "/api/node-command-results/by-command/{command_id}",
            "events": "/api/events",
        },
        "runtime": {
            "ssh_bootstrap": True,
            "redis_streams_target": True,
            "gateway_transport_contract": True,
            "gateway_reconnect_governance": True,
            "worker_claim_ready": False,
        },
        "events": {
            "url": "/api/events",
            "formats": ["json", "sse"],
            "query": ["last_id", "limit", "count", "format=sse"],
            "sse_cursor_hint": "include Last-Event-ID request header or last_id query for replay",
            "max_limit": EVENTS_STREAM_LIMIT_MAX,
        },
    }


def parse_duration_seconds(value: Any, *, default_seconds: int = 600) -> int:
    raw = str(value or "").strip().lower()
    if not raw:
        return default_seconds
    match = re.fullmatch(r"(\d+)(s|m|h|d)", raw)
    if not match:
        raise ValueError("duration must look like 30s, 10m, 2h, or 1d")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError("duration must be positive")
    unit = match.group(2)
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return amount * multiplier


def phone_control_path(root: Path = ROOT) -> Path:
    return root / PHONE_CONTROL_REL_PATH


def phone_control_commands_for_group(group: str) -> list[str]:
    normalized = str(group or "").strip().lower()
    if normalized == "all":
        return sorted({cmd for commands in PHONE_CONTROL_GROUPS.values() for cmd in commands})
    if normalized not in PHONE_CONTROL_GROUPS:
        raise ValueError(f"group must be one of: {', '.join([*PHONE_CONTROL_GROUPS, 'all'])}")
    return sorted(PHONE_CONTROL_GROUPS[normalized])


def read_phone_control_state(root: Path = ROOT) -> dict[str, Any] | None:
    path = phone_control_path(root)
    if not path.exists():
        return None
    try:
        state = read_json(path)
    except (json.JSONDecodeError, OSError):
        return None
    if state.get("version") != 1:
        return None
    expires_raw = str(state.get("expires_at") or "")
    try:
        expires_at = datetime.fromisoformat(expires_raw)
    except ValueError:
        return None
    if expires_at <= utc_now_dt():
        return None
    return state


def write_phone_control_state(state: dict[str, Any] | None, *, root: Path = ROOT) -> None:
    path = phone_control_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not state:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_phone_admin(payload: dict[str, Any]) -> None:
    scopes = payload.get("operator_scopes") or payload.get("scopes") or []
    if isinstance(scopes, str):
        scopes = [scopes]
    if PHONE_ADMIN_SCOPE not in [str(scope) for scope in scopes]:
        raise PermissionError("phone control mutation requires operator.admin")


def phone_control_status(*, root: Path = ROOT) -> dict[str, Any]:
    state = read_phone_control_state(root)
    if not state:
        write_phone_control_state(None, root=root)
        return {
            "status": "disarmed",
            "armed": False,
            "groups": sorted([*PHONE_CONTROL_GROUPS, "all"]),
            "commands": [],
            "known_commands": KNOWN_CONTROL_COMMANDS,
        }
    return {
        "status": "armed",
        "armed": True,
        "group": state.get("group"),
        "commands": state.get("commands", []),
        "known_commands": KNOWN_CONTROL_COMMANDS,
        "armed_at": state.get("armed_at"),
        "expires_at": state.get("expires_at"),
        "source": state.get("source", "control-api"),
    }


def phone_control_arm(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    require_phone_admin(payload)
    group = str(payload.get("group") or "runtime").strip().lower()
    commands = phone_control_commands_for_group(group)
    duration_seconds = parse_duration_seconds(payload.get("duration"), default_seconds=600)
    now = utc_now_dt()
    state = {
        "version": 1,
        "status": "armed",
        "group": group,
        "commands": commands,
        "armed_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(seconds=duration_seconds)).isoformat(timespec="seconds"),
        "source": str(payload.get("source") or "control-api"),
    }
    write_phone_control_state(state, root=root)
    return phone_control_status(root=root)


def phone_control_disarm(payload: dict[str, Any] | None = None, *, root: Path = ROOT) -> dict[str, Any]:
    require_phone_admin(payload or {})
    write_phone_control_state(None, root=root)
    return phone_control_status(root=root)


def command_gate(command: str, *, root: Path = ROOT) -> dict[str, Any]:
    normalized = str(command or "").strip()
    if not normalized:
        raise ValueError("command is required")
    if normalized not in KNOWN_CONTROL_COMMANDS:
        return {
            "status": "unknown",
            "allowed": False,
            "command": normalized,
            "reason": "unknown_command",
            "required_gate": "registered_control_command",
        }
    state = read_phone_control_state(root)
    if not state:
        return {
            "status": "blocked",
            "allowed": False,
            "command": normalized,
            "reason": "phone_control_disarmed",
            "required_gate": "phone_control_arm",
        }
    commands = [str(item) for item in state.get("commands", [])]
    if normalized not in commands:
        return {
            "status": "blocked",
            "allowed": False,
            "command": normalized,
            "reason": "command_not_in_current_arm_group",
            "required_gate": "phone_control_arm_matching_group",
            "armed_group": state.get("group"),
            "armed_commands": commands,
            "expires_at": state.get("expires_at"),
        }
    return {
        "status": "allowed",
        "allowed": True,
        "command": normalized,
        "reason": "phone_control_armed",
        "armed_group": state.get("group"),
        "expires_at": state.get("expires_at"),
    }


def infer_remote_audit_node_id(payload: dict[str, Any], result: dict[str, Any] | None = None) -> str:
    for source in (result or {}, payload):
        for key in ("node_id", "ssh_target", "target"):
            value = source.get(key)
            if value:
                return str(value)
    return ""


def build_remote_post_audit_receipt(
    command: str,
    endpoint: str,
    gate: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    receipt = {
        "request_id": str((payload or {}).get("request_id") or ""),
        "command": command,
        "endpoint": endpoint,
        "gate_status": gate.get("status"),
        "gate_reason": gate.get("reason"),
        "allowed": bool(gate.get("allowed")),
        "result_status": (result or {}).get("status") or ("allowed" if gate.get("allowed") else "blocked"),
        "action_evidence_path": str((result or {}).get("evidence_path") or ""),
        "evidence_path": "",
        "at": utc_now(),
    }
    node_id = infer_remote_audit_node_id(payload or {}, result)
    if node_id:
        evidence_path = write_node_evidence("remote-post-audit", node_id, receipt, root=root)
        receipt["evidence_path"] = str(evidence_path)
    return receipt


def guarded_remote_post(
    command: str,
    payload: dict[str, Any],
    action: Any,
    *,
    endpoint: str,
    root: Path = ROOT,
) -> tuple[int, dict[str, Any]]:
    gate = command_gate(command, root=root)
    if not gate.get("allowed"):
        audit_receipt = build_remote_post_audit_receipt(command, endpoint, gate, payload=payload, root=root)
        return 403, {"status": "blocked", "gate": gate, "audit_receipt": audit_receipt}

    result = action(payload)
    if not isinstance(result, dict):
        result = {"status": "ok", "result": result}
    audit_receipt = build_remote_post_audit_receipt(command, endpoint, gate, result=result, payload=payload, root=root)
    return 200, {**result, "audit_receipt": audit_receipt}


def node_status(root: Path = ROOT) -> dict[str, Any]:
    nodes_dir = root / ".a9" / "nodes"
    nodes = []
    if nodes_dir.exists():
        for path in sorted(nodes_dir.glob("*.json"), key=lambda item: item.stat().st_mtime):
            try:
                record = enrich_node_connection(read_json(path))
                record = enrich_node_tmux_action(record, root=root)
                record = enrich_node_probe_evidence(record, root=root)
                record = enrich_node_heartbeat_start_evidence(record, root=root)
                record["hygiene"] = node_hygiene(record)
                record = enrich_node_recovery_plan(record)
                nodes.append(record)
            except json.JSONDecodeError:
                nodes.append({"node_id": path.stem, "status": "invalid", "connection_state": "invalid"})
    tasks_stream = redis_tasks_stream_probe()
    return {
        "count": len(nodes),
        "nodes": nodes[-50:],
        "redis": redis_node_hot_status(),
        "tasks_stream": tasks_stream,
        "communication_followup": communication_followup_intent(nodes[-50:], tasks_stream),
    }


def node_connection_summary(root: Path = ROOT) -> dict[str, Any]:
    status = node_status(root)
    nodes = status.get("nodes", [])
    connection_states: dict[str, int] = {}
    recovery_actions: dict[str, int] = {}
    connection_actions: dict[str, int] = {}
    tmux_actions: dict[str, int] = {}
    hygiene_categories: dict[str, int] = {}
    risk_nodes: list[dict[str, Any]] = []
    skipped_noise_nodes: list[dict[str, Any]] = []
    duplicate_nodes: list[dict[str, Any]] = []
    seen_operational_targets: dict[str, str] = {}
    evidence_paths: list[str] = []
    duplicate_groups = duplicate_target_groups(nodes)
    duplicate_primary_by_target = {
        str(group.get("target_key") or ""): str(group.get("primary_node_id") or "")
        for group in duplicate_groups
    }

    for node in nodes:
        node_id = str(node.get("node_id") or "")
        target_key = canonical_ssh_target(str(node.get("ssh_target") or ""))
        state = str(node.get("connection_state") or "unknown")
        connection_states[state] = connection_states.get(state, 0) + 1
        summary_action = str(node.get("action") or "unknown")
        connection_actions[summary_action] = connection_actions.get(summary_action, 0) + 1

        plan = node.get("recovery_plan") if isinstance(node.get("recovery_plan"), dict) else {}
        recovery_action = str(plan.get("action") or "unknown")
        recovery_actions[recovery_action] = recovery_actions.get(recovery_action, 0) + 1

        tmux_action = str(node.get("tmux_action") or "unknown")
        tmux_actions[tmux_action] = tmux_actions.get(tmux_action, 0) + 1
        hygiene = node.get("hygiene") if isinstance(node.get("hygiene"), dict) else node_hygiene(node)
        hygiene_category = str(hygiene.get("category") or "unknown")
        hygiene_categories[hygiene_category] = hygiene_categories.get(hygiene_category, 0) + 1

        for key in (
            "tmux_evidence_path",
            "probe_evidence_path",
            "heartbeat_start_evidence_path",
            "last_probe_evidence_path",
        ):
            value = str(node.get(key) or "")
            if value and value not in evidence_paths:
                evidence_paths.append(value)

        if hygiene.get("risk_scope") == "noise" and recovery_action in {"quarantine", "probe", "tmux", "heartbeat"}:
            skipped_noise_nodes.append(
                {
                    "node_id": node.get("node_id"),
                    "ssh_target": node.get("ssh_target"),
                    "connection_state": state,
                    "recovery_action": recovery_action,
                    "hygiene": hygiene,
                }
            )
            continue

        if target_key:
            primary_node_id = duplicate_primary_by_target.get(target_key)
            if primary_node_id and node_id != primary_node_id:
                duplicate_nodes.append(
                    {
                        "node_id": node.get("node_id"),
                        "ssh_target": node.get("ssh_target"),
                        "target_key": target_key,
                        "primary_node_id": primary_node_id,
                        "connection_state": state,
                        "recovery_action": recovery_action,
                        "hygiene": hygiene,
                    }
                )
                continue
            if target_key in seen_operational_targets:
                duplicate_nodes.append(
                    {
                        "node_id": node.get("node_id"),
                        "ssh_target": node.get("ssh_target"),
                        "target_key": target_key,
                        "primary_node_id": seen_operational_targets[target_key],
                        "connection_state": state,
                        "recovery_action": recovery_action,
                        "hygiene": hygiene,
                    }
                )
                continue
            seen_operational_targets[target_key] = node_id

        if state in {"stale", "offline", "degraded", "disconnected", "needs_repair", "unknown"} or recovery_action not in {"observe"}:
            risk_nodes.append(
                {
                    "node_id": node_id,
                    "ssh_target": node.get("ssh_target"),
                    "target_key": target_key,
                    "connection_state": state,
                    "connection_action": node.get("connection_action"),
                    "action": str(node.get("action") or ""),
                    "retry_delay_ms": node.get("retry_delay_ms"),
                    "connection_evidence_path": str(node.get("probe_evidence_path") or ""),
                    "recovery_action": recovery_action,
                    "requires_operator": bool(plan.get("requires_operator")) if plan else False,
                    "route": plan.get("route") if plan else None,
                    "hygiene": hygiene,
                }
            )

    return {
        "status": "ok",
        "generated_at": utc_now(),
        "count": status.get("count", len(nodes)),
        "connection_states": connection_states,
        "connection_actions": connection_actions,
        "recovery_actions": recovery_actions,
        "tmux_actions": tmux_actions,
        "hygiene_categories": hygiene_categories,
        "risk_count": len(risk_nodes),
        "risk_nodes": risk_nodes,
        "duplicate_target_groups": duplicate_groups,
        "duplicate_node_count": len(duplicate_nodes),
        "duplicate_nodes": duplicate_nodes,
        "skipped_noise_count": len(skipped_noise_nodes),
        "skipped_noise_nodes": skipped_noise_nodes,
        "latest_evidence_paths": evidence_paths[-20:],
        "communication_followup": status.get("communication_followup"),
    }


def _node_recovery_action_payload(node: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    result = {
        "node_id": str(node.get("node_id") or ""),
        "ssh_target": str(node.get("ssh_target") or ""),
        "target": str(node.get("ssh_target") or ""),
        "connect_timeout": int(payload.get("connect_timeout") or 5),
        "timeout_seconds": int(payload.get("timeout_seconds") or 20),
        "operator_scopes": payload.get("operator_scopes") or payload.get("scopes") or [],
        "request_id": str(payload.get("request_id") or ""),
    }
    if payload.get("identity_file"):
        result["identity_file"] = str(payload.get("identity_file"))
    return result


def node_recovery_cycle(payload: dict[str, Any] | None = None, *, root: Path = ROOT) -> dict[str, Any]:
    payload = payload or {}
    execute = bool(payload.get("execute") or payload.get("apply"))
    include_noise = parse_truthy(payload.get("include_noise"))
    include_duplicates = parse_truthy(payload.get("include_duplicates"))
    try:
        max_actions = max(1, int(payload.get("max_actions") or payload.get("max_nodes") or 3))
    except (TypeError, ValueError):
        max_actions = 3
    requested_node_id = safe_node_id(str(payload.get("node_id") or "")) if payload.get("node_id") else ""
    status = node_status(root)
    nodes = status.get("nodes") if isinstance(status.get("nodes"), list) else []
    steps: list[dict[str, Any]] = []
    duplicate_groups = duplicate_target_groups(nodes)
    duplicate_primary_by_target = {
        str(group.get("target_key") or ""): str(group.get("primary_node_id") or "")
        for group in duplicate_groups
    }
    skipped_duplicates: list[dict[str, Any]] = []
    recovery_gate = command_gate("nodes.recovery.cycle", root=root) if execute else {
        "status": "not_required",
        "allowed": True,
        "command": "nodes.recovery.cycle",
        "reason": "planning_only",
    }
    if execute and not recovery_gate.get("allowed"):
        result = {
            "status": "blocked",
            "kind": "node_recovery_cycle",
            "generated_at": utc_now(),
            "execute": execute,
            "include_noise": include_noise,
            "include_duplicates": include_duplicates,
            "max_actions": max_actions,
            "node_id": requested_node_id,
            "step_count": 0,
            "steps": [],
            "gate": recovery_gate,
            "summary": node_connection_summary(root),
        }
        evidence_path = write_node_evidence("recovery-cycle", requested_node_id or "all", result, root=root)
        return {**result, "evidence_path": str(evidence_path)}

    for node in nodes:
        if requested_node_id and str(node.get("node_id") or "") != requested_node_id:
            continue
        hygiene = node.get("hygiene") if isinstance(node.get("hygiene"), dict) else node_hygiene(node)
        plan = node.get("recovery_plan") if isinstance(node.get("recovery_plan"), dict) else node_recovery_plan(node)
        recovery_action = str(plan.get("action") or "")
        route = plan.get("route") if isinstance(plan.get("route"), dict) else {}
        if recovery_action in {"observe", "none"}:
            continue
        if not include_noise and not requested_node_id and hygiene.get("risk_scope") == "noise":
            continue
        target_key = canonical_ssh_target(str(node.get("ssh_target") or ""))
        primary_node_id = duplicate_primary_by_target.get(target_key)
        node_id = str(node.get("node_id") or "")
        if (
            not include_duplicates
            and not requested_node_id
            and target_key
            and primary_node_id
            and node_id != primary_node_id
        ):
            skipped_duplicates.append(
                {
                    "node_id": node_id,
                    "ssh_target": str(node.get("ssh_target") or ""),
                    "target_key": target_key,
                    "primary_node_id": primary_node_id,
                    "hygiene": hygiene,
                }
            )
            continue
        if len(steps) >= max_actions:
            break

        action_payload = _node_recovery_action_payload(node, payload)
        step: dict[str, Any] = {
            "node_id": node_id,
            "ssh_target": str(node.get("ssh_target") or ""),
            "target_key": target_key,
            "recovery_action": recovery_action,
            "reason": str(plan.get("reason") or ""),
            "route": route,
            "execute": execute,
            "status": "planned",
            "result": None,
            "evidence_path": "",
            "hygiene": hygiene,
        }

        try:
            if recovery_action == "probe":
                if execute:
                    status_code, result = guarded_remote_post(
                        "nodes.probe.execute",
                        action_payload,
                        lambda item: probe_node(item, root=root),
                        endpoint="/api/nodes/probe",
                        root=root,
                    )
                    step.update({"status": "executed" if status_code == 200 else "blocked", "result": result})
                else:
                    step["result"] = {"status": "planned", "endpoint": "/api/nodes/probe", "payload": action_payload}

            elif recovery_action == "tmux":
                evidence_path = str(node.get("tmux_evidence_path") or "")
                if not evidence_path or "tmux-plan-" not in Path(evidence_path).name:
                    plan_payload = {
                        **action_payload,
                        "session": payload.get("session") or "a9",
                        "remote_dir": payload.get("remote_dir") or "~/a9-worker",
                    }
                    tmux_plan = tmux_plan_node(plan_payload, root=root)
                    evidence_path = str(tmux_plan.get("evidence_path") or "")
                    step["prepared_plan"] = tmux_plan
                action_payload["evidence_path"] = evidence_path
                endpoint = str(route.get("endpoint") or "/api/nodes/tmux-ensure")
                if execute:
                    if endpoint == "/api/nodes/tmux-status":
                        status_code, result = guarded_remote_post(
                            "nodes.tmux.status",
                            action_payload,
                            lambda item: tmux_status_node(item, root=root),
                            endpoint="/api/nodes/tmux-status",
                            root=root,
                        )
                        step.update({"status": "executed" if status_code == 200 else "blocked", "result": result})
                    else:
                        result = tmux_ensure_node(action_payload, root=root)
                        step.update({"status": "executed" if result.get("status") != "blocked" else "blocked", "result": result})
                else:
                    step["result"] = {"status": "planned", "endpoint": endpoint, "payload": action_payload}

            elif recovery_action == "heartbeat_start":
                plan_payload = {
                    **action_payload,
                    "session": payload.get("heartbeat_session") or "a9-heartbeat",
                    "remote_dir": payload.get("remote_dir") or "~/a9-worker",
                    "controller_url": payload.get("controller_url") or "",
                    "heartbeat_interval": payload.get("heartbeat_interval") or 30,
                }
                heartbeat_plan = heartbeat_tmux_plan_node(plan_payload, root=root)
                action_payload["evidence_path"] = str(heartbeat_plan.get("evidence_path") or "")
                step["prepared_plan"] = heartbeat_plan
                if execute:
                    result = heartbeat_tmux_start_node(action_payload, root=root)
                    step.update({"status": "executed" if result.get("status") != "blocked" else "blocked", "result": result})
                else:
                    step["result"] = {"status": "planned", "endpoint": "/api/nodes/heartbeat-tmux-start", "payload": action_payload}

            elif recovery_action == "quarantine":
                step["status"] = "manual_required"
                step["result"] = {
                    "status": "manual_required",
                    "reason": str(plan.get("reason") or "quarantine_required"),
                    "steps": plan.get("steps") if isinstance(plan.get("steps"), list) else [],
                    "requires_operator": True,
                }

            else:
                step["status"] = "noop"
                step["result"] = {"status": "noop", "reason": "unsupported_recovery_action"}

        except Exception as exc:
            step.update({"status": "failed", "result": {"status": "failed", "error": str(exc)}})

        if isinstance(step.get("result"), dict):
            step["evidence_path"] = str(step["result"].get("evidence_path") or "")
        steps.append(step)

    overall_status = "ok"
    if any(step.get("status") == "failed" for step in steps):
        overall_status = "degraded"
    elif any(step.get("status") == "blocked" for step in steps):
        overall_status = "blocked"
    elif any(step.get("status") == "manual_required" for step in steps):
        overall_status = "needs_attention"
    result = {
        "status": overall_status,
        "kind": "node_recovery_cycle",
        "generated_at": utc_now(),
        "execute": execute,
        "include_noise": include_noise,
        "include_duplicates": include_duplicates,
        "max_actions": max_actions,
        "node_id": requested_node_id,
        "step_count": len(steps),
        "steps": steps,
        "skipped_duplicate_count": len(skipped_duplicates),
        "skipped_duplicates": skipped_duplicates,
        "gate": recovery_gate,
        "summary": node_connection_summary(root),
    }
    evidence_path = write_node_evidence("recovery-cycle", requested_node_id or "all", result, root=root)
    return {**result, "evidence_path": str(evidence_path)}


def node_connection_action(connection_state: str) -> tuple[str, str]:
    if connection_state == "online":
        return ("continue", "heartbeat_fresh")
    if connection_state == "stale":
        return ("reconnect", "heartbeat_stale")
    if connection_state == "degraded":
        return ("reconnect", "heartbeat_reported_degraded")
    if connection_state == "offline":
        return ("quarantine", "heartbeat_offline")
    return ("reconnect", "heartbeat_unknown")


def node_recovery_plan(record: dict[str, Any]) -> dict[str, Any]:
    connection_action = str(record.get("connection_action") or "")
    connection_state = str(record.get("connection_state") or "")
    connection_reason = str(record.get("connection_action_reason") or "")
    probe_action = str(record.get("probe_action") or "")
    tmux_action = str(record.get("tmux_action") or "")
    heartbeat_start_action = str(record.get("heartbeat_start_action") or "")

    if connection_action in {"continue", "watch"} or connection_state == "online":
        return {
            "action": "observe",
            "reason": connection_reason or "healthy",
            "steps": [],
            "requires_operator": False,
            "route": {
                "method": None,
                "endpoint": None,
                "command": None,
                "requires_arm": False,
            },
        }

    if connection_action == "quarantine" or connection_state == "offline":
        return {
            "action": "quarantine",
            "reason": connection_reason or "heartbeat_offline",
            "steps": [
                "verify_ssh_target_reachable",
                "verify_tailscale_and_tmux_state",
                "run_manual_recovery_before_resume",
            ],
            "requires_operator": True,
            "route": {
                "method": None,
                "endpoint": None,
                "command": None,
                "requires_arm": False,
            },
        }

    if probe_action in {"retry", "repair"}:
        return {
            "action": "probe",
            "reason": str(record.get("probe_action_reason") or "probe_required"),
            "steps": ["run_node_communication_probe", "refresh_node_status"],
            "requires_operator": False,
            "route": {
                "method": "POST",
                "endpoint": "/api/nodes/probe",
                "command": "nodes.probe.execute",
                "requires_arm": True,
            },
        }

    if tmux_action in {"retry", "repair", "wait_for_approval"}:
        endpoint = "/api/nodes/tmux-status" if tmux_action == "wait_for_approval" else "/api/nodes/tmux-ensure"
        command = "nodes.tmux.status" if tmux_action == "wait_for_approval" else "nodes.tmux.ensure"
        return {
            "action": "tmux",
            "reason": str(record.get("tmux_action_reason") or "tmux_repair_required"),
            "steps": ["ensure_tmux_session", "refresh_node_status"],
            "requires_operator": tmux_action == "wait_for_approval",
            "route": {
                "method": "POST",
                "endpoint": endpoint,
                "command": command,
                "requires_arm": True,
            },
        }

    if heartbeat_start_action in {"retry", "repair"}:
        return {
            "action": "heartbeat_start",
            "reason": str(record.get("heartbeat_start_action_reason") or "heartbeat_start_required"),
            "steps": ["start_heartbeat_tmux", "refresh_node_status"],
            "requires_operator": False,
            "route": {
                "method": "POST",
                "endpoint": "/api/nodes/heartbeat-tmux-start",
                "command": "nodes.heartbeat.tmux.start",
                "requires_arm": True,
            },
        }

    if connection_action == "reconnect" or connection_state in {"stale", "degraded", "unknown"}:
        return {
            "action": "observe",
            "reason": connection_reason or "reconnect_required",
            "steps": ["refresh_node_status"],
            "requires_operator": False,
            "route": {
                "method": None,
                "endpoint": None,
                "command": None,
                "requires_arm": False,
            },
        }

    return {
        "action": "none",
        "reason": connection_reason or "no_recovery_needed",
        "steps": [],
        "requires_operator": False,
        "route": {
            "method": None,
            "endpoint": None,
            "command": None,
            "requires_arm": False,
        },
    }


def enrich_node_recovery_plan(record: dict[str, Any]) -> dict[str, Any]:
    return {**record, "recovery_plan": node_recovery_plan(record)}


def probe_action_to_followup(probe_action: Any, probe_action_reason: Any = "") -> dict[str, str]:
    return supervisor().probe_action_to_followup(probe_action, probe_action_reason)


def communication_followup_intent(nodes: list[dict[str, Any]], tasks_stream: dict[str, Any]) -> dict[str, Any]:
    action_priority = {"continue": 1, "watch": 2, "reconnect": 3, "intervene": 4, "quarantine": 5}
    status_by_action = {
        "continue": "ok",
        "watch": "degraded",
        "reconnect": "degraded",
        "intervene": "needs_attention",
        "quarantine": "needs_attention",
    }
    best = {
        "priority": action_priority["continue"],
        "action": "continue",
        "reason": "healthy",
        "status": status_by_action["continue"],
        "evidence": {"nodes": [], "tasks_stream": {"action": "continue", "reason": "none"}},
    }
    duplicate_primary_by_target = {
        str(group.get("target_key") or ""): str(group.get("primary_node_id") or "")
        for group in duplicate_target_groups(nodes)
    }
    for node in nodes:
        hygiene = node.get("hygiene") if isinstance(node.get("hygiene"), dict) else node_hygiene(node)
        if hygiene.get("risk_scope") == "noise":
            continue
        target_key = canonical_ssh_target(str(node.get("ssh_target") or ""))
        node_id = str(node.get("node_id") or "")
        primary_node_id = duplicate_primary_by_target.get(target_key)
        if target_key and primary_node_id and node_id != primary_node_id:
            continue
        action = str(node.get("connection_action") or "continue")
        if action not in action_priority:
            continue
        priority = action_priority[action]
        if priority < best["priority"]:
            continue
        node_evidence = {
            "node_id": node_id,
            "target_key": target_key,
            "connection_state": str(node.get("connection_state") or ""),
            "action": action,
            "reason": str(node.get("connection_action_reason") or ""),
            "recovery_plan": node.get("recovery_plan") or node_recovery_plan(node),
            "hygiene": hygiene,
        }
        if priority == best["priority"] and best["reason"].startswith("node:") and best["action"] == action:
            best["evidence"]["nodes"].append(node_evidence)
            continue
        best = {
            "priority": priority,
            "action": action,
            "reason": f"node:{node.get('connection_action_reason') or 'unknown'}",
            "status": status_by_action[action],
            "evidence": {
                "nodes": [node_evidence],
                "tasks_stream": {
                    "action": str(tasks_stream.get("stream_action") or "continue"),
                    "reason": str(tasks_stream.get("stream_action_reason") or "none"),
                },
            },
        }
    stream_action = str(tasks_stream.get("stream_action") or "continue")
    if stream_action in action_priority and action_priority[stream_action] >= best["priority"]:
        best = {
            "priority": action_priority[stream_action],
            "action": stream_action,
            "reason": f"tasks_stream:{tasks_stream.get('stream_action_reason') or 'none'}",
            "status": status_by_action[stream_action],
            "evidence": {
                "nodes": [],
                "tasks_stream": {
                    "action": stream_action,
                    "reason": str(tasks_stream.get("stream_action_reason") or "none"),
                    "status": str(tasks_stream.get("status") or ""),
                },
            },
        }
    return {
        "action": best["action"],
        "reason": best["reason"],
        "status": best["status"],
        "evidence": best["evidence"],
    }


def enrich_node_connection(record: dict[str, Any]) -> dict[str, Any]:
    heartbeat_at = parse_iso_datetime(str(record.get("last_heartbeat_at") or record.get("updated_at") or ""))
    reported_status = str(record.get("status") or "").strip().lower()
    reported_degraded = reported_status in {"degraded", "error", "failed"}
    if not heartbeat_at:
        action, reason = node_connection_action("unknown")
        return {
            **record,
            "connection_state": "unknown",
            "connection_action": action,
            "connection_action_reason": reason,
            "last_seen_age_seconds": None,
        }
    age = max(0, int((utc_now_dt() - heartbeat_at).total_seconds()))
    if age <= NODE_ONLINE_TTL_SECONDS:
        state = "online"
    elif age <= NODE_STALE_TTL_SECONDS:
        state = "stale"
    else:
        state = "offline"
    if reported_degraded and state != "offline":
        state = "degraded"
    action, reason = node_connection_action(state)
    return {
        **record,
        "connection_state": state,
        "connection_action": action,
        "connection_action_reason": reason,
        "last_seen_age_seconds": age,
        "heartbeat_ttl_seconds": NODE_ONLINE_TTL_SECONDS,
    }


def latest_tmux_action_for_node(node_id: str, *, root: Path = ROOT) -> dict[str, Any] | None:
    evidence_dir = node_evidence_dir(node_id, root)
    if not evidence_dir.exists():
        return None
    candidates = sorted(
        evidence_dir.glob("tmux-*.json"),
        key=lambda item: (item.stat().st_mtime, item.name.rsplit("-", 1)[-1]),
        reverse=True,
    )
    for path in candidates:
        try:
            payload = read_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        action = payload.get("tmux_action")
        reason = payload.get("tmux_action_reason") or payload.get("reason")
        if not action:
            continue
        return {
            "tmux_action": str(action),
            "tmux_action_reason": str(reason or ""),
            "tmux_status": str(payload.get("status") or ""),
            "tmux_evidence_path": str(path),
        }
    return None


def latest_probe_evidence_for_node(node_id: str, *, root: Path = ROOT) -> dict[str, Any] | None:
    evidence_dir = node_evidence_dir(node_id, root)
    if not evidence_dir.exists():
        return None
    candidates = sorted(
        evidence_dir.glob("probe*.json"),
        key=lambda item: (item.stat().st_mtime, item.name.rsplit("-", 1)[-1]),
        reverse=True,
    )
    for path in candidates:
        try:
            payload = read_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        action = payload.get("probe_action")
        if not action:
            continue
        result = {
            "probe_status": str(payload.get("status") or ""),
            "probe_action": str(action),
            "probe_action_reason": str(payload.get("probe_action_reason") or ""),
            "probe_return_code": payload.get("return_code"),
            "probe_timed_out": bool(payload.get("timed_out")),
            "probe_checked_at": str(payload.get("checked_at") or ""),
            "probe_evidence_path": str(path),
        }
        connection_summary = payload.get("connection_summary") if isinstance(payload, dict) else None
        if isinstance(connection_summary, dict):
            try:
                retry_delay_ms = int(connection_summary.get("retry_delay_ms") or 0)
            except (TypeError, ValueError):
                retry_delay_ms = 0
            result.update(
                {
                    "connection_state": str(connection_summary.get("connection_state") or ""),
                    "action": str(connection_summary.get("action") or ""),
                    "action_reason": str(connection_summary.get("action_reason") or ""),
                    "retry_delay_ms": retry_delay_ms,
                }
            )
        return result
    return None


def latest_heartbeat_start_evidence_for_node(node_id: str, *, root: Path = ROOT) -> dict[str, Any] | None:
    evidence_dir = node_evidence_dir(node_id, root)
    if not evidence_dir.exists():
        return None
    candidates = sorted(
        evidence_dir.glob("heartbeat-tmux-start*.json"),
        key=lambda item: (item.stat().st_mtime, item.name.rsplit("-", 1)[-1]),
        reverse=True,
    )
    for path in candidates:
        try:
            payload = read_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        action = payload.get("heartbeat_action")
        if not action:
            continue
        return {
            "heartbeat_start_status": str(payload.get("status") or ""),
            "heartbeat_start_action": str(action),
            "heartbeat_start_action_reason": str(payload.get("heartbeat_action_reason") or ""),
            "heartbeat_start_return_code": payload.get("return_code"),
            "heartbeat_start_timed_out": bool(payload.get("timed_out")),
            "heartbeat_start_executed_at": str(payload.get("executed_at") or ""),
            "heartbeat_start_evidence_path": str(path),
        }
    return None


def enrich_node_tmux_action(record: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    node_id = str(record.get("node_id") or "")
    if not node_id:
        return record
    tmux = latest_tmux_action_for_node(node_id, root=root)
    if not tmux:
        return record
    return {**record, **tmux}


def enrich_node_probe_evidence(record: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    node_id = str(record.get("node_id") or "")
    if not node_id:
        return record
    probe = latest_probe_evidence_for_node(node_id, root=root)
    if not probe:
        return record
    return {**record, **probe}


def enrich_node_heartbeat_start_evidence(record: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    node_id = str(record.get("node_id") or "")
    if not node_id:
        return record
    heartbeat_start = latest_heartbeat_start_evidence_for_node(node_id, root=root)
    if not heartbeat_start:
        return record
    return {**record, **heartbeat_start}


def redis_node_hot_status() -> dict[str, Any]:
    if not redis_available():
        return {"status": "unavailable", "hot_path": False}
    try:
        stream = redis_cli(["XLEN", "a9:heartbeats"])
        events = redis_cli(["XLEN", "a9:events"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "unavailable", "hot_path": False, "error": str(exc)}
    return {
        "status": "ok" if stream.returncode == 0 else "degraded",
        "hot_path": stream.returncode == 0,
        "heartbeats_stream_len": int(stream.stdout.strip() or "0") if stream.returncode == 0 else None,
        "events_stream_len": int(events.stdout.strip() or "0") if events.returncode == 0 else None,
    }


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_xinfo_groups_rows(output: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    rows: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for index in range(0, len(lines) - 1, 2):
        key = lines[index]
        value = lines[index + 1]
        if key == "name" and current:
            rows.append(current)
            current = {}
        current[key] = value
    if current:
        rows.append(current)
    return rows


def parse_xpending_total(output: str) -> int | None:
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    if not lines:
        return None
    return parse_int(lines[0], default=-1)


def parse_xinfo_consumers_rows(output: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    rows: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for index in range(0, len(lines) - 1, 2):
        key = lines[index]
        value = lines[index + 1]
        if key == "name" and current:
            rows.append(current)
            current = {}
        current[key] = value
    if current:
        rows.append(current)
    return rows


def xinfo_consumers_rows_malformed(output: str, rows: list[dict[str, str]]) -> bool:
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    if len(lines) % 2 != 0:
        return True
    if not lines:
        return False
    for row in rows:
        if not row.get("name"):
            return True
        if parse_int(row.get("pending"), default=-1) < 0:
            return True
        if parse_int(row.get("idle"), default=-1) < 0:
            return True
    return False


def redis_tasks_stream_probe() -> dict[str, Any]:
    def early_result(*, status: str, reason: str, error: str | None = None) -> dict[str, Any]:
        action_by_reason = {
            "redis_unavailable": "intervene",
            "redis_probe_error": "intervene",
            "xinfo_groups_failed": "intervene",
            "consumer_group_missing": "watch",
            "invalid_lag": "watch",
        }
        result: dict[str, Any] = {
            "status": status,
            "reason": reason,
            "lag": None,
            "pending": None,
            "thresholds_version": "redis_streams_v1",
            "stream_action": action_by_reason.get(reason, "watch"),
            "stream_action_reason": reason,
        }
        if error is not None:
            result["error"] = error
        return result

    if not redis_available():
        return early_result(status="unavailable", reason="redis_unavailable")
    try:
        groups = redis_cli(["--raw", "XINFO", "GROUPS", TASKS_STREAM_KEY])
        pending = redis_cli(["--raw", "XPENDING", TASKS_STREAM_KEY, TASKS_STREAM_GROUP])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return early_result(status="degraded", reason="redis_probe_error", error=str(exc))
    if groups.returncode != 0:
        return early_result(status="degraded", reason="xinfo_groups_failed")
    group = next((row for row in parse_xinfo_groups_rows(groups.stdout) if row.get("name") == TASKS_STREAM_GROUP), None)
    if not group:
        return early_result(status="degraded", reason="consumer_group_missing")
    lag = parse_int(group.get("lag"), default=-1)
    if lag < 0:
        return early_result(status="degraded", reason="invalid_lag")
    result: dict[str, Any] = {
        "status": "ok",
        "reason": "healthy",
        "stream": TASKS_STREAM_KEY,
        "group": TASKS_STREAM_GROUP,
        "lag": lag,
        "pending": None,
        "consumer_count": parse_int(group.get("consumers"), default=0),
        "entries_read": parse_int(group.get("entries-read"), default=0),
    }
    result["thresholds_version"] = "redis_streams_v1"

    def set_stream_action(*, pending_total: int | None, top_pending: int = 0, top_idle: int = 0) -> None:
        action = "continue"
        action_reason = "none"
        if lag >= 1000:
            action = "intervene"
            action_reason = "lag_critical"
        else:
            total_pending = pending_total if pending_total is not None else 0
            if total_pending > 0 and top_idle >= 30000 and top_pending > 0:
                action = "intervene"
                action_reason = "pending_stuck"
            elif total_pending > 0 and top_pending / total_pending >= 0.8:
                action = "intervene"
                action_reason = "pending_skew"
            elif lag >= 100:
                action = "watch"
                action_reason = "lag_warn"
            elif total_pending > 0:
                action = "watch"
                action_reason = "pending_stuck"
        result["stream_action"] = action
        result["stream_action_reason"] = action_reason

    if pending.returncode != 0:
        result["status"] = "degraded"
        result["reason"] = "xpending_failed"
        result["stream_action"] = "watch"
        result["stream_action_reason"] = "xpending_failed"
        return result
    total = parse_xpending_total(pending.stdout)
    if total is None or total < 0:
        result["status"] = "degraded"
        result["reason"] = "invalid_pending"
        result["stream_action"] = "watch"
        result["stream_action_reason"] = "invalid_pending"
        return result
    result["pending"] = total
    try:
        consumers = redis_cli(["--raw", "XINFO", "CONSUMERS", TASKS_STREAM_KEY, TASKS_STREAM_GROUP])
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["consumer_probe_status"] = "degraded"
        result["consumer_probe_reason"] = "xinfo_consumers_probe_error"
        result["consumer_probe_error"] = str(exc)
        set_stream_action(pending_total=total)
        return result
    if consumers.returncode != 0:
        result["consumer_probe_status"] = "degraded"
        result["consumer_probe_reason"] = "xinfo_consumers_failed"
        set_stream_action(pending_total=total)
        return result
    rows = parse_xinfo_consumers_rows(consumers.stdout)
    if xinfo_consumers_rows_malformed(consumers.stdout, rows):
        result["consumer_probe_status"] = "degraded"
        result["consumer_probe_reason"] = "xinfo_consumers_malformed"
        set_stream_action(pending_total=total)
        return result
    consumer_rows = [
        {
            "name": row.get("name", ""),
            "pending": parse_int(row.get("pending"), default=0),
            "idle": parse_int(row.get("idle"), default=0),
        }
        for row in rows
    ]
    top_consumers = sorted(
        consumer_rows,
        key=lambda item: item["pending"],
        reverse=True,
    )[:TASKS_STREAM_TOP_CONSUMERS_LIMIT]
    result["consumer_probe_status"] = "ok"
    result["consumer_probe_reason"] = "healthy"
    result["top_consumers"] = top_consumers
    highest_pending = top_consumers[0]["pending"] if top_consumers else 0
    highest_idle = max((item["idle"] for item in consumer_rows if item["pending"] > 0), default=0)
    set_stream_action(pending_total=total, top_pending=highest_pending, top_idle=highest_idle)
    return result


def publish_node_heartbeat_redis(record: dict[str, Any]) -> dict[str, Any]:
    node_id = str(record.get("node_id") or "")
    if not node_id or not redis_available():
        return {"status": "skipped", "reason": "redis_unavailable"}
    payload = {
        "node_id": node_id,
        "status": record.get("status"),
        "connection_state": record.get("connection_state"),
        "connection_action": record.get("connection_action"),
        "connection_action_reason": record.get("connection_action_reason"),
        "last_heartbeat_at": record.get("last_heartbeat_at"),
        "updated_at": record.get("updated_at"),
        "ssh_target": record.get("ssh_target", ""),
        "host": record.get("host", ""),
        "message": record.get("message", ""),
        "load": record.get("load") or {},
        "current_task": record.get("current_task", ""),
    }
    key = f"a9:node:{node_id}"
    try:
        json_set = redis_cli(["JSON.SET", key, "$", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))])
        stream = redis_cli(
            [
                "XADD",
                "a9:heartbeats",
                "*",
                "node_id",
                node_id,
                "status",
                str(record.get("status") or ""),
                "connection_state",
                str(record.get("connection_state") or ""),
                "connection_action",
                str(record.get("connection_action") or ""),
                "connection_action_reason",
                str(record.get("connection_action_reason") or ""),
                "at",
                str(record.get("last_heartbeat_at") or ""),
            ]
        )
        ts = redis_cli(["TS.ADD", "a9:ts:heartbeat", "*", "1"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "error": str(exc)}
    return {
        "status": "ok" if json_set.returncode == 0 and stream.returncode == 0 else "failed",
        "json_key": key,
        "stream_id": stream.stdout.strip() if stream.returncode == 0 else "",
        "timeseries": "ok" if ts.returncode == 0 else "skipped",
        "output": compact_text("\n".join([json_set.stdout, stream.stdout, ts.stdout]), 1000),
    }


def validate_node_command_payload(payload: dict[str, Any], *, now_fn=utc_now) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a json object")
    command_id = str(payload.get("command_id") or "").strip()
    if not command_id:
        raise ValueError("command_id is required")
    node_id = str(payload.get("node_id") or "").strip()
    if not node_id:
        raise ValueError("node_id is required")
    action = str(payload.get("action") or "").strip()
    if not action:
        raise ValueError("action is required")
    action_reason = str(payload.get("action_reason") or "").strip()
    if not action_reason:
        raise ValueError("action_reason is required")
    target = str(payload.get("target") or "").strip()
    if not target:
        raise ValueError("target is required")

    try:
        expected_revision = int(payload.get("expected_revision"))
    except (TypeError, ValueError):
        raise ValueError("expected_revision must be integer")
    if expected_revision < 0:
        raise ValueError("expected_revision must be non-negative")

    try:
        ttl_seconds = int(payload.get("ttl_seconds"))
    except (TypeError, ValueError):
        raise ValueError("ttl_seconds must be integer")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")

    provided_created_at = str(payload.get("created_at") or "").strip()
    created_at = provided_created_at or now_fn()
    if parse_iso_datetime(created_at) is None:
        raise ValueError("created_at must be ISO-8601")

    command_status = str(payload.get("status") or "queued").strip() or "queued"
    return {
        "command_id": command_id,
        "node_id": node_id,
        "action": action,
        "action_reason": action_reason,
        "target": target,
        "expected_revision": expected_revision,
        "ttl_seconds": ttl_seconds,
        "created_at": created_at,
        "status": command_status,
        "stream": TASKS_STREAM_KEY,
        "stream_id": str(payload.get("stream_id") or "pending"),
        "error_code": str(payload.get("error_code") or ""),
    }


def enqueue_node_command(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        command = validate_node_command_payload(payload)
    except ValueError as exc:
        return {
            "status": "degraded",
            "kind": "node_command_enqueue",
            "error_code": "invalid_payload",
            "error": str(exc),
        }

    if not redis_available():
        command["status"] = "degraded"
        if not command["error_code"]:
            command["error_code"] = "redis_unavailable"
        return {
            "status": "degraded",
            "kind": "node_command_enqueue",
            "error_code": command["error_code"],
            "command": command,
        }

    fields = [
        "command_id",
        command["command_id"],
        "node_id",
        command["node_id"],
        "action",
        command["action"],
        "action_reason",
        command["action_reason"],
        "target",
        command["target"],
        "expected_revision",
        str(command["expected_revision"]),
        "ttl_seconds",
        str(command["ttl_seconds"]),
        "created_at",
        command["created_at"],
        "status",
        command["status"],
        "stream",
        command["stream"],
        "stream_id",
        command["stream_id"],
        "error_code",
        command["error_code"] or "none",
    ]
    try:
        proc = redis_cli(["XADD", TASKS_STREAM_KEY, "*", *fields])
    except (OSError, subprocess.TimeoutExpired) as exc:
        command["status"] = "degraded"
        command["error_code"] = "redis_unavailable"
        return {
            "status": "degraded",
            "kind": "node_command_enqueue",
            "error_code": command["error_code"],
            "command": command,
            "error": str(exc),
        }
    if proc.returncode != 0:
        command["status"] = "degraded"
        command["error_code"] = "xadd_failed"
        return {
            "status": "degraded",
            "kind": "node_command_enqueue",
            "error_code": command["error_code"],
            "command": command,
            "error": proc.stdout.strip(),
            "return_code": proc.returncode,
        }

    stream_id = proc.stdout.strip()
    command["stream_id"] = stream_id
    command["error_code"] = "none"
    return {
        "status": "ok",
        "kind": "node_command_enqueue",
        "command": command,
    }


def node_command_result_lookup(
    result_event_id: str,
    *,
    event_stream: str = EVENTS_STREAM_KEY,
    timeout: int = 3,
) -> dict[str, Any]:
    safe_result_event_id = str(result_event_id or "").strip()
    safe_event_stream = str(event_stream or "").strip()
    base: dict[str, Any] = {
        "status": "degraded",
        "kind": "node_command_result_lookup",
        "result_event_id": safe_result_event_id,
        "event_stream": safe_event_stream,
        "result": {},
    }
    if not _looks_like_stream_id(safe_result_event_id):
        return {
            **base,
            "error_code": "invalid_payload",
            "reason": "result_event_id_must_be_redis_stream_id",
        }
    if not safe_event_stream:
        return {
            **base,
            "error_code": "invalid_payload",
            "reason": "event_stream_required",
        }
    try:
        safe_timeout = max(1, int(timeout))
    except (TypeError, ValueError):
        return {
            **base,
            "error_code": "invalid_payload",
            "reason": "timeout_must_be_integer",
        }
    try:
        result = a9_node().node_command_result_read_once(
            safe_result_event_id,
            event_stream=safe_event_stream,
            timeout=safe_timeout,
        )
    except (OSError, RuntimeError, AttributeError, subprocess.TimeoutExpired) as exc:
        return {
            **base,
            "error_code": "node_helper_unavailable",
            "reason": str(exc),
        }

    status = str(result.get("status") or "degraded")
    error_code = str(result.get("error_code") or ("ok" if status == "ok" else status))
    payload: dict[str, Any] = {
        **base,
        "status": status,
        "error_code": error_code,
        "result": result,
    }
    if status != "ok":
        payload["reason"] = str(result.get("reason") or error_code)
    return payload


def node_command_result_by_command_lookup(
    command_id: str,
    *,
    event_stream: str = EVENTS_STREAM_KEY,
    limit: int = 100,
    timeout: int = 3,
) -> dict[str, Any]:
    safe_command_id = str(command_id or "").strip()
    safe_event_stream = str(event_stream or "").strip()
    base: dict[str, Any] = {
        "status": "degraded",
        "kind": "node_command_result_by_command_lookup",
        "command_id": safe_command_id,
        "event_stream": safe_event_stream,
        "limit": 0,
        "result_event_id": "",
        "result": {},
    }
    if not safe_command_id:
        return {**base, "error_code": "invalid_payload", "reason": "command_id_required"}
    if not safe_event_stream:
        return {**base, "error_code": "invalid_payload", "reason": "event_stream_required"}
    try:
        requested = max(1, min(EVENTS_STREAM_LIMIT_MAX, int(limit)))
    except (TypeError, ValueError):
        return {**base, "error_code": "invalid_payload", "reason": "limit_must_be_integer"}
    try:
        safe_timeout = max(1, int(timeout))
    except (TypeError, ValueError):
        return {**base, "limit": requested, "error_code": "invalid_payload", "reason": "timeout_must_be_integer"}

    try:
        proc = redis_cli(["--raw", "XREVRANGE", safe_event_stream, "+", "-", "COUNT", str(requested)])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**base, "limit": requested, "error_code": "redis_unavailable", "reason": str(exc)}
    if proc.returncode != 0:
        return {
            **base,
            "limit": requested,
            "error_code": "xrevrange_failed",
            "reason": proc.stdout.strip() or "redis command failed",
        }

    events = parse_xrange_events(proc.stdout)
    for event in events:
        fields = event.get("fields") or {}
        if str(fields.get("kind") or "") != "node_command_result":
            continue
        if str(fields.get("command_id") or "") != safe_command_id:
            continue
        result_event_id = str(event.get("id") or "")
        lookup = node_command_result_lookup(result_event_id, event_stream=safe_event_stream, timeout=safe_timeout)
        status = str(lookup.get("status") or "degraded")
        error_code = str(lookup.get("error_code") or ("ok" if status == "ok" else status))
        payload: dict[str, Any] = {
            **base,
            "status": status,
            "limit": requested,
            "result_event_id": result_event_id,
            "result": lookup,
            "error_code": error_code,
            "scanned_count": len(events),
        }
        if status != "ok":
            payload["reason"] = str(lookup.get("reason") or error_code)
        return payload

    return {
        **base,
        "status": "noop",
        "limit": requested,
        "error_code": "no_result",
        "reason": "node_command_result_not_found",
        "scanned_count": len(events),
    }


def register_node(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    node_id = safe_node_id(str(payload.get("node_id") or ""))
    now = utc_now()
    existing_path = node_path(node_id, root)
    existing = read_json(existing_path) if existing_path.exists() else {}
    record = {
        **existing,
        "node_id": node_id,
        "status": "registered",
        "registered_at": existing.get("registered_at") or now,
        "updated_at": now,
        "last_heartbeat_at": now,
        "host": str(payload.get("host") or existing.get("host") or ""),
        "user": str(payload.get("user") or existing.get("user") or ""),
        "kernel": str(payload.get("kernel") or existing.get("kernel") or ""),
        "ssh_target": str(payload.get("ssh_target") or existing.get("ssh_target") or ""),
        "capabilities": payload.get("capabilities") or existing.get("capabilities") or {},
        "labels": payload.get("labels") or existing.get("labels") or [],
        "last_probe_action": str(payload.get("last_probe_action") or existing.get("last_probe_action") or ""),
        "last_probe_action_reason": str(
            payload.get("last_probe_action_reason") or existing.get("last_probe_action_reason") or ""
        ),
        "last_probe_required_missing": list(
            payload.get("last_probe_required_missing") or existing.get("last_probe_required_missing") or []
        ),
        "last_probe_optional_missing": list(
            payload.get("last_probe_optional_missing") or existing.get("last_probe_optional_missing") or []
        ),
        "last_probe_checked_at": str(payload.get("last_probe_checked_at") or existing.get("last_probe_checked_at") or ""),
        "reconnect_action": str(payload.get("reconnect_action") or existing.get("reconnect_action") or ""),
        "reconnect_reason": str(payload.get("reconnect_reason") or existing.get("reconnect_reason") or ""),
        "reconnect_attempt": int(payload.get("reconnect_attempt") or existing.get("reconnect_attempt") or 0),
        "reconnect_backoff_seconds": int(
            payload.get("reconnect_backoff_seconds") or existing.get("reconnect_backoff_seconds") or 0
        ),
        "stream_action": str(payload.get("stream_action") or existing.get("stream_action") or ""),
        "stream_reason": str(payload.get("stream_reason") or existing.get("stream_reason") or ""),
        "reconnect_lifecycle": payload.get("reconnect_lifecycle")
        or existing.get("reconnect_lifecycle")
        or {},
        "controller_seen": True,
    }
    record = enrich_node_connection(record)
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    redis_result = publish_node_heartbeat_redis(record)
    return {"status": "registered", "node": record, "redis": redis_result}


def probe_node(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    target = str(payload.get("ssh_target") or payload.get("target") or "").strip()
    if not target:
        raise ValueError("ssh_target is required")
    connect_timeout = int(payload.get("connect_timeout") or 5)
    identity_file = str(payload.get("identity_file") or default_identity_file())
    mod = remote()
    cmd = mod.ssh_base(target, connect_timeout=connect_timeout, identity_file=identity_file)
    default_probe_timeout = max(connect_timeout * 2, 10)
    try:
        probe_timeout = int(payload.get("timeout_seconds") or default_probe_timeout)
    except (TypeError, ValueError):
        probe_timeout = default_probe_timeout
    if probe_timeout <= 0:
        probe_timeout = default_probe_timeout
    try:
        policy_budget_remaining = int(
            payload.get("policy_budget_remaining") or payload.get("reconnect_budget_remaining") or 1
        )
    except (TypeError, ValueError):
        policy_budget_remaining = 1

    timed_out = False
    return_code = 0
    raw_output = ""
    parsed: dict[str, str] = {}
    try:
        proc = subprocess.run(
            [*cmd, mod.remote_probe_script()],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=probe_timeout,
        )
        return_code = proc.returncode
        raw_output = proc.stdout
        parsed = mod.parse_probe(raw_output)
        classification = mod.classify_probe_result(return_code, parsed)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        raw_output = f"probe timeout after {probe_timeout}s: {exc}"
        classification = {
            "probe_action": "retry",
            "probe_action_reason": "ssh_connect_timeout",
            "required_missing": [],
            "optional_missing": [],
        }
    checked_at = utc_now()
    reconnect_reason = str(classification.get("probe_action_reason") or "probe_ok")
    connect_error_action = getattr(mod, "connect_error_action", None)
    if connect_error_action is None:
        connect_error_action = lambda reason: "reconnect" if reason == "ssh_exec_error" else "connected"
    reconnect_action = connect_error_action(reconnect_reason)
    reconnect_attempt = int(payload.get("reconnect_attempt") or 0)
    backoff_seconds = getattr(mod, "capped_reconnect_backoff_seconds", lambda attempt: min(30, 2 ** max(0, int(attempt))))
    reconnect_backoff_seconds = backoff_seconds(reconnect_attempt) if reconnect_action == "reconnect" else 0
    gateway_decision = getattr(mod, "gateway_reconnect_decision", None)
    if callable(gateway_decision):
        decision = gateway_decision(
            phase="connect",
            error_class=reconnect_reason,
            attempt=reconnect_attempt,
            node_id=str(payload.get("node_id") or target),
            origin="probe_node",
            policy_budget_remaining=max(0, policy_budget_remaining),
            at=checked_at,
        )
        if isinstance(decision, dict):
            decision_action = str(decision.get("action") or "")
            if decision_action in {"connected", "reconnect", "terminate"}:
                reconnect_action = decision_action
                reconnect_backoff_seconds = (
                    int(decision.get("delay_ms") or 0) // 1000 if reconnect_action == "reconnect" else 0
                )
    lifecycle_event = "reconnecting" if reconnect_action == "reconnect" else "connected"
    lifecycle_update = getattr(
        mod,
        "lifecycle_update",
        lambda event, *, node_id="", at="", details=None: {
            "event": event,
            "node_id": node_id,
            "at": at,
            "details": details or {},
        },
    )
    lifecycle = lifecycle_update(
        lifecycle_event,
        node_id=str(payload.get("node_id") or target),
        at=checked_at,
        details={
            "reason": reconnect_reason,
            "attempt": reconnect_attempt,
            "backoff_seconds": reconnect_backoff_seconds,
        },
    )
    connection_summary = None
    summarize_node_connection_state = getattr(mod, "summarize_node_connection_state", None)
    if callable(summarize_node_connection_state):
        try:
            connection_summary = summarize_node_connection_state(
                node_id=str(payload.get("node_id") or target),
                return_code=return_code,
                output=parsed,
                attempt=reconnect_attempt,
                policy_budget_remaining=max(0, policy_budget_remaining),
            )
        except Exception:
            connection_summary = None
        if timed_out and isinstance(connection_summary, dict):
            connection_summary["action_reason"] = reconnect_reason
            connection_summary["action"] = reconnect_action
            if reconnect_action == "reconnect":
                connection_summary["retry_delay_ms"] = int(reconnect_backoff_seconds) * 1000
            else:
                connection_summary["retry_delay_ms"] = 0
    stream_reason = str(payload.get("stream_reason") or "")
    stream_error_action = getattr(mod, "stream_error_action", lambda reason: "reconnect")
    stream_action = stream_error_action(stream_reason) if stream_reason else ""
    followup = probe_action_to_followup(
        classification.get("probe_action"),
        classification.get("probe_action_reason"),
    )
    host = str(payload.get("host") or parsed.get("host") or ssh_target_host(target))
    registered = register_node(
        {
            "node_id": payload.get("node_id") or target,
            "host": host,
            "user": payload.get("user") or parsed.get("user") or "",
            "kernel": parsed.get("kernel") or "",
            "ssh_target": target,
            "capabilities": {
                key: value
                for key, value in parsed.items()
                if key not in {"host", "user", "kernel"} and value
            },
            "labels": payload.get("labels") or ["mobile-probed"],
            "last_probe_action": classification.get("probe_action"),
            "last_probe_action_reason": classification.get("probe_action_reason"),
            "last_probe_required_missing": classification.get("required_missing") or [],
            "last_probe_optional_missing": classification.get("optional_missing") or [],
            "last_probe_checked_at": checked_at,
            "reconnect_action": reconnect_action,
            "reconnect_reason": reconnect_reason,
            "reconnect_attempt": reconnect_attempt,
            "reconnect_backoff_seconds": reconnect_backoff_seconds,
            "stream_action": stream_action,
            "stream_reason": stream_reason,
            "reconnect_lifecycle": lifecycle,
        },
        root=root,
    )
    evidence_payload = {
        "status": "ok" if return_code == 0 else "failed",
        "target": target,
        "node_id": str(registered.get("node", {}).get("node_id") or target),
        "host": host,
        "checked_at": checked_at,
        "return_code": return_code,
        "timed_out": timed_out,
        "probe_action": classification.get("probe_action"),
        "probe_action_reason": classification.get("probe_action_reason"),
        "supervisor_followup": followup,
        "missing_required_tools": classification.get("required_missing") or [],
        "missing_optional_tools": classification.get("optional_missing") or [],
        "reconnect_action": reconnect_action,
        "reconnect_reason": reconnect_reason,
        "reconnect_attempt": reconnect_attempt,
        "reconnect_backoff_seconds": reconnect_backoff_seconds,
        "reconnect_lifecycle": lifecycle,
        "connection_summary": connection_summary,
        "raw": compact_text(raw_output, 4000),
        "transport_quality": transport_quality(target),
    }
    evidence_path = write_node_evidence(
        "probe-timeout" if timed_out else "probe",
        str(registered.get("node", {}).get("node_id") or target),
        evidence_payload,
        root=root,
    )
    return {
        "status": "ok" if return_code == 0 else "failed",
        "checked_at": checked_at,
        "ssh_target": target,
        "return_code": return_code,
        "timed_out": timed_out,
        "probe_action": classification["probe_action"],
        "probe_action_reason": classification["probe_action_reason"],
        "supervisor_followup": followup,
        "missing_required_tools": classification["required_missing"],
        "missing_optional_tools": classification["optional_missing"],
        "probe": parsed,
        "raw": compact_text(raw_output, 4000),
        "evidence_path": str(evidence_path),
        "node": registered["node"],
    }


def bootstrap_plan_node(payload: dict[str, Any]) -> dict[str, Any]:
    target = str(payload.get("ssh_target") or payload.get("target") or "").strip()
    if not target:
        raise ValueError("ssh_target is required")
    controller_url = str(payload.get("controller_url") or "http://127.0.0.1:8787")
    repo = str(payload.get("repo") or "git@github.com:deepcooker/a9.git")
    remote_dir = str(payload.get("remote_dir") or "~/a9-worker")
    worker_name = str(payload.get("worker_name") or "")
    mod = remote()
    args = type(
        "BootstrapArgs",
        (),
        {
            "controller_url": controller_url,
            "repo": repo,
            "remote_dir": remote_dir,
            "worker_name": worker_name,
        },
    )()
    script = mod.build_bootstrap_script(args)
    return {
        "status": "planned",
        "target": target,
        "controller_url": controller_url,
        "repo": repo,
        "remote_dir": remote_dir,
        "worker_name": worker_name,
        "dry_run_script": script,
        "steps": [
            "ssh probe remote host",
            "ensure git/python3/curl are present",
            "clone or update A9 repo on remote host",
            "write remote-node config with controller URL",
            "install heartbeat loop script at .a9/remote-node/heartbeat.sh",
            "later start worker daemon and Redis Streams consumer",
            "later register heartbeat back to controller",
        ],
    }


def bootstrap_dry_run_node(payload: dict[str, Any]) -> dict[str, Any]:
    plan = bootstrap_plan_node(payload)
    return {
        **plan,
        "status": "dry-run",
        "command_preview": [
            "ssh",
            str(plan["target"]),
            "<dry_run_script>",
        ],
        "execution_enabled": False,
    }


def tmux_plan_node(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    target = str(payload.get("ssh_target") or payload.get("target") or "").strip()
    if not target:
        raise ValueError("ssh_target is required")
    node_id = safe_node_id(str(payload.get("node_id") or target))
    session = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(payload.get("session") or "a9").strip())[:64] or "a9"
    remote_dir = str(payload.get("remote_dir") or "~/a9-worker")
    connect_timeout = int(payload.get("connect_timeout") or 5)
    identity_file = str(payload.get("identity_file") or default_identity_file())
    attach_command = f"tmux attach -t {session}"
    ensure_command = f"mkdir -p {remote_dir} && (tmux has-session -t {session} 2>/dev/null || tmux new-session -d -s {session} -c {remote_dir})"
    quality = transport_quality(target)
    plan = {
        "status": "planned",
        "transport": "tailscale+ssh+tmux",
        "transport_quality": quality,
        "node_id": node_id,
        "target": target,
        "session": session,
        "remote_dir": remote_dir,
        "connect_timeout_seconds": connect_timeout,
        "planned_at": utc_now(),
        "steps": [
            "connect over Tailscale or private SSH target",
            "ensure tmux session exists on the remote host",
            "attach for manual takeover or tail logs without killing the worker",
            "keep runtime state in A9 evidence/API/Redis instead of scraping tmux as truth",
        ],
        "command_preview": [
            ssh_remote_command(target, ensure_command, connect_timeout=connect_timeout, identity_file=identity_file),
            [*ssh_remote_command(target, attach_command, connect_timeout=connect_timeout, identity_file=identity_file)[:-1], attach_command],
        ],
        "execution_enabled": False,
    }
    evidence_path = write_node_evidence("tmux-plan", node_id, plan, root=root)
    return {**plan, "evidence_path": str(evidence_path)}


def heartbeat_tmux_plan_node(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    target = str(payload.get("ssh_target") or payload.get("target") or "").strip()
    if not target:
        raise ValueError("ssh_target is required")
    node_id = safe_node_id(str(payload.get("node_id") or target))
    session = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(payload.get("session") or "a9-heartbeat").strip())[:64] or "a9-heartbeat"
    remote_dir = str(payload.get("remote_dir") or "~/a9-worker")
    controller_url = str(payload.get("controller_url") or "").strip() or None
    connect_timeout = int(payload.get("connect_timeout") or 5)
    identity_file = str(payload.get("identity_file") or default_identity_file())
    heartbeat_interval = int(payload.get("heartbeat_interval") or 30)
    smoke = bool(payload.get("smoke_test") or payload.get("smoke"))
    heartbeat_script = f"{remote_dir.rstrip('/')}/.a9/remote-node/heartbeat.sh"
    quoted_remote_dir = shlex.quote(remote_dir)
    quoted_session = shlex.quote(session)
    quoted_heartbeat_script = shlex.quote(heartbeat_script)
    heartbeat_env_value = " ".join(
        [
            f"A9_HEARTBEAT_INTERVAL={shlex.quote(str(heartbeat_interval))}",
            *( [f"A9_HEARTBEAT_ONCE={shlex.quote('1')}"] if smoke else []),
        ]
    )
    heartbeat_run_command = shlex.quote(f"{heartbeat_env_value} {quoted_heartbeat_script}")
    ensure_command = (
        f"mkdir -p {quoted_remote_dir} && (tmux has-session -t {quoted_session} 2>/dev/null || "
        f"tmux new-session -d -s {quoted_session} -c {quoted_remote_dir} {heartbeat_run_command})"
    )
    quality = transport_quality(target)
    plan = {
        "status": "planned",
        "transport": "tailscale+ssh+tmux",
        "transport_quality": quality,
        "node_id": node_id,
        "target": target,
        "session": session,
        "remote_dir": remote_dir,
        "heartbeat_script": heartbeat_script,
        "heartbeat_interval": heartbeat_interval,
        "planned_at": utc_now(),
        "execution_enabled": False,
        "steps": [
            "create/confirm remote tmux session dedicated for heartbeat loop",
            "run .a9/remote-node/heartbeat.sh inside tmux session with heartbeat interval",
            "avoid systemd/daemon by keeping execution inside tmux session command",
        ],
        "command_preview": [
            ssh_remote_command(
                target,
                ensure_command,
                connect_timeout=connect_timeout,
                identity_file=identity_file,
            ),
        ],
    }
    if controller_url is not None:
        plan["controller_url"] = controller_url
    evidence_path = write_node_evidence("heartbeat-tmux-plan", node_id, plan, root=root)
    return {**plan, "evidence_path": str(evidence_path)}


def read_tmux_plan_evidence(path_value: str, *, root: Path = ROOT) -> dict[str, Any]:
    if not path_value:
        raise ValueError("evidence_path is required")
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    allowed = (root / ".a9" / "nodes" / "evidence").resolve()
    if not (resolved == allowed or resolved.is_relative_to(allowed)):
        raise ValueError("tmux evidence path is outside node evidence root")
    plan = read_json(resolved)
    if plan.get("transport") != "tailscale+ssh+tmux":
        raise ValueError("evidence is not a tmux takeover plan")
    if plan.get("execution_enabled") is not False:
        raise ValueError("tmux plan evidence must be non-executing")
    commands = plan.get("command_preview")
    if not isinstance(commands, list) or not commands:
        raise ValueError("tmux plan evidence is missing command_preview")
    ensure = commands[0]
    if not isinstance(ensure, list) or len(ensure) < 3 or ensure[0] != "ssh":
        raise ValueError("tmux ensure command must be an ssh argv")
    if "tmux new-session" not in str(ensure[-1]) or "tmux has-session" not in str(ensure[-1]):
        raise ValueError("tmux ensure command is missing tmux new-session")
    return {**plan, "evidence_path": str(resolved)}


def read_heartbeat_tmux_plan_evidence(path_value: str, *, root: Path = ROOT) -> dict[str, Any]:
    plan = read_tmux_plan_evidence(path_value, root=root)
    evidence_path = Path(str(plan.get("evidence_path") or ""))
    if not evidence_path.name.startswith("heartbeat-tmux-plan-"):
        raise ValueError("evidence is not a heartbeat tmux plan")
    command = plan.get("command_preview")
    if not isinstance(command, list) or not command:
        raise ValueError("heartbeat tmux plan evidence is missing command_preview")
    ensure = command[0]
    if not isinstance(ensure, list) or len(ensure) < 3 or ensure[0] != "ssh":
        raise ValueError("heartbeat tmux ensure command must be an ssh argv")
    command_text = str(ensure[-1] or "")
    if ".a9/remote-node/heartbeat.sh" not in command_text:
        raise ValueError("heartbeat tmux plan command is missing heartbeat script")
    return plan


def tmux_ensure_node(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    require_phone_admin(payload)
    gate = command_gate("nodes.tmux.ensure", root=root)
    if not gate.get("allowed"):
        return {
            "status": "blocked",
            "execution_enabled": False,
            "tmux_action": "wait_for_approval",
            "tmux_action_reason": str(gate.get("reason") or "phone_control_disarmed"),
            "gate": gate,
        }
    plan = read_tmux_plan_evidence(str(payload.get("evidence_path") or ""), root=root)
    command = plan["command_preview"][0]
    timed_out = False
    try:
        proc = subprocess.run(
            [str(item) for item in command],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=int(payload.get("timeout_seconds") or 20),
        )
        return_code = proc.returncode
        output = proc.stdout
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        output = str(exc)
    status = "timeout" if timed_out else "ok" if return_code == 0 else "failed"
    tmux_action = "retry" if status == "timeout" else "continue" if status == "ok" else "repair"
    reason = "tmux_ensure_timeout" if status == "timeout" else "tmux_ensure_ok" if status == "ok" else "tmux_ensure_failed"
    result = {
        "status": status,
        "transport": "tailscale+ssh+tmux",
        "transport_quality": plan.get("transport_quality") or transport_quality(str(plan.get("target") or "")),
        "node_id": plan.get("node_id"),
        "target": plan.get("target"),
        "session": plan.get("session"),
        "executed_at": utc_now(),
        "return_code": return_code,
        "timed_out": timed_out,
        "output": compact_text(output, 4000),
        "plan_evidence_path": plan.get("evidence_path"),
        "tmux_action": tmux_action,
        "tmux_action_reason": reason,
        "reason": reason,
        "gate": gate,
    }
    evidence_path = write_node_evidence("tmux-ensure", str(plan.get("node_id") or plan.get("target") or "node"), result, root=root)
    return {**result, "evidence_path": str(evidence_path)}


def tmux_status_node(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    plan = read_tmux_plan_evidence(str(payload.get("evidence_path") or ""), root=root)
    target = str(plan.get("target") or "")
    session = str(plan.get("session") or "a9")
    if not target:
        raise ValueError("tmux plan is missing target")
    connect_timeout = int(plan.get("connect_timeout_seconds") or payload.get("connect_timeout") or 5)
    command = ssh_remote_command(target, f"tmux has-session -t {session}", connect_timeout=connect_timeout)
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=int(payload.get("timeout_seconds") or 10),
        )
        return_code = proc.returncode
        output = proc.stdout
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        return_code = 124
        output = str(exc)
        timed_out = True
    status = "exists" if return_code == 0 else "timeout" if timed_out else "missing"
    tmux_action = "continue" if status == "exists" else "retry" if status == "timeout" else "repair"
    reason = "tmux_session_exists" if status == "exists" else "tmux_status_timeout" if status == "timeout" else "tmux_session_missing"
    result = {
        "status": status,
        "transport": "tailscale+ssh+tmux",
        "transport_quality": plan.get("transport_quality") or transport_quality(target),
        "node_id": plan.get("node_id"),
        "target": target,
        "session": session,
        "checked_at": utc_now(),
        "return_code": return_code,
        "timed_out": timed_out,
        "output": compact_text(output, 4000),
        "plan_evidence_path": plan.get("evidence_path"),
        "tmux_action": tmux_action,
        "tmux_action_reason": reason,
        "reason": reason,
        "command_preview": command,
    }
    evidence_path = write_node_evidence("tmux-status", str(plan.get("node_id") or target or "node"), result, root=root)
    return {**result, "evidence_path": str(evidence_path)}


def heartbeat_tmux_start_node(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    require_phone_admin(payload)
    gate = command_gate("nodes.heartbeat.tmux.start", root=root)
    if not gate.get("allowed"):
        return {
            "status": "blocked",
            "execution_enabled": False,
            "heartbeat_action": "wait_for_approval",
            "heartbeat_action_reason": str(gate.get("reason") or "phone_control_disarmed"),
            "reason": str(gate.get("reason") or "phone_control_disarmed"),
            "gate": gate,
        }
    plan = read_heartbeat_tmux_plan_evidence(str(payload.get("evidence_path") or ""), root=root)
    command = plan["command_preview"][0]
    timed_out = False
    try:
        proc = subprocess.run(
            [str(item) for item in command],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=int(payload.get("timeout_seconds") or 20),
        )
        return_code = proc.returncode
        output = proc.stdout
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        output = str(exc)
    status = "timeout" if timed_out else "ok" if return_code == 0 else "failed"
    heartbeat_action = "retry" if status == "timeout" else "continue" if status == "ok" else "repair"
    heartbeat_reason = (
        "heartbeat_tmux_start_timeout"
        if status == "timeout"
        else "heartbeat_tmux_start_ok"
        if status == "ok"
        else "heartbeat_tmux_start_failed"
    )
    result = {
        "status": status,
        "transport": "tailscale+ssh+tmux",
        "transport_quality": plan.get("transport_quality") or transport_quality(str(plan.get("target") or "")),
        "node_id": plan.get("node_id"),
        "target": plan.get("target"),
        "session": plan.get("session"),
        "executed_at": utc_now(),
        "return_code": return_code,
        "timed_out": timed_out,
        "output": compact_text(output, 4000),
        "plan_evidence_path": plan.get("evidence_path"),
        "heartbeat_action": heartbeat_action,
        "heartbeat_action_reason": heartbeat_reason,
        "reason": heartbeat_reason,
        "gate": gate,
    }
    evidence_path = write_node_evidence(
        "heartbeat-tmux-start",
        str(plan.get("node_id") or plan.get("target") or "node"),
        result,
        root=root,
    )
    return {**result, "evidence_path": str(evidence_path)}


def heartbeat_node(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    node_id = safe_node_id(str(payload.get("node_id") or ""))
    path = node_path(node_id, root)
    existing = read_json(path) if path.exists() else {"node_id": node_id, "registered_at": utc_now()}
    now = utc_now()
    record = {
        **existing,
        "node_id": node_id,
        "status": str(payload.get("status") or "online"),
        "updated_at": now,
        "last_heartbeat_at": now,
        "load": payload.get("load") or {},
        "current_task": str(payload.get("current_task") or ""),
        "message": str(payload.get("message") or ""),
    }
    record = enrich_node_connection(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    redis_result = publish_node_heartbeat_redis(record)
    return {"status": "ok", "node": record, "redis": redis_result}


def find_latest_operator_session(base: Path | None = None) -> Path | None:
    base = base or CODEX_SESSIONS_DIR
    if not base.exists():
        return None
    sessions = sorted(base.glob("**/*.jsonl"), key=lambda path: path.stat().st_mtime)
    return sessions[-1] if sessions else None


def assert_operator_session_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    allowed = CODEX_SESSIONS_DIR.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise ValueError(f"operator session path must be under {allowed}") from exc
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    return resolved


def operator_tail(session_jsonl: str | None = None, *, limit: int = 10, preview_chars: int = 240) -> dict[str, Any]:
    path = assert_operator_session_path(Path(session_jsonl)) if session_jsonl else find_latest_operator_session()
    if not path:
        return {"status": "missing", "source_session_path": "", "turns": []}
    path = assert_operator_session_path(path)
    refresh = session_refresh()
    index = refresh.session_index(path, batch_size=max(1, limit))
    turns = index.get("turns", [])
    tail = turns[-max(1, limit) :]
    return {
        "status": "ok",
        "session_id": index.get("session_id"),
        "source_session_path": str(path),
        "source_sha256": index.get("source_sha256"),
        "jsonl_lines": index.get("jsonl_lines"),
        "user_turn_count": index.get("user_turn_count"),
        "turns": [
            {
                "turn": item.get("turn"),
                "line": item.get("line"),
                "timestamp": item.get("timestamp"),
                "preview": compact_text(str(item.get("preview", "")), preview_chars),
            }
            for item in tail
        ],
    }


def run_summary(run_id: str | None = None, *, root: Path = ROOT, compact: bool = False) -> dict[str, Any] | None:
    if run_id in (None, "", "latest"):
        summary = latest_run_summary(root)
    else:
        path = root / ".a9" / "runs" / run_id / "summary.json"
        if not path.exists():
            return None
        summary = read_json(path)
    return compact_summary(summary) if compact else summary


def read_evidence_file(path_value: str, *, root: Path = ROOT, max_bytes: int = 8000) -> dict[str, Any]:
    if not path_value:
        raise ValueError("path is required")
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    allowed_roots = [
        (root / ".a9" / "runs").resolve(),
        (root / ".a9" / "nodes").resolve(),
    ]
    if not any(resolved == allowed or resolved.is_relative_to(allowed) for allowed in allowed_roots):
        raise ValueError("path is outside allowed evidence roots")
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    data = resolved.read_bytes()
    truncated = len(data) > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    return {
        "status": "ok",
        "path": str(resolved),
        "bytes": len(data),
        "truncated": truncated,
        "content": text,
    }


def submit_task(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    mod = supervisor()
    task_id = str(payload.get("task_id") or mod.slugify(prompt[:60]))
    path = mod.enqueue_task_file(
        task_id,
        prompt,
        phase=str(payload.get("phase") or "implement"),
        checks=[str(item) for item in payload.get("checks", [])],
        timeout_seconds=int(payload.get("timeout_seconds", 3600)),
        idle_timeout_seconds=int(payload.get("idle_timeout_seconds", 300)),
        max_attempts=int(payload.get("max_attempts", 2)),
        allowed_paths=[str(item) for item in payload.get("allowed_paths", [])],
    )
    result: dict[str, Any] = {"status": "queued", "task_id": task_id, "queue_path": str(path)}
    if payload.get("run"):
        require_phone_admin(payload)
        gate = command_gate("submit.run", root=ROOT)
        if not gate.get("allowed"):
            result.update({"status": "blocked", "gate": gate})
            return result
        code = mod.run_one(auto_next=bool(payload.get("auto_next", False)))
        result["run_return_code"] = code
        result["status"] = "run-complete" if code == 0 else "run-failed"
        result["latest_run"] = compact_summary(latest_run_summary(ROOT))
    return result


def runtime_run_one(payload: dict[str, Any]) -> dict[str, Any]:
    require_phone_admin(payload)
    gate = command_gate("submit.run", root=ROOT)
    if not gate.get("allowed"):
        return {"status": "blocked", "gate": gate}
    mod = supervisor()
    code = mod.run_one(auto_next=bool(payload.get("auto_next", False)))
    return {
        "status": "run-complete" if code == 0 else "run-failed",
        "command": "submit.run",
        "run_return_code": code,
        "gate": gate,
        "latest_run": compact_summary(latest_run_summary(ROOT)),
    }


def runtime_session_refresh_trial(payload: dict[str, Any]) -> dict[str, Any]:
    require_phone_admin(payload)
    gate = command_gate("session.refresh.trial", root=ROOT)
    if not gate.get("allowed"):
        return {"status": "blocked", "gate": gate}
    path = find_latest_operator_session()
    if not path:
        return {"status": "missing-session", "gate": gate, "source_session_path": ""}
    tail = operator_tail(str(path), limit=1)
    turns = tail.get("turns") or []
    if not turns:
        return {"status": "missing-turns", "gate": gate, "source_session_path": str(path)}
    turn = int(turns[-1].get("turn") or 1)
    mod = supervisor()
    prompt = "\n".join(
        [
            f"source_session_path: {path}",
            f"from_turn: {turn}",
            f"to_turn: {turn}",
            "batch_size: 1",
            "auto_continue: false",
            "auto_close_reading: false",
            "close_reading_doc: docs/session-raw-close-reading.md",
            "summary_doc: docs/session-raw-summary.md",
            "",
            "Mobile runtime trial: deterministically refresh one latest operator session turn without calling a model.",
        ]
    )
    task_id = f"mobile-session-refresh-trial-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    queue_path = mod.enqueue_task_file(
        task_id,
        prompt,
        phase=mod.SESSION_REFRESH_PHASE,
        checks=[],
        timeout_seconds=120,
        idle_timeout_seconds=30,
        max_attempts=1,
        allowed_paths=[],
    )
    task = mod.parse_task(queue_path)
    code = mod.run_session_refresh_task(task, auto_next=False)
    latest = compact_summary(latest_run_summary(ROOT))
    return {
        "status": "run-complete" if code == 0 else "run-failed",
        "command": "session.refresh.trial",
        "run_return_code": code,
        "gate": gate,
        "task_id": task.task_id,
        "queue_path": str(queue_path),
        "source_session_path": str(path),
        "turn": turn,
        "latest_run": latest,
    }


def eval_override(payload: dict[str, Any]) -> dict[str, Any]:
    require_phone_admin(payload)
    gate = command_gate("eval.override", root=ROOT)
    if not gate.get("allowed"):
        return {"status": "blocked", "command": "eval.override", "gate": gate}
    evidence_refs = payload.get("evidence_refs", [])
    if isinstance(evidence_refs, str):
        evidence_refs = [evidence_refs]
    if not isinstance(evidence_refs, list):
        evidence_refs = []
    mod = supervisor()
    result = mod.write_eval_manual_override(
        run_id=str(payload.get("run_id") or "").strip(),
        action=str(payload.get("action") or "").strip(),
        reason=str(payload.get("reason") or "").strip(),
        actor=str(payload.get("actor") or "mobile-operator").strip(),
        evidence_refs=[str(item) for item in evidence_refs],
    )
    return {"command": "eval.override", "gate": gate, **result}


def response(status: int, payload: Any) -> tuple[int, bytes]:
    return status, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


class ControlHandler(BaseHTTPRequestHandler):
    server_version = "A9ControlAPI/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def write_json(self, status: int, payload: Any) -> None:
        code, body = response(status, payload)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def write_sse(self, status: int, payload: dict[str, Any]) -> None:
        body = events_to_sse(payload)
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/health":
                self.write_json(200, {"status": "ok"})
            elif parsed.path == "/api/discovery":
                self.write_json(200, controller_discovery())
            elif parsed.path == "/api/status":
                self.write_json(200, supervisor_status())
            elif parsed.path == "/api/tailscale/status":
                self.write_json(200, tailscale_status())
            elif parsed.path == "/api/nodes":
                self.write_json(200, node_status())
            elif parsed.path == "/api/nodes/status":
                self.write_json(200, node_status())
            elif parsed.path == "/api/nodes/connection-summary":
                self.write_json(200, node_connection_summary())
            elif parsed.path == "/api/nodes/recovery-cycle":
                self.write_json(
                    200,
                    node_recovery_cycle(
                        {
                            "max_actions": query.get("max_actions", [""])[0],
                            "node_id": query.get("node_id", [""])[0],
                            "include_noise": query.get("include_noise", [""])[0],
                            "include_duplicates": query.get("include_duplicates", [""])[0],
                        }
                    ),
                )
            elif parsed.path == "/api/gateway/transport-contract":
                emit_event = str(query.get("emit_event", ["0"])[0]).lower() in {"1", "true", "yes", "on"}
                self.write_json(200, gateway_transport_contract(emit_event=emit_event))
            elif parsed.path == "/api/gateway/reconnect-decision":
                self.write_json(200, latest_gateway_reconnect_decision_event())
            elif parsed.path == "/api/gateway/reconnect-diagnostic":
                success = str(query.get("success", ["0"])[0]).lower() in {"1", "true", "yes", "on"}
                self.write_json(200, gateway_reconnect_diagnostic(success=success))
            elif parsed.path == "/api/gateway/reconnect-governance":
                self.write_json(200, gateway_reconnect_governance())
            elif parsed.path == "/api/gateway/health-refresh":
                self.write_json(200, gateway_health_refresh())
            elif parsed.path == "/api/nodes/evidence":
                self.write_json(
                    200,
                    list_node_evidence(
                        query.get("node_id", [None])[0],
                        limit=int(query.get("limit", ["20"])[0]),
                    ),
                )
            elif parsed.path == "/api/phone-control/status":
                self.write_json(200, phone_control_status())
            elif parsed.path == "/api/commands/gate":
                self.write_json(200, command_gate(query.get("command", [""])[0]))
            elif parsed.path == "/api/operator/tail":
                limit = int(query.get("limit", ["10"])[0])
                source = query.get("source_session_path", [None])[0]
                self.write_json(200, operator_tail(source, limit=limit))
            elif parsed.path.startswith("/api/node-command-results/by-command/"):
                command_id = unquote(parsed.path.removeprefix("/api/node-command-results/by-command/")).strip("/")
                self.write_json(
                    200,
                    node_command_result_by_command_lookup(
                        command_id,
                        event_stream=query.get("event_stream", [EVENTS_STREAM_KEY])[0],
                        limit=query.get("limit", ["100"])[0],
                        timeout=query.get("timeout", ["3"])[0],
                    ),
                )
            elif parsed.path.startswith("/api/node-command-results/"):
                result_event_id = parsed.path.removeprefix("/api/node-command-results/").strip("/")
                event_stream = query.get("event_stream", [EVENTS_STREAM_KEY])[0]
                try:
                    timeout = int(query.get("timeout", ["3"])[0])
                except ValueError:
                    self.write_json(
                        400,
                        {
                            "status": "degraded",
                            "kind": "node_command_result_lookup",
                            "error_code": "invalid_payload",
                            "reason": "timeout_must_be_integer",
                            "result_event_id": result_event_id,
                            "event_stream": event_stream,
                            "result": {},
                        },
                    )
                    return
                self.write_json(
                    200,
                    node_command_result_lookup(result_event_id, event_stream=event_stream, timeout=timeout),
                )
            elif parsed.path == "/api/events":
                last_id = _resolve_event_last_id(query.get("last_id", [None])[0], self.headers.get("Last-Event-ID"))
                try:
                    limit = int(query.get("limit", query.get("count", ["100"]))[0])
                except ValueError:
                    self.write_json(400, {"error": "limit must be integer"})
                    return
                payload = read_events(last_id, limit=limit)
                if str(query.get("format", ["json"])[0]).lower() == "sse":
                    self.write_sse(200, payload)
                else:
                    self.write_json(200, payload)
            elif parsed.path == "/api/runs/latest":
                self.write_json(200, run_summary("latest", compact=query.get("compact", ["0"])[0] in {"1", "true"}))
            elif parsed.path.startswith("/api/runs/") and parsed.path.endswith("/summary"):
                run_id = parsed.path.removeprefix("/api/runs/").removesuffix("/summary").strip("/")
                summary = run_summary(run_id, compact=query.get("compact", ["0"])[0] in {"1", "true"})
                if summary is None:
                    self.write_json(404, {"error": "run summary not found", "run_id": run_id})
                else:
                    self.write_json(200, summary)
            elif parsed.path == "/api/files/read":
                path_value = query.get("path", [""])[0]
                self.write_json(200, read_evidence_file(path_value))
            else:
                self.write_json(404, {"error": "not found", "path": parsed.path})
        except Exception as exc:
            self.write_json(500, {"error": str(exc)})

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if self.path == "/api/submit":
                self.write_json(200, submit_task(payload))
            elif self.path == "/api/runtime/run-one":
                self.write_json(200, runtime_run_one(payload))
            elif self.path == "/api/runtime/session-refresh-trial":
                self.write_json(200, runtime_session_refresh_trial(payload))
            elif self.path == "/api/eval/override":
                self.write_json(200, eval_override(payload))
            elif self.path == "/api/nodes/register":
                self.write_json(200, register_node(payload))
            elif self.path == "/api/nodes/probe":
                status, body = guarded_remote_post(
                    "nodes.probe.execute",
                    payload,
                    probe_node,
                    endpoint="/api/nodes/probe",
                )
                self.write_json(status, body)
            elif self.path == "/api/nodes/bootstrap-plan":
                self.write_json(200, bootstrap_plan_node(payload))
            elif self.path == "/api/nodes/bootstrap-dry-run":
                self.write_json(200, bootstrap_dry_run_node(payload))
            elif self.path == "/api/nodes/tmux-plan":
                self.write_json(200, tmux_plan_node(payload))
            elif self.path == "/api/nodes/tmux-ensure":
                self.write_json(200, tmux_ensure_node(payload))
            elif self.path == "/api/nodes/tmux-status":
                status, body = guarded_remote_post(
                    "nodes.tmux.status",
                    payload,
                    tmux_status_node,
                    endpoint="/api/nodes/tmux-status",
                )
                self.write_json(status, body)
            elif self.path == "/api/nodes/recovery-cycle":
                self.write_json(200, node_recovery_cycle(payload))
            elif self.path == "/api/nodes/heartbeat-tmux-start":
                self.write_json(200, heartbeat_tmux_start_node(payload))
            elif self.path == "/api/nodes/heartbeat":
                self.write_json(200, heartbeat_node(payload))
            elif self.path in ["/api/nodes/command", "/api/nodes/command-submit"]:
                self.write_json(200, enqueue_node_command(payload))
            elif self.path == "/api/phone-control/arm":
                self.write_json(200, phone_control_arm(payload))
            elif self.path == "/api/phone-control/disarm":
                self.write_json(200, phone_control_disarm(payload))
            else:
                self.write_json(404, {"error": "not found", "path": self.path})
        except Exception as exc:
            self.write_json(400, {"error": str(exc)})


def serve(args: argparse.Namespace) -> int:
    server = ThreadingHTTPServer((args.host, args.port), ControlHandler)
    print(f"a9 control api listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 mobile/control-plane API")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("operator-tail").add_argument("--limit", type=int, default=10)
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    if args.command == "status":
        print(json.dumps(supervisor_status(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "operator-tail":
        print(json.dumps(operator_tail(limit=args.limit), ensure_ascii=False, indent=2))
        return 0
    if args.command == "serve":
        return serve(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
