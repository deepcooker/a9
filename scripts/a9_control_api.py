#!/usr/bin/env python3
"""A9 mobile/control-plane HTTP API.

This is intentionally small and stdlib-only. It exposes existing A9 state to a
phone/browser without making the phone a new source of truth.
"""

from __future__ import annotations

import argparse
import ipaddress
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
CODEX_SESSIONS_DIR = Path("/root/.codex/sessions")
SUPERVISOR_PATH = ROOT / "scripts" / "a9_supervisor.py"
SESSION_REFRESH_PATH = ROOT / "scripts" / "a9_session_refresh.py"
REMOTE_PATH = ROOT / "scripts" / "a9_remote.py"
NODES_DIR = ROOT / ".a9" / "nodes"
PHONE_CONTROL_REL_PATH = Path(".a9") / "control" / "phone_control.json"
TAILSCALE_SOCKET = "/run/tailscale/tailscaled.sock"
DEFAULT_SSH_IDENTITY_FILE = "/root/id_ed25519"
NODE_ONLINE_TTL_SECONDS = 90
NODE_STALE_TTL_SECONDS = 300
PHONE_ADMIN_SCOPE = "operator.admin"
PHONE_CONTROL_GROUPS = {
    "runtime": ["submit.run", "session.refresh.trial", "flow.resume", "approval.approve", "approval.reject"],
    "remote": ["nodes.bootstrap.execute", "nodes.remote.install", "nodes.remote.repair", "nodes.tmux.ensure"],
}
KNOWN_CONTROL_COMMANDS = sorted({cmd for commands in PHONE_CONTROL_GROUPS.values() for cmd in commands})
EVENTS_STREAM_KEY = "a9:events"
EVENTS_STREAM_LIMIT_MAX = 1000
TASKS_STREAM_KEY = "a9:tasks"
TASKS_STREAM_GROUP = "a9-worker"
TASKS_STREAM_TOP_CONSUMERS_LIMIT = 3


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
        "context_pressure": context_pressure,
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
            "events": "/api/events",
        },
        "runtime": {
            "ssh_bootstrap": True,
            "redis_streams_target": True,
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


def node_status(root: Path = ROOT) -> dict[str, Any]:
    nodes_dir = root / ".a9" / "nodes"
    nodes = []
    if nodes_dir.exists():
        for path in sorted(nodes_dir.glob("*.json"), key=lambda item: item.stat().st_mtime):
            try:
                record = enrich_node_connection(read_json(path))
                record = enrich_node_tmux_action(record, root=root)
                nodes.append(record)
            except json.JSONDecodeError:
                nodes.append({"node_id": path.stem, "status": "invalid", "connection_state": "invalid"})
    return {
        "count": len(nodes),
        "nodes": nodes[-50:],
        "redis": redis_node_hot_status(),
        "tasks_stream": redis_tasks_stream_probe(),
    }


def node_connection_action(connection_state: str) -> tuple[str, str]:
    if connection_state == "online":
        return ("continue", "heartbeat_fresh")
    if connection_state == "stale":
        return ("reconnect", "heartbeat_stale")
    if connection_state == "offline":
        return ("quarantine", "heartbeat_offline")
    return ("reconnect", "heartbeat_unknown")


def enrich_node_connection(record: dict[str, Any]) -> dict[str, Any]:
    heartbeat_at = parse_iso_datetime(str(record.get("last_heartbeat_at") or record.get("updated_at") or ""))
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
    candidates = sorted(evidence_dir.glob("tmux-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
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


def enrich_node_tmux_action(record: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    node_id = str(record.get("node_id") or "")
    if not node_id:
        return record
    tmux = latest_tmux_action_for_node(node_id, root=root)
    if not tmux:
        return record
    return {**record, **tmux}


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
    proc = subprocess.run(
        [*cmd, mod.remote_probe_script()],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    parsed = mod.parse_probe(proc.stdout) if proc.returncode == 0 else {}
    host = str(payload.get("host") or parsed.get("host") or target.split("@")[-1].split(":")[0])
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
        },
        root=root,
    )
    return {
        "status": "ok" if proc.returncode == 0 else "failed",
        "checked_at": utc_now(),
        "ssh_target": target,
        "return_code": proc.returncode,
        "probe": parsed,
        "raw": compact_text(proc.stdout, 4000),
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
            "later install worker daemon and Redis Streams consumer",
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
            elif parsed.path == "/api/events":
                last_id = _resolve_event_last_id(query.get("last_id", [None])[0], self.headers.get("Last-Event-ID"))
                try:
                    limit = int(query.get("limit", query.get("count", ["100"]))[0])
                except ValueError:
                    self.write_json(400, {"error": "limit must be integer"})
                    return
                payload = read_events(last_id, limit=limit)
                if query.get("format", ["json"])[0] == "sse":
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
            elif self.path == "/api/nodes/register":
                self.write_json(200, register_node(payload))
            elif self.path == "/api/nodes/probe":
                self.write_json(200, probe_node(payload))
            elif self.path == "/api/nodes/bootstrap-plan":
                self.write_json(200, bootstrap_plan_node(payload))
            elif self.path == "/api/nodes/bootstrap-dry-run":
                self.write_json(200, bootstrap_dry_run_node(payload))
            elif self.path == "/api/nodes/tmux-plan":
                self.write_json(200, tmux_plan_node(payload))
            elif self.path == "/api/nodes/tmux-ensure":
                self.write_json(200, tmux_ensure_node(payload))
            elif self.path == "/api/nodes/tmux-status":
                self.write_json(200, tmux_status_node(payload))
            elif self.path == "/api/nodes/heartbeat":
                self.write_json(200, heartbeat_node(payload))
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
