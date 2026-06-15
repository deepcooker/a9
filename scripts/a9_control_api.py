#!/usr/bin/env python3
"""A9 mobile/control-plane HTTP API.

This is intentionally small and stdlib-only. It exposes existing A9 state to a
phone/browser without making the phone a new source of truth.
"""

from __future__ import annotations

import argparse
import ipaddress
import importlib.util
import os
import shlex
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
CODEX_SESSIONS_DIR = Path("/root/.codex/sessions")
SUPERVISOR_PATH = ROOT / "scripts" / "a9_supervisor.py"
SESSION_REFRESH_PATH = ROOT / "scripts" / "a9_session_refresh.py"
MEMPALACE_PROVIDER_PATH = ROOT / "scripts" / "a9_mempalace_provider.py"
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
RECOVERY_LOOP_LATEST_REL_PATH = Path(".a9") / "services" / "recovery-loop-latest.json"
COMMUNICATION_OBSERVATION_REL_PATH = Path(".a9") / "services" / "communication-observation.json"
COMMUNICATION_REPAIR_SUGGESTIONS_REL_PATH = Path(".a9") / "services" / "communication-repair-suggestions.json"
COMMUNICATION_REPAIR_SUGGESTION_AUDIT_REL_PATH = Path(".a9") / "services" / "communication-repair-suggestion-audit.jsonl"
SERVICE_CONTROL_AUDIT_REL_PATH = Path(".a9") / "services" / "service-control-audit.jsonl"
MONITOR_INTERVENTION_AUDIT_REL_PATH = Path(".a9") / "monitor" / "interventions.jsonl"
RUNTIME_CONTROL_STATE_REL_PATH = Path(".a9") / "runtime" / "control_state.json"
LLM_WORKER_CONFIG_REL_PATH = Path(".a9") / "runtime" / "llm_worker_config.json"
BOOTSTRAP_TAKEOVER_ADMISSION_AUDIT_REL_PATH = Path(".a9") / "nodes" / "bootstrap-takeover-admissions.jsonl"
MONITOR_INTERVENTION_ALLOWED_ACTIONS = {
    "approve",
    "change_request",
    "pause",
    "reject",
    "repair",
    "resume",
    "rollback_request",
    "route_to_debate",
}
COMMUNICATION_DATA_CONTRACT_VERSION = "v1_draft"
COMMUNICATION_DATA_CONTRACT_OBJECTS = [
    "operator_session",
    "node",
    "ssh_identity",
    "tmux_session",
    "command",
    "command_result",
    "event_cursor",
    "heartbeat",
    "reconnect_state",
    "repair_action",
    "audit_event",
]
COMMUNICATION_DATA_CONTRACT_FIELDS = {
    "operator_session": [
        "operator_id",
        "client_kind",
        "client_id",
        "auth_scope",
        "connected_at",
        "last_seen_at",
        "last_event_id",
        "control_permissions",
        "status",
    ],
    "node": [
        "node_id",
        "hostname",
        "machine_id",
        "tailscale_ip",
        "ssh_target",
        "capabilities",
        "status",
        "status_reason",
        "revision",
        "last_seen_at",
    ],
    "ssh_identity": [
        "identity_id",
        "node_id",
        "user",
        "host",
        "port",
        "key_ref",
        "known_host_ref",
        "state",
        "last_probe_at",
    ],
    "tmux_session": [
        "tmux_id",
        "node_id",
        "session_name",
        "pane_id",
        "attached",
        "last_output_id",
        "state",
        "revision",
    ],
    "command": [
        "command_id",
        "node_id",
        "tmux_id",
        "created_by",
        "expected_revision",
        "ttl_ms",
        "policy_attestation",
        "status",
        "created_at",
        "started_at",
        "finished_at",
    ],
    "command_result": [
        "command_id",
        "stream_id",
        "status",
        "exit_code",
        "stdout_ref",
        "stderr_ref",
        "summary",
        "next_last_id",
    ],
    "event_cursor": [
        "stream",
        "consumer",
        "last_id",
        "oldest_id",
        "newest_id",
        "cursor_status",
        "updated_at",
    ],
    "heartbeat": [
        "node_id",
        "observed_at",
        "latency_ms",
        "runtime_pid",
        "tmux_state",
        "redis_state",
        "tailnet_state",
    ],
    "reconnect_state": [
        "node_id",
        "phase",
        "attempt",
        "action",
        "backoff_ms",
        "error_class",
        "budget_remaining",
        "updated_at",
    ],
    "repair_action": [
        "action_id",
        "kind",
        "target",
        "reason",
        "required_arm",
        "status",
        "evidence_path",
        "created_at",
    ],
    "audit_event": [
        "event_id",
        "actor",
        "command",
        "target",
        "gate",
        "before",
        "after",
        "evidence",
        "created_at",
    ],
}
COMMUNICATION_DATA_CONTRACT_BASELINE = {
    "operator_session": {
        "status": "missing",
        "current_surface": "No first-class operator_session entity in runtime",
        "missing_fields_or_gap": [
            "operator_session persistence",
            "operator_session schema enforcement",
            "operator object status transitions",
        ],
        "evidence": "docs/project.md Current Code Mapping",
    },
    "node": {
        "status": "partial",
        "current_surface": "Node snapshot via control API node status + .a9/nodes fallback",
        "missing_fields_or_gap": [
            "mysql authority table a9_nodes",
            "redisjson node snapshots",
            "full transition audit for phase/state changes",
        ],
        "evidence": "scripts/a9_node.py, scripts/a9_control_api.py node_status()",
    },
    "ssh_identity": {
        "status": "missing",
        "current_surface": "No dedicated ssh_identity store or lifecycle",
        "missing_fields_or_gap": [
            "identity table and state transitions",
            "host-key/auth failure handling for terminal states",
            "identity snapshots/replay",
        ],
        "evidence": "docs/project.md Current Code Mapping",
    },
    "tmux_session": {
        "status": "missing",
        "current_surface": "No tmux session persistence object in control/runtime schema",
        "missing_fields_or_gap": [
            "tmux session table and snapshots",
            "attached/detached lifecycle state",
            "session evidence join to command lifecycle",
        ],
        "evidence": "docs/project.md Current Code Mapping",
    },
    "command": {
        "status": "partial",
        "current_surface": "Command planning/claim/ack path exists, but no durable schema contract",
        "missing_fields_or_gap": [
            "mysql a9_commands persistence",
            "uniform expected_revision checks on all mutations",
            "command object snapshot API",
        ],
        "evidence": "scripts/a9_node.py command claim/ack/work loop",
    },
    "command_result": {
        "status": "partial",
        "current_surface": "Events and watch path exist, missing canonical object persistence contract",
        "missing_fields_or_gap": [
            "mysql a9_command_results",
            "canonical command_result snapshot/read APIs",
        ],
        "evidence": "scripts/a9_node.py command result emit path + scripts/a9_control_api.py node-command lookup/watch",
    },
    "event_cursor": {
        "status": "partial",
        "current_surface": "Replay cursor handling exists in API transport layer, no cursor object storage",
        "missing_fields_or_gap": [
            "redisjson a9_event_cursors table",
            "cursor object lifecycle and timeout repair persistence",
        ],
        "evidence": "scripts/a9_control_api.py read_events/next_replay/reset helpers",
    },
    "heartbeat": {
        "status": "partial",
        "current_surface": "Heartbeat execution evidence exists, but runtime object/schema not canonical",
        "missing_fields_or_gap": [
            "mysql a9_heartbeats",
            "redisjson a9:heartbeats snapshots",
            "uniform heartbeat state transitions",
        ],
        "evidence": "scripts/a9_node.py heartbeat execution + scripts/a9_control_api.py heartbeat APIs",
    },
    "reconnect_state": {
        "status": "partial",
        "current_surface": "Gateway reconnect decision exists, but no centralized reconnect_state object",
        "missing_fields_or_gap": [
            "redisjson a9:reconnect:{node_id}",
            "canonical reconnect action/state transitions",
            "budget/backoff persistence schema",
        ],
        "evidence": "crates/a9-gateway (via contract acceptance), scripts/a9_control_api.py reconnect governance",
    },
    "repair_action": {
        "status": "missing",
        "current_surface": "Repair suggestions/payloads are advisory, not a first-class repair_action entity",
        "missing_fields_or_gap": [
            "mysql a9_repair_actions",
            "repair_action lifecycle state persistence",
            "audit before/after for repair_action mutations",
        ],
        "evidence": "docs/project.md Current Code Mapping",
    },
    "audit_event": {
        "status": "partial",
        "current_surface": "Service-control audit and control logs exist, not full audit_event object table contract",
        "missing_fields_or_gap": [
            "mysql a9_audit_events",
            "canonical runtime-audit event object",
            "uniform actor/command/target before-after schema",
        ],
        "evidence": "scripts/a9_control_api.py service_control_audit_tail + a9_control_api action log paths",
    },
}
COMMUNICATION_DATA_CONTRACT_MODEL_CLOSURE = {
    "operator_session": {
        "mysql_authority": "a9_operator_sessions",
        "redis_keys": [
            "a9:operator_events",
            "a9:operator:{operator_id}:{client_id}",
        ],
        "status_enum": ["active", "idle", "stale", "revoked", "disconnected"],
        "owner": "runtime auth layer + operator control endpoints",
        "invariants": [
            "operator_session_id identifies one authenticated operator/client session",
            "authority-reducing transitions require operator identity evidence",
            "last_seen_at can only move forward unless explicitly reset",
        ],
        "evidence": "docs/project.md",
    },
    "event_cursor": {
        "mysql_authority": "a9_event_cursors",
        "redis_keys": [
            "a9:events",
            "a9:tasks",
        ],
        "status_enum": ["active", "gap_detected", "invalid", "stale", "reset_pending"],
        "owner": "operator-control API replay/watch surfaces",
        "invariants": [
            "stream and consumer identify a unique cursor entry",
            "next_last_id is monotonic non-decreasing for a stream+consumer pair",
            "gap_detected is not a terminal success state",
        ],
        "evidence": "docs/project.md",
    },
    "reconnect_state": {
        "mysql_authority": "a9_reconnect_states",
        "redis_keys": [
            "a9:reconnect_events",
            "a9:reconnect:{node_id}",
            "a9:events",
        ],
        "phase_enum": ["connect", "stream", "ssh", "tmux", "redis"],
        "action_enum": ["continue", "reconnect", "terminate", "quarantine", "watch"],
        "owner": "gateway worker/recovery loop decisions + operator/runtime governance paths",
        "invariants": [
            "phase/action are valid state machine values",
            "attempt must not decrease without explicit reset",
            "terminal SSH/auth/host-key failures must not auto-loop",
        ],
        "evidence": "docs/project.md",
    },
}


_COMMUNICATION_MODEL_CLOSURE_ENUM_FIELD_MAP = {
    "operator_session": {"status_enum": "status"},
    "event_cursor": {"status_enum": "cursor_status"},
    "reconnect_state": {"phase_enum": "phase", "action_enum": "action"},
}


def _communication_model_closure_missing_fields(
    object_name: str, payload: dict[str, Any]
) -> list[str]:
    required_fields = COMMUNICATION_DATA_CONTRACT_FIELDS.get(object_name, [])
    return [field for field in required_fields if field not in payload]


def _communication_model_closure_enum_violations(
    object_name: str, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    model_closure = COMMUNICATION_DATA_CONTRACT_MODEL_CLOSURE.get(object_name, {})
    enum_field_map = _COMMUNICATION_MODEL_CLOSURE_ENUM_FIELD_MAP.get(object_name, {})
    violations: list[dict[str, Any]] = []
    for enum_name, field_name in enum_field_map.items():
        allowed = model_closure.get(enum_name)
        if not isinstance(allowed, list) or field_name not in payload:
            continue
        value = payload.get(field_name)
        if value not in allowed:
            violations.append({"field": field_name, "value": value, "allowed": allowed})
    return violations


def communication_model_closure_serialize(
    object_name: str, payload: Any
) -> dict[str, Any]:
    requested = (object_name or "").strip()
    if not isinstance(payload, dict):
        return {
            "status": "invalid_payload",
            "kind": "communication_model_closure_serialize",
            "error_code": "invalid_payload",
            "object": requested,
            "serialized": {},
            "missing_fields": [],
            "enum_violations": [],
        }

    if requested not in COMMUNICATION_DATA_CONTRACT_MODEL_CLOSURE:
        return {
            "status": "unsupported_object",
            "kind": "communication_model_closure_serialize",
            "error_code": "unsupported_object",
            "object": requested,
            "serialized": {},
            "missing_fields": [],
            "enum_violations": [],
        }

    required_fields = COMMUNICATION_DATA_CONTRACT_FIELDS[requested]
    serialized = {field: payload.get(field) for field in required_fields}
    missing_fields = _communication_model_closure_missing_fields(requested, payload)
    enum_violations = _communication_model_closure_enum_violations(requested, payload)

    return {
        "status": "ok" if not missing_fields and not enum_violations else "invalid_model",
        "kind": "communication_model_closure_serialize",
        "object": requested,
        "serialized": serialized,
        "required_fields": required_fields,
        "missing_fields": missing_fields,
        "enum_violations": enum_violations,
    }


def communication_model_closure_validate(
    object_name: str, payload: Any
) -> dict[str, Any]:
    serialized = communication_model_closure_serialize(object_name, payload)
    return {**serialized, "kind": "communication_model_closure_validate"}


def communication_data_contract_report(
    *, object_name: str | None = None, root: Path = ROOT
) -> dict[str, Any]:
    requested = (object_name or "").strip()
    if requested and requested not in COMMUNICATION_DATA_CONTRACT_OBJECTS:
        required_fields = COMMUNICATION_DATA_CONTRACT_FIELDS.get(requested, [])
        return {
            "status": "ok",
            "kind": "communication_data_contract_report",
            "contract_version": COMMUNICATION_DATA_CONTRACT_VERSION,
            "generated_at": utc_now(),
            "objects": [
                {
                    "object": requested,
                    "status": "missing",
                    "current_surface": "unsupported object name",
                    "current_mapping": "unsupported object name",
                    "mysql_target": None,
                    "redis_target": None,
                    "required_fields": required_fields,
                    "missing_fields_or_gap": [f"unsupported object {requested} not in v1 contract"],
                    "evidence": "no_report_object",
                }
            ],
            "runtime_root": str(root),
        }

    payload_objects = []
    for item in COMMUNICATION_DATA_CONTRACT_OBJECTS:
        baseline = COMMUNICATION_DATA_CONTRACT_BASELINE[item]
        model_closure = COMMUNICATION_DATA_CONTRACT_MODEL_CLOSURE.get(item)
        current_surface = baseline.get("current_surface", "not_available")
        payload_objects.append(
            {
                "object": item,
                "status": baseline["status"],
                "current_surface": current_surface,
                "current_mapping": baseline.get("current_mapping", current_surface),
                "mysql_target": baseline.get("mysql_target"),
                "redis_target": baseline.get("redis_target"),
                "required_fields": COMMUNICATION_DATA_CONTRACT_FIELDS.get(item, []),
                "missing_fields_or_gap": baseline.get("missing_fields_or_gap", []),
                "evidence": baseline["evidence"],
                **(
                    {"model_closure": model_closure}
                    if model_closure is not None
                    else {}
                ),
            }
        )

    if requested:
        payload_objects = [item for item in payload_objects if item["object"] == requested]

    return {
        "status": "ok",
        "kind": "communication_data_contract_report",
        "contract_version": COMMUNICATION_DATA_CONTRACT_VERSION,
        "generated_at": utc_now(),
        "required_fields": COMMUNICATION_DATA_CONTRACT_FIELDS,
        "objects": payload_objects,
        "runtime_root": str(root),
    }
PHONE_CONTROL_GROUPS = {
    "runtime": [
        "submit.run",
        "session.refresh.trial",
        "session.lane.latest",
        "flow.resume",
        "plan.decision.approve",
        "plan.debate.next",
        "plan.backlog.next",
        "approval.approve",
        "approval.reject",
        "eval.override",
        "monitor.intervention",
        "services.start",
        "services.restart",
        "worker.transport.check",
        "worker.transport.config.update",
        "worker.transport.update",
    ],
    "remote": [
        "nodes.bootstrap.execute",
        "nodes.probe.execute",
        "nodes.recover.stale_commands",
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
MONITOR_INTERVENTIONS_STREAM_KEY = "a9:monitor:interventions"
TASKS_STREAM_TOP_CONSUMERS_LIMIT = 3
GATEWAY_CONTRACT_EVENT_STALE_SECONDS = 300
SERVICE_PROCESS_MARKERS = {
    "control-api": "a9_control_api.py serve",
    "node-worker": "a9_node.py command-work-loop",
    "recovery-loop": "a9_recovery_loop.py",
    "supervisor": "a9_supervisor.py run-loop",
}
SERVICE_HELPER_PATH = ROOT / "scripts" / "a9_service.py"
SERVICE_INTENT_CONTRACT = [
    {
        "service": "control-api",
        "unit_path": str(ROOT / "infra" / "systemd" / "a9-control-api.service"),
        "start_intent": "python3 scripts/a9_control_api.py serve --host 0.0.0.0 --port 8787",
    },
    {
        "service": "node-worker",
        "unit_path": str(ROOT / "infra" / "systemd" / "a9-node-worker.service"),
        "start_intent": "python3 scripts/a9_node.py command-work-loop --block-ms 5000 --timeout 10 --sleep-seconds 1 --min-idle-ms 30000",
    },
    {
        "service": "recovery-loop",
        "unit_path": str(ROOT / "infra" / "systemd" / "a9-recovery-loop.service"),
        "start_intent": "python3 scripts/a9_recovery_loop.py --controller-url http://127.0.0.1:8787 --interval-seconds 60 --timeout 10 --max-actions 3",
    },
    {
        "service": "supervisor",
        "unit_path": str(ROOT / "infra" / "systemd" / "a9-supervisor.service"),
        "start_intent": "python3 scripts/a9_supervisor.py run-loop --auto-next --sleep-seconds 10 --keep-going-on-error",
    },
]


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


def mempalace_provider() -> Any:
    return load_module("a9_mempalace_provider_control_api", MEMPALACE_PROVIDER_PATH)


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


def read_redis_stream(
    stream_key: str,
    last_id: str | None = None,
    *,
    count: int = 100,
    limit: int | None = None,
) -> dict[str, Any]:
    requested_raw = limit if limit is not None else count
    requested = max(1, min(EVENTS_STREAM_LIMIT_MAX, int(requested_raw)))
    if last_id is not None and not _looks_like_stream_id(last_id):
        return {
            "status": "degraded",
            "stream": stream_key,
            "error": "invalid last_id format, expected stream-id like 1740000000-0",
            "last_id": last_id,
            "requested_count": requested,
            "events": [],
        }

    start = "-" if not last_id else f"({last_id}"
    try:
        proc = redis_cli(["--raw", "XRANGE", stream_key, start, "+", "COUNT", str(requested)])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "degraded",
            "stream": stream_key,
            "error": str(exc),
            "last_id": last_id,
            "requested_count": requested,
            "events": [],
        }

    if proc.returncode != 0:
        return {
            "status": "degraded",
            "stream": stream_key,
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
            oldest_proc = redis_cli(["--raw", "XRANGE", stream_key, "-", "+", "COUNT", "1"])
            newest_proc = redis_cli(["--raw", "XREVRANGE", stream_key, "+", "-", "COUNT", "1"])
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "status": "degraded",
                "stream": stream_key,
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
        "stream": stream_key,
        "count": len(events),
        "requested_count": requested,
        "last_id": last_id,
        "events": events,
        "next_last_id": events[-1]["id"] if events else (last_id or ""),
    }


def read_events(last_id: str | None = None, *, count: int = 100, limit: int | None = None) -> dict[str, Any]:
    return read_redis_stream(EVENTS_STREAM_KEY, last_id, count=count, limit=limit)


def read_monitor_intervention_events(
    last_id: str | None = None,
    *,
    count: int = 100,
    limit: int | None = None,
) -> dict[str, Any]:
    payload = read_redis_stream(MONITOR_INTERVENTIONS_STREAM_KEY, last_id, count=count, limit=limit)
    payload["kind"] = "monitor_intervention_events"
    payload["schema"] = "a9.monitor_intervention_events.v1"
    return payload


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


def read_node_result_replay(
    last_id: str | None = None,
    *,
    event_stream: str = EVENTS_STREAM_KEY,
    count: int = 100,
    limit: int | None = None,
) -> dict[str, Any]:
    requested_raw = limit if limit is not None else count
    requested = max(1, min(EVENTS_STREAM_LIMIT_MAX, int(requested_raw)))
    safe_stream = str(event_stream or "").strip()
    if not safe_stream:
        return {
            "status": "degraded",
            "kind": "node_command_result_replay",
            "stream": safe_stream,
            "error_code": "invalid_payload",
            "error": "event_stream_required",
            "last_id": last_id,
            "requested_count": requested,
            "events": [],
            "next_last_id": "",
        }
    if last_id is not None and not _looks_like_stream_id(last_id):
        return {
            "status": "degraded",
            "kind": "node_command_result_replay",
            "stream": safe_stream,
            "error_code": "invalid_cursor",
            "error": "invalid last_id format, expected stream-id like 1740000000-0",
            "last_id": last_id,
            "requested_count": requested,
            "events": [],
            "next_last_id": "",
        }

    start = "-" if not last_id else f"({last_id}"
    try:
        proc = redis_cli(["--raw", "XRANGE", safe_stream, start, "+", "COUNT", str(requested)])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "degraded",
            "kind": "node_command_result_replay",
            "stream": safe_stream,
            "error_code": "redis_unavailable",
            "error": str(exc),
            "last_id": last_id,
            "requested_count": requested,
            "events": [],
            "next_last_id": "",
        }
    if proc.returncode != 0:
        return {
            "status": "degraded",
            "kind": "node_command_result_replay",
            "stream": safe_stream,
            "error_code": "redis_command_failed",
            "error": proc.stdout.strip() or "redis command failed",
            "last_id": last_id,
            "requested_count": requested,
            "events": [],
            "next_last_id": "",
        }

    events = [evt for evt in parse_xrange_events(proc.stdout) if str((evt.get("fields") or {}).get("kind") or "") == "node_command_result"]
    if last_id and not events:
        try:
            oldest_proc = redis_cli(["--raw", "XRANGE", safe_stream, "-", "+", "COUNT", "1"])
            newest_proc = redis_cli(["--raw", "XREVRANGE", safe_stream, "+", "-", "COUNT", "1"])
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "status": "degraded",
                "kind": "node_command_result_replay",
                "stream": safe_stream,
                "error_code": "redis_unavailable",
                "error": str(exc),
                "last_id": last_id,
                "requested_count": requested,
                "events": [],
                "next_last_id": "",
            }
        if oldest_proc.returncode == 0 and newest_proc.returncode == 0:
            oldest_events = parse_xrange_events(oldest_proc.stdout)
            newest_events = parse_xrange_events(newest_proc.stdout)
            if oldest_events and newest_events:
                oldest_id = str(oldest_events[0].get("id") or "")
                newest_id = str(newest_events[0].get("id") or "")
                return {
                    "status": "degraded",
                    "kind": "node_command_result_replay",
                    "stream": safe_stream,
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
        "kind": "node_command_result_replay",
        "stream": safe_stream,
        "count": len(events),
        "requested_count": requested,
        "last_id": last_id,
        "events": events,
        "next_last_id": str(events[-1].get("id") or "") if events else (last_id or ""),
    }


def result_replay_reset_decision(response: dict[str, Any]) -> dict[str, Any]:
    """Return bounded client action for /api/node-command-results replay responses."""
    if response.get("status") == "degraded":
        error_code = str(response.get("error_code") or "")
        if error_code == "cursor_gap":
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
        if error_code == "invalid_cursor":
            return {
                "action": "retry_without_cursor",
                "reason": "invalid_cursor_format",
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
    data = read_json(summaries[-1])
    if isinstance(data, dict):
        data.setdefault("summary_path", str(summaries[-1]))
    return data


def is_selftest_summary(summary: dict[str, Any] | None) -> bool:
    if not isinstance(summary, dict):
        return False
    values = [summary.get("task_id"), summary.get("run_dir"), summary.get("summary_path")]
    for value in values:
        path = Path(str(value or "").strip())
        if any(part.startswith("selftest-") for part in path.parts):
            return True
        if path.name.startswith("selftest-"):
            return True
    return False


def read_run_summary(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict):
        return {}
    data.setdefault("summary_path", str(path))
    return data


def active_plan_payload(root: Path = ROOT) -> dict[str, Any]:
    plans_dir = root / ".a9" / "plans"
    active_path = plans_dir / ".active_plan"
    if not active_path.exists():
        return {}
    try:
        plan_id = active_path.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    if not plan_id:
        return {}
    plan_path = plans_dir / plan_id / "plan.json"
    if not plan_path.exists():
        return {}
    data = read_json(plan_path)
    return data if isinstance(data, dict) else {}


def latest_plan_run_summary(root: Path = ROOT) -> dict[str, Any]:
    plan = active_plan_payload(root)
    if not plan:
        return {}
    evidence_refs = plan.get("evidence_refs", []) if isinstance(plan.get("evidence_refs"), list) else []
    for value in reversed(evidence_refs):
        text = str(value or "").strip()
        if not text or any(part.startswith("selftest-") for part in Path(text).parts):
            continue
        if not text.endswith("/summary.json"):
            continue
        path = Path(text)
        if not path.is_absolute():
            path = root / path
        data = read_run_summary(path)
        if data:
            return data
        return {"summary_path": str(path)}
    run_ids = plan.get("run_ids", []) if isinstance(plan.get("run_ids"), list) else []
    for value in reversed(run_ids):
        run_id = str(value or "").strip()
        if not run_id or run_id.startswith("selftest-"):
            continue
        path = root / ".a9" / "runs" / run_id / "summary.json"
        data = read_run_summary(path)
        if data:
            return data
    return {}


def tail_plan_progress_line(
    plan: dict[str, Any],
    *,
    root: Path = ROOT,
    actor: str | None = None,
    max_chars: int = 260,
) -> str:
    plan_id = str(plan.get("plan_id") or "").strip() if plan else ""
    if not plan_id:
        return ""
    path = root / ".a9" / "plans" / plan_id / "progress.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for raw in reversed(lines):
        text = str(raw or "").strip()
        if not text or text.startswith("#"):
            continue
        if actor and f"actor={actor}" not in text:
            continue
        return text[:max_chars]
    return ""


def latest_plan_progress_lane(root: Path = ROOT) -> dict[str, Any]:
    plan = active_plan_payload(root)
    latest_progress = tail_plan_progress_line(plan, root=root)
    latest_monitor_progress = tail_plan_progress_line(plan, root=root, actor="monitor")
    return {
        "latest_progress": latest_progress,
        "latest_monitor_progress": latest_monitor_progress,
        "has_monitor_progress": bool(latest_monitor_progress),
    }


def latest_run_lanes(root: Path = ROOT) -> dict[str, Any]:
    summaries = sorted((root / ".a9" / "runs").glob("*/summary.json"), key=lambda path: path.stat().st_mtime)
    latest_any: dict[str, Any] = {}
    latest_real: dict[str, Any] = {}
    latest_selftest: dict[str, Any] = {}
    invalid_summaries = 0
    for summary_path in reversed(summaries):
        data = read_run_summary(summary_path)
        if not data:
            invalid_summaries += 1
            continue
        if not latest_any:
            latest_any = data
        if is_selftest_summary(data):
            if not latest_selftest:
                latest_selftest = data
        elif not latest_real:
            latest_real = data
        if latest_any and latest_real and latest_selftest:
            break
    return {
        "latest_any": compact_summary(latest_any),
        "latest_real": compact_summary(latest_real),
        "latest_selftest": compact_summary(latest_selftest),
        "latest_plan": compact_summary(latest_plan_run_summary(root)),
        "latest_plan_progress": latest_plan_progress_lane(root),
        "invalid_summaries": invalid_summaries,
    }


def queued_task_quality_summary(root: Path = ROOT, limit: int = 10) -> dict[str, Any]:
    queue_dir = root / ".a9" / "tasks" / "queue"
    queued = sorted(queue_dir.glob("*.md"))
    warning_tasks: list[dict[str, Any]] = []
    warnings_by_code: dict[str, int] = {}
    warning_task_count = 0
    warnings_count = 0
    parse_errors = 0
    for path in queued:
        try:
            task = supervisor().parse_task(path)
            warnings = list(task.task_quality_warnings)
            task_id = task.task_id
            phase = task.phase
        except Exception:
            parse_errors += 1
            warning_task_count += 1
            warnings = ["task_parse_error"]
            task_id = path.stem
            phase = ""
        if not warnings:
            continue
        if warnings != ["task_parse_error"]:
            warning_task_count += 1
        warnings_count += len(warnings)
        for warning in warnings:
            code = str(warning).split(":", 1)[0]
            warnings_by_code[code] = warnings_by_code.get(code, 0) + 1
        if len(warning_tasks) < limit:
            warning_tasks.append(
                {
                    "task_id": task_id,
                    "path": str(path),
                    "phase": phase,
                    "warnings": warnings,
                }
            )
    return {
        "status": "warning" if warning_task_count else "ok",
        "queued_task_count": len(queued),
        "warning_task_count": warning_task_count,
        "warnings_count": warnings_count,
        "warnings_by_code": warnings_by_code,
        "tasks": warning_tasks,
        "truncated": warning_task_count > len(warning_tasks),
        "parse_errors": parse_errors,
    }


def compact_runtime_monitor_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(contract, dict):
        return {}
    task = contract.get("task", {}) if isinstance(contract.get("task"), dict) else {}
    run = contract.get("run", {}) if isinstance(contract.get("run"), dict) else {}
    monitor = contract.get("monitor", {}) if isinstance(contract.get("monitor"), dict) else {}
    command_envelope = contract.get("command_envelope", {}) if isinstance(contract.get("command_envelope"), dict) else {}
    evidence_refs = contract.get("evidence_refs", {}) if isinstance(contract.get("evidence_refs"), dict) else {}
    guardrails = contract.get("guardrails", {}) if isinstance(contract.get("guardrails"), dict) else {}
    worker_intent = contract.get("worker_intent", {}) if isinstance(contract.get("worker_intent"), dict) else {}
    worker_prompt = contract.get("worker_prompt", {}) if isinstance(contract.get("worker_prompt"), dict) else {}
    diff_and_checks = contract.get("diff_and_checks", {}) if isinstance(contract.get("diff_and_checks"), dict) else {}
    execution = contract.get("execution", {}) if isinstance(contract.get("execution"), dict) else {}
    return {
        "schema": contract.get("schema"),
        "task": {
            "task_id": task.get("task_id"),
            "phase": task.get("phase"),
            "route": task.get("route"),
            "plan_revision": task.get("plan_revision"),
            "allowed_paths": task.get("allowed_paths", []),
            "declared_checks": task.get("declared_checks", []),
        },
        "run": {
            "run_id": run.get("run_id"),
            "status": run.get("status"),
            "attempt": run.get("attempt"),
            "run_dir": run.get("run_dir"),
        },
        "worker_intent": {
            "status": worker_intent.get("status"),
            "phase_focus": worker_intent.get("phase_focus"),
            "reference_gate_status": worker_intent.get("reference_gate_status"),
        },
        "worker_prompt": {
            "prompt_path": worker_prompt.get("prompt_path"),
            "raw_task_path": worker_prompt.get("raw_task_path"),
            "prompt_approx_tokens": worker_prompt.get("prompt_approx_tokens"),
            "prompt_budget_tokens": worker_prompt.get("prompt_budget_tokens"),
        },
        "command_envelope": {
            "command_id": command_envelope.get("command_id"),
            "target_node": command_envelope.get("target_node"),
            "expected_revision": command_envelope.get("expected_revision"),
            "idempotency_key": command_envelope.get("idempotency_key"),
            "evidence_path": command_envelope.get("evidence_path"),
        },
        "execution": {
            "worker_model": execution.get("worker_model"),
            "return_code": execution.get("return_code"),
            "timed_out": execution.get("timed_out"),
            "idle_timed_out": execution.get("idle_timed_out"),
            "budget_stopped": execution.get("budget_stopped"),
        },
        "diff_and_checks": {
            "changed_files": diff_and_checks.get("changed_files", []),
            "checks_count": diff_and_checks.get("checks_count"),
            "failed_checks_count": diff_and_checks.get("failed_checks_count"),
            "diff_path": diff_and_checks.get("diff_path"),
        },
        "monitor": {
            "next_action": monitor.get("next_action"),
            "recommended_action": monitor.get("recommended_action"),
            "decision_model": monitor.get("decision_model"),
            "score": monitor.get("score"),
            "intervention_options": monitor.get("intervention_options", []),
            "block": monitor.get("block", {}),
        },
        "evidence_refs": {
            "runtime_monitor_contract_path": evidence_refs.get("runtime_monitor_contract_path"),
            "summary_path": evidence_refs.get("summary_path"),
            "execution_chain_path": evidence_refs.get("execution_chain_path"),
            "evidence_path": evidence_refs.get("evidence_path"),
            "state_path": evidence_refs.get("state_path"),
        },
        "guardrails": guardrails,
    }


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
    runtime_monitor_contract = compact_runtime_monitor_contract(summary.get("runtime_monitor_contract"))
    return {
        "task_id": summary.get("task_id"),
        "status": summary.get("status"),
        "phase": summary.get("phase"),
        "run_dir": summary.get("run_dir"),
        "summary_path": summary.get("summary_path"),
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
        "runtime_monitor_contract": runtime_monitor_contract,
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
    worker_transport_health_path = state_dir / "runtime" / "worker_transport_health.json"
    return {
        "queued": len(queued),
        "running": len(running),
        "done": len(done),
        "queue": [str(path) for path in queued[-20:]],
        "task_quality": queued_task_quality_summary(root),
        "running_tasks": [read_json(path) for path in running[-20:]],
        "latest_run": compact_summary(latest_run_summary(root)),
        "latest_run_lanes": latest_run_lanes(root),
        "progress": read_json(progress_path) if progress_path.exists() else {},
        "daemon_heartbeat": read_json(heartbeat_path) if heartbeat_path.exists() else {},
        "worker_transport_health": read_json(worker_transport_health_path) if worker_transport_health_path.exists() else {},
        "service_observation": service_observation_status(root),
        "nodes": node_status(root),
        "gateway": gateway_transport_contract(root),
    }


def parse_service_process_table(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 3)
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        kind = ""
        cmd = parts[3]
        for service, marker in SERVICE_PROCESS_MARKERS.items():
            if marker in cmd:
                kind = service
                break
        if not kind:
            continue
        rows.append(
            {
                "service": kind,
                "pid": int(parts[0]),
                "ppid": int(parts[1]) if parts[1].isdigit() else 0,
                "etime": parts[2],
                "cmd": cmd,
            }
        )
    return rows


def service_observed_processes(root: Path = ROOT) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid,ppid,etime,cmd"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "degraded", "reason": "ps_probe_failed", "error": str(exc), "processes": []}
    if proc.returncode != 0:
        return {
            "status": "degraded",
            "reason": "ps_probe_failed",
            "error": (proc.stdout or "").strip() or "ps return code non-zero",
            "processes": [],
        }
    return {"status": "ok", "reason": "ps_probe_ok", "processes": parse_service_process_table(proc.stdout)}


def service_observation_status(root: Path = ROOT) -> dict[str, Any]:
    observed = service_observed_processes(root)
    process_rows = observed.get("processes", [])
    by_service: dict[str, list[dict[str, Any]]] = {}
    for row in process_rows if isinstance(process_rows, list) else []:
        service = str(row.get("service") or "")
        if not service:
            continue
        by_service.setdefault(service, []).append(row)

    services: list[dict[str, Any]] = []
    missing_services: list[str] = []
    for contract in SERVICE_INTENT_CONTRACT:
        service = str(contract.get("service") or "")
        rows = by_service.get(service, [])
        running = bool(rows)
        if not running:
            missing_services.append(service)
        services.append(
            {
                "service": service,
                "unit_path": contract.get("unit_path"),
                "start_intent": contract.get("start_intent"),
                "observed_running": running,
                "process_count": len(rows),
                "observed_processes": rows,
                "observation_status": "running" if running else "missing",
                "next_action": "observe" if running else "start_service",
            }
        )

    return {
        "status": observed.get("status", "degraded"),
        "checked_at": utc_now(),
        "intent": {"services": SERVICE_INTENT_CONTRACT},
        "observed": {
            "reason": observed.get("reason", ""),
            "services": services,
            "missing_services": missing_services,
            "missing_count": len(missing_services),
            "next_action": "observe" if not missing_services else "start_missing_services",
        },
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


def remote_shell_path(path_value: str) -> str:
    raw = str(path_value or "").strip()
    if raw.startswith("~/"):
        suffix = raw[2:].replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
        return f'"$HOME/{suffix}"'
    return shlex.quote(raw)


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


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


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
            action = (
                payload.get("recovery_action")
                or payload.get("probe_action")
                or payload.get("repair_action")
                or payload.get("heartbeat_action")
                or payload.get("tmux_action")
                or payload.get("bootstrap_action")
            )
            reason = (
                payload.get("reason")
                or payload.get("probe_action_reason")
                or payload.get("repair_action_reason")
                or payload.get("heartbeat_action_reason")
                or payload.get("tmux_action_reason")
                or payload.get("bootstrap_action_reason")
            )
            items.append(
                {
                    "node_id": directory.name,
                    "kind": kind,
                    "status": payload.get("status"),
                    "action": action,
                    "reason": reason,
                    "target": payload.get("target"),
                    "session": payload.get("session"),
                    "return_code": payload.get("return_code"),
                    "timed_out": payload.get("timed_out"),
                    "step_count": payload.get("step_count"),
                    "path": str(path),
                    "bytes": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
                }
            )
    items.sort(key=lambda item: str(item["mtime"]), reverse=True)
    safe_limit = max(1, min(int(limit), 200))
    return {"status": "ok", "count": len(items), "limit": safe_limit, "items": items[:safe_limit]}


def recovery_loop_latest(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / RECOVERY_LOOP_LATEST_REL_PATH
    observation_path = root / COMMUNICATION_OBSERVATION_REL_PATH
    suggestions_path = root / COMMUNICATION_REPAIR_SUGGESTIONS_REL_PATH
    if not path.exists():
        return {
            "status": "missing",
            "kind": "recovery_loop_latest",
            "path": str(path),
            "reason": "recovery_loop_latest_not_found",
        }
    try:
        payload = read_json(path)
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "status": "degraded",
            "kind": "recovery_loop_latest",
            "path": str(path),
            "reason": "recovery_loop_latest_unreadable",
            "error": str(exc),
        }
    stat = path.stat()
    cycle = payload.get("cycle") if isinstance(payload.get("cycle"), dict) else {}
    communication_observation = payload.get("communication_observation") if isinstance(payload.get("communication_observation"), dict) else None
    if communication_observation is None and observation_path.exists():
        try:
            communication_observation = read_json(observation_path)
        except (json.JSONDecodeError, OSError):
            communication_observation = None
    suggestions = payload.get("communication_repair_suggestions") if isinstance(payload.get("communication_repair_suggestions"), dict) else None
    if suggestions is None and suggestions_path.exists():
        try:
            suggestions = read_json(suggestions_path)
        except (json.JSONDecodeError, OSError):
            suggestions = None
    communication_execute_enabled = (
        payload.get("communication_execute_enabled")
        if "communication_execute_enabled" in payload
        else payload.get("execute")
    )
    return {
        "status": "ok",
        "kind": "recovery_loop_latest",
        "path": str(path),
        "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        "checked_at": payload.get("checked_at"),
        "controller_url": payload.get("controller_url"),
        "cycle_status": payload.get("cycle_status"),
        "step_count": payload.get("step_count"),
        "risk_count": payload.get("risk_count"),
        "execute": payload.get("execute"),
        "communication_execute_enabled": communication_execute_enabled,
        "communication_route_execution": payload.get("communication_route_execution"),
        "communication_plan_status": payload.get("communication_plan_status"),
        "communication_action": payload.get("communication_action"),
        "communication_priority_source": payload.get("communication_priority_source"),
        "communication_route": payload.get("communication_route") or {},
        "communication_observation": communication_observation or {},
        "communication_repair_suggestions": suggestions or {},
        "summary": cycle.get("summary") if isinstance(cycle, dict) else None,
        "steps": cycle.get("steps", [])[:8] if isinstance(cycle, dict) else [],
        "raw_status": payload.get("status"),
        "error": payload.get("error"),
    }


def communication_repair_suggestions(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / COMMUNICATION_REPAIR_SUGGESTIONS_REL_PATH
    if not path.exists():
        return {
            "status": "missing",
            "kind": "communication_repair_suggestions",
            "path": str(path),
            "pending_count": 0,
            "pending": [],
            "reason": "communication_repair_suggestions_not_found",
        }
    try:
        payload = read_json(path)
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "status": "degraded",
            "kind": "communication_repair_suggestions",
            "path": str(path),
            "pending_count": 0,
            "pending": [],
            "reason": "communication_repair_suggestions_unreadable",
            "error": str(exc),
        }
    pending = payload.get("pending") if isinstance(payload.get("pending"), list) else []
    approved = payload.get("approved") if isinstance(payload.get("approved"), list) else []
    closed = payload.get("closed") if isinstance(payload.get("closed"), list) else []
    return {
        "status": str(payload.get("status") or "ok"),
        "kind": "communication_repair_suggestions",
        "path": str(path),
        "updated_at": payload.get("updated_at"),
        "mode": payload.get("mode"),
        "pending_count": int(payload.get("pending_count") or len(pending)),
        "pending": pending[:20],
        "approved_count": int(payload.get("approved_count") or len(approved)),
        "approved": approved[:20],
        "closed_count": int(payload.get("closed_count") or len(closed)),
        "closed": closed[:20],
        "last_observation": payload.get("last_observation") if isinstance(payload.get("last_observation"), dict) else {},
    }


def append_communication_suggestion_audit(event: dict[str, Any], *, root: Path = ROOT) -> None:
    path = root / COMMUNICATION_REPAIR_SUGGESTION_AUDIT_REL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def enqueue_communication_suggestion_audit(event: dict[str, Any], *, root: Path = ROOT) -> None:
    def safe_append() -> None:
        try:
            append_communication_suggestion_audit(event, root=root)
        except OSError:
            return

    if Path(root) != ROOT:
        safe_append()
        return
    thread = threading.Thread(
        target=safe_append,
        daemon=True,
    )
    thread.start()


def build_service_control_audit_event(
    action: str,
    command: str,
    status: str,
    *,
    target_services: list[str] | None = None,
    requested_services: list[str] | None = None,
    reason: str | None = None,
    gate: dict[str, Any] | None = None,
    return_code: int | None = None,
    payload: dict[str, Any] | None = None,
    service_observation: dict[str, Any] | None = None,
    service_observation_path: str | None = None,
) -> dict[str, Any]:
    operator_scopes = payload.get("operator_scopes") if isinstance(payload, dict) else []
    scope_count = len([scope for scope in operator_scopes if str(scope).strip()]) if isinstance(operator_scopes, list) else 0
    observation_summary: dict[str, Any] | None = None
    if isinstance(service_observation, dict):
        observed = service_observation.get("observed")
        if isinstance(observed, dict):
            observation_summary = {
                "status": service_observation.get("status"),
                "checked_at": service_observation.get("checked_at"),
                "observed_status": observed.get("next_action"),
                "missing_count": observed.get("missing_count"),
            }
    event = {
        "at": utc_now(),
        "action": action,
        "command": command,
        "status": status,
    }
    if status in {"blocked", "invalid_request"} and reason:
        event["reason"] = reason
    if target_services is not None:
        event["target_services"] = target_services
    if requested_services is not None:
        event["requested_services"] = requested_services
    if gate is not None:
        event["gate_allowed"] = bool(gate.get("allowed"))
        event["gate_reason"] = gate.get("reason") or gate.get("status")
        event["gate_status"] = gate.get("status")
    if return_code is not None:
        event["return_code"] = return_code
    if reason and status == "failed":
        event["reason"] = reason
    if observation_summary is not None:
        event["service_observation_summary"] = observation_summary
    if service_observation_path:
        event["service_observation_path"] = service_observation_path
    event["has_operator_scope"] = scope_count > 0
    event["operator_scope_count"] = scope_count
    return event


def append_service_control_audit(event: dict[str, Any], *, root: Path = ROOT) -> None:
    path = root / SERVICE_CONTROL_AUDIT_REL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def service_control_audit_tail(limit: int = 20, *, root: Path = ROOT) -> dict[str, Any]:
    safe_limit = max(1, min(100, int(limit)))
    path = root / SERVICE_CONTROL_AUDIT_REL_PATH
    if not path.exists():
        return {
            "status": "missing",
            "kind": "service_control_audit_tail",
            "path": str(path),
            "events": [],
            "event_count": 0,
            "skipped_bad_lines": 0,
            "reason": "service_control_audit_file_not_found",
        }

    skipped_bad_lines = 0
    events: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            skipped_bad_lines += 1
            continue
        if not isinstance(payload, dict):
            skipped_bad_lines += 1
            continue
        events.append(payload)

    bounded_events = events[-safe_limit:]
    result = {
        "status": "degraded" if skipped_bad_lines else "ok",
        "kind": "service_control_audit_tail",
        "path": str(path),
        "events": bounded_events,
        "event_count": len(bounded_events),
        "skipped_bad_lines": skipped_bad_lines,
    }
    if skipped_bad_lines:
        result["reason"] = "service_control_audit_tail_bad_lines_skipped"
    return result


def enqueue_service_control_audit(event: dict[str, Any], *, root: Path = ROOT) -> None:
    def safe_append() -> None:
        try:
            append_service_control_audit(event, root=root)
        except OSError:
            return

    if Path(root) != ROOT:
        safe_append()
        return
    thread = threading.Thread(
        target=safe_append,
        daemon=True,
    )
    thread.start()


def monitor_intervention_audit_path(root: Path = ROOT) -> Path:
    return root / MONITOR_INTERVENTION_AUDIT_REL_PATH


def append_monitor_intervention_audit(event: dict[str, Any], *, root: Path = ROOT) -> None:
    path = monitor_intervention_audit_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def enqueue_monitor_intervention_audit(event: dict[str, Any], *, root: Path = ROOT) -> None:
    def safe_append() -> None:
        try:
            append_monitor_intervention_audit(event, root=root)
        except OSError:
            return

    if Path(root) != ROOT:
        safe_append()
        return
    thread = threading.Thread(
        target=safe_append,
        daemon=True,
    )
    thread.start()


def monitor_intervention_audit_tail(limit: int = 20, *, root: Path = ROOT) -> dict[str, Any]:
    safe_limit = max(1, min(100, int(limit)))
    path = monitor_intervention_audit_path(root)
    if not path.exists():
        return {
            "status": "missing",
            "kind": "monitor_intervention_audit_tail",
            "path": str(path),
            "events": [],
            "event_count": 0,
            "skipped_bad_lines": 0,
            "reason": "monitor_intervention_audit_file_not_found",
        }

    skipped_bad_lines = 0
    events: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            skipped_bad_lines += 1
            continue
        if not isinstance(payload, dict):
            skipped_bad_lines += 1
            continue
        events.append(payload)

    bounded_events = events[-safe_limit:]
    result = {
        "status": "degraded" if skipped_bad_lines else "ok",
        "kind": "monitor_intervention_audit_tail",
        "path": str(path),
        "events": bounded_events,
        "event_count": len(bounded_events),
        "skipped_bad_lines": skipped_bad_lines,
    }
    if skipped_bad_lines:
        result["reason"] = "monitor_intervention_audit_tail_bad_lines_skipped"
    return result


def publish_monitor_intervention_redis(event: dict[str, Any]) -> dict[str, Any]:
    if not redis_available():
        return {"status": "skipped", "reason": "redis_unavailable", "stream": MONITOR_INTERVENTIONS_STREAM_KEY}
    try:
        stream = redis_cli(
            [
                "XADD",
                MONITOR_INTERVENTIONS_STREAM_KEY,
                "*",
                "kind",
                str(event.get("kind") or "monitor_intervention_audit"),
                "schema",
                str(event.get("schema") or "a9.monitor_intervention.v1"),
                "intervention_id",
                str(event.get("intervention_id") or ""),
                "action",
                str(event.get("action") or ""),
                "status",
                str(event.get("status") or ""),
                "task_id",
                str(event.get("task_id") or ""),
                "run_id",
                str(event.get("run_id") or ""),
                "actor",
                str(event.get("actor") or ""),
                "gate_allowed",
                "1" if event.get("gate_allowed") else "0",
                "effect_mode",
                str((event.get("execution_effect") or {}).get("mode") if isinstance(event.get("execution_effect"), dict) else ""),
                "at",
                str(event.get("at") or utc_now()),
                "payload_json",
                json.dumps(event, ensure_ascii=False, separators=(",", ":")),
            ]
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "stream": MONITOR_INTERVENTIONS_STREAM_KEY, "error": str(exc)}
    if stream.returncode != 0:
        return {
            "status": "failed",
            "stream": MONITOR_INTERVENTIONS_STREAM_KEY,
            "error": stream.stdout.strip() or "redis xadd failed",
        }
    return {"status": "ok", "stream": MONITOR_INTERVENTIONS_STREAM_KEY, "stream_id": stream.stdout.strip()}


def monitor_intervention_examples(root: Path = ROOT) -> dict[str, Any]:
    status = monitor_status(root)
    latest_run = status.get("latest_run") if isinstance(status.get("latest_run"), dict) else {}
    evidence_refs = status.get("evidence_refs") if isinstance(status.get("evidence_refs"), dict) else {}
    evidence_list = normalize_monitor_intervention_evidence_refs(evidence_refs)
    task_id = latest_run.get("task_id") or "latest-task"
    run_id = latest_run.get("run_id") or "latest-run"
    return {
        "status": "ok",
        "kind": "monitor_intervention_examples",
        "schema": "a9.monitor_intervention_examples.v1",
        "endpoint": "/api/monitor/intervention",
        "requires": {
            "operator_scopes": [PHONE_ADMIN_SCOPE],
            "phone_control_group": "runtime",
            "phone_control_command": "monitor.intervention",
        },
        "examples": {
            "pause": {
                "action": "pause",
                "reason": "operator inspection before next claim",
                "operator_scopes": [PHONE_ADMIN_SCOPE],
                "task_id": task_id,
                "run_id": run_id,
            },
            "resume": {
                "action": "resume",
                "reason": "inspection complete",
                "operator_scopes": [PHONE_ADMIN_SCOPE],
            },
            "repair": {
                "action": "repair",
                "reason": "failed check needs deterministic repair",
                "operator_scopes": [PHONE_ADMIN_SCOPE],
                "task_id": task_id,
                "run_id": run_id,
                "evidence_refs": evidence_list[:5],
            },
            "route_to_debate": {
                "action": "route_to_debate",
                "reason": "requirements or architecture decision needs review",
                "operator_scopes": [PHONE_ADMIN_SCOPE],
                "task_id": task_id,
                "run_id": run_id,
            },
            "approve": {
                "action": "approve",
                "reason": "operator approved worker request",
                "operator_scopes": [PHONE_ADMIN_SCOPE],
                "flow_id": "flow-id-from-task-frontmatter",
                "flow_expected_revision": 1,
                "evidence_id": "checkpoint-or-intervention-id",
            },
            "reject": {
                "action": "reject",
                "reason": "operator rejected worker request",
                "operator_scopes": [PHONE_ADMIN_SCOPE],
                "flow_id": "flow-id-from-task-frontmatter",
                "flow_expected_revision": 1,
                "evidence_id": "checkpoint-or-intervention-id",
            },
        },
    }


def normalize_monitor_intervention_evidence_refs(payload: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(payload, dict):
        iterable: list[Any] = [value for value in payload.values()]
    elif isinstance(payload, list):
        iterable = payload
    elif payload:
        iterable = [payload]
    else:
        iterable = []
    for item in iterable:
        ref = str(item or "").strip()
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def build_monitor_intervention_command(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    status = monitor_status(root)
    latest_run = status.get("latest_run") if isinstance(status.get("latest_run"), dict) else {}
    command_envelope = status.get("command_envelope") if isinstance(status.get("command_envelope"), dict) else {}
    action = str(payload.get("action") or "").strip().lower()
    if action not in MONITOR_INTERVENTION_ALLOWED_ACTIONS:
        raise ValueError(
            "action must be one of: " + ", ".join(sorted(MONITOR_INTERVENTION_ALLOWED_ACTIONS))
        )
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValueError("reason is required")

    run_id = str(payload.get("run_id") or latest_run.get("run_id") or "").strip()
    task_id = str(payload.get("task_id") or latest_run.get("task_id") or "").strip()
    actor = str(payload.get("actor") or "mobile-operator").strip()
    expected_revision = payload.get("expected_revision", command_envelope.get("expected_revision"))
    idempotency_key = str(
        payload.get("idempotency_key")
        or command_envelope.get("idempotency_key")
        or f"{action}:{task_id or 'no-task'}:{run_id or 'no-run'}"
    ).strip()
    intervention_seed = f"{action}:{task_id}:{run_id}:{idempotency_key}"
    intervention_slug = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", intervention_seed).strip("-")[:96]
    evidence_refs = normalize_monitor_intervention_evidence_refs(payload.get("evidence_refs"))
    for ref in normalize_monitor_intervention_evidence_refs(status.get("evidence_refs")):
        if ref not in evidence_refs:
            evidence_refs.append(ref)

    return {
        "status": "ready",
        "kind": "monitor_intervention_command",
        "schema": "a9.monitor_intervention.v1",
        "command": "monitor.intervention",
        "intervention_id": f"monitor-{intervention_slug or utc_now().replace(':', '')}",
        "action": action,
        "reason": reason,
        "actor": actor,
        "task_id": task_id or None,
        "run_id": run_id or None,
        "expected_revision": expected_revision,
        "idempotency_key": idempotency_key,
        "flow_id": str(payload.get("flow_id") or "").strip() or None,
        "flow_expected_revision": payload.get("flow_expected_revision", payload.get("expected_revision")),
        "flow_expected_last_seq": payload.get("flow_expected_last_seq"),
        "flow_sequence": payload.get("flow_sequence"),
        "evidence_id": str(payload.get("evidence_id") or "").strip() or None,
        "evidence_refs": evidence_refs,
        "proposal": payload.get("proposal"),
        "target": payload.get("target") or "runtime_monitor",
        "created_at": utc_now(),
        "monitor_status_snapshot": {
            "next_action": status.get("next_action"),
            "latest_run_status": latest_run.get("status"),
            "failed_checks_count": status.get("failed_checks_count"),
            "changed_files": status.get("changed_files", []),
        },
        "execution_effect": {
            "mode": "supervisor_routed",
            "reason": "typed_intervention_contract_with_supervisor_effect_routing",
        },
    }


def monitor_intervention(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    require_phone_admin(payload)
    command = build_monitor_intervention_command(payload, root=root)
    gate = command_gate(command["command"], root=root)
    effect = command.get("execution_effect", {})
    if gate.get("allowed"):
        effect = supervisor().apply_monitor_intervention_effect(command)
    event = {
        "at": utc_now(),
        "schema": command["schema"],
        "kind": "monitor_intervention_audit",
        "command": command["command"],
        "intervention_id": command["intervention_id"],
        "action": command["action"],
        "status": "recorded" if gate.get("allowed") else "blocked",
        "reason": command["reason"] if gate.get("allowed") else gate.get("reason"),
        "task_id": command.get("task_id"),
        "run_id": command.get("run_id"),
        "actor": command.get("actor"),
        "gate_allowed": bool(gate.get("allowed")),
        "gate_reason": gate.get("reason") or gate.get("status"),
        "gate_status": gate.get("status"),
        "evidence_refs": command.get("evidence_refs", []),
        "execution_effect": effect,
    }
    redis_mirror = publish_monitor_intervention_redis(event)
    event["redis_mirror"] = redis_mirror
    enqueue_monitor_intervention_audit(event, root=root)
    if not gate.get("allowed"):
        return {
            "status": "blocked",
            "kind": "monitor_intervention",
            "schema": command["schema"],
            "command": command["command"],
            "action": command["action"],
            "intervention_id": command["intervention_id"],
            "gate": gate,
            "audit_async": True,
            "redis_mirror": redis_mirror,
            "execution_effect": effect,
        }
    return {
        "status": "recorded",
        "kind": "monitor_intervention",
        "schema": command["schema"],
        "command": command["command"],
        "action": command["action"],
        "intervention_id": command["intervention_id"],
        "gate": gate,
        "audit_async": True,
        "command_envelope": command,
        "audit_path": str(monitor_intervention_audit_path(root)),
        "redis_mirror": redis_mirror,
        "execution_effect": effect,
    }


def parse_cli_list(values: list[str] | None) -> list[str]:
    return [str(item).strip() for item in (values or []) if str(item).strip()]


def monitor_intervention_cli_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": args.action,
        "reason": args.reason,
        "operator_scopes": [PHONE_ADMIN_SCOPE],
    }
    optional_fields = (
        "task_id",
        "run_id",
        "actor",
        "flow_id",
        "flow_expected_revision",
        "flow_expected_last_seq",
        "flow_sequence",
        "evidence_id",
        "idempotency_key",
    )
    for field in optional_fields:
        value = getattr(args, field, None)
        if value not in (None, ""):
            payload[field] = value
    evidence_refs = parse_cli_list(getattr(args, "evidence_ref", []))
    if evidence_refs:
        payload["evidence_refs"] = evidence_refs
    return payload


def monitor_intervention_cli(args: argparse.Namespace) -> int:
    if args.examples:
        print(json.dumps(monitor_intervention_examples(), ensure_ascii=False, indent=2))
        return 0
    if args.arm_duration:
        phone_control_arm(
            {
                "group": "runtime",
                "duration": args.arm_duration,
                "operator_scopes": [PHONE_ADMIN_SCOPE],
                "source": "monitor-intervention-cli",
            }
        )
    result = monitor_intervention(monitor_intervention_cli_payload(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"recorded", "ok"} else 1


def worker_transport_cli_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload = {
        "preset": getattr(args, "preset", ""),
        "operator_scopes": [PHONE_ADMIN_SCOPE],
    }
    for key in ["model", "base_url", "api_key_env", "reason"]:
        value = getattr(args, key, "")
        if value:
            payload[key] = value
    timeout_seconds = getattr(args, "timeout_seconds", None)
    if timeout_seconds is not None:
        payload["timeout_seconds"] = timeout_seconds
    if getattr(args, "execute", False):
        payload["execute"] = True
    if getattr(args, "require_probe_pass", False):
        payload["require_probe_pass"] = True
    return payload


def worker_transport_check_cli(args: argparse.Namespace) -> int:
    if args.arm_duration:
        phone_control_arm(
            {
                "group": "runtime",
                "duration": args.arm_duration,
                "operator_scopes": [PHONE_ADMIN_SCOPE],
                "source": "worker-transport-check-cli",
            }
        )
    result = worker_transport_check(worker_transport_cli_payload(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"ready", "pass"} else 1


def worker_transport_policy_cli(args: argparse.Namespace) -> int:
    if args.arm_duration:
        phone_control_arm(
            {
                "group": "runtime",
                "duration": args.arm_duration,
                "operator_scopes": [PHONE_ADMIN_SCOPE],
                "source": "worker-transport-policy-cli",
            }
        )
    result = update_worker_transport_policy(worker_transport_cli_payload(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "applied" else 1


def worker_transport_config_cli(args: argparse.Namespace) -> int:
    if args.arm_duration:
        phone_control_arm(
            {
                "group": "runtime",
                "duration": args.arm_duration,
                "operator_scopes": [PHONE_ADMIN_SCOPE],
                "source": "worker-transport-config-cli",
            }
        )
    payload = worker_transport_cli_payload(args)
    result = update_llm_worker_config(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "applied" else 1


def runtime_run_one_with_transport_cli(args: argparse.Namespace) -> int:
    if args.arm_duration:
        phone_control_arm(
            {
                "group": "runtime",
                "duration": args.arm_duration,
                "operator_scopes": [PHONE_ADMIN_SCOPE],
                "source": "runtime-run-one-with-transport-cli",
            }
        )
    payload = {
        "operator_scopes": [PHONE_ADMIN_SCOPE],
        "auto_next": bool(args.auto_next),
        "transport": worker_transport_cli_payload(args),
    }
    result = runtime_run_one_with_transport(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "run-complete" else 1


def communication_repair_suggestion_review(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    require_phone_admin(payload)
    suggestion_id = str(payload.get("suggestion_id") or "").strip()
    action = str(payload.get("action") or payload.get("review_action") or "").strip().lower()
    if not suggestion_id:
        raise ValueError("suggestion_id is required")
    if action not in {"approve", "ignore", "resolve"}:
        raise ValueError("action must be approve, ignore, or resolve")
    path = root / COMMUNICATION_REPAIR_SUGGESTIONS_REL_PATH
    current = read_json(path) if path.exists() else {
        "status": "ok",
        "kind": "communication_repair_suggestions",
        "mode": "observe_only",
        "pending": [],
    }
    pending = current.get("pending") if isinstance(current.get("pending"), list) else []
    approved = current.get("approved") if isinstance(current.get("approved"), list) else []
    closed = current.get("closed") if isinstance(current.get("closed"), list) else []
    target = next((item for item in pending if str(item.get("suggestion_id") or "") == suggestion_id), None)
    if target is None:
        return {
            "status": "not_found",
            "kind": "communication_repair_suggestion_review",
            "suggestion_id": suggestion_id,
            "action": action,
            "pending_count": len(pending),
            "audit_async": True,
        }

    reviewed_at = utc_now()
    reviewed = {
        **target,
        "status": "approved" if action == "approve" else action,
        "review_action": action,
        "reviewed_at": reviewed_at,
        "reviewer": str(payload.get("reviewer") or "mobile-operator"),
        "review_reason": str(payload.get("reason") or ""),
        "auto_execute": False,
    }
    pending = [item for item in pending if str(item.get("suggestion_id") or "") != suggestion_id]
    if action == "approve":
        approved = [reviewed, *approved][:50]
    else:
        closed = [reviewed, *closed][:50]
    updated = {
        **current,
        "status": "ok",
        "kind": "communication_repair_suggestions",
        "updated_at": reviewed_at,
        "pending_count": len(pending),
        "pending": pending,
        "approved_count": len(approved),
        "approved": approved,
        "closed_count": len(closed),
        "closed": closed,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit_event = {
        "kind": "communication_repair_suggestion_review",
        "ts": reviewed_at,
        "suggestion_id": suggestion_id,
        "action": action,
        "reviewer": reviewed["reviewer"],
        "review_reason": reviewed["review_reason"],
        "route": reviewed.get("route") or {},
        "auto_execute": False,
        "state_path": str(path),
    }
    enqueue_communication_suggestion_audit(audit_event, root=root)
    return {
        "status": "ok",
        "kind": "communication_repair_suggestion_review",
        "suggestion_id": suggestion_id,
        "action": action,
        "reviewed": reviewed,
        "pending_count": len(pending),
        "approved_count": len(approved),
        "closed_count": len(closed),
        "audit_async": True,
    }


def _transcript_item(
    *,
    source: str,
    phase: str,
    action: str,
    reason: str = "",
    status: str = "",
    node_id: str = "",
    flow_id: str = "",
    evidence_path: str = "",
    event_id: str = "",
    ts: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "phase": phase,
        "action": action,
        "reason": reason,
        "status": status,
        "node_id": node_id,
        "flow_id": flow_id,
        "evidence_path": evidence_path,
        "event_id": event_id,
        "ts": ts,
        "details": details or {},
    }


def transcript_phase_for_evidence(kind: str) -> str:
    if kind.startswith("probe"):
        return "probe"
    if kind.startswith("tmux") or kind.startswith("heartbeat") or kind.startswith("bootstrap"):
        return "reconnecting"
    if kind.startswith("recovery-cycle"):
        return "observe"
    return "evidence"


def transcript_intervention_decision(
    items: list[dict[str, Any]],
    tasks_stream: dict[str, Any],
    followup: dict[str, Any],
    loop: dict[str, Any],
) -> dict[str, Any]:
    allowed_actions = {"observe", "watch", "repair", "intervene", "quarantine"}
    severity = {"observe": 1, "watch": 2, "repair": 3, "intervene": 4, "quarantine": 5}
    reason = "healthy"
    evidence_refs: list[str] = []
    action = "observe"

    followup_action = str(followup.get("action") or "")
    followup_reason = str(followup.get("reason") or "")
    stream_action = str(tasks_stream.get("stream_action") or "")
    stream_reason = str(tasks_stream.get("stream_action_reason") or "")
    loop_risk_count = int(loop.get("risk_count") or 0) if isinstance(loop, dict) else 0

    action_map = {
        "continue": "observe",
        "observe": "observe",
        "watch": "watch",
        "reconnect": "repair",
        "repair": "repair",
        "intervene": "intervene",
        "quarantine": "quarantine",
        "terminate": "quarantine",
    }
    reason_map = {
        "lag_warn": "stream_lag_warn",
        "pending_stuck": "stream_pending_stuck",
        "pending_skew": "stream_pending_skew",
        "lag_critical": "stream_lag_critical",
        "consumer_group_missing": "stream_consumer_group_missing",
        "invalid_lag": "stream_invalid_lag",
        "xpending_failed": "stream_probe_failed",
        "redis_unavailable": "stream_redis_unavailable",
    }
    quarantine_markers = ("unsafe_terminal", "sequence_conflict", "terminal_conflict", "quarantine")

    def elevate(candidate: str, candidate_reason: str) -> None:
        nonlocal action, reason
        if candidate not in allowed_actions:
            return
        if severity[candidate] >= severity[action]:
            action = candidate
            reason = candidate_reason

    for item in items:
        item_reason = str(item.get("reason") or "")
        item_action = str(item.get("action") or "")
        if any(marker in item_reason for marker in quarantine_markers):
            elevate("quarantine", "unsafe_terminal_or_sequence_conflict")
            if item.get("evidence_path"):
                evidence_refs.append(str(item["evidence_path"]))
            elif item.get("event_id"):
                evidence_refs.append(str(item["event_id"]))

    if followup_action:
        elevate(action_map.get(followup_action, "observe"), followup_reason or "followup")
        evidence = followup.get("evidence") if isinstance(followup.get("evidence"), dict) else {}
        for node_ref in evidence.get("nodes", []):
            if isinstance(node_ref, dict):
                node_id = str(node_ref.get("node_id") or "")
                if node_id:
                    evidence_refs.append(f"node:{node_id}")
        stream_ref = evidence.get("tasks_stream") if isinstance(evidence, dict) else {}
        if isinstance(stream_ref, dict):
            if stream_ref.get("reason"):
                evidence_refs.append(f"tasks_stream:{stream_ref.get('reason')}")

    if stream_action:
        mapped_stream = action_map.get(stream_action, "observe")
        mapped_reason = reason_map.get(stream_reason, "healthy" if stream_reason in {"", "none"} else stream_reason)
        elevate(mapped_stream, mapped_reason)
        if stream_reason:
            evidence_refs.append(f"tasks_stream:{stream_reason}")
        if stream_action == "watch" and stream_reason in {"lag_warn", "consumer_group_missing", "invalid_lag"}:
            elevate("watch", reason_map.get(stream_reason, "stream_watch"))
        if stream_action == "intervene" and stream_reason in {"pending_stuck", "pending_skew", "lag_critical"}:
            elevate("repair", reason_map.get(stream_reason, "stream_repair_needed"))

    if (
        followup_action == "intervene"
        and isinstance(followup_reason, str)
        and followup_reason.startswith("tasks_stream:")
        and action == "intervene"
    ):
        stream_tail = followup_reason.split(":", 1)[1] if ":" in followup_reason else ""
        action = "repair"
        reason = reason_map.get(stream_tail, "stream_repair_needed")

    if loop_risk_count > 0 and action == "observe":
        elevate("watch", "recovery_risk_present")

    dedup_refs: list[str] = []
    seen = set()
    for ref in evidence_refs:
        normalized = str(ref).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        dedup_refs.append(normalized)

    return {
        "action": action if action in allowed_actions else "observe",
        "reason": reason or "healthy",
        "evidence_refs": dedup_refs,
    }


def _append_transcript_recovery_hint_item(
    items: list[dict[str, Any]],
    *,
    hint: dict[str, Any],
    source: str,
    phase: str,
    node_id: str = "",
    ts: str = "",
) -> None:
    if not isinstance(hint, dict):
        return
    action = str(hint.get("action") or "").strip()
    reason = str(hint.get("reason") or "").strip()
    if not action and not reason:
        return
    items.append(
        _transcript_item(
            source=source,
            phase=phase,
            action=action or "observe",
            reason=reason or "recovery_hint",
            node_id=node_id,
            ts=ts or utc_now(),
            details={"recovery_hint": hint},
        )
    )


def _transcript_recovery_hint_evidence_refs(items: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for item in items:
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        hint = details.get("recovery_hint") if isinstance(details, dict) else {}
        if not isinstance(hint, dict):
            continue
        raw_refs = hint.get("evidence_refs")
        if not isinstance(raw_refs, list):
            continue
        for ref in raw_refs:
            normalized = str(ref).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            refs.append(normalized)
    return refs


def recovery_transcript(
    node_id: str | None = None,
    *,
    root: Path = ROOT,
    limit: int = 20,
) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 100))
    evidence = list_node_evidence(node_id, root=root, limit=safe_limit)
    items: list[dict[str, Any]] = []
    for item in reversed(evidence.get("items", [])):
        kind = str(item.get("kind") or "")
        items.append(
            _transcript_item(
                source="node_evidence",
                phase=transcript_phase_for_evidence(kind),
                action=str(item.get("action") or item.get("status") or "observe"),
                reason=str(item.get("reason") or kind or "node_evidence"),
                status=str(item.get("status") or ""),
                node_id=str(item.get("node_id") or ""),
                evidence_path=str(item.get("path") or ""),
                ts=str(item.get("mtime") or ""),
                details={
                    "kind": kind,
                    "target": item.get("target"),
                    "session": item.get("session"),
                    "return_code": item.get("return_code"),
                    "timed_out": item.get("timed_out"),
                },
            )
        )

    gateway = latest_gateway_reconnect_decision_event()
    if gateway.get("status") != "missing":
        items.append(
            _transcript_item(
                source="gateway_reconnect_decision",
                phase=str(gateway.get("phase") or "stream"),
                action=str(gateway.get("action") or gateway.get("status") or "observe"),
                reason=str(gateway.get("error_class") or gateway.get("reason") or "gateway_reconnect_decision"),
                status=str(gateway.get("status") or ""),
                node_id=str(gateway.get("node_id") or ""),
                flow_id=str(gateway.get("flow_id") or ""),
                event_id=str(gateway.get("event_id") or ""),
                ts=str(gateway.get("ts") or ""),
                details={
                    "origin": gateway.get("origin"),
                    "attempt": gateway.get("attempt"),
                    "delay_ms": gateway.get("delay_ms"),
                    "policy_budget_remaining": gateway.get("policy_budget_remaining"),
                    "flow_revision": gateway.get("flow_revision"),
                    "reset_on_success": gateway.get("reset_on_success"),
                },
            )
        )

    status = node_status(root)
    nodes = status.get("nodes") if isinstance(status.get("nodes"), list) else []
    tasks_stream = status.get("tasks_stream") if isinstance(status.get("tasks_stream"), dict) else {}
    if tasks_stream:
        items.append(
            _transcript_item(
                source="redis_tasks_stream",
                phase="stream-health",
                action=str(tasks_stream.get("stream_action") or "continue"),
                reason=str(tasks_stream.get("stream_action_reason") or tasks_stream.get("reason") or "none"),
                status=str(tasks_stream.get("status") or ""),
                ts=str(tasks_stream.get("sampled_at") or ""),
                details={
                    "stream": tasks_stream.get("stream"),
                    "group": tasks_stream.get("group"),
                    "lag": tasks_stream.get("lag"),
                    "pending": tasks_stream.get("pending"),
                    "thresholds_version": tasks_stream.get("thresholds_version"),
                    "consumer_probe_status": tasks_stream.get("consumer_probe_status"),
                    "consumer_probe_reason": tasks_stream.get("consumer_probe_reason"),
                },
            )
        )

    followup = status.get("communication_followup") if isinstance(status.get("communication_followup"), dict) else {}
    if followup:
        items.append(
            _transcript_item(
                source="communication_followup",
                phase="resume" if followup.get("action") in {"continue", "watch"} else "reconnecting",
                action=str(followup.get("action") or "continue"),
                reason=str(followup.get("reason") or ""),
                status=str(followup.get("status") or ""),
                ts=utc_now(),
                details={"evidence": followup.get("evidence")},
            )
        )
    if str(tasks_stream.get("stream_action_reason") or "") == "redis_unavailable":
        redis_hint = node_command_recovery_hint(
            node_id=node_id or "",
            result_status="degraded",
            result_error_code="redis_unavailable",
            root=root,
        )
        _append_transcript_recovery_hint_item(
            items,
            hint=redis_hint,
            source="node_command_recovery_hint",
            phase="stream-health",
            node_id=node_id or "",
            ts=str(tasks_stream.get("sampled_at") or ""),
        )
    candidate_node_ids: list[str] = []
    if node_id:
        candidate_node_ids.append(str(node_id))
    followup_evidence = followup.get("evidence") if isinstance(followup, dict) else {}
    for ref in followup_evidence.get("nodes", []) if isinstance(followup_evidence, dict) else []:
        if not isinstance(ref, dict):
            continue
        hinted_node_id = str(ref.get("node_id") or "").strip()
        if hinted_node_id and hinted_node_id not in candidate_node_ids:
            candidate_node_ids.append(hinted_node_id)
    for node in nodes:
        current_node_id = str(node.get("node_id") or "").strip()
        if not current_node_id:
            continue
        if candidate_node_ids and current_node_id not in candidate_node_ids:
            continue
        if not candidate_node_ids:
            connection_state = str(node.get("connection_state") or "")
            if connection_state not in {"stale", "degraded", "offline", "unknown"}:
                continue
        bootstrap_execution = node.get("bootstrap_execution")
        if isinstance(bootstrap_execution, dict) and bootstrap_execution.get("evidence_path"):
            bootstrap_result = str(bootstrap_execution.get("result") or "")
            if bootstrap_result == "ok":
                recovery_action = "observe"
                recovery_next_endpoint = "/api/nodes/recovery-transcript"
                recovery_next_method = "GET"
                recovery_next_requires_arm = False
            else:
                recovery_action = str(bootstrap_execution.get("action") or "repair")
                recovery_next_endpoint = "/api/nodes/bootstrap-execute"
                recovery_next_method = "POST"
                recovery_next_requires_arm = True
            recovery_hint = {
                "action": recovery_action,
                "reason": str(node.get("status_reason") or f"bootstrap_{bootstrap_result or 'unknown'}"),
                "evidence_refs": [str(bootstrap_execution.get("evidence_path") or "")],
                "next_endpoint": recovery_next_endpoint,
                "next_method": recovery_next_method,
                "next_requires_arm": recovery_next_requires_arm,
            }
            items.append(
                _transcript_item(
                    source="node_bootstrap_execution",
                    phase="reconnecting",
                    action=str(bootstrap_execution.get("action") or "continue"),
                    reason="bootstrap_execution",
                    status=str(bootstrap_execution.get("result") or ""),
                    node_id=current_node_id,
                    evidence_path=str(bootstrap_execution.get("evidence_path") or ""),
                    ts=str(node.get("updated_at") or ""),
                    details={
                        "bootstrap_execution": bootstrap_execution,
                        "status_reason": str(node.get("status_reason") or ""),
                        "updated_at": str(node.get("updated_at") or ""),
                        "status": str(node.get("status") or ""),
                        "recovery_hint": recovery_hint,
                    },
                )
            )
        node_hint = node_command_recovery_hint(
            node_id=current_node_id,
            result_status="noop",
            result_error_code="no_result",
            root=root,
        )
        _append_transcript_recovery_hint_item(
            items,
            hint=node_hint,
            source="node_command_recovery_hint",
            phase="reconnecting",
            node_id=current_node_id,
            ts=utc_now(),
        )

    loop = recovery_loop_latest(root=root)
    if loop.get("status") == "ok":
        items.append(
            _transcript_item(
                source="recovery_loop_latest",
                phase="observe",
                action="observe" if int(loop.get("risk_count") or 0) == 0 else "repair",
                reason=str(loop.get("cycle_status") or loop.get("raw_status") or ""),
                status=str(loop.get("cycle_status") or loop.get("status") or ""),
                evidence_path=str(loop.get("path") or ""),
                ts=str(loop.get("checked_at") or loop.get("mtime") or ""),
                details={
                    "risk_count": loop.get("risk_count"),
                    "step_count": loop.get("step_count"),
                    "execute": loop.get("execute"),
                },
            )
        )

    def sort_key(item: dict[str, Any]) -> str:
        return str(item.get("ts") or "")

    items.sort(key=sort_key)
    actions = [str(item.get("action") or "") for item in items]
    current_action = str(followup.get("action") or "")
    if not current_action:
        current_action = "repair" if int(loop.get("risk_count") or 0) > 0 else "continue"
    current_reason = str(followup.get("reason") or tasks_stream.get("stream_action_reason") or loop.get("cycle_status") or "")
    active_attention = current_action in {"repair", "reconnect", "intervene", "quarantine", "terminate"}
    active_watch = current_action == "watch"
    bouncing = active_attention and actions.count("repair") + actions.count("reconnect") + actions.count("intervene") >= 2
    status_value = "needs_attention" if active_attention else "degraded" if active_watch else "ok"
    conclusion = "bouncing" if bouncing else "repairing" if active_attention else "watching" if active_watch else "converging"
    intervention = _normalize_intervention_decision_payload(followup.get("intervention_decision"))
    if not intervention:
        intervention = transcript_intervention_decision(items, tasks_stream, followup, loop)
    hint_refs = _transcript_recovery_hint_evidence_refs(items)
    if hint_refs:
        merged_refs: list[str] = []
        seen_refs: set[str] = set()
        for ref in list(intervention.get("evidence_refs") or []) + hint_refs:
            normalized = str(ref).strip()
            if not normalized or normalized in seen_refs:
                continue
            seen_refs.add(normalized)
            merged_refs.append(normalized)
        intervention["evidence_refs"] = merged_refs
    return {
        "status": status_value,
        "kind": "node_recovery_transcript",
        "schema": "a9.node_recovery_transcript.v1",
        "node_id": node_id or "",
        "generated_at": utc_now(),
        "limit": safe_limit,
        "item_count": len(items),
        "conclusion": conclusion,
        "current_action": current_action,
        "current_reason": current_reason,
        "intervention_decision": intervention,
        "items": items[-safe_limit:],
        "sources": {
            "node_evidence_count": evidence.get("count", 0),
            "gateway_status": gateway.get("status"),
            "tasks_stream_status": tasks_stream.get("status"),
            "recovery_loop_status": loop.get("status"),
        },
    }


def controller_discovery() -> dict[str, Any]:
    return {
        "service": "a9-controller",
        "version": 1,
        "time": utc_now(),
        "endpoints": {
            "health": "/api/health",
            "status": "/api/status",
            "monitor_control": "/api/monitor/control",
            "monitor_status": "/api/monitor/status",
            "monitor_intervention": "/api/monitor/intervention",
            "monitor_intervention_audit": "/api/monitor/interventions/audit",
            "monitor_intervention_events": "/api/monitor/interventions/events",
            "monitor_intervention_examples": "/api/monitor/intervention/examples",
            "worker_transport_presets": "/api/worker/transport-presets",
            "worker_transport_check": "/api/worker/transport-check",
            "worker_transport_config": "/api/worker/transport-config",
            "worker_transport_policy_update": "/api/worker/transport-policy",
            "communication_status": "/api/communication/status",
            "communication_data_contract_report": "/api/communication/data-contract-report",
            "communication_action_plan": "/api/communication/action-plan",
            "communication_model_closure_validate": "/api/communication/model-closure-validate",
            "communication_repair_one": "/api/communication/repair-one",
            "communication_repair_suggestions": "/api/communication/repair-suggestions",
            "communication_repair_suggestion_review": "/api/communication/repair-suggestions/review",
            "services_control_audit": "/api/services/control-audit",
            "register_node": "/api/nodes/register",
            "heartbeat_node": "/api/nodes/heartbeat",
            "phone_control_status": "/api/phone-control/status",
            "phone_control_arm": "/api/phone-control/arm",
            "phone_control_disarm": "/api/phone-control/disarm",
            "submit": "/api/submit",
            "runtime_run_one": "/api/runtime/run-one",
            "runtime_run_one_with_transport": "/api/runtime/run-one-with-transport",
            "runtime_session_refresh_trial": "/api/runtime/session-refresh-trial",
            "runtime_session_lane_latest": "/api/runtime/session-lane-latest",
            "mempalace_status": "/api/memory/mempalace/status",
            "mempalace_search": "/api/memory/mempalace/search",
            "mempalace_wakeup": "/api/memory/mempalace/wakeup",
            "runtime_plan_decision_approve": "/api/runtime/plan-decision-approve",
            "runtime_plan_debate_next": "/api/runtime/plan-debate-next",
            "runtime_plan_backlog_next": "/api/runtime/plan-backlog-next",
            "services_start": "/api/services/start",
            "eval_override": "/api/eval/override",
            "gateway_transport_contract": "/api/gateway/transport-contract",
            "gateway_reconnect_decision": "/api/gateway/reconnect-decision",
            "gateway_reconnect_diagnostic": "/api/gateway/reconnect-diagnostic",
            "gateway_reconnect_governance": "/api/gateway/reconnect-governance",
            "gateway_health_refresh": "/api/gateway/health-refresh",
            "node_recovery_loop_latest": "/api/nodes/recovery-loop/latest",
            "node_recovery_transcript": "/api/nodes/recovery-transcript",
            "node_command_submit": "/api/nodes/command-submit",
            "node_command": "/api/nodes/command",
            "node_command_result": "/api/node-command-results/{result_event_id}",
            "node_command_result_by_command": "/api/node-command-results/by-command/{command_id}",
            "node_command_result_watch": "/api/node-command-results/watch/{command_id}",
            "services_restart": "/api/services/restart",
            "events": "/api/events",
        },
        "runtime": {
            "ssh_bootstrap": True,
            "redis_streams_target": True,
            "gateway_transport_contract": True,
            "gateway_reconnect_governance": True,
            "node_command_recovery_hint_contract": True,
            "monitor_control_contract": True,
            "monitor_status_contract": True,
            "monitor_intervention_contract": True,
            "monitor_intervention_examples": True,
            "monitor_intervention_redis_stream": MONITOR_INTERVENTIONS_STREAM_KEY,
            "worker_transport_policy_update": True,
            "worker_transport_presets": True,
            "worker_transport_check": True,
            "worker_transport_config": True,
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
                record = enrich_node_heartbeat_repair_evidence(record, root=root)
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
    tasks_stream = status.get("tasks_stream") if isinstance(status.get("tasks_stream"), dict) else {}
    stream_reason = str(tasks_stream.get("stream_action_reason") or tasks_stream.get("reason") or "").strip()
    stream_action = str(tasks_stream.get("stream_action") or "").strip()
    stream_recommended_action = str(tasks_stream.get("recommended_action") or "").strip()

    if stream_reason in {"", "none", "healthy"}:
        recovery_next_action = {"action": "continue", "reason": "none"}
    elif stream_reason == "pending_stuck" and stream_recommended_action == "recover_stale_commands":
        recovery_next_action = {"action": "repair", "reason": "recover_stale_commands"}
    elif stream_reason in {"lag_critical", "pending_skew"}:
        recovery_next_action = {"action": "intervene", "reason": stream_reason}
    elif stream_reason in {"lag_warn", "consumer_group_missing", "invalid_lag", "xpending_failed", "invalid_pending"}:
        recovery_next_action = {"action": "watch", "reason": stream_reason}
    elif stream_action == "intervene":
        recovery_next_action = {"action": "intervene", "reason": stream_reason or "unknown"}
    elif stream_action == "watch":
        recovery_next_action = {"action": "watch", "reason": stream_reason or "unknown"}
    elif stream_action in {"reconnect", "repair"}:
        recovery_next_action = {"action": "repair", "reason": stream_reason or "unknown"}
    else:
        recovery_next_action = {"action": "continue", "reason": stream_reason or "none"}

    stream_pending = tasks_stream.get("pending")
    stream_evidence = {
        "lag": tasks_stream.get("lag"),
        "pending_total": stream_pending,
        "pending": stream_pending,
        "stream_action": tasks_stream.get("stream_action"),
        "stream_action_reason": tasks_stream.get("stream_action_reason"),
        "recommended_action": tasks_stream.get("recommended_action"),
    }
    top_consumers = tasks_stream.get("top_consumers")
    if isinstance(top_consumers, list):
        stream_evidence["top_consumers"] = top_consumers

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
        "redis": status.get("redis"),
        "tasks_stream": status.get("tasks_stream"),
        "stream_evidence": stream_evidence,
        "recovery_next_action": recovery_next_action,
        "communication_followup": status.get("communication_followup"),
    }


def communication_status(root: Path = ROOT) -> dict[str, Any]:
    tailscale = tailscale_status()
    services = service_observation_status(root)
    nodes = node_connection_summary(root)
    tasks_stream = nodes.get("tasks_stream") if isinstance(nodes.get("tasks_stream"), dict) else {}
    recovery_next_action = nodes.get("recovery_next_action") if isinstance(nodes.get("recovery_next_action"), dict) else {}
    recovery = recovery_loop_latest(root=root)

    actions = {
        "continue": 1,
        "observe": 1,
        "watch": 2,
        "start_missing_services": 3,
        "reconnect": 3,
        "login": 3,
        "install": 3,
        "repair": 4,
        "intervene": 4,
        "await_bootstrap_takeover": 5,
        "quarantine": 5,
    }
    status_by_action = {
        "continue": "ok",
        "observe": "ok",
        "watch": "degraded",
        "start_missing_services": "degraded",
        "reconnect": "degraded",
        "login": "needs_attention",
        "install": "needs_attention",
        "repair": "needs_attention",
        "intervene": "needs_attention",
        "await_bootstrap_takeover": "needs_attention",
        "quarantine": "needs_attention",
    }

    candidates: list[dict[str, Any]] = []
    tail_status = str(tailscale.get("status") or "")
    tail_action = "continue"
    tail_reason = tail_status or "unknown"
    if tail_status == "missing":
        tail_action = "install"
    elif tail_status == "needs_login":
        tail_action = "login"
    elif tail_status in {"timeout", "unavailable", "stopped"}:
        tail_action = "reconnect"
    elif tail_status != "ok":
        tail_action = "watch"
    candidates.append({"source": "tailscale", "action": tail_action, "reason": tail_reason})

    service_observed = services.get("observed") if isinstance(services.get("observed"), dict) else {}
    service_action = str(service_observed.get("next_action") or "observe")
    candidates.append(
        {
            "source": "services",
            "action": service_action,
            "reason": f"missing:{service_observed.get('missing_count', 0)}",
            "missing_services": service_observed.get("missing_services") or [],
        }
    )

    node_followup = nodes.get("communication_followup") if isinstance(nodes.get("communication_followup"), dict) else {}
    candidates.append(
        {
            "source": "nodes",
            "action": str(node_followup.get("action") or "continue"),
            "reason": str(node_followup.get("reason") or "healthy"),
            "risk_count": nodes.get("risk_count", 0),
        }
    )

    candidates.append(
        {
            "source": "tasks_stream",
            "action": str(recovery_next_action.get("action") or tasks_stream.get("stream_action") or "continue"),
            "reason": str(recovery_next_action.get("reason") or tasks_stream.get("stream_action_reason") or tasks_stream.get("reason") or "none"),
            "lag": tasks_stream.get("lag"),
            "pending": tasks_stream.get("pending"),
            "stream_action": tasks_stream.get("stream_action"),
            "stream_action_reason": tasks_stream.get("stream_action_reason"),
            "recommended_action": tasks_stream.get("recommended_action"),
            "status": tasks_stream.get("status"),
        }
    )
    recovery_status = str(recovery.get("status") or recovery.get("cycle_status") or "")
    recovery_action = "continue"
    if recovery_status in {"needs_attention", "failed", "error"}:
        recovery_action = "intervene"
    elif recovery_status in {"degraded", "stale"}:
        recovery_action = "watch"
    candidates.append(
        {
            "source": "recovery_loop",
            "action": recovery_action,
            "reason": recovery_status or "unknown",
            "risk_count": recovery.get("risk_count"),
        }
    )
    reconnect_event = latest_gateway_reconnect_decision_event()
    reconnect_action = str(reconnect_event.get("action") or "")
    gateway_action = "await_bootstrap_takeover" if reconnect_action in {"terminate", "quarantine"} else "continue"
    candidates.append(
        {
            "source": "gateway_reconnect",
            "action": gateway_action,
            "reason": str(reconnect_event.get("error_class") or reconnect_event.get("reason") or reconnect_action or "unknown"),
            "event_id": reconnect_event.get("event_id", ""),
            "node_id": reconnect_event.get("node_id", ""),
            "reconnect_action": reconnect_action,
            "reconnect_event": reconnect_event,
        }
    )

    def candidate_key(item: dict[str, Any]) -> tuple[int, int]:
        action = str(item.get("action") or "watch")
        priority = actions.get(action, actions["watch"])
        source = str(item.get("source") or "")
        action_priority_tiebreak = 0
        if priority == 4 and source == "recovery_loop" and action in {"repair", "intervene"}:
            action_priority_tiebreak = 2
        elif priority == 4 and source == "tasks_stream" and action in {"repair", "intervene"}:
            action_priority_tiebreak = 1
        return (priority, action_priority_tiebreak)

    best = max(candidates, key=candidate_key)
    action = str(best.get("action") or "watch")
    return {
        "status": status_by_action.get(action, "degraded"),
        "generated_at": utc_now(),
        "action": action,
        "reason": f"{best.get('source')}:{best.get('reason')}",
        "priority_source": best.get("source"),
        "candidates": candidates,
        "layers": {
            "tailscale": tailscale,
            "services": services,
            "nodes": nodes,
            "tasks_stream": tasks_stream,
            "recovery_loop": recovery,
            "gateway_reconnect": reconnect_event,
        },
    }


def communication_action_plan(status: dict[str, Any] | None = None, *, root: Path = ROOT) -> dict[str, Any]:
    status = status or communication_status(root)
    action = str(status.get("action") or "continue")
    source = str(status.get("priority_source") or "")
    reason = str(status.get("reason") or "")
    base = {
        "status": "ok",
        "kind": "communication_action_plan",
        "generated_at": utc_now(),
        "communication": {
            "status": status.get("status"),
            "action": action,
            "reason": reason,
            "priority_source": source,
        },
    }
    if action in {"continue", "observe"}:
        return {
            **base,
            "plan_status": "noop",
            "route": {"method": None, "endpoint": None, "command": None, "requires_arm": False, "arm_group": None},
            "reason": "communication_healthy",
            "steps": ["continue_observation"],
            "executable": False,
        }
    if source == "services" and action == "start_missing_services":
        missing = []
        layers = status.get("layers") if isinstance(status.get("layers"), dict) else {}
        services = layers.get("services") if isinstance(layers.get("services"), dict) else {}
        observed = services.get("observed") if isinstance(services.get("observed"), dict) else {}
        if isinstance(observed.get("missing_services"), list):
            missing = [str(item) for item in observed.get("missing_services", [])]
        return {
            **base,
            "plan_status": "ready",
            "route": {"method": "POST", "endpoint": "/api/services/start", "command": "services.start", "requires_arm": True, "arm_group": "runtime"},
            "payload": {"services": missing},
            "reason": "start_missing_services",
            "steps": ["arm_runtime", "post_services_start", "refresh_communication_status"],
            "executable": True,
        }
    if source in {"nodes", "recovery_loop"} and action in {"reconnect", "intervene", "quarantine", "watch"}:
        return {
            **base,
            "plan_status": "ready",
            "route": {
                "method": "POST",
                "endpoint": "/api/nodes/recovery-cycle",
                "command": "nodes.recovery.cycle",
                "requires_arm": True,
                "arm_group": "remote",
            },
            "payload": {"execute": True, "max_actions": 1},
            "reason": "run_node_recovery_cycle",
            "steps": ["arm_remote", "post_nodes_recovery_cycle", "refresh_communication_status"],
            "executable": True,
        }
    if source == "gateway_reconnect" and action == "await_bootstrap_takeover":
        reconnect_event = {}
        layers = status.get("layers") if isinstance(status.get("layers"), dict) else {}
        if isinstance(layers.get("gateway_reconnect"), dict):
            reconnect_event = layers["gateway_reconnect"]
        return {
            **base,
            "plan_status": "ready",
            "route": {
                "method": "POST",
                "endpoint": "/api/nodes/bootstrap-takeover-admission",
                "command": "nodes.bootstrap.takeover.admit",
                "requires_arm": False,
                "arm_group": None,
            },
            "payload": {"reconnect_event": reconnect_event},
            "reason": "admit_bootstrap_takeover_wait_state",
            "steps": ["post_bootstrap_takeover_admission", "operator_review_before_bootstrap_execute"],
            "executable": True,
        }
    if source == "tasks_stream" and action in {"watch", "intervene", "repair"}:
        stream_reason = str(
            status.get("layers", {}).get("tasks_stream", {}).get("stream_action_reason")
            or status.get("communication_followup", {}).get("intervention_decision", {}).get("reason")
            or ""
        )
        status_reason = str(status.get("reason") or "")
        action_reason = status_reason.removeprefix("tasks_stream:") if status_reason.startswith("tasks_stream:") else stream_reason
        if stream_reason == "pending_stuck":
            return {
                **base,
                "plan_status": "ready",
                "route": {
                    "method": "POST",
                    "endpoint": "/api/communication/repair-one",
                    "command": "nodes.recover.stale_commands",
                    "requires_arm": True,
                    "arm_group": "remote",
                },
                "payload": {"action": "recover_stale_commands", "stream": TASKS_STREAM_KEY, "group": TASKS_STREAM_GROUP},
                "reason": "recover_stream_stale_commands",
                "steps": ["arm_remote", "post_communication_repair_one", "refresh_communication_status"],
                "executable": True,
            }
        if action == "repair" or action_reason == "recover_stale_commands":
            return {
                **base,
                "plan_status": "ready",
                "route": {
                    "method": "POST",
                    "endpoint": "/api/communication/repair-one",
                    "command": "nodes.recover.stale_commands",
                    "requires_arm": True,
                    "arm_group": "remote",
                },
                "payload": {"action": "recover_stale_commands", "stream": TASKS_STREAM_KEY, "group": TASKS_STREAM_GROUP},
                "reason": "recover_stream_stale_commands",
                "steps": ["arm_remote", "post_communication_repair_one", "refresh_communication_status"],
                "executable": True,
            }
        return {
            **base,
            "plan_status": "observe_only",
            "route": {"method": "GET", "endpoint": "/api/gateway/health-refresh", "command": None, "requires_arm": False, "arm_group": None},
            "reason": "refresh_gateway_health_evidence",
            "steps": ["get_gateway_health_refresh", "refresh_communication_status"],
            "executable": True,
        }
    if source == "tailscale" and action in {"install", "login", "reconnect"}:
        return {
            **base,
            "plan_status": "manual_required",
            "route": {"method": None, "endpoint": None, "command": None, "requires_arm": False, "arm_group": None},
            "reason": "tailscale_operator_action_required",
            "steps": ["open_tailscale", "install_or_login_or_reconnect", "refresh_communication_status"],
            "executable": False,
        }
    return {
        **base,
        "plan_status": "manual_required",
        "route": {"method": None, "endpoint": None, "command": None, "requires_arm": False, "arm_group": None},
        "reason": f"no_route_for_{source}_{action}",
        "steps": ["inspect_communication_status"],
        "executable": False,
    }


def communication_repair_one(payload: dict[str, Any] | None = None, *, root: Path = ROOT) -> dict[str, Any]:
    payload = payload or {}
    status = communication_status(root)
    plan = communication_action_plan(status, root=root)
    if not plan.get("executable"):
        return {"status": "noop" if plan.get("plan_status") == "noop" else "manual_required", "kind": "communication_repair_one", "plan": plan}
    route = plan.get("route") if isinstance(plan.get("route"), dict) else {}
    endpoint = str(route.get("endpoint") or "")
    if endpoint == "/api/services/start":
        service_payload = {
            **payload,
            "services": plan.get("payload", {}).get("services", []),
            "operator_scopes": payload.get("operator_scopes") or payload.get("scopes") or [],
        }
        result = service_start_action(service_payload, root=root)
    elif endpoint == "/api/nodes/recovery-cycle":
        cycle_payload = {
            **payload,
            "execute": True,
            "max_actions": int(payload.get("max_actions") or 1),
            "operator_scopes": payload.get("operator_scopes") or payload.get("scopes") or [],
        }
        result = node_recovery_cycle(cycle_payload, root=root)
    elif endpoint == "/api/communication/repair-one":
        repair_action = str(payload.get("action") or "")
        if repair_action != "recover_stale_commands":
            return {"status": "manual_required", "kind": "communication_repair_one", "plan": plan, "reason": "unsupported_repair_action"}
        recover_payload = {
            **payload,
            "node_id": str(payload.get("node_id") or ""),
            "stream": str(payload.get("stream") or TASKS_STREAM_KEY),
            "group": str(payload.get("group") or TASKS_STREAM_GROUP),
            "count": payload.get("count"),
            "max_claim": payload.get("max_claim"),
            "min_idle_ms": payload.get("min_idle_ms"),
            "timeout": payload.get("timeout"),
            "operator_scopes": payload.get("operator_scopes") or payload.get("scopes") or [],
            "request_id": str(payload.get("request_id") or ""),
        }
        result = recover_stale_commands(recover_payload, root=root)
    elif endpoint == "/api/gateway/health-refresh":
        result = gateway_health_refresh(root=root)
    elif endpoint == "/api/nodes/bootstrap-takeover-admission":
        admission_payload = {**plan.get("payload", {}), **payload}
        result = bootstrap_takeover_admission(admission_payload, root=root)
    else:
        return {"status": "manual_required", "kind": "communication_repair_one", "plan": plan, "reason": "unknown_route"}
    refreshed = communication_status(root)
    return {"status": "ok", "kind": "communication_repair_one", "plan": plan, "result": result, "communication_after": refreshed}


def recover_stale_commands(payload: dict[str, Any] | None = None, *, root: Path = ROOT) -> dict[str, Any]:
    payload = payload or {}
    started_at = utc_now()
    try:
        node_id = safe_node_id(str(payload.get("node_id") or ""))
    except ValueError:
        return {
            "status": "degraded",
            "kind": "recover_stale_commands",
            "action": "recover_stale_commands",
            "node_id": "",
            "stream": str(payload.get("stream") or TASKS_STREAM_KEY),
            "group": str(payload.get("group") or TASKS_STREAM_GROUP),
            "before": {},
            "after": {},
            "claim_result": {
                "status": "degraded",
                "error_code": "invalid_payload",
                "action": "claim_stale_once",
                "reason": "node_id is required",
            },
            "recovered_count": 0,
            "claimed_ids": [],
            "reason": "node_id is required",
            "started_at": started_at,
            "finished_at": utc_now(),
        }

    stream = str(payload.get("stream") or TASKS_STREAM_KEY).strip() or TASKS_STREAM_KEY
    group = str(payload.get("group") or TASKS_STREAM_GROUP).strip() or TASKS_STREAM_GROUP
    recovery_gate = command_gate("nodes.recover.stale_commands", root=root)
    if not recovery_gate.get("allowed"):
        return {
            "status": "blocked",
            "kind": "recover_stale_commands",
            "action": "recover_stale_commands",
            "node_id": node_id,
            "stream": stream,
            "group": group,
            "before": {},
            "after": {},
            "claim_result": {},
            "recovered_count": 0,
            "claimed_ids": [],
            "reason": str(recovery_gate.get("reason") or "phone_control_disarmed"),
            "gate": recovery_gate,
            "started_at": started_at,
            "finished_at": utc_now(),
        }
    raw_count = payload.get("count")
    if raw_count is None:
        raw_count = payload.get("max_claim")
    try:
        count = int(raw_count or 1)
    except (TypeError, ValueError):
        return {
            "status": "degraded",
            "kind": "recover_stale_commands",
            "action": "recover_stale_commands",
            "node_id": node_id,
            "stream": stream,
            "group": group,
            "before": {},
            "after": {},
            "claim_result": {
                "status": "degraded",
                "error_code": "invalid_payload",
                "action": "claim_stale_once",
                "reason": "count_or_max_claim_must_be_integer",
            },
            "recovered_count": 0,
            "claimed_ids": [],
            "reason": "count_or_max_claim_must_be_integer",
            "started_at": started_at,
            "finished_at": utc_now(),
        }
    if count < 1:
        return {
            "status": "degraded",
            "kind": "recover_stale_commands",
            "action": "recover_stale_commands",
            "node_id": node_id,
            "stream": stream,
            "group": group,
            "before": {},
            "after": {},
            "claim_result": {
                "status": "degraded",
                "error_code": "invalid_payload",
                "action": "claim_stale_once",
                "reason": "count_or_max_claim_must_be_positive",
            },
            "recovered_count": 0,
            "claimed_ids": [],
            "reason": "count_or_max_claim_must_be_positive",
            "started_at": started_at,
            "finished_at": utc_now(),
        }
    try:
        min_idle_ms = int(payload.get("min_idle_ms") or 30000)
    except (TypeError, ValueError):
        return {
            "status": "degraded",
            "kind": "recover_stale_commands",
            "action": "recover_stale_commands",
            "node_id": node_id,
            "stream": stream,
            "group": group,
            "before": {},
            "after": {},
            "claim_result": {
                "status": "degraded",
                "error_code": "invalid_payload",
                "action": "claim_stale_once",
                "reason": "min_idle_ms_must_be_integer",
            },
            "recovered_count": 0,
            "claimed_ids": [],
            "reason": "min_idle_ms_must_be_integer",
            "started_at": started_at,
            "finished_at": utc_now(),
        }
    try:
        timeout = int(payload.get("timeout") or 3)
    except (TypeError, ValueError):
        return {
            "status": "degraded",
            "kind": "recover_stale_commands",
            "action": "recover_stale_commands",
            "node_id": node_id,
            "stream": stream,
            "group": group,
            "before": {},
            "after": {},
            "claim_result": {
                "status": "degraded",
                "error_code": "invalid_payload",
                "action": "claim_stale_once",
                "reason": "timeout_must_be_integer",
            },
            "recovered_count": 0,
            "claimed_ids": [],
            "reason": "timeout_must_be_integer",
            "started_at": started_at,
            "finished_at": utc_now(),
        }

    before = redis_tasks_stream_probe()
    claim_result = a9_node().node_command_claim_stale_once(
        node_id=node_id,
        count=count,
        min_idle_ms=min_idle_ms,
        group=group,
        stream=stream,
        timeout=max(1, timeout),
    )
    after = redis_tasks_stream_probe()
    finished_at = utc_now()

    events = claim_result.get("events") if isinstance(claim_result.get("events"), list) else []
    claimed_ids = [str(item.get("id")) for item in events if isinstance(item, dict) and item.get("id")]
    if claim_result.get("status") == "ok":
        recovered_count = int(claim_result.get("command_count") or 0)
        status = "ok"
        reason = "stale_commands_recovered"
    elif claim_result.get("status") == "noop" and claim_result.get("error_code") == "no_pending_events":
        recovered_count = 0
        status = "noop"
        reason = "no_stale_pending_commands"
    elif claim_result.get("status") == "noop":
        recovered_count = 0
        status = "ok"
        reason = str(claim_result.get("reason") or "noop_without_pending_claims")
    else:
        recovered_count = 0
        status = "degraded"
        reason = str(claim_result.get("reason") or "recover_stale_commands_failed")

    result = {
        "status": status,
        "kind": "recover_stale_commands",
        "action": "recover_stale_commands",
        "node_id": node_id,
        "stream": stream,
        "group": group,
        "gate": recovery_gate,
        "before": {
            "status": before.get("status"),
            "stream": before.get("stream") or stream,
            "group": before.get("group") or group,
            "pending": before.get("pending"),
            "stream_action": before.get("stream_action"),
            "stream_action_reason": before.get("stream_action_reason"),
        },
        "after": {
            "status": after.get("status"),
            "stream": after.get("stream") or stream,
            "group": after.get("group") or group,
            "pending": after.get("pending"),
            "stream_action": after.get("stream_action"),
            "stream_action_reason": after.get("stream_action_reason"),
        },
        "claim_result": claim_result,
        "recovered_count": recovered_count,
        "claimed_ids": claimed_ids,
        "reason": reason,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    evidence_path = write_node_evidence(
        "recover-stale-commands",
        node_id,
        {
            "kind": result["kind"],
            "action": result["action"],
            "node_id": node_id,
            "stream": stream,
            "group": group,
            "before": result["before"],
            "after": result["after"],
            "claim_result": claim_result,
        },
        root=root,
    )
    result["evidence_path"] = str(evidence_path)
    return result


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
                evidence_name = Path(evidence_path).name if evidence_path else ""
                if not evidence_path or ("tmux-plan-" not in evidence_name and "heartbeat-tmux-plan-" not in evidence_name):
                    plan_payload = {
                        **action_payload,
                        "session": route.get("session") or payload.get("session") or "a9",
                        "remote_dir": payload.get("remote_dir") or "~/a9-worker",
                    }
                    if route.get("plan_kind") == "heartbeat_tmux":
                        tmux_plan = heartbeat_tmux_plan_node(plan_payload, root=root)
                    else:
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

            elif recovery_action == "heartbeat_repair":
                action_payload.update(
                    {
                        "controller_url": payload.get("controller_url") or "",
                        "remote_dir": payload.get("remote_dir") or "~/a9-worker",
                        "worker_name": payload.get("worker_name") or node_id,
                    }
                )
                step["prepared_plan"] = {
                    "status": "planned",
                    "endpoint": "/api/nodes/heartbeat-repair",
                    "target": action_payload["target"],
                    "remote_dir": action_payload["remote_dir"],
                    "worker_name": action_payload["worker_name"],
                    "controller_url": action_payload["controller_url"] or "http://127.0.0.1:8787",
                    "execution_enabled": False,
                    "steps": ["write heartbeat config", "write heartbeat.sh", "chmod heartbeat.sh"],
                }
                if execute:
                    result = heartbeat_repair_node(action_payload, root=root)
                    step.update({"status": "executed" if result.get("status") != "blocked" else "blocked", "result": result})
                else:
                    step["result"] = {
                        "status": "planned",
                        "endpoint": "/api/nodes/heartbeat-repair",
                        "payload": action_payload,
                    }

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
    heartbeat_repair_action = str(record.get("heartbeat_repair_action") or "")
    hygiene = record.get("hygiene") if isinstance(record.get("hygiene"), dict) else node_hygiene(record)
    heartbeat_start_at = parse_iso_datetime(str(record.get("heartbeat_start_executed_at") or ""))
    heartbeat_repair_at = parse_iso_datetime(str(record.get("heartbeat_repair_executed_at") or ""))
    tmux_checked_at = parse_iso_datetime(str(record.get("tmux_checked_at") or ""))
    repair_after_start = bool(heartbeat_repair_at and (not heartbeat_start_at or heartbeat_repair_at > heartbeat_start_at))
    tmux_missing_after_start = bool(
        tmux_checked_at
        and (not heartbeat_start_at or tmux_checked_at > heartbeat_start_at)
        and (not heartbeat_repair_at or tmux_checked_at > heartbeat_repair_at)
    )

    if (
        hygiene.get("category") == "remote_candidate"
        and heartbeat_repair_action == "continue"
        and (
            heartbeat_start_action != "continue"
            or repair_after_start
        )
    ):
        return {
            "action": "heartbeat_start",
            "reason": "heartbeat_repaired_start_required",
            "steps": ["start_heartbeat_tmux", "refresh_node_status"],
            "requires_operator": False,
            "route": {
                "method": "POST",
                "endpoint": "/api/nodes/heartbeat-tmux-start",
                "command": "nodes.heartbeat.tmux.start",
                "requires_arm": True,
            },
        }

    if hygiene.get("category") == "remote_candidate" and probe_action == "continue" and heartbeat_start_action != "continue":
        return {
            "action": "heartbeat_start",
            "reason": str(record.get("heartbeat_start_action_reason") or "remote_probe_ok_heartbeat_missing"),
            "steps": ["start_heartbeat_tmux", "refresh_node_status"],
            "requires_operator": False,
            "route": {
                "method": "POST",
                "endpoint": "/api/nodes/heartbeat-tmux-start",
                "command": "nodes.heartbeat.tmux.start",
                "requires_arm": True,
            },
        }

    if (
        hygiene.get("category") == "remote_candidate"
        and heartbeat_start_action == "continue"
        and tmux_action in {"retry", "repair"}
        and str(record.get("tmux_session") or "") == "a9-heartbeat"
        and tmux_missing_after_start
    ):
        return {
            "action": "heartbeat_repair",
            "reason": "heartbeat_tmux_missing_after_start",
            "steps": ["repair_remote_heartbeat_script", "start_heartbeat_tmux", "refresh_node_status"],
            "requires_operator": True,
            "route": {
                "method": "POST",
                "endpoint": "/api/nodes/heartbeat-repair",
                "command": "nodes.remote.repair",
                "requires_arm": True,
            },
        }

    if (
        hygiene.get("category") == "remote_candidate"
        and heartbeat_start_action == "continue"
        and connection_state in {"stale", "offline", "degraded", "unknown", "connected"}
        and connection_action not in {"continue", "watch"}
    ):
        return {
            "action": "tmux",
            "reason": "remote_heartbeat_stale_check_tmux",
            "steps": ["check_heartbeat_tmux_session", "refresh_node_status"],
            "requires_operator": True,
            "route": {
                "method": "POST",
                "endpoint": "/api/nodes/tmux-status",
                "command": "nodes.tmux.status",
                "requires_arm": True,
                "session": "a9-heartbeat",
                "plan_kind": "heartbeat_tmux",
            },
        }

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
        if hygiene.get("category") == "remote_candidate":
            return {
                "action": "probe",
                "reason": "remote_candidate_heartbeat_offline",
                "steps": ["run_node_communication_probe", "refresh_node_status"],
                "requires_operator": False,
                "route": {
                    "method": "POST",
                    "endpoint": "/api/nodes/probe",
                    "command": "nodes.probe.execute",
                    "requires_arm": True,
                },
            }
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


def _normalize_intervention_decision_payload(payload: Any) -> dict[str, Any]:
    allowed_actions = {"observe", "watch", "repair", "intervene", "quarantine"}
    if not isinstance(payload, dict):
        return {}
    action = str(payload.get("action") or "")
    if action not in allowed_actions:
        return {}
    refs_raw = payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), list) else []
    refs: list[str] = []
    seen = set()
    for ref in refs_raw:
        normalized = str(ref).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        refs.append(normalized)
    return {
        "action": action,
        "reason": str(payload.get("reason") or "healthy"),
        "evidence_refs": refs,
    }


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
    followup = {
        "action": best["action"],
        "reason": best["reason"],
        "status": best["status"],
        "evidence": best["evidence"],
    }
    followup["intervention_decision"] = transcript_intervention_decision([], tasks_stream, followup, {})
    return followup


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
            "tmux_session": str(payload.get("session") or ""),
            "tmux_checked_at": str(payload.get("checked_at") or payload.get("executed_at") or ""),
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


def latest_heartbeat_repair_evidence_for_node(node_id: str, *, root: Path = ROOT) -> dict[str, Any] | None:
    evidence_dir = node_evidence_dir(node_id, root)
    if not evidence_dir.exists():
        return None
    candidates = sorted(
        evidence_dir.glob("heartbeat-repair*.json"),
        key=lambda item: (item.stat().st_mtime, item.name.rsplit("-", 1)[-1]),
        reverse=True,
    )
    for path in candidates:
        try:
            payload = read_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        action = payload.get("repair_action")
        if not action:
            continue
        return {
            "heartbeat_repair_status": str(payload.get("status") or ""),
            "heartbeat_repair_action": str(action),
            "heartbeat_repair_action_reason": str(payload.get("repair_action_reason") or ""),
            "heartbeat_repair_executed_at": str(payload.get("executed_at") or ""),
            "heartbeat_repair_evidence_path": str(path),
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


def enrich_node_heartbeat_repair_evidence(record: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    node_id = str(record.get("node_id") or "")
    if not node_id:
        return record
    repair = latest_heartbeat_repair_evidence_for_node(node_id, root=root)
    if not repair:
        return record
    return {**record, **repair}


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
        if action_reason == "pending_stuck":
            result["recommended_action"] = "recover_stale_commands"

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
        recovery_hint = node_command_recovery_hint(
            node_id=str(command.get("node_id") or ""),
            command_id=str(command.get("command_id") or ""),
            result_status="degraded",
            result_error_code=command["error_code"],
        )
        return {
            "status": "degraded",
            "kind": "node_command_enqueue",
            "error_code": command["error_code"],
            "command": command,
            "recovery_hint": recovery_hint,
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
            "recovery_hint": node_command_recovery_hint(
                node_id=str(command.get("node_id") or ""),
                command_id=str(command.get("command_id") or ""),
                result_status="degraded",
                result_error_code=command["error_code"],
            ),
        }

    stream_id = proc.stdout.strip()
    command["stream_id"] = stream_id
    command["error_code"] = "none"
    return {
        "status": "ok",
        "kind": "node_command_enqueue",
        "command": command,
        "recovery_hint": node_command_recovery_hint(
            node_id=str(command.get("node_id") or ""),
            command_id=str(command.get("command_id") or ""),
            result_status="submitted",
            result_error_code="none",
        ),
    }


def node_command_recovery_hint(
    *,
    node_id: str,
    command_id: str = "",
    result_event_id: str = "",
    result_status: str = "",
    result_error_code: str = "",
    root: Path = ROOT,
) -> dict[str, Any]:
    normalized_node_id = safe_node_id(str(node_id or "").strip()) if str(node_id or "").strip() else ""
    safe_command_id = str(command_id or "").strip()
    safe_result_event_id = str(result_event_id or "").strip()
    safe_result_status = str(result_status or "").strip()
    safe_error_code = str(result_error_code or "").strip()
    evidence_refs: list[str] = []
    if safe_result_event_id:
        evidence_refs.append(f"redis:event:{safe_result_event_id}")
    if safe_command_id:
        evidence_refs.append(f"redis:command:{safe_command_id}")
    if safe_error_code == "redis_unavailable":
        return {
            "action": "degraded",
            "reason": "redis_unavailable",
            "evidence_refs": evidence_refs + ["redis:ping"],
            "next_endpoint": "/api/nodes/status",
        }
    if safe_result_status in {"submitted", "queued"}:
        return {
            "action": "wait",
            "reason": "await_result",
            "evidence_refs": evidence_refs,
            "next_endpoint": (
                f"/api/node-command-results/by-command/{safe_command_id}"
                if safe_command_id
                else "/api/node-command-results/by-command/{command_id}"
            ),
        }
    if safe_result_status == "ok":
        return {
            "action": "observe",
            "reason": "command_result_found",
            "evidence_refs": evidence_refs,
            "next_endpoint": "/api/nodes/recovery-transcript",
        }
    if not normalized_node_id:
        return {
            "action": "probe",
            "reason": "node_unknown",
            "evidence_refs": evidence_refs + ["node:unknown"],
            "next_endpoint": "/api/nodes/probe",
        }
    record_path = node_path(normalized_node_id, root)
    if not record_path.exists():
        return {
            "action": "probe",
            "reason": "node_unknown",
            "evidence_refs": evidence_refs + [f"node:{normalized_node_id}:missing"],
            "next_endpoint": "/api/nodes/probe",
        }
    try:
        record = enrich_node_connection(read_json(record_path))
    except (OSError, json.JSONDecodeError):
        return {
            "action": "probe",
            "reason": "node_state_unreadable",
            "evidence_refs": evidence_refs + [str(record_path)],
            "next_endpoint": "/api/nodes/probe",
        }
    connection_state = str(record.get("connection_state") or "")
    connection_reason = str(record.get("connection_action_reason") or "")
    evidence_refs.extend([str(record_path), f"node:{normalized_node_id}:state:{connection_state or 'unknown'}"])
    recovery = node_recovery_plan(record)
    route = recovery.get("route") if isinstance(recovery, dict) else {}
    recovery_endpoint = str(route.get("endpoint") or "").strip()
    recovery_action = str(recovery.get("action") or "wait")
    recovery_reason = str(recovery.get("reason") or "result_missing_pending")
    if recovery_endpoint and recovery_action not in {"observe", "none", "wait"}:
        return {
            "action": recovery_action,
            "reason": recovery_reason,
            "evidence_refs": evidence_refs,
            "next_endpoint": recovery_endpoint,
            "next_method": route.get("method"),
            "next_command": route.get("command"),
            "next_requires_arm": bool(route.get("requires_arm")),
        }
    if connection_state in {"stale", "degraded"}:
        return {
            "action": "reconnect",
            "reason": connection_reason or "heartbeat_stale",
            "evidence_refs": evidence_refs,
            "next_endpoint": "/api/nodes/probe",
        }
    if connection_state in {"offline", "unknown"}:
        return {
            "action": "probe",
            "reason": connection_reason or "heartbeat_timeout",
            "evidence_refs": evidence_refs,
            "next_endpoint": "/api/nodes/probe",
        }
    endpoint = recovery_endpoint or "/api/node-command-results/by-command/{command_id}"
    action = recovery_action
    reason = recovery_reason
    if action in {"observe", "none"}:
        action = "wait"
        reason = "result_missing_pending"
    return {
        "action": action,
        "reason": reason,
        "evidence_refs": evidence_refs,
        "next_endpoint": endpoint,
    }


def node_command_result_lookup(
    result_event_id: str,
    *,
    event_stream: str = EVENTS_STREAM_KEY,
    timeout: int = 3,
    node_id: str = "",
    root: Path = ROOT,
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
    resolved_node_id = str(result.get("node_id") or node_id or "")
    payload["recovery_hint"] = node_command_recovery_hint(
        node_id=resolved_node_id,
        command_id=str(result.get("command_id") or ""),
        result_event_id=safe_result_event_id,
        result_status=status,
        result_error_code=error_code,
        root=root,
    )
    return payload


def node_command_result_by_command_lookup(
    command_id: str,
    *,
    event_stream: str = EVENTS_STREAM_KEY,
    limit: int = 100,
    timeout: int = 3,
    result_last_id: str | None = None,
    node_id: str = "",
    root: Path = ROOT,
) -> dict[str, Any]:
    safe_command_id = str(command_id or "").strip()
    safe_event_stream = str(event_stream or "").strip()
    base: dict[str, Any] = {
        "status": "degraded",
        "kind": "node_command_result_by_command_lookup",
        "command_id": safe_command_id,
        "requested_node_id": str(node_id or ""),
        "event_stream": safe_event_stream,
        "limit": 0,
        "result_event_id": "",
        "result_node_id": "",
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

    replay: dict[str, Any] | None = None
    replay_reset = {"action": "keep_cursor", "reason": "no_cursor_reset_needed", "next_last_id": ""}
    if result_last_id is not None:
        replay = read_node_result_replay(
            result_last_id,
            event_stream=safe_event_stream,
            limit=requested,
        )
        replay_reset = result_replay_reset_decision(replay)
        if str(replay.get("status") or "") == "degraded":
            return {
                **base,
                "status": "degraded",
                "limit": requested,
                "error_code": str(replay.get("error_code") or "result_replay_degraded"),
                "reason": str(replay.get("error") or replay.get("error_code") or "result_replay_degraded"),
                "scanned_count": 0,
                "result_replay": replay,
                "result_replay_reset": replay_reset,
                "recovery_hint": node_command_recovery_hint(
                    node_id=node_id,
                    command_id=safe_command_id,
                    result_status="degraded",
                    result_error_code=str(replay.get("error_code") or "result_replay_degraded"),
                    root=root,
                ),
            }

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
            "result_replay_reset": replay_reset,
        }
        if replay is not None:
            payload["result_replay"] = replay
        if status != "ok":
            payload["reason"] = str(lookup.get("reason") or error_code)
        actual_node_id = str(lookup.get("result", {}).get("result", {}).get("node_id") or "").strip()
        payload["result_node_id"] = actual_node_id
        payload["recovery_hint"] = node_command_recovery_hint(
            node_id=actual_node_id or str(node_id or ""),
            command_id=safe_command_id,
            result_event_id=result_event_id,
            result_status=status,
            result_error_code=error_code,
            root=root,
        )
        return payload

    return_payload = {
        **base,
        "status": "noop",
        "limit": requested,
        "error_code": "no_result",
        "reason": "node_command_result_not_found",
        "scanned_count": len(events),
        "result_replay_reset": replay_reset,
    }
    if replay is not None:
        return_payload["result_replay"] = replay
    return_payload["recovery_hint"] = node_command_recovery_hint(
        node_id=node_id,
        command_id=safe_command_id,
        result_status="noop",
        result_error_code="no_result",
        root=root,
    )
    return return_payload


def node_command_result_watch(
    command_id: str,
    *,
    event_stream: str = EVENTS_STREAM_KEY,
    limit: int = 100,
    timeout: int = 3,
    timeout_seconds: int | None = None,
    result_last_id: str | None = None,
    node_id: str = "",
    root: Path = ROOT,
) -> dict[str, Any]:
    safe_timeout_raw = timeout_seconds if timeout_seconds is not None else timeout
    lookup = node_command_result_by_command_lookup(
        command_id,
        event_stream=event_stream,
        limit=limit,
        timeout=safe_timeout_raw,
        result_last_id=result_last_id,
        node_id=node_id,
        root=root,
    )
    status = str(lookup.get("status") or "degraded")
    replay_reset = lookup.get("result_replay_reset") if isinstance(lookup.get("result_replay_reset"), dict) else {}
    next_last_id = str(lookup.get("result_event_id") or replay_reset.get("next_last_id") or result_last_id or "")
    watch_action = "reconnect"
    watch_reason = "transient_error"

    if status == "ok":
        watch_action = "terminate"
        watch_reason = "command_result_found"
    elif status == "noop":
        watch_action = "continue"
        watch_reason = "node_command_result_not_found_yet"
    elif status == "degraded":
        error_code = str(lookup.get("error_code") or "")
        if error_code in {"invalid_payload", "invalid_cursor"}:
            watch_action = "terminate"
            watch_reason = error_code or "invalid_payload"
        elif error_code == "cursor_gap":
            watch_action = "reconnect"
            watch_reason = "cursor_gap_reset_required"

    payload = {
        "status": status,
        "kind": "node_command_result_watch",
        "command_id": str(lookup.get("command_id") or str(command_id or "").strip()),
        "result": lookup.get("result") or {},
        "result_replay": lookup.get("result_replay") if "result_replay" in lookup else None,
        "result_replay_reset": replay_reset
        if replay_reset
        else {"action": "keep_cursor", "reason": "no_cursor_reset_needed", "next_last_id": ""},
        "watch_action": watch_action,
        "watch_reason": watch_reason,
        "next_last_id": next_last_id,
    }
    if "recovery_hint" in lookup:
        payload["recovery_hint"] = lookup["recovery_hint"]
    if "error_code" in lookup:
        payload["error_code"] = lookup["error_code"]
    if "reason" in lookup:
        payload["reason"] = lookup["reason"]
    return payload


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
    runtime_contract = {
        "bootstrap_mode": "ssh_bootstrap_only",
        "runtime_mode": "redis_api_runtime",
        "transport": "tailscale+ssh+bootstrap",
        "heartbeat_script": ".a9/remote-node/heartbeat.sh",
        "heartbeat_tmux_session": "a9-heartbeat",
        "controller_heartbeat_endpoint": f"{controller_url.rstrip('/')}/api/nodes/heartbeat",
    }
    return {
        "status": "planned",
        "target": target,
        "controller_url": controller_url,
        "repo": repo,
        "remote_dir": remote_dir,
        "worker_name": worker_name,
        "runtime_contract": runtime_contract,
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


def bootstrap_takeover_admission(payload: dict[str, Any] | None = None, *, root: Path = ROOT) -> dict[str, Any]:
    payload = payload or {}
    reconnect_event = payload.get("reconnect_event") if isinstance(payload.get("reconnect_event"), dict) else latest_gateway_reconnect_decision_event()
    reconnect_action = str(reconnect_event.get("action") or payload.get("reconnect_action") or "").strip().lower()
    terminal_actions = {"terminate", "quarantine"}
    if reconnect_action not in terminal_actions:
        return {
            "status": "noop",
            "kind": "bootstrap_takeover_admission",
            "execution_enabled": False,
            "no_actuation": True,
            "reason": "reconnect_action_not_terminal",
            "reconnect_event": reconnect_event,
        }

    raw_node_id = str(payload.get("node_id") or reconnect_event.get("node_id") or payload.get("ssh_target") or payload.get("target") or "gateway").strip()
    node_id = safe_node_id(raw_node_id)
    record_path = node_path(node_id, root)
    existing = read_json(record_path) if record_path.exists() else {}
    current_revision = parse_int(existing.get("revision"), default=parse_int(reconnect_event.get("flow_revision"), default=0))
    if "expected_revision" in payload and payload.get("expected_revision") is not None:
        expected_revision = parse_int(payload.get("expected_revision"), default=-1)
    else:
        expected_revision = current_revision
    if expected_revision != current_revision:
        result = {
            "status": "conflict",
            "kind": "bootstrap_takeover_admission",
            "execution_enabled": False,
            "no_actuation": True,
            "node_id": node_id,
            "expected_revision": expected_revision,
            "actual_revision": current_revision,
            "reason": "expected_revision_mismatch",
            "reconnect_event": reconnect_event,
        }
        append_jsonl(root / BOOTSTRAP_TAKEOVER_ADMISSION_AUDIT_REL_PATH, {**result, "recorded_at": utc_now()})
        return result

    now = utc_now()
    next_revision = current_revision + 1
    approval_id = str(payload.get("approval_id") or f"bootstrap-takeover:{node_id}:{next_revision}")
    resume_token = str(payload.get("resume_token") or f"{approval_id}:resume")
    target = str(payload.get("ssh_target") or payload.get("target") or existing.get("ssh_target") or "").strip()
    wait = {
        "type": "approval_request",
        "approvalId": approval_id,
        "resumeToken": resume_token,
        "prompt": "Gateway reconnect policy terminated automatic reconnect. Approve bootstrap takeover only after operator review.",
        "items": [
            {"type": "reconnect_event", "event_id": str(reconnect_event.get("event_id") or ""), "action": reconnect_action},
            {"type": "node", "node_id": node_id, "expected_revision": next_revision},
        ],
    }
    record = {
        **existing,
        "node_id": node_id,
        "status": "await_bootstrap_takeover",
        "status_reason": str(payload.get("reason") or reconnect_event.get("error_class") or "reconnect_terminal"),
        "revision": next_revision,
        "updated_at": now,
        "last_seen_at": str(existing.get("last_seen_at") or now),
        "ssh_target": target,
        "bootstrap_takeover": {
            "state": "waiting",
            "reason": str(payload.get("reason") or "gateway_reconnect_terminal"),
            "expected_revision": next_revision,
            "previous_revision": current_revision,
            "admitted_at": now,
            "approval_id": approval_id,
            "resume_token": resume_token,
            "reconnect_event_id": str(reconnect_event.get("event_id") or ""),
        },
        "reconnect_action": reconnect_action,
        "reconnect_reason": str(reconnect_event.get("error_class") or payload.get("reason") or "reconnect_terminal"),
        "reconnect_lifecycle": {
            "event": "await_bootstrap_takeover",
            "phase": str(reconnect_event.get("phase") or ""),
            "action": reconnect_action,
            "at": now,
        },
    }
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = {
        "status": "needs_approval",
        "kind": "bootstrap_takeover_admission",
        "schema": "a9.bootstrap_takeover_admission.v1",
        "execution_enabled": False,
        "no_actuation": True,
        "node_id": node_id,
        "target": target,
        "previous_revision": current_revision,
        "expected_revision": next_revision,
        "admitted_at": now,
        "reason": "await_bootstrap_takeover",
        "wait": wait,
        "reconnect_event": reconnect_event,
        "record": record,
    }
    evidence_path = write_node_evidence("bootstrap-takeover-admission", node_id, result, root=root)
    result["evidence_path"] = str(evidence_path)
    append_jsonl(root / BOOTSTRAP_TAKEOVER_ADMISSION_AUDIT_REL_PATH, {**result, "record": {"node_id": node_id, "revision": next_revision}})
    return result


def bootstrap_takeover_resume(payload: dict[str, Any] | None = None, *, root: Path = ROOT) -> dict[str, Any]:
    raw = payload or {}
    require_phone_admin(raw)

    raw_node_id = str(raw.get('node_id') or raw.get('target') or raw.get('ssh_target') or '').strip()
    node_id = safe_node_id(raw_node_id)
    if not node_id:
        return {
            'status': 'invalid_request',
            'kind': 'bootstrap_takeover_resume',
            'schema': 'a9.bootstrap_takeover_resume.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'reason': 'node_id_required',
        }

    record_path = node_path(node_id, root)
    if not record_path.exists():
        return {
            'status': 'missing',
            'kind': 'bootstrap_takeover_resume',
            'schema': 'a9.bootstrap_takeover_resume.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'reason': 'record_missing',
        }

    try:
        record = read_json(record_path)
    except (OSError, json.JSONDecodeError):
        return {
            'status': 'invalid_state',
            'kind': 'bootstrap_takeover_resume',
            'schema': 'a9.bootstrap_takeover_resume.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'reason': 'record_read_failed',
        }

    bootstrap_state = record.get('bootstrap_takeover')
    if not isinstance(bootstrap_state, dict):
        return {
            'status': 'invalid_state',
            'kind': 'bootstrap_takeover_resume',
            'schema': 'a9.bootstrap_takeover_resume.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'reason': 'missing_bootstrap_takeover_state',
        }

    if 'expected_revision' not in raw:
        return {
            'status': 'invalid_request',
            'kind': 'bootstrap_takeover_resume',
            'schema': 'a9.bootstrap_takeover_resume.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'reason': 'expected_revision_required',
        }

    try:
        expected_revision = int(raw.get('expected_revision'))
    except (TypeError, ValueError):
        return {
            'status': 'invalid_request',
            'kind': 'bootstrap_takeover_resume',
            'schema': 'a9.bootstrap_takeover_resume.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'reason': 'expected_revision_must_be_integer',
        }

    current_revision = parse_int(record.get('revision'), default=-1)
    if expected_revision != current_revision:
        result = {
            'status': 'conflict',
            'kind': 'bootstrap_takeover_resume',
            'schema': 'a9.bootstrap_takeover_resume.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'expected_revision': expected_revision,
            'actual_revision': current_revision,
            'reason': 'expected_revision_mismatch',
            'record': {'node_id': node_id, 'revision': current_revision},
        }
        append_jsonl(root / BOOTSTRAP_TAKEOVER_ADMISSION_AUDIT_REL_PATH, {**result, 'record': record})
        return result

    if str(bootstrap_state.get('state') or '') != 'waiting':
        return {
            'status': 'invalid_state',
            'kind': 'bootstrap_takeover_resume',
            'schema': 'a9.bootstrap_takeover_resume.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'expected_revision': expected_revision,
            'reason': 'not_in_wait_state',
        }

    now = utc_now()
    next_revision = current_revision + 1
    approval_id = str(
        raw.get('approval_id')
        or bootstrap_state.get('approval_id')
        or f'bootstrap-takeover:{node_id}:{next_revision}'
    )
    resume_token = str(
        raw.get('resume_token')
        or bootstrap_state.get('resume_token')
        or f'{approval_id}:resume'
    )
    actor = str(raw.get('actor') or raw.get('operator') or 'mobile-operator').strip() or 'mobile-operator'

    updated = {
        **record,
        'node_id': node_id,
        'status': 'await_bootstrap_takeover',
        'status_reason': 'bootstrap_takeover_approved',
        'revision': next_revision,
        'updated_at': now,
        'bootstrap_takeover': {
            **bootstrap_state,
            'state': 'approved',
            'decision': 'resume_approved',
            'approval_id': approval_id,
            'resume_token': resume_token,
            'approved_by': actor,
            'approved_at': now,
            'decision_reason': str(raw.get('reason') or 'approved'),
        },
    }
    record_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    result = {
        'status': 'approved',
        'kind': 'bootstrap_takeover_resume',
        'schema': 'a9.bootstrap_takeover_resume.v1',
        'execution_enabled': False,
        'no_actuation': True,
        'node_id': node_id,
        'expected_revision': expected_revision,
        'previous_revision': current_revision,
        'next_revision': next_revision,
        'reason': 'bootstrap_takeover_approved',
        'record': updated,
    }
    evidence_path = write_node_evidence('bootstrap-takeover-resume', node_id, result, root=root)
    result['evidence_path'] = str(evidence_path)
    append_jsonl(root / BOOTSTRAP_TAKEOVER_ADMISSION_AUDIT_REL_PATH, {
        **result,
        'record': {
            'node_id': node_id,
            'revision': next_revision,
        },
    })
    return result


def bootstrap_takeover_reject(payload: dict[str, Any] | None = None, *, root: Path = ROOT) -> dict[str, Any]:
    raw = payload or {}
    require_phone_admin(raw)

    raw_node_id = str(raw.get('node_id') or raw.get('target') or raw.get('ssh_target') or '').strip()
    node_id = safe_node_id(raw_node_id)
    if not node_id:
        return {
            'status': 'invalid_request',
            'kind': 'bootstrap_takeover_reject',
            'schema': 'a9.bootstrap_takeover_reject.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'reason': 'node_id_required',
        }

    record_path = node_path(node_id, root)
    if not record_path.exists():
        return {
            'status': 'missing',
            'kind': 'bootstrap_takeover_reject',
            'schema': 'a9.bootstrap_takeover_reject.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'reason': 'record_missing',
        }

    try:
        record = read_json(record_path)
    except (OSError, json.JSONDecodeError):
        return {
            'status': 'invalid_state',
            'kind': 'bootstrap_takeover_reject',
            'schema': 'a9.bootstrap_takeover_reject.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'reason': 'record_read_failed',
        }

    bootstrap_state = record.get('bootstrap_takeover')
    if not isinstance(bootstrap_state, dict):
        return {
            'status': 'invalid_state',
            'kind': 'bootstrap_takeover_reject',
            'schema': 'a9.bootstrap_takeover_reject.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'reason': 'missing_bootstrap_takeover_state',
        }

    if 'expected_revision' not in raw:
        return {
            'status': 'invalid_request',
            'kind': 'bootstrap_takeover_reject',
            'schema': 'a9.bootstrap_takeover_reject.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'reason': 'expected_revision_required',
        }

    try:
        expected_revision = int(raw.get('expected_revision'))
    except (TypeError, ValueError):
        return {
            'status': 'invalid_request',
            'kind': 'bootstrap_takeover_reject',
            'schema': 'a9.bootstrap_takeover_reject.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'reason': 'expected_revision_must_be_integer',
        }

    current_revision = parse_int(record.get('revision'), default=-1)
    if expected_revision != current_revision:
        result = {
            'status': 'conflict',
            'kind': 'bootstrap_takeover_reject',
            'schema': 'a9.bootstrap_takeover_reject.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'expected_revision': expected_revision,
            'actual_revision': current_revision,
            'reason': 'expected_revision_mismatch',
            'record': {'node_id': node_id, 'revision': current_revision},
        }
        append_jsonl(root / BOOTSTRAP_TAKEOVER_ADMISSION_AUDIT_REL_PATH, {**result, 'record': record})
        return result

    if str(bootstrap_state.get('state') or '') != 'waiting':
        return {
            'status': 'invalid_state',
            'kind': 'bootstrap_takeover_reject',
            'schema': 'a9.bootstrap_takeover_reject.v1',
            'execution_enabled': False,
            'no_actuation': True,
            'node_id': node_id,
            'expected_revision': expected_revision,
            'reason': 'not_in_wait_state',
        }

    now = utc_now()
    next_revision = current_revision + 1
    actor = str(raw.get('actor') or raw.get('operator') or 'mobile-operator').strip() or 'mobile-operator'
    current_status = str(record.get('status') or 'registered')
    next_status = 'registered' if current_status == 'await_bootstrap_takeover' else current_status

    updated = {
        **record,
        'node_id': node_id,
        'status': next_status,
        'status_reason': 'bootstrap_takeover_rejected',
        'revision': next_revision,
        'updated_at': now,
        'bootstrap_takeover': {
            **bootstrap_state,
            'state': 'rejected',
            'decision': 'reject',
            'rejected_by': actor,
            'rejected_at': now,
            'rejection_reason': str(raw.get('reason') or 'rejected'),
        },
    }
    record_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    result = {
        'status': 'rejected',
        'kind': 'bootstrap_takeover_reject',
        'schema': 'a9.bootstrap_takeover_reject.v1',
        'execution_enabled': False,
        'no_actuation': True,
        'node_id': node_id,
        'expected_revision': expected_revision,
        'previous_revision': current_revision,
        'next_revision': next_revision,
        'reason': 'bootstrap_takeover_rejected',
        'record': updated,
    }
    evidence_path = write_node_evidence('bootstrap-takeover-reject', node_id, result, root=root)
    result['evidence_path'] = str(evidence_path)
    append_jsonl(root / BOOTSTRAP_TAKEOVER_ADMISSION_AUDIT_REL_PATH, {
        **result,
        'record': {
            'node_id': node_id,
            'revision': next_revision,
        },
    })
    return result


def bootstrap_execute_node(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    require_phone_admin(payload)
    gate = command_gate("nodes.bootstrap.execute", root=root)
    if not gate.get("allowed"):
        return {
            "status": "blocked",
            "execution_enabled": False,
            "bootstrap_action": "wait_for_approval",
            "bootstrap_action_reason": str(gate.get("reason") or "phone_control_disarmed"),
            "reason": str(gate.get("reason") or "phone_control_disarmed"),
            "gate": gate,
        }
    plan = bootstrap_plan_node(payload)
    target = str(plan.get('target') or '')
    node_id = safe_node_id(str(payload.get('node_id') or payload.get('ssh_target') or target).strip())
    execution_commit: dict[str, Any] | None = None
    if node_id:
        takeover_path = node_path(node_id, root)
        if takeover_path.exists():
            try:
                takeover_record = read_json(takeover_path)
            except (OSError, json.JSONDecodeError):
                takeover_record = {}
            takeover = takeover_record.get('bootstrap_takeover')
            if (
                str(takeover_record.get('status') or '') == 'await_bootstrap_takeover'
                and (not isinstance(takeover, dict) or str(takeover.get('state') or '') != 'approved')
            ):
                return {
                    'status': 'blocked',
                    'execution_enabled': False,
                    'bootstrap_action': 'wait_for_approval',
                    'bootstrap_action_reason': 'bootstrap_takeover_not_approved',
                    'reason': 'bootstrap_takeover_not_approved',
                    'gate': gate,
                }
            if str(takeover_record.get('status') or '') == 'await_bootstrap_takeover' and isinstance(takeover, dict):
                current_revision = parse_int(takeover_record.get('revision'), default=-1)
                if 'expected_revision' not in payload:
                    return {
                        'status': 'conflict',
                        'execution_enabled': False,
                        'bootstrap_action': 'wait_for_approval',
                        'bootstrap_action_reason': 'expected_revision_required',
                        'reason': 'expected_revision_required',
                        'node_id': node_id,
                        'actual_revision': current_revision,
                        'gate': gate,
                    }
                expected_revision = parse_int(payload.get('expected_revision'), default=-1)
                if expected_revision != current_revision:
                    return {
                        'status': 'conflict',
                        'execution_enabled': False,
                        'bootstrap_action': 'wait_for_approval',
                        'bootstrap_action_reason': 'expected_revision_mismatch',
                        'reason': 'expected_revision_mismatch',
                        'node_id': node_id,
                        'expected_revision': expected_revision,
                        'actual_revision': current_revision,
                        'gate': gate,
                    }
                execution_commit = {
                    'node_id': node_id,
                    'record_path': takeover_path,
                    'previous_revision': current_revision,
                    'current_status': str(takeover_record.get('status') or 'await_bootstrap_takeover'),
                    'bootstrap_takeover': takeover,
                }
    if not target:
        raise ValueError("bootstrap plan is missing target")
    connect_timeout = int(payload.get("connect_timeout") or 5)
    identity_file = str(payload.get("identity_file") or default_identity_file())
    command = ssh_remote_command(target, str(plan.get("dry_run_script") or ""), connect_timeout=connect_timeout, identity_file=identity_file)
    timed_out = False
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=int(payload.get("timeout_seconds") or 60),
        )
        return_code = proc.returncode
        output = proc.stdout
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        output = str(exc)
    status = "timeout" if timed_out else "ok" if return_code == 0 else "failed"
    action = "retry" if status == "timeout" else "continue" if status == "ok" else "repair"
    reason = "bootstrap_timeout" if status == "timeout" else "bootstrap_ok" if status == "ok" else "bootstrap_failed"
    result = {
        "status": status,
        "transport": "tailscale+ssh+bootstrap",
        "transport_quality": transport_quality(target),
        "node_id": safe_node_id(str(payload.get("node_id") or target)),
        "runtime_contract": plan.get("runtime_contract") or {
            "bootstrap_mode": "ssh_bootstrap_only",
            "runtime_mode": "redis_api_runtime",
            "transport": "tailscale+ssh+bootstrap",
            "heartbeat_script": ".a9/remote-node/heartbeat.sh",
            "heartbeat_tmux_session": "a9-heartbeat",
            "controller_heartbeat_endpoint": f"{str(plan.get('controller_url') or '').rstrip('/')}/api/nodes/heartbeat",
        },
        "target": target,
        "controller_url": plan.get("controller_url"),
        "repo": plan.get("repo"),
        "remote_dir": plan.get("remote_dir"),
        "worker_name": plan.get("worker_name"),
        "executed_at": utc_now(),
        "return_code": return_code,
        "timed_out": timed_out,
        "output": compact_text(output, 4000),
        "bootstrap_action": action,
        "bootstrap_action_reason": reason,
        "reason": reason,
        "gate": gate,
        "command_preview": [*command[:-1], "<bootstrap_script>"],
    }
    evidence_path = write_node_evidence("bootstrap", str(result.get("node_id") or target or "node"), result, root=root)
    evidence_path_value = str(evidence_path)
    result["evidence_path"] = evidence_path_value
    if execution_commit is not None:
        now = utc_now()
        previous_revision = int(execution_commit.get("previous_revision") or 0)
        new_revision = previous_revision + 1
        record_path = execution_commit.get("record_path")
        try:
            node_record = read_json(record_path) if isinstance(record_path, Path) else {}
        except (OSError, json.JSONDecodeError):
            node_record = {"node_id": execution_commit.get("node_id"), "revision": previous_revision}
        bootstrap_execution = {
            "action": action,
            "result": status,
            "return_code": return_code,
            "timed_out": timed_out,
            "evidence_path": evidence_path_value,
            "previous_revision": previous_revision,
            "new_revision": new_revision,
        }
        takeover = dict(execution_commit.get("bootstrap_takeover") or {})
        takeover.setdefault("executed_at", now)
        takeover.setdefault("execution_result", status)
        updated_node = {
            **node_record,
            "revision": new_revision,
            "status": "registered" if status == "ok" else str(execution_commit.get("current_status") or "await_bootstrap_takeover"),
            "status_reason": reason,
            "updated_at": now,
            "bootstrap_takeover": takeover,
            "bootstrap_execution": bootstrap_execution,
        }
        if isinstance(record_path, Path):
            record_path.write_text(json.dumps(updated_node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["bootstrap_execution"] = bootstrap_execution
    recovery_action = "observe" if status == "ok" else action
    recovery_endpoint = "/api/nodes/recovery-transcript" if status == "ok" else "/api/nodes/bootstrap-execute"
    result["recovery_hint"] = {
        "action": recovery_action,
        "reason": reason,
        "evidence_refs": [evidence_path_value],
        "next_endpoint": recovery_endpoint,
        "next_method": "GET" if status == "ok" else "POST",
        "next_requires_arm": status != "ok",
    }
    return result


def heartbeat_repair_node(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    require_phone_admin(payload)
    gate = command_gate("nodes.remote.repair", root=root)
    if not gate.get("allowed"):
        return {
            "status": "blocked",
            "execution_enabled": False,
            "repair_action": "wait_for_approval",
            "repair_action_reason": str(gate.get("reason") or "phone_control_disarmed"),
            "reason": str(gate.get("reason") or "phone_control_disarmed"),
            "gate": gate,
        }
    target = str(payload.get("ssh_target") or payload.get("target") or "").strip()
    if not target:
        raise ValueError("ssh_target is required")
    controller_url = str(payload.get("controller_url") or "http://127.0.0.1:8787")
    remote_dir = str(payload.get("remote_dir") or "~/a9-worker")
    worker_name = str(payload.get("worker_name") or payload.get("node_id") or "")
    mod = remote()
    args = type(
        "HeartbeatRepairArgs",
        (),
        {
            "controller_url": controller_url,
            "worker_name": worker_name,
        },
    )()
    script = mod.heartbeat_loop_script(args)
    quoted_remote_dir = remote_shell_path(remote_dir)
    command_text = "\n".join(
        [
            "set -eu",
            f"REMOTE_DIR={quoted_remote_dir}",
            f"CONTROLLER_URL={shlex.quote(controller_url)}",
            f"WORKER_NAME={shlex.quote(worker_name)}",
            'mkdir -p "$REMOTE_DIR/.a9/remote-node"',
            'cat > "$REMOTE_DIR/.a9/remote-node/config.json" <<EOF',
            "{",
            '  "controller_url": "$CONTROLLER_URL",',
            '  "worker_name": "$WORKER_NAME",',
            '  "installed_at": "' + utc_now() + '"',
            "}",
            "EOF",
            'cat > "$REMOTE_DIR/.a9/remote-node/heartbeat.sh" <<\'EOF\'',
            script,
            "EOF",
            'chmod +x "$REMOTE_DIR/.a9/remote-node/heartbeat.sh"',
            'printf "A9 heartbeat repaired: %s -> %s\\n" "$REMOTE_DIR" "$CONTROLLER_URL"',
        ]
    )
    connect_timeout = int(payload.get("connect_timeout") or 5)
    identity_file = str(payload.get("identity_file") or default_identity_file())
    command = ssh_remote_command(target, command_text, connect_timeout=connect_timeout, identity_file=identity_file)
    timed_out = False
    try:
        proc = subprocess.run(
            command,
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
    action = "retry" if status == "timeout" else "continue" if status == "ok" else "repair"
    reason = "heartbeat_repair_timeout" if status == "timeout" else "heartbeat_repair_ok" if status == "ok" else "heartbeat_repair_failed"
    result = {
        "status": status,
        "transport": "tailscale+ssh+heartbeat-repair",
        "transport_quality": transport_quality(target),
        "node_id": safe_node_id(str(payload.get("node_id") or target)),
        "target": target,
        "controller_url": controller_url,
        "remote_dir": remote_dir,
        "worker_name": worker_name,
        "executed_at": utc_now(),
        "return_code": return_code,
        "timed_out": timed_out,
        "output": compact_text(output, 4000),
        "repair_action": action,
        "repair_action_reason": reason,
        "reason": reason,
        "gate": gate,
        "command_preview": [*command[:-1], "<heartbeat_repair_script>"],
    }
    evidence_path = write_node_evidence("heartbeat-repair", str(result.get("node_id") or target or "node"), result, root=root)
    return {**result, "evidence_path": str(evidence_path)}


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
    quoted_remote_dir = remote_shell_path(remote_dir)
    quoted_session = shlex.quote(session)
    quoted_heartbeat_script = remote_shell_path(heartbeat_script)
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


def runtime_control_state(root: Path = ROOT) -> dict[str, Any]:
    path = root / RUNTIME_CONTROL_STATE_REL_PATH
    if not path.exists():
        return {
            "schema": "a9.runtime_control_state.v1",
            "status": "running",
            "paused": False,
            "path": str(path),
            "source": "default",
        }
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return {
            "schema": "a9.runtime_control_state.v1",
            "status": "unknown",
            "paused": False,
            "path": str(path),
            "source": "unreadable",
        }
    if not isinstance(payload, dict):
        payload = {}
    return {
        "schema": payload.get("schema") or "a9.runtime_control_state.v1",
        "status": payload.get("status") or ("paused" if payload.get("paused") else "running"),
        "paused": bool(payload.get("paused")),
        "reason": payload.get("reason", ""),
        "updated_at": payload.get("updated_at", ""),
        "last_intervention": payload.get("last_intervention", {}),
        "last_decision_action": payload.get("last_decision_action", ""),
        "last_flow_transition": payload.get("last_flow_transition", {}),
        "path": str(path),
        "source": "file",
    }


def worker_model_policy(root: Path = ROOT) -> dict[str, Any]:
    del root
    phases = [
        "reference_scan",
        "mechanism_extract",
        "vendor_import",
        "implement",
        "test",
        "repair",
        "record",
        "session_refresh",
        "session_close_reading",
    ]
    env_keys = [
        "A9_SUPERVISOR_MODEL",
        "A9_SUPERVISOR_REFERENCE_MODEL",
        "A9_SUPERVISOR_CRITICAL_MODEL",
        *[f"A9_SUPERVISOR_PHASE_MODEL_{phase.upper()}" for phase in phases],
    ]
    try:
        mod = supervisor()
        policy_state = mod.worker_model_policy_state()
        resolved = {}
        for phase in phases:
            task = mod.Task(path=Path("model-policy.md"), task_id=f"model-policy-{phase}", prompt="", phase=phase)
            model, source = mod.resolved_worker_model(task)
            resolved[phase] = {
                "model": model,
                "source": source,
                "disabled_features": mod.worker_disabled_features_for_model(model),
            }
        return {
            "status": "ok",
            "kind": "worker_model_policy",
            "schema": "a9.worker_model_policy.v1",
            "global_override_env": "A9_SUPERVISOR_MODEL",
            "critical_model_env": "A9_SUPERVISOR_CRITICAL_MODEL",
            "reference_model_env": "A9_SUPERVISOR_REFERENCE_MODEL",
            "phase_model_env_prefix": "A9_SUPERVISOR_PHASE_MODEL_",
            "configured_env": {key: os.getenv(key, "") for key in env_keys if os.getenv(key, "")},
            "policy_state": policy_state,
            "policy_path": str(mod.WORKER_MODEL_POLICY_PATH),
            "resolved": resolved,
        }
    except Exception as exc:
        return {
            "status": "error",
            "kind": "worker_model_policy",
            "schema": "a9.worker_model_policy.v1",
            "error": compact_text(str(exc), 1000),
        }


def worker_transport_policy(root: Path = ROOT) -> dict[str, Any]:
    del root
    try:
        mod = supervisor()
        task = mod.Task(path=Path("transport-policy.md"), task_id="transport-policy", prompt="", phase="record")
        resolved = mod.resolved_worker_transport(task)
        return {
            "status": "ok",
            "kind": "worker_transport_policy",
            "schema": "a9.worker_transport_policy.v1",
            "backend_env": "A9_SUPERVISOR_WORKER_TRANSPORT_BACKEND",
            "custom_command_env": "A9_SUPERVISOR_WORKER_CMD",
            "custom_command_template_env": "A9_SUPERVISOR_WORKER_CMD_TEMPLATE",
            "configured_env": {
                key: os.getenv(key, "")
                for key in [
                    "A9_SUPERVISOR_WORKER_TRANSPORT_BACKEND",
                    "A9_SUPERVISOR_WORKER_CMD",
                    "A9_SUPERVISOR_WORKER_CMD_TEMPLATE",
                ]
                if os.getenv(key, "")
            },
            "policy_state": mod.worker_transport_policy_state(),
            "policy_path": str(mod.WORKER_TRANSPORT_POLICY_PATH),
            "resolved": resolved,
        }
    except Exception as exc:
        return {
            "status": "error",
            "kind": "worker_transport_policy",
            "schema": "a9.worker_transport_policy.v1",
            "error": compact_text(str(exc), 1000),
        }


def worker_transport_presets(root: Path = ROOT) -> dict[str, Any]:
    del root
    openai_worker = ROOT / "scripts" / "a9_openai_compatible_worker.py"
    local_worker = ROOT / "scripts" / "a9_local_envelope_worker.py"
    return {
        "status": "ok",
        "kind": "worker_transport_presets",
        "schema": "a9.worker_transport_presets.v1",
        "presets": [
            {
                "name": "codex_exec",
                "backend": "codex_exec",
                "description": "Default Codex exec worker transport.",
                "requires": [],
                "custom_command_template": "",
            },
            {
                "name": "local_envelope_smoke",
                "backend": "custom_command",
                "description": "Deterministic no-edit strict-envelope smoke worker.",
                "requires": [],
                "custom_command_template": (
                    f"python3 {local_worker} --prompt-file {{prompt_file}} --final-path {{final_path}} "
                    "--task-id {task_id} --phase {phase}"
                ),
            },
            {
                "name": "openai_compatible",
                "backend": "custom_command",
                "description": "OpenAI-compatible LLM worker for OpenAI, vLLM, SGLang, NIM, or A9 model gateway.",
                "requires": ["A9_LLM_WORKER_API_KEY or OPENAI_API_KEY", "A9_LLM_WORKER_MODEL"],
                "custom_command_template": (
                    f"python3 {openai_worker} --prompt-file {{prompt_file}} --final-path {{final_path}} "
                    "--task-id {task_id} --phase {phase}"
                ),
            },
        ],
    }


def worker_transport_preset_by_name(name: str) -> dict[str, Any] | None:
    normalized = str(name or "").strip()
    if not normalized:
        return None
    for preset in worker_transport_presets().get("presets", []):
        if str(preset.get("name") or "") == normalized:
            return preset
    return None


def worker_transport_rollback_payload(policy_state: dict[str, Any], *, reason: str) -> dict[str, Any]:
    backend = str(policy_state.get("backend") or "").strip()
    payload: dict[str, Any] = {
        "backend": backend,
        "reason": reason,
        "operator_scopes": [PHONE_ADMIN_SCOPE],
    }
    if backend == "custom_command":
        payload["custom_command_template"] = str(policy_state.get("custom_command_template") or "")
    elif backend == "codex_exec":
        payload["preset"] = "codex_exec"
    return payload


def openai_compatible_custom_command_template(config: dict[str, Any]) -> str:
    openai_worker = ROOT / "scripts" / "a9_openai_compatible_worker.py"
    return (
        f"python3 {shlex.quote(str(openai_worker))} "
        "--prompt-file {prompt_file} --final-path {final_path} "
        "--task-id {task_id} --phase {phase} "
        f"--model {shlex.quote(str(config.get('model') or ''))} "
        f"--base-url {shlex.quote(str(config.get('base_url') or ''))} "
        f"--api-key-env {shlex.quote(str(config.get('api_key_env') or 'A9_LLM_WORKER_API_KEY'))} "
        f"--timeout-seconds {int(config.get('timeout_seconds') or 30)}"
    )


def update_worker_transport_policy(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    require_phone_admin(payload)
    command = "worker.transport.update"
    gate = command_gate(command, root=root)
    mod = supervisor()
    before = mod.worker_transport_policy_state()
    if not gate.get("allowed"):
        event = {
            "at": utc_now(),
            "kind": "worker_transport_policy_audit",
            "schema": "a9.worker_transport_policy_update.v1",
            "command": command,
            "status": "blocked",
            "reason": str(gate.get("reason") or "phone_control_disarmed"),
            "gate_allowed": False,
            "gate_reason": gate.get("reason"),
            "before": before,
            "actor": str(payload.get("actor") or "mobile-operator"),
        }
        enqueue_monitor_intervention_audit(event, root=root)
        return {
            "status": "blocked",
            "kind": "worker_transport_policy_update",
            "schema": "a9.worker_transport_policy_update.v1",
            "command": command,
            "gate": gate,
            "before": before,
            "rollback_payload": worker_transport_rollback_payload(before, reason="rollback blocked worker transport update"),
            "audit_async": True,
        }

    preset_name = str(payload.get("preset") or "").strip()
    preset = worker_transport_preset_by_name(preset_name) if preset_name else None
    if preset_name and not preset:
        raise ValueError("unknown worker transport preset: " + preset_name)
    backend = str(payload.get("backend") or (preset or {}).get("backend") or before.get("backend") or "").strip()
    if payload.get("custom_command_template") is not None:
        custom_command_template = str(payload.get("custom_command_template") or "")
    elif preset is not None:
        custom_command_template = str(preset.get("custom_command_template") or "")
    else:
        custom_command_template = str(before.get("custom_command_template") or "")
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValueError("reason is required")
    if backend not in {"codex_exec", "custom_command"}:
        raise ValueError("backend must be one of: codex_exec, custom_command")
    if backend == "custom_command" and not custom_command_template.strip():
        raise ValueError("custom_command_template is required for custom_command backend")
    probe: dict[str, Any] = {}
    config: dict[str, Any] = {}
    if preset_name == "openai_compatible":
        config = openai_compatible_worker_config(payload, root=root)
        if config.get("model") and config.get("base_url") and config.get("api_key_env"):
            custom_command_template = openai_compatible_custom_command_template(config)
    if bool(payload.get("require_probe_pass")):
        if preset_name != "openai_compatible":
            raise ValueError("require_probe_pass is only supported for preset=openai_compatible")
        config = config or openai_compatible_worker_config(payload, root=root)
        if config.get("missing"):
            return {
                "status": "not_configured",
                "kind": "worker_transport_policy_update",
                "schema": "a9.worker_transport_policy_update.v1",
                "command": command,
                "gate": gate,
                "before": before,
                "preset": preset_name,
                "config": config,
                "rollback_payload": worker_transport_rollback_payload(before, reason="rollback failed worker transport update"),
                "reason": "missing required OpenAI-compatible worker configuration",
                "audit_async": False,
            }
        probe = run_openai_compatible_worker_probe(config)
        if probe.get("status") != "pass":
            event = {
                "at": utc_now(),
                "kind": "worker_transport_policy_audit",
                "schema": "a9.worker_transport_policy_update.v1",
                "command": command,
                "status": "probe_failed",
                "reason": "required OpenAI-compatible worker probe failed; policy unchanged",
                "gate_allowed": True,
                "gate_reason": gate.get("reason"),
                "before": before,
                "preset": preset_name,
                "probe": probe,
                "actor": str(payload.get("actor") or "mobile-operator"),
            }
            enqueue_monitor_intervention_audit(event, root=root)
            return {
                "status": "probe_failed",
                "kind": "worker_transport_policy_update",
                "schema": "a9.worker_transport_policy_update.v1",
                "command": command,
                "gate": gate,
                "before": before,
                "preset": preset_name,
                "probe": probe,
                "rollback_payload": worker_transport_rollback_payload(before, reason="rollback failed worker transport update"),
                "reason": "required OpenAI-compatible worker probe failed; policy unchanged",
                "audit_async": True,
            }

    after = mod.write_worker_transport_policy(
        backend=backend,
        custom_command_template=custom_command_template,
        reason=reason,
    )
    task = mod.Task(path=Path("transport-policy.md"), task_id="transport-policy", prompt="", phase="record")
    resolved = mod.resolved_worker_transport(task)
    event = {
        "at": utc_now(),
        "kind": "worker_transport_policy_audit",
        "schema": "a9.worker_transport_policy_update.v1",
        "command": command,
        "status": "applied",
        "reason": reason,
        "gate_allowed": True,
        "gate_reason": gate.get("reason"),
        "before": before,
        "after": after,
        "resolved": resolved,
        "preset": preset_name,
        "probe": probe,
        "rollback_payload": worker_transport_rollback_payload(before, reason="rollback worker transport update"),
        "actor": str(payload.get("actor") or "mobile-operator"),
    }
    enqueue_monitor_intervention_audit(event, root=root)
    return {
        "status": "applied",
        "kind": "worker_transport_policy_update",
        "schema": "a9.worker_transport_policy_update.v1",
        "command": command,
        "gate": gate,
        "before": before,
        "after": after,
        "resolved": resolved,
        "preset": preset_name,
        "probe": probe,
        "rollback_payload": worker_transport_rollback_payload(before, reason="rollback worker transport update"),
        "policy_path": str(mod.WORKER_TRANSPORT_POLICY_PATH),
        "audit_async": True,
    }


def llm_worker_config_state(root: Path = ROOT) -> dict[str, Any]:
    path = root / LLM_WORKER_CONFIG_REL_PATH
    data = read_json(path) if path.exists() else {}
    if not isinstance(data, dict):
        data = {}
    timeout_raw = data.get("timeout_seconds", data.get("timeout"))
    if isinstance(timeout_raw, (int, float)):
        timeout_seconds = max(0, int(timeout_raw))
    else:
        timeout_seconds = parse_duration_seconds(timeout_raw, default_seconds=0) if timeout_raw not in (None, "") else 0
    return {
        "schema": data.get("schema") or "a9.llm_worker_config.v1",
        "model": str(data.get("model") or ""),
        "base_url": str(data.get("base_url") or ""),
        "api_key_env": str(data.get("api_key_env") or ""),
        "timeout_seconds": timeout_seconds,
        "updated_at": str(data.get("updated_at") or ""),
        "last_update": data.get("last_update", {}) if isinstance(data.get("last_update"), dict) else {},
        "path": str(path),
    }


def update_llm_worker_config(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    require_phone_admin(payload)
    command = "worker.transport.config.update"
    gate = command_gate(command, root=root)
    before = llm_worker_config_state(root)
    if not gate.get("allowed"):
        return {
            "status": "blocked",
            "kind": "llm_worker_config_update",
            "schema": "a9.llm_worker_config_update.v1",
            "command": command,
            "gate": gate,
            "before": before,
        }
    model = str(payload.get("model") or before.get("model") or "").strip()
    base_url = str(payload.get("base_url") or before.get("base_url") or "").strip()
    api_key_env = str(payload.get("api_key_env") or before.get("api_key_env") or "A9_LLM_WORKER_API_KEY").strip()
    timeout_raw = payload.get("timeout_seconds", payload.get("timeout", before.get("timeout_seconds") or 30))
    timeout_seconds = max(1, int(timeout_raw)) if isinstance(timeout_raw, (int, float)) else parse_duration_seconds(timeout_raw, default_seconds=30)
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValueError("reason is required")
    if not model:
        raise ValueError("model is required")
    if not base_url:
        raise ValueError("base_url is required")
    if not api_key_env:
        raise ValueError("api_key_env is required")
    path = root / LLM_WORKER_CONFIG_REL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    after = {
        "schema": "a9.llm_worker_config.v1",
        "model": model,
        "base_url": base_url,
        "api_key_env": api_key_env,
        "timeout_seconds": timeout_seconds,
        "updated_at": utc_now(),
        "last_update": {
            "kind": "llm_worker_config_update",
            "reason": reason,
            "updated_at": utc_now(),
        },
    }
    path.write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "applied",
        "kind": "llm_worker_config_update",
        "schema": "a9.llm_worker_config_update.v1",
        "command": command,
        "gate": gate,
        "before": before,
        "after": llm_worker_config_state(root),
        "path": str(path),
    }


def openai_compatible_worker_config(payload: dict[str, Any] | None = None, *, root: Path = ROOT) -> dict[str, Any]:
    payload = payload or {}
    state = llm_worker_config_state(root)
    api_key_env = str(payload.get("api_key_env") or os.getenv("A9_LLM_WORKER_API_KEY_ENV") or state.get("api_key_env") or "A9_LLM_WORKER_API_KEY").strip()
    model = str(payload.get("model") or os.getenv("A9_LLM_WORKER_MODEL") or state.get("model") or "").strip()
    base_url = str(payload.get("base_url") or os.getenv("A9_LLM_WORKER_BASE_URL") or state.get("base_url") or "https://api.openai.com/v1").strip()
    timeout_raw = payload.get("timeout", payload.get("timeout_seconds"))
    if isinstance(timeout_raw, (int, float)):
        timeout_seconds = max(1, int(timeout_raw))
    elif timeout_raw not in (None, ""):
        timeout_seconds = parse_duration_seconds(timeout_raw, default_seconds=30)
    elif os.getenv("A9_LLM_WORKER_TIMEOUT", "").strip():
        timeout_seconds = parse_duration_seconds(os.getenv("A9_LLM_WORKER_TIMEOUT"), default_seconds=30)
    elif int(state.get("timeout_seconds") or 0) > 0:
        timeout_seconds = int(state.get("timeout_seconds") or 0)
    else:
        timeout_seconds = 30
    key_available = bool(os.getenv(api_key_env) or os.getenv("OPENAI_API_KEY"))
    missing = []
    if not key_available:
        missing.append(f"{api_key_env} or OPENAI_API_KEY")
    if not model:
        missing.append("A9_LLM_WORKER_MODEL or payload.model")
    if not base_url:
        missing.append("A9_LLM_WORKER_BASE_URL or payload.base_url")
    return {
        "api_key_env": api_key_env,
        "api_key_available": key_available,
        "model": model,
        "base_url": base_url,
        "timeout_seconds": timeout_seconds,
        "config_state": state,
        "missing": missing,
    }


def run_openai_compatible_worker_probe(config: dict[str, Any]) -> dict[str, Any]:
    worker_path = ROOT / "scripts" / "a9_openai_compatible_worker.py"
    with tempfile.TemporaryDirectory(prefix="a9-worker-probe-") as tmp:
        tmp_path = Path(tmp)
        prompt_path = tmp_path / "prompt.md"
        final_path = tmp_path / "final.json"
        prompt_path.write_text(
            "# Task Declared Checks\n\n"
            "- none\n\n"
            "# Current Task\n\n"
            "Return a strict A9 worker envelope with no file changes. "
            "Set changed_files and search_replace_blocks to empty arrays.\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["A9_LLM_WORKER_MODEL"] = str(config.get("model") or "")
        env["A9_LLM_WORKER_BASE_URL"] = str(config.get("base_url") or "")
        cmd = [
            sys.executable,
            str(worker_path),
            "--prompt-file",
            str(prompt_path),
            "--final-path",
            str(final_path),
            "--task-id",
            "worker-transport-probe",
            "--phase",
            "record",
            "--api-key-env",
            str(config.get("api_key_env") or "A9_LLM_WORKER_API_KEY"),
            "--timeout-seconds",
            str(int(config.get("timeout_seconds") or 30)),
        ]
        started = utc_now()
        try:
            completed = subprocess.run(
                cmd,
                cwd=ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=max(1, int(config.get("timeout_seconds") or 30) + 5),
            )
            return_code = completed.returncode
            stdout_tail = compact_text(completed.stdout or "", 1000)
            stderr_tail = compact_text(completed.stderr or "", 1000)
            error = ""
        except (subprocess.TimeoutExpired, OSError) as exc:
            return_code = -1
            stdout_tail = compact_text(getattr(exc, "stdout", "") or "", 1000)
            stderr_tail = compact_text(getattr(exc, "stderr", "") or "", 1000)
            error = compact_text(str(exc), 1000)
        final_payload = read_json(final_path) if final_path.exists() else {}
        ok = return_code == 0 and bool(final_payload.get("ok"))
        return {
            "status": "pass" if ok else "fail",
            "kind": "openai_compatible_worker_probe",
            "schema": "a9.openai_compatible_worker_probe.v1",
            "started_at": started,
            "completed_at": utc_now(),
            "return_code": return_code,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "error": error,
            "final_envelope": final_payload,
            "final_path_present": final_path.exists(),
        }


def worker_transport_check(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    preset_name = str(payload.get("preset") or "openai_compatible").strip()
    preset = worker_transport_preset_by_name(preset_name)
    if not preset:
        raise ValueError("unknown worker transport preset: " + preset_name)
    execute = bool(payload.get("execute"))
    config = openai_compatible_worker_config(payload, root=root) if preset_name == "openai_compatible" else {
        "missing": [],
        "api_key_available": True,
        "model": "",
        "base_url": "",
        "timeout_seconds": 0,
    }
    gate = {"status": "not_required", "allowed": True, "reason": "configuration_check_only"}
    if execute:
        require_phone_admin(payload)
        gate = command_gate("worker.transport.check", root=root)
    status = "ready" if not config.get("missing") else "not_configured"
    result: dict[str, Any] = {
        "status": status,
        "kind": "worker_transport_check",
        "schema": "a9.worker_transport_check.v1",
        "preset": preset_name,
        "execute": execute,
        "gate": gate,
        "config": config,
        "preset_detail": preset,
        "checked_at": utc_now(),
    }
    if execute and not gate.get("allowed"):
        result["status"] = "blocked"
        result["reason"] = str(gate.get("reason") or "phone_control_disarmed")
        return result
    if execute and config.get("missing"):
        result["status"] = "not_configured"
        result["reason"] = "missing required OpenAI-compatible worker configuration"
        return result
    if execute:
        probe = run_openai_compatible_worker_probe(config) if preset_name == "openai_compatible" else {}
        result["probe"] = probe
        result["status"] = "pass" if probe.get("status") == "pass" else "probe_failed"
        result["reason"] = "live OpenAI-compatible worker probe executed"
    return result


def monitor_status(root: Path = ROOT) -> dict[str, Any]:
    status = supervisor_status(root)
    control_state = runtime_control_state(root)
    intervention_audit = monitor_intervention_audit_tail(limit=5, root=root)
    latest_run = status.get("latest_run") if isinstance(status.get("latest_run"), dict) else {}
    latest_lanes = status.get("latest_run_lanes") if isinstance(status.get("latest_run_lanes"), dict) else {}
    contract = latest_run.get("runtime_monitor_contract") if isinstance(latest_run, dict) else {}
    contract = contract if isinstance(contract, dict) else {}
    monitor = contract.get("monitor", {}) if isinstance(contract.get("monitor"), dict) else {}
    evidence_refs = contract.get("evidence_refs", {}) if isinstance(contract.get("evidence_refs"), dict) else {}
    diff_and_checks = contract.get("diff_and_checks", {}) if isinstance(contract.get("diff_and_checks"), dict) else {}
    context_pressure = latest_run.get("context_pressure") if isinstance(latest_run.get("context_pressure"), dict) else {}
    service_observation = status.get("service_observation") if isinstance(status.get("service_observation"), dict) else {}
    nodes = status.get("nodes") if isinstance(status.get("nodes"), dict) else {}
    next_action = str(monitor.get("next_action") or "")
    if not next_action:
        if latest_run.get("status") in {"needs-repair", "monitor-blocked"}:
            next_action = "repair"
        elif latest_run.get("status") == "needs-approval":
            next_action = "approve_or_reject"
        elif latest_run.get("status") == "pass":
            next_action = "continue"
        elif latest_run:
            next_action = "route_to_debate"
        else:
            next_action = "observe"
    queue_depth = int(status.get("queued") or 0)
    running_count = int(status.get("running") or 0)
    return {
        "status": "ok",
        "kind": "monitor_status",
        "schema": "a9.monitor_status.v1",
        "generated_at": utc_now(),
        "queue": {
            "queued": queue_depth,
            "running": running_count,
            "done": int(status.get("done") or 0),
            "queue_tail": status.get("queue", []),
            "running_tasks": status.get("running_tasks", []),
            "task_quality": status.get("task_quality", {}),
        },
        "latest_run": {
            "task_id": latest_run.get("task_id"),
            "run_id": contract.get("run", {}).get("run_id") if isinstance(contract.get("run"), dict) else None,
            "status": latest_run.get("status"),
            "phase": latest_run.get("phase"),
            "run_dir": latest_run.get("run_dir"),
            "summary_path": latest_run.get("summary_path"),
        },
        "latest_run_lanes": latest_lanes,
        "next_action": next_action,
        "runtime_control": control_state,
        "worker_transport_health": status.get("worker_transport_health", {}),
        "recent_interventions": intervention_audit,
        "monitor": monitor,
        "evidence_refs": evidence_refs,
        "failed_checks": diff_and_checks.get("failed_checks", []),
        "failed_checks_count": diff_and_checks.get("failed_checks_count", 0),
        "changed_files": diff_and_checks.get("changed_files", []),
        "context_pressure": {
            "prompt_approx_tokens": context_pressure.get("prompt_approx_tokens"),
            "prompt_budget_tokens": context_pressure.get("prompt_budget_tokens"),
            "budget_ratio": context_pressure.get("budget_ratio"),
            "remaining_tokens": context_pressure.get("remaining_tokens"),
            "over_budget": context_pressure.get("over_budget"),
        },
        "worker_prompt": contract.get("worker_prompt", {}),
        "worker_intent": contract.get("worker_intent", {}),
        "command_envelope": contract.get("command_envelope", {}),
        "guardrails": contract.get("guardrails", {}),
        "intervention_options": monitor.get("intervention_options", []),
        "service_observation": {
            "status": service_observation.get("status"),
            "missing_count": service_observation.get("observed", {}).get("missing_count")
            if isinstance(service_observation.get("observed"), dict)
            else None,
        },
        "nodes": {
            "status": nodes.get("status"),
            "count": nodes.get("count"),
            "online_count": nodes.get("online_count"),
            "stale_count": nodes.get("stale_count"),
        },
    }


def monitor_control(root: Path = ROOT) -> dict[str, Any]:
    status = monitor_status(root)
    examples = monitor_intervention_examples(root)
    model_policy = worker_model_policy(root)
    transport_policy = worker_transport_policy(root)
    recent = status.get("recent_interventions") if isinstance(status.get("recent_interventions"), dict) else {}
    next_last_id = ""
    events = recent.get("events") if isinstance(recent, dict) else []
    if isinstance(events, list) and events:
        next_last_id = str(events[-1].get("stream_id") or events[-1].get("redis_mirror", {}).get("stream_id") or "")
    return {
        "status": "ok",
        "kind": "monitor_control",
        "schema": "a9.monitor_control.v1",
        "generated_at": utc_now(),
        "monitor_status": status,
        "worker_model_policy": model_policy,
        "worker_transport_policy": transport_policy,
        "intervention_examples": examples,
        "intervention_stream": {
            "stream": MONITOR_INTERVENTIONS_STREAM_KEY,
            "events_endpoint": "/api/monitor/interventions/events",
            "sse_endpoint": "/api/monitor/interventions/events?format=sse",
            "recent_event_count": int(recent.get("event_count") or 0) if isinstance(recent, dict) else 0,
            "next_last_id": next_last_id,
            "reconnect_hint": "Use Last-Event-ID header or last_id query parameter.",
        },
        "actions": {
            "post_endpoint": "/api/monitor/intervention",
            "examples_endpoint": "/api/monitor/intervention/examples",
            "requires_phone_control": "runtime group with monitor.intervention",
        },
    }


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


def runtime_run_one_with_transport(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    require_phone_admin(payload)
    gate = command_gate("submit.run", root=root)
    if not gate.get("allowed"):
        return {"status": "blocked", "kind": "runtime_run_one_with_transport", "gate": gate}
    transport_payload = dict(payload.get("transport") or payload.get("worker_transport") or {})
    if not transport_payload:
        raise ValueError("transport payload is required")
    transport_payload.setdefault("operator_scopes", [PHONE_ADMIN_SCOPE])
    transport_payload.setdefault("reason", "temporary worker transport for runtime run-one")
    update = update_worker_transport_policy(transport_payload, root=root)
    if update.get("status") != "applied":
        return {
            "status": "transport-update-failed",
            "kind": "runtime_run_one_with_transport",
            "command": "submit.run",
            "gate": gate,
            "transport_update": update,
        }
    rollback_payload = dict(update.get("rollback_payload") or {})
    rollback_result: dict[str, Any] = {}
    code = 1
    try:
        mod = supervisor()
        code = mod.run_one(auto_next=bool(payload.get("auto_next", False)))
        status = "run-complete" if code == 0 else "run-failed"
    finally:
        if rollback_payload:
            rollback_payload["operator_scopes"] = [PHONE_ADMIN_SCOPE]
            rollback_result = update_worker_transport_policy(rollback_payload, root=root)
    return {
        "status": status,
        "kind": "runtime_run_one_with_transport",
        "command": "submit.run",
        "run_return_code": code,
        "gate": gate,
        "transport_update": update,
        "rollback": rollback_result,
        "latest_run": compact_summary(latest_run_summary(root)),
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
            "close_reading_doc: docs/session.md",
            "summary_doc: docs/session.md",
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


def audit_session_lane_latest(result: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    enqueue_service_control_audit(
        {
            "at": utc_now(),
            "action": "session_lane_latest",
            "command": result.get("command", "session.lane.latest"),
            "status": result.get("status"),
            "source_session_path": result.get("source_session_path", ""),
            "from_turn": result.get("from_turn"),
            "to_turn": result.get("to_turn"),
            "queued_task_path": result.get("queued_task_path", ""),
            "reason": result.get("reason") or result.get("blocked_reason"),
        },
        root=root,
    )
    result["audit_async"] = True
    return result


def runtime_session_lane_latest(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    command = "session.lane.latest"
    base = {"command": command, "called_model": False, "called_worker": False}
    try:
        require_phone_admin(payload)
    except PermissionError as exc:
        return audit_session_lane_latest({**base, "status": "blocked", "blocked_reason": str(exc)}, root=root)
    gate = command_gate(command, root=root)
    if not gate.get("allowed"):
        return audit_session_lane_latest({**base, "status": "blocked", "gate": gate}, root=root)
    mod = supervisor()
    try:
        tail_turns = max(1, int(payload.get("tail_turns", 1)))
        batch_size = max(1, int(payload.get("batch_size", 1)))
        timeout_seconds = int(payload.get("timeout_seconds", 120))
        idle_timeout_seconds = int(payload.get("idle_timeout_seconds", 120))
    except (TypeError, ValueError):
        return audit_session_lane_latest(
            {**base, "status": "invalid_request", "gate": gate, "reason": "numeric_fields_must_be_integer"},
            root=root,
        )
    session_path_text = str(payload.get("session_path") or "").strip()
    try:
        session_path = Path(session_path_text) if session_path_text else mod.latest_codex_session_path()
        if not session_path.is_absolute():
            session_path = root / session_path
        tail = mod.latest_session_tail_range(session_path, tail_turns=tail_turns, batch_size=batch_size)
    except (FileNotFoundError, ValueError, OSError) as exc:
        return audit_session_lane_latest(
            {**base, "status": "missing-session", "gate": gate, "reason": str(exc), "source_session_path": session_path_text},
            root=root,
        )
    task_id = str(payload.get("task_id") or "").strip() or (
        f"mobile-session-lane-latest-{tail.get('session_id') or mod.compact_task_ref(session_path.stem)}-"
        f"{tail['from_turn']}-{tail['to_turn']}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    auto_continue = bool(payload.get("auto_continue", False))
    auto_close_reading = not bool(payload.get("no_auto_close_reading", False))
    close_doc = str(payload.get("close_reading_doc") or "docs/session.md")
    summary_doc = str(payload.get("summary_doc") or "docs/session.md")
    prompt = "\n".join(
        [
            f"source_session_path: {tail['source_session_path']}",
            f"from_turn: {tail['from_turn']}",
            f"to_turn: {tail['to_turn']}",
            f"batch_size: {tail['batch_size']}",
            f"auto_continue: {str(auto_continue).lower()}",
            f"auto_close_reading: {str(auto_close_reading).lower()}",
            f"close_reading_doc: {close_doc}",
            f"summary_doc: {summary_doc}",
            "",
            "Mobile runtime action: enqueue the deterministic latest external operator session lane. "
            "Do not call a model, do not run a worker, and do not enter the copy-project pipeline.",
        ]
    )
    queue_path = mod.enqueue_task_file(
        task_id,
        prompt,
        phase=mod.SESSION_REFRESH_PHASE,
        checks=[],
        timeout_seconds=timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        max_attempts=1,
        allowed_paths=[],
        auto_next=True,
    )
    return audit_session_lane_latest(
        {
            **base,
            "status": "enqueued",
            "gate": gate,
            "task_id": Path(queue_path).stem,
            "queued_task_path": str(queue_path),
            "source_session_path": str(tail["source_session_path"]),
            "session_id": tail.get("session_id", ""),
            "from_turn": tail["from_turn"],
            "to_turn": tail["to_turn"],
            "user_turn_count": tail["user_turn_count"],
            "auto_continue": auto_continue,
            "auto_close_reading": auto_close_reading,
        },
        root=root,
    )


def mempalace_status() -> dict[str, Any]:
    provider = mempalace_provider()
    return {
        "schema": "a9.control_api.mempalace_status.v1",
        "native_mempalace": provider.native_status(),
        "fallback_drawers": provider.drawer_status(provider.DEFAULT_DRAWERS),
    }


def _mempalace_limit(payload: dict[str, Any], *, default: int, maximum: int) -> int:
    try:
        value = int(payload.get("limit") or default)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be integer") from exc
    return max(1, min(value, maximum))


def mempalace_search(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    if not query:
        return {
            "schema": "a9.control_api.mempalace_search.v1",
            "status": "invalid_request",
            "error": "query_required",
            "truth_policy": "recall_not_truth",
            "results": [],
        }
    provider = mempalace_provider()
    drawers = Path(str(payload.get("drawers") or provider.DEFAULT_DRAWERS))
    limit = _mempalace_limit(payload, default=8, maximum=50)
    native_mode = str(payload.get("native_mode") or "auto")
    native = None
    if native_mode in {"auto", "native"} and hasattr(provider, "native_search"):
        native = provider.native_search(
            query,
            limit=limit,
            wing=payload.get("wing") or "operator-codex",
            room=payload.get("room"),
        )
        if native and native.get("status") == "ok":
            return {
                "schema": "a9.control_api.mempalace_search.v1",
                "status": "ok",
                "query": query,
                "truth_policy": "recall_not_truth",
                **native,
            }
    if native_mode == "native":
        return {
            "schema": "a9.control_api.mempalace_search.v1",
            "status": "error",
            "query": query,
            "truth_policy": "recall_not_truth",
            "source": "native_mempalace",
            "error": (native or {}).get("error") if native else "native palace index unavailable",
            "results": [],
        }
    return {
        "schema": "a9.control_api.mempalace_search.v1",
        "status": "ok",
        "query": query,
        "truth_policy": "recall_not_truth",
        "source": "mempalace-compatible-drawer-jsonl",
        "native_fallback_reason": None if not native else native.get("error"),
        "results": provider.search_drawers(
            drawers,
            query,
            limit=limit,
            role=payload.get("role"),
            event_kind=payload.get("event_kind"),
        ),
    }


def mempalace_wakeup(payload: dict[str, Any]) -> dict[str, Any]:
    provider = mempalace_provider()
    drawers = Path(str(payload.get("drawers") or provider.DEFAULT_DRAWERS))
    query = str(payload.get("query") or "A9 MemPalace current mainline next action")
    pack = provider.build_wakeup(
        drawers,
        query=query,
        limit=_mempalace_limit(payload, default=8, maximum=20),
    )
    pack["schema"] = "a9.control_api.mempalace_wakeup.v1"
    pack["status"] = "ok"
    return pack


def audit_plan_backlog_next(result: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    enqueue_service_control_audit(
        {
            "at": utc_now(),
            "action": "plan_backlog_next",
            "command": result.get("command", "plan.backlog.next"),
            "status": result.get("status"),
            "plan_id": result.get("plan_id"),
            "reason": result.get("reason") or result.get("blocked_reason"),
            "runtime_state": result.get("runtime_state"),
            "runtime_state_reason": result.get("runtime_state_reason"),
            "queued_count": result.get("queued_count"),
            "queued_task_paths": result.get("queued_task_paths", []),
        },
        root=root,
    )
    result["audit_async"] = True
    return result


def audit_plan_debate_next(result: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    enqueue_service_control_audit(
        {
            "at": utc_now(),
            "action": "plan_debate_next",
            "command": result.get("command", "plan.debate.next"),
            "status": result.get("status"),
            "plan_id": result.get("plan_id"),
            "debate_status": result.get("requirements_debate_status"),
            "debate_stage": result.get("requirements_debate_current_stage"),
            "reason": result.get("reason") or result.get("blocked_reason"),
            "runtime_state": result.get("runtime_state"),
            "runtime_state_reason": result.get("runtime_state_reason"),
            "queued_task_path": result.get("queued_task_path"),
        },
        root=root,
    )
    result["audit_async"] = True
    return result


def runtime_plan_debate_next(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    command = "plan.debate.next"
    mod = supervisor()
    status = supervisor_status(root)
    runtime_state, runtime_state_reason = mod.runtime_state_from_summary(
        int(status.get("queued") or 0),
        int(status.get("running") or 0),
        latest_run_summary(root),
    )
    base = {
        "command": command,
        "runtime_state": runtime_state,
        "runtime_state_reason": runtime_state_reason,
    }
    try:
        require_phone_admin(payload)
    except PermissionError as exc:
        return audit_plan_debate_next({**base, "status": "blocked", "blocked_reason": str(exc)}, root=root)
    gate = command_gate(command, root=root)
    if not gate.get("allowed"):
        return audit_plan_debate_next({**base, "status": "blocked", "gate": gate}, root=root)

    plan_id = str(payload.get("plan_id") or "").strip() or str(mod.active_plan_id() or "").strip()
    if not plan_id:
        return audit_plan_debate_next({**base, "status": "missing_plan", "gate": gate, "reason": "active_plan_missing"}, root=root)
    plan = mod.load_plan(plan_id)
    if not isinstance(plan, dict):
        return audit_plan_debate_next(
            {**base, "status": "missing_plan", "plan_id": plan_id, "gate": gate, "reason": "plan_not_found"},
            root=root,
        )
    try:
        timeout_seconds = int(payload.get("timeout_seconds", 3600))
        idle_timeout_seconds = int(payload.get("idle_timeout_seconds", 300))
    except (TypeError, ValueError):
        return audit_plan_debate_next(
            {**base, "status": "invalid_request", "plan_id": plan_id, "gate": gate, "reason": "numeric_fields_must_be_integer"},
            root=root,
        )
    auto_next_raw = payload.get("auto_next", False)
    auto_next = auto_next_raw if isinstance(auto_next_raw, bool) else str(auto_next_raw).lower() not in {"0", "false", "off", "no"}
    path, debate = mod.enqueue_plan_debate_task(
        plan,
        stage_id=str(payload.get("stage") or "").strip(),
        task_id=str(payload.get("task_id") or "").strip(),
        extra=str(payload.get("extra") or "").strip(),
        phase=str(payload.get("phase") or "reference_scan").strip() or "reference_scan",
        timeout_seconds=timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        auto_next=auto_next,
    )
    return audit_plan_debate_next(
        {
            **base,
            "status": "enqueued",
            "plan_id": plan_id,
            "gate": gate,
            "queued_task_path": str(path),
            "requirements_debate_status": debate.get("status"),
            "requirements_debate_current_stage": debate.get("current_stage"),
            "auto_next": auto_next,
        },
        root=root,
    )


def audit_plan_decision_approve(result: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    enqueue_service_control_audit(
        {
            "at": utc_now(),
            "action": "plan_decision_approve",
            "command": result.get("command", "plan.decision.approve"),
            "status": result.get("status"),
            "plan_id": result.get("plan_id"),
            "reason": result.get("reason") or result.get("blocked_reason"),
            "approved_count": result.get("approved_count"),
            "source_run": result.get("source_run"),
        },
        root=root,
    )
    result["audit_async"] = True
    return result


def runtime_plan_decision_approve(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    command = "plan.decision.approve"
    mod = supervisor()
    base = {"command": command}
    try:
        require_phone_admin(payload)
    except PermissionError as exc:
        return audit_plan_decision_approve({**base, "status": "blocked", "blocked_reason": str(exc)}, root=root)
    gate = command_gate(command, root=root)
    if not gate.get("allowed"):
        return audit_plan_decision_approve({**base, "status": "blocked", "gate": gate}, root=root)
    evidence_refs = payload.get("evidence_refs", [])
    if isinstance(evidence_refs, str):
        evidence_refs = [evidence_refs]
    if not isinstance(evidence_refs, list):
        evidence_refs = []
    item_ids = payload.get("item_ids", [])
    if isinstance(item_ids, str):
        item_ids = [item_ids]
    if not isinstance(item_ids, list):
        item_ids = []
    item_ids = [str(item).strip() for item in item_ids if str(item).strip()]
    allow_all = bool(payload.get("allow_all"))
    if not item_ids and not allow_all:
        return audit_plan_decision_approve(
            {
                **base,
                "status": "invalid_request",
                "gate": gate,
                "reason": "item_ids_required",
                "hint": "pass explicit item_ids or allow_all=true after review",
            },
            root=root,
        )
    plan_id = str(payload.get("plan_id") or "").strip() or str(mod.active_plan_id() or "").strip()
    result = mod.approve_plan_decision_backlog(
        plan_id=plan_id,
        source_run=str(payload.get("source_run") or "").strip(),
        item_ids=item_ids,
        reason=str(payload.get("reason") or "").strip(),
        actor=str(payload.get("actor") or "mobile-operator").strip(),
        evidence_refs=[str(item) for item in evidence_refs],
    )
    return audit_plan_decision_approve({**base, "gate": gate, **result}, root=root)


def runtime_plan_backlog_next(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    command = "plan.backlog.next"
    mod = supervisor()
    status = supervisor_status(root)
    runtime_state, runtime_state_reason = mod.runtime_state_from_summary(
        int(status.get("queued") or 0),
        int(status.get("running") or 0),
        latest_run_summary(root),
    )
    base = {
        "command": command,
        "runtime_state": runtime_state,
        "runtime_state_reason": runtime_state_reason,
    }
    try:
        require_phone_admin(payload)
    except PermissionError as exc:
        return audit_plan_backlog_next({**base, "status": "blocked", "blocked_reason": str(exc)}, root=root)
    gate = command_gate(command, root=root)
    if not gate.get("allowed"):
        return audit_plan_backlog_next({**base, "status": "blocked", "gate": gate}, root=root)

    plan_id = str(payload.get("plan_id") or "").strip() or str(mod.active_plan_id() or "").strip()
    if not plan_id:
        return audit_plan_backlog_next({**base, "status": "missing_plan", "gate": gate, "reason": "active_plan_missing"}, root=root)
    plan = mod.load_plan(plan_id)
    if not isinstance(plan, dict):
        return audit_plan_backlog_next(
            {**base, "status": "missing_plan", "plan_id": plan_id, "gate": gate, "reason": "plan_not_found"},
            root=root,
        )
    try:
        count = max(0, int(payload.get("count", 1)))
        timeout_seconds = int(payload.get("timeout_seconds", 3600))
        idle_timeout_seconds = int(payload.get("idle_timeout_seconds", 300))
    except (TypeError, ValueError):
        return audit_plan_backlog_next(
            {**base, "status": "invalid_request", "plan_id": plan_id, "gate": gate, "reason": "numeric_fields_must_be_integer"},
            root=root,
        )
    auto_next_raw = payload.get("auto_next", True)
    auto_next = auto_next_raw if isinstance(auto_next_raw, bool) else str(auto_next_raw).lower() not in {"0", "false", "off", "no"}
    items = mod.plan_execution_backlog_items(plan, count=count)
    if not items:
        return audit_plan_backlog_next(
            {
                **base,
                "status": "no_items",
                "plan_id": plan_id,
                "gate": gate,
                "queued_count": 0,
                "queued_task_paths": [],
            },
            root=root,
        )
    created = mod.enqueue_execution_backlog_items(
        plan,
        items,
        prefix=str(payload.get("prefix") or ""),
        timeout_seconds=timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        auto_next=auto_next,
    )
    queued_paths = [str(path) for path in created]
    return audit_plan_backlog_next(
        {
            **base,
            "status": "enqueued",
            "plan_id": plan_id,
            "gate": gate,
            "requested_count": count,
            "queued_count": len(queued_paths),
            "queued_task_paths": queued_paths,
            "auto_next": auto_next,
        },
        root=root,
    )


def service_start_action(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    try:
        require_phone_admin(payload)
    except PermissionError as exc:
        observation = service_observation_status(root)
        missing_services = [str(item) for item in observation.get("observed", {}).get("missing_services", [])]
        result = {
            "status": "blocked",
            "command": "services.start",
            "blocked_reason": str(exc),
            "missing_services": missing_services,
            "service_observation": observation,
        }
        audit_event = build_service_control_audit_event(
            "start",
            "services.start",
            "blocked",
            reason=str(exc),
            target_services=missing_services,
            payload=payload,
            service_observation=observation,
        )
        enqueue_service_control_audit(audit_event, root=root)
        result["audit_async"] = True
        return result
    gate = command_gate("services.start", root=root)
    observation = service_observation_status(root)
    missing_services = [str(item) for item in observation.get("observed", {}).get("missing_services", [])]
    if not gate.get("allowed"):
        result = {
            "status": "blocked",
            "command": "services.start",
            "gate": gate,
            "blocked_reason": str(gate.get("reason") or "phone_control_disarmed"),
            "missing_services": missing_services,
            "service_observation": observation,
        }
        audit_event = build_service_control_audit_event(
            "start",
            "services.start",
            "blocked",
            reason=str(gate.get("reason") or "phone_control_disarmed"),
            gate=gate,
            target_services=missing_services,
            payload=payload,
            service_observation=observation,
        )
        enqueue_service_control_audit(audit_event, root=root)
        result["audit_async"] = True
        return result

    requested_raw = payload.get("services", payload.get("missing_services", []))
    requested_services = [str(item).strip() for item in requested_raw] if isinstance(requested_raw, list) else []
    requested_services = [item for item in requested_services if item]
    if requested_services:
        unknown = sorted({item for item in requested_services if item not in SERVICE_PROCESS_MARKERS})
        if unknown:
            result = {
                "status": "invalid_request",
                "command": "services.start",
                "gate": gate,
                "reason": "unknown_service",
                "unknown_services": unknown,
                "known_services": sorted(SERVICE_PROCESS_MARKERS),
                "missing_services": missing_services,
                "service_observation": observation,
            }
            audit_event = build_service_control_audit_event(
                "start",
                "services.start",
                "invalid_request",
                reason="unknown_service",
                requested_services=requested_services,
                gate=gate,
                target_services=[],
                payload=payload,
                service_observation=observation,
            )
            enqueue_service_control_audit(audit_event, root=root)
            result["audit_async"] = True
            return result
        target_services = [item for item in requested_services if item in missing_services]
    else:
        target_services = missing_services
    if not target_services:
        return {
            "status": "noop",
            "command": "services.start",
            "gate": gate,
            "reason": "no_missing_services",
            "missing_services": missing_services,
            "requested_services": requested_services,
            "service_observation": observation,
        }

    cmd = ["python3", str(SERVICE_HELPER_PATH), "start", "--only", *target_services]
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        result = {
            "status": "degraded",
            "command": "services.start",
            "gate": gate,
            "reason": "service_start_timeout",
            "target_services": target_services,
            "timeout_seconds": 5,
            "error": str(exc),
            "service_observation": observation,
        }
        audit_event = build_service_control_audit_event(
            "start",
            "services.start",
            "degraded",
            reason="service_start_timeout",
            target_services=target_services,
            gate=gate,
            payload=payload,
            service_observation=observation,
        )
        enqueue_service_control_audit(audit_event, root=root)
        result["audit_async"] = True
        return result

    output = (proc.stdout or "").strip()
    try:
        start_result = json.loads(output) if output else {}
    except json.JSONDecodeError:
        result = {
            "status": "degraded",
            "command": "services.start",
            "gate": gate,
            "reason": "service_start_invalid_json",
            "target_services": target_services,
            "return_code": proc.returncode,
            "output": output[:2000],
            "service_observation": observation,
        }
        audit_event = build_service_control_audit_event(
            "start",
            "services.start",
            "degraded",
            reason="service_start_invalid_json",
            target_services=target_services,
            return_code=proc.returncode,
            gate=gate,
            payload=payload,
            service_observation=observation,
        )
        enqueue_service_control_audit(audit_event, root=root)
        result["audit_async"] = True
        return result
    refreshed = service_observation_status(root)
    result = {
        "status": "ok" if proc.returncode == 0 else "failed",
        "command": "services.start",
        "gate": gate,
        "target_services": target_services,
        "return_code": proc.returncode,
        "start_result": start_result,
        "service_observation_before": observation,
        "service_observation_after": refreshed,
    }
    audit_event = build_service_control_audit_event(
        "start",
        "services.start",
        result["status"],
        target_services=target_services,
        return_code=proc.returncode,
        gate=gate,
        payload=payload,
        service_observation=observation,
    )
    enqueue_service_control_audit(audit_event, root=root)
    result["audit_async"] = True
    return result


def service_restart_action(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    try:
        require_phone_admin(payload)
    except PermissionError as exc:
        observation = service_observation_status(root)
        result = {
            "status": "blocked",
            "command": "services.restart",
            "blocked_reason": str(exc),
            "service_observation": observation,
        }
        audit_event = build_service_control_audit_event(
            "restart",
            "services.restart",
            "blocked",
            reason=str(exc),
            payload=payload,
            service_observation=observation,
        )
        enqueue_service_control_audit(audit_event, root=root)
        result["audit_async"] = True
        return result
    gate = command_gate("services.restart", root=root)
    observation = service_observation_status(root)
    if not gate.get("allowed"):
        result = {
            "status": "blocked",
            "command": "services.restart",
            "gate": gate,
            "blocked_reason": str(gate.get("reason") or "phone_control_disarmed"),
            "service_observation": observation,
        }
        audit_event = build_service_control_audit_event(
            "restart",
            "services.restart",
            "blocked",
            reason=str(gate.get("reason") or "phone_control_disarmed"),
            gate=gate,
            payload=payload,
            service_observation=observation,
        )
        enqueue_service_control_audit(audit_event, root=root)
        result["audit_async"] = True
        return result

    requested_raw = payload.get("services")
    requested_services = [str(item).strip() for item in requested_raw] if isinstance(requested_raw, list) else []
    requested_services = [item for item in requested_services if item]
    if not requested_services:
        result = {
            "status": "invalid_request",
            "command": "services.restart",
            "gate": gate,
            "reason": "no_services_requested",
            "service_observation": observation,
        }
        audit_event = build_service_control_audit_event(
            "restart",
            "services.restart",
            "invalid_request",
            reason="no_services_requested",
            gate=gate,
            target_services=requested_services,
            requested_services=requested_services,
            payload=payload,
            service_observation=observation,
        )
        enqueue_service_control_audit(audit_event, root=root)
        result["audit_async"] = True
        return result
    requested_services = list(dict.fromkeys(requested_services))
    if "supervisor" in requested_services and not bool(payload.get("allow_supervisor")):
        result = {
            "status": "invalid_request",
            "command": "services.restart",
            "gate": gate,
            "reason": "supervisor_restart_not_allowed",
            "target_services": requested_services,
            "service_observation": observation,
        }
        audit_event = build_service_control_audit_event(
            "restart",
            "services.restart",
            "invalid_request",
            reason="supervisor_restart_not_allowed",
            target_services=requested_services,
            gate=gate,
            payload=payload,
            service_observation=observation,
        )
        enqueue_service_control_audit(audit_event, root=root)
        result["audit_async"] = True
        return result
    unknown = sorted({item for item in requested_services if item not in SERVICE_PROCESS_MARKERS})
    if unknown:
        result = {
            "status": "invalid_request",
            "command": "services.restart",
            "gate": gate,
            "reason": "unknown_service",
            "unknown_services": unknown,
            "known_services": sorted(SERVICE_PROCESS_MARKERS),
            "service_observation": observation,
        }
        audit_event = build_service_control_audit_event(
            "restart",
            "services.restart",
            "invalid_request",
            reason="unknown_service",
            requested_services=requested_services,
            gate=gate,
            target_services=requested_services,
            payload=payload,
            service_observation=observation,
        )
        enqueue_service_control_audit(audit_event, root=root)
        result["audit_async"] = True
        return result

    cmd = ["python3", str(SERVICE_HELPER_PATH), "restart", "--only", *requested_services]
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=8,
        )
    except subprocess.TimeoutExpired as exc:
        result = {
            "status": "degraded",
            "command": "services.restart",
            "gate": gate,
            "reason": "service_restart_timeout",
            "target_services": requested_services,
            "timeout_seconds": 8,
            "error": str(exc),
            "service_observation": observation,
        }
        audit_event = build_service_control_audit_event(
            "restart",
            "services.restart",
            "degraded",
            reason="service_restart_timeout",
            target_services=requested_services,
            gate=gate,
            payload=payload,
            service_observation=observation,
        )
        enqueue_service_control_audit(audit_event, root=root)
        result["audit_async"] = True
        return result

    output = (proc.stdout or "").strip()
    try:
        restart_result = json.loads(output) if output else {}
    except json.JSONDecodeError:
        result = {
            "status": "degraded",
            "command": "services.restart",
            "gate": gate,
            "reason": "service_restart_invalid_json",
            "target_services": requested_services,
            "return_code": proc.returncode,
            "output": output[:2000],
            "service_observation": observation,
        }
        audit_event = build_service_control_audit_event(
            "restart",
            "services.restart",
            "degraded",
            reason="service_restart_invalid_json",
            target_services=requested_services,
            return_code=proc.returncode,
            gate=gate,
            payload=payload,
            service_observation=observation,
        )
        enqueue_service_control_audit(audit_event, root=root)
        result["audit_async"] = True
        return result
    refreshed = service_observation_status(root)
    result = {
        "status": "ok" if proc.returncode == 0 else "failed",
        "command": "services.restart",
        "gate": gate,
        "target_services": requested_services,
        "return_code": proc.returncode,
        "restart_result": restart_result,
        "service_observation_before": observation,
        "service_observation_after": refreshed,
    }
    audit_event = build_service_control_audit_event(
        "restart",
        "services.restart",
        result["status"],
        target_services=requested_services,
        return_code=proc.returncode,
        gate=gate,
        payload=payload,
        service_observation=observation,
    )
    enqueue_service_control_audit(audit_event, root=root)
    result["audit_async"] = True
    return result


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
            elif parsed.path == "/api/monitor/control":
                self.write_json(200, monitor_control())
            elif parsed.path == "/api/monitor/status":
                self.write_json(200, monitor_status())
            elif parsed.path == "/api/monitor/intervention/examples":
                self.write_json(200, monitor_intervention_examples())
            elif parsed.path == "/api/worker/transport-presets":
                self.write_json(200, worker_transport_presets())
            elif parsed.path == "/api/worker/transport-config":
                self.write_json(200, llm_worker_config_state())
            elif parsed.path == "/api/monitor/interventions/events":
                last_id = _resolve_event_last_id(query.get("last_id", [None])[0], self.headers.get("Last-Event-ID"))
                try:
                    limit = int(query.get("limit", query.get("count", ["100"]))[0])
                except ValueError:
                    self.write_json(
                        400,
                        {
                            "status": "invalid_request",
                            "kind": "monitor_intervention_events",
                            "error": "limit must be integer",
                        },
                    )
                    return
                payload = read_monitor_intervention_events(last_id, limit=limit)
                if str(query.get("format", ["json"])[0]).lower() == "sse":
                    self.write_sse(200, payload)
                else:
                    self.write_json(200, payload)
            elif parsed.path == "/api/monitor/interventions/audit":
                try:
                    limit = int(query.get("limit", ["20"])[0])
                except ValueError:
                    self.write_json(
                        400,
                        {
                            "status": "invalid_request",
                            "kind": "monitor_intervention_audit_tail",
                            "error": "limit must be integer",
                        },
                    )
                    return
                self.write_json(200, monitor_intervention_audit_tail(limit=limit))
            elif parsed.path == "/api/tailscale/status":
                self.write_json(200, tailscale_status())
            elif parsed.path == "/api/nodes":
                self.write_json(200, node_status())
            elif parsed.path == "/api/nodes/status":
                self.write_json(200, node_status())
            elif parsed.path == "/api/nodes/connection-summary":
                self.write_json(200, node_connection_summary())
            elif parsed.path == "/api/communication/status":
                self.write_json(200, communication_status())
            elif parsed.path == "/api/communication/action-plan":
                self.write_json(200, communication_action_plan())
            elif parsed.path == "/api/communication/data-contract-report":
                self.write_json(
                    200,
                    communication_data_contract_report(
                        object_name=unquote(query.get("object", [""])[0]),
                        root=ROOT,
                    ),
                )
            elif parsed.path == "/api/communication/repair-suggestions":
                self.write_json(200, communication_repair_suggestions())
            elif parsed.path == "/api/services/control-audit":
                try:
                    limit = int(query.get("limit", ["20"])[0])
                except ValueError:
                    self.write_json(
                        400,
                        {
                            "status": "invalid_request",
                            "kind": "service_control_audit_tail",
                            "error": "limit must be integer",
                        },
                    )
                    return
                self.write_json(200, service_control_audit_tail(limit=limit))
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
            elif parsed.path == "/api/nodes/recovery-loop/latest":
                self.write_json(200, recovery_loop_latest())
            elif parsed.path == "/api/nodes/recovery-transcript":
                self.write_json(
                    200,
                    recovery_transcript(
                        query.get("node_id", [None])[0],
                        limit=int(query.get("limit", ["20"])[0]),
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
            elif parsed.path == "/api/memory/mempalace/status":
                self.write_json(200, mempalace_status())
            elif parsed.path.startswith("/api/node-command-results/by-command/"):
                command_id = unquote(parsed.path.removeprefix("/api/node-command-results/by-command/")).strip("/")
                result_last_id = _resolve_event_last_id(
                    query.get("result_last_id", [None])[0],
                    self.headers.get("Last-Event-ID"),
                )
                self.write_json(
                    200,
                    node_command_result_by_command_lookup(
                        command_id,
                        event_stream=query.get("event_stream", [EVENTS_STREAM_KEY])[0],
                        limit=query.get("limit", ["100"])[0],
                        timeout=query.get("timeout", ["3"])[0],
                        result_last_id=result_last_id,
                        node_id=query.get("node_id", [""])[0],
                    ),
                )
            elif parsed.path.startswith("/api/node-command-results/watch/"):
                command_id = unquote(parsed.path.removeprefix("/api/node-command-results/watch/")).strip("/")
                result_last_id = _resolve_event_last_id(
                    query.get("result_last_id", [None])[0],
                    self.headers.get("Last-Event-ID"),
                )
                payload = node_command_result_watch(
                    command_id,
                    event_stream=query.get("event_stream", [EVENTS_STREAM_KEY])[0],
                    limit=query.get("limit", ["100"])[0],
                    timeout=query.get("timeout", ["3"])[0],
                    timeout_seconds=query.get("timeout_seconds", [None])[0],
                    result_last_id=result_last_id,
                    node_id=query.get("node_id", [""])[0],
                )
                if str(query.get("format", ["json"])[0]).lower() == "sse":
                    sse_id = str(payload.get("next_last_id") or result_last_id or "")
                    self.write_sse(200, {"events": [{"id": sse_id, "fields": payload}]})
                else:
                    self.write_json(200, payload)
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
                    node_command_result_lookup(
                        result_event_id,
                        event_stream=event_stream,
                        timeout=timeout,
                        node_id=query.get("node_id", [""])[0],
                    ),
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
            elif self.path == "/api/communication/model-closure-validate":
                requested_object = str(payload.get("object_name") or payload.get("object") or "")
                requested_payload = payload.get("payload")
                self.write_json(
                    200,
                    communication_model_closure_validate(requested_object, requested_payload),
                )
            elif self.path == "/api/runtime/run-one":
                self.write_json(200, runtime_run_one(payload))
            elif self.path == "/api/runtime/run-one-with-transport":
                self.write_json(200, runtime_run_one_with_transport(payload))
            elif self.path == "/api/runtime/session-refresh-trial":
                self.write_json(200, runtime_session_refresh_trial(payload))
            elif self.path == "/api/runtime/session-lane-latest":
                self.write_json(200, runtime_session_lane_latest(payload))
            elif self.path == "/api/memory/mempalace/search":
                self.write_json(200, mempalace_search(payload))
            elif self.path == "/api/memory/mempalace/wakeup":
                self.write_json(200, mempalace_wakeup(payload))
            elif self.path == "/api/runtime/plan-decision-approve":
                self.write_json(200, runtime_plan_decision_approve(payload))
            elif self.path == "/api/runtime/plan-debate-next":
                self.write_json(200, runtime_plan_debate_next(payload))
            elif self.path == "/api/runtime/plan-backlog-next":
                self.write_json(200, runtime_plan_backlog_next(payload))
            elif self.path == "/api/monitor/intervention":
                self.write_json(200, monitor_intervention(payload))
            elif self.path == "/api/worker/transport-policy":
                self.write_json(200, update_worker_transport_policy(payload))
            elif self.path == "/api/worker/transport-check":
                self.write_json(200, worker_transport_check(payload))
            elif self.path == "/api/worker/transport-config":
                self.write_json(200, update_llm_worker_config(payload))
            elif self.path == "/api/services/restart":
                self.write_json(200, service_restart_action(payload))
            elif self.path == "/api/services/start":
                self.write_json(200, service_start_action(payload))
            elif self.path == "/api/communication/repair-one":
                self.write_json(200, communication_repair_one(payload))
            elif self.path == "/api/communication/repair-suggestions/review":
                self.write_json(200, communication_repair_suggestion_review(payload))
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
            elif self.path == "/api/nodes/bootstrap-takeover-admission":
                self.write_json(200, bootstrap_takeover_admission(payload))
            elif self.path == "/api/nodes/bootstrap-takeover-resume":
                self.write_json(200, bootstrap_takeover_resume(payload))
            elif self.path == "/api/nodes/bootstrap-takeover-reject":
                self.write_json(200, bootstrap_takeover_reject(payload))
            elif self.path == "/api/nodes/bootstrap-execute":
                status, body = guarded_remote_post(
                    "nodes.bootstrap.execute",
                    payload,
                    bootstrap_execute_node,
                    endpoint="/api/nodes/bootstrap-execute",
                )
                self.write_json(status, body)
            elif self.path == "/api/nodes/heartbeat-repair":
                status, body = guarded_remote_post(
                    "nodes.remote.repair",
                    payload,
                    heartbeat_repair_node,
                    endpoint="/api/nodes/heartbeat-repair",
                )
                self.write_json(status, body)
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
    monitor_parser = sub.add_parser("monitor-intervention")
    monitor_parser.add_argument(
        "action",
        choices=sorted(MONITOR_INTERVENTION_ALLOWED_ACTIONS),
        nargs="?",
        default="pause",
    )
    monitor_parser.add_argument("--reason", default="operator cli intervention")
    monitor_parser.add_argument("--task-id", dest="task_id", default="")
    monitor_parser.add_argument("--run-id", dest="run_id", default="")
    monitor_parser.add_argument("--actor", default="cli-operator")
    monitor_parser.add_argument("--evidence-ref", action="append", default=[])
    monitor_parser.add_argument("--flow-id", dest="flow_id", default="")
    monitor_parser.add_argument("--flow-expected-revision", dest="flow_expected_revision", type=int)
    monitor_parser.add_argument("--flow-expected-last-seq", dest="flow_expected_last_seq", type=int)
    monitor_parser.add_argument("--flow-sequence", dest="flow_sequence", type=int)
    monitor_parser.add_argument("--evidence-id", dest="evidence_id", default="")
    monitor_parser.add_argument("--idempotency-key", dest="idempotency_key", default="")
    monitor_parser.add_argument("--arm-duration", dest="arm_duration", default="")
    monitor_parser.add_argument("--examples", action="store_true")
    check_parser = sub.add_parser("worker-transport-check")
    check_parser.add_argument("--preset", default="openai_compatible")
    check_parser.add_argument("--execute", action="store_true")
    check_parser.add_argument("--model", default="")
    check_parser.add_argument("--base-url", dest="base_url", default="")
    check_parser.add_argument("--api-key-env", dest="api_key_env", default="")
    check_parser.add_argument("--timeout-seconds", dest="timeout_seconds", type=int)
    check_parser.add_argument("--arm-duration", dest="arm_duration", default="")
    policy_parser = sub.add_parser("worker-transport-policy")
    policy_parser.add_argument("--preset", default="")
    policy_parser.add_argument("--model", default="")
    policy_parser.add_argument("--base-url", dest="base_url", default="")
    policy_parser.add_argument("--api-key-env", dest="api_key_env", default="")
    policy_parser.add_argument("--timeout-seconds", dest="timeout_seconds", type=int)
    policy_parser.add_argument("--reason", required=True)
    policy_parser.add_argument("--require-probe-pass", dest="require_probe_pass", action="store_true")
    policy_parser.add_argument("--arm-duration", dest="arm_duration", default="")
    config_parser = sub.add_parser("worker-transport-config")
    config_parser.add_argument("--model", required=True)
    config_parser.add_argument("--base-url", dest="base_url", required=True)
    config_parser.add_argument("--api-key-env", dest="api_key_env", default="A9_LLM_WORKER_API_KEY")
    config_parser.add_argument("--timeout-seconds", dest="timeout_seconds", type=int, default=30)
    config_parser.add_argument("--reason", required=True)
    config_parser.add_argument("--arm-duration", dest="arm_duration", default="")
    runtime_transport_parser = sub.add_parser("runtime-run-one-with-transport")
    runtime_transport_parser.add_argument("--preset", default="local_envelope_smoke")
    runtime_transport_parser.add_argument("--model", default="")
    runtime_transport_parser.add_argument("--base-url", dest="base_url", default="")
    runtime_transport_parser.add_argument("--api-key-env", dest="api_key_env", default="")
    runtime_transport_parser.add_argument("--timeout-seconds", dest="timeout_seconds", type=int)
    runtime_transport_parser.add_argument("--reason", default="temporary transport runtime run-one")
    runtime_transport_parser.add_argument("--require-probe-pass", dest="require_probe_pass", action="store_true")
    runtime_transport_parser.add_argument("--auto-next", dest="auto_next", action="store_true")
    runtime_transport_parser.add_argument("--arm-duration", dest="arm_duration", default="")
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
    if args.command == "monitor-intervention":
        return monitor_intervention_cli(args)
    if args.command == "worker-transport-check":
        return worker_transport_check_cli(args)
    if args.command == "worker-transport-policy":
        return worker_transport_policy_cli(args)
    if args.command == "worker-transport-config":
        return worker_transport_config_cli(args)
    if args.command == "runtime-run-one-with-transport":
        return runtime_run_one_with_transport_cli(args)
    if args.command == "serve":
        return serve(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
