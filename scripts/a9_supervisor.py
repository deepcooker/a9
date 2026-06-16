#!/usr/bin/env python3
"""A9 Codex supervisor MVP.

Runs queued markdown tasks through `codex exec --json`, stores traces, captures
git diffs, executes declared checks, and classifies the result without scraping
the interactive UI.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.environ.get("A9_STATE_DIR", str(ROOT / ".a9"))).expanduser()
QUEUE_DIR = STATE_DIR / "tasks" / "queue"
RUNNING_DIR = STATE_DIR / "tasks" / "running"
DONE_DIR = STATE_DIR / "tasks" / "done"
INTERRUPTED_DIR = STATE_DIR / "tasks" / "interrupted"
BLOCKED_DIR = STATE_DIR / "tasks" / "blocked"
RUNS_DIR = STATE_DIR / "runs"
WORKTREES_DIR = STATE_DIR / "worktrees"
WORKER_CODEX_HOME = STATE_DIR / "codex-home"
WORKER_TMP_DIR = STATE_DIR / "tmp"
EXTERNAL_SESSIONS_DIR = STATE_DIR / "external_sessions"
MEMPALACE_DRAWERS_PATH = STATE_DIR / "mempalace" / "operator-session-drawers.jsonl"
CODEX_SESSIONS_DIR = Path(os.environ.get("A9_CODEX_SESSIONS_DIR", str(Path.home() / ".codex" / "sessions")))
RECORDS_DIR = STATE_DIR / "records"
GOALS_DIR = STATE_DIR / "goals"
PLANS_DIR = STATE_DIR / "plans"
ACTIVE_PLAN_PATH = PLANS_DIR / ".active_plan"
EVAL_STORE_DIR = STATE_DIR / "eval_store"
EVAL_STORE_RUNS_DIR = EVAL_STORE_DIR / "runs"
EVAL_STORE_OVERRIDES_DIR = EVAL_STORE_DIR / "overrides"
PROGRESS_PATH = STATE_DIR / "progress.json"
DAEMON_HEARTBEAT_PATH = STATE_DIR / "daemon_heartbeat.json"
AUTO_LOOP_GUARD_PATH = STATE_DIR / "auto_loop_guard.json"
RUN_LOOP_LOCK_PATH = STATE_DIR / "run_loop.lock"
RUNTIME_CONTROL_STATE_PATH = STATE_DIR / "runtime" / "control_state.json"
WORKER_MODEL_POLICY_PATH = STATE_DIR / "runtime" / "worker_model_policy.json"
WORKER_TRANSPORT_POLICY_PATH = STATE_DIR / "runtime" / "worker_transport_policy.json"
WORKER_TRANSPORT_HEALTH_PATH = STATE_DIR / "runtime" / "worker_transport_health.json"
DEFAULT_CONTEXT_TOKEN_BUDGET = 24000
DEFAULT_WORKER_MODEL = "gpt-5.3-codex-spark"
DEFAULT_WORKER_TRANSPORT_BACKEND = "codex_exec"
DEFAULT_WORKER_TRANSPORT_COOLDOWN_SECONDS = 300
DEFAULT_REFERENCE_SCAN_WORKER_MODEL = ""
DEFAULT_CRITICAL_WORKER_MODEL = ""
DEFAULT_MAX_WORKER_EVENTS = 80
DEFAULT_MAX_WORKER_EVENT_BYTES = 120_000
DEFAULT_WORKER_EVENT_BUDGET_MODE = "observe"
DEFAULT_MEMPALACE_WAKEUP_ENABLED = True
DEFAULT_AUTO_LOOP_FAILURE_LIMIT = 2
DEFAULT_REDIS_DEEP_MARK_LIMIT = 80
DEFAULT_IDLE_GOAL_CONTINUATION_ENABLED = True
DEFAULT_WORKER_MODEL_FALLBACK = "gpt-5.5"
WORKER_COST_OBSERVE_INPUT_TOKENS = 1_000_000
WORKER_COST_HIGH_INPUT_TOKENS = 2_000_000
WORKER_COST_OBSERVE_UNCACHED_TOKENS = 120_000
WORKER_COST_HIGH_UNCACHED_TOKENS = 500_000
WORKER_COST_OBSERVE_OUTPUT_REASONING_TOKENS = 20_000
WORKER_COST_HIGH_OUTPUT_REASONING_TOKENS = 100_000
COMMUNICATION_GATE_HINTS = (
    "gateway runtime",
    "gateway transport",
    "gateway communication",
    "gateway evidence",
    "ws",
    "websocket",
    "ssh",
    "tailscale",
    "tmux",
    "mobile",
    "control api",
    "control plane",
    "communication",
    "remote",
    "通讯",
    "通信",
    "多机器",
    "手机",
    "远程",
)
COMMUNICATION_GATE_COMBO_HINTS = (
    ("redis", "stream"),
    ("redis", "communication"),
    ("redis", "通讯"),
)
BLOCKED_WORKER_COMMAND_PATTERNS = [
    "codex exec",
    "a9_supervisor.py run-one",
    "a9_supervisor.py run-loop",
]
DEFAULT_NEXT_CHECKS = [
    "python3 -m unittest tests/test_supervisor.py tests/test_memory.py tests/test_checkpoint.py",
    "cargo build --workspace",
]
REFERENCE_SCAN_CHECKS = [
    "python3 -m py_compile scripts/a9_supervisor.py",
]
TEST_COMMAND_HINTS = ("pytest", "unittest", "py_compile", "cargo test", "npm test", "pnpm test", "yarn test")
SESSION_REFRESH_PHASE = "session_refresh"
SESSION_CLOSE_READING_PHASE = "session_close_reading"
SESSION_CONTEXT_READ_PHASES = {SESSION_REFRESH_PHASE, SESSION_CLOSE_READING_PHASE}
FORBIDDEN_SESSION_CONTEXT_PATHS = (
    "docs/session.md",
    "docs/mistakes.md",
    "/root/.codex/sessions",
    ".a9/external_sessions",
)
FORBIDDEN_SESSION_CONTEXT_PATH_PREFIXES = (
    "archive/original-ideas/",
)
RUNTIME_EVIDENCE_ROOTS = (
    ".a9",
    ".a9/",
    ".a9/tasks",
    ".a9/tasks/done",
    ".a9/worktrees",
    ".a9/runs",
)
WORKSPACE_WRITE_PREFIXES = (
    "AGENTS.md",
    "README.md",
    "docs/",
    "scripts/",
    "tests/",
    "crates/",
    "infra/",
    "session-governance.md",
    "原始想法需求.md",
)
FLOW_KEY_PREFIX = "a9:flow:"
PHASE_ORDER = [
    "reference_scan",
    "mechanism_extract",
    "vendor_import",
    "implement",
    "test",
    "record",
]
PHASE_FOCUS = {
    "reference_scan": "Inspect mature local reference projects and pick one concrete mechanism worth copying.",
    "mechanism_extract": "Explain the copied mechanism's moving parts, contracts, failure modes, and token/cost behavior.",
    "vendor_import": "Import or update licensed source slices under vendor-src and record license/source metadata.",
    "implement": "Adapt the selected mechanism into A9 with bounded code or docs changes.",
    "test": "Strengthen automated verification and regression coverage for the copied mechanism.",
    "repair": "Fix the previous failed checks, incomplete implementation, or missing evidence.",
    "record": "Update docs, evidence, and progress so the next worker can continue without chat context.",
    "compare": "Verify the previous run, active-plan hydration, and declared decisions with bounded evidence before executing the next slice.",
    SESSION_REFRESH_PHASE: "Index and extract external Codex/operator sessions without calling an AI worker.",
    SESSION_CLOSE_READING_PHASE: "Append bounded external-session close-reading notes from extracted evidence.",
}
AI_WORKER_PHASES = {
    "reference_scan",
    "mechanism_extract",
    "vendor_import",
    "implement",
    "test",
    "repair",
    "record",
}
SECTION_TOKEN_BUDGETS = {
    "doctrine": 5000,
    "method": 1800,
    "task": 4000,
    "previous_context": 3000,
    "repo_map": 2500,
    "reference_mechanisms": 2500,
    "contract": 1500,
}
PHASE_SECTION_TOKEN_BUDGETS = {
    "implement": {
        "doctrine": 1800,
        "method": 1600,
        "task": 4000,
        "previous_context": 1800,
        "repo_map": 2500,
        "reference_mechanisms": 1200,
        "contract": 1200,
    },
    "test": {
        "doctrine": 1200,
        "method": 1400,
        "task": 4000,
        "previous_context": 2000,
        "repo_map": 3000,
        "reference_mechanisms": 1000,
        "contract": 1200,
    },
    "repair": {
        "doctrine": 1000,
        "method": 1600,
        "task": 4200,
        "previous_context": 2500,
        "repo_map": 2500,
        "reference_mechanisms": 800,
        "contract": 1200,
    },
    "reference_scan": {
        "doctrine": 2000,
        "method": 1600,
        "task": 3600,
        "previous_context": 1000,
        "repo_map": 2500,
        "reference_mechanisms": 3500,
        "contract": 1200,
    },
    "mechanism_extract": {
        "doctrine": 2200,
        "method": 1800,
        "task": 3600,
        "previous_context": 1200,
        "repo_map": 2500,
        "reference_mechanisms": 3200,
        "contract": 1200,
    },
    "vendor_import": {
        "doctrine": 1500,
        "method": 1600,
        "task": 3800,
        "previous_context": 1200,
        "repo_map": 2600,
        "reference_mechanisms": 2800,
        "contract": 1400,
    },
    SESSION_REFRESH_PHASE: {
        "doctrine": 1000,
        "method": 0,
        "task": 4200,
        "previous_context": 800,
        "repo_map": 1600,
        "reference_mechanisms": 700,
        "contract": 1000,
    },
    SESSION_CLOSE_READING_PHASE: {
        "doctrine": 1300,
        "method": 0,
        "task": 4200,
        "previous_context": 1200,
        "repo_map": 1800,
        "reference_mechanisms": 800,
        "contract": 1000,
    },
}
SUMMARY_MIN_SPLIT = 4
SUMMARY_MAX_DEPTH = 3
SUMMARY_MIN_HEAD_BUDGET = 256
SUMMARY_RESERVED_TAIL_TOKENS = 192
NOISE_PATTERNS = [
    re.compile(r"^mysql: \[Warning\] Using a password on the command line interface", re.I),
    re.compile(r"^\.+$"),
    re.compile(r"^-+$"),
    re.compile(r"^=+$"),
    re.compile(r"^Ran \d+ tests? in [\d.]+s$", re.I),
    re.compile(r"^OK$"),
    re.compile(r"^\[.*truncated.*\]$", re.I),
    re.compile(r"^\.\.\.\[truncated.*\]\.\.\.$", re.I),
]
PROMPTWARE_PATTERNS = [
    re.compile(r"\bignore\s+previous\s+instructions?\b", re.I),
    re.compile(r"\bsystem\s+prompt\b", re.I),
]
WORKER_NETWORK_ERROR_PATTERNS = [
    re.compile(r"\bConnection reset by peer\b", re.I),
    re.compile(r"\bConnection refused\b", re.I),
    re.compile(r"\bConnection timed out\b", re.I),
    re.compile(r"\bTLS handshake\b", re.I),
    re.compile(r"\bwebsocket\b.*\b(error|closed|disconnect|reset)\b", re.I),
    re.compile(r"\bReconnecting\.\.\.", re.I),
    re.compile(r"\bnetwork\b.*\b(error|unreachable|reset|timeout)\b", re.I),
]
WORKER_STARTUP_ERROR_PATTERNS = [
    re.compile(r"\bapp-server\b.*\b(init|initiali[sz]e|startup|start)\b.*\b(fail|error|timeout)\b", re.I),
    re.compile(r"\bfailed to (start|initialize|initialise)\b", re.I),
    re.compile(r"\bNo such file or directory\b.*\bcodex\b", re.I),
    re.compile(r"\bpermission denied\b", re.I),
]
WORKER_BROKEN_PIPE_PATTERNS = [
    re.compile(r"\bBroken pipe\b", re.I),
    re.compile(r"\bEPIPE\b", re.I),
]
WORKER_TRANSPORT_OBSERVATION_PATTERNS = [
    re.compile(r"\bTransport channel closed\b", re.I),
    re.compile(r"\bhttp/request failed\b", re.I),
    re.compile(r"\berror sending request\b", re.I),
    re.compile(r"\bCreateProcess\b.*\bRejected\b", re.I),
    re.compile(r"\bexec_command failed\b", re.I),
    re.compile(r"\brmcp::transport::worker\b", re.I),
]
WORKER_TRANSPORT_EXHAUSTED_PATTERNS = [
    re.compile(r"\bReconnecting\.\.\.\s*5/5\b.*\btimeout waiting for child process to exit\b", re.I | re.S),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return value.strip("-") or f"task-{int(time.time())}"


def compact_task_ref(value: str, *, limit: int = 48) -> str:
    clean = slugify(value)
    if len(clean) <= limit:
        return clean
    digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:10]
    head = clean[: max(8, limit - len(digest) - 1)].rstrip("-")
    return f"{head}-{digest}"


def artifact_task_ref(value: str) -> str:
    return compact_task_ref(value, limit=96)


def run_id_for_task(task_id: str, attempt: int) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{artifact_task_ref(task_id)}-{timestamp}-a{attempt}"


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


def run_cmd_no_raise(args: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def ensure_dirs() -> None:
    for path in [
        QUEUE_DIR,
        RUNNING_DIR,
        DONE_DIR,
        INTERRUPTED_DIR,
        BLOCKED_DIR,
        RUNS_DIR,
        WORKTREES_DIR,
        WORKER_CODEX_HOME,
        WORKER_TMP_DIR,
        EXTERNAL_SESSIONS_DIR,
        RECORDS_DIR,
        GOALS_DIR,
        PLANS_DIR,
        EVAL_STORE_DIR,
        EVAL_STORE_RUNS_DIR,
        EVAL_STORE_OVERRIDES_DIR,
        RUNTIME_CONTROL_STATE_PATH.parent,
    ]:
        path.mkdir(parents=True, exist_ok=True)


@dataclass
class Task:
    path: Path
    task_id: str
    prompt: str
    phase: str = "implement"
    workspace_root: str = ""
    timeout_seconds: int = 3600
    idle_timeout_seconds: int = 300
    max_attempts: int = 2
    checks: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    auto_next_allowed: bool = True
    task_quality_warnings: list[str] = field(default_factory=list)


OBSERVATION_ONLY_TASK_MARKERS = (
    "observation-only",
    "observation only",
    "test-only",
    "test only",
    "read-only",
    "read only",
    "verify only",
    "validate only",
    "no production changes",
    "without production changes",
)


def task_is_observation_only(task: Task) -> bool:
    """Detect small verification tasks that should not hydrate broad memory."""
    if task.phase not in {"test", "compare"}:
        return False
    prompt_lower = task.prompt.lower()
    return any(marker in prompt_lower for marker in OBSERVATION_ONLY_TASK_MARKERS)


def effective_worker_idle_timeout_seconds(task: Task) -> int:
    if any("tests/test_supervisor.py" in check for check in task.checks):
        return max(task.idle_timeout_seconds, 420)
    return task.idle_timeout_seconds


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
                    meta.setdefault(current_list_key, []).append(parse_frontmatter_scalar(line[4:].strip()))
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
                elif value.lower() in {"true", "false"}:
                    meta[key] = value.lower() == "true"
                else:
                    meta[key] = parse_frontmatter_scalar(value)

    task_id = slugify(str(meta.get("id") or path.stem))
    checks = [str(item) for item in meta.get("checks", [])]
    allowed_paths = [str(item) for item in meta.get("allowed_paths", [])]
    task_quality_warnings = [str(item) for item in meta.get("task_quality_warnings", [])]
    workspace_root = str(meta.get("workspace_root", "")).strip()
    auto_next_allowed = bool(meta.get("auto_next", True))
    if bool(meta.get("no_auto_next", False)):
        auto_next_allowed = False
    return Task(
        path=path,
        task_id=task_id,
        prompt=body.strip(),
        phase=str(meta.get("phase", "implement")),
        workspace_root=workspace_root,
        timeout_seconds=int(meta.get("timeout_seconds", 3600)),
        idle_timeout_seconds=int(meta.get("idle_timeout_seconds", 300)),
        max_attempts=int(meta.get("max_attempts", 2)),
        checks=checks,
        allowed_paths=allowed_paths,
        auto_next_allowed=auto_next_allowed,
        task_quality_warnings=task_quality_warnings,
    )


def parse_frontmatter_scalar(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text[0] in {"'", '"'}:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, str):
                return parsed
        except json.JSONDecodeError:
            pass
    return text.strip('"')


def frontmatter_quote(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def next_task() -> Task | None:
    tasks = sorted(QUEUE_DIR.glob("*.md"))
    return parse_task(tasks[0]) if tasks else None


def task_quality_blockers(warnings: list[str]) -> list[str]:
    blockers: list[str] = []
    for warning in warnings:
        text = str(warning or "")
        if text.startswith("declared_check_unresolved_unittest_target:"):
            blockers.append(text)
    return blockers


def record_active_plan_task_quality_block(task: Task, block_record: dict[str, Any]) -> dict[str, Any]:
    plan = active_plan()
    if not plan:
        return {"status": "skipped", "reason": "no_active_plan"}
    backlog = execution_backlog_state(plan)
    items = backlog.get("items")
    if not isinstance(items, list):
        return {"status": "skipped", "reason": "no_execution_backlog_items"}
    task_id = str(task.task_id or "").strip()
    matched: dict[str, Any] | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        if task_id in {
            str(item.get("queued_task_id") or "").strip(),
            str(item.get("task_id") or "").strip(),
        }:
            matched = item
            break
    if matched is None:
        return {"status": "skipped", "reason": "task_not_in_execution_backlog", "task_id": task_id}
    now = utc_now()
    matched["status"] = "monitor-blocked"
    matched["blocked_at"] = now
    matched["blocked_reason"] = "task_quality_block"
    matched["quality_blockers"] = list(block_record.get("blockers") or [])
    matched["quality_block_path"] = str(block_record.get("blocked_path") or "")
    matched["quality_block_record_path"] = str(block_record.get("audit_path") or "")
    matched["last_updated_at"] = now
    plan["updated_at"] = now
    plan_dir = write_plan_files(plan, activate=True)
    append_plan_progress(
        plan_dir,
        (
            f"- {now} task_quality_block: task={task_id} "
            f"item={matched.get('id') or matched.get('backlog_id') or ''} "
            f"blockers={'; '.join(str(item) for item in block_record.get('blockers', []))}"
        ),
    )
    return {
        "status": "updated",
        "task_id": task_id,
        "item_id": str(matched.get("id") or matched.get("backlog_id") or ""),
        "item_status": "monitor-blocked",
    }


def queued_task_quality_summary(limit: int = 10) -> dict[str, Any]:
    ensure_dirs()
    queued_paths = sorted(QUEUE_DIR.glob("*.md"))
    warning_tasks: list[dict[str, Any]] = []
    warnings_by_code: dict[str, int] = {}
    warning_task_count = 0
    warnings_count = 0
    blocker_task_count = 0
    blockers_count = 0
    blockers_by_code: dict[str, int] = {}
    parse_errors = 0
    for path in queued_paths:
        try:
            task = parse_task(path)
        except Exception:
            parse_errors += 1
            warning_task_count += 1
            code = "task_parse_error"
            warnings_by_code[code] = warnings_by_code.get(code, 0) + 1
            warnings_count += 1
            if len(warning_tasks) < limit:
                warning_tasks.append(
                    {
                        "task_id": path.stem,
                        "path": str(path),
                        "phase": "",
                        "warnings": [code],
                    }
                )
            continue
        if not task.task_quality_warnings:
            continue
        blockers = task_quality_blockers(task.task_quality_warnings)
        warning_task_count += 1
        warnings_count += len(task.task_quality_warnings)
        for warning in task.task_quality_warnings:
            code = str(warning).split(":", 1)[0]
            warnings_by_code[code] = warnings_by_code.get(code, 0) + 1
        if blockers:
            blocker_task_count += 1
            blockers_count += len(blockers)
            for blocker in blockers:
                code = str(blocker).split(":", 1)[0]
                blockers_by_code[code] = blockers_by_code.get(code, 0) + 1
        if len(warning_tasks) < limit:
            warning_tasks.append(
                {
                    "task_id": task.task_id,
                    "path": str(path),
                    "phase": task.phase,
                    "warnings": list(task.task_quality_warnings),
                    "blockers": blockers,
                }
            )
    return {
        "status": "blocked" if blocker_task_count else "warning" if warning_tasks or parse_errors else "ok",
        "queued_task_count": len(queued_paths),
        "warning_task_count": warning_task_count,
        "warnings_count": warnings_count,
        "warnings_by_code": warnings_by_code,
        "blocker_task_count": blocker_task_count,
        "blockers_count": blockers_count,
        "blockers_by_code": blockers_by_code,
        "tasks": warning_tasks,
        "truncated": warning_task_count > len(warning_tasks),
        "parse_errors": parse_errors,
    }


def runtime_control_state() -> dict[str, Any]:
    ensure_dirs()
    if not RUNTIME_CONTROL_STATE_PATH.exists():
        return {
            "schema": "a9.runtime_control_state.v1",
            "paused": False,
            "status": "running",
            "updated_at": "",
            "last_intervention": {},
        }
    data = read_json_file(RUNTIME_CONTROL_STATE_PATH)
    if not data:
        return {
            "schema": "a9.runtime_control_state.v1",
            "paused": False,
            "status": "running",
            "updated_at": "",
            "last_intervention": {},
            "state_error": "unreadable_runtime_control_state",
        }
    return data


def write_runtime_control_state(state: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    payload = {
        "schema": "a9.runtime_control_state.v1",
        **state,
        "updated_at": utc_now(),
    }
    write_json(RUNTIME_CONTROL_STATE_PATH, payload)
    return payload


def worker_model_policy_state() -> dict[str, Any]:
    ensure_dirs()
    data = read_json_file(WORKER_MODEL_POLICY_PATH)
    if not data:
        data = {}
    phase_models = data.get("phase_models") if isinstance(data.get("phase_models"), dict) else {}
    return {
        "schema": data.get("schema") or "a9.worker_model_policy_state.v1",
        "global_model": str(data.get("global_model") or ""),
        "critical_model": str(data.get("critical_model") or ""),
        "reference_model": str(data.get("reference_model") or ""),
        "phase_models": {str(key): str(value) for key, value in phase_models.items() if str(value).strip()},
        "updated_at": str(data.get("updated_at") or ""),
        "last_update": data.get("last_update", {}) if isinstance(data.get("last_update"), dict) else {},
    }


def write_worker_model_phase_override(
    phase: str,
    model: str,
    *,
    reason: str,
    task_id: str = "",
    run_dir: str = "",
) -> dict[str, Any]:
    state = worker_model_policy_state()
    phase_models = dict(state.get("phase_models", {}))
    phase_models[phase] = model
    payload = {
        **state,
        "schema": "a9.worker_model_policy_state.v1",
        "phase_models": phase_models,
        "updated_at": utc_now(),
        "last_update": {
            "kind": "phase_model_override",
            "phase": phase,
            "model": model,
            "reason": reason,
            "task_id": task_id,
            "run_dir": run_dir,
            "updated_at": utc_now(),
        },
    }
    write_json(WORKER_MODEL_POLICY_PATH, payload)
    return payload


def worker_transport_policy_state() -> dict[str, Any]:
    ensure_dirs()
    data = read_json_file(WORKER_TRANSPORT_POLICY_PATH)
    if not data:
        data = {}
    backend = str(data.get("backend") or DEFAULT_WORKER_TRANSPORT_BACKEND).strip() or DEFAULT_WORKER_TRANSPORT_BACKEND
    if backend not in {"codex_exec", "custom_command"}:
        backend = DEFAULT_WORKER_TRANSPORT_BACKEND
    return {
        "schema": data.get("schema") or "a9.worker_transport_policy_state.v1",
        "backend": backend,
        "custom_command_template": str(data.get("custom_command_template") or ""),
        "updated_at": str(data.get("updated_at") or ""),
        "last_update": data.get("last_update", {}) if isinstance(data.get("last_update"), dict) else {},
    }


def write_worker_transport_policy(
    *,
    backend: str,
    custom_command_template: str = "",
    reason: str,
) -> dict[str, Any]:
    if backend not in {"codex_exec", "custom_command"}:
        raise ValueError(f"unsupported worker transport backend: {backend}")
    payload = {
        "schema": "a9.worker_transport_policy_state.v1",
        "backend": backend,
        "custom_command_template": custom_command_template,
        "updated_at": utc_now(),
        "last_update": {
            "kind": "worker_transport_policy_update",
            "backend": backend,
            "reason": reason,
            "updated_at": utc_now(),
        },
    }
    write_json(WORKER_TRANSPORT_POLICY_PATH, payload)
    return payload


def parse_utc_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def worker_transport_cooldown_seconds() -> int:
    value = os.getenv("A9_WORKER_TRANSPORT_COOLDOWN_SECONDS", str(DEFAULT_WORKER_TRANSPORT_COOLDOWN_SECONDS))
    try:
        return max(0, int(value))
    except ValueError:
        return DEFAULT_WORKER_TRANSPORT_COOLDOWN_SECONDS


def worker_transport_health_state() -> dict[str, Any]:
    ensure_dirs()
    data = read_json_file(WORKER_TRANSPORT_HEALTH_PATH)
    if not data:
        return {
            "schema": "a9.worker_transport_health.v1",
            "status": "unknown",
            "failure_count": 0,
            "consecutive_failures": 0,
            "last_failure_at": "",
            "cooldown_until": "",
            "last_failure": {},
            "updated_at": "",
        }
    return data


def worker_transport_cooldown_gate(
    now: datetime | None = None,
    *,
    requested_backend: str = "",
) -> dict[str, Any] | None:
    state = worker_transport_health_state()
    cooldown_until = parse_utc_datetime(str(state.get("cooldown_until") or ""))
    if not cooldown_until:
        return None
    current = now or datetime.now(timezone.utc)
    if cooldown_until <= current:
        return None
    last_failure = state.get("last_failure", {}) if isinstance(state.get("last_failure"), dict) else {}
    failed_backend = str(last_failure.get("backend") or "")
    if requested_backend and failed_backend and requested_backend != failed_backend:
        return None
    return {
        "status": "blocked",
        "reason": "worker_transport_cooldown",
        "cooldown_until": cooldown_until.isoformat(),
        "consecutive_failures": int(state.get("consecutive_failures") or 0),
        "last_failure": last_failure,
        "requested_backend": requested_backend,
        "health_path": str(WORKER_TRANSPORT_HEALTH_PATH),
    }


def update_worker_transport_health_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    failure = summary.get("worker_failure", {}) if isinstance(summary.get("worker_failure"), dict) else {}
    status = str(summary.get("status") or "")
    previous = worker_transport_health_state()
    previous_consecutive = int(previous.get("consecutive_failures") or 0)
    previous_total = int(previous.get("failure_count") or 0)
    if status == "retryable-worker-transport" or failure.get("category") == "transport":
        now = datetime.now(timezone.utc)
        cooldown_until = now + timedelta(seconds=worker_transport_cooldown_seconds())
        payload = {
            "schema": "a9.worker_transport_health.v1",
            "status": "cooldown",
            "failure_count": previous_total + 1,
            "consecutive_failures": previous_consecutive + 1,
            "last_failure_at": now.isoformat(),
            "cooldown_until": cooldown_until.isoformat(),
            "last_failure": {
                "task_id": summary.get("task_id", ""),
                "run_dir": summary.get("run_dir", ""),
                "status": status,
                "reason": failure.get("reason", ""),
                "backend": summary.get("worker", {}).get("worker_transport_backend", "")
                if isinstance(summary.get("worker"), dict)
                else "",
            },
            "updated_at": now.isoformat(),
        }
        write_json(WORKER_TRANSPORT_HEALTH_PATH, payload)
        summary["worker_transport_health"] = payload
        return payload
    if status == "pass" and previous.get("status") in {"cooldown", "degraded"}:
        payload = {
            **previous,
            "status": "ok",
            "consecutive_failures": 0,
            "cooldown_until": "",
            "updated_at": utc_now(),
            "last_recovery": {
                "task_id": summary.get("task_id", ""),
                "run_dir": summary.get("run_dir", ""),
                "status": status,
            },
        }
        write_json(WORKER_TRANSPORT_HEALTH_PATH, payload)
        summary["worker_transport_health"] = payload
        return payload
    summary["worker_transport_health"] = previous
    return previous


def update_worker_transport_health_from_probe(probe: dict[str, Any]) -> dict[str, Any]:
    previous = worker_transport_health_state()
    if probe.get("status") in {"ok", "skipped"}:
        payload = {
            **previous,
            "schema": "a9.worker_transport_health.v1",
            "status": "ok" if probe.get("status") == "ok" else "skipped",
            "consecutive_failures": 0,
            "cooldown_until": "",
            "last_probe": probe,
            "updated_at": utc_now(),
        }
        write_json(WORKER_TRANSPORT_HEALTH_PATH, payload)
        return payload
    now = datetime.now(timezone.utc)
    cooldown_until = now + timedelta(seconds=worker_transport_cooldown_seconds())
    payload = {
        "schema": "a9.worker_transport_health.v1",
        "status": "cooldown",
        "failure_count": int(previous.get("failure_count") or 0) + 1,
        "consecutive_failures": int(previous.get("consecutive_failures") or 0) + 1,
        "last_failure_at": now.isoformat(),
        "cooldown_until": cooldown_until.isoformat(),
        "last_failure": {
            "task_id": "worker_transport_probe",
            "run_dir": probe.get("probe_dir", ""),
            "status": "retryable-worker-transport",
            "reason": probe.get("reason", ""),
            "backend": probe.get("backend", ""),
        },
        "last_probe": probe,
        "updated_at": now.isoformat(),
    }
    write_json(WORKER_TRANSPORT_HEALTH_PATH, payload)
    return payload


def worker_transport_probe(timeout_seconds: int = 45, *, ignore_user_config: bool = False) -> dict[str, Any]:
    ensure_dirs()
    transport = resolved_worker_transport()
    backend = str(transport.get("backend") or "")
    probe_dir = WORKER_TMP_DIR / f"transport-probe-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    probe_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = probe_dir / "stdout.jsonl"
    stderr_path = probe_dir / "stderr.log"
    final_path = probe_dir / "final.md"
    if backend != "codex_exec":
        probe = {
            "status": "skipped",
            "backend": backend,
            "reason": "live probe currently supports codex_exec only",
            "probe_dir": str(probe_dir),
            "checked_at": utc_now(),
        }
        update_worker_transport_health_from_probe(probe)
        return probe
    model, model_source = resolved_worker_model(None)
    cmd = [
        "env",
        f"CODEX_HOME={WORKER_CODEX_HOME}",
        f"HOME={WORKER_CODEX_HOME}",
        f"TMPDIR={WORKER_TMP_DIR}",
        "codex",
        "exec",
        "--json",
        "--ephemeral",
        "--model",
        model,
        "-C",
        str(ROOT),
    ]
    if ignore_user_config:
        cmd.append("--ignore-user-config")
    cmd.extend(["--output-last-message", str(final_path), "Return exactly: probe-ok"])
    started = time.monotonic()
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        proc = subprocess.run(
            ["timeout", f"{max(1, int(timeout_seconds))}s", *cmd],
            cwd=ROOT,
            text=True,
            stdout=stdout,
            stderr=stderr,
            check=False,
        )
    elapsed = round(time.monotonic() - started, 3)
    stdout_text = stdout_path.read_text(encoding="utf-8", errors="backslashreplace")
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="backslashreplace")
    final_text = final_path.read_text(encoding="utf-8", errors="backslashreplace").strip() if final_path.exists() else ""
    exhausted = worker_transport_exhausted_text_reason(stdout_text + "\n" + stderr_text)
    ok = proc.returncode == 0 and final_text == "probe-ok" and not exhausted
    reason = "probe_ok" if ok else exhausted or f"probe_failed_return_code:{proc.returncode}"
    probe = {
        "status": "ok" if ok else "failed",
        "backend": backend,
        "model": model,
        "model_source": model_source,
        "ignore_user_config": ignore_user_config,
        "return_code": proc.returncode,
        "elapsed_seconds": elapsed,
        "reason": reason,
        "probe_dir": str(probe_dir),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "final_path": str(final_path),
        "checked_at": utc_now(),
    }
    update_worker_transport_health_from_probe(probe)
    return probe


def runtime_control_paused() -> bool:
    state = runtime_control_state()
    return bool(state.get("paused"))


def runtime_control_blocks_claim() -> dict[str, Any] | None:
    state = runtime_control_state()
    if not state.get("paused"):
        return None
    return {
        "status": "paused",
        "reason": state.get("reason") or "monitor_intervention_pause",
        "intervention_id": state.get("last_intervention", {}).get("intervention_id")
        if isinstance(state.get("last_intervention"), dict)
        else None,
    }


def monitor_intervention_task_prompt(command: dict[str, Any], *, phase: str) -> str:
    evidence_refs = command.get("evidence_refs") if isinstance(command.get("evidence_refs"), list) else []
    evidence_text = "\n".join(f"- {ref}" for ref in evidence_refs[:20])
    decision_lines: list[str] = []
    if phase == "repair":
        decision_lines = [
            "decision_status: decided",
            "problem: The referenced run is monitor-blocked and requires bounded repair of the specific failed evidence.",
            "system_requirement: Execute only the requested monitor repair intervention against the supplied evidence refs.",
            "out_of_scope: new product scope, broad refactors, unrelated gate changes, and unrelated file edits.",
            "allowed_execution: inspect supplied evidence refs, produce deterministic SEARCH/REPLACE repair blocks, and rely on supervisor declared checks.",
        ]
    return "\n".join(
        [
            *decision_lines,
            f"monitor_intervention_action: {command.get('action')}",
            f"monitor_intervention_id: {command.get('intervention_id')}",
            f"source_task_id: {command.get('task_id') or ''}",
            f"source_run_id: {command.get('run_id') or ''}",
            f"reason: {command.get('reason') or ''}",
            "mainline_requirement: Execute only the requested monitor intervention. Keep business/data model first, performance second. Do not add hard gates unless the requirement is already stable.",
            f"phase_intent: {phase}",
            "evidence_refs:",
            evidence_text or "- none",
        ]
    )


def optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def apply_monitor_approval_effect(
    command: dict[str, Any],
    intervention: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    action = str(command.get("action") or "").strip().lower()
    flow_id = str(command.get("flow_id") or "").strip()
    expected_revision = optional_int(command.get("flow_expected_revision") or command.get("expected_revision"))
    if not flow_id or expected_revision is None:
        updated = write_runtime_control_state(
            {
                **state,
                "last_intervention": intervention,
                "last_decision_action": action,
                "last_decision_reason": command.get("reason"),
                "last_decision_status": "missing_flow_contract",
            }
        )
        return {
            "status": "recorded",
            "mode": "decision_only",
            "action": action,
            "reason": "missing_flow_contract",
            "runtime_state_path": str(RUNTIME_CONTROL_STATE_PATH),
            "state": updated,
        }

    next_status = "approved" if action == "approve" else "rejected"
    flow_transition = transition_managed_flow(
        flow_id=flow_id,
        expected_revision=expected_revision,
        expected_last_seq=optional_int(command.get("flow_expected_last_seq")),
        sequence=optional_int(command.get("flow_sequence")),
        next_status=next_status,
        actor=str(command.get("actor") or "monitor"),
        reason=str(command.get("reason") or f"monitor_{action}"),
        evidence_id=str(command.get("evidence_id") or command.get("intervention_id") or ""),
    )
    updated = write_runtime_control_state(
        {
            **state,
            "last_intervention": intervention,
            "last_decision_action": action,
            "last_decision_reason": command.get("reason"),
            "last_flow_transition": flow_transition,
        }
    )
    return {
        "status": "applied" if flow_transition.get("status") in {"pass", "skipped"} else "degraded",
        "mode": "managed_flow_transition",
        "action": action,
        "flow_transition": flow_transition,
        "runtime_state_path": str(RUNTIME_CONTROL_STATE_PATH),
        "state": updated,
    }


def apply_monitor_intervention_effect(command: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    action = str(command.get("action") or "").strip().lower()
    intervention = {
        "intervention_id": command.get("intervention_id"),
        "action": action,
        "reason": command.get("reason"),
        "actor": command.get("actor"),
        "task_id": command.get("task_id"),
        "run_id": command.get("run_id"),
        "idempotency_key": command.get("idempotency_key"),
        "applied_at": utc_now(),
    }
    state = runtime_control_state()
    if action == "pause":
        updated = write_runtime_control_state(
            {
                **state,
                "paused": True,
                "status": "paused",
                "reason": command.get("reason") or "monitor_intervention_pause",
                "last_intervention": intervention,
            }
        )
        return {
            "status": "applied",
            "mode": "runtime_state",
            "action": action,
            "runtime_state_path": str(RUNTIME_CONTROL_STATE_PATH),
            "paused": True,
            "state": updated,
        }
    if action == "resume":
        updated = write_runtime_control_state(
            {
                **state,
                "paused": False,
                "status": "running",
                "reason": command.get("reason") or "monitor_intervention_resume",
                "last_intervention": intervention,
            }
        )
        return {
            "status": "applied",
            "mode": "runtime_state",
            "action": action,
            "runtime_state_path": str(RUNTIME_CONTROL_STATE_PATH),
            "paused": False,
            "state": updated,
        }
    if action in {"repair", "route_to_debate"}:
        phase = "repair" if action == "repair" else "mechanism_extract"
        task_prefix = "operator-repair" if action == "repair" else "operator-debate"
        task_ref = compact_task_ref(str(command.get("task_id") or command.get("run_id") or command.get("intervention_id") or "monitor"))
        queued = enqueue_task_file(
            f"{task_prefix}-{task_ref}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            monitor_intervention_task_prompt(command, phase=phase),
            phase=phase,
            checks=[],
            timeout_seconds=3600,
            idle_timeout_seconds=300,
            max_attempts=1,
        )
        updated = write_runtime_control_state(
            {
                **state,
                "last_intervention": intervention,
                "last_queued_task_path": str(queued),
                "last_queued_task_phase": phase,
            }
        )
        return {
            "status": "applied",
            "mode": "queue_task",
            "action": action,
            "queued_task_path": str(queued),
            "queued_task_phase": phase,
            "runtime_state_path": str(RUNTIME_CONTROL_STATE_PATH),
            "state": updated,
        }
    if action in {"approve", "reject"}:
        return apply_monitor_approval_effect(command, intervention, state)
    updated = write_runtime_control_state(
        {
            **state,
            "last_intervention": intervention,
            "last_decision_action": action,
            "last_decision_reason": command.get("reason"),
        }
    )
    return {
        "status": "recorded",
        "mode": "decision_only",
        "action": action,
        "runtime_state_path": str(RUNTIME_CONTROL_STATE_PATH),
        "state": updated,
    }


def claim_next_task() -> Task | None:
    ensure_dirs()
    if runtime_control_paused():
        return None
    for path in sorted(QUEUE_DIR.glob("*.md")):
        try:
            candidate = parse_task(path)
        except Exception:
            candidate = None
        if candidate is not None:
            blockers = task_quality_blockers(candidate.task_quality_warnings)
            if blockers:
                blocked_path = BLOCKED_DIR / path.name
                suffix = 1
                while blocked_path.exists():
                    suffix += 1
                    blocked_path = BLOCKED_DIR / f"{path.stem}-{suffix}{path.suffix}"
                block_record = {
                    "status": "blocked",
                    "kind": "task_quality_block",
                    "task_id": candidate.task_id,
                    "phase": candidate.phase,
                    "blocked_at": utc_now(),
                    "blockers": blockers,
                    "source_path": str(path),
                    "blocked_path": str(blocked_path),
                    "reason": "task_contract_invalid_before_worker_claim",
                }
                audit_path = BLOCKED_DIR / f"{path.stem}.quality-block.json"
                block_record["audit_path"] = str(audit_path)
                write_json(audit_path, block_record)
                try:
                    os.replace(path, blocked_path)
                except FileNotFoundError:
                    continue
                except OSError:
                    continue
                record_active_plan_task_quality_block(candidate, block_record)
                continue
        claimed = RUNNING_DIR / path.name
        try:
            os.replace(path, claimed)
        except FileNotFoundError:
            continue
        except OSError:
            continue
        return parse_task(claimed)
    return None


def parse_utc_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def running_process_contains(text: str) -> bool:
    if not text:
        return False
    proc = run_cmd_no_raise(["ps", "-eo", "args"], cwd=ROOT)
    return proc.returncode == 0 and text in proc.stdout


def process_pid_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def running_lease_is_orphaned(lease: dict[str, Any], *, max_age_seconds: int = 60) -> tuple[bool, str]:
    run_dir_text = str(lease.get("run_dir") or "")
    if not run_dir_text:
        return False, "missing_run_dir"
    run_dir = Path(run_dir_text)
    if (run_dir / "summary.json").exists():
        return False, "summary_exists"
    started_at = parse_utc_datetime(lease.get("started_at"))
    if started_at is None:
        return False, "missing_started_at"
    age_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()
    if age_seconds < max_age_seconds:
        return False, "lease_not_old_enough"
    worker_pid = lease.get("worker_pid")
    if process_pid_alive(worker_pid):
        return False, "worker_pid_alive"
    if running_process_contains(run_dir_text):
        return False, "worker_process_alive"
    return True, "no_live_worker_process"


def interrupt_running_task(
    lease_path: Path,
    lease: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    ensure_dirs()
    task_id = str(lease.get("task_id") or lease_path.stem)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target_json = INTERRUPTED_DIR / f"{lease_path.stem}-interrupted-{suffix}.json"
    target_md = INTERRUPTED_DIR / f"{lease_path.stem}-interrupted-{suffix}.md"
    task_md = RUNNING_DIR / f"{lease_path.stem}.md"
    interrupted = {
        **lease,
        "status": "interrupted",
        "interrupted_at": utc_now(),
        "interrupt_reason": reason,
        "lease_path": str(lease_path),
        "interrupted_task_json": str(target_json),
        "interrupted_task_md": str(target_md) if task_md.exists() else "",
    }
    write_json(target_json, interrupted)
    if task_md.exists():
        shutil.move(str(task_md), str(target_md))
    lease_path.unlink(missing_ok=True)
    run_dir = Path(str(lease.get("run_dir") or ""))
    if str(run_dir):
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json(run_dir / "orphaned_interruption.json", interrupted)
        status = "retryable-worker-interrupted"
        summary = {
            **lease,
            "finished_at": utc_now(),
            "status": status,
            "phase": lease.get("phase", ""),
            "task_path": str(task_md),
            "worker": {
                "return_code": None,
                "timed_out": False,
                "idle_timed_out": False,
                "transport_stopped": False,
                "event_count": 0,
                "event_bytes": 0,
                "stderr_path": str(run_dir / "stderr.log"),
                "events_path": str(run_dir / "events.jsonl"),
            },
            "worker_failure": {
                "status": status,
                "category": "interrupted",
                "reason": reason,
                "matched_pattern": "orphaned_running_task",
            },
            "checks": [],
            "guard_summary": {},
            "context_pressure": {},
            "interrupted": interrupted,
            "persistence": {"mysql": {"status": "skipped"}, "redis": {"status": "skipped"}},
        }
        write_json(run_dir / "summary.json", summary)
        write_json(
            run_dir / "state.json",
            {
                "schema": "a9.run_state.v1",
                "task_id": task_id,
                "status": status,
                "checkpoint_id": f"{task_id}:interrupted:{suffix}",
                "interrupted": interrupted,
            },
        )
        with (run_dir / "evidence.jsonl").open("a", encoding="utf-8") as evidence_file:
            evidence_file.write(
                json.dumps(
                    {
                        "schema": "a9.evidence.v1",
                        "kind": "orphaned_interruption",
                        "task_id": task_id,
                        "status": status,
                        "reason": reason,
                        "interrupted_at": interrupted["interrupted_at"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return {"task_id": task_id, "status": "interrupted", "reason": reason, "target_json": str(target_json)}


def archive_completed_running_lease(
    lease_path: Path,
    lease: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    ensure_dirs()
    task_id = str(lease.get("task_id") or lease_path.stem)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target_json = INTERRUPTED_DIR / f"{lease_path.stem}-stale-running-{suffix}.json"
    target_md = INTERRUPTED_DIR / f"{lease_path.stem}-stale-running-{suffix}.md"
    task_md = RUNNING_DIR / f"{lease_path.stem}.md"
    archived = {
        **lease,
        "status": "stale-running-archived",
        "archived_at": utc_now(),
        "archive_reason": reason,
        "lease_path": str(lease_path),
        "archived_task_json": str(target_json),
        "archived_task_md": str(target_md) if task_md.exists() else "",
    }
    write_json(target_json, archived)
    if task_md.exists():
        shutil.move(str(task_md), str(target_md))
    lease_path.unlink(missing_ok=True)
    run_dir = Path(str(lease.get("run_dir") or ""))
    if str(run_dir):
        run_dir.mkdir(parents=True, exist_ok=True)
        with (run_dir / "evidence.jsonl").open("a", encoding="utf-8") as evidence_file:
            evidence_file.write(
                json.dumps(
                    {
                        "schema": "a9.evidence.v1",
                        "kind": "stale_running_lease_archived",
                        "task_id": task_id,
                        "status": "stale-running-archived",
                        "reason": reason,
                        "archived_at": archived["archived_at"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return {"task_id": task_id, "status": "stale-running-archived", "reason": reason, "target_json": str(target_json)}


def reconcile_orphaned_running_tasks(*, max_age_seconds: int = 60) -> list[dict[str, Any]]:
    ensure_dirs()
    reconciled: list[dict[str, Any]] = []
    for lease_path in sorted(RUNNING_DIR.glob("*.json")):
        lease = read_json_file(lease_path)
        if not lease:
            continue
        run_dir = Path(str(lease.get("run_dir") or ""))
        if run_dir and (run_dir / "summary.json").exists():
            reconciled.append(
                archive_completed_running_lease(
                    lease_path,
                    lease,
                    reason="summary_exists_stale_running_lease",
                )
            )
            continue
        if run_dir and (run_dir / "final.md").exists():
            reconciled.append(
                archive_completed_running_lease(
                    lease_path,
                    lease,
                    reason="final_exists_without_summary_stale_running_lease",
                )
            )
            continue
        orphaned, reason = running_lease_is_orphaned(lease, max_age_seconds=max_age_seconds)
        if orphaned:
            reconciled.append(interrupt_running_task(lease_path, lease, reason=reason))
    return reconciled


def task_workspace_root(task: Task) -> Path:
    raw = str(task.workspace_root or "").strip()
    if not raw:
        return ROOT
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def git_head(root: Path | None = None) -> str:
    return run_cmd(["git", "rev-parse", "HEAD"], cwd=root or ROOT).stdout.strip()


SUPERVISOR_PROCESS_REPO_HEAD = ""


def supervisor_process_repo_head() -> str:
    global SUPERVISOR_PROCESS_REPO_HEAD
    if not SUPERVISOR_PROCESS_REPO_HEAD:
        try:
            SUPERVISOR_PROCESS_REPO_HEAD = git_head()
        except RuntimeError:
            SUPERVISOR_PROCESS_REPO_HEAD = "unknown"
    return SUPERVISOR_PROCESS_REPO_HEAD


def git_head_for_workspace(root: Path) -> str:
    return git_head() if root.resolve() == ROOT.resolve() else git_head(root)


def approx_token_count(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def token_budget() -> int:
    value = os.getenv("A9_CONTEXT_TOKEN_BUDGET", str(DEFAULT_CONTEXT_TOKEN_BUDGET))
    try:
        return max(4000, int(value))
    except ValueError:
        return DEFAULT_CONTEXT_TOKEN_BUDGET


def section_token_budgets_for_phase(phase: str, total_budget: int) -> dict[str, int]:
    """Route context budget by phase instead of sending every worker the same large packet."""
    phase_budget = PHASE_SECTION_TOKEN_BUDGETS.get(phase, PHASE_SECTION_TOKEN_BUDGETS["implement"])
    section_budgets = {**SECTION_TOKEN_BUDGETS, **phase_budget}
    # Keep previous-context budget large enough for deterministic head-summary + tail reserve.
    minimum_previous_context = SUMMARY_MIN_HEAD_BUDGET + SUMMARY_RESERVED_TAIL_TOKENS
    section_budgets["previous_context"] = max(minimum_previous_context, section_budgets["previous_context"])
    scale = min(1.0, total_budget / sum(section_budgets.values()))
    if scale < 1.0:
        section_budgets = {
            name: max(256, int(value * scale)) for name, value in section_budgets.items()
        }
    return section_budgets


def section_token_budgets_for_task(task: Task, total_budget: int) -> dict[str, int]:
    section_budgets = section_token_budgets_for_phase(task.phase, total_budget)
    if not task_is_observation_only(task):
        return section_budgets
    observation_profile = {
        "doctrine": 700,
        "method": 900,
        "task": min(section_budgets["task"], 2600),
        "previous_context": 700,
        "repo_map": 1100,
        "reference_mechanisms": 350,
        "contract": 1000,
    }
    section_budgets.update(observation_profile)
    return section_budgets


def truncate_to_token_budget(text: str, budget: int, *, keep: str = "head") -> str:
    if budget <= 0 or approx_token_count(text) <= budget:
        return text
    char_budget = max(0, budget * 4)
    marker = "\n...[truncated by A9 token budget]...\n"
    marker_budget = len(marker)
    if char_budget <= marker_budget:
        return text[:char_budget]
    remaining = char_budget - marker_budget
    if keep == "tail":
        return marker + text[-remaining:]
    if keep == "middle":
        head = remaining // 2
        tail = remaining - head
        return text[:head] + marker + text[-tail:]
    return text[:remaining] + marker


def normalize_context_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


def is_noise_line(line: str) -> bool:
    stripped = normalize_context_line(line)
    if not stripped:
        return True
    return any(pattern.search(stripped) for pattern in NOISE_PATTERNS)


def append_unique_limited(items: list[str], value: str, seen: set[str], limit: int) -> None:
    normalized = normalize_context_line(value)
    if not normalized or normalized in seen or is_noise_line(normalized):
        return
    if len(items) >= limit:
        return
    seen.add(normalized)
    items.append(normalized)


def text_to_messages(text: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    current_role = "user"
    current_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        role = ""
        if stripped.startswith("# USER"):
            role = "user"
        elif stripped.startswith("# ASSISTANT"):
            role = "assistant"
        if role:
            if current_lines:
                messages.append({"role": current_role, "content": "\n".join(current_lines).strip()})
            current_role = role
            current_lines = []
            continue
        current_lines.append(line)
    if current_lines:
        messages.append({"role": current_role, "content": "\n".join(current_lines).strip()})
    return [message for message in messages if message["content"]]


def summarize_messages_deterministic(messages: list[dict[str, str]], budget: int) -> list[dict[str, str]]:
    headings: list[str] = []
    bullets: list[str] = []
    references: list[str] = []
    status_lines: list[str] = []
    heading_seen: set[str] = set()
    bullet_seen: set[str] = set()
    reference_seen: set[str] = set()
    status_seen: set[str] = set()
    file_re = re.compile(r"[\w./-]+\.(?:py|rs|ts|tsx|js|jsx|md|toml|yml|yaml|sql|json)")
    symbol_re = re.compile(r"\b(?:def|class|fn|struct|enum|impl|function|CREATE TABLE|CREATE INDEX)\s+[\w_]+")

    for message in messages:
        role = message["role"].upper()
        for line in message["content"].splitlines():
            stripped = line.strip()
            if is_noise_line(stripped):
                continue
            if stripped.startswith("#"):
                append_unique_limited(headings, f"{role}: {stripped}", heading_seen, 20)
            if stripped.startswith(("-", "*")):
                append_unique_limited(bullets, f"{role}: {stripped}", bullet_seen, 30)
            if re.search(r"\b(pass|failed|error|timeout|needs-repair|needs-followup|blocked|TODO|FIXME)\b", stripped, re.I):
                append_unique_limited(status_lines, f"{role}: {stripped}", status_seen, 20)
            for match in file_re.finditer(stripped):
                append_unique_limited(references, f"file:{match.group(0)}", reference_seen, 40)
            symbol_match = symbol_re.search(stripped)
            if symbol_match:
                append_unique_limited(references, f"symbol:{symbol_match.group(0)}", reference_seen, 40)

    parts = [
        "I asked you to continue from compressed A9 context. This summary is deterministic and preserves concrete references.",
    ]
    if status_lines:
        parts.append("Status signals:\n" + "\n".join(f"- {item}" for item in status_lines))
    if references:
        parts.append("Referenced files/symbols:\n" + "\n".join(f"- {item}" for item in references))
    if headings:
        parts.append("Headings:\n" + "\n".join(f"- {item}" for item in headings))
    if bullets:
        parts.append("Details:\n" + "\n".join(f"- {item}" for item in bullets))
    if messages:
        recent_tail = messages[-1]["content"]
        parts.append(
            "Recent tail preserved verbatim:\n"
            + truncate_to_token_budget(recent_tail, max(128, budget // 4), keep="tail")
        )
    if len(parts) == 1:
        excerpt = "\n\n".join(f"{msg['role'].upper()}: {msg['content']}" for msg in messages)
        parts.append(truncate_to_token_budget(excerpt, max(256, budget - 128), keep="middle"))
    summary = "\n\n".join(parts)
    render_overhead = approx_token_count("# USER\n\n")
    content_budget = max(1, budget - render_overhead)
    return [{"role": "user", "content": truncate_to_token_budget(summary, content_budget, keep="middle")}]


def sanitize_messages_for_context(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    for message in messages:
        seen_lines: set[str] = set()
        lines: list[str] = []
        for line in message["content"].splitlines():
            normalized = normalize_context_line(line)
            if is_noise_line(normalized) or normalized in seen_lines:
                continue
            seen_lines.add(normalized)
            lines.append(line)
        content = "\n".join(lines).strip()
        if content:
            sanitized.append({"role": message["role"], "content": content})
    return sanitized


def compress_messages_aider_style(
    messages: list[dict[str, str]],
    max_tokens: int,
    *,
    depth: int = 0,
) -> list[dict[str, str]]:
    messages = sanitize_messages_for_context(messages)
    sized = [(approx_token_count(message["content"]), message) for message in messages]
    total = sum(tokens for tokens, _message in sized)
    if total <= max_tokens and depth == 0:
        return messages
    if len(messages) <= SUMMARY_MIN_SPLIT or depth > SUMMARY_MAX_DEPTH:
        return summarize_messages_deterministic(messages, max_tokens)

    target_tail_tokens = min(
        max_tokens - SUMMARY_MIN_HEAD_BUDGET,
        max(SUMMARY_RESERVED_TAIL_TOKENS, max_tokens // 2),
    )
    if target_tail_tokens <= 0:
        return summarize_messages_deterministic(messages, max_tokens)

    tail_tokens = 0
    split_index = len(messages)
    for index in range(len(sized) - 1, -1, -1):
        tokens, _message = sized[index]
        if tail_tokens + tokens <= target_tail_tokens:
            tail_tokens += tokens
            split_index = index
        else:
            break

    while split_index > 1 and messages[split_index - 1]["role"] != "assistant":
        split_index -= 1

    if split_index <= SUMMARY_MIN_SPLIT:
        return summarize_messages_deterministic(messages, max_tokens)

    head = messages[:split_index]
    tail = messages[split_index:]
    summary_budget = max(SUMMARY_MIN_HEAD_BUDGET, max_tokens - tail_tokens)
    summary = summarize_messages_deterministic(head, summary_budget)
    combined = summary + tail
    combined_tokens = sum(approx_token_count(message["content"]) for message in combined)
    if combined_tokens <= max_tokens and approx_token_count(render_messages(combined)) <= max_tokens:
        return combined
    return compress_messages_aider_style(combined, max_tokens, depth=depth + 1)


def render_messages(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(
        f"# {message['role'].upper()}\n\n{message['content']}".rstrip() for message in messages
    )


def compress_text_aider_style(text: str, budget: int) -> tuple[str, dict[str, Any]]:
    messages = text_to_messages(text)
    if not messages:
        messages = [{"role": "user", "content": text}]
    original_tokens = sum(approx_token_count(message["content"]) for message in messages)
    compressed_messages = compress_messages_aider_style(messages, budget)
    compressed = render_messages(compressed_messages)
    if approx_token_count(compressed) > budget:
        compressed = truncate_to_token_budget(compressed, budget, keep="tail")
    return compressed, {
        "strategy": "aider_tail_preserve_deterministic_summary",
        "original_messages": len(messages),
        "compressed_messages": len(compressed_messages),
        "original_tokens": original_tokens,
        "compressed_tokens": approx_token_count(compressed),
        "budget_tokens": budget,
    }


def prompt_terms(text: str) -> set[str]:
    return {
        item.lower()
        for item in re.findall(r"[A-Za-z_][A-Za-z0-9_./-]{2,}", text)
        if item.lower() not in {"the", "and", "for", "with", "this", "that", "from", "into"}
    }


def git_tracked_files(root: Path = ROOT) -> list[str]:
    result = run_cmd_no_raise(["git", "ls-files"], cwd=root)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def repo_map_allowed_file(rel_path: str) -> bool:
    blocked_prefixes = (
        ".a9/",
        ".git/",
        "reference-projects/",
        "vendor-src/",
        "target/",
        "node_modules/",
        "__pycache__/",
    )
    if rel_path.startswith(blocked_prefixes):
        return False
    blocked_parts = {".git", "target", "node_modules", "__pycache__", ".pytest_cache"}
    if any(part in blocked_parts for part in Path(rel_path).parts):
        return False
    allowed_suffixes = {
        ".py",
        ".rs",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".md",
        ".toml",
        ".yml",
        ".yaml",
        ".sql",
        ".json",
        ".sh",
    }
    return Path(rel_path).suffix in allowed_suffixes


def extract_repo_symbols(rel_path: str, limit: int = 8, root: Path = ROOT) -> list[str]:
    path = root / rel_path
    if not path.exists() or path.stat().st_size > 200_000:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    patterns = [
        re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.M),
        re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.M),
        re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.M),
        re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.M),
        re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.M),
        re.compile(r"^\s*(?:export\s+)?(?:class|interface|type)\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.M),
        re.compile(r"^\s*CREATE\s+(?:TABLE|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)", re.M | re.I),
        re.compile(r"^#{1,3}\s+(.+)$", re.M),
    ]
    symbols: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            symbol = normalize_context_line(match.group(1))
            if symbol and symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)
            if len(symbols) >= limit:
                return symbols
    return symbols


def score_repo_file(rel_path: str, symbols: list[str], terms: set[str]) -> int:
    lower_path = rel_path.lower()
    score = 0
    important_names = {
        "AGENTS.md",
        "docs/project.md",
        "docs/project.md",
        "docs/reference.md",
        "scripts/a9_supervisor.py",
        "scripts/a9_checkpoint.py",
        "scripts/a9_memory.py",
        "docker-compose.yml",
        "infra/mysql/initdb/001_session_store.sql",
    }
    if rel_path in important_names:
        score += 20
    if lower_path.startswith(("scripts/", "crates/", "infra/", "tests/", "docs/")):
        score += 8
    symbol_text = " ".join(symbols).lower()
    for term in terms:
        if term in lower_path:
            score += 10
        if term in symbol_text:
            score += 6
    return score


def path_matches_allowed_paths(rel_path: str, allowed_paths: list[str]) -> bool:
    if not allowed_paths:
        return True
    normalized = rel_path.strip("/")
    for pattern in allowed_paths:
        item = str(pattern).strip().strip("/")
        if not item:
            continue
        if any(ch in item for ch in "*?[]"):
            if fnmatch.fnmatch(normalized, item):
                return True
            continue
        if normalized == item or normalized.startswith(item.rstrip("/") + "/"):
            return True
    return False


def build_repo_map(
    task_prompt: str,
    budget: int,
    allowed_paths: list[str] | None = None,
    *,
    root: Path = ROOT,
) -> tuple[str, dict[str, Any]]:
    terms = prompt_terms(task_prompt)
    allowed_paths = [str(item) for item in (allowed_paths or [])]
    candidates: list[tuple[int, str, list[str]]] = []
    scanned = 0
    for rel_path in git_tracked_files(root):
        if not repo_map_allowed_file(rel_path):
            continue
        scanned += 1
        in_allowed_scope = path_matches_allowed_paths(rel_path, allowed_paths)
        if allowed_paths and not in_allowed_scope:
            continue
        symbols = extract_repo_symbols(rel_path, root=root)
        score = score_repo_file(rel_path, symbols, terms)
        if in_allowed_scope:
            # Scope guard is the hard task boundary; keep task-local files dominant.
            score += 100
        if score <= 0 and not symbols:
            continue
        candidates.append((score, rel_path, symbols))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    lines = [
        "A9 repo map, inspired by Aider: ranked files and symbols only; raw files are not inlined.",
    ]
    included = 0
    for score, rel_path, symbols in candidates:
        entry_lines = [f"- {rel_path} score={score}"]
        if symbols:
            entry_lines.append("  symbols: " + ", ".join(symbols))
        next_lines = lines + entry_lines
        rendered = "\n".join(next_lines) + "\n"
        if approx_token_count(rendered) > budget:
            break
        lines = next_lines
        included += 1

    repo_map = "\n".join(lines) + "\n"
    return repo_map, {
        "strategy": "aider_ranked_symbol_repo_map",
        "terms": sorted(terms)[:50],
        "allowed_paths": allowed_paths,
        "root": str(root),
        "scanned_files": scanned,
        "candidate_files": len(candidates),
        "included_files": included,
        "budget_tokens": budget,
        "approx_tokens": approx_token_count(repo_map),
    }


def read_budgeted(path: Path, budget: int, *, keep: str = "head") -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="backslashreplace")
    return truncate_to_token_budget(text, budget, keep=keep)


def build_canonical_doctrine_section(task: Task, budget: int) -> tuple[str, str]:
    """Build bounded doctrine/context section.

    Default workers should see a short canonical context index and source pointers,
    while session-context tasks may still hydrate doctrine documents for close reading.
    """
    if task.phase in SESSION_CONTEXT_READ_PHASES:
        doctrine_parts = []
        source_paths = []
        for path in [ROOT / "原始想法需求.md", ROOT / "session-governance.md"]:
            source_paths.append(str(path))
            text = read_budgeted(path, max(512, budget // 3), keep="head")
            if text:
                doctrine_parts.append(f"## {path.name}\n\n{text}")
        return ",".join(source_paths), "\n\n".join(doctrine_parts) or "(none)"

    canonical_sources = [
        "AGENTS.md",
        "docs/project.md",
        "docs/session.md",
        "docs/method.md",
    ]
    doctrinal_notes = [
        "# Canonical Context Index",
        "Workers should load this index first for active mainline and routing rules.",
        "- AGENTS.md: stage model, hard rules, and task-level priorities.",
        "- docs/project.md: product, architecture, runtime and context summary.",
        "- docs/session.md: causal lane and stale-branch memory.",
        "- docs/method.md: requirements method, review closure and execution contract.",
        "- Raw source doctrine references (preserved on disk): 原始想法需求.md, session-governance.md",
        "  Read these only when task packets explicitly allow bounded close reading.",
    ]
    return ",".join(canonical_sources), truncate_to_token_budget("\n".join(doctrinal_notes), budget, keep="head")


def scan_promptware_findings(text: str) -> list[str]:
    findings: list[str] = []
    for pattern in PROMPTWARE_PATTERNS:
        if pattern.search(text):
            findings.append(pattern.pattern)
    return findings


def build_context_router_sections(
    section_inputs: list[dict[str, Any]],
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    rendered_sections: list[tuple[str, str]] = []
    section_meta: list[dict[str, Any]] = []
    blocked_count = 0
    for item in section_inputs:
        name = str(item.get("name", "")).strip()
        source = str(item.get("source", "")).strip()
        role = str(item.get("role", "")).strip() or "reference"
        budget_tokens = int(item.get("budget_tokens", 0) or 0)
        reference_only = bool(item.get("reference_only", False))
        body = str(item.get("body") or "")
        findings: list[str] = []
        blocked = False
        if reference_only and body.strip():
            findings = scan_promptware_findings(body)
            if findings:
                blocked = True
                blocked_count += 1
                body = "[blocked by context router: promptware detected in reference-only section]"
        approx_tokens = approx_token_count(body) if body else 0
        rendered_sections.append((name, body))
        section_meta.append(
            {
                "name": name,
                "source": source,
                "role": role,
                "budget_tokens": budget_tokens,
                "approx_tokens": approx_tokens,
                "reference_only": reference_only,
                "blocked": blocked,
                "findings": findings,
            }
        )

    return rendered_sections, {
        "strategy": "hermes_context_router_v1",
        "sections": section_meta,
        "blocked_sections": blocked_count,
    }


def mempalace_provider_module() -> Any:
    module_name = "a9_mempalace_provider_supervisor"
    module_path = ROOT / "scripts" / "a9_mempalace_provider.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load scripts/a9_mempalace_provider.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def mempalace_wakeup_enabled() -> bool:
    value = os.environ.get("A9_MEMPALACE_WAKEUP_ENABLED")
    if value is None:
        return DEFAULT_MEMPALACE_WAKEUP_ENABLED
    return value.strip().lower() not in {"0", "false", "no", "off"}


def mempalace_wakeup_budget_for_task(task: Task) -> int:
    if task_is_observation_only(task):
        return 0
    if task.phase in {"test", "compare"}:
        return 400
    return 1200


def build_mempalace_recall_section(task: Task, budget_tokens: int = 1200) -> tuple[str, dict[str, Any]]:
    """Build a protocol-shaped MemPalace recall section for worker context.

    MemPalace's official pattern is layered: search returns verbatim drawer
    candidates, get_drawer hydrates exact content, KG/diary remain separate
    continuity channels, and recall is never promoted to truth. A9 injects a
    bounded slice of that protocol instead of a flat summary.
    """
    meta: dict[str, Any] = {
        "enabled": mempalace_wakeup_enabled(),
        "status": "disabled",
        "source": str(MEMPALACE_DRAWERS_PATH),
        "evidence_refs": [],
        "search_hits": [],
        "hydrated_drawers": [],
        "budget_tokens": budget_tokens,
        "protocol": "mempalace_recall_packet_v1",
    }
    if not meta["enabled"]:
        return "", meta
    if budget_tokens <= 0:
        meta["status"] = "skipped_observation_only"
        meta["reason"] = "observation/test tasks use task contract and declared checks without broad recall"
        return "", meta
    if not MEMPALACE_DRAWERS_PATH.exists():
        meta["status"] = "missing_drawers"
        return "", meta
    query = f"{task.task_id} {task.phase} {truncate_to_token_budget(task.prompt, 240, keep='head')}"
    try:
        provider = mempalace_provider_module()
        if hasattr(provider, "build_recall_packet"):
            pack = provider.build_recall_packet(MEMPALACE_DRAWERS_PATH, query=query, limit=4, hydrate=2)
        else:
            pack = provider.build_wakeup(MEMPALACE_DRAWERS_PATH, query=query, limit=3)
    except Exception as exc:
        meta["status"] = "error"
        meta["error"] = f"{type(exc).__name__}: {exc}"
        return "", meta
    recalls = pack.get("fallback_recall") if isinstance(pack, dict) else []
    if not isinstance(recalls, list):
        recalls = pack.get("recall") if isinstance(pack, dict) else []
    refs = pack.get("fallback_evidence_refs") if isinstance(pack, dict) else []
    if not isinstance(refs, list):
        refs = pack.get("evidence_refs") if isinstance(pack, dict) else []
    search_hits = pack.get("search_hits") if isinstance(pack, dict) else []
    hydrated_drawers = pack.get("hydrated_drawers") if isinstance(pack, dict) else []
    official_protocol = pack.get("official_protocol") if isinstance(pack, dict) else []
    meta.update(
        {
            "status": "ok",
            "schema": pack.get("schema") if isinstance(pack, dict) else "",
            "query": query,
            "truth_policy": pack.get("truth_policy") if isinstance(pack, dict) else "recall_not_truth",
            "official_protocol": official_protocol if isinstance(official_protocol, list) else [],
            "search_hit_count": len(search_hits) if isinstance(search_hits, list) else 0,
            "hydrated_drawer_count": len(hydrated_drawers) if isinstance(hydrated_drawers, list) else 0,
            "recall_count": len(recalls) if isinstance(recalls, list) else 0,
            "evidence_refs": refs if isinstance(refs, list) else [],
            "search_hits": search_hits if isinstance(search_hits, list) else [],
            "hydrated_drawers": hydrated_drawers if isinstance(hydrated_drawers, list) else [],
        }
    )
    lines = [
        "MemPalace recall protocol evidence is recall, not truth.",
        "Use it only as a layered, source-preserving recovery hint; task contract and allowed paths remain authoritative.",
        "",
        f"query: {query}",
        "truth_policy: recall_not_truth",
        "protocol_layers:",
        "- wakeup/start context stays small",
        "- search_hits are candidate drawer IDs with source hashes",
        "- hydrated_drawers are drawer-id pointers; hydrate by drawer_id when needed",
        "- fallback_evidence_refs keep raw JSONL/source hash auditability",
        "- KG/diary are separate continuity layers and are not implied by this packet",
        "",
        "must_not_do:",
        "- do not inject full raw recall into execution workers",
        "- do not replace raw JSONL/source hashes with summaries",
        "- do not treat old recalled decisions as current unless validated by task evidence",
        "",
        "search_hits:",
    ]
    if isinstance(search_hits, list):
        for hit in search_hits[:4]:
            if not isinstance(hit, dict):
                continue
            lines.append(
                "- "
                f"drawer_id={hit.get('drawer_id')} "
                f"source_ref={hit.get('source_ref')} "
                f"role={hit.get('role')} "
                f"distance={hit.get('distance')} "
                f"content_hash={hit.get('content_hash')}"
            )
    lines.extend(
        [
            "",
            "hydrated_drawers:",
        ]
    )
    if isinstance(hydrated_drawers, list):
        for drawer in hydrated_drawers[:2]:
            if not isinstance(drawer, dict):
                continue
            metadata = drawer.get("metadata") if isinstance(drawer.get("metadata"), dict) else {}
            source_hash = metadata.get("source_sha256") or metadata.get("content_hash")
            lines.append(
                "- "
                f"drawer_id={drawer.get('drawer_id')} "
                f"source_ref={metadata.get('source_ref')} "
                f"source_hash={source_hash}"
            )
    lines.extend(
        [
            "",
            "fallback_evidence_refs:",
        ]
    )
    for ref in meta["evidence_refs"][:3]:
        if not isinstance(ref, dict):
            continue
        content_hash = ref.get("content_hash")
        source_hash = ref.get("source_sha256") or content_hash
        lines.append(
            "- "
            f"source_ref={ref.get('source_ref')} "
            f"source_hash={source_hash} "
            f"content_hash={content_hash} "
            f"role={ref.get('role')} "
            f"event_kind={ref.get('event_kind')} "
            f"run_id={ref.get('run_id') or ''}"
        )
    lines.append("")
    body = truncate_to_token_budget("\n".join(lines), budget_tokens, keep="head")
    return body, meta


def build_mempalace_wakeup_section(task: Task, budget_tokens: int = 1200) -> tuple[str, dict[str, Any]]:
    """Backward-compatible wrapper for older callers/tests."""
    return build_mempalace_recall_section(task, budget_tokens=budget_tokens)


def build_context_packet(task: Task) -> dict[str, Any]:
    """Build a bounded prompt packet from durable channels.

    This copies the Codex/Aider shape: assemble only what is needed for prompt
    time, track approximate token pressure, keep recent task context as tail,
    and leave raw evidence on disk instead of inlining everything.
    """
    total_budget = token_budget()
    section_budgets = section_token_budgets_for_task(task, total_budget)
    workspace_root = task_workspace_root(task)

    doctrine_source, doctrine = build_canonical_doctrine_section(task, section_budgets["doctrine"])

    previous_context_path = DONE_DIR / f"{artifact_task_ref(task.task_id)}.context.md"
    legacy_context_path = DONE_DIR / f"{task.task_id}.context.md"
    if not path_exists(previous_context_path) and path_exists(legacy_context_path):
        previous_context_path = legacy_context_path
    previous_context = ""
    previous_context_meta: dict[str, Any] = {}
    if path_exists(previous_context_path):
        previous_context_raw = previous_context_path.read_text(
            encoding="utf-8",
            errors="backslashreplace",
        )
        previous_context, previous_context_meta = compress_text_aider_style(
            previous_context_raw,
            section_budgets["previous_context"],
        )

    repo_map, repo_map_meta = build_repo_map(
        task.prompt,
        section_budgets["repo_map"],
        allowed_paths=task.allowed_paths,
        root=workspace_root,
    )

    reference_mechanisms = truncate_to_token_budget(
        """Codex is the first source-level reference for session governance:
- ordered raw history before prompt construction
- history_version changes when history is rewritten
- prompt-time normalization
- token pressure tracking
- compaction as an explicit task with hooks/status
- summary reinjection as handoff, not truth

Aider complements Codex for token cost control:
- keep recent tail with high fidelity
- summarize or omit older head under token pressure
- force filenames/functions/libraries/packages into summaries
- use repo maps instead of dumping whole repositories

LangGraph/mem0/OpenHands/Continue complement persistence:
- checkpoint channels and parent lineage
- scoped memories with history and evidence
- UI/browser streams as adapters, never canonical state
""",
        section_budgets["reference_mechanisms"],
    )
    method_packet = ""
    if strict_worker_envelope_required_for_phase(task.phase):
        method_packet = truncate_to_token_budget(
            requirements_method_packet(),
            section_budgets.get("method", 0),
        )
    mempalace_wakeup_budget = mempalace_wakeup_budget_for_task(task)
    mempalace_wakeup_body, mempalace_wakeup_meta = build_mempalace_recall_section(
        task,
        budget_tokens=mempalace_wakeup_budget,
    )

    evidence_edit_contract = truncate_to_token_budget(worker_evidence_and_edit_contract(task), 900)
    task_prompt = truncate_to_token_budget(worker_prompt_with_default_envelope(task), section_budgets["task"], keep="tail")
    declared_checks_body = "\n".join(f"- {check}" for check in task.checks) if task.checks else "- none"
    contract = truncate_to_token_budget(
        """Run under the A9 supervisor.

Hard rules:
- The project core is copying mature mechanisms, then adapting them with license awareness.
- Prefer Codex session/compaction/context governance before weaker alternatives.
- Task-local hard rules override generic repository guidance when they conflict.
- Do not inline huge raw logs or whole reference repositories.
- Do not search `.a9/tasks/done`, `.a9/worktrees`, or `.a9/runs` as broad roots; read only explicit evidence paths.
- Do not read `docs/session.md` or raw session logs unless phase is `session_refresh`/`session_close_reading`.
- Do not read `docs/session.md`, `docs/mistakes.md`, or `archive/original-ideas/*` as active context unless bounded by prompt evidence plan.
- Do not edit repository files with shell redirection, `tee`, or `sed -i`; output SEARCH/REPLACE blocks in final and let A9 deterministic apply write files.
- Cite local source paths when borrowing ideas from reference projects.
- Preserve details by writing artifacts, evidence, state, checks, and patches.
- Final answer must include files changed, reference ideas used, commands run, test result, and next recommended task.
- Do not invoke nested supervisor or worker loops such as `a9_supervisor.py run-one`, `a9_supervisor.py run-loop`, or `codex exec`.
- Declared checks are executed by the outer A9 supervisor after the worker final; do not call supervisor commands to run them.
- Do not execute exact commands from Task Declared Checks even if the task body says "run declared checks";
  copy them into supervisor_declared_checks and let the outer supervisor run them.
- If the task asks for `strict_worker_envelope: true`, the final answer must include a JSON object
  shaped like OpenClaw/Lobster tool envelopes, but A9 protocol is numeric:
  {"protocolVersion":1,"ok":true,"status":"ok","output":{...}}.
  The envelope must be one complete valid JSON object. Do not emit adjacent sibling JSON objects,
  trailing `,{"summary":...}` fragments, or analysis/summary objects outside `output`.
  The envelope must be valid JSON only; put file paths and evidence as strings, not Markdown links.
  In output, separate worker_commands_run from supervisor_declared_checks; worker self-report is evidence,
  while supervisor-declared checks in the run summary are authoritative.
  Copy supervisor_declared_checks exactly from the Task Declared Checks section; use [] only when it says none.
  If changed_files is non-empty, output.search_replace_blocks must contain machine-readable objects
  with path/search/replace or path/block; do not put prose patch text or apply_patch text in strings.
  copied_mechanisms is only for borrowed external mechanisms/source slices; put ordinary inspected local files in files_validated.
  files_validated is for source/docs validated; put `.git` and runtime metadata evidence in repo_metadata_evidence.
""",
        section_budgets["contract"],
    )

    sections, context_router_meta = build_context_router_sections(
        [
            {
                "name": "A9 Bounded Context Packet",
                "source": "supervisor.template",
                "role": "header",
                "budget_tokens": 0,
                "reference_only": False,
                "body": "",
            },
            {
                "name": "Token Budget",
                "source": "supervisor.budget",
                "role": "control",
                "budget_tokens": 64,
                "reference_only": False,
                "body": f"approx_budget: {total_budget} tokens",
            },
            {
                "name": "Contract",
                "source": "supervisor.contract",
                "role": "policy",
                "budget_tokens": section_budgets["contract"],
                "reference_only": False,
                "body": contract,
            },
            {
                "name": "A9 Worker Method Packet",
                "source": "docs/method.md",
                "role": "policy",
                "budget_tokens": section_budgets.get("method", 0),
                "reference_only": False,
                "body": method_packet,
            },
            {
                "name": "Task Decision Packet",
                "source": str(task.path),
                "role": "policy",
                "budget_tokens": 512,
                "reference_only": False,
                "body": task_decision_packet_prompt(task) if strict_worker_envelope_required_for_phase(task.phase) else "",
            },
            {
                "name": "Evidence And Edit Contract",
                "source": "supervisor.evidence_edit_contract",
                "role": "policy",
                "budget_tokens": 900,
                "reference_only": False,
                "body": evidence_edit_contract,
            },
            {
                "name": "Task Declared Checks",
                "source": str(task.path),
                "role": "authority",
                "budget_tokens": 512,
                "reference_only": False,
                "body": declared_checks_body,
            },
            {
                "name": "Workspace Root",
                "source": str(task.path),
                "role": "authority",
                "budget_tokens": 128,
                "reference_only": False,
                "body": str(workspace_root),
            },
            {
                "name": "Current Task",
                "source": str(task.path),
                "role": "task",
                "budget_tokens": section_budgets["task"],
                "reference_only": False,
                "body": task_prompt,
            },
            {
                "name": "Previous Task Context Tail",
                "source": str(previous_context_path) if previous_context else "none",
                "role": "memory",
                "budget_tokens": section_budgets["previous_context"],
                "reference_only": True,
                "body": previous_context or "(none)",
            },
            {
                "name": "MemPalace Recall Protocol",
                "source": mempalace_wakeup_meta.get("source", "none"),
                "role": "memory",
                "budget_tokens": mempalace_wakeup_budget,
                "reference_only": True,
                "body": mempalace_wakeup_body or "(none)",
            },
            {
                "name": "Repository Map",
                "source": "repo-map",
                "role": "repo_map",
                "budget_tokens": section_budgets["repo_map"],
                "reference_only": True,
                "body": repo_map or "(none)",
            },
            {
                "name": "Reference Mechanisms To Copy",
                "source": "docs/reference.md",
                "role": "reference",
                "budget_tokens": section_budgets["reference_mechanisms"],
                "reference_only": True,
                "body": reference_mechanisms,
            },
            {
                "name": "Doctrine Excerpts",
                "source": doctrine_source or "docs/project.md",
                "role": "doctrine",
                "budget_tokens": section_budgets["doctrine"],
                "reference_only": True,
                "body": doctrine or "(none)",
            },
        ]
    )
    prompt = "\n\n".join(f"# {title}\n\n{body}".rstrip() for title, body in sections) + "\n"
    if approx_token_count(prompt) > total_budget:
        prompt = truncate_to_token_budget(prompt, total_budget, keep="middle")
    return {
        "prompt": prompt,
        "approx_tokens": approx_token_count(prompt),
        "budget_tokens": total_budget,
        "section_budgets": section_budgets,
        "previous_context_path": str(previous_context_path) if previous_context else "",
        "previous_context_compression": previous_context_meta,
        "repo_map": repo_map_meta,
        "context_router": context_router_meta,
        "mempalace_wakeup": mempalace_wakeup_meta,
        "mempalace_recall": mempalace_wakeup_meta,
    }


def create_worktree(task: Task, attempt: int) -> Path:
    task_ref = artifact_task_ref(task.task_id)
    worktree = WORKTREES_DIR / f"{task_ref}-attempt-{attempt}"
    workspace_root = task_workspace_root(task)
    branch_scope = hashlib.sha256(f"{WORKTREES_DIR.resolve()}:{workspace_root}".encode("utf-8")).hexdigest()[:10]
    branch = f"a9-supervisor/{task_ref}-{attempt}-{branch_scope}"
    if worktree.exists():
        return reset_existing_worktree(worktree, workspace_root=workspace_root)
    add_args = ["git", "worktree", "add", "-B", branch, str(worktree), "HEAD"]
    result = run_cmd_no_raise(add_args, cwd=workspace_root)
    if result.returncode != 0:
        run_cmd_no_raise(["git", "worktree", "prune"], cwd=workspace_root)
        result = run_cmd_no_raise(add_args, cwd=workspace_root)
    if result.returncode != 0:
        if "Read-only file system" in result.stdout or "cannot lock ref" in result.stdout:
            worktree = create_isolated_git_copy(worktree, source_root=workspace_root)
            if workspace_root == ROOT:
                hydrate_worker_reference_slices(worktree)
            return worktree
        raise subprocess.CalledProcessError(result.returncode, add_args, output=result.stdout)
    if workspace_root == ROOT:
        hydrate_worker_reference_slices(worktree)
    return worktree


def reset_existing_worktree(worktree: Path, *, workspace_root: Path = ROOT) -> Path:
    """Reuse a stale worker tree only after returning it to the current base."""
    try:
        is_supervisor_worktree = worktree.resolve().is_relative_to(WORKTREES_DIR.resolve())
    except AttributeError:
        try:
            worktree.resolve().relative_to(WORKTREES_DIR.resolve())
            is_supervisor_worktree = True
        except ValueError:
            is_supervisor_worktree = False
    if is_supervisor_worktree and (worktree / ".git").is_dir():
        worktree = create_isolated_git_copy(worktree, replace_existing=True, source_root=workspace_root)
        if workspace_root == ROOT:
            hydrate_worker_reference_slices(worktree)
        return worktree
    base_head = git_head_for_workspace(workspace_root)
    commands = (
        ["git", "restore", "--staged", "."],
        ["git", "reset", "--hard", base_head],
        ["git", "clean", "-fdq"],
    )
    for command in commands:
        result = run_cmd_no_raise(command, cwd=worktree)
        if result.returncode != 0:
            if "Read-only file system" in result.stdout or "cannot lock" in result.stdout:
                worktree = create_isolated_git_copy(worktree, replace_existing=True, source_root=workspace_root)
                if workspace_root == ROOT:
                    hydrate_worker_reference_slices(worktree)
                return worktree
            raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout)
    if workspace_root == ROOT:
        hydrate_worker_reference_slices(worktree)
    return worktree


def create_isolated_git_copy(worktree: Path, *, replace_existing: bool = False, source_root: Path = ROOT) -> Path:
    """Fallback for sandboxes that cannot mutate the shared git metadata."""
    if worktree.exists():
        if not replace_existing:
            return worktree
        shutil.rmtree(worktree)
    worktree.mkdir(parents=True, exist_ok=True)
    for rel in git_tracked_files(source_root):
        src = source_root / rel
        dst = worktree / rel
        if not src.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    commands = [
        ["git", "init"],
        ["git", "config", "user.email", "a9-supervisor@example.invalid"],
        ["git", "config", "user.name", "A9 Supervisor"],
        ["git", "add", "-A"],
        ["git", "commit", "-m", "baseline"],
    ]
    for command in commands:
        result = run_cmd_no_raise(command, cwd=worktree)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout)
    return worktree


def worker_reference_slices() -> list[str]:
    return [
        "reference-projects/hermes-agent/README.md",
        "reference-projects/hermes-agent/LICENSE",
        "reference-projects/hermes-agent/agent/prompt_builder.py",
        "reference-projects/hermes-agent/agent/context_compressor.py",
        "reference-projects/hermes-agent/agent/memory_manager.py",
        "reference-projects/hermes-agent/agent/background_review.py",
        "reference-projects/hermes-agent/agent/curator.py",
        "reference-projects/hermes-agent/agent/trajectory.py",
        "reference-projects/hermes-agent/batch_runner.py",
        "reference-projects/hermes-agent/datagen-config-examples/trajectory_compression.yaml",
        "reference-projects/hermes-agent/tools/delegate_tool.py",
        "reference-projects/hermes-agent/tui_gateway",
        "reference-projects/aider/aider/repomap.py",
        "reference-projects/aider/aider/history.py",
        "reference-projects/aider/aider/prompts.py",
        "reference-projects/codex/codex-rs/core/src/context_manager",
        "reference-projects/codex/codex-rs/core/src/compact.rs",
        "reference-projects/codex/codex-rs/core/src/goals.rs",
        "reference-projects/codex/codex-rs/core/src/context/goal_context.rs",
        "reference-projects/codex/codex-rs/core/templates/goals",
        "reference-projects/codex/codex-rs/state/src/runtime/goals.rs",
        "reference-projects/codex/codex-rs/state/src/model/thread_goal.rs",
        "reference-projects/codex/codex-rs/app-server-transport/src/transport",
        "reference-projects/openclaw/extensions/lobster",
        "reference-projects/openclaw/extensions/policy",
        "reference-projects/openclaw/extensions/memory-core",
        "reference-projects/openclaw/extensions/memory-wiki",
        "reference-projects/ecc/README.md",
        "reference-projects/ecc/LICENSE",
        "reference-projects/ecc/docs/SESSION-ADAPTER-CONTRACT.md",
        "reference-projects/ecc/docs/ECC-2.0-REFERENCE-ARCHITECTURE.md",
        "reference-projects/ecc/docs/token-optimization.md",
        "reference-projects/ecc/docs/continuous-learning-v2-spec.md",
        "reference-projects/ecc/docs/PLAN-PRD-PATTERN.md",
        "reference-projects/barter-rs/barter-integration/src/socket",
        "reference-projects/barter-rs/barter-data/src/streams/consumer.rs",
        "reference-projects/barter-rs/barter/src/engine/command.rs",
        "reference-projects/barter-rs/barter/src/engine/audit",
        "reference-projects/barter-rs/barter/src/strategy",
        "vendor-src",
    ]


def hydrate_worker_reference_slices(worktree: Path) -> list[str]:
    """Copy small local reference slices into isolated worker trees.

    Full reference-projects is intentionally large. A9 workers only need bounded
    source slices for copying mechanisms, and copying avoids write-through
    symlink damage to the operator's reference checkout.
    """
    copied: list[str] = []
    ignore = shutil.ignore_patterns(
        ".git",
        "node_modules",
        "dist",
        "build",
        ".next",
        "coverage",
        "__pycache__",
    )
    for rel in worker_reference_slices():
        src = ROOT / rel
        dst = worktree / rel
        if not src.exists() or dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=ignore)
        elif src.is_file():
            shutil.copy2(src, dst)
        copied.append(rel)
    return copied


def validate_worker_reference_gate(task: Task, worktree: Path, run_dir: Path) -> dict[str, Any]:
    output_path = run_dir / "reference_gate.json"
    declared = prompt_reference_paths(task.prompt)
    items = []
    missing = []
    for rel in declared:
        exists = (worktree / rel).exists()
        item = {"path": rel, "exists": exists}
        items.append(item)
        if not exists:
            missing.append(rel)
    result = {
        "status": "fail" if missing else "pass",
        "kind": "reference_gate",
        "declared_count": len(declared),
        "missing_count": len(missing),
        "items": items,
        "missing_paths": missing,
        "output_path": str(output_path),
        "source": "prompt_declared_reference_paths_in_worker_worktree",
    }
    write_json(output_path, result)
    return result


def build_worker_cmd(
    task: Task,
    worktree: Path,
    run_dir: Path,
    final_path: Path,
    prompt_text: str,
) -> list[str]:
    transport = resolved_worker_transport(task)
    if transport["backend"] == "custom_command":
        template = str(transport.get("custom_command_template") or "")
        if not template:
            reason = "worker transport custom_command selected without custom_command_template"
            return ["bash", "-lc", f"echo {shlex.quote(reason)} >&2; exit 97"]
        return ["bash", "-lc", format_worker_command_template(template, task, worktree, run_dir, final_path)]

    model, _source = resolved_worker_model(task)
    prepare_worker_codex_home()
    cmd = [
        "env",
        f"CODEX_HOME={WORKER_CODEX_HOME}",
        f"HOME={WORKER_CODEX_HOME}",
        f"TMPDIR={WORKER_TMP_DIR}",
        "codex",
        "exec",
        "--json",
        "--ephemeral",
        "--model",
        model,
        "-C",
        str(worktree),
        "--output-last-message",
        str(final_path),
        prompt_text,
    ]
    for feature in worker_disabled_features_for_model(model):
        insert_at = cmd.index("-C")
        cmd[insert_at:insert_at] = ["--disable", feature]
    return cmd


def format_worker_command_template(
    template: str,
    task: Task,
    worktree: Path,
    run_dir: Path,
    final_path: Path,
) -> str:
    prompt_file = run_dir / "prompt.md"
    replacements = {
        "prompt_file": shlex.quote(str(prompt_file)),
        "run_dir": shlex.quote(str(run_dir)),
        "worktree": shlex.quote(str(worktree)),
        "final_path": shlex.quote(str(final_path)),
        "task_id": shlex.quote(task.task_id),
        "phase": shlex.quote(task.phase),
    }
    formatted = template
    for key, value in replacements.items():
        formatted = formatted.replace("{" + key + "}", value)
    return formatted


def resolved_worker_transport(task: Task | None = None) -> dict[str, Any]:
    override = os.getenv("A9_SUPERVISOR_WORKER_CMD")
    if override:
        return {
            "backend": "custom_command",
            "source": "A9_SUPERVISOR_WORKER_CMD",
            "status": "ok",
            "custom_command_template": override,
            "task_phase": task.phase if task else "",
        }
    env_backend = os.getenv("A9_SUPERVISOR_WORKER_TRANSPORT_BACKEND", "").strip()
    env_template = os.getenv("A9_SUPERVISOR_WORKER_CMD_TEMPLATE", "")
    if env_backend:
        if env_backend not in {"codex_exec", "custom_command"}:
            return {
                "backend": DEFAULT_WORKER_TRANSPORT_BACKEND,
                "source": "A9_SUPERVISOR_WORKER_TRANSPORT_BACKEND",
                "status": "invalid_backend_fallback_to_codex_exec",
                "configured_backend": env_backend,
                "custom_command_template": env_template,
                "task_phase": task.phase if task else "",
            }
        return {
            "backend": env_backend,
            "source": "A9_SUPERVISOR_WORKER_TRANSPORT_BACKEND",
            "status": "ok" if env_backend == "codex_exec" or env_template else "missing_custom_command_template",
            "custom_command_template": env_template,
            "task_phase": task.phase if task else "",
        }
    policy = worker_transport_policy_state()
    backend = str(policy.get("backend") or DEFAULT_WORKER_TRANSPORT_BACKEND)
    template = str(policy.get("custom_command_template") or "")
    return {
        "backend": backend,
        "source": "worker_transport_policy.backend",
        "status": "ok" if backend == "codex_exec" or template else "missing_custom_command_template",
        "custom_command_template": template,
        "policy_path": str(WORKER_TRANSPORT_POLICY_PATH),
        "policy_state": policy,
        "task_phase": task.phase if task else "",
    }


def worker_disabled_features_for_model(model: str) -> list[str]:
    model_name = model.lower()
    if "spark" in model_name:
        return ["image_generation"]
    return []


def resolved_worker_model(task: Task | None) -> tuple[str, str]:
    policy = worker_model_policy_state()
    phase = task.phase if task else "implement"
    global_model = os.getenv("A9_SUPERVISOR_MODEL", "").strip()
    if global_model:
        return global_model, "A9_SUPERVISOR_MODEL"
    policy_global_model = str(policy.get("global_model") or "").strip()
    if policy_global_model:
        return policy_global_model, "worker_model_policy.global_model"
    phase_model_env = f"A9_SUPERVISOR_PHASE_MODEL_{phase.upper()}"
    phase_model = os.getenv(phase_model_env, "").strip()
    if phase_model:
        return phase_model, phase_model_env
    policy_phase_models = policy.get("phase_models", {}) if isinstance(policy.get("phase_models"), dict) else {}
    policy_phase_model = str(policy_phase_models.get(phase) or "").strip()
    if policy_phase_model:
        return policy_phase_model, f"worker_model_policy.phase_models.{phase}"
    if phase in {"repair", "test"}:
        critical_model = os.getenv("A9_SUPERVISOR_CRITICAL_MODEL", DEFAULT_CRITICAL_WORKER_MODEL).strip()
        if critical_model:
            return critical_model, "A9_SUPERVISOR_CRITICAL_MODEL"
        policy_critical_model = str(policy.get("critical_model") or "").strip()
        if policy_critical_model:
            return policy_critical_model, "worker_model_policy.critical_model"
    if phase == "reference_scan":
        reference_model = os.getenv("A9_SUPERVISOR_REFERENCE_MODEL", DEFAULT_REFERENCE_SCAN_WORKER_MODEL).strip()
        if reference_model:
            return reference_model, "A9_SUPERVISOR_REFERENCE_MODEL"
        policy_reference_model = str(policy.get("reference_model") or "").strip()
        if policy_reference_model:
            return policy_reference_model, "worker_model_policy.reference_model"
    return DEFAULT_WORKER_MODEL, "DEFAULT_WORKER_MODEL"


def worker_transport_exhausted_payload_text(payload: dict[str, Any]) -> str:
    event_type = str(payload.get("type") or payload.get("event") or payload.get("msg", {}).get("type") or "")
    if event_type == "error":
        return str(payload.get("message") or payload.get("error") or "")
    if event_type == "turn.failed":
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        return str(error.get("message") or payload.get("message") or "")
    msg = payload.get("msg") if isinstance(payload.get("msg"), dict) else {}
    if str(msg.get("type") or "") in {"error", "turn.failed"}:
        error = msg.get("error") if isinstance(msg.get("error"), dict) else {}
        return str(error.get("message") or msg.get("message") or "")
    return ""


def worker_transport_exhausted_reason(payload: dict[str, Any]) -> str:
    text = worker_transport_exhausted_payload_text(payload)
    if not text:
        return ""
    return worker_transport_exhausted_text_reason(text)


def worker_transport_exhausted_text_reason(text: str) -> str:
    for pattern in WORKER_TRANSPORT_EXHAUSTED_PATTERNS:
        match = pattern.search(text)
        if match:
            return f"worker transport exhausted: {bounded_inline(match.group(0), 240)}"
    return ""


def worker_transport_exhausted_stderr_reason(path: Path, *, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="backslashreplace")
    if len(text) > limit:
        text = text[-limit:]
    return worker_transport_exhausted_text_reason(text)


def kill_process_group_if_still_running(proc: subprocess.Popen[str], *, grace_seconds: float = 0.05) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            proc.kill()


def prepare_worker_codex_home() -> None:
    """Give nested Codex workers a writable home inside ignored A9 state."""
    ensure_dirs()
    source_home = Path(os.getenv("A9_SOURCE_CODEX_HOME", str(Path.home() / ".codex")))
    for name in ("auth.json", "config.toml"):
        src = source_home / name
        dst = WORKER_CODEX_HOME / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)


def classify_event(line: str) -> str | None:
    payload = parse_event_payload(line)
    if not payload:
        return None
    event_type = payload.get("type") or payload.get("event") or payload.get("msg", {}).get("type")
    return str(event_type) if event_type else None


def parse_event_payload(line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def aggregate_token_usage(event_summaries: list[dict[str, Any]]) -> dict[str, int]:
    fields = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
    totals = {field: 0 for field in fields}
    for summary in event_summaries:
        usage = summary.get("usage")
        if not isinstance(usage, dict):
            continue
        for field in fields:
            value = usage.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                totals[field] += value
    totals["uncached_input_tokens"] = max(0, totals["input_tokens"] - totals["cached_input_tokens"])
    totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"] + totals["reasoning_output_tokens"]
    return totals


def summarize_thread_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    event_type = payload.get("type") or payload.get("event") or payload.get("msg", {}).get("type")
    if not event_type:
        return None
    summary: dict[str, Any] = {"event_type": str(event_type)}
    if event_type == "thread.started":
        summary["thread_id"] = payload.get("thread_id")
        summary["label"] = "thread_started"
        return summary
    if event_type == "turn.completed":
        usage = payload.get("usage") or {}
        summary["label"] = "turn_completed"
        summary["usage"] = usage
        summary["input_tokens"] = usage.get("input_tokens")
        summary["cached_input_tokens"] = usage.get("cached_input_tokens")
        summary["output_tokens"] = usage.get("output_tokens")
        summary["reasoning_output_tokens"] = usage.get("reasoning_output_tokens")
        return summary
    if event_type == "turn.failed":
        error = payload.get("error") or {}
        summary["label"] = "turn_failed"
        summary["message"] = error.get("message") or payload.get("message")
        return summary
    if event_type == "error":
        summary["label"] = "stream_error"
        summary["message"] = payload.get("message")
        return summary

    item = payload.get("item")
    if not isinstance(item, dict):
        summary["label"] = str(event_type)
        return summary

    item_type = item.get("type") or item.get("details", {}).get("type")
    summary.update(
        {
            "item_id": item.get("id"),
            "item_type": item_type,
            "label": f"{event_type}:{item_type}",
        }
    )
    if item_type == "command_execution":
        command = item.get("command") or item.get("details", {}).get("command")
        output = item.get("aggregated_output") or item.get("details", {}).get("aggregated_output")
        summary.update(
            {
                "command": command,
                "status": item.get("status"),
                "exit_code": item.get("exit_code"),
                "output_preview": truncate_to_token_budget(str(output or ""), 120, keep="tail"),
            }
        )
    elif item_type == "file_change":
        changes = item.get("changes") or item.get("details", {}).get("changes") or []
        summary["changes"] = changes[:50] if isinstance(changes, list) else changes
    elif item_type in {"web_search_call", "web_search"}:
        args = item.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        query = args.get("query")
        if not isinstance(query, str):
            query = item.get("query")
        summary.update(
            {
                "tool": "web_search",
                "query": str(query or ""),
                "status": item.get("status"),
            }
        )
    elif item_type == "mcp_tool_call":
        result = item.get("result") or {}
        arguments = item.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        query = arguments.get("query")
        if not isinstance(query, str):
            query = item.get("query")
        summary.update(
            {
                "server": item.get("server"),
                "tool": item.get("tool"),
                "status": item.get("status"),
                "duration_ms": item.get("duration_ms"),
                "has_meta": isinstance(result, dict) and "_meta" in result,
                "query": str(query or ""),
            }
        )
    elif item_type in {"agent_message", "reasoning"}:
        text = item.get("text") or item.get("details", {}).get("text") or ""
        summary["text_preview"] = truncate_to_token_budget(str(text), 160, keep="tail")
    return summary


def worker_budget_limit(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def worker_event_budget_mode() -> str:
    raw = (os.getenv("A9_WORKER_EVENT_BUDGET_MODE") or DEFAULT_WORKER_EVENT_BUDGET_MODE).strip().lower()
    if raw in {"enforce", "hard", "kill"}:
        return "enforce"
    return "observe"


def blocked_worker_command(command: str) -> str:
    normalized = " ".join(command.split())
    for pattern in BLOCKED_WORKER_COMMAND_PATTERNS:
        if pattern in normalized:
            return pattern
    return ""


def command_reads_runtime_evidence_root(
    command: str,
    bounded_read_paths: list[str] | None = None,
) -> bool:
    normalized = normalize_shell_command(command)
    if not re.search(r"\b(?:rg|grep|find|ls)\b", normalized):
        return False
    bounded_read_paths = [path.rstrip("/") for path in (bounded_read_paths or [])]
    read_targets = command_read_targets(normalized)
    for target in read_targets:
        normalized_target = target[2:] if target.startswith("./") else target
        if any(bounded_read_path_matches(pattern, normalized_target) for pattern in bounded_read_paths):
            continue
        if not any(
            normalized_target == root.rstrip("/")
            or normalized_target.startswith(root.rstrip("/") + "/")
            for root in RUNTIME_EVIDENCE_ROOTS
        ):
            continue
        candidate = Path(normalized_target)
        # Avoid treating bounded evidence file reads as a root read.
        if candidate.suffix:
            continue
        try:
            if candidate.exists() and candidate.is_file():
                continue
        except OSError:
            pass
        return True
    for root in RUNTIME_EVIDENCE_ROOTS:
        escaped = re.escape(root.rstrip("/"))
        if re.search(rf"(?:^|[\s'\"=])(?:\./)?{escaped}/?(?:$|[\s'\"|&;])", normalized):
            return True
    return False


def command_directly_writes_workspace(command: str) -> bool:
    normalized = normalize_shell_command(command)
    prefix_pattern = "|".join(re.escape(item) for item in WORKSPACE_WRITE_PREFIXES)
    path_pattern = rf"(?:\./)?(?:{prefix_pattern})"
    if re.search(rf"(?:>>|>)\s*['\"]?{path_pattern}", normalized):
        return True
    if re.search(rf"\btee\b(?:\s+-[A-Za-z]+)*\s+['\"]?{path_pattern}", normalized):
        return True
    if re.search(r"\bsed\s+-i(?:\s|$)", normalized):
        return True
    return False


def worker_workspace_escape_violation(command: str, worktree: Path | str) -> dict[str, Any]:
    normalized = normalize_shell_command(command)
    worktree_text = str(worktree or "").rstrip("/")
    root_text = str(ROOT).rstrip("/")
    if not worktree_text or worktree_text == root_text:
        return {}
    if not worktree_text.startswith(root_text + "/.a9/worktrees/"):
        return {}
    root_re = re.escape(root_text)
    worktree_re = re.escape(worktree_text)
    cd_root = re.search(rf"\bcd\s+['\"]?{root_re}['\"]?(?:\s|&&|;|\|\||$)", normalized)
    cd_worktree = re.search(rf"\bcd\s+['\"]?{worktree_re}['\"]?(?:\s|&&|;|\|\||$)", normalized)
    if cd_root and not cd_worktree:
        return {
            "kind": "worker_workspace_escape",
            "reason": "worker command changed directory to the main workspace instead of its isolated worktree",
            "command": normalized,
            "workspace_root": root_text,
            "worktree": worktree_text,
        }
    return {}


def live_worker_command_violation(task: Task, command: str, *, rationale: str = "") -> dict[str, Any]:
    normalized = normalize_shell_command(command)
    live_read_budget_stop = prompt_requires_live_read_budget_stop(task.prompt)
    if command_looks_like_test(normalized) and task.checks and command_matches_declared_check(normalized, task.checks):
        return {
            "kind": "worker_declared_check_execution",
            "level": "warn",
            "reason": "declared checks are executed by the outer A9 supervisor after worker final output",
            "command": normalized,
        }
    allowed_read_findings = allowed_read_path_findings(task, normalized)
    if allowed_read_findings:
        finding = allowed_read_findings[0]
        return {
            "kind": finding["kind"],
            "reason": finding["message"],
            "command": normalized,
            "path": finding["path"],
        }
    if command_directly_writes_workspace(normalized):
        return {
            "kind": "direct_workspace_write",
            "reason": "worker tried to edit repository files directly instead of using SEARCH/REPLACE final output",
            "command": normalized,
        }
    if command_looks_like_test(normalized) and task.checks and not command_matches_declared_check(normalized, task.checks):
        return {}
    bounded_paths = bounded_read_paths_from_prompt(task.prompt)
    if command_is_python_readonly_probe_on_allowed_paths(normalized, list(task.allowed_paths) + bounded_paths):
        return {}
    if command_is_low_cost_workspace_orientation(normalized):
        return {}
    if command_is_low_cost_directory_listing(normalized, list(task.allowed_paths) + bounded_paths):
        return {}
    if (
        bounded_paths
        and not command_looks_like_test(normalized)
        and not command_is_single_bounded_read_of_paths(normalized, bounded_paths)
        and not command_is_read_only_of_paths(normalized, bounded_paths)
    ):
        if live_read_budget_stop:
            return {
                "kind": "outside_bounded_read_scope",
                "reason": "worker command is outside the task's explicit bounded read scope",
                "command": normalized,
                "allowed_paths": bounded_paths,
            }
        return {}
    compound_read_findings = compound_wide_read_command_findings(task, normalized)
    if compound_read_findings:
        if command_is_read_only_of_paths(normalized, list(task.allowed_paths) + bounded_paths):
            return {}
        finding = compound_read_findings[0]
        return {
            "kind": finding["kind"],
            "reason": finding["message"],
            "command": normalized,
            "read_count": finding["read_count"],
            "target_count": finding["target_count"],
            "broad_read_count": finding["broad_read_count"],
        }
    if prompt_forbids_rg_files(task.prompt) and "rg --files" in normalized:
        return {}
    if prompt_forbids_ls(task.prompt) and command_runs_ls(normalized):
        return {}
    if prompt_requires_targeted_rg(task.prompt) and command_runs_broad_rg(normalized):
        return {}
    if (
        task.phase in READ_HEAVY_PHASES
        and command_runs_uncapped_rg(normalized)
        and not (bounded_paths and command_is_single_bounded_read_of_paths(normalized, bounded_paths))
        and not command_is_read_only_of_paths(normalized, list(task.allowed_paths) + bounded_paths)
    ):
        if live_read_budget_stop:
            return {
                "kind": "uncapped_rg_command",
                "reason": "worker ran rg without an output cap in a read-heavy live-budget task",
                "command": normalized,
            }
        return {}
    if command_reads_runtime_evidence_root(normalized, bounded_paths):
        if live_read_budget_stop:
            return {
                "kind": "runtime_evidence_root_read",
                "reason": "worker searched a runtime evidence root instead of an exact bounded evidence path",
                "command": normalized,
            }
        return {}
    session_read_finding = forbidden_session_context_read(task, normalized)
    if session_read_finding and session_read_finding.get("level") == "error":
        return {
            "kind": session_read_finding["kind"],
            "reason": session_read_finding["message"],
            "command": normalized,
            "path": session_read_finding["path"],
        }
    for finding in sed_window_governance(task, normalized, rationale=rationale):
        if finding.get("level") == "error":
            return {}
    return {}


def run_worker(task: Task, worktree: Path, run_dir: Path, *, lease_path: Path | None = None) -> dict[str, Any]:
    prompt_path = run_dir / "prompt.md"
    raw_task_path = run_dir / "raw_task.md"
    final_path = run_dir / "final.md"
    events_path = run_dir / "events.jsonl"
    event_summaries_path = run_dir / "event_summaries.jsonl"
    stderr_path = run_dir / "stderr.log"
    context_packet = build_context_packet(task)
    raw_task_path.write_text(task.prompt + "\n", encoding="utf-8")
    prompt_path.write_text(context_packet["prompt"], encoding="utf-8")
    reference_gate = validate_worker_reference_gate(task, worktree, run_dir)
    worker_model, worker_model_source = resolved_worker_model(task)
    worker_transport = resolved_worker_transport(task)

    cmd = build_worker_cmd(task, worktree, run_dir, final_path, context_packet["prompt"])
    if reference_gate["status"] == "fail":
        event_summaries_path.write_text(
            json.dumps(
                {
                    "event_type": "reference_gate.failed",
                    "label": "reference_gate_failed",
                    "missing_paths": reference_gate["missing_paths"],
                    "output_path": reference_gate["output_path"],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        events_path.write_text("", encoding="utf-8")
        stderr_path.write_text("reference gate failed before worker launch\n", encoding="utf-8")
        return {
            "command": cmd,
            "worker_model": worker_model,
            "worker_model_source": worker_model_source,
            "worker_transport": worker_transport,
            "worker_transport_backend": worker_transport.get("backend", ""),
            "worker_transport_source": worker_transport.get("source", ""),
            "return_code": 0,
            "timed_out": False,
            "idle_timed_out": False,
            "idle_timeout_seconds": effective_worker_idle_timeout_seconds(task),
            "budget_stopped": False,
            "budget_stop_kind": "",
            "budget_reason": "",
            "event_count": 1,
            "event_bytes": 0,
            "event_budget": {
                "max_events": worker_budget_limit("A9_WORKER_MAX_EVENTS", DEFAULT_MAX_WORKER_EVENTS),
                "max_event_bytes": worker_budget_limit("A9_WORKER_MAX_EVENT_BYTES", DEFAULT_MAX_WORKER_EVENT_BYTES),
                "mode": worker_event_budget_mode(),
            },
            "budget_observations": [],
            "event_counts": {"reference_gate.failed": 1},
            "event_summary_count": 1,
            "events_path": str(events_path),
            "event_summaries_path": str(event_summaries_path),
            "stderr_path": str(stderr_path),
            "final_path": str(final_path),
            "raw_task_path": str(raw_task_path),
            "actual_token_usage": {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
                "uncached_input_tokens": 0,
                "total_tokens": 0,
            },
            "prompt_approx_tokens": context_packet["approx_tokens"],
            "prompt_budget_tokens": context_packet["budget_tokens"],
            "prompt_section_budgets": context_packet["section_budgets"],
            "previous_context_path": context_packet["previous_context_path"],
            "previous_context_compression": context_packet["previous_context_compression"],
            "repo_map": context_packet["repo_map"],
            "context_router": context_packet.get("context_router", {}),
            "mempalace_wakeup": context_packet.get("mempalace_wakeup", {}),
            "mempalace_recall": context_packet.get("mempalace_recall", {}),
            "reference_gate": reference_gate,
        }
    started = time.monotonic()
    last_output = started
    idle_timeout_seconds = effective_worker_idle_timeout_seconds(task)
    event_counts: dict[str, int] = {}
    event_summaries: list[dict[str, Any]] = []
    seen_event_summaries: set[str] = set()
    last_agent_rationale = ""
    timed_out = False
    idle_timed_out = False
    budget_stopped = False
    budget_reason = ""
    budget_stop_kind = ""
    transport_stopped = False
    transport_reason = ""
    event_count = 0
    event_bytes = 0
    max_events = worker_budget_limit("A9_WORKER_MAX_EVENTS", DEFAULT_MAX_WORKER_EVENTS)
    max_event_bytes = worker_budget_limit("A9_WORKER_MAX_EVENT_BYTES", DEFAULT_MAX_WORKER_EVENT_BYTES)
    event_budget_mode = worker_event_budget_mode()
    budget_observations: list[dict[str, Any]] = []
    observed_event_count_budget = False
    observed_event_bytes_budget = False

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
            start_new_session=True,
        )
        if lease_path is not None:
            lease = read_json_file(lease_path)
            if lease:
                lease["worker_pid"] = proc.pid
                lease["worker_started_at"] = utc_now()
                write_json(lease_path, lease)
        assert proc.stdout is not None
        while True:
            now = time.monotonic()
            if now - started > task.timeout_seconds:
                timed_out = True
                kill_process_group_if_still_running(proc)
                break
            if now - last_output > idle_timeout_seconds:
                idle_timed_out = True
                kill_process_group_if_still_running(proc)
                break

            stderr_exhausted_reason = worker_transport_exhausted_stderr_reason(stderr_path)
            if stderr_exhausted_reason:
                transport_stopped = True
                transport_reason = stderr_exhausted_reason
                kill_process_group_if_still_running(proc)
                break

            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if ready:
                line = proc.stdout.readline()
                if line:
                    last_output = time.monotonic()
                    payload = parse_event_payload(line)
                    if not payload:
                        continue
                    event_count += 1
                    event_bytes += len(line.encode("utf-8"))
                    events.write(line)
                    events.flush()
                    event_type = payload.get("type") or payload.get("event") or payload.get("msg", {}).get("type")
                    if event_type:
                        event_counts[str(event_type)] = event_counts.get(str(event_type), 0) + 1
                    exhausted_reason = worker_transport_exhausted_reason(payload)
                    if exhausted_reason:
                        transport_stopped = True
                        transport_reason = exhausted_reason
                        kill_process_group_if_still_running(proc)
                        break
                    event_summary = summarize_thread_event(payload)
                    if event_summary:
                        fingerprint = json_compact(event_summary)
                        if fingerprint not in seen_event_summaries:
                            seen_event_summaries.add(fingerprint)
                            event_summaries.append(event_summary)
                        if event_summary.get("item_type") in {"agent_message", "reasoning"}:
                            last_agent_rationale = str(event_summary.get("text_preview") or "")
                    if event_summary and event_summary.get("item_type") == "command_execution":
                        command = str(event_summary.get("command", ""))
                        blocked = blocked_worker_command(command)
                        if blocked:
                            budget_stopped = True
                            budget_stop_kind = "command_bounds"
                            budget_reason = f"blocked nested worker command: {blocked}"
                            kill_process_group_if_still_running(proc)
                            break
                        escape = worker_workspace_escape_violation(command, worktree)
                        if escape:
                            budget_stopped = True
                            budget_stop_kind = "workspace_escape"
                            budget_reason = (
                                f"blocked worker command by workspace isolation: {escape.get('kind')} "
                                f"{bounded_inline(escape.get('command', ''), 240)}"
                            )
                            kill_process_group_if_still_running(proc)
                            break
                        violation = live_worker_command_violation(
                            task,
                            command,
                            rationale=last_agent_rationale,
                        )
                        if violation:
                            violation_level = str(violation.get("level") or "").strip().lower()
                            stop_live_violation = violation.get("kind") == "direct_workspace_write" or (
                                prompt_requires_live_read_budget_stop(task.prompt) and violation_level != "warn"
                            )
                            budget_observations.append(
                                {
                                    "kind": violation.get("kind", "command_bounds"),
                                    "level": violation.get("level") or "warn",
                                    "reason": violation.get("reason", "worker command bound observed"),
                                    "command": violation.get("command", ""),
                                    "action": "observe"
                                    if not stop_live_violation
                                    else "stop",
                                }
                            )
                            if stop_live_violation:
                                budget_stopped = True
                                budget_stop_kind = str(violation.get("kind") or "command_bounds")
                                budget_reason = str(violation.get("reason") or "worker command bound violated")
                                kill_process_group_if_still_running(proc)
                                break
                    if event_count > max_events:
                        reason = f"worker event count exceeded {max_events}"
                        if event_budget_mode == "enforce":
                            budget_stopped = True
                            budget_stop_kind = "event_count"
                            budget_reason = reason
                            kill_process_group_if_still_running(proc)
                            break
                        if not observed_event_count_budget:
                            observed_event_count_budget = True
                            budget_observations.append(
                                {
                                    "kind": "event_count",
                                    "reason": reason,
                                    "event_count": event_count,
                                    "max_events": max_events,
                                    "action": "observe",
                                }
                            )
                    if event_bytes > max_event_bytes:
                        reason = f"worker event bytes exceeded {max_event_bytes}"
                        if event_budget_mode == "enforce":
                            budget_stopped = True
                            budget_stop_kind = "event_bytes"
                            budget_reason = reason
                            kill_process_group_if_still_running(proc)
                            break
                        if not observed_event_bytes_budget:
                            observed_event_bytes_budget = True
                            budget_observations.append(
                                {
                                    "kind": "event_bytes",
                                    "reason": reason,
                                    "event_bytes": event_bytes,
                                    "max_event_bytes": max_event_bytes,
                                    "action": "observe",
                                }
                            )
                elif proc.poll() is not None:
                    break
            elif proc.poll() is not None:
                break

        try:
            return_code = proc.wait()
        finally:
            if proc.stdout is not None and not proc.stdout.closed:
                proc.stdout.close()

    with event_summaries_path.open("w", encoding="utf-8") as summaries:
        for item in event_summaries:
            summaries.write(json.dumps(item, ensure_ascii=False) + "\n")

    actual_token_usage = aggregate_token_usage(event_summaries)
    return {
        "command": cmd,
        "worker_model": worker_model,
        "worker_model_source": worker_model_source,
        "worker_transport": worker_transport,
        "worker_transport_backend": worker_transport.get("backend", ""),
        "worker_transport_source": worker_transport.get("source", ""),
        "return_code": return_code,
        "timed_out": timed_out,
        "idle_timed_out": idle_timed_out,
        "idle_timeout_seconds": idle_timeout_seconds,
        "budget_stopped": budget_stopped,
        "budget_stop_kind": budget_stop_kind,
        "budget_reason": budget_reason,
        "transport_stopped": transport_stopped,
        "transport_reason": transport_reason,
        "event_count": event_count,
        "event_bytes": event_bytes,
        "event_budget": {
            "max_events": max_events,
            "max_event_bytes": max_event_bytes,
            "mode": event_budget_mode,
        },
        "budget_observations": budget_observations,
        "event_counts": event_counts,
        "event_summary_count": len(event_summaries),
        "events_path": str(events_path),
        "event_summaries_path": str(event_summaries_path),
        "stderr_path": str(stderr_path),
        "final_path": str(final_path),
        "raw_task_path": str(raw_task_path),
        "actual_token_usage": actual_token_usage,
        "prompt_approx_tokens": context_packet["approx_tokens"],
        "prompt_budget_tokens": context_packet["budget_tokens"],
        "prompt_section_budgets": context_packet["section_budgets"],
        "previous_context_path": context_packet["previous_context_path"],
        "previous_context_compression": context_packet["previous_context_compression"],
        "repo_map": context_packet["repo_map"],
        "context_router": context_packet.get("context_router", {}),
        "mempalace_wakeup": context_packet.get("mempalace_wakeup", {}),
        "mempalace_recall": context_packet.get("mempalace_recall", {}),
        "reference_gate": reference_gate,
    }


def capture_diff(worktree: Path, run_dir: Path) -> dict[str, Any]:
    run_cmd(["git", "add", "-A"], cwd=worktree)
    diff = run_cmd(["git", "diff", "--cached", "--binary"], cwd=worktree).stdout
    diff_path = run_dir / "patch.diff"
    diff_path.write_text(diff, encoding="utf-8", errors="backslashreplace")
    return {"diff_path": str(diff_path), "diff_bytes": len(diff.encode("utf-8"))}


def normalize_worker_patch_path(raw_path: str, root: Path | None, source_root: Path | None = None) -> str:
    path = raw_path.strip()
    if not path:
        return ""
    normalized_text = path.replace("\\", "/")
    marker = "/.a9/worktrees/"
    if marker in normalized_text:
        after = normalized_text.split(marker, 1)[1]
        parts = after.split("/", 1)
        if len(parts) == 2 and parts[1]:
            return parts[1]
    if normalized_text.startswith(".a9/worktrees/"):
        parts = normalized_text.split("/", 3)
        if len(parts) == 4 and parts[3]:
            return parts[3]
    if source_root is not None:
        candidate = Path(path)
        if candidate.is_absolute():
            try:
                return str(candidate.resolve().relative_to(source_root.resolve()))
            except (OSError, ValueError):
                pass
    if root is not None:
        try:
            return str(Path(path).resolve().relative_to(root.resolve()))
        except (OSError, ValueError):
            pass
    return path


def normalize_worker_search_replace_text(
    text: str,
    root: Path | None = None,
    source_root: Path | None = None,
) -> str:
    lines = text.strip().splitlines()
    normalized: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.upper() == "SEARCH/REPLACE":
            continue
        if stripped.startswith("*** Update File: "):
            normalized.append(normalize_worker_patch_path(stripped.split(": ", 1)[1], root, source_root))
            continue
        normalized.append(line)
    return "\n".join(normalized).strip() + "\n" if normalized else ""


def extract_begin_patch_update_blocks(
    text: str,
    root: Path | None = None,
    source_root: Path | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    begin = text.find("*** Begin Patch")
    end = text.find("*** End Patch", begin)
    if begin < 0 or end < 0:
        return "", []
    patch_text = text[begin : end + len("*** End Patch")]
    parts: list[str] = []
    findings: list[dict[str, Any]] = []
    current_path = ""
    search_lines: list[str] = []
    replace_lines: list[str] = []

    def flush_hunk() -> None:
        if not current_path or not search_lines and not replace_lines:
            return
        search_text = "".join(search_lines)
        replace_text = "".join(replace_lines)
        if not search_text:
            findings.append(
                {
                    "level": "warning",
                    "code": "begin_patch.empty_search_unsupported",
                    "scope": "final_message.begin_patch",
                    "message": "ignored Begin Patch hunk without SEARCH-side context",
                    "path": current_path,
                }
            )
            return
        parts.append(
            f"{current_path}\n<<<<<<< SEARCH\n{search_text}=======\n{replace_text}>>>>>>> REPLACE\n"
        )

    for raw_line in patch_text.splitlines(keepends=True):
        line = raw_line.rstrip("\n")
        if line.startswith("*** Update File: "):
            flush_hunk()
            current_path = normalize_worker_patch_path(line.split(": ", 1)[1], root, source_root)
            search_lines = []
            replace_lines = []
            continue
        if line.startswith("*** "):
            flush_hunk()
            search_lines = []
            replace_lines = []
            continue
        if line.startswith("@@"):
            flush_hunk()
            search_lines = []
            replace_lines = []
            continue
        if not current_path:
            continue
        if raw_line.startswith("+"):
            replace_lines.append(raw_line[1:])
        elif raw_line.startswith("-"):
            search_lines.append(raw_line[1:])
        elif raw_line.startswith(" "):
            search_lines.append(raw_line[1:])
            replace_lines.append(raw_line[1:])

    if parts:
        findings.append(
            {
                "level": "info",
                "code": "final_message.begin_patch_update.extracted",
                "scope": "final_message.begin_patch",
                "message": "converted fenced Begin Patch update hunks into SEARCH/REPLACE blocks",
                "count": len(parts),
            }
        )
    return "\n".join(parts), findings


def extract_worker_search_replace_patch(
    text: str,
    root: Path | None = None,
    source_root: Path | None = None,
) -> tuple[str, str | None, list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    candidates = [item for item in find_json_objects(text) if is_worker_envelope_candidate(item)]
    if candidates:
        envelope = candidates[-1]
        output = envelope.get("output")
        blocks = output.get("search_replace_blocks") if isinstance(output, dict) else None
        if isinstance(blocks, list):
            parts: list[str] = []
            for index, item in enumerate(blocks, start=1):
                if not isinstance(item, dict):
                    findings.append(
                        {
                            "level": "warning",
                            "code": "search_replace_blocks.non_object_item",
                            "scope": "envelope.output.search_replace_blocks",
                            "message": "ignored non-object search_replace_blocks item",
                            "index": index,
                        }
                    )
                    continue

                def _build_patch_block(raw: dict[str, Any]) -> str:
                    block = str(raw.get("block") or "").strip()
                    search = raw.get("search")
                    replace = raw.get("replace")
                    if not block and isinstance(search, str) and isinstance(replace, str):
                        search_text = search if search.endswith("\n") else f"{search}\n"
                        replace_text = replace if replace.endswith("\n") else f"{replace}\n"
                        block = f"<<<<<<< SEARCH\n{search_text}=======\n{replace_text}>>>>>>> REPLACE"
                    return block

                path = normalize_worker_patch_path(
                    str(item.get("path") or item.get("file") or "").strip(),
                    root,
                    source_root,
                )
                nested_blocks = item.get("blocks")
                if isinstance(nested_blocks, list):
                    for sub_index, sub_item in enumerate(nested_blocks, start=1):
                        if not isinstance(sub_item, dict):
                            findings.append(
                                {
                                    "level": "warning",
                                    "code": "search_replace_blocks.nested_non_object_block",
                                    "scope": "envelope.output.search_replace_blocks.blocks",
                                    "message": "ignored non-object nested block",
                                    "index": index,
                                    "block_index": sub_index,
                                }
                            )
                            continue
                        sub_path = normalize_worker_patch_path(
                            str(sub_item.get("path") or sub_item.get("file") or path).strip(),
                            root,
                            source_root,
                        )
                        block = _build_patch_block(sub_item)
                        if not sub_path or "<<<<<<< SEARCH" not in block or ">>>>>>> REPLACE" not in block:
                            findings.append(
                                {
                                    "level": "warning",
                                    "code": "search_replace_blocks.malformed_nested_block",
                                    "scope": "envelope.output.search_replace_blocks.blocks",
                                    "message": "ignored malformed nested block",
                                    "index": index,
                                    "block_index": sub_index,
                                }
                            )
                            continue
                        parts.append(f"{sub_path}\n{block}\n")
                    continue

                block = _build_patch_block(item)
                if not path or "<<<<<<< SEARCH" not in block or ">>>>>>> REPLACE" not in block:
                    findings.append(
                        {
                            "level": "warning",
                            "code": "search_replace_blocks.malformed_item",
                            "scope": "envelope.output.search_replace_blocks",
                            "message": "ignored malformed search_replace_blocks item",
                            "index": index,
                        }
                    )
                    continue
                parts.append(f"{path}\n{block}\n")
            if parts:
                findings.append(
                    {
                        "level": "info",
                        "code": "search_replace_blocks.extracted",
                        "scope": "envelope.output.search_replace_blocks",
                        "message": "extracted SEARCH/REPLACE blocks from worker envelope output.search_replace_blocks",
                        "count": len(parts),
                    }
                )
                return "\n".join(parts), "worker_envelope.output.search_replace_blocks", findings

        if isinstance(output, dict):
            for field_name in ("documentation_patch", "patch"):
                patch_value = output.get(field_name)
                if isinstance(patch_value, str) and "<<<<<<< SEARCH" in patch_value and ">>>>>>> REPLACE" in patch_value:
                    normalized_patch = normalize_worker_search_replace_text(patch_value, root, source_root)
                    findings.append(
                        {
                            "level": "info",
                            "code": f"worker_envelope.output.{field_name}.extracted",
                            "scope": f"envelope.output.{field_name}",
                            "message": f"extracted SEARCH/REPLACE patch from worker envelope output.{field_name}",
                        }
                    )
                    return normalized_patch, f"worker_envelope.output.{field_name}", findings

    def _extract_markdown_file_blocks(raw_text: str) -> list[str]:
        parts: list[str] = []
        fence_re = re.compile(r"```[^\n`]*\n(.*?)\n```", re.DOTALL)
        file_header_re = re.compile(r"^###\s*File:\s*(.+?)\s*$")
        for fence in fence_re.finditer(raw_text):
            lines = fence.group(1).splitlines()
            index = 0
            while index < len(lines):
                header = file_header_re.match(lines[index].strip())
                if not header:
                    index += 1
                    continue
                path = header.group(1).strip()
                if index + 1 >= len(lines) or lines[index + 1].strip() != "SEARCH":
                    index += 1
                    continue
                index += 2
                search_lines: list[str] = []
                while index < len(lines) and lines[index].strip() != "REPLACE":
                    search_lines.append(lines[index])
                    index += 1
                if index >= len(lines) or lines[index].strip() != "REPLACE":
                    continue
                index += 1
                replace_lines: list[str] = []
                while index < len(lines) and not file_header_re.match(lines[index].strip()):
                    replace_lines.append(lines[index])
                    index += 1
                search_text = "\n".join(search_lines)
                replace_text = "\n".join(replace_lines)
                if not search_text.endswith("\n"):
                    search_text = f"{search_text}\n"
                if not replace_text.endswith("\n"):
                    replace_text = f"{replace_text}\n"
                parts.append(
                    f"{path}\n<<<<<<< SEARCH\n{search_text}=======\n{replace_text}>>>>>>> REPLACE\n"
                )
        return parts

    markdown_parts = _extract_markdown_file_blocks(text)
    if markdown_parts:
        findings.append(
            {
                "level": "info",
                "code": "final_message.markdown_search_replace_blocks.extracted",
                "scope": "final_message",
                "message": "extracted fenced ### File SEARCH/REPLACE blocks from final message",
                "count": len(markdown_parts),
            }
        )
        return "\n".join(markdown_parts), "final_message.markdown_search_replace_blocks", findings

    begin_patch_parts, begin_patch_findings = extract_begin_patch_update_blocks(text, root, source_root)
    if begin_patch_parts:
        findings.extend(begin_patch_findings)
        return begin_patch_parts, "final_message.begin_patch_update", findings
    findings.extend(begin_patch_findings)

    if "<<<<<<< SEARCH" in text and ">>>>>>> REPLACE" in text:
        return normalize_worker_search_replace_text(text, root, source_root), "final_message", findings
    return "", None, findings


def apply_worker_search_replace(
    worker: dict[str, Any],
    worktree: Path,
    run_dir: Path,
    source_root: Path | None = None,
) -> dict[str, Any]:
    output_path = run_dir / "patch_apply.json"
    patch_path = run_dir / "model_patch.search_replace"
    final_path = Path(worker["final_path"])
    result: dict[str, Any] = {
        "status": "skip",
        "kind": "search_replace_apply",
        "return_code": 0,
        "output_path": str(output_path),
        "patch_path": str(patch_path),
        "patch_source": None,
        "findings": [{"level": "info", "message": "no SEARCH/REPLACE patch in final message"}],
    }
    if not final_path.exists():
        write_json(output_path, result)
        return result

    text = final_path.read_text(encoding="utf-8", errors="backslashreplace")
    patch_text, patch_source, extraction_findings = extract_worker_search_replace_patch(text, worktree, source_root)
    result["patch_source"] = patch_source
    if not patch_text:
        result["findings"].extend(extraction_findings)
        write_json(output_path, result)
        return result

    dirty = run_cmd_no_raise(["git", "status", "--porcelain"], cwd=worktree).stdout.strip()
    if dirty:
        result.update(
            {
                "status": "skip-dirty-worktree",
                "findings": [
                    {
                        "level": "warning",
                        "message": "worker already modified files; deterministic apply skipped",
                        "status_preview": dirty.splitlines()[:20],
                    }
                ],
            }
        )
        write_json(output_path, result)
        return result

    patch_path.write_text(patch_text, encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "a9_patch_apply.py"),
            str(patch_path),
            "--root",
            str(worktree),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {
            "status": "fail",
            "kind": "search_replace_apply",
            "applied_count": 0,
            "applied": [],
            "touched_files": [],
            "findings": [
                {
                    "level": "error",
                    "message": "patch apply returned non-json output",
                    "output_preview": proc.stdout[-2000:],
                }
            ],
        }
    result["return_code"] = proc.returncode
    result["output_path"] = str(output_path)
    result["patch_path"] = str(patch_path)
    result["patch_source"] = patch_source
    result.setdefault("findings", [])
    result["findings"] = extraction_findings + result["findings"]
    write_json(output_path, result)
    return result


def find_json_objects(text: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(value)
    return objects


def is_worker_envelope_candidate(value: dict[str, Any]) -> bool:
    if "ok" not in value:
        return False
    if "protocolVersion" in value:
        return True
    return "status" in value or "error" in value or "requiresApproval" in value


def normalize_worker_envelope_status(status: Any, ok: Any) -> tuple[str, str | None]:
    raw = str(status or "")
    if ok is not True:
        return raw, None
    alias_map = {
        "pass": "ok",
        "success": "ok",
        "completed": "ok",
        "reference_scan_complete": "ok",
    }
    canonical = alias_map.get(raw.strip().lower())
    if canonical:
        return canonical, raw
    return raw, None


def normalize_worker_envelope_protocol_version(protocol_version: Any, ok: Any) -> tuple[Any, Any | None]:
    if ok is not True:
        return protocol_version, None
    alias_map = {
        "1": 1,
        "1.0": 1,
        "openclaw/1": 1,
        "openclaw/v1": 1,
        "openclaw-lobster/v1": 1,
        "openclaw-lobster-v1": 1,
        "openclaw-lobster-worker-envelope/1.0": 1,
        "a9.strict_worker_envelope.v1": 1,
    }
    if protocol_version in {1, "1"}:
        return 1, "1" if protocol_version == "1" else None
    if isinstance(protocol_version, str):
        canonical = alias_map.get(protocol_version.strip().lower())
        if canonical is not None:
            return canonical, protocol_version
    return protocol_version, None


def validate_worker_envelope(task: Task, worker: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    output_path = run_dir / "worker_envelope.json"
    final_path = Path(worker["final_path"])
    required = strict_worker_envelope_required(task)
    result: dict[str, Any] = {
        "status": "skip",
        "kind": "worker_envelope",
        "required": required,
        "output_path": str(output_path),
        "findings": [],
    }
    if not final_path.exists():
        result["status"] = "fail" if required else "skip"
        result["findings"].append({"level": "error" if required else "info", "message": "final message missing"})
        write_json(output_path, result)
        return result

    text = final_path.read_text(encoding="utf-8", errors="backslashreplace")
    candidates = [item for item in find_json_objects(text) if is_worker_envelope_candidate(item)]
    if not candidates:
        result["status"] = "fail" if required else "skip"
        result["findings"].append(
            {
                "level": "error" if required else "info",
                "message": "no worker envelope JSON object found",
            }
        )
        write_json(output_path, result)
        return result

    envelope = candidates[-1]
    result["envelope"] = envelope
    ok = envelope.get("ok")
    protocol_version, normalized_protocol_from = normalize_worker_envelope_protocol_version(
        envelope.get("protocolVersion"), ok
    )
    if normalized_protocol_from is not None:
        envelope["protocolVersion"] = protocol_version
        result["findings"].append(
            {
                "level": "info",
                "message": f"normalized protocolVersion alias from {normalized_protocol_from!r} to {protocol_version!r}",
            }
        )
    status, normalized_from = normalize_worker_envelope_status(envelope.get("status"), ok)
    if normalized_from is not None:
        envelope["status"] = status
        result["findings"].append(
            {
                "level": "info",
                "message": f"normalized status alias from {normalized_from!r} to {status!r}",
            }
        )
    if protocol_version not in {1, "1"}:
        result["findings"].append({"level": "error", "message": "protocolVersion must be 1"})
    if not isinstance(ok, bool):
        result["findings"].append({"level": "error", "message": "ok must be boolean"})
    if ok is False:
        error = envelope.get("error")
        if not isinstance(error, dict) or not error.get("message"):
            result["findings"].append({"level": "error", "message": "error envelope must include error.message"})
        result["status"] = "fail"
    elif ok is True:
        if status not in {"ok", "needs_approval", "cancelled"}:
            result["findings"].append({"level": "error", "message": "status must be ok, needs_approval, or cancelled"})
        if status == "needs_approval":
            approval = envelope.get("requiresApproval")
            if not isinstance(approval, dict):
                result["findings"].append({"level": "error", "message": "needs_approval requires requiresApproval object"})
            else:
                if approval.get("type") != "approval_request":
                    result["findings"].append({"level": "error", "message": "requiresApproval.type must be approval_request"})
                if not approval.get("prompt"):
                    result["findings"].append({"level": "error", "message": "requiresApproval.prompt is required"})
                if not approval.get("resumeToken") and not approval.get("approvalId"):
                    result["findings"].append(
                        {"level": "error", "message": "requiresApproval needs resumeToken or approvalId"}
                    )
        elif status == "ok" and "output" in envelope and not isinstance(envelope.get("output"), (dict, list)):
            result["findings"].append({"level": "error", "message": "output must be an object or list when present"})
        output = envelope.get("output")
        if status == "ok" and isinstance(output, dict):
            if "worker_commands_run" not in output:
                result["findings"].append(
                    {
                        "level": "warn",
                        "message": "output should include worker_commands_run separate from supervisor_declared_checks",
                    }
                )
            if "supervisor_declared_checks" not in output:
                result["findings"].append(
                    {
                        "level": "warn",
                        "message": "output should include supervisor_declared_checks separate from worker_commands_run",
                    }
                )
            elif (
                isinstance(output.get("supervisor_declared_checks"), list)
                and normalize_declared_checks_for_worker_envelope(output.get("supervisor_declared_checks"))
                != normalize_declared_checks_for_worker_envelope(task.checks)
            ):
                result["findings"].append(
                    {
                        "level": "error",
                        "kind": "worker_declared_checks_self_report_mismatch",
                        "message": "worker-reported supervisor_declared_checks differ from task checks; task checks remain authoritative",
                        "expected": normalize_declared_checks_for_worker_envelope(task.checks),
                        "actual": normalize_declared_checks_for_worker_envelope(output.get("supervisor_declared_checks")),
                    }
                )
            search_replace_blocks = output.get("search_replace_blocks")
            if (
                strict_worker_envelope_required(task)
                and "search_replace_blocks" in output
                and (
                    not isinstance(search_replace_blocks, list)
                    or any(not isinstance(item, dict) for item in search_replace_blocks)
                )
            ):
                changed_files = output.get("changed_files")
                search_replace_blocks = output.get("search_replace_blocks")
                result["findings"].append(
                    {
                        "level": "error",
                        "kind": "worker_malformed_search_replace_blocks",
                        "message": "strict worker envelope search_replace_blocks must be a list containing object-shaped patch blocks",
                        "changed_files": [str(item) for item in changed_files] if isinstance(changed_files, list) else [],
                    }
                )
            copied_mechanism_drift = local_paths_reported_as_copied_mechanisms(output.get("copied_mechanisms"))
            if copied_mechanism_drift:
                result["findings"].append(
                    {
                        "level": "warn",
                        "kind": "worker_copied_mechanisms_local_path_drift",
                        "message": "copied_mechanisms should name borrowed external mechanisms or source slices, not local files inspected during validation",
                        "paths": copied_mechanism_drift,
                    }
                )
            files_validated_metadata = repo_metadata_paths_reported_as_files_validated(output.get("files_validated"))
            if files_validated_metadata:
                result["findings"].append(
                    {
                        "level": "warn",
                        "kind": "worker_files_validated_repo_metadata_drift",
                        "message": "files_validated should list source/docs validated; repo/runtime metadata belongs in repo_metadata_evidence",
                        "paths": files_validated_metadata,
                    }
                )
        has_error_finding = any(item.get("level") == "error" for item in result["findings"])
        if has_error_finding:
            result["status"] = "fail"
        elif status == "needs_approval":
            result["status"] = "needs-approval"
        elif status == "cancelled":
            result["status"] = "fail"
        else:
            result["status"] = "pass"
    else:
        result["status"] = "fail"

    write_json(output_path, result)
    return result


def normalize_declared_checks_for_worker_envelope(checks: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for item in checks or []:
        text = str(item).strip()
        if not text:
            continue
        targets = unittest_targets(text)
        if targets:
            normalized.extend(f"python3 -m unittest {target}" for target in targets)
        else:
            normalized.append(text)
    return sorted(normalized)


def local_paths_reported_as_copied_mechanisms(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    local_roots = ("scripts/", "tests/", "docs/", "archive/", ".a9/")
    findings: list[str] = []
    cwd = Path.cwd().resolve()
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        if text.startswith(local_roots):
            findings.append(text)
            continue
        path_text = text.split(":", 1)[0]
        if not Path(path_text).is_absolute():
            continue
        try:
            path = Path(path_text).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        try:
            path.relative_to(cwd)
        except ValueError:
            continue
        findings.append(text)
    return findings


def repo_metadata_paths_reported_as_files_validated(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    metadata_parts = {".git", ".a9", ".pytest_cache", "__pycache__"}
    findings: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        path_text = text.split(":", 1)[0]
        parts = set(Path(path_text).parts)
        if parts & metadata_parts:
            findings.append(text)
    return findings


def validate_captured_diff(diff: dict[str, Any], worktree: Path, run_dir: Path) -> dict[str, Any]:
    output_path = run_dir / "patch_guard.json"
    if diff["diff_bytes"] == 0:
        result = {
            "status": "skip",
            "kind": "unified_diff",
            "block_count": 0,
            "touched_files": [],
            "findings": [{"level": "info", "message": "no recorded worker diff"}],
            "return_code": 0,
            "output_path": str(output_path),
        }
        write_json(output_path, result)
        return result

    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "a9_patch_guard.py"),
            str(diff["diff_path"]),
            "--root",
            str(worktree),
            "--format",
            "unified_diff",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {
            "status": "fail",
            "kind": "unified_diff",
            "block_count": 0,
            "touched_files": [],
            "findings": [
                {
                    "level": "error",
                    "message": "patch guard returned non-json output",
                    "output_preview": proc.stdout[-2000:],
                }
            ],
        }
    result["return_code"] = proc.returncode
    result["output_path"] = str(output_path)
    write_json(output_path, result)
    return result


def validate_scope(diff: dict[str, Any], task: Task, run_dir: Path) -> dict[str, Any]:
    output_path = run_dir / "scope_guard.json"
    if diff["diff_bytes"] == 0:
        result = {
            "status": "skip",
            "changed_files": [],
            "allowed_paths": task.allowed_paths,
            "findings": [{"level": "info", "message": "no recorded worker diff"}],
            "return_code": 0,
            "output_path": str(output_path),
        }
        write_json(output_path, result)
        return result

    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "a9_scope_guard.py"),
        str(diff["diff_path"]),
    ]
    for allowed in task.allowed_paths:
        cmd.extend(["--allow", allowed])
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {
            "status": "fail",
            "changed_files": [],
            "allowed_paths": task.allowed_paths,
            "findings": [
                {
                    "level": "error",
                    "message": "scope guard returned non-json output",
                    "output_preview": proc.stdout[-2000:],
                }
            ],
        }
    result["return_code"] = proc.returncode
    result["output_path"] = str(output_path)
    write_json(output_path, result)
    return result


def apply_git_governance(worktree: Path, run_dir: Path, task: Task, status: str, diff: dict[str, Any]) -> dict[str, Any]:
    output_path = run_dir / "git_governance.json"
    base_head = run_cmd_no_raise(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    result: dict[str, Any] = {
        "status": "skip",
        "policy": "aider_atomic_commit_sweagent_reset",
        "base_head": base_head,
        "diff_bytes": diff.get("diff_bytes", 0),
        "commit": "",
        "rolled_back": False,
        "commands": [],
        "findings": [],
        "output_path": str(output_path),
    }

    if diff.get("diff_bytes", 0) == 0:
        result["findings"].append({"level": "info", "message": "no worker diff to commit or rollback"})
        write_json(output_path, result)
        return result

    if status == "pass":
        message = f"a9 worker: {task.task_id} attempt snapshot"
        command = [
            "git",
            "-c",
            "user.email=a9-supervisor@example.invalid",
            "-c",
            "user.name=A9 Supervisor",
            "commit",
            "-m",
            message,
        ]
        proc = run_cmd_no_raise(command, cwd=worktree)
        result["commands"].append({"command": " ".join(command), "return_code": proc.returncode})
        if proc.returncode == 0:
            result["status"] = "committed"
            result["commit"] = run_cmd_no_raise(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
            result["main_integration"] = integrate_worker_commit_to_main(
                worktree,
                result["commit"],
                base_head,
                workspace_root=task_workspace_root(task),
            )
        else:
            result["status"] = "commit-failed"
            result["findings"].append(
                {
                    "level": "error",
                    "message": "failed to commit accepted worker diff",
                    "output_preview": (proc.stdout or "")[-2000:],
                }
            )
        write_json(output_path, result)
        return result

    for command in (
        ["git", "restore", "--staged", "."],
        ["git", "reset", "--hard", "HEAD"],
        ["git", "clean", "-fdq"],
    ):
        proc = run_cmd_no_raise(command, cwd=worktree)
        result["commands"].append({"command": " ".join(command), "return_code": proc.returncode})
        if proc.returncode != 0:
            result["findings"].append(
                {
                    "level": "error",
                    "message": "rollback command failed",
                    "command": " ".join(command),
                    "output_preview": (proc.stdout or "")[-2000:],
                }
            )
    result["rolled_back"] = not result["findings"]
    result["status"] = "rolled-back" if result["rolled_back"] else "rollback-failed"
    write_json(output_path, result)
    return result


def path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def integrate_worker_commit_to_main(
    worktree: Path,
    commit: str,
    base_head: str,
    *,
    workspace_root: Path = ROOT,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "skipped",
        "policy": "clean_workspace_fast_forward_cherry_pick",
        "commit": commit,
        "base_head": base_head,
        "workspace_root": str(workspace_root),
        "root_head_before": "",
        "main_commit": "",
        "commands": [],
        "findings": [],
    }
    if not commit:
        result["reason"] = "missing_commit"
        return result
    if not path_is_relative_to(worktree, WORKTREES_DIR):
        result["reason"] = "non_supervisor_worktree"
        return result
    root_head = git_head_for_workspace(workspace_root)
    result["root_head_before"] = root_head
    if root_head != base_head:
        result["reason"] = "root_head_mismatch"
        result["findings"].append(
            {
                "level": "warning",
                "message": "worker commit was accepted but root HEAD moved before integration",
                "root_head": root_head,
                "base_head": base_head,
            }
        )
        return result
    dirty = run_cmd_no_raise(["git", "status", "--porcelain"], cwd=workspace_root).stdout.strip()
    if dirty:
        result["reason"] = "dirty_root"
        result["findings"].append(
            {
                "level": "warning",
                "message": "worker commit was accepted but target workspace is dirty",
                "status_preview": dirty[:2000],
            }
        )
        return result

    command = ["git", "cherry-pick", commit]
    proc = run_cmd_no_raise(command, cwd=workspace_root)
    result["commands"].append({"command": " ".join(command), "return_code": proc.returncode})
    if proc.returncode == 0:
        result["status"] = "integrated"
        result["main_commit"] = git_head_for_workspace(workspace_root)
        return result

    abort = run_cmd_no_raise(["git", "cherry-pick", "--abort"], cwd=workspace_root)
    result["commands"].append({"command": "git cherry-pick --abort", "return_code": abort.returncode})
    result["status"] = "failed"
    result["reason"] = "cherry_pick_failed"
    result["findings"].append(
        {
            "level": "error",
                "message": "failed to integrate accepted worker commit into target workspace",
            "output_preview": (proc.stdout or "")[-2000:],
        }
    )
    return result


def supplemental_test_module_for_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    if not normalized.startswith("tests/test_") or not normalized.endswith(".py"):
        return ""
    return normalized[:-3].replace("/", ".")


def cached_changed_files(worktree: Path) -> list[str]:
    proc = run_cmd(["git", "diff", "--cached", "--name-only"], cwd=worktree)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def declared_check_covers_unittest_module(check: str, module: str) -> bool:
    targets = unittest_targets(normalize_shell_command(check))
    return any(target == module for target in targets)


def supplemental_check_commands(task: Task, worktree: Path) -> list[str]:
    modules: list[str] = []
    for path in cached_changed_files(worktree):
        module = supplemental_test_module_for_path(path)
        if module and module not in modules:
            modules.append(module)
    commands: list[str] = []
    for module in modules:
        command = f"python3 -m unittest {module}"
        if any(declared_check_covers_unittest_module(check, module) for check in task.checks):
            continue
        commands.append(command)
    return commands


def run_checks(task: Task, worktree: Path, run_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    checks_dir = run_dir / "checks"
    checks_dir.mkdir(exist_ok=True)
    checks_to_run = [{"command": check, "source": "declared"} for check in task.checks]
    checks_to_run.extend({"command": check, "source": "supplemental_changed_test_file"} for check in supplemental_check_commands(task, worktree))
    for index, check_item in enumerate(checks_to_run, start=1):
        check_cmd = check_item["command"]
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
                "source": check_item["source"],
            }
        )
    return results


def normalize_shell_command(command: str) -> str:
    return " ".join(str(command or "").split())


def command_looks_like_test(command: str) -> bool:
    normalized = normalize_shell_command(command)
    lowered = normalized.lower()
    if re.search(r"\bpython3?\s+-m\s+(?:unittest|pytest|py_compile)\b", lowered):
        return True
    if re.search(r"(?:^|&&|;)\s*(?:pytest|cargo\s+test|npm\s+test|pnpm\s+test|yarn\s+test)\b", lowered):
        return True
    if re.search(r"\bpython3?\s+-\s*<<", normalized):
        return any(marker in normalized for marker in ("assert ", "AssertionError", "CHECK:", "raise "))
    return False


def command_matches_declared_check(command: str, checks: list[str]) -> bool:
    normalized = normalize_shell_command(command)
    normalized_variants = command_equivalence_variants(normalized)
    declared_variants = [variant for item in checks for variant in command_equivalence_variants(normalize_shell_command(item))]
    if any(
        command_variant == declared_variant
        or command_variant in declared_variant
        or declared_variant in command_variant
        for command_variant in normalized_variants
        for declared_variant in declared_variants
    ):
        return True
    command_targets = unittest_targets(normalized)
    declared_targets = [target for item in checks for target in unittest_targets(normalize_shell_command(item))]
    return any(
        command_target and declared_target.startswith(command_target + ".")
        for command_target in command_targets
        for declared_target in declared_targets
    )


def unittest_targets(command: str) -> list[str]:
    normalized = normalize_shell_command(command)
    match = re.search(r"python3?\s+-m\s+unittest\s+([^'\";&|]+)", normalized)
    if not match:
        return []
    targets: list[str] = []
    for target in match.group(1).split():
        cleaned = target.strip()
        if not cleaned or cleaned.startswith("-"):
            continue
        if cleaned.endswith(".py"):
            cleaned = cleaned[:-3].replace("/", ".").replace("\\", ".")
        targets.append(cleaned)
    return targets


def unittest_target_exists(target: str) -> bool:
    text = str(target or "").strip()
    if not text:
        return True
    if text.endswith(".py"):
        text = text[:-3].replace("/", ".").replace("\\", ".")
    parts = [part for part in text.split(".") if part]
    for index in range(len(parts), 0, -1):
        module_name = ".".join(parts[:index])
        try:
            spec = importlib.util.find_spec(module_name)
        except (ImportError, AttributeError, ValueError):
            spec = None
        if spec is None:
            continue
        try:
            module = __import__(module_name, fromlist=["*"])
        except Exception:
            return True
        obj: Any = module
        for attr in parts[index:]:
            if not hasattr(obj, attr):
                return False
            obj = getattr(obj, attr)
        return True
    return False


def unresolved_unittest_targets(command: str) -> list[str]:
    unresolved: list[str] = []
    for target in unittest_targets(command):
        if not unittest_target_exists(target):
            unresolved.append(target)
    return unresolved


def unittest_target_allowed_for_future_test(target: str, allowed_paths: list[str]) -> bool:
    parts = [part for part in str(target or "").strip().split(".") if part]
    for index in range(len(parts), 0, -1):
        candidate = "/".join(parts[:index]) + ".py"
        if candidate in allowed_paths:
            return True
    return False


def command_equivalence_variants(command: str) -> set[str]:
    normalized = normalize_shell_command(command)
    variants = {normalized}
    match = re.search(r"python3?\s+-m\s+unittest\s+([A-Za-z0-9_./-]+\.py)\b", normalized)
    if match:
        module = match.group(1)[:-3].replace("/", ".").replace("\\", ".")
        variants.add(normalized[: match.start(1)] + module + normalized[match.end(1) :])
    match = re.search(r"python3?\s+-m\s+unittest\s+([A-Za-z0-9_.-]+)\b", normalized)
    if match and "." in match.group(1):
        path = match.group(1).replace(".", "/") + ".py"
        variants.add(normalized[: match.start(1)] + path + normalized[match.end(1) :])
    return variants


def prompt_forbids_rg_files(prompt: str) -> bool:
    return "rg --files" in str(prompt or "").lower() and "do not" in str(prompt or "").lower()


def prompt_forbids_ls(prompt: str) -> bool:
    return bool(re.search(r"\bdo not run ls\b", str(prompt or ""), flags=re.IGNORECASE))


def prompt_requires_targeted_rg(prompt: str) -> bool:
    return "targeted rg" in str(prompt or "").lower()


def bounded_read_paths_from_prompt(prompt: str) -> list[str]:
    paths: list[str] = []
    for match in re.finditer(
        r"bounded read(?:\s+of|\s*:)\s*([A-Za-z0-9_./\-*]+)",
        str(prompt or ""),
        flags=re.IGNORECASE,
    ):
        path = match.group(1).strip().rstrip(".,;:")
        if path and path not in paths:
            paths.append(path)
    return paths


def prompt_requires_bounded_evidence_plan(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    return "evidence-and-edit contract" in lowered or (
        "bounded evidence plan" in lowered and "before any reads" in lowered
    )


def evidence_plan_stated_in_text(text: str) -> bool:
    lowered = str(text or "").lower()
    if "bounded evidence plan" in lowered:
        return True
    if "before any reads" in lowered and "bounded" in lowered and "plan" in lowered:
        return True
    original = str(text or "")
    has_path = bool(re.search(r"\b(?:scripts|tests|docs|crates|infra)/[A-Za-z0-9_./*-]+", original))
    has_read_intent = any(token in original for token in ("只读", "读取", "检索", "定位", "相关片段", "证据"))
    has_ordering = any(token in original for token in ("先", "随后", "下一步", "本轮"))
    return has_path and has_read_intent and has_ordering


def evidence_plan_has_bounded_read_commands(text: str) -> bool:
    original = str(text or "")
    has_path = bool(re.search(r"\b(?:scripts|tests|docs|crates|infra)/[A-Za-z0-9_./*-]+", original))
    has_bounded_command = bool(re.search(r"\b(?:rg\s+-n|sed\s+-n|tail\s+-n)\b", original))
    return has_path and has_bounded_command


def command_is_single_bounded_read_of_paths(command: str, paths: list[str]) -> bool:
    if not paths:
        return True
    normalized = normalize_shell_command(command)
    inner = shell_lc_inner_command(normalized)
    inner = inner.strip()
    if "||" in shell_sequence_operators(inner) or ";" in shell_sequence_operators(inner):
        return False
    fragments = [part.strip() for part in shell_sequence_parts(inner, allow_and=True) if part.strip()]
    fragments = [part for part in fragments if not command_fragment_is_cd(part)]
    return bool(fragments) and all(command_fragment_is_bounded_read_of_paths(fragment, paths) for fragment in fragments)


def shell_lc_inner_command(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return command
    if len(parts) >= 3 and parts[0] in {"/bin/bash", "/bin/sh", "bash", "sh"} and parts[1] == "-lc":
        return parts[2]
    return command


def command_fragment_is_cd(inner: str) -> bool:
    try:
        parts = shlex.split(inner)
    except ValueError:
        return False
    return len(parts) == 2 and parts[0] == "cd" and bool(parts[1].strip())


def shell_pipeline_parts(command: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    for char in command:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            current.append(char)
            quote = char
            continue
        if char == "|":
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def shell_sequence_parts(command: str, *, allow_and: bool = False) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            current.append(char)
            escaped = False
            index += 1
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            index += 1
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            current.append(char)
            quote = char
            index += 1
            continue
        if char == ";":
            parts.append("".join(current).strip())
            current = []
            index += 1
            continue
        if command[index : index + 2] == "&&":
            if allow_and:
                parts.append("".join(current).strip())
                current = []
                index += 2
                continue
        current.append(char)
        index += 1
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def shell_sequence_operators(command: str) -> set[str]:
    operators: set[str] = set()
    quote = ""
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if quote:
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == ";":
            operators.add(";")
        if command[index : index + 2] == "||":
            operators.add("||")
            index += 2
            continue
        if command[index : index + 2] == "&&":
            operators.add("&&")
            index += 2
            continue
        index += 1
    return operators


def command_fragment_is_bounded_read_of_paths(inner: str, paths: list[str]) -> bool:
    pipe_parts = shell_pipeline_parts(inner)
    if len(pipe_parts) == 2 and (
        re.fullmatch(r"head\s+(?:-n\s+\d+|-\d+)", pipe_parts[1])
        or re.fullmatch(r"tail\s+(?:-n\s+\d+|-\d+)", pipe_parts[1])
        or re.fullmatch(r"sed\s+-n\s+['\"]?\d+\s*,\s*\d+p['\"]?", pipe_parts[1])
        or command_fragment_is_stdin_rg_filter(pipe_parts[1])
    ):
        return command_fragment_is_bounded_read_of_paths(pipe_parts[0], paths)
    if len(pipe_parts) > 1:
        return False

    try:
        parts = shlex.split(inner)
    except ValueError:
        return False

    if parts and parts[0] in {"head", "tail"}:
        if len(parts) >= 4 and parts[1] == "-n":
            target = parts[-1]
            return any(bounded_read_path_matches(path, target) for path in paths)
        return False

    if parts and parts[0] == "nl":
        targets = [part for part in parts[1:] if not part.startswith("-")]
        if len(targets) != 1:
            return False
        return any(bounded_read_path_matches(path, targets[0]) for path in paths)

    if parts and parts[0] == "sed":
        if len(parts) < 4 or parts[1] != "-n":
            return False
        window = parts[2].strip("'\"")
        if not sed_window_is_bounded(window):
            return False
        target = parts[3]
        return any(bounded_read_path_matches(path, target) for path in paths)

    git_parts = normalize_git_command_parts(parts)
    if git_parts and len(git_parts) >= 5 and git_parts[0] == "git" and git_parts[1] == "show" and "--" in git_parts:
        dash_index = git_parts.index("--")
        targets = [part for part in git_parts[dash_index + 1 :] if part.strip()]
        return bool(targets) and all(
            any(bounded_read_path_matches(pattern_text, target) for pattern_text in paths) for target in targets
        )

    if git_parts and len(git_parts) >= 4 and git_parts[0] == "git" and git_parts[1] == "diff" and "--" in git_parts:
        dash_index = git_parts.index("--")
        targets = [part for part in git_parts[dash_index + 1 :] if part.strip()]
        return bool(targets) and all(
            any(bounded_read_path_matches(pattern_text, target) for pattern_text in paths) for target in targets
        )

    if parts and parts[0] == "rg":
        allowed_flags = {"-n", "--line-number", "-F", "--fixed-strings"}
        allowed_value_flags = {"-m", "--max-count", "-g", "--glob"}
        saw_line_flag = False
        index = 1
        while index < len(parts) and parts[index].startswith("-"):
            flag = parts[index]
            if flag in allowed_value_flags:
                index += 2
                continue
            if flag.startswith("--max-count="):
                index += 1
                continue
            if flag not in allowed_flags:
                return False
            saw_line_flag = saw_line_flag or parts[index] in {"-n", "--line-number"}
            index += 1
        if not saw_line_flag or index >= len(parts):
            return False
        pattern = parts[index]
        raw_rg_paths = parts[index + 1 :]
        rg_paths: list[str] = []
        path_index = 0
        while path_index < len(raw_rg_paths):
            part = raw_rg_paths[path_index]
            if part in allowed_flags:
                path_index += 1
                continue
            if part in allowed_value_flags:
                path_index += 2
                continue
            if part.startswith("--max-count="):
                path_index += 1
                continue
            if rg_target_looks_like_path(part):
                rg_paths.append(part)
            path_index += 1
        if not pattern or not rg_paths:
            return False
        return all(any(bounded_read_path_matches(pattern_text, rg_path) for pattern_text in paths) for rg_path in rg_paths)
    return False


def sed_window_is_bounded(window: str) -> bool:
    segments = [segment.strip() for segment in window.split(";") if segment.strip()]
    if not segments:
        return False
    for segment in segments:
        match = re.fullmatch(r"(\d+)\s*,\s*(\d+)p", segment)
        if not match:
            return False
        start = int(match.group(1))
        end = int(match.group(2))
        if end < start:
            return False
    return True


def bounded_read_path_matches(pattern: str, candidate: str) -> bool:
    candidates = [candidate]
    root_text = str(ROOT).rstrip("/")
    if candidate.startswith(root_text + "/"):
        candidates.append(candidate[len(root_text) + 1 :])
    worktree_match = re.match(rf"^{re.escape(root_text)}/\.a9/worktrees/[^/]+/(.+)$", candidate)
    if worktree_match:
        candidates.append(worktree_match.group(1))
    for item in candidates:
        if pattern == item:
            return True
        if pattern.endswith("/") and item.startswith(pattern):
            return True
        if "*" in pattern and fnmatch.fnmatch(item, pattern):
            return True
    return False


def prompt_enforces_allowed_read_paths(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    if "allowed_paths" not in lowered:
        return False
    markers = (
        "inspect only",
        "read only",
        "only bounded slices",
        "bounded slices from allowed_paths",
        "bounded rg/sed reads only on allowed_paths",
        "bounded read",
    )
    return any(marker in lowered for marker in markers)


def prompt_requires_live_read_budget_stop(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    return "live_read_budget_policy: stop" in lowered or "stop on read budget violations" in lowered


def command_read_targets(command: str) -> list[str]:
    normalized = normalize_shell_command(command)
    inner = shell_lc_inner_command(normalized).strip()
    fragments = [part.strip() for part in shell_sequence_parts(inner, allow_and=True) if part.strip()]
    targets: list[str] = []
    for fragment in fragments or [inner]:
        pipe_head = shell_pipeline_parts(fragment)[0].strip()
        try:
            parts = shlex.split(pipe_head)
        except ValueError:
            continue
        if not parts:
            continue
        name = parts[0]
        if name == "sed" and len(parts) >= 4 and parts[1] == "-n":
            targets.append(parts[3])
        elif name in {"tail", "head"} and len(parts) >= 4 and parts[1] == "-n":
            targets.append(parts[-1])
        elif name == "nl" and len(parts) >= 2:
            targets.extend(part for part in parts[1:] if not part.startswith("-"))
        elif name == "wc" and len(parts) >= 3 and parts[1] in {"-l", "-c", "-w"}:
            targets.extend(part for part in parts[2:] if not part.startswith("-"))
        elif name == "rg":
            index = 1
            rg_files = False
            while index < len(parts) and parts[index].startswith("-"):
                flag = parts[index]
                if flag == "--files":
                    rg_files = True
                    index += 1
                    continue
                if flag in {"-m", "--max-count", "-g", "--glob"}:
                    index += 2
                    continue
                if flag.startswith("--max-count="):
                    index += 1
                    continue
                if flag.startswith("--glob="):
                    index += 1
                    continue
                index += 1
            if rg_files:
                targets.extend(part for part in parts[index:] if not part.startswith("-") and rg_target_looks_like_path(part))
            elif index < len(parts):
                raw_targets = parts[index + 1 :]
                target_index = 0
                while target_index < len(raw_targets):
                    part = raw_targets[target_index]
                    if part in {"-m", "--max-count", "-g", "--glob"}:
                        target_index += 2
                        continue
                    if part.startswith("--max-count=") or part.startswith("--glob="):
                        target_index += 1
                        continue
                    if not part.startswith("-") and rg_target_looks_like_path(part):
                        targets.append(part)
                    target_index += 1
        elif name == "git":
            git_parts = normalize_git_command_parts(parts)
            if len(git_parts) >= 4 and git_parts[1] in {"diff", "show"} and "--" in git_parts:
                dash_index = git_parts.index("--")
                targets.extend(part for part in git_parts[dash_index + 1 :] if part.strip())
        elif name == "awk" and len(parts) >= 2:
            awk_targets = [part for part in parts[1:] if not part.startswith("-") and rg_target_looks_like_path(part)]
            if awk_targets:
                targets.append(awk_targets[-1])
        elif name == "jq" and len(parts) >= 2:
            jq_targets = [part for part in parts[1:] if not part.startswith("-") and rg_target_looks_like_path(part)]
            if jq_targets:
                targets.append(jq_targets[-1])
    return targets


def normalize_git_command_parts(parts: list[str]) -> list[str]:
    if not parts or parts[0] != "git":
        return parts
    normalized = [parts[0]]
    index = 1
    while index < len(parts):
        part = parts[index]
        if part == "-C" and index + 1 < len(parts):
            index += 2
            continue
        normalized.extend(parts[index:])
        break
    return normalized


def command_is_read_only_of_paths(command: str, paths: list[str]) -> bool:
    if not paths:
        return False
    normalized = normalize_shell_command(command)
    inner = shell_lc_inner_command(normalized).strip()
    if "||" in shell_sequence_operators(inner) or ";" in shell_sequence_operators(inner):
        return False
    fragments = [part.strip() for part in shell_sequence_parts(inner, allow_and=True) if part.strip()]
    fragments = [part for part in fragments if not command_fragment_is_cd(part)]
    if not fragments:
        return False
    for fragment in fragments:
        targets = command_read_targets(fragment)
        if not targets:
            if command_fragment_is_read_command_with_explicit_allowed_path(fragment, paths):
                continue
            return False
        if not all(any(bounded_read_path_matches(pattern, target) for pattern in paths) for target in targets):
            return False
    return True


def command_fragment_is_read_command_with_explicit_allowed_path(fragment: str, paths: list[str]) -> bool:
    normalized = normalize_shell_command(fragment)
    if not re.search(r"(?:^|\s)(rg|sed|awk|jq|wc|head|tail|nl|git)(?:\s|$)", normalized):
        return False
    for path in paths:
        item = str(path or "").strip()
        if not item:
            continue
        candidates = {item}
        root_text = str(ROOT).rstrip("/")
        if not item.startswith(root_text + "/"):
            candidates.add(f"{root_text}/{item}")
        for candidate in candidates:
            if candidate and candidate in normalized:
                return True
    return False


def rg_target_looks_like_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text in {".", ".."} or text.startswith(("./", "../", "/", ".a9/")):
        return True
    if "/" in text or "\\" in text:
        return True
    if Path(text).suffix:
        return True
    return False


def command_fragment_is_stdin_rg_filter(fragment: str) -> bool:
    try:
        parts = shlex.split(fragment)
    except ValueError:
        return False
    if not parts or parts[0] != "rg":
        return False
    index = 1
    while index < len(parts) and parts[index].startswith("-"):
        flag = parts[index]
        if flag in {"-m", "--max-count"}:
            index += 2
            continue
        if flag.startswith("--max-count="):
            index += 1
            continue
        index += 1
    if index >= len(parts):
        return False
    targets = [part for part in parts[index + 1 :] if not part.startswith("-")]
    return not any(rg_target_looks_like_path(target) for target in targets)


def command_read_fragments(command: str) -> list[dict[str, Any]]:
    normalized = normalize_shell_command(command)
    inner = shell_lc_inner_command(normalized).strip()
    fragments = [part.strip() for part in re.split(r"\s+(?:&&|;)\s+", inner) if part.strip()]
    reads: list[dict[str, Any]] = []
    for fragment in fragments or [inner]:
        pipe_head = shell_pipeline_parts(fragment)[0].strip()
        try:
            parts = shlex.split(pipe_head)
        except ValueError:
            continue
        if not parts:
            continue
        name = parts[0]
        target = ""
        line_count = 0
        if name == "sed" and len(parts) >= 4 and parts[1] == "-n":
            target = parts[3]
            window = parts[2].strip("'\"")
            match = re.search(r"^(\d+)\s*,\s*(\d+)p$", window)
            if match:
                start = int(match.group(1))
                end = int(match.group(2))
                if end >= start:
                    line_count = end - start + 1
        elif name in {"tail", "head"} and len(parts) >= 4 and parts[1] == "-n":
            target = parts[-1]
            try:
                line_count = int(parts[2])
            except ValueError:
                line_count = 0
        elif name == "rg":
            index = 1
            while index < len(parts) and parts[index].startswith("-"):
                if parts[index] in {"-m", "--max-count"}:
                    index += 2
                    continue
                index += 1
            if index < len(parts):
                target = " ".join(part for part in parts[index + 1 :] if not part.startswith("-"))
        if target:
            reads.append({"tool": name, "target": target, "line_count": line_count, "fragment": fragment})
    return reads


def compound_wide_read_command_findings(task: Task, command: str) -> list[dict[str, Any]]:
    if command_looks_like_test(command):
        return []
    reads = command_read_fragments(command)
    if len(reads) <= 1:
        return []
    targets = {str(item.get("target") or "").strip() for item in reads if item.get("target")}
    broad_reads = [item for item in reads if int(item.get("line_count") or 0) > BROAD_FILE_SLICE_WARN_LINES]
    if len(targets) <= 1 and not broad_reads:
        return []
    return [
        {
            "level": "warn",
            "kind": "compound_wide_read_command",
            "message": "worker combined multiple source reads or broad read windows in one command; split into bounded single-evidence steps",
            "command": command,
            "read_count": len(reads),
            "target_count": len(targets),
            "broad_read_count": len(broad_reads),
            "targets": sorted(targets)[:6],
        }
    ]


def allowed_read_path_findings(task: Task, command: str) -> list[dict[str, Any]]:
    if not task.allowed_paths or not prompt_enforces_allowed_read_paths(task.prompt):
        return []
    read_scope_paths = list(task.allowed_paths)
    for bounded_path in bounded_read_paths_from_prompt(task.prompt):
        if bounded_path not in read_scope_paths:
            read_scope_paths.append(bounded_path)
    findings: list[dict[str, Any]] = []
    for target in command_read_targets(command):
        normalized_target = target[2:] if target.startswith("./") else target
        if any(bounded_read_path_matches(allowed, normalized_target) for allowed in read_scope_paths):
            continue
        findings.append(
            {
                "level": "error",
                "kind": "read_outside_allowed_paths",
                "message": "worker read a path outside the task's explicit allowed read scope",
                "command": command,
                "path": normalized_target,
                "allowed_paths": task.allowed_paths,
                "read_scope_paths": read_scope_paths,
            }
        )
    return findings


def task_allows_session_context_reads(task: Task, command: str) -> bool:
    if task.phase in SESSION_CONTEXT_READ_PHASES:
        return True
    bounded_paths = bounded_read_paths_from_prompt(task.prompt)
    if bounded_paths and (
        command_is_single_bounded_read_of_paths(command, bounded_paths)
        or command_is_read_only_of_paths(command, bounded_paths)
    ):
        return True
    allowed_context_paths = [
        path
        for path in task.allowed_paths
        if path
        in {
            "docs/session.md",
            "docs/mistakes.md",
        }
    ]
    if allowed_context_paths and (
        command_is_single_bounded_read_of_paths(command, task.allowed_paths)
        or command_is_read_only_of_paths(command, task.allowed_paths)
    ):
        return True
    return bool(allowed_context_paths) and (
        command_is_single_bounded_read_of_paths(command, allowed_context_paths)
        or command_is_read_only_of_paths(command, allowed_context_paths)
    )


def command_session_context_path(command: str, prefix: str) -> str:
    normalized_prefix = f"./{prefix}"
    idx = command.find(prefix)
    if idx < 0:
        idx = command.find(normalized_prefix)
        if idx < 0:
            return prefix
        else:
            idx = idx + 2
    if idx < 0:
        return prefix
    tail = command[idx:]
    parts = re.split(r"\s+|['\"]|[|;&]", tail)
    if parts:
        return parts[0].strip()
    return prefix


def forbidden_session_context_read(task: Task, command: str) -> dict[str, Any] | None:
    if task_allows_session_context_reads(task, command):
        return None
    normalized = normalize_shell_command(command)
    lowered = normalized.lower()
    for path in FORBIDDEN_SESSION_CONTEXT_PATHS:
        if path.lower() in lowered:
            return {
                "level": "warn",
                "kind": "forbidden_session_context_read",
                "message": "worker read session memory/raw context outside a session_refresh/session_close_reading task",
                "command": normalized,
                "path": path,
            }
    for path in FORBIDDEN_SESSION_CONTEXT_PATH_PREFIXES:
        if path in lowered:
            matched_path = command_session_context_path(normalized, path)
            return {
                "level": "warn",
                "kind": "forbidden_session_context_read",
                "message": (
                    "worker read session context/archival or raw evidence file outside a "
                    "session_refresh/session_close_reading task"
                ),
                "command": normalized,
                "path": matched_path,
            }
    return None


def prompt_sed_window_limit(prompt: str) -> int | None:
    match = re.search(
        r"sed windows?\s*(?:must\s+be\s*)?<=\s*(\d+)\s*lines?",
        str(prompt or ""),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return int(match.group(1))


def total_sed_line_limit_for_task(task: Task) -> int | None:
    match = re.search(
        r"total requested source lines\s*<=\s*(\d+)",
        str(task.prompt or ""),
        flags=re.IGNORECASE,
    )
    if match:
        return int(match.group(1))
    if task_is_observation_only(task):
        return 180
    return None


READ_HEAVY_PHASES = {"reference_scan", "mechanism_extract", SESSION_CLOSE_READING_PHASE}
BATCHED_READ_RATIONALE_HINTS = (
    "原因",
    "因为",
    "为了",
    "需要",
    "分批",
    "定位",
    "机制",
    "语义",
    "状态机",
    "上下文",
    "边界",
    "失败模式",
    "because",
    "reason",
    "why",
    "need",
    "batch",
    "mechanism",
    "state",
    "context",
    "failure",
)
BROAD_FILE_SLICE_WARN_LINES = 240


def sed_window_policy(task: Task) -> dict[str, Any] | None:
    prompt_limit = prompt_sed_window_limit(task.prompt)
    if prompt_limit is None:
        return None
    soft_limit = max(prompt_limit, 180)
    multiplier = 2 if task.phase in READ_HEAVY_PHASES else 1
    hard_limit = max(240, soft_limit * multiplier)
    return {
        "prompt_limit": prompt_limit,
        "soft_limit": soft_limit,
        "hard_limit": hard_limit,
        "phase": task.phase,
        "rationale_required_over": soft_limit,
    }


def rationale_supports_batched_read(text: str) -> bool:
    normalized = str(text or "").lower()
    if not normalized.strip():
        return False
    return any(hint in normalized for hint in BATCHED_READ_RATIONALE_HINTS)


def sed_window_governance(
    task: Task,
    command: str,
    *,
    rationale: str = "",
) -> list[dict[str, Any]]:
    policy = sed_window_policy(task)
    findings: list[dict[str, Any]] = []
    has_rationale = rationale_supports_batched_read(rationale)
    for start, end in sed_windows_from_command(command):
        lines = end - start + 1
        if not policy and lines > BROAD_FILE_SLICE_WARN_LINES:
            findings.append(
                {
                    "command": command,
                    "start": start,
                    "end": end,
                    "line_count": lines,
                    "lines": lines,
                    "read_span": f"{start}-{end}",
                    "level": "warn",
                    "kind": "broad_file_slice_observation",
                    "message": "worker read a broad sed file slice; prefer rg anchors plus narrower sed slices",
                    "recommendation": "use rg anchors (grep-like) to locate lines first, then read narrower sed slices",
                }
            )
            continue
        if not policy:
            continue
        base = {
            "command": command,
            "start": start,
            "end": end,
            "lines": lines,
            "prompt_limit": policy["prompt_limit"],
            "soft_limit": policy["soft_limit"],
            "hard_limit": policy["hard_limit"],
        }
        if lines > policy["hard_limit"]:
            findings.append(
                {
                    **base,
                    "level": "warn",
                    "kind": "command_window_exceeded",
                    "message": "worker read more sed lines than the hard task bound allows",
                }
            )
        elif lines > policy["soft_limit"] and not has_rationale:
            findings.append(
                {
                    **base,
                    "level": "warning",
                    "kind": "command_window_missing_rationale",
                    "message": "worker used a larger batched sed window without explaining why first",
                }
            )
        elif lines > policy["soft_limit"]:
            findings.append(
                {
                    **base,
                    "level": "info",
                    "kind": "batched_read_with_rationale",
                    "message": "worker used a larger bounded sed window after giving a rationale",
                }
            )
    return findings


def command_runs_ls(command: str) -> bool:
    normalized = normalize_shell_command(command)
    return bool(re.search(r"(?:^|\s)(?:/bin/)?(?:bash|sh)\s+-lc\s+['\"]?ls(?:['\"]?|\s|$)", normalized)) or normalized == "ls"


def command_is_low_cost_workspace_orientation(command: str) -> bool:
    normalized = normalize_shell_command(command)
    inner = shell_lc_inner_command(normalized).strip()
    fragments = [part.strip() for part in re.split(r"\s*;\s*", inner) if part.strip()]
    return fragments in (["pwd"], ["pwd", "ls"], ["pwd", "ls -1"])


def command_is_low_cost_directory_listing(command: str, allowed_paths: list[str] | None = None) -> bool:
    normalized = normalize_shell_command(command)
    inner = shell_lc_inner_command(normalized).strip()
    if re.search(r"\s(?:\|\||;)\s", inner):
        return False
    fragments = [part.strip() for part in re.split(r"\s+&&\s+", inner) if part.strip()]
    fragments = [part for part in fragments if not command_fragment_is_cd(part)]
    if len(fragments) != 1:
        return False
    pipe_parts = shell_pipeline_parts(fragments[0])
    if len(pipe_parts) > 2:
        return False
    if len(pipe_parts) == 2 and not re.fullmatch(r"head(?:\s+(?:-n\s+\d+|-\d+))?", pipe_parts[1]):
        return False
    try:
        parts = shlex.split(pipe_parts[0])
    except ValueError:
        return False
    if not parts or parts[0] != "ls":
        return False
    targets: list[str] = []
    for part in parts[1:]:
        if part.startswith("-"):
            if part in {"-1", "--format=single-column"}:
                continue
            return False
        targets.append(part)
    if len(targets) > 1:
        return False
    target = targets[0] if targets else "."
    root_text = str(ROOT)
    forbidden_targets = {".", root_text, f"{root_text}/", "/", ".a9", f"{root_text}/.a9"}
    if target in forbidden_targets:
        return False
    allowed_paths = allowed_paths or []
    allowed_parent_dirs = {str(Path(path).parent) for path in allowed_paths if str(path).strip()}
    normalized_target = target.rstrip("/")
    if normalized_target in allowed_parent_dirs:
        return True
    if target.startswith(".a9/") or target.startswith(f"{root_text}/.a9/"):
        if any(
            bounded_read_path_matches(allowed_parent, normalized_target)
            for allowed_parent in allowed_parent_dirs
        ):
            return True
        return False
    return True


def command_is_python_readonly_probe_on_allowed_paths(command: str, allowed_paths: list[str]) -> bool:
    normalized = normalize_shell_command(command)
    if not re.search(r"\bpython3?\s+-\s*<<", normalized):
        return False
    if not re.search(r"\bread_text\s*\(", normalized):
        return False
    write_markers = ("write_text(", "write_bytes(", ".write(", "open(", ">>", "tee ")
    if any(marker in normalized for marker in write_markers):
        return False
    path_matches = re.findall(r"(?:pathlib\.)?Path\(['\"]([^'\"]+)['\"]\)", normalized)
    if not path_matches:
        return False
    return all(any(bounded_read_path_matches(allowed, path) for allowed in allowed_paths) for path in path_matches)


def command_runs_broad_rg(command: str) -> bool:
    normalized = normalize_shell_command(command)
    if not re.search(r"(?:^|[\s'\"])rg\s", normalized):
        return False
    return bool(re.search(r"(?:^|\s)(?:\.|docs\s+\.)(?:\s|['\"]|$)", normalized))


def command_runs_uncapped_rg(command: str) -> bool:
    normalized = normalize_shell_command(command)
    if not re.search(r"(?:^|[\s'\"])rg\s", normalized):
        return False
    if re.search(r"(?:^|\s)(?:-m|--max-count)(?:=|\s*)\d+", normalized):
        return False
    if re.search(r"\|\s*(?:head|tail)(?:\s|$)", normalized):
        return False
    if re.search(r"\|\s*sed\s+-n\s+['\"]?\d+\s*,\s*\d+p['\"]?", normalized):
        return False
    if re.search(r">\s*[^|&;]+", normalized):
        return False
    return True


def sed_windows_from_command(command: str) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    for match in re.finditer(r"sed\s+-n\s+['\"]?(\d+)\s*,\s*(\d+)p", command):
        start = int(match.group(1))
        end = int(match.group(2))
        if end >= start:
            windows.append((start, end))
    return windows


def read_jsonl_file(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def parse_direct_file_change_policy(prompt: str) -> str:
    explicit = explicit_direct_file_change_policy(prompt)
    return explicit if explicit else "observe"


def explicit_direct_file_change_policy(prompt: str) -> str:
    fields = parse_key_value_prompt(prompt)
    value = str(fields.get("direct_file_change_policy", "")).strip().lower()
    return value if value in {"observe", "repair"} else ""


def effective_direct_file_change_policy(task: Task) -> str:
    explicit_policy = explicit_direct_file_change_policy(task.prompt)
    if explicit_policy:
        return explicit_policy
    if strict_worker_envelope_required(task) and task.phase in AI_WORKER_PHASES:
        return "repair"
    return "observe"


def classify_process_governance(
    task: Task,
    worker: dict[str, Any],
    run_dir: Path,
    *,
    write_output: bool = True,
) -> dict[str, Any]:
    output_path = run_dir / "process_governance.json"
    event_path = Path(str(worker.get("event_summaries_path") or ""))
    findings: list[dict[str, Any]] = []
    commands_seen: set[str] = set()
    forbids_rg_files = prompt_forbids_rg_files(task.prompt)
    forbids_ls = prompt_forbids_ls(task.prompt)
    requires_targeted_rg = prompt_requires_targeted_rg(task.prompt)
    bounded_read_paths = bounded_read_paths_from_prompt(task.prompt)
    prompt_lower = task.prompt.lower()
    requires_bounded_plan = prompt_requires_bounded_evidence_plan(task.prompt)
    bounded_plan_stated = False
    bounded_plan_has_commands = False
    missing_plan_recorded = False
    missing_plan_commands_recorded = False
    deterministic_output_required = (
        "search/replace" in prompt_lower and "deterministic apply" in prompt_lower
    ) or ("strict_worker_envelope: true" in prompt_lower)
    forbids_web = ("do not browse web" in prompt_lower) or ("no web" in prompt_lower)
    direct_change_policy = effective_direct_file_change_policy(task)
    direct_change_enforce = deterministic_output_required and direct_change_policy == "repair"
    last_agent_rationale = ""
    total_sed_line_limit = total_sed_line_limit_for_task(task)
    cumulative_sed_lines = 0
    cumulative_sed_command_count = 0
    cumulative_sed_recorded = False
    for event in read_jsonl_file(event_path):
        if event.get("item_type") in {"agent_message", "reasoning"}:
            last_agent_rationale = str(event.get("text_preview") or "")
            if not bounded_plan_stated and evidence_plan_stated_in_text(last_agent_rationale):
                bounded_plan_stated = True
                bounded_plan_has_commands = evidence_plan_has_bounded_read_commands(last_agent_rationale)
            continue
        item_type = str(event.get("item_type") or "")
        if item_type == "file_change" and deterministic_output_required:
            level = "error" if direct_change_enforce else "warn"
            findings.append(
                {
                    "level": level,
                    "kind": "direct_file_change_event",
                    "message": "worker emitted direct file_change events while task requires deterministic SEARCH/REPLACE final output",
                }
            )
            continue
        tool_name = str(event.get("tool") or "")
        if item_type in {"web_search_call", "web_search"} or tool_name == "web_search":
            query = str(event.get("query") or "")
            query_empty = not query.strip()
            status_text = str(event.get("status") or "").strip().lower()
            if query_empty or (forbids_web and status_text in {"noop", "skipped", "ignored"}):
                findings.append(
                    {
                        "level": "warn",
                        "kind": "noop_web_search_event",
                        "message": "worker emitted empty/noop web_search event despite task bounds",
                        "query": query,
                        "status_text": status_text,
                        "web_forbidden_by_prompt": forbids_web,
                    }
                )
            continue
        if event.get("item_type") != "command_execution" or not isinstance(event.get("command"), str):
            continue
        command = normalize_shell_command(str(event.get("command") or ""))
        if not command or command in commands_seen:
            continue
        commands_seen.add(command)
        if requires_bounded_plan and not bounded_plan_stated and not missing_plan_recorded:
            findings.append(
                {
                    "level": "warn",
                    "kind": "missing_bounded_evidence_plan",
                    "message": "first command_execution happened before a bounded evidence plan was stated",
                    "command": command,
                    "evidence": "bounded evidence plan must be stated before source reads",
                }
            )
            missing_plan_recorded = True
        if (
            requires_bounded_plan
            and bounded_plan_stated
            and not bounded_plan_has_commands
            and not missing_plan_commands_recorded
        ):
            findings.append(
                {
                    "level": "warn",
                    "kind": "bounded_evidence_plan_missing_commands",
                    "message": "bounded evidence plan did not include exact bounded read commands",
                    "command": command,
                    "evidence": "plan should include exact rg/sed/tail commands before source reads",
                    "rationale": last_agent_rationale[:500],
                }
            )
            missing_plan_commands_recorded = True
        if command_looks_like_test(command) and task.checks and not command_matches_declared_check(command, task.checks):
            findings.append(
                {
                    "level": "warn",
                    "kind": "undeclared_check",
                    "message": "worker ran test/check command outside declared checks",
                    "command": command,
                    "declared_checks": task.checks,
                }
            )
        if command_looks_like_test(command) and task.checks and command_matches_declared_check(command, task.checks):
            findings.append(
                {
                    "level": "warn",
                    "kind": "worker_declared_check_execution",
                    "message": (
                        "worker ran a declared check inside the model session; observed as process "
                        "governance observation while outer supervisor checks are authoritative"
                    ),
                    "command": command,
                    "declared_checks": task.checks,
                }
            )
        if (
            bounded_read_paths
            and not command_looks_like_test(command)
            and not command_is_single_bounded_read_of_paths(command, bounded_read_paths)
            and not command_is_read_only_of_paths(command, bounded_read_paths)
        ):
            findings.append(
                {
                    "level": "warn",
                    "kind": "outside_bounded_read_scope",
                    "message": "worker ran a non-test command outside the prompt's bounded read scope",
                    "command": command,
                    "allowed_paths": bounded_read_paths,
                }
            )
        if forbids_rg_files and "rg --files" in command:
            findings.append(
                {
                    "level": "warn",
                    "kind": "forbidden_command",
                    "message": "worker ran rg --files despite task command bounds",
                    "command": command,
                }
            )
        if forbids_ls and command_runs_ls(command):
            findings.append(
                {
                    "level": "warn",
                    "kind": "forbidden_command",
                    "message": "worker ran ls despite task command bounds",
                    "command": command,
                }
            )
        if requires_targeted_rg and command_runs_broad_rg(command):
            findings.append(
                {
                    "level": "warn",
                    "kind": "broad_rg_command",
                    "message": "worker ran rg against a broad root despite targeted rg bounds",
                    "command": command,
                }
            )
        if (
            task.phase in READ_HEAVY_PHASES
            and command_runs_uncapped_rg(command)
            and not (bounded_read_paths and command_is_single_bounded_read_of_paths(command, bounded_read_paths))
        ):
            findings.append(
                {
                    "level": "warn",
                    "kind": "uncapped_rg_command",
                    "message": "worker ran rg without an output cap in a read-heavy task",
                    "command": command,
                }
            )
        if command_reads_runtime_evidence_root(command, bounded_read_paths):
            findings.append(
                {
                    "level": "warn",
                    "kind": "runtime_evidence_root_read",
                    "message": "worker searched a runtime evidence root instead of a specific evidence path",
                    "command": command,
                }
            )
        findings.extend(compound_wide_read_command_findings(task, command))
        if command_directly_writes_workspace(command):
            findings.append(
                {
                    "level": "error",
                    "kind": "direct_workspace_write",
                    "message": "worker edited repository files directly instead of using SEARCH/REPLACE final output",
                    "command": command,
                }
            )
        findings.extend(allowed_read_path_findings(task, command))
        session_read_finding = forbidden_session_context_read(task, command)
        if session_read_finding:
            findings.append(session_read_finding)
        sed_windows = sed_windows_from_command(command)
        if sed_windows:
            cumulative_sed_command_count += 1
            cumulative_sed_lines += sum(end - start + 1 for start, end in sed_windows)
            if (
                total_sed_line_limit is not None
                and cumulative_sed_lines > total_sed_line_limit
                and not cumulative_sed_recorded
            ):
                findings.append(
                    {
                        "level": "warn",
                        "kind": "cumulative_sed_read_observation",
                        "message": "worker stayed under per-window sed bounds but exceeded the task's cumulative source read budget",
                        "command": command,
                        "total_sed_lines": cumulative_sed_lines,
                        "sed_command_count": cumulative_sed_command_count,
                        "limit": total_sed_line_limit,
                        "recommendation": "for observation-only tasks, prefer rg anchors and fewer targeted snippets before asking for more context",
                    }
                )
                cumulative_sed_recorded = True
        findings.extend(sed_window_governance(task, command, rationale=last_agent_rationale))
    error_findings = [finding for finding in findings if finding.get("level") == "error"]
    result = {
        "status": "fail" if error_findings else "pass",
        "policy": "declared_checks_and_task_command_bounds_are_authoritative",
        "direct_file_change_policy": direct_change_policy,
        "findings": findings,
        "error_findings_count": len(error_findings),
        "output_path": str(output_path),
    }
    if write_output:
        write_json(output_path, result)
    return result


def task_path_for_summary(summary: dict[str, Any]) -> Path | None:
    task_id = str(summary.get("task_id") or "").strip()
    if not task_id:
        return None
    for directory in (DONE_DIR, RUNNING_DIR, QUEUE_DIR):
        candidate = directory / f"{task_id}.md"
        if candidate.exists():
            return candidate
    return None


def replay_process_governance_for_summary(summary: dict[str, Any]) -> dict[str, Any]:
    run_dir = Path(str(summary.get("run_dir") or ""))
    worker = summary.get("worker", {}) if isinstance(summary.get("worker"), dict) else {}
    event_path = str(worker.get("event_summaries_path") or "")
    task_path = task_path_for_summary(summary)
    if not run_dir.exists() or not event_path or task_path is None:
        return {"status": "unavailable", "findings": []}
    return classify_process_governance(
        parse_task(task_path),
        {"event_summaries_path": event_path},
        run_dir,
        write_output=False,
    )


def process_governance_has_only_direct_file_change_errors(process_governance: dict[str, Any] | None) -> bool:
    if not isinstance(process_governance, dict) or process_governance.get("status") != "fail":
        return False
    findings = process_governance.get("findings", [])
    findings = findings if isinstance(findings, list) else []
    error_findings = [
        item
        for item in findings
        if isinstance(item, dict) and item.get("level") == "error"
    ]
    return bool(error_findings) and all(
        item.get("kind") == "direct_file_change_event" for item in error_findings
    )


def decide_status(
    worker: dict[str, Any],
    diff: dict[str, Any],
    checks: list[dict[str, Any]],
    patch_guard: dict[str, Any] | None = None,
    scope_guard: dict[str, Any] | None = None,
    patch_apply: dict[str, Any] | None = None,
    worker_envelope: dict[str, Any] | None = None,
    process_governance: dict[str, Any] | None = None,
    allow_no_diff: bool = False,
) -> str:
    failure = classify_worker_failure(worker)
    if failure.get("status"):
        return str(failure["status"])
    if worker_envelope and worker_envelope.get("status") == "needs-approval":
        return "needs-approval"
    if worker_envelope and worker_envelope.get("status") == "fail":
        return "needs-repair"
    if (
        patch_apply
        and patch_apply.get("status") == "skip-dirty-worktree"
        and process_governance
        and process_governance.get("direct_file_change_policy") == "repair"
    ):
        return "needs-repair"
    if patch_apply and patch_apply.get("status") == "fail":
        return "needs-repair"
    if patch_guard and patch_guard.get("status") == "fail":
        return "needs-repair"
    if scope_guard and scope_guard.get("status") == "fail":
        return "needs-repair"
    direct_change_only_process_failure = process_governance_has_only_direct_file_change_errors(process_governance)
    if process_governance and process_governance.get("status") == "fail" and not direct_change_only_process_failure:
        findings = process_governance.get("findings", [])
        findings = findings if isinstance(findings, list) else []
        direct_change_repair = process_governance.get("direct_file_change_policy") == "repair" and any(
            item.get("level") == "error" and item.get("kind") == "direct_file_change_event"
            for item in findings
            if isinstance(item, dict)
        )
        return "needs-repair" if direct_change_repair else "monitor-blocked"
    failed_checks = [item for item in checks if item["return_code"] != 0]
    if failed_checks:
        return "needs-repair"
    if changed_files_claim_without_patch_evidence(diff, patch_apply, worker_envelope):
        return "needs-repair"
    if diff["diff_bytes"] == 0:
        if allow_no_diff:
            return "pass"
        return "needs-followup"
    return "pass"


def changed_files_claim_without_patch_evidence(
    diff: dict[str, Any],
    patch_apply: dict[str, Any] | None,
    worker_envelope: dict[str, Any] | None,
) -> bool:
    if not isinstance(worker_envelope, dict):
        return False
    envelope = worker_envelope.get("envelope")
    if not isinstance(envelope, dict):
        return False
    output = envelope.get("output")
    if not isinstance(output, dict):
        return False
    changed_files = output.get("changed_files")
    if not isinstance(changed_files, list):
        return False
    declared = [str(item).strip() for item in changed_files if str(item).strip()]
    if not declared:
        return False
    if int(diff.get("diff_bytes", 0) or 0) > 0:
        return False
    if not isinstance(patch_apply, dict):
        return True
    touched = patch_apply.get("touched_files")
    if isinstance(touched, list) and any(str(item).strip() for item in touched):
        return False
    applied_count = int(patch_apply.get("applied_count", 0) or 0)
    already_applied_count = int(patch_apply.get("already_applied_count", 0) or 0)
    success_count = int(patch_apply.get("success_count", 0) or 0)
    return applied_count <= 0 and already_applied_count <= 0 and success_count <= 0


def reconcile_worker_envelope_check_conflict(
    worker_envelope: dict[str, Any] | None,
    checks: list[dict[str, Any]],
    patch_apply: dict[str, Any] | None = None,
    patch_guard: dict[str, Any] | None = None,
    scope_guard: dict[str, Any] | None = None,
    process_governance: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(worker_envelope, dict) or worker_envelope.get("status") != "fail":
        return None
    findings = worker_envelope.get("findings") if isinstance(worker_envelope.get("findings"), list) else []
    parse_failure = any(
        str(item.get("message") or "") == "no worker envelope JSON object found"
        for item in findings
        if isinstance(item, dict)
    )
    if parse_failure:
        if not checks or any(item.get("return_code") != 0 for item in checks):
            return None
        if patch_apply and patch_apply.get("status") == "fail":
            return None
        if not patch_guard or patch_guard.get("status") != "pass":
            return None
        if not scope_guard or scope_guard.get("status") != "pass":
            return None
        if process_governance and process_governance.get("status") == "fail":
            return None
        return {
            "status": "reconciled-pass",
            "reason": "worker envelope parse failed but patch, scope, process governance, and supervisor checks passed",
            "error_code": "worker_envelope_parse_failed",
            "error_message": "no worker envelope JSON object found",
            "checks_count": len(checks),
            "patch_guard_status": patch_guard.get("status"),
            "scope_guard_status": scope_guard.get("status"),
        }
    envelope = worker_envelope.get("envelope")
    if not isinstance(envelope, dict) or envelope.get("ok") is not False:
        return None
    error = envelope.get("error")
    if not isinstance(error, dict):
        return None
    error_code = str(error.get("code") or "").strip().lower()
    error_message = str(error.get("message") or "").strip().lower()
    stale_self_report = error_code in {"declared_check_timeout", "declared_checks_failed", "declared_check_failed"} or (
        "declared_check" in error_message and ("timeout" in error_message or "fail" in error_message)
    )
    if not stale_self_report:
        return None
    if not checks or any(item.get("return_code") != 0 for item in checks):
        return None
    if patch_apply and patch_apply.get("status") == "fail":
        return None
    if patch_guard and patch_guard.get("status") == "fail":
        return None
    if scope_guard and scope_guard.get("status") == "fail":
        return None
    if process_governance and process_governance.get("status") == "fail":
        return None
    return {
        "status": "reconciled-pass",
        "reason": "worker self-reported declared check failure/timeout but supervisor checks passed",
        "error_code": error_code,
        "error_message": error_message,
        "checks_count": len(checks),
    }


def task_allows_no_diff(task: Task) -> bool:
    fields = parse_key_value_prompt(task.prompt)
    if parse_bool_field(fields, "allow_no_diff", False):
        return True
    if task.phase == "test":
        return True
    if "expected_file_changes" in fields and not parse_bool_field(fields, "expected_file_changes", True):
        return True
    if "expect_file_changes" in fields and not parse_bool_field(fields, "expect_file_changes", True):
        return True
    return re.search(r"\bdo not (modify|change|edit) files\b|\bno file changes\b", task.prompt, re.I) is not None


def compact_guard_summary(summary: dict[str, Any]) -> dict[str, Any]:
    guards: dict[str, Any] = {}
    for guard_name in ("patch_guard", "scope_guard"):
        guard = summary.get(guard_name)
        if not isinstance(guard, dict):
            continue
        item: dict[str, Any] = {
            "status": guard.get("status"),
            "return_code": guard.get("return_code"),
            "findings_count": len(guard.get("findings", [])),
            "output_path": guard.get("output_path"),
        }
        if guard_name == "patch_guard":
            item["kind"] = guard.get("kind")
            item["touched_files"] = guard.get("touched_files", [])
        if guard_name == "scope_guard":
            item["changed_files"] = guard.get("changed_files", [])
            item["allowed_paths"] = guard.get("allowed_paths", [])
        guards[guard_name] = item
    return guards


def compact_context_pressure(summary: dict[str, Any]) -> dict[str, Any]:
    worker = summary.get("worker")
    if not isinstance(worker, dict):
        return {}
    approx_tokens = worker.get("prompt_approx_tokens")
    budget_tokens = worker.get("prompt_budget_tokens")
    if not isinstance(approx_tokens, int) or not isinstance(budget_tokens, int):
        return {}
    remaining_tokens = max(0, budget_tokens - approx_tokens)
    ratio = round(approx_tokens / budget_tokens, 3) if budget_tokens > 0 else 0.0
    return {
        "prompt_approx_tokens": approx_tokens,
        "prompt_budget_tokens": budget_tokens,
        "budget_ratio": ratio,
        "remaining_tokens": remaining_tokens,
        "over_budget": approx_tokens > budget_tokens,
        "actual_token_usage": worker.get("actual_token_usage", {}),
        "section_budgets": worker.get("prompt_section_budgets", {}),
        "previous_context_path": worker.get("previous_context_path", ""),
        "previous_context_compression": worker.get("previous_context_compression", {}),
        "repo_map": worker.get("repo_map", {}),
        "context_router": worker.get("context_router", {}),
    }


REFERENCE_PATH_RE = re.compile(r"\b(?:reference-projects|vendor-src)/[^\s`'\",)]+")


def prompt_reference_paths(prompt: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for match in REFERENCE_PATH_RE.finditer(prompt):
        path = match.group(0).rstrip("。.;:")
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def command_touches_reference(command: str, reference_path: str) -> bool:
    normalized_command = command.replace("\\", "/")
    normalized_reference = reference_path.replace("\\", "/")
    return normalized_reference in normalized_command


def command_is_bounded_read(command: str) -> bool:
    normalized = " ".join(command.split())
    return bool(
        re.search(r"\b(sed\s+-n|rg\s+--line-number|rg\s+--files|head\s+-n|tail\s+-n|nl\s+-ba)\b", normalized)
    )


def execution_chain_next_slice(worker_envelope: dict[str, Any]) -> str:
    envelope = worker_envelope.get("envelope") if isinstance(worker_envelope, dict) else {}
    if not isinstance(envelope, dict):
        return ""
    output = envelope.get("output")
    if isinstance(output, dict):
        return resolve_next_slice_contract(output).get("next_slice", "")
    return ""


def build_execution_chain(task: Task, run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    worker = summary.get("worker", {}) if isinstance(summary.get("worker"), dict) else {}
    event_summaries_path = Path(str(worker.get("event_summaries_path") or ""))
    event_summaries = read_jsonl(event_summaries_path)
    commands: list[dict[str, Any]] = []
    reads: list[dict[str, Any]] = []
    for item in event_summaries:
        if item.get("item_type") != "command_execution":
            continue
        command = str(item.get("command") or "")
        record = {
            "command": command,
            "status": item.get("status"),
            "exit_code": item.get("exit_code"),
            "output_preview": item.get("output_preview", ""),
        }
        commands.append(record)
        if command_is_bounded_read(command):
            reads.append(record)

    declared_references = prompt_reference_paths(task.prompt)
    reference_evidence = []
    for reference_path in declared_references:
        matching_reads = [read for read in reads if command_touches_reference(read["command"], reference_path)]
        reference_evidence.append(
            {
                "path": reference_path,
                "observed": bool(matching_reads),
                "read_commands": matching_reads[:10],
            }
        )

    diff = summary.get("diff", {}) if isinstance(summary.get("diff"), dict) else {}
    patch_apply = summary.get("patch_apply", {}) if isinstance(summary.get("patch_apply"), dict) else {}
    context_pressure = summary.get("context_pressure") or compact_context_pressure(summary)
    tokens = {}
    if isinstance(context_pressure, dict):
        tokens.update(context_pressure.get("actual_token_usage") or {})
    if not tokens:
        tokens.update(worker.get("actual_token_usage") or {})

    evidence_path = summary.get("evidence_path") or str(run_dir / "evidence.jsonl")
    return {
        "schema": "a9.execution_chain.v1",
        "task_id": task.task_id,
        "run_id": Path(str(summary.get("run_dir") or run_dir)).name,
        "attempt": summary.get("attempt"),
        "status": summary.get("status"),
        "phase": summary.get("phase") or task.phase,
        "task_prompt_preview": truncate_to_token_budget(task.prompt, 500, keep="head"),
        "reference_evidence": reference_evidence,
        "commands": commands,
        "reads": reads,
        "patch": {
            "changed_files": diff.get("changed_files", []),
            "diff_path": diff.get("diff_path", ""),
            "patch_apply_status": patch_apply.get("status", ""),
            "patch_apply_output_path": patch_apply.get("output_path", ""),
        },
        "checks": [
            {
                "command": check.get("command"),
                "return_code": check.get("return_code"),
                "output_path": check.get("output_path"),
            }
            for check in summary.get("checks", [])
            if isinstance(check, dict)
        ],
        "tokens": tokens,
        "next_slice": execution_chain_next_slice(summary.get("worker_envelope", {})),
        "evidence_paths": {
            "event_summaries_path": str(event_summaries_path) if str(event_summaries_path) else "",
            "raw_task_path": str(worker.get("raw_task_path") or ""),
            "final_path": str(worker.get("final_path") or ""),
            "evidence_path": evidence_path,
        },
    }


def write_execution_chain_artifact(task: Task, run_dir: Path, summary: dict[str, Any]) -> Path:
    output_path = run_dir / "execution_chain.json"
    chain = build_execution_chain(task, run_dir, summary)
    write_json(output_path, chain)
    summary["execution_chain_path"] = str(output_path)
    return output_path


def runtime_monitor_action(summary: dict[str, Any]) -> str:
    status = str(summary.get("status") or "")
    monitor_block = summary.get("monitor_block", {}) if isinstance(summary.get("monitor_block"), dict) else {}
    worker_failure = summary.get("worker_failure", {}) if isinstance(summary.get("worker_failure"), dict) else {}
    if monitor_block.get("blocked"):
        return "repair"
    if status in {"needs-repair", "monitor-blocked"}:
        return "repair"
    if status == "needs-approval":
        return "approve_or_reject"
    if status.startswith("retryable-") or worker_failure.get("status"):
        return "repair"
    if status == "pass":
        return "continue"
    return "route_to_debate"


def build_runtime_monitor_contract(task: Task, run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    worker = summary.get("worker", {}) if isinstance(summary.get("worker"), dict) else {}
    context_pressure = summary.get("context_pressure") or compact_context_pressure(summary)
    execution_chain_path = str(summary.get("execution_chain_path") or run_dir / "execution_chain.json")
    evidence_path = str(summary.get("evidence_path") or run_dir / "evidence.jsonl")
    state_path = str(summary.get("state_path") or run_dir / "state.json")
    deep_marks_path = str(summary.get("deep_marks_path") or run_dir / "deep_marks.jsonl")
    worker_prompt_path = str(run_dir / "prompt.md")
    raw_task_path = str(worker.get("raw_task_path") or run_dir / "raw_task.md")
    monitor_score = summary.get("monitor_score", {}) if isinstance(summary.get("monitor_score"), dict) else {}
    monitor_block = summary.get("monitor_block", {}) if isinstance(summary.get("monitor_block"), dict) else {}
    worker_envelope = summary.get("worker_envelope", {}) if isinstance(summary.get("worker_envelope"), dict) else {}
    patch_apply = summary.get("patch_apply", {}) if isinstance(summary.get("patch_apply"), dict) else {}
    diff = summary.get("diff", {}) if isinstance(summary.get("diff"), dict) else {}
    checks = summary.get("checks", []) if isinstance(summary.get("checks"), list) else []
    failed_checks = [item for item in checks if isinstance(item, dict) and item.get("return_code") != 0]
    reference_gate = worker.get("reference_gate", {}) if isinstance(worker.get("reference_gate"), dict) else {}
    command_envelope = {
        "status": "derived_from_task",
        "command_id": summary.get("task_id") or task.task_id,
        "target_node": "local-supervisor",
        "expected_revision": summary.get("attempt"),
        "ttl": task.timeout_seconds,
        "created_by": "a9_supervisor",
        "policy_attestation": summary.get("policy_attestation", {}),
        "idempotency_key": f"{task.task_id}:{summary.get('attempt', 1)}",
        "evidence_path": evidence_path,
    }
    return {
        "schema": "a9.runtime_monitor_contract.v1",
        "task": {
            "task_id": task.task_id,
            "task_path": str(task.path),
            "phase": task.phase,
            "route": "execution_next" if task.phase in AI_WORKER_PHASES else task.phase,
            "plan_revision": summary.get("flow_transition", {}).get("revision")
            if isinstance(summary.get("flow_transition"), dict)
            else "",
            "allowed_paths": task.allowed_paths,
            "declared_checks": task.checks,
            "timeout_seconds": task.timeout_seconds,
            "idle_timeout_seconds": task.idle_timeout_seconds,
            "max_attempts": task.max_attempts,
        },
        "run": {
            "run_id": Path(str(summary.get("run_dir") or run_dir)).name,
            "run_dir": str(summary.get("run_dir") or run_dir),
            "attempt": summary.get("attempt"),
            "status": summary.get("status"),
            "started_at": summary.get("started_at"),
            "finished_at": summary.get("finished_at"),
            "worktree": summary.get("worktree", ""),
        },
        "worker_intent": {
            "status": "visible",
            "phase_focus": PHASE_FOCUS.get(task.phase, ""),
            "prompt_preview": truncate_to_token_budget(task.prompt, 700, keep="head"),
            "reference_gate_status": reference_gate.get("status"),
            "reference_gate_output_path": reference_gate.get("output_path"),
        },
        "worker_prompt": {
            "prompt_path": worker_prompt_path,
            "raw_task_path": raw_task_path,
            "prompt_approx_tokens": worker.get("prompt_approx_tokens"),
            "prompt_budget_tokens": worker.get("prompt_budget_tokens"),
            "section_budgets": worker.get("prompt_section_budgets", {}),
            "context_router": worker.get("context_router", {}),
            "mempalace_wakeup": worker.get("mempalace_wakeup", {}),
            "mempalace_recall": worker.get("mempalace_recall", {}),
        },
        "reference_slices": {
            "declared_reference_paths": prompt_reference_paths(task.prompt),
            "reference_gate": reference_gate,
        },
        "command_envelope": command_envelope,
        "execution": {
            "worker_model": worker.get("worker_model"),
            "worker_model_source": worker.get("worker_model_source"),
            "return_code": worker.get("return_code"),
            "timed_out": worker.get("timed_out", False),
            "idle_timed_out": worker.get("idle_timed_out", False),
            "event_count": worker.get("event_count", 0),
            "event_bytes": worker.get("event_bytes", 0),
            "budget_stopped": worker.get("budget_stopped", False),
            "budget_reason": worker.get("budget_reason", ""),
        },
        "diff_and_checks": {
            "changed_files": diff.get("changed_files", []),
            "diff_path": diff.get("diff_path", ""),
            "diff_bytes": diff.get("diff_bytes", 0),
            "patch_apply_status": patch_apply.get("status"),
            "patch_guard_status": summary.get("patch_guard", {}).get("status")
            if isinstance(summary.get("patch_guard"), dict)
            else None,
            "scope_guard_status": summary.get("scope_guard", {}).get("status")
            if isinstance(summary.get("scope_guard"), dict)
            else None,
            "checks_count": len(checks),
            "failed_checks_count": len(failed_checks),
            "failed_checks": failed_checks[:10],
        },
        "monitor": {
            "score": monitor_score.get("score"),
            "decision_model": monitor_score.get("decision_model"),
            "recommended_action": monitor_score.get("recommended_action"),
            "block": monitor_block,
            "next_action": runtime_monitor_action(summary),
            "intervention_options": [
                "pause",
                "resume",
                "repair",
                "change_request",
                "approve",
                "reject",
                "rollback_request",
                "route_to_debate",
            ],
        },
        "context_pressure": context_pressure,
        "session_links": {
            "operator_session": "external_session_link_pending",
            "previous_context_path": worker.get("previous_context_path", ""),
            "context_path": summary.get("context_path", ""),
        },
        "evidence_refs": {
            "summary_path": str(run_dir / "summary.json"),
            "runtime_monitor_contract_path": str(run_dir / "runtime_monitor_contract.json"),
            "execution_chain_path": execution_chain_path,
            "evidence_path": evidence_path,
            "state_path": state_path,
            "deep_marks_path": deep_marks_path,
            "events_path": worker.get("events_path", ""),
            "event_summaries_path": worker.get("event_summaries_path", ""),
            "final_path": worker.get("final_path", ""),
            "worker_envelope_path": worker_envelope.get("output_path", ""),
            "monitor_score_path": monitor_score.get("output_path", ""),
        },
        "guardrails": {
            "page_details_frozen": True,
            "no_nzx_business_code": True,
            "no_compute_rwa": True,
            "no_broad_workspace_migration": True,
            "no_source_vendor_copy": True,
        },
    }


def write_runtime_monitor_contract_artifact(task: Task, run_dir: Path, summary: dict[str, Any]) -> Path:
    output_path = run_dir / "runtime_monitor_contract.json"
    contract = build_runtime_monitor_contract(task, run_dir, summary)
    write_json(output_path, contract)
    summary["runtime_monitor_contract_path"] = str(output_path)
    summary["runtime_monitor_contract"] = {
        "schema": contract["schema"],
        "task": contract["task"],
        "run": contract["run"],
        "monitor": contract["monitor"],
        "evidence_refs": contract["evidence_refs"],
        "guardrails": contract["guardrails"],
    }
    return output_path


def monitor_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    monitor_score = summary.get("monitor_score", {})
    findings = monitor_score.get("findings", []) if isinstance(monitor_score, dict) else []
    return [item for item in findings if isinstance(item, dict)]


def guard_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for name in ("reference_gate", "worker_envelope", "patch_apply", "patch_guard", "scope_guard", "process_governance"):
        guard = summary.get(name, {})
        if name == "reference_gate":
            worker = summary.get("worker", {})
            guard = worker.get("reference_gate", {}) if isinstance(worker, dict) else {}
        if not isinstance(guard, dict):
            continue
        if name == "reference_gate" and guard.get("status") == "fail":
            findings.append(
                {
                    "source": name,
                    "level": "error",
                    "kind": "reference_gate_missing",
                    "message": "prompt-declared reference paths missing from worker worktree",
                    "output_path": guard.get("output_path", ""),
                    "missing_paths": guard.get("missing_paths", []),
                }
            )
        for item in guard.get("findings", []) or []:
            if isinstance(item, dict):
                findings.append({"source": name, **item})
    return findings


def build_memory_commit(task: Task, run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    execution_chain_path = Path(str(summary.get("execution_chain_path") or run_dir / "execution_chain.json"))
    execution_chain = read_json_file(execution_chain_path)
    reference_evidence = execution_chain.get("reference_evidence", []) if isinstance(execution_chain, dict) else []
    observed_references = [item for item in reference_evidence if isinstance(item, dict) and item.get("observed")]
    missing_references = [item for item in reference_evidence if isinstance(item, dict) and not item.get("observed")]
    checks = summary.get("checks", []) if isinstance(summary.get("checks"), list) else []
    failed_checks = [item for item in checks if isinstance(item, dict) and item.get("return_code") not in {0, None}]
    passed_checks = [item for item in checks if isinstance(item, dict) and item.get("return_code") == 0]
    worker_failure = summary.get("worker_failure", {}) if isinstance(summary.get("worker_failure"), dict) else {}
    status = str(summary.get("status") or "")
    next_slice = str(execution_chain.get("next_slice") or "") if isinstance(execution_chain, dict) else ""

    doctrine_updates: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    eval_samples: list[dict[str, Any]] = []
    next_tasks: list[dict[str, Any]] = []

    if observed_references:
        doctrine_updates.append(
            {
                "kind": "reference_first",
                "memory_type": "procedure",
                "text": "Worker run produced observable bounded reads for prompt-declared reference sources before implementation evidence.",
                "confidence": 0.72,
                "evidence": [item.get("path") for item in observed_references],
            }
        )
    if missing_references:
        rules.append(
            {
                "kind": "reference_gate",
                "memory_type": "risk",
                "text": "Prompt-declared reference sources were not observed in execution_chain reads; future workers should repair reference slice/path access before continuing implementation.",
                "severity": "warn",
                "evidence": [item.get("path") for item in missing_references],
            }
        )
    if worker_failure.get("category") == "budget" or status.startswith("retryable-worker-budget"):
        rules.append(
            {
                "kind": "budget_governance",
                "memory_type": "risk",
                "text": "Worker budget failure is an execution-chain signal; inspect event_summaries for path churn or over-broad reads before retrying.",
                "severity": "warn",
                "evidence": [summary.get("worker", {}).get("event_summaries_path", "")],
            }
        )
    for finding in guard_findings(summary) + monitor_findings(summary):
        level = str(finding.get("level") or "")
        if level not in {"error", "warn"}:
            continue
        rules.append(
            {
                "kind": str(finding.get("kind") or finding.get("message") or "governance_finding")[:80],
                "memory_type": "risk" if level == "error" else "procedure",
                "text": bounded_inline(str(finding.get("message") or finding), 500),
                "severity": level,
                "evidence": [str(finding.get("output_path") or summary.get("evidence_path") or "")],
            }
        )
    if checks:
        eval_samples.append(
            {
                "kind": "supervisor_run_eval",
                "status": "fail" if failed_checks else "pass",
                "text": f"Run {Path(str(summary.get('run_dir') or run_dir)).name} finished with {len(passed_checks)} passing checks and {len(failed_checks)} failing checks.",
                "checks": [
                    {
                        "command": item.get("command"),
                        "return_code": item.get("return_code"),
                        "output_path": item.get("output_path"),
                    }
                    for item in checks
                    if isinstance(item, dict)
                ],
            }
        )
    if next_slice:
        next_tasks.append(
            {
                "kind": "worker_next_slice",
                "text": next_slice,
                "source": "worker_envelope.output.next_slice",
            }
        )

    evidence_paths = {
        "execution_chain_path": str(execution_chain_path),
        "evidence_path": str(summary.get("evidence_path") or run_dir / "evidence.jsonl"),
        "state_path": str(summary.get("state_path") or run_dir / "state.json"),
        "deep_marks_path": str(summary.get("deep_marks_path") or run_dir / "deep_marks.jsonl"),
    }
    return {
        "schema": "a9.memory_commit.v1",
        "task_id": task.task_id,
        "run_id": Path(str(summary.get("run_dir") or run_dir)).name,
        "checkpoint_id": summary.get("checkpoint_id") or "",
        "status": status,
        "phase": summary.get("phase") or task.phase,
        "created_at": utc_now(),
        "source": "deterministic_execution_chain_curator",
        "doctrine_updates": doctrine_updates,
        "rules": rules,
        "eval_samples": eval_samples,
        "next_tasks": next_tasks,
        "evidence_paths": evidence_paths,
        "stats": {
            "observed_reference_count": len(observed_references),
            "missing_reference_count": len(missing_references),
            "rule_count": len(rules),
            "eval_sample_count": len(eval_samples),
            "next_task_count": len(next_tasks),
        },
    }


def write_memory_commit_artifact(task: Task, run_dir: Path, summary: dict[str, Any]) -> Path:
    output_path = run_dir / "memory_commit.json"
    commit = build_memory_commit(task, run_dir, summary)
    write_json(output_path, commit)
    summary["memory_commit_path"] = str(output_path)
    summary["memory_commit_stats"] = commit.get("stats", {})
    return output_path


def failed_experts_from_monitor_score(monitor_score: dict[str, Any]) -> list[str]:
    gates = monitor_score.get("gates") if isinstance(monitor_score.get("gates"), dict) else {}
    failed: list[str] = []
    for gate in gates.values():
        if not isinstance(gate, dict):
            continue
        for name in gate.get("failed_experts", []) or []:
            if isinstance(name, str) and name not in failed:
                failed.append(name)
    return failed


def build_eval_store_record(task: Task, run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    run_id = Path(str(summary.get("run_dir") or run_dir)).name
    monitor_score = summary.get("monitor_score") if isinstance(summary.get("monitor_score"), dict) else {}
    eval_contract_path = Path(str(monitor_score.get("eval_contract_path") or run_dir / "moe_eval_contract.json"))
    eval_contract = read_json_file(eval_contract_path)
    layers = monitor_score.get("layers") if isinstance(monitor_score.get("layers"), dict) else {}
    failed_experts = failed_experts_from_monitor_score(monitor_score)
    findings = monitor_score.get("findings", []) if isinstance(monitor_score.get("findings"), list) else []
    samples: list[dict[str, Any]] = []
    for expert in failed_experts:
        expert_findings = [item for item in findings if isinstance(item, dict) and item.get("expert") == expert]
        samples.append(
            {
                "kind": "failed_expert_eval_sample",
                "expert": expert,
                "status": "fail",
                "recommended_action": monitor_score.get("recommended_action", ""),
                "findings": expert_findings[:8],
                "evidence_refs": {
                    "monitor_score_path": monitor_score.get("output_path", str(run_dir / "monitor_score.json")),
                    "eval_contract_path": str(eval_contract_path),
                    "run_dir": str(run_dir),
                },
            }
        )
    record = {
        "schema": "a9.eval_store_record.v1",
        "record_id": f"eval-{run_id}",
        "run_id": run_id,
        "task_id": task.task_id,
        "phase": summary.get("phase") or task.phase,
        "status": summary.get("status", ""),
        "created_at": utc_now(),
        "source": "supervisor_moe_eval_store",
        "rule_monitor": {
            "decision_model": monitor_score.get("decision_model", ""),
            "score": monitor_score.get("score", 0),
            "recommended_action": monitor_score.get("recommended_action", ""),
            "gates": monitor_score.get("gates", {}),
            "failed_experts": failed_experts,
        },
        "llm_evaluator": layers.get("llm_evaluator", {"status": "not_configured"}),
        "manual_override": None,
        "eval_contract": {
            "path": str(eval_contract_path),
            "schema": eval_contract.get("schema", "a9.moe_eval_contract.v1") if isinstance(eval_contract, dict) else "",
            "sha256": sha256_file(eval_contract_path) if eval_contract_path.exists() else "",
        },
        "monitor_score_path": monitor_score.get("output_path", str(run_dir / "monitor_score.json")),
        "evidence_paths": {
            "summary_path": str(run_dir / "summary.json"),
            "state_path": str(summary.get("state_path") or run_dir / "state.json"),
            "evidence_path": str(summary.get("evidence_path") or run_dir / "evidence.jsonl"),
            "execution_chain_path": str(summary.get("execution_chain_path") or run_dir / "execution_chain.json"),
            "memory_commit_path": str(summary.get("memory_commit_path") or run_dir / "memory_commit.json"),
        },
        "eval_samples": samples,
        "stats": {
            "failed_expert_count": len(failed_experts),
            "eval_sample_count": len(samples),
            "finding_count": len(findings),
        },
    }
    record["record_hash"] = sha256_text(stable_json({key: value for key, value in record.items() if key != "record_hash"}))
    return record


def append_eval_store_index(record: dict[str, Any]) -> None:
    ensure_dirs()
    index_path = EVAL_STORE_DIR / "index.jsonl"
    record_id = str(record.get("record_id") or "")
    existing_ids: set[str] = set()
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("record_id"):
                existing_ids.add(str(item["record_id"]))
    if record_id in existing_ids:
        return
    index_row = {
        "record_id": record.get("record_id"),
        "run_id": record.get("run_id"),
        "task_id": record.get("task_id"),
        "status": record.get("status"),
        "recommended_action": record.get("rule_monitor", {}).get("recommended_action", ""),
        "failed_experts": record.get("rule_monitor", {}).get("failed_experts", []),
        "record_path": str(EVAL_STORE_RUNS_DIR / f"{compact_task_ref(str(record.get('run_id') or 'run'))}.json"),
        "record_hash": record.get("record_hash"),
        "created_at": record.get("created_at"),
    }
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(index_row, ensure_ascii=False, sort_keys=True) + "\n")


def write_eval_store_record(task: Task, run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    record = build_eval_store_record(task, run_dir, summary)
    output_path = run_dir / "eval_store_record.json"
    global_path = EVAL_STORE_RUNS_DIR / f"{compact_task_ref(str(record.get('run_id') or 'run'))}.json"
    write_json(output_path, record)
    write_json(global_path, record)
    append_eval_store_index(record)
    result = {
        "status": "written",
        "output_path": str(output_path),
        "global_path": str(global_path),
        "index_path": str(EVAL_STORE_DIR / "index.jsonl"),
        "record_id": record.get("record_id"),
        "record_hash": record.get("record_hash"),
        "stats": record.get("stats", {}),
    }
    summary["eval_store_record"] = result
    return result


EVAL_OVERRIDE_ACTIONS = {
    "continue",
    "monitor_review",
    "needs_tradeoff",
    "narrow_task",
    "repair",
    "product_rewrite",
    "block_and_rewrite_task",
}


def load_eval_store_record_for_run(run_id: str) -> tuple[Path, dict[str, Any]]:
    run_path = RUNS_DIR / run_id / "eval_store_record.json"
    global_path = EVAL_STORE_RUNS_DIR / f"{compact_task_ref(run_id)}.json"
    for path in (run_path, global_path):
        record = read_json_file(path)
        if record:
            return path, record
    raise FileNotFoundError(f"eval store record not found for run_id={run_id}")


def append_eval_override_index(override: dict[str, Any]) -> None:
    ensure_dirs()
    index_path = EVAL_STORE_DIR / "overrides.jsonl"
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(override, ensure_ascii=False, sort_keys=True) + "\n")


def write_eval_manual_override(
    *,
    run_id: str,
    action: str,
    reason: str,
    actor: str,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    if action not in EVAL_OVERRIDE_ACTIONS:
        raise ValueError(f"invalid override action: {action}")
    if not reason.strip():
        raise ValueError("override reason is required")
    record_path, record = load_eval_store_record_for_run(run_id)
    override_id = f"override-{compact_task_ref(run_id)}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    rule_monitor = record.get("rule_monitor") if isinstance(record.get("rule_monitor"), dict) else {}
    override = {
        "schema": "a9.eval_manual_override.v1",
        "override_id": override_id,
        "run_id": run_id,
        "task_id": record.get("task_id", ""),
        "created_at": utc_now(),
        "actor": actor,
        "action": action,
        "reason": reason.strip(),
        "evidence_refs": evidence_refs or [],
        "original": {
            "record_path": str(record_path),
            "record_hash": record.get("record_hash", ""),
            "status": record.get("status", ""),
            "recommended_action": rule_monitor.get("recommended_action", ""),
            "failed_experts": rule_monitor.get("failed_experts", []),
            "gates": rule_monitor.get("gates", {}),
        },
        "training_label": {
            "kind": "manual_eval_override",
            "input_contract_path": record.get("eval_contract", {}).get("path", ""),
            "rule_action": rule_monitor.get("recommended_action", ""),
            "human_action": action,
            "reason": reason.strip(),
        },
    }
    override["override_hash"] = sha256_text(stable_json({key: value for key, value in override.items() if key != "override_hash"}))
    output_path = EVAL_STORE_OVERRIDES_DIR / f"{override_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, override)
    append_eval_override_index({**override, "override_path": str(output_path)})
    return {
        "status": "written",
        "output_path": str(output_path),
        "index_path": str(EVAL_STORE_DIR / "overrides.jsonl"),
        "override_id": override_id,
        "override_hash": override["override_hash"],
    }


def eval_override(args: argparse.Namespace) -> int:
    try:
        result = write_eval_manual_override(
            run_id=args.run_id,
            action=args.action,
            reason=args.reason,
            actor=args.actor,
            evidence_refs=args.evidence_ref or [],
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def patch_apply_block_line(item: dict[str, Any]) -> str:
    path = item.get("effective_path") or item.get("path") or "unknown"
    mode = item.get("mode", "unknown")
    index = item.get("index", "?")
    strategy = item.get("match_strategy", "unknown")
    replace_matches = item.get("replace_matches")
    suffix = f", replace_matches={replace_matches}" if replace_matches is not None else ""
    return f"- block {index}: {path} mode={mode} strategy={strategy}{suffix}"


def format_patch_apply_repair_hint(
    patch_apply: dict[str, Any],
    git_governance: dict[str, Any] | None = None,
) -> str:
    if not patch_apply:
        return ""
    git_governance = git_governance or {}
    rolled_back = bool(git_governance.get("rolled_back"))
    successful = patch_apply.get("successful_blocks") or []
    failed = patch_apply.get("failed_blocks") or []
    lines = [
        "Patch apply repair metadata:",
        f"- status: {patch_apply.get('status', 'missing')}",
        f"- applied_count: {patch_apply.get('applied_count', 0)}",
        f"- already_applied_count: {patch_apply.get('already_applied_count', 0)}",
        f"- success_count: {patch_apply.get('success_count', len(successful))}",
        f"- failed_count: {patch_apply.get('failed_count', len(failed))}",
        f"- partial_success: {patch_apply.get('partial_success', False)}",
        f"- git_governance_status: {git_governance.get('status', 'missing')}",
        f"- git_rolled_back: {rolled_back}",
    ]
    if successful:
        if rolled_back:
            success_guidance = (
                "Successful blocks were recorded before git governance rolled the run back; "
                "inspect current file content before deciding whether to resend them."
            )
        else:
            success_guidance = (
                "Successful blocks already handled; do not resend them unless the current file content proves "
                "they were rolled back."
            )
        lines.extend(
            [
                "",
                success_guidance,
                *[patch_apply_block_line(item) for item in successful],
            ]
        )
    if failed:
        lines.extend(["", "Failed blocks that need repair:", *[patch_apply_block_line(item) for item in failed]])
    repair_hint = patch_apply.get("repair_hint", "")
    if repair_hint:
        lines.extend(["", "Patch apply repair hint:", "", repair_hint])
    return "\n".join(lines)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def create_monitor_score(run_dir: Path) -> dict[str, Any]:
    output_path = run_dir / "monitor_score.json"
    monitor_path = ROOT / "scripts" / "a9_monitor.py"
    if not monitor_path.exists():
        payload = {
            "status": "unavailable",
            "score": 0.0,
            "recommended_action": "continue",
            "findings": [{"level": "warn", "kind": "monitor_missing", "message": "a9_monitor.py missing"}],
            "output_path": str(output_path),
        }
        write_json(output_path, payload)
        return payload
    spec = importlib.util.spec_from_file_location("a9_monitor_runtime", monitor_path)
    if not spec or not spec.loader:
        payload = {
            "status": "unavailable",
            "score": 0.0,
            "recommended_action": "continue",
            "findings": [{"level": "warn", "kind": "monitor_load_failed", "message": "cannot load monitor module"}],
            "output_path": str(output_path),
        }
        write_json(output_path, payload)
        return payload
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = module.score_run(run_dir)
    module.write_score(run_dir, payload)
    payload["output_path"] = str(output_path)
    return payload


def json_compact(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sql_quote(value: Any) -> str:
    if value is None:
        return "NULL"
    text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def rel_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_policy_attestation(task: Task, run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    output_path = run_dir / "policy_attestation.json"
    fields = parse_key_value_prompt(task.prompt)
    policy = {
        "scope": "a9-supervisor-run",
        "allowed_paths": task.allowed_paths,
        "checks": task.checks,
        "phase": task.phase,
        "strict_worker_envelope": parse_bool_field(fields, "strict_worker_envelope", False),
        "direct_file_change_policy": parse_direct_file_change_policy(task.prompt),
        "worker_model": summary.get("worker", {}).get("worker_model") or resolved_worker_model(task)[0],
        "worker_model_source": summary.get("worker", {}).get("worker_model_source") or resolved_worker_model(task)[1],
        "guards": ["worker_envelope", "patch_guard", "scope_guard", "checks", "git_governance"],
    }
    workspace = {
        "diff": {
            "path": summary.get("diff", {}).get("diff_path", ""),
            "bytes": summary.get("diff", {}).get("diff_bytes", 0),
        },
        "worker_envelope": {
            "status": summary.get("worker_envelope", {}).get("status"),
            "required": summary.get("worker_envelope", {}).get("required", False),
        },
        "patch_apply": {
            "status": summary.get("patch_apply", {}).get("status"),
            "applied_count": summary.get("patch_apply", {}).get("applied_count", 0),
            "failed_count": summary.get("patch_apply", {}).get("failed_count", 0),
        },
        "patch_guard": {
            "status": summary.get("patch_guard", {}).get("status"),
            "touched_files": summary.get("patch_guard", {}).get("touched_files", []),
        },
        "scope_guard": {
            "status": summary.get("scope_guard", {}).get("status"),
            "changed_files": summary.get("scope_guard", {}).get("changed_files", []),
            "allowed_paths": summary.get("scope_guard", {}).get("allowed_paths", []),
        },
        "checks": [
            {
                "command": item.get("command", ""),
                "return_code": item.get("return_code"),
                "output_path": item.get("output_path", ""),
            }
            for item in summary.get("checks", [])
        ],
        "git_governance": {
            "status": summary.get("git_governance", {}).get("status"),
            "commit": summary.get("git_governance", {}).get("commit", ""),
            "rolled_back": summary.get("git_governance", {}).get("rolled_back", False),
        },
    }
    findings = []
    for guard_name in ("worker_envelope", "patch_apply", "patch_guard", "scope_guard", "git_governance"):
        guard = summary.get(guard_name, {})
        if isinstance(guard, dict):
            for finding in guard.get("findings", []) or []:
                findings.append({"source": guard_name, **finding})
    for index, check in enumerate(summary.get("checks", []), start=1):
        if check.get("return_code") != 0:
            findings.append(
                {
                    "source": "check",
                    "level": "error",
                    "message": "check failed",
                    "index": index,
                    "command": check.get("command", ""),
                    "return_code": check.get("return_code"),
                }
            )
    ok = summary.get("status") in {"pass", "needs-followup", "needs-approval"}
    policy_hash = sha256_text(stable_json(policy))
    workspace_hash = sha256_text(stable_json(workspace))
    findings_hash = sha256_text(stable_json(findings))
    attestation = {
        "checked_at": utc_now(),
        "ok": ok,
        "policy": {
            "path": "a9://supervisor/runtime-policy",
            "hash": policy_hash,
            "snapshot": policy,
        },
        "workspace": {
            "scope": "policy",
            "hash": workspace_hash,
            "evidence": workspace,
        },
        "findings": findings,
        "findingsHash": findings_hash,
        "attestationHash": sha256_text(
            stable_json(
                {
                    "ok": ok,
                    "policyHash": policy_hash,
                    "workspaceHash": workspace_hash,
                    "findingsHash": findings_hash,
                }
            )
        ),
        "source": "openclaw_policy_attestation_shape",
    }
    write_json(output_path, attestation)
    return {
        "status": "pass" if ok else "fail",
        "output_path": str(output_path),
        "policy_hash": policy_hash,
        "workspace_hash": workspace_hash,
        "findings_hash": findings_hash,
        "attestation_hash": attestation["attestationHash"],
        "findings_count": len(findings),
        "source": "reference-projects/openclaw/extensions/policy/src/policy-state.ts",
    }


def evidence_record(
    *,
    run_id: str,
    checkpoint_id: str,
    kind: str,
    path: Path,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return {
        "evidence_id": f"{checkpoint_id}:{kind}:{len(str(path))}:{path.name}",
        "run_id": run_id,
        "checkpoint_id": checkpoint_id,
        "kind": kind,
        "path": rel_path(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "created_at": utc_now(),
        "metadata": metadata or {},
    }


def mark_record(
    *,
    record: dict[str, Any],
    index: int,
    kind: str,
    label: str,
    value: str,
    weight: float = 1.0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "mark_id": f"{record['evidence_id']}:mark:{index}",
        "session_id": record.get("session_id", record["run_id"]),
        "run_id": record["run_id"],
        "checkpoint_id": record["checkpoint_id"],
        "evidence_id": record["evidence_id"],
        "kind": kind,
        "label": label,
        "value": value,
        "weight": weight,
        "metadata": metadata or {},
        "created_at": utc_now(),
    }


def extract_deep_marks_from_text(record: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    marks: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8", errors="backslashreplace")
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if is_noise_line(stripped):
            continue
        if stripped.startswith("#"):
            marks.append(
                mark_record(
                    record=record,
                    index=len(marks) + 1,
                    kind="heading",
                    label="markdown_heading",
                    value=stripped,
                    weight=0.8,
                    metadata={"line": line_no},
                )
            )
        if re.search(r"\b(TODO|FIXME|error|failed|needs-repair|timeout|blocked)\b", stripped, re.I):
            marks.append(
                mark_record(
                    record=record,
                    index=len(marks) + 1,
                    kind="risk_or_status",
                    label="status_signal",
                    value=stripped,
                    weight=1.4,
                    metadata={"line": line_no},
                )
            )
        for match in re.finditer(r"[\w./-]+\.(?:py|rs|ts|tsx|js|jsx|md|toml|yml|yaml|sql|json)", stripped):
            marks.append(
                mark_record(
                    record=record,
                    index=len(marks) + 1,
                    kind="file_reference",
                    label="file_path",
                    value=match.group(0),
                    weight=1.2,
                    metadata={"line": line_no},
                )
            )
        if stripped.startswith(("-", "*")) and len(stripped) > 2:
            marks.append(
                mark_record(
                    record=record,
                    index=len(marks) + 1,
                    kind="detail",
                    label="bullet_detail",
                    value=stripped,
                    weight=0.7,
                    metadata={"line": line_no},
                )
            )
    return marks


def extract_deep_marks_from_events(record: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    marks: list[dict[str, Any]] = []
    if not path.exists():
        return marks
    seen_events: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if is_noise_line(line):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            normalized = normalize_context_line(line[:500])
            if normalized in seen_events:
                continue
            seen_events.add(normalized)
            marks.append(
                mark_record(
                    record=record,
                    index=len(marks) + 1,
                    kind="event_line",
                    label="raw_event",
                    value=line[:500],
                    weight=0.6,
                    metadata={"line": line_no, "parse_error": True},
                )
            )
            continue
        event_type = payload.get("type") or payload.get("event") or payload.get("msg", {}).get("type")
        value = json.dumps(payload, ensure_ascii=False)[:1000]
        normalized = normalize_context_line(f"{event_type}:{value}")
        if normalized in seen_events:
            continue
        seen_events.add(normalized)
        marks.append(
            mark_record(
                record=record,
                index=len(marks) + 1,
                kind="event",
                label=str(event_type or "unknown"),
                value=value,
                weight=1.0,
                metadata={"line": line_no},
            )
        )
    return marks


def extract_deep_marks_from_diff(record: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    marks: list[dict[str, Any]] = []
    if not path.exists():
        return marks
    current_file = ""
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="backslashreplace").splitlines(), start=1):
        if line.startswith("diff --git "):
            parts = line.split()
            current_file = parts[-1][2:] if len(parts) >= 4 and parts[-1].startswith("b/") else line
            marks.append(
                mark_record(
                    record=record,
                    index=len(marks) + 1,
                    kind="changed_file",
                    label="diff_file",
                    value=current_file,
                    weight=1.6,
                    metadata={"line": line_no},
                )
            )
        elif line.startswith("@@"):
            marks.append(
                mark_record(
                    record=record,
                    index=len(marks) + 1,
                    kind="diff_hunk",
                    label=current_file or "hunk",
                    value=line,
                    weight=1.3,
                    metadata={"line": line_no, "file": current_file},
                )
            )
        elif line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            stripped = line[:500]
            if re.search(r"\b(def |class |function |CREATE TABLE|CREATE INDEX|import |from )", stripped):
                marks.append(
                    mark_record(
                        record=record,
                        index=len(marks) + 1,
                        kind="code_symbol_change",
                        label=current_file or "symbol_change",
                        value=stripped,
                        weight=1.5,
                        metadata={"line": line_no, "file": current_file},
                    )
                )
    return marks


def extract_deep_marks(record: dict[str, Any]) -> list[dict[str, Any]]:
    path = ROOT / record["path"]
    kind = record["kind"]
    if kind == "events":
        return extract_deep_marks_from_events(record, path)
    if kind == "patch":
        return extract_deep_marks_from_diff(record, path)
    if kind == "patch_guard":
        marks = extract_deep_marks_from_text(record, path)
        metadata = record.get("metadata", {})
        marks.insert(
            0,
            mark_record(
                record=record,
                index=0,
                kind="patch_guard_result",
                label="patch_guard_status",
                value=f"{metadata.get('status')} -> {metadata.get('return_code')}",
                weight=1.8 if metadata.get("status") == "fail" else 1.3,
                metadata=metadata,
            ),
        )
        return marks
    if kind == "scope_guard":
        marks = extract_deep_marks_from_text(record, path)
        metadata = record.get("metadata", {})
        marks.insert(
            0,
            mark_record(
                record=record,
                index=0,
                kind="scope_guard_result",
                label="scope_guard_status",
                value=f"{metadata.get('status')} -> {metadata.get('return_code')}",
                weight=1.8 if metadata.get("status") == "fail" else 1.3,
                metadata=metadata,
            ),
        )
        return marks
    marks = extract_deep_marks_from_text(record, path)
    if kind == "check_log":
        command = record.get("metadata", {}).get("command", "")
        return_code = record.get("metadata", {}).get("return_code")
        marks.insert(
            0,
            mark_record(
                record=record,
                index=0,
                kind="check_result",
                label="command_status",
                value=f"{command} -> {return_code}",
                weight=1.8 if return_code else 1.2,
                metadata=record.get("metadata", {}),
            ),
        )
    return marks


def write_evidence_and_state(
    task: Task,
    run_dir: Path,
    summary: dict[str, Any],
    context_path: Path,
) -> tuple[Path, Path, Path, list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    run_id = Path(summary["run_dir"]).name
    checkpoint_id = f"{run_id}:checkpoint:{summary['attempt']}"
    records: list[dict[str, Any]] = []
    execution_chain_path = write_execution_chain_artifact(task, run_dir, summary)
    memory_commit_path = write_memory_commit_artifact(task, run_dir, summary)

    paths = [
        ("raw_task", Path(summary["worker"]["raw_task_path"]), {"task_id": task.task_id}),
        ("prompt", run_dir / "prompt.md", {"task_id": task.task_id}),
        ("events", Path(summary["worker"]["events_path"]), summary["worker"]["event_counts"]),
        (
            "event_summary",
            Path(summary["worker"]["event_summaries_path"]),
            {"count": summary["worker"].get("event_summary_count", 0)},
        ),
        ("stderr", Path(summary["worker"]["stderr_path"]), {}),
        ("final_message", Path(summary["worker"]["final_path"]), {}),
        (
            "reference_gate",
            Path(summary["worker"].get("reference_gate", {}).get("output_path") or run_dir / "reference_gate.missing"),
            {
                "status": summary["worker"].get("reference_gate", {}).get("status"),
                "missing_count": summary["worker"].get("reference_gate", {}).get("missing_count", 0),
            },
        ),
        (
            "goal_state",
            Path(summary.get("goal_state", {}).get("output_path") or run_dir / "goal_state.missing"),
            {
                "enabled": summary.get("goal_state", {}).get("enabled", False),
                "status": summary.get("goal_state", {}).get("status", ""),
                "goal_id": summary.get("goal_state", {}).get("goal", {}).get("goal_id")
                if isinstance(summary.get("goal_state", {}).get("goal"), dict)
                else summary.get("goal_state", {}).get("goal_id", ""),
            },
        ),
        (
            "worker_envelope",
            Path(summary["worker_envelope"]["output_path"]),
            {
                "status": summary["worker_envelope"].get("status"),
                "required": summary["worker_envelope"].get("required", False),
            },
        ),
        (
            "patch_apply",
            Path(summary["patch_apply"]["output_path"]),
            {
                "status": summary["patch_apply"].get("status"),
                "return_code": summary["patch_apply"].get("return_code"),
                "applied_count": summary["patch_apply"].get("applied_count", 0),
                "already_applied_count": summary["patch_apply"].get("already_applied_count", 0),
                "success_count": summary["patch_apply"].get("success_count", 0),
                "failed_count": summary["patch_apply"].get("failed_count", 0),
                "touched_files": summary["patch_apply"].get("touched_files", []),
                "referenced_files": summary["patch_apply"].get("referenced_files", []),
            },
        ),
        ("patch", Path(summary["diff"]["diff_path"]), {"diff_bytes": summary["diff"]["diff_bytes"]}),
        (
            "patch_guard",
            Path(summary["patch_guard"]["output_path"]),
            {
                "status": summary["patch_guard"].get("status"),
                "return_code": summary["patch_guard"].get("return_code"),
                "touched_files": summary["patch_guard"].get("touched_files", []),
            },
        ),
        (
            "scope_guard",
            Path(summary["scope_guard"]["output_path"]),
            {
                "status": summary["scope_guard"].get("status"),
                "return_code": summary["scope_guard"].get("return_code"),
                "changed_files": summary["scope_guard"].get("changed_files", []),
                "allowed_paths": summary["scope_guard"].get("allowed_paths", []),
            },
        ),
        (
            "git_governance",
            Path(summary["git_governance"]["output_path"]),
            {
                "status": summary["git_governance"].get("status"),
                "commit": summary["git_governance"].get("commit", ""),
                "rolled_back": summary["git_governance"].get("rolled_back", False),
            },
        ),
        (
            "policy_attestation",
            Path(summary["policy_attestation"]["output_path"]),
            {
                "status": summary["policy_attestation"].get("status"),
                "policy_hash": summary["policy_attestation"].get("policy_hash"),
                "workspace_hash": summary["policy_attestation"].get("workspace_hash"),
                "findings_hash": summary["policy_attestation"].get("findings_hash"),
                "attestation_hash": summary["policy_attestation"].get("attestation_hash"),
            },
        ),
        (
            "monitor_score",
            Path(summary.get("monitor_score", {}).get("output_path") or run_dir / "monitor_score.missing"),
            {
                "decision_model": summary.get("monitor_score", {}).get("decision_model", ""),
                "recommended_action": summary.get("monitor_score", {}).get("recommended_action", ""),
                "score": summary.get("monitor_score", {}).get("score", 0),
            },
        ),
        (
            "moe_eval_contract",
            Path(summary.get("monitor_score", {}).get("eval_contract_path") or run_dir / "moe_eval_contract.missing"),
            {
                "schema": "a9.moe_eval_contract.v1",
                "llm_evaluator_status": summary.get("monitor_score", {})
                .get("layers", {})
                .get("llm_evaluator", {})
                .get("status", ""),
            },
        ),
        (
            "eval_store_record",
            Path(summary.get("eval_store_record", {}).get("output_path") or run_dir / "eval_store_record.missing"),
            {
                "schema": "a9.eval_store_record.v1",
                "record_id": summary.get("eval_store_record", {}).get("record_id", ""),
                "record_hash": summary.get("eval_store_record", {}).get("record_hash", ""),
            },
        ),
        ("execution_chain", execution_chain_path, {"schema": "a9.execution_chain.v1"}),
        ("memory_commit", memory_commit_path, summary.get("memory_commit_stats", {})),
        ("context", context_path, {"status": summary["status"]}),
    ]
    for kind, path, metadata in paths:
        if not str(path):
            continue
        record = evidence_record(
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            kind=kind,
            path=path,
            metadata=metadata,
        )
        if record:
            record["session_id"] = task.task_id
            records.append(record)

    for index, check in enumerate(summary["checks"], start=1):
        record = evidence_record(
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            kind="check_log",
            path=Path(check["output_path"]),
            metadata={
                "index": index,
                "command": check["command"],
                "return_code": check["return_code"],
                "duration_seconds": check["duration_seconds"],
            },
        )
        if record:
            record["session_id"] = task.task_id
            records.append(record)

    evidence_path = run_dir / "evidence.jsonl"
    with evidence_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    deep_marks = []
    for record in records:
        deep_marks.extend(extract_deep_marks(record))
    deep_marks_path = run_dir / "deep_marks.jsonl"
    with deep_marks_path.open("w", encoding="utf-8") as handle:
        for mark in deep_marks:
            handle.write(json.dumps(mark, ensure_ascii=False) + "\n")

    by_kind: dict[str, list[str]] = {}
    for record in records:
        by_kind.setdefault(record["kind"], []).append(record["evidence_id"])

    state = {
        "checkpoint_id": checkpoint_id,
        "session_id": task.task_id,
        "parent_checkpoint_id": summary.get("parent_checkpoint_id"),
        "step": summary["attempt"],
        "source": "loop",
        "created_at": utc_now(),
        "status": summary["status"],
        "channels": {
            "task": by_kind.get("prompt", []),
            "messages": by_kind.get("final_message", []) + by_kind.get("context", []),
            "tool_events": by_kind.get("events", []) + by_kind.get("stderr", []),
            "event_summaries": by_kind.get("event_summary", []),
            "reference_gates": by_kind.get("reference_gate", []),
            "goal_states": by_kind.get("goal_state", []),
            "worker_envelopes": by_kind.get("worker_envelope", []),
            "repo_state": [
                {
                    "repo_head": summary["repo_head"],
                    "worktree": summary["worktree"],
                }
            ],
            "patches": by_kind.get("patch_apply", []) + by_kind.get("patch", []) + by_kind.get("patch_guard", []),
            "guards": by_kind.get("patch_guard", []) + by_kind.get("scope_guard", []),
            "git_governance": by_kind.get("git_governance", []),
            "policy_attestations": by_kind.get("policy_attestation", []),
            "monitor_scores": by_kind.get("monitor_score", []),
            "moe_eval_contracts": by_kind.get("moe_eval_contract", []),
            "eval_store_records": by_kind.get("eval_store_record", []),
            "execution_chains": by_kind.get("execution_chain", []),
            "memory_commits": by_kind.get("memory_commit", []),
            "checks": by_kind.get("check_log", []),
            "deep_marks": [mark["mark_id"] for mark in deep_marks],
            "memories": by_kind.get("memory_commit", []),
        },
        "updated_channels": [
            "task",
            "messages",
            "tool_events",
            "event_summaries",
            "reference_gates",
            "goal_states",
            "worker_envelopes",
            "repo_state",
            "patches",
            "guards",
            "git_governance",
            "policy_attestations",
            "monitor_scores",
            "moe_eval_contracts",
            "eval_store_records",
            "execution_chains",
            "memory_commits",
            "checks",
            "context_pressure",
            "deep_marks",
        ],
        "evidence_ids": [record["evidence_id"] for record in records],
        "deep_mark_count": len(deep_marks),
        "context_pressure": summary.get("context_pressure", compact_context_pressure(summary)),
        "context_compression": summary["worker"].get("previous_context_compression", {}),
        "repo_map": summary["worker"].get("repo_map", {}),
    }
    state_path = run_dir / "state.json"
    write_json(state_path, state)
    return evidence_path, state_path, deep_marks_path, records, state, deep_marks


def mysql_exec_stdin(sql: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "a9-mysql",
            "mysql",
            "-h127.0.0.1",
            "-ua9",
            "-pa9_dev_password",
            "a9",
        ],
        cwd=ROOT,
        text=True,
        input=sql,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def redis_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["docker", "exec", "a9-redis", "redis-cli", *args],
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            ["docker", "exec", "a9-redis", "redis-cli", *args],
            124,
            stdout=f"redis-cli timeout after {exc.timeout}s",
        )


def redis_available() -> bool:
    return redis_cli(["PING"]).stdout.strip().endswith("PONG")


def redis_deep_mark_limit() -> int:
    value = os.getenv("A9_REDIS_DEEP_MARK_LIMIT", str(DEFAULT_REDIS_DEEP_MARK_LIMIT))
    try:
        return max(0, int(value))
    except ValueError:
        return DEFAULT_REDIS_DEEP_MARK_LIMIT


def redis_flow_key(flow_id: str) -> str:
    return f"{FLOW_KEY_PREFIX}{flow_id}"


def transition_managed_flow(
    *,
    flow_id: str,
    expected_revision: int | None,
    next_status: str,
    actor: str,
    reason: str,
    evidence_id: str,
    expected_last_seq: int | None = None,
    sequence: int | None = None,
) -> dict[str, Any]:
    if not flow_id:
        return {"enabled": False, "status": "skipped", "reason": "missing_flow_id"}
    if expected_revision is None:
        return {"enabled": False, "status": "skipped", "reason": "missing_expected_revision", "flow_id": flow_id}
    if not redis_available():
        return {"enabled": True, "status": "unavailable", "flow_id": flow_id}

    result = redis_cli(
        [
            "FCALL",
            "transition_flow",
            "1",
            redis_flow_key(flow_id),
            str(expected_revision),
            next_status,
            actor,
            reason,
            evidence_id,
            utc_now(),
            "" if expected_last_seq is None else str(expected_last_seq),
            "" if sequence is None else str(sequence),
        ]
    )
    output = result.stdout.strip()
    payload: dict[str, Any] | None = None
    if output.startswith("{"):
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            payload = None
    status = "pass" if payload and result.returncode == 0 else "fail"
    if "revision_mismatch" in output or "flow_not_found" in output:
        status = "fail"
    if "sequence_mismatch" in output:
        status = "fail"
    if payload and payload.get("terminal_reason") == "sequence_gap":
        status = "fail"
    if payload and payload.get("status") == "quarantined":
        status = "fail"
    if (
        status == "pass"
        and sequence is not None
        and payload
        and payload.get("revision") == expected_revision
        and int(payload.get("last_seq", 0)) >= sequence
    ):
        status = "skipped"
    return {
        "enabled": True,
        "status": status,
        "flow_id": flow_id,
        "expected_revision": expected_revision,
        "expected_last_seq": expected_last_seq,
        "sequence": sequence,
        "next_status": next_status,
        "return_code": result.returncode,
        "output": output,
        "revision": payload.get("revision") if payload else None,
        "last_seq": payload.get("last_seq") if payload else None,
        "flow_status": payload.get("status") if payload else "",
        "terminal_reason": payload.get("terminal_reason") if payload else "",
    }


def set_managed_flow_wait(
    *,
    flow_id: str,
    expected_revision: int | None,
    worker_envelope: dict[str, Any],
    policy_attestation: dict[str, Any] | None = None,
    actor: str,
    evidence_id: str,
) -> dict[str, Any]:
    if not flow_id:
        return {"enabled": False, "status": "skipped", "reason": "missing_flow_id"}
    if expected_revision is None:
        return {"enabled": False, "status": "skipped", "reason": "missing_expected_revision", "flow_id": flow_id}
    if not redis_available():
        return {"enabled": True, "status": "unavailable", "flow_id": flow_id, "kind": "flow_wait"}
    envelope = worker_envelope.get("envelope") if isinstance(worker_envelope, dict) else {}
    approval = envelope.get("requiresApproval") if isinstance(envelope, dict) else {}
    if not isinstance(approval, dict):
        return {"enabled": True, "status": "fail", "flow_id": flow_id, "reason": "missing_requiresApproval"}
    prompt = str(approval.get("prompt") or "Worker requested approval.")
    approval_id = str(approval.get("approvalId") or "")
    resume_token = str(approval.get("resumeToken") or "")
    policy_hash = str((policy_attestation or {}).get("attestation_hash") or "")
    waiting_step = "worker_needs_approval"
    if policy_hash:
        waiting_step = f"{waiting_step}:policy:{policy_hash[:12]}"
    result = redis_cli(
        [
            "FCALL",
            "set_waiting_flow",
            "1",
            redis_flow_key(flow_id),
            str(expected_revision),
            actor,
            prompt,
            approval_id,
            resume_token,
            waiting_step,
            utc_now(),
        ]
    )
    output = result.stdout.strip()
    payload: dict[str, Any] | None = None
    if output.startswith("{"):
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            payload = None
    status = "pass" if payload and result.returncode == 0 else "fail"
    if "revision_mismatch" in output or "flow_not_found" in output:
        status = "fail"
    return {
        "enabled": True,
        "kind": "flow_wait",
        "status": status,
        "flow_id": flow_id,
        "expected_revision": expected_revision,
        "next_status": "waiting",
        "return_code": result.returncode,
        "output": output,
        "revision": payload.get("revision") if payload else None,
        "flow_status": payload.get("status") if payload else "",
        "approval_id": approval_id,
        "resume_token_present": bool(resume_token),
        "policy_attestation_hash": policy_hash,
        "evidence_id": evidence_id,
    }


def redis_session_payload(
    task: Task,
    summary: dict[str, Any],
    state: dict[str, Any],
    evidence_count: int,
) -> dict[str, Any]:
    channel_counts = {
        name: len(value) if isinstance(value, list) else 1
        for name, value in state.get("channels", {}).items()
    }
    return {
        "session_id": task.task_id,
        "current_checkpoint_id": state["checkpoint_id"],
        "status": summary["status"],
        "updated_at": summary["finished_at"],
        "run_id": Path(summary["run_dir"]).name,
        "run_dir": summary["run_dir"],
        "summary_path": str(Path(summary["run_dir"]) / "summary.json"),
        "state_path": str(Path(summary["run_dir"]) / "state.json"),
        "evidence_path": summary.get("evidence_path"),
        "deep_marks_path": summary.get("deep_marks_path"),
        "execution_chain_path": summary.get("execution_chain_path"),
        "memory_commit_path": summary.get("memory_commit_path"),
        "memory_commit_stats": summary.get("memory_commit_stats", {}),
        "goal_state": summary.get("goal_state", {}),
        "eval_store_record": summary.get("eval_store_record", {}),
        "guard_summary": summary.get("guard_summary", compact_guard_summary(summary)),
        "context_pressure": summary.get("context_pressure", compact_context_pressure(summary)),
        "git_governance": summary.get("git_governance", {}),
        "policy_attestation": summary.get("policy_attestation", {}),
        "actual_token_usage": summary.get("worker", {}).get("actual_token_usage", {}),
        "channel_counts": channel_counts,
        "deep_mark_count": state.get("deep_mark_count", 0),
        "evidence_count": evidence_count,
    }


def mysql_available() -> bool:
    result = run_cmd_no_raise(
        [
            "docker",
            "exec",
            "a9-mysql",
            "mysql",
            "-h127.0.0.1",
            "-ua9",
            "-pa9_dev_password",
            "a9",
            "-NBe",
            "select 1;",
        ]
    )
    return result.returncode == 0


def persist_mysql(
    task: Task,
    summary: dict[str, Any],
    evidence: list[dict[str, Any]],
    state: dict[str, Any],
    deep_marks: list[dict[str, Any]],
) -> dict[str, Any]:
    if not mysql_available():
        return {"enabled": False, "status": "unavailable"}

    checkpoint_id = state["checkpoint_id"]
    session_sql = f"""
INSERT INTO sessions (session_id, project_id, root_path, status, current_checkpoint_id, source)
VALUES ({sql_quote(task.task_id)}, 'a9', {sql_quote(str(ROOT))}, 'running', {sql_quote(checkpoint_id)}, 'codex_exec')
ON DUPLICATE KEY UPDATE
  status=VALUES(status),
  current_checkpoint_id=VALUES(current_checkpoint_id),
  updated_at=CURRENT_TIMESTAMP(6);
"""
    checkpoint_sql = f"""
INSERT INTO checkpoints (
  checkpoint_id, session_id, parent_checkpoint_id, step, source, status,
  channels, updated_channels, token_usage, evidence_ids
) VALUES (
  {sql_quote(checkpoint_id)},
  {sql_quote(task.task_id)},
  {sql_quote(state.get('parent_checkpoint_id'))},
  {int(summary['attempt'])},
  'loop',
  {sql_quote(summary['status'])},
  {sql_quote(json_compact(state['channels']))},
  {sql_quote(json_compact(state['updated_channels']))},
  {sql_quote(json_compact({
      'prompt_approx_tokens': summary['worker'].get('prompt_approx_tokens'),
      'prompt_budget_tokens': summary['worker'].get('prompt_budget_tokens'),
      'actual_token_usage': summary['worker'].get('actual_token_usage', {}),
      'context_pressure': summary.get('context_pressure', {}),
      'previous_context_compression': summary['worker'].get('previous_context_compression', {}),
      'repo_map': summary['worker'].get('repo_map', {}),
  }))},
  {sql_quote(json_compact(state['evidence_ids']))}
) ON DUPLICATE KEY UPDATE
  status=VALUES(status),
  parent_checkpoint_id=VALUES(parent_checkpoint_id),
  channels=VALUES(channels),
  updated_channels=VALUES(updated_channels),
  token_usage=VALUES(token_usage),
  evidence_ids=VALUES(evidence_ids);
"""
    evidence_sql = "\n".join(
        f"""
INSERT INTO evidence (
  evidence_id, session_id, checkpoint_id, kind, path, sha256, size_bytes, metadata
) VALUES (
  {sql_quote(item['evidence_id'])},
  {sql_quote(task.task_id)},
  {sql_quote(item['checkpoint_id'])},
  {sql_quote(item['kind'])},
  {sql_quote(item['path'])},
  {sql_quote(item['sha256'])},
  {int(item['size_bytes'])},
  {sql_quote(json_compact(item.get('metadata', {})))}
) ON DUPLICATE KEY UPDATE
  path=VALUES(path),
  sha256=VALUES(sha256),
  size_bytes=VALUES(size_bytes),
  metadata=VALUES(metadata);
"""
        for item in evidence
    )
    marks_sql = "\n".join(
        f"""
INSERT INTO deep_context_marks (
  mark_id, session_id, checkpoint_id, evidence_id, kind, label, value, weight, metadata
) VALUES (
  {sql_quote(mark['mark_id'])},
  {sql_quote(task.task_id)},
  {sql_quote(mark['checkpoint_id'])},
  {sql_quote(mark['evidence_id'])},
  {sql_quote(mark['kind'])},
  {sql_quote(mark['label'])},
  {sql_quote(mark['value'])},
  {float(mark['weight'])},
  {sql_quote(json_compact(mark.get('metadata', {})))}
) ON DUPLICATE KEY UPDATE
  kind=VALUES(kind),
  label=VALUES(label),
  value=VALUES(value),
  weight=VALUES(weight),
  metadata=VALUES(metadata);
"""
        for mark in deep_marks
    )
    result = mysql_exec_stdin(session_sql + checkpoint_sql + evidence_sql + marks_sql)
    return {
        "enabled": True,
        "status": "ok" if result.returncode == 0 else "error",
        "return_code": result.returncode,
        "output": result.stdout[-4000:],
        "evidence_rows": len(evidence),
        "deep_mark_rows": len(deep_marks),
    }


def persist_redis(
    task: Task,
    summary: dict[str, Any],
    evidence: list[dict[str, Any]],
    state: dict[str, Any],
    deep_marks: list[dict[str, Any]],
) -> dict[str, Any]:
    if not redis_available():
        return {"enabled": False, "status": "unavailable"}

    run_id = Path(summary["run_dir"]).name
    checkpoint_id = state["checkpoint_id"]
    errors: list[str] = []

    def call(args: list[str]) -> None:
        try:
            result = redis_cli(args)
        except OSError as exc:
            errors.append(f"{args[0]} failed before redis-cli: {exc}")
            return
        if result.returncode != 0:
            errors.append(result.stdout.strip())

    session_payload = redis_session_payload(task, summary, state, len(evidence))

    call(
        [
            "XADD",
            "a9:events",
            "*",
            "type",
            "run_completed",
            "task_id",
            task.task_id,
            "run_id",
            run_id,
            "checkpoint_id",
            checkpoint_id,
            "status",
            summary["status"],
            "summary_path",
            str(Path(summary["run_dir"]) / "summary.json"),
        ]
    )
    call(
        [
            "JSON.SET",
            f"a9:session:{task.task_id}",
            "$",
            json_compact(session_payload),
        ]
    )
    for item in evidence:
        call(["BF.ADD", "a9:dedupe:evidence", item["sha256"]])
        call(
            [
                "XADD",
                "a9:events",
                "*",
                "type",
                "evidence",
                "task_id",
                task.task_id,
                "run_id",
                run_id,
                "evidence_id",
                item["evidence_id"],
                "kind",
                item["kind"],
                "path",
                item["path"],
            ]
        )
    deep_mark_limit = redis_deep_mark_limit()
    persisted_deep_marks = deep_marks[:deep_mark_limit]
    skipped_deep_marks = max(0, len(deep_marks) - len(persisted_deep_marks))
    for mark in persisted_deep_marks:
        call(
            [
                "JSON.SET",
                f"a9:deep_mark:{mark['mark_id']}",
                "$",
                json_compact(mark),
            ]
        )
        call(
            [
                "XADD",
                "a9:deep_marks",
                "*",
                "task_id",
                task.task_id,
                "run_id",
                run_id,
                "mark_id",
                mark["mark_id"],
                "kind",
                mark["kind"],
                "label",
                mark["label"],
                "value",
                mark["value"][:1000],
            ]
        )
    if skipped_deep_marks:
        call(
            [
                "XADD",
                "a9:deep_marks",
                "*",
                "task_id",
                task.task_id,
                "run_id",
                run_id,
                "kind",
                "redis_deep_mark_limit",
                "persisted",
                str(len(persisted_deep_marks)),
                "skipped",
                str(skipped_deep_marks),
            ]
        )
    call(["TS.ADD", "a9:ts:tokens_in", "*", str(summary["worker"].get("prompt_approx_tokens", 0))])
    call(["TS.ADD", "a9:ts:task_latency_ms", "*", "0"])
    if summary["status"].startswith("retryable-"):
        call(["TS.ADD", "a9:ts:retry", "*", "1"])
    call(["TS.ADD", "a9:ts:heartbeat", "*", "1"])
    return {
        "enabled": True,
        "status": "ok" if not errors else "error",
        "errors": errors[-10:],
        "evidence_events": len(evidence),
        "deep_mark_events": len(persisted_deep_marks),
        "deep_mark_skipped": skipped_deep_marks,
        "deep_mark_limit": deep_mark_limit,
    }


def persist_run_state(
    task: Task,
    summary: dict[str, Any],
    evidence: list[dict[str, Any]],
    state: dict[str, Any],
    deep_marks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "mysql": persist_mysql(task, summary, evidence, state, deep_marks),
        "redis": persist_redis(task, summary, evidence, state, deep_marks),
    }


def read_text_if_exists(path: Path, limit: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="backslashreplace")
    if len(text) > limit:
        return text[:limit] + "\n...[truncated]\n"
    return text


def worker_failure_text(worker: dict[str, Any], limit: int = 12000) -> str:
    parts: list[str] = []
    for key in ("budget_reason", "transport_reason"):
        if worker.get(key):
            parts.append(str(worker[key]))
    for key in ("event_summaries_path", "stderr_path", "final_path"):
        raw_path = worker.get(key)
        if not raw_path:
            continue
        path = Path(str(raw_path))
        parts.append(read_text_if_exists(path, limit=limit // 3))
    return "\n".join(part for part in parts if part).strip()[:limit]


def classify_transport_observation(worker: dict[str, Any]) -> dict[str, Any]:
    text = worker_failure_text(worker, limit=12000)
    matches: list[dict[str, str]] = []
    for pattern in WORKER_TRANSPORT_OBSERVATION_PATTERNS:
        match = pattern.search(text)
        if match:
            matches.append(
                {
                    "pattern": pattern.pattern,
                    "sample": bounded_inline(match.group(0), 240),
                }
            )
    if not matches:
        return {"status": "none", "category": "", "count": 0, "matches": []}
    return {
        "status": "observed",
        "category": "transport_runtime",
        "count": len(matches),
        "matches": matches,
        "does_not_affect_status": True,
    }


def classify_worker_failure(worker: dict[str, Any]) -> dict[str, Any]:
    reference_gate = worker.get("reference_gate", {})
    if isinstance(reference_gate, dict) and reference_gate.get("status") == "fail":
        return {
            "status": "monitor-blocked",
            "category": "reference_gate",
            "reason": "prompt-declared reference paths missing from worker worktree",
            "matched_pattern": "reference_gate_missing",
            "missing_paths": reference_gate.get("missing_paths", []),
        }
    if worker.get("transport_stopped"):
        return {
            "status": "retryable-worker-transport",
            "category": "transport",
            "reason": worker.get("transport_reason", "worker transport exhausted"),
            "matched_pattern": "transport_exhausted",
        }
    if worker.get("budget_stopped"):
        if worker.get("budget_stop_kind") == "command_bounds":
            return {
                "status": "monitor-blocked",
                "category": "process_governance",
                "reason": worker.get("budget_reason", "worker command blocked by task bounds"),
                "matched_pattern": "command_bounds",
            }
        return {
            "status": "retryable-worker-budget",
            "category": "budget",
            "reason": worker.get("budget_reason", "worker budget stopped"),
            "matched_pattern": "budget_stopped",
        }
    if worker.get("timed_out") or worker.get("idle_timed_out"):
        return {
            "status": "retryable-timeout",
            "category": "timeout",
            "reason": "worker timed out" if worker.get("timed_out") else "worker idle timed out",
            "matched_pattern": "timed_out" if worker.get("timed_out") else "idle_timed_out",
        }
    if worker.get("return_code", 0) == 0:
        return {"status": "", "category": "", "reason": "", "matched_pattern": ""}

    text = worker_failure_text(worker)
    patterns = [
        ("retryable-worker-network", WORKER_NETWORK_ERROR_PATTERNS),
        ("retryable-worker-startup", WORKER_STARTUP_ERROR_PATTERNS),
        ("retryable-worker-broken-pipe", WORKER_BROKEN_PIPE_PATTERNS),
    ]
    for status, compiled in patterns:
        for pattern in compiled:
            match = pattern.search(text)
            if match:
                return {
                    "status": status,
                    "category": status.removeprefix("retryable-worker-"),
                    "reason": match.group(0),
                    "matched_pattern": pattern.pattern,
                }
    return {
        "status": "retryable-worker-failed",
        "category": "worker-failed",
        "reason": f"worker return_code={worker.get('return_code')}",
        "matched_pattern": "return_code",
    }


def write_context_summary(task: Task, run_dir: Path, summary: dict[str, Any]) -> Path:
    final_text = read_text_if_exists(Path(summary["worker"]["final_path"]), limit=3000).strip()
    diff_text = read_text_if_exists(Path(summary["diff"]["diff_path"]), limit=3000).strip()
    failed_checks = [item for item in summary["checks"] if item["return_code"] != 0]
    checks_text = "\n".join(
        f"- `{item['command']}` -> {item['return_code']} ({item['output_path']})"
        for item in summary["checks"]
    )
    patch_apply = summary.get("patch_apply", {})
    patch_guard = summary.get("patch_guard", {})
    scope_guard = summary.get("scope_guard", {})
    git_governance = summary.get("git_governance", {})
    context_pressure = summary.get("context_pressure", compact_context_pressure(summary))
    patch_apply_repair = format_patch_apply_repair_hint(patch_apply, git_governance)
    content = f"""# Task Context: {task.task_id}

Updated: {summary['finished_at']}
Status: {summary['status']}
Attempt: {summary['attempt']}
Worktree: {summary['worktree']}

## Objective

{task.prompt}

## Worker Result

- return_code: {summary['worker']['return_code']}
- timed_out: {summary['worker']['timed_out']}
- idle_timed_out: {summary['worker']['idle_timed_out']}
- budget_stopped: {summary['worker'].get('budget_stopped', False)}
- budget_reason: {summary['worker'].get('budget_reason', '')}
- failure_status: {summary.get('worker_failure', {}).get('status', '')}
- failure_category: {summary.get('worker_failure', {}).get('category', '')}
- failure_reason: {summary.get('worker_failure', {}).get('reason', '')}
- event_count: {summary['worker'].get('event_count', 0)}
- event_bytes: {summary['worker'].get('event_bytes', 0)}
- events: {json.dumps(summary['worker']['event_counts'], ensure_ascii=False)}

## Checks

{checks_text or '- none'}

## Patch Apply

- status: {patch_apply.get('status', 'missing')}
- return_code: {patch_apply.get('return_code', 'missing')}
- applied_count: {patch_apply.get('applied_count', 0)}
- failed_count: {patch_apply.get('failed_count', 0)}
- already_applied_count: {patch_apply.get('already_applied_count', 0)}
- success_count: {patch_apply.get('success_count', 0)}
- partial_success: {patch_apply.get('partial_success', False)}
- referenced_files: {json.dumps(patch_apply.get('referenced_files', []), ensure_ascii=False)}
- output: {patch_apply.get('output_path', 'missing')}

{patch_apply_repair}

## Patch Guard

- status: {patch_guard.get('status', 'missing')}
- return_code: {patch_guard.get('return_code', 'missing')}
- output: {patch_guard.get('output_path', 'missing')}

## Scope Guard

- status: {scope_guard.get('status', 'missing')}
- return_code: {scope_guard.get('return_code', 'missing')}
- allowed_paths: {json.dumps(scope_guard.get('allowed_paths', []), ensure_ascii=False)}
- changed_files: {json.dumps(scope_guard.get('changed_files', []), ensure_ascii=False)}
- output: {scope_guard.get('output_path', 'missing')}

## Git Governance

- status: {git_governance.get('status', 'missing')}
- commit: {git_governance.get('commit', '')}
- rolled_back: {git_governance.get('rolled_back', False)}
- output: {git_governance.get('output_path', 'missing')}

## Context Pressure

- prompt_tokens: {context_pressure.get('prompt_approx_tokens', 'missing')}
- budget_tokens: {context_pressure.get('prompt_budget_tokens', 'missing')}
- budget_ratio: {context_pressure.get('budget_ratio', 'missing')}
- remaining_tokens: {context_pressure.get('remaining_tokens', 'missing')}

## Failed Checks

{json.dumps(failed_checks, ensure_ascii=False, indent=2)}

## Final Message

{final_text or '(empty)'}

## Patch Preview

```diff
{diff_text or '(empty)'}
```

## Next Continuation Prompt

Continue this task from the durable context above. If status is `needs-repair`, inspect the failed checks and patch, then produce a minimal repair. If status is `needs-followup`, make the next concrete progress step. If status is `pass`, propose the next task in the same project direction.
"""
    if summary.get("status") == "retryable-worker-budget":
        content = retryable_budget_context_summary(task, summary, context_pressure)
    context_path = run_dir / "context.md"
    context_path.write_text(content, encoding="utf-8")
    task_context_path = STATE_DIR / "tasks" / "done" / f"{artifact_task_ref(task.task_id)}.context.md"
    task_context_path.write_text(content, encoding="utf-8")
    return context_path


def retryable_budget_context_summary(
    task: Task,
    summary: dict[str, Any],
    context_pressure: dict[str, Any],
) -> str:
    worker = summary.get("worker", {}) if isinstance(summary.get("worker"), dict) else {}
    diff = summary.get("diff", {}) if isinstance(summary.get("diff"), dict) else {}
    patch_guard = summary.get("patch_guard", {}) if isinstance(summary.get("patch_guard"), dict) else {}
    scope_guard = summary.get("scope_guard", {}) if isinstance(summary.get("scope_guard"), dict) else {}
    checks = summary.get("checks", []) if isinstance(summary.get("checks"), list) else []
    failed_checks = [item for item in checks if isinstance(item, dict) and item.get("return_code") != 0]
    return f"""# Task Context: {task.task_id}

Updated: {summary.get('finished_at', '')}
Status: {summary.get('status', '')}
Attempt: {summary.get('attempt', '')}
Worktree: {summary.get('worktree', '')}

## Objective

{truncate_to_token_budget(task.prompt, 500, keep="tail")}

## Retryable Budget Failure

- failure_status: {summary.get('worker_failure', {}).get('status', '')}
- failure_reason: {summary.get('worker_failure', {}).get('reason', '')}
- budget_reason: {worker.get('budget_reason', '')}
- event_count: {worker.get('event_count', 0)}
- event_bytes: {worker.get('event_bytes', 0)}
- prompt_tokens: {context_pressure.get('prompt_approx_tokens', 'missing')}
- budget_tokens: {context_pressure.get('prompt_budget_tokens', 'missing')}
- run_dir: {summary.get('run_dir', '')}
- events_path: {worker.get('event_summaries_path', '')}
- diff_path: {diff.get('diff_path', '')}

## Evidence Summary

- diff_bytes: {diff.get('diff_bytes', 0)}
- patch_guard: {patch_guard.get('status', 'missing')}
- scope_guard: {scope_guard.get('status', 'missing')}
- changed_files: {json.dumps(scope_guard.get('changed_files', []), ensure_ascii=False)}
- checks_count: {len(checks)}
- failed_checks_count: {len(failed_checks)}

## Continuation Rule

The previous attempt exceeded the worker budget. Do not read this context file
back in full. Inspect only the specific evidence path needed, with bounded sed
windows or capped rg, then make the smallest repair or continuation step.
"""


def previous_task_checkpoint_id(task: Task) -> str | None:
    done_path = DONE_DIR / f"{artifact_task_ref(task.task_id)}.json"
    if not path_exists(done_path):
        legacy_path = DONE_DIR / f"{task.task_id}.json"
        if path_exists(legacy_path):
            done_path = legacy_path
    if not path_exists(done_path):
        return None
    try:
        summary = json.loads(done_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    state_path = summary.get("state_path")
    if state_path:
        path = Path(state_path)
        if path.exists():
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                state = {}
            checkpoint_id = state.get("checkpoint_id")
            if checkpoint_id:
                return str(checkpoint_id)
    checkpoint_id = summary.get("checkpoint_id")
    return str(checkpoint_id) if checkpoint_id else None


def parse_session_refresh_spec(prompt: str) -> dict[str, Any]:
    fields = parse_key_value_prompt(prompt)
    session_path = (
        fields.get("source_session_path")
        or fields.get("session_jsonl")
        or fields.get("session_path")
        or fields.get("path")
    )
    missing = [
        name
        for name, value in [
            ("source_session_path", session_path),
            ("from_turn", fields.get("from_turn")),
            ("to_turn", fields.get("to_turn")),
        ]
        if not value
    ]
    if missing:
        raise ValueError(f"missing session_refresh fields: {', '.join(missing)}")

    try:
        from_turn = int(str(fields["from_turn"]))
        to_turn = int(str(fields["to_turn"]))
        batch_size = int(str(fields.get("batch_size", "10")))
    except ValueError as exc:
        raise ValueError("from_turn, to_turn, and batch_size must be integers") from exc
    if from_turn < 1 or to_turn < from_turn:
        raise ValueError("from_turn must be >= 1 and to_turn must be >= from_turn")
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    auto_continue = parse_bool_field(fields, "auto_continue", True)
    auto_close_reading = parse_bool_field(fields, "auto_close_reading", True)

    return {
        "source_session_path": session_path,
        "from_turn": from_turn,
        "to_turn": to_turn,
        "batch_size": batch_size,
        "auto_continue": auto_continue,
        "auto_close_reading": auto_close_reading,
        "close_reading_doc": fields.get("close_reading_doc", "docs/session.md"),
        "summary_doc": fields.get("summary_doc", "docs/session.md"),
        "flow_id": fields.get("flow_id", ""),
        "flow_expected_revision": parse_optional_int(fields.get("flow_expected_revision")),
        "flow_expected_last_seq": parse_optional_int(fields.get("flow_expected_last_seq")),
        "flow_sequence": parse_optional_int(fields.get("flow_sequence")),
    }


def parse_bool_field(fields: dict[str, str], name: str, default: bool) -> bool:
    if name not in fields:
        return default
    return str(fields[name]).strip().lower() not in {"0", "false", "no", "off"}


def session_refresh_module() -> Any:
    module_name = "a9_session_refresh_supervisor"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "scripts" / "a9_session_refresh.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load scripts/a9_session_refresh.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def latest_codex_session_path(sessions_dir: Path | None = None) -> Path:
    root = sessions_dir or CODEX_SESSIONS_DIR
    candidates = [path for path in root.rglob("*.jsonl") if path.is_file()] if root.exists() else []
    if not candidates:
        raise FileNotFoundError(f"no Codex session JSONL found under {root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def latest_session_tail_range(session_path: Path, *, tail_turns: int, batch_size: int) -> dict[str, Any]:
    module = session_refresh_module()
    index = module.session_index(session_path, batch_size=max(1, batch_size))
    user_turn_count = int(index.get("user_turn_count") or 0)
    if user_turn_count < 1:
        raise ValueError(f"session has no user turns: {session_path}")
    bounded_tail = max(1, int(tail_turns))
    from_turn = max(1, user_turn_count - bounded_tail + 1)
    return {
        "session_id": index.get("session_id", ""),
        "source_session_path": str(session_path),
        "user_turn_count": user_turn_count,
        "from_turn": from_turn,
        "to_turn": user_turn_count,
        "batch_size": max(1, int(batch_size)),
    }


def session_lane_latest(args: argparse.Namespace) -> int:
    ensure_dirs()
    session_path_text = str(args.session_path or "").strip()
    session_path = Path(session_path_text) if session_path_text else latest_codex_session_path()
    if not session_path.is_absolute():
        session_path = ROOT / session_path
    tail = latest_session_tail_range(session_path, tail_turns=args.tail_turns, batch_size=args.batch_size)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    task_id = str(args.task_id or "").strip() or (
        f"session-lane-latest-{tail['session_id'] or compact_task_ref(session_path.stem)}-"
        f"{tail['from_turn']}-{tail['to_turn']}-{timestamp}"
    )
    prompt = f"""source_session_path: {tail['source_session_path']}
from_turn: {tail['from_turn']}
to_turn: {tail['to_turn']}
batch_size: {tail['batch_size']}
auto_continue: {str(bool(args.auto_continue)).lower()}
auto_close_reading: {str(not args.no_auto_close_reading).lower()}
close_reading_doc: {args.close_reading_doc}
summary_doc: {args.summary_doc}

Run the deterministic latest external operator session lane. Do not call a model,
do not run a worker, and do not enter the copy-project pipeline.
"""
    path = enqueue_task_file(
        task_id,
        prompt,
        phase=SESSION_REFRESH_PHASE,
        checks=[],
        timeout_seconds=args.timeout_seconds,
        idle_timeout_seconds=args.idle_timeout_seconds,
        max_attempts=1,
        auto_next=True,
    )
    print(path)
    print(f"session_id: {tail['session_id']}")
    print(f"source_session_path: {tail['source_session_path']}")
    print(f"from_turn: {tail['from_turn']}")
    print(f"to_turn: {tail['to_turn']}")
    print(f"user_turn_count: {tail['user_turn_count']}")
    print("called_model: false")
    print("called_worker: false")
    return 0


def strict_worker_envelope_required_for_phase(phase: str) -> bool:
    return phase in AI_WORKER_PHASES


def strict_worker_envelope_required(task: Task) -> bool:
    fields = parse_key_value_prompt(task.prompt)
    if "strict_worker_envelope" in fields:
        return parse_bool_field(fields, "strict_worker_envelope", False)
    return strict_worker_envelope_required_for_phase(task.phase)


def worker_prompt_with_default_envelope(task: Task) -> str:
    fields = parse_key_value_prompt(task.prompt)
    if "strict_worker_envelope" in fields or not strict_worker_envelope_required_for_phase(task.phase):
        return task.prompt
    return f"strict_worker_envelope: true\n{task.prompt}".strip()


def worker_evidence_and_edit_contract(task: Task) -> str:
    if not strict_worker_envelope_required_for_phase(task.phase):
        return ""
    paths = [path for path in task.allowed_paths if str(path).strip()]
    path_lines = "\n".join(f"- bounded read of {path}" for path in paths) or "- bounded read of task-named files only"
    command_lines = []
    for path in paths[:4]:
        command_lines.append(f"- `rg -n \"<symbol-or-term>\" {path} | head -n 40`")
        command_lines.append(f"- `sed -n '<start>,<end>p' {path}` after an rg anchor; keep windows narrow")
    if not command_lines:
        command_lines.append("- `rg -n \"<symbol-or-term>\" <task-file> | head -n 40`")
        command_lines.append("- `sed -n '<start>,<end>p' <task-file>` after an rg anchor; keep windows narrow")
    commands = "\n".join(command_lines[:8])
    return f"""Evidence-and-edit contract:
- Before any reads, state a bounded evidence plan with exact paths, exact rg/sed commands, and the reason for each read.
- Read only these task-scoped paths unless the monitor supplies new explicit evidence:
{path_lines}
- Preferred bounded read commands:
{commands}
- Use `rg -n "<symbol-or-term>" ... | head -n 40` before every `sed` source read.
- Keep each `sed -n '<start>,<end>p'` source window <= 120 lines.
- If multiple `sed` windows are needed, keep the total requested source lines <= 180 and state why.
- Do not start with broad file slices such as `sed -n '1,260p'`, `sed -n '1,400p'`, or multi-window reads over the total limit.
- Do not chain multiple broad reads in one shell command.
- direct_file_change_policy: repair
- Do not edit files directly. Put SEARCH/REPLACE blocks in the final answer for deterministic A9 apply.
"""


DECIDED_STATUS_VALUES = {"decided", "decision", "done", "true", "yes"}
NOT_DECIDED_STATUS_VALUES = {"", "not_decided", "not-decided", "undecided", "draft", "partial", "partial_decision"}
EXECUTION_DECISION_REQUIRED_FIELDS = (
    "decision_status",
    "problem",
    "system_requirement",
    "data_contract",
    "state_flow",
    "exception_flow",
    "acceptance",
    "out_of_scope",
    "allowed_execution",
    "change_record",
    "role_signoff",
)


def decision_required_fields_for_task(task: Task, fields: dict[str, str] | None = None) -> tuple[str, ...]:
    fields = fields or {}
    if task.phase in {"test", "repair"} and "decision_status" in fields:
        return ("decision_status",)
    return EXECUTION_DECISION_REQUIRED_FIELDS


def task_decision_packet(task: Task) -> dict[str, Any]:
    fields = parse_leading_key_value_prompt(task.prompt)
    decision_status = str(fields.get("decision_status", "")).strip().lower()
    if not decision_status and task.phase in {"implement", "test", "repair"} and task.allowed_paths and task.checks:
        return {
            "route": "execution_next",
            "recommendation": "execute_bounded_task_metadata",
            "decision_status": "decided",
            "decided": True,
            "missing_fields": [],
            "required_fields": ["bounded_task_metadata"],
            "decision_source": "task_metadata.allowed_paths_and_checks",
        }
    required_fields = decision_required_fields_for_task(task, fields)
    missing = [name for name in required_fields if not str(fields.get(name, "")).strip()]
    decided = decision_status in DECIDED_STATUS_VALUES and not missing
    if decided:
        route = "execution_next"
        recommendation = "execute_decided_slice"
    else:
        route = "debate_next"
        recommendation = "produce_analysis_or_change_request_before_execution"
    return {
        "route": route,
        "recommendation": recommendation,
        "decision_status": decision_status or "missing",
        "decided": decided,
        "missing_fields": missing,
        "required_fields": list(required_fields),
    }


def decision_packet_template() -> str:
    return """Decision packet task-shaping template:
- decision_status: decided | not_decided | partial_decision.
- problem: the real problem being solved, not proposed implementation steps.
- system_requirement: mandatory system behavior and constraints.
- data_contract: objects, fields, invariants, ownership, and event/state meaning.
- state_flow: normal transitions and authoritative order of states.
- exception_flow: failure, repair, timeout, manual intervention, audit, and rollback behavior.
- acceptance: required evidence, tests, run outputs, and pass/fail rules.
- out_of_scope: explicit exclusions and rationale.
- allowed_execution: files, commands, checks, and boundaries for this slice.
- change_record: what changed in direction, scope, or authority with justification.
- role_signoff: required business/product/architecture/test confirmations.
"""


def task_decision_packet_prompt(task: Task) -> str:
    packet = task_decision_packet(task)
    missing = ", ".join(packet["missing_fields"]) if packet["missing_fields"] else "none"
    required = ", ".join(packet["required_fields"]) if packet["required_fields"] else "none"
    return f"""Task decision packet:
- route: {packet['route']}
- decision_status: {packet['decision_status']}
- decided: {str(packet['decided']).lower()}
- missing_fields: {missing}
- required_fields: {required}
- recommendation: {packet['recommendation']}
- rule: if route is debate_next, do analysis/research/modeling/review output and change_request; do not implement production changes.
{decision_packet_template()}
"""


def explicit_task_decision_packet(task: Task) -> dict[str, Any] | None:
    fields = parse_key_value_prompt(task.prompt)
    if "decision_status" not in fields:
        return None
    return task_decision_packet(task)


def task_has_closed_execution_decision(task: Task) -> bool:
    packet = task_decision_packet(task)
    return bool(packet.get("decided")) and packet.get("route") == "execution_next"


def closed_execution_route_exists_from_summary(summary: dict[str, Any] | None) -> bool:
    if not summary:
        return False
    task_path = summary.get("task_path", "")
    if not task_path:
        return False
    try:
        task = parse_task(Path(task_path))
    except OSError:
        return False
    return task_has_closed_execution_decision(task)


def summary_has_explicit_goal_completion(summary: dict[str, Any] | None) -> bool:
    if not summary:
        return False
    goal_state = summary.get("goal_state")
    if not isinstance(goal_state, dict):
        return False
    goal = goal_state.get("goal")
    if not isinstance(goal, dict) or str(goal.get("status", "")).strip() != "complete":
        return False
    audits = goal.get("completion_audit")
    if not isinstance(audits, list):
        return False
    for entry in audits:
        if isinstance(entry, dict) and str(entry.get("audit", "")).strip():
            return True
    return False


def runtime_state_from_summary(
    queued_tasks: int,
    running_tasks: int,
    summary: dict[str, Any] | None = None,
) -> tuple[str, str]:
    if queued_tasks or running_tasks:
        return "active", "tasks_in_queue_or_running"
    if summary_has_explicit_goal_completion(summary):
        return "complete", "goal_completion_evidence_present"
    if closed_execution_route_exists_from_summary(summary):
        return "active", "closed_execution_task_declared"
    return "waiting_for_review_closure", "closed_next_execution_task_missing"


def parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized == "" or normalized.lower() in {"none", "null"}:
        return None
    return int(normalized)


def parse_key_value_prompt(prompt: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in prompt.splitlines():
        match = re.match(r"^\s*(?:[-*]\s*)?([A-Za-z0-9_-]+)\s*[:=]\s*(.+?)\s*$", line)
        if not match:
            continue
        key = match.group(1).strip().lower().replace("-", "_")
        fields[key] = match.group(2).strip().strip('"').strip("'")
    return fields


def parse_leading_key_value_prompt(prompt: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    started = False
    for line in prompt.splitlines():
        stripped = line.strip()
        if not stripped:
            if started:
                break
            continue
        match = re.match(r"^\s*(?:[-*]\s*)?([A-Za-z0-9_-]+)\s*[:=]\s*(.+?)\s*$", line)
        if not match:
            if started:
                break
            continue
        started = True
        key = match.group(1).strip().lower().replace("-", "_")
        fields[key] = match.group(2).strip().strip('"').strip("'")
    return fields


def parse_session_close_reading_spec(prompt: str) -> dict[str, Any]:
    fields = parse_key_value_prompt(prompt)
    extract_path = fields.get("extract_path") or fields.get("path")
    if not extract_path:
        raise ValueError("missing session_close_reading fields: extract_path")
    spec: dict[str, Any] = {
        "extract_path": extract_path,
        "close_reading_doc": fields.get("close_reading_doc", "docs/session.md"),
        "summary_doc": fields.get("summary_doc", "docs/session.md"),
        "source_session_path": fields.get("source_session_path", ""),
        "auto_continue": parse_bool_field(fields, "auto_continue", True),
        "auto_close_reading": parse_bool_field(fields, "auto_close_reading", True),
        "flow_id": fields.get("flow_id", ""),
        "flow_expected_revision": parse_optional_int(fields.get("flow_expected_revision")),
        "flow_expected_last_seq": parse_optional_int(fields.get("flow_expected_last_seq")),
        "flow_sequence": parse_optional_int(fields.get("flow_sequence")),
    }
    for name in ("to_turn", "user_turn_count", "batch_size"):
        if fields.get(name):
            try:
                spec[name] = int(str(fields[name]))
            except ValueError as exc:
                raise ValueError(f"{name} must be an integer") from exc
    return spec


def parse_task_flow_spec(prompt: str) -> dict[str, Any]:
    fields = parse_key_value_prompt(prompt)
    return {
        "flow_id": fields.get("flow_id", ""),
        "flow_expected_revision": parse_optional_int(fields.get("flow_expected_revision")),
        "flow_expected_last_seq": parse_optional_int(fields.get("flow_expected_last_seq")),
        "flow_sequence": parse_optional_int(fields.get("flow_sequence")),
    }


GOAL_STATUSES = {"active", "paused", "blocked", "usage_limited", "budget_limited", "complete"}


def parse_task_goal_spec(prompt: str) -> dict[str, Any]:
    fields = parse_key_value_prompt(prompt)
    status = str(fields.get("goal_status") or "").strip().lower()
    if status and status not in GOAL_STATUSES:
        status = ""
    return {
        "goal_id": fields.get("goal_id", ""),
        "goal_objective": fields.get("goal_objective", ""),
        "goal_status": status,
        "goal_token_budget": parse_optional_int(fields.get("goal_token_budget")),
        "goal_completion_audit": fields.get("goal_completion_audit", ""),
        "goal_blocked_reason": fields.get("goal_blocked_reason", ""),
    }


def goal_id_for_objective(objective: str) -> str:
    digest = hashlib.sha256(objective.encode("utf-8")).hexdigest()[:10]
    return f"goal-{slugify(objective)[:48]}-{digest}"


def goal_path(goal_id: str) -> Path:
    return GOALS_DIR / f"{slugify(goal_id)}.json"


def load_goal(goal_id: str) -> dict[str, Any]:
    return read_json_file(goal_path(goal_id))


def write_goal(goal: dict[str, Any]) -> None:
    ensure_dirs()
    goal["updated_at"] = utc_now()
    write_json(goal_path(str(goal["goal_id"])), goal)


def plan_id_for_problem(problem: str) -> str:
    digest = hashlib.sha256(problem.encode("utf-8")).hexdigest()[:10]
    return f"plan-{slugify(problem)[:48]}-{digest}"


def plan_path(plan_id: str) -> Path:
    return PLANS_DIR / slugify(plan_id)


def active_plan_id() -> str:
    try:
        plan_id = ACTIVE_PLAN_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not plan_id:
        return ""
    if not plan_path(plan_id).exists() or not (plan_path(plan_id) / "plan.json").exists():
        return ""
    return plan_id


def load_plan(plan_id: str) -> dict[str, Any]:
    if not plan_id:
        return {}
    return read_json_file(plan_path(plan_id) / "plan.json")


def active_plan() -> dict[str, Any]:
    return load_plan(active_plan_id())


REQUIREMENTS_DEBATE_STAGES: tuple[dict[str, Any], ...] = (
    {
        "stage_id": "requirement_audit",
        "label": "Demand audit and true problem framing",
        "required_contract_fields": ("problem", "why_now", "out_of_scope"),
        "prompt": (
            "Audit the requirement source. Distinguish the real problem from proposed implementation, "
            "name why this is the current mainline, and name stale or out-of-scope branches."
        ),
    },
    {
        "stage_id": "preparation_reference_scan",
        "label": "Preparation and reference scan",
        "required_contract_fields": ("reference_entry",),
        "prompt": (
            "Prepare for requirements debate: inspect current system evidence and local reference projects, "
            "then list mechanisms worth copying, rejected mechanisms, source paths, and open questions."
        ),
    },
    {
        "stage_id": "system_requirement_translation",
        "label": "Translate user demand into system requirement",
        "required_contract_fields": ("must", "system_requirement"),
        "prompt": (
            "Translate the user/product demand into system requirements. Separate must/should/could, "
            "scope, system behavior, and risks. Do not implement."
        ),
    },
    {
        "stage_id": "data_state_model",
        "label": "Data model, state flow, exception flow",
        "required_contract_fields": ("data_shape", "normal_flow", "exception_flow"),
        "prompt": (
            "Model the business/system objects, fields, authoritative states, normal transitions, "
            "exception transitions, audit facts, and recovery behavior."
        ),
    },
    {
        "stage_id": "acceptance_and_backlog",
        "label": "Acceptance and execution backlog shaping",
        "required_contract_fields": ("acceptance", "allowed_execution"),
        "prompt": (
            "Turn the reviewed requirement into verifiable acceptance and a bounded execution backlog. "
            "Generate candidate execution_next slices, allowed files, commands, tests, and repair conditions."
        ),
    },
)


def default_requirements_debate_state() -> dict[str, Any]:
    return {
        "schema": "a9.requirements_debate_state.v1",
        "status": "debating",
        "current_stage": REQUIREMENTS_DEBATE_STAGES[0]["stage_id"],
        "stages": [
            {
                "stage_id": str(stage["stage_id"]),
                "label": str(stage["label"]),
                "status": "pending",
                "required_contract_fields": list(stage["required_contract_fields"]),
            }
            for stage in REQUIREMENTS_DEBATE_STAGES
        ],
        "generated_execution_next_count": 0,
    }


def default_execution_backlog_state() -> dict[str, Any]:
    return {
        "schema": "a9.execution_backlog.v1",
        "items": [],
        "generated_task_ids": [],
    }


def requirements_debate_progress(plan: dict[str, Any]) -> dict[str, Any]:
    contract = plan.get("contract", {}) if isinstance(plan.get("contract"), dict) else {}
    stages: list[dict[str, Any]] = []
    current_stage = ""
    missing_total: list[str] = []
    for spec in REQUIREMENTS_DEBATE_STAGES:
        required = [str(item) for item in spec["required_contract_fields"]]
        missing = [field for field in required if not str(contract.get(field) or "").strip()]
        if missing and not current_stage:
            current_stage = str(spec["stage_id"])
        missing_total.extend(missing)
        stages.append(
            {
                "stage_id": str(spec["stage_id"]),
                "label": str(spec["label"]),
                "status": "done" if not missing else "open",
                "missing_fields": missing,
                "required_contract_fields": required,
            }
        )
    return {
        "schema": "a9.requirements_debate_progress.v1",
        "status": "ready_for_execution_backlog" if not missing_total else "debating",
        "current_stage": current_stage or "execution_backlog_generation",
        "missing_fields": missing_total,
        "stages": stages,
    }


def requirements_debate_stage_spec(stage_id: str) -> dict[str, Any]:
    for stage in REQUIREMENTS_DEBATE_STAGES:
        if stage["stage_id"] == stage_id:
            return stage
    return REQUIREMENTS_DEBATE_STAGES[-1]


def parse_active_plan_from_prompt(prompt: str) -> dict[str, Any]:
    if not prompt:
        return {}
    lines = prompt.splitlines()
    start = -1
    for idx, line in enumerate(lines):
        if line.strip() == "Active plan contract:":
            start = idx + 1
            break
    if start < 0:
        return {}
    allowed = {
        "plan_id",
        "goal_id",
        "flow_id",
        "expected_flow_revision",
        "problem",
        "why_now",
        "must",
        "should",
        "could",
        "system_requirement",
        "data_shape",
        "normal_flow",
        "exception_flow",
        "acceptance",
        "out_of_scope",
        "allowed_execution",
        "reference_entry",
        "change_record",
    }
    values: dict[str, str] = {}
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("- "):
            break
        key, sep, value = stripped[2:].partition(":")
        if not sep:
            continue
        field = key.strip()
        if field not in allowed:
            continue
        values[field] = value.strip()
    plan_id = values.get("plan_id", "").strip()
    goal_id = values.get("goal_id", "").strip()
    if not plan_id or not goal_id:
        return {}
    contract = {
        key: values.get(key, "")
        for key in (
            "problem",
            "why_now",
            "must",
            "should",
            "could",
            "system_requirement",
            "data_shape",
            "normal_flow",
            "exception_flow",
            "acceptance",
            "out_of_scope",
            "allowed_execution",
            "reference_entry",
            "change_record",
        )
    }
    expected_raw = values.get("expected_flow_revision", "")
    expected_flow_revision: int | None
    try:
        expected_flow_revision = int(expected_raw) if expected_raw else None
    except ValueError:
        expected_flow_revision = None
    return create_plan_payload(
        plan_id=plan_id,
        goal_id=goal_id,
        flow_id=values.get("flow_id", ""),
        expected_flow_revision=expected_flow_revision,
        source="a9_supervisor_prompt_recovery",
        contract=contract,
    )


def write_plan_markdown(plan: dict[str, Any]) -> str:
    contract = plan.get("contract", {}) if isinstance(plan.get("contract"), dict) else {}
    lines = [
        f"# {plan.get('plan_id', '')}",
        "",
        "## Runtime Refs",
        "",
        f"- goal_id: {plan.get('goal_id', '')}",
        f"- flow_id: {plan.get('flow_id', '')}",
        f"- expected_flow_revision: {plan.get('expected_flow_revision', '')}",
        f"- run_ids: {', '.join(plan.get('run_ids', [])) if isinstance(plan.get('run_ids'), list) else ''}",
        f"- evidence_refs: {', '.join(plan.get('evidence_refs', [])) if isinstance(plan.get('evidence_refs'), list) else ''}",
        "",
        "## Contract",
        "",
    ]
    for key in [
        "problem",
        "why_now",
        "must",
        "should",
        "could",
        "system_requirement",
        "solution_type",
        "data_shape",
        "normal_flow",
        "exception_flow",
        "acceptance",
        "out_of_scope",
        "reference_entry",
        "change_record",
        "allowed_execution",
    ]:
        lines.extend([f"### {key}", "", str(contract.get(key) or "").strip() or "TBD", ""])
    debate = requirements_debate_progress(plan)
    lines.extend(["## Requirements Debate", ""])
    lines.extend(
        [
            f"- status: {debate.get('status', '')}",
            f"- current_stage: {debate.get('current_stage', '')}",
            f"- missing_fields: {', '.join(debate.get('missing_fields', [])) if isinstance(debate.get('missing_fields'), list) else ''}",
            "",
        ]
    )
    for stage in debate.get("stages", []):
        if not isinstance(stage, dict):
            continue
        missing = stage.get("missing_fields", [])
        lines.append(
            f"- {stage.get('stage_id', '')}: {stage.get('status', '')}"
            + (f" missing={', '.join(str(item) for item in missing)}" if missing else "")
        )
    lines.append("")
    backlog = execution_backlog_state(plan)
    backlog_items = [item for item in backlog.get("items", []) if isinstance(item, dict)]
    lines.extend(["## Execution Backlog", ""])
    lines.append(f"- items: {len(backlog_items)}")
    generated = backlog.get("generated_task_ids", [])
    lines.append(
        f"- generated_task_ids: {', '.join(str(item) for item in generated) if isinstance(generated, list) else ''}"
    )
    lines.append("")
    for index, item in enumerate(backlog_items, start=1):
        lines.append(
            f"- {index}. {item.get('id', '')}: {item.get('status', '')} "
            f"phase={item.get('phase', '')} title={item.get('title', '')}"
        )
    lines.append("")
    lines.extend(
        [
            "## Authority",
            "",
            "- This plan is a task contract and prompt hydration view.",
            "- Goal completion, flow transition, approval/resume, git acceptance, and completion audit remain runtime authority.",
            "- Workers may append findings/progress/mistakes and must use change_request for contract changes.",
            "",
        ]
    )
    return "\n".join(lines)


def create_plan_payload(
    *,
    plan_id: str,
    goal_id: str,
    flow_id: str = "",
    expected_flow_revision: int | None = None,
    source: str = "a9_supervisor_plan_create",
    contract: dict[str, str],
) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema": "a9.plan.v1",
        "plan_id": plan_id,
        "goal_id": goal_id,
        "flow_id": flow_id,
        "expected_flow_revision": expected_flow_revision,
        "run_ids": [],
        "evidence_refs": [],
        "completion_audit_ref": "",
        "source": source,
        "status": "active",
        "contract": contract,
        "requirements_debate": default_requirements_debate_state(),
        "execution_backlog": default_execution_backlog_state(),
        "created_at": now,
        "updated_at": now,
    }


def write_plan_files(plan: dict[str, Any], *, activate: bool = True) -> Path:
    ensure_dirs()
    plan_dir = plan_path(str(plan["plan_id"]))
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan["updated_at"] = utc_now()
    write_json(plan_dir / "plan.json", plan)
    (plan_dir / "plan.md").write_text(write_plan_markdown(plan), encoding="utf-8")
    for name, heading in [
        ("findings.md", "Findings"),
        ("progress.md", "Progress"),
        ("mistakes.md", "Mistakes"),
        ("change_request.md", "Change Request"),
    ]:
        path = plan_dir / name
        if not path.exists():
            path.write_text(f"# {heading}\n\n", encoding="utf-8")
    if activate:
        ACTIVE_PLAN_PATH.write_text(str(plan["plan_id"]) + "\n", encoding="utf-8")
    return plan_dir


def active_plan_prompt_context() -> str:
    plan = active_plan()
    if not plan:
        return ""
    budget_tokens_raw = os.getenv("A9_ACTIVE_PLAN_PROMPT_TOKEN_BUDGET", "1200")
    try:
        budget_tokens = max(256, int(budget_tokens_raw))
    except ValueError:
        budget_tokens = 1200
    contract = plan.get("contract", {}) if isinstance(plan.get("contract"), dict) else {}
    run_ids = plan.get("run_ids", []) if isinstance(plan.get("run_ids"), list) else []
    evidence_refs = plan.get("evidence_refs", []) if isinstance(plan.get("evidence_refs"), list) else []
    plan_dir = plan_path(str(plan.get("plan_id", "")))
    recovery_tail = {
        "last_progress": tail_recovery_line(plan_dir / "progress.md"),
        "last_findings": tail_recovery_line(plan_dir / "findings.md"),
        "last_mistake": tail_recovery_line(plan_dir / "mistakes.md"),
        "last_change_request": tail_change_request_line(plan_dir / "change_request.md"),
    }
    latest_run = plan_latest_run_snapshot(plan)
    required_lines = [
        "Active plan contract:",
        f"- plan_id: {plan.get('plan_id', '')}",
        f"- goal_id: {plan.get('goal_id', '')}",
        f"- flow_id: {plan.get('flow_id', '')}",
        f"- expected_flow_revision: {plan.get('expected_flow_revision', '')}",
        f"- run_ids: {bounded_inline(', '.join(str(item) for item in run_ids), 500)}",
        f"- evidence_refs: {bounded_inline(', '.join(str(item) for item in evidence_refs), 700)}",
        f"- problem: {bounded_inline(contract.get('problem', ''), 500)}",
        f"- why_now: {bounded_inline(contract.get('why_now', ''), 500)}",
        f"- must: {bounded_inline(contract.get('must', ''), 500)}",
        f"- should: {bounded_inline(contract.get('should', ''), 500)}",
        f"- could: {bounded_inline(contract.get('could', ''), 500)}",
        f"- system_requirement: {bounded_inline(contract.get('system_requirement', ''), 700)}",
        f"- data_shape: {bounded_inline(contract.get('data_shape', ''), 500)}",
        f"- normal_flow: {bounded_inline(contract.get('normal_flow', ''), 500)}",
        f"- exception_flow: {bounded_inline(contract.get('exception_flow', ''), 500)}",
        f"- acceptance: {bounded_inline(contract.get('acceptance', ''), 600)}",
        f"- out_of_scope: {bounded_inline(contract.get('out_of_scope', ''), 500)}",
        f"- allowed_execution: {bounded_inline(contract.get('allowed_execution', ''), 500)}",
        "- write_scope_authority: task frontmatter allowed_paths is the only write-scope authority.",
        f"- reference_entry: {bounded_inline(contract.get('reference_entry', ''), 500)}",
        f"- change_record: {bounded_inline(contract.get('change_record', ''), 500)}",
        "- authority: plan is a task contract view; goal/flow/run/monitor remain runtime authority.",
    ]
    optional_lines = [
        f"- last_progress: {recovery_tail['last_progress']}",
        f"- last_findings: {recovery_tail['last_findings']}",
        f"- last_mistake: {recovery_tail['last_mistake']}",
        f"- last_change_request: {recovery_tail['last_change_request']}",
        f"- latest_run_summary: {bounded_inline(latest_run.get('summary_path', ''), 500)}",
        f"- latest_run_status: {bounded_inline(latest_run.get('status', ''), 200)}",
        f"- latest_run_phase: {bounded_inline(latest_run.get('phase', ''), 200)}",
        f"- latest_run_next_slice: {bounded_inline(latest_run.get('next_slice', ''), 500)}",
    ]
    selected = list(required_lines)
    for line in optional_lines:
        candidate = "\n".join(selected + [line]) + "\n"
        if approx_token_count(candidate) <= budget_tokens:
            selected.append(line)
        else:
            break
    return "\n".join(selected) + "\n"


def tail_recovery_line(path: Path, *, max_chars: int = 260) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for raw in reversed(lines):
        text = str(raw or "").strip()
        if not text:
            continue
        if text.startswith("#"):
            continue
        return bounded_inline(text, max_chars)
    return ""


def tail_change_request_line(path: Path, *, max_chars: int = 260) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for raw in reversed(lines):
        text = str(raw or "").strip()
        if text.startswith("- proposal:"):
            return bounded_inline(text, max_chars)
    return tail_recovery_line(path, max_chars=max_chars)


def latest_plan_change_request(plan: dict[str, Any], *, max_chars: int = 500) -> str:
    plan_id = str(plan.get("plan_id") or "").strip() if plan else ""
    if not plan_id:
        return ""
    path = plan_path(plan_id) / "change_request.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    blocks = re.split(r"(?m)^##\s+", text)
    for block in reversed(blocks):
        lines = [str(line or "").strip() for line in block.splitlines()]
        if not any(line.startswith("- proposal:") for line in lines):
            continue
        status_line = next((line for line in lines if line.startswith("- status:")), "")
        status = status_line.split(":", 1)[1].strip().lower() if ":" in status_line else "proposed"
        if status in {"applied", "approved", "satisfied", "done", "closed", "cancelled", "rejected"}:
            continue
        proposal = next((line for line in lines if line.startswith("- proposal:")), "")
        return bounded_inline(proposal, max_chars)
    return ""


def tail_progress_lane_line(
    plan: dict[str, Any],
    *,
    actor: str | None = None,
    max_chars: int = 260,
) -> str:
    plan_id = str(plan.get("plan_id") or "").strip() if plan else ""
    if not plan_id:
        return ""
    path = plan_path(plan_id) / "progress.md"
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
        return bounded_inline(text, max_chars)
    return ""


def plan_progress_snapshot(plan: dict[str, Any], *, max_chars: int = 260) -> dict[str, Any]:
    latest_progress = tail_progress_lane_line(plan, max_chars=max_chars)
    latest_monitor_progress = tail_progress_lane_line(plan, actor="monitor", max_chars=max_chars)
    return {
        "latest_progress": latest_progress,
        "latest_monitor_progress": latest_monitor_progress,
        "has_monitor_progress": bool(latest_monitor_progress),
    }


def is_selftest_run_id(value: Any) -> bool:
    return Path(str(value or "").strip()).name.startswith("selftest-")


def latest_plan_run_id(plan: dict[str, Any]) -> str:
    run_ids = plan.get("run_ids", []) if isinstance(plan.get("run_ids"), list) else []
    for value in reversed(run_ids):
        text = str(value or "").strip()
        if text and not is_selftest_run_id(text):
            return text
    return ""


def latest_plan_evidence_ref(plan: dict[str, Any]) -> str:
    evidence_refs = plan.get("evidence_refs", []) if isinstance(plan.get("evidence_refs"), list) else []
    for value in reversed(evidence_refs):
        text = str(value or "").strip()
        if text and not any(part.startswith("selftest-") for part in Path(text).parts):
            return text
    return ""


def plan_latest_run_snapshot(plan: dict[str, Any]) -> dict[str, str]:
    evidence_refs = plan.get("evidence_refs", []) if isinstance(plan.get("evidence_refs"), list) else []
    summary_path = ""
    for value in reversed(evidence_refs):
        text = str(value or "").strip()
        if any(part.startswith("selftest-") for part in Path(text).parts):
            continue
        if text.endswith("/summary.json"):
            summary_path = text
            break
    if not summary_path:
        run_id = latest_plan_run_id(plan)
        if run_id:
            candidate = RUNS_DIR / run_id / "summary.json"
            if candidate.exists():
                summary_path = str(candidate)
    if not summary_path:
        return {"summary_path": "", "phase": "", "status": ""}
    data = read_json_file(Path(summary_path))
    if not data:
        return {"summary_path": summary_path, "phase": "", "status": ""}
    return {
        "summary_path": summary_path,
        "phase": str(data.get("phase") or ""),
        "status": str(data.get("status") or ""),
    }


def append_plan_progress(plan_dir: Path, line: str) -> None:
    path = plan_dir / "progress.md"
    if not path.exists():
        path.write_text("# Progress\n\n", encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    if line in text:
        return
    with path.open("a", encoding="utf-8") as handle:
        if text and not text.endswith("\n"):
            handle.write("\n")
        handle.write(line + "\n")


def append_plan_note(
    *,
    plan_id: str,
    note_type: str,
    note: str,
    actor: str = "worker",
    evidence_refs: list[str] | None = None,
) -> dict[str, str]:
    plan = load_plan(plan_id)
    if not plan:
        return {"status": "missing", "plan_id": plan_id, "path": ""}
    note_map = {
        "findings": ("findings.md", "Findings"),
        "progress": ("progress.md", "Progress"),
        "mistakes": ("mistakes.md", "Mistakes"),
    }
    target = note_map.get(note_type)
    if not target:
        return {"status": "invalid_type", "plan_id": plan_id, "path": ""}
    file_name, heading = target
    path = plan_path(plan_id) / file_name
    if not path.exists():
        path.write_text(f"# {heading}\n\n", encoding="utf-8")
    refs = [str(item).strip() for item in (evidence_refs or []) if str(item).strip()]
    line = f"- {utc_now()} actor={actor} note={note.strip()}"
    if refs:
        line += f" evidence_refs={', '.join(refs)}"
    text = path.read_text(encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        if text and not text.endswith("\n"):
            handle.write("\n")
        handle.write(line + "\n")
    return {"status": "appended", "plan_id": plan_id, "path": str(path), "type": note_type}


def append_plan_change_request(
    *,
    plan_id: str,
    field: str,
    proposal: str,
    reason: str,
    actor: str = "worker",
    evidence_refs: list[str] | None = None,
) -> dict[str, str]:
    plan = load_plan(plan_id)
    if not plan:
        return {"status": "missing", "plan_id": plan_id, "path": ""}
    plan_dir = plan_path(plan_id)
    path = plan_dir / "change_request.md"
    if not path.exists():
        path.write_text("# Change Request\n\n", encoding="utf-8")
    request_id = f"cr-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{hashlib.sha256((field + proposal + reason).encode('utf-8')).hexdigest()[:8]}"
    refs = evidence_refs or []
    lines = [
        f"## {request_id}",
        "",
        f"- status: proposed",
        f"- created_at: {utc_now()}",
        f"- actor: {actor}",
        f"- field: {field}",
        f"- reason: {reason}",
        f"- proposal: {proposal}",
    ]
    if refs:
        lines.append(f"- evidence_refs: {', '.join(refs)}")
    lines.append("")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return {"status": "appended", "plan_id": plan_id, "request_id": request_id, "path": str(path)}


def approve_plan_decision_backlog(
    *,
    plan_id: str,
    reason: str,
    actor: str = "monitor",
    source_run: str = "",
    item_ids: list[str] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    plan = load_plan(plan_id)
    if not plan:
        return {"status": "missing_plan", "plan_id": plan_id, "approved_count": 0}
    reason_text = str(reason or "").strip()
    if not reason_text:
        return {"status": "invalid_request", "plan_id": plan_id, "reason": "approval_reason_required", "approved_count": 0}
    source_filter = str(source_run or "").strip()
    id_filter = {str(item).strip() for item in (item_ids or []) if str(item).strip()}
    backlog = execution_backlog_state(plan)
    items = backlog.get("items")
    if not isinstance(items, list):
        items = []
        backlog["items"] = items
    approved: list[dict[str, Any]] = []
    approved_at = utc_now()
    actor_text = str(actor or "monitor").strip() or "monitor"
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") != "blocked_not_decided":
            continue
        item_id = str(item.get("id") or "").strip()
        if id_filter and item_id not in id_filter:
            continue
        item_source = str(item.get("source_run") or "")
        if source_filter and source_filter not in {item_source, Path(item_source).name}:
            continue
        item["status"] = "ready"
        item["decision_status"] = "decided"
        item["approved_at"] = approved_at
        item["approved_by"] = actor_text
        item["approval_reason"] = reason_text
        item["approval_source"] = "monitor_explicit_decision"
        item.pop("blocked_reason", None)
        item.pop("blocked_at", None)
        item.pop("queued_task_id", None)
        item.pop("queued_task_path", None)
        item.pop("queued_at", None)
        approved.append({"id": item.get("id"), "title": item.get("title"), "source_run": item_source})
    if not approved:
        return {"status": "no_items", "plan_id": plan_id, "approved_count": 0, "source_run": source_filter, "item_ids": sorted(id_filter)}
    plan["updated_at"] = approved_at
    plan_dir = write_plan_files(plan)
    refs = [str(item).strip() for item in (evidence_refs or []) if str(item).strip()]
    approval_path = plan_dir / "decision_approval.md"
    if not approval_path.exists():
        approval_path.write_text("# Decision Approval\n\n", encoding="utf-8")
    with approval_path.open("a", encoding="utf-8") as handle:
        handle.write(f"## approval-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{len(approved)}\n\n")
        handle.write(f"- status: approved\n- approved_at: {approved_at}\n- actor: {actor_text}\n")
        handle.write(f"- reason: {reason_text}\n")
        if source_filter:
            handle.write(f"- source_run: {source_filter}\n")
        if id_filter:
            handle.write(f"- item_ids: {', '.join(sorted(id_filter))}\n")
        if refs:
            handle.write(f"- evidence_refs: {', '.join(refs)}\n")
        handle.write(f"- approved_count: {len(approved)}\n")
        for item in approved:
            handle.write(f"  - {item.get('id')}: {item.get('title')}\n")
        handle.write("\n")
    append_plan_progress(plan_dir, f"decision_approval: approved {len(approved)} blocked_not_decided backlog item(s) actor={actor_text} reason={reason_text}")
    return {
        "status": "approved",
        "plan_id": plan_id,
        "approved_count": len(approved),
        "approved_items": approved,
        "path": str(plan_dir / "plan.json"),
        "approval_path": str(approval_path),
        "source_run": source_filter,
        "item_ids": sorted(id_filter),
    }


def extract_contract_change_requests_from_summary(summary: dict[str, Any]) -> list[dict[str, str]]:
    worker = worker_output_from_summary(summary)
    raw: Any = None
    for key in ("contract_change_request", "contract_change_requests", "contract_update", "contract_updates"):
        value = worker.get(key)
        if value:
            raw = value
            break
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    requests: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or item.get("contract_field") or "").strip()
        proposal = str(item.get("proposal") or item.get("value") or item.get("proposed_value") or "").strip()
        reason = str(item.get("reason") or item.get("why") or "").strip()
        if not field or not proposal:
            continue
        requests.append(
            {
                "field": field,
                "proposal": proposal,
                "reason": reason or "worker proposed contract change during run",
            }
        )
    return requests


def update_execution_backlog_item_from_run(plan: dict[str, Any], task: Task, run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    backlog = execution_backlog_state(plan)
    items = backlog.get("items")
    if not isinstance(items, list):
        return {"status": "skipped", "reason": "no_execution_backlog_items"}
    task_id = str(task.task_id or "").strip()
    if not task_id:
        return {"status": "skipped", "reason": "missing_task_id"}
    task_fields = parse_key_value_prompt(task.prompt)
    parent_task_id = str(task_fields.get("parent_task_id") or "").strip()
    matched: dict[str, Any] | None = None
    match_kind = "task"
    for item in items:
        if not isinstance(item, dict):
            continue
        if task_id in {
            str(item.get("queued_task_id") or "").strip(),
            str(item.get("task_id") or "").strip(),
        }:
            matched = item
            break
    if matched is None and parent_task_id:
        match_kind = "parent_task"
        for item in items:
            if not isinstance(item, dict):
                continue
            if parent_task_id in {
                str(item.get("queued_task_id") or "").strip(),
                str(item.get("task_id") or "").strip(),
            }:
                matched = item
                break
    if matched is None:
        return {
            "status": "skipped",
            "reason": "task_not_in_execution_backlog",
            "task_id": task_id,
            "parent_task_id": parent_task_id,
        }

    run_status = str(summary.get("status") or "").strip()
    known_terminal_statuses = {"pass", "needs-followup", "needs-repair", "monitor-blocked", "worker-failed", "failed", "timeout"}
    if run_status not in known_terminal_statuses and not run_status.startswith("retryable-"):
        return {"status": "skipped", "reason": "non_terminal_or_unknown_status", "task_id": task_id, "run_status": run_status}
    now = utc_now()
    git_governance = summary.get("git_governance") if isinstance(summary.get("git_governance"), dict) else {}
    main_integration = git_governance.get("main_integration") if isinstance(git_governance.get("main_integration"), dict) else {}
    item_status = run_status
    if match_kind == "parent_task" and run_status in {"pass", "needs-followup"}:
        item_status = "pass"
        matched["repaired_by_task_id"] = task_id
        matched["repair_status"] = run_status
    matched["status"] = item_status
    matched["last_run_id"] = Path(str(summary.get("run_dir") or run_dir)).name
    matched["last_run_dir"] = str(run_dir)
    matched["last_summary_path"] = str(run_dir / "summary.json")
    matched["last_updated_at"] = now
    if item_status in {"pass", "needs-followup"}:
        matched["completed_at"] = now
        matched.pop("failed_at", None)
    else:
        matched["failed_at"] = now
    commit = str(main_integration.get("main_commit") or git_governance.get("commit") or "").strip()
    if commit:
        matched["last_commit"] = commit
    return {
        "status": "updated",
        "task_id": task_id,
        "parent_task_id": parent_task_id,
        "item_id": str(matched.get("id") or matched.get("backlog_id") or ""),
        "match_kind": match_kind,
        "run_status": run_status,
        "item_status": item_status,
    }


def update_active_plan_from_run(task: Task, run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    run_id = Path(str(summary.get("run_dir") or run_dir)).name
    if str(task.task_id or "").startswith("selftest-") or is_selftest_run_id(run_id):
        return {"status": "skipped", "reason": "selftest_run_not_plan_memory", "run_id": run_id}
    plan = active_plan()
    if not plan:
        recovered = parse_active_plan_from_prompt(task.prompt)
        if not recovered:
            return {"status": "skipped", "reason": "no_active_plan"}
        write_plan_files(recovered, activate=True)
        plan = recovered
    plan_id = str(plan.get("plan_id") or "")
    if not plan_id:
        return {"status": "skipped", "reason": "active_plan_missing_plan_id"}
    run_ids = plan.setdefault("run_ids", [])
    if isinstance(run_ids, list) and run_id not in run_ids:
        run_ids.append(run_id)
    evidence_refs = plan.setdefault("evidence_refs", [])
    ref_values = [str(run_dir / "summary.json")]
    ref_values.extend(str(summary.get(key) or "") for key in ("evidence_path", "state_path", "deep_marks_path", "context_path"))
    for value in ref_values:
        if isinstance(evidence_refs, list) and value and str(value) not in evidence_refs:
            evidence_refs.append(str(value))
    contract_change_requests = extract_contract_change_requests_from_summary(summary)
    backlog_item_update = update_execution_backlog_item_from_run(plan, task, run_dir, summary)
    backlog_update = append_execution_backlog_items_from_debate_run(plan, task, run_dir, summary)
    plan_dir = write_plan_files(plan, activate=True)
    appended_change_requests: list[dict[str, str]] = []
    for request in contract_change_requests:
        appended = append_plan_change_request(
            plan_id=plan_id,
            field=request["field"],
            proposal=request["proposal"],
            reason=request["reason"],
            actor="worker",
            evidence_refs=[str(run_dir / "summary.json")],
        )
        if appended.get("status") == "appended":
            appended_change_requests.append(appended)
    commit = summary.get("git_governance", {}).get("commit", "") if isinstance(summary.get("git_governance"), dict) else ""
    next_task_path = str(summary.get("next_task_path") or "")
    append_plan_progress(
        plan_dir,
        (
            f"- {utc_now()} run={run_id} task={task.task_id} phase={task.phase} "
            f"status={summary.get('status', '')} commit={str(commit)[:12]} next={next_task_path}"
        ),
    )
    if backlog_update.get("status") == "appended":
        append_plan_progress(
            plan_dir,
            (
                f"- {utc_now()} run={run_id} task={task.task_id} "
                f"execution_backlog_from_debate added={backlog_update.get('added_count', 0)} "
                f"items={', '.join(str(item) for item in backlog_update.get('item_ids', []))}"
            ),
        )
    return {
        "status": "updated",
        "plan_id": plan_id,
        "plan_dir": str(plan_dir),
        "run_id": run_id,
        "evidence_refs": list(evidence_refs) if isinstance(evidence_refs, list) else [],
        "execution_backlog_item_update": backlog_item_update,
        "execution_backlog_update": backlog_update,
        "contract_change_requests": appended_change_requests,
    }


def create_goal_payload(goal_id: str, objective: str, token_budget_value: int | None = None) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema": "a9.goal.v1",
        "goal_id": goal_id,
        "objective": objective,
        "status": "active",
        "token_budget": token_budget_value,
        "tokens_used": 0,
        "total_tokens_observed": 0,
        "token_accounting": {
            "budget_mode": "uncached_input_plus_output_plus_reasoning",
            "last_delta": {},
        },
        "time_used_seconds": 0,
        "blocked_count": 0,
        "completion_audit": [],
        "blocked_audit": [],
        "task_ids": [],
        "run_ids": [],
        "created_at": now,
        "updated_at": now,
        "source": "codex_thread_goal_shape",
    }


def task_goal_context(task: Task) -> dict[str, Any]:
    spec = parse_task_goal_spec(task.prompt)
    goal_id = str(spec.get("goal_id") or "").strip()
    objective = str(spec.get("goal_objective") or "").strip()
    if not goal_id and not objective:
        return {"enabled": False, "status": "none"}
    if not goal_id:
        goal_id = goal_id_for_objective(objective)
    goal = load_goal(goal_id)
    if not goal:
        if not objective:
            return {"enabled": True, "status": "missing", "goal_id": goal_id}
        goal = create_goal_payload(goal_id, objective, spec.get("goal_token_budget"))
    else:
        if objective and objective != goal.get("objective"):
            goal["objective"] = objective
        if spec.get("goal_token_budget") is not None:
            goal["token_budget"] = spec.get("goal_token_budget")
    return {"enabled": True, "status": "loaded", "goal_id": goal_id, "goal": goal, "spec": spec}


def parse_utc_datetime(value: Any) -> datetime | None:
    try:
        text = str(value or "")
        if not text:
            return None
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def run_duration_seconds(summary: dict[str, Any]) -> int:
    started = parse_utc_datetime(summary.get("started_at"))
    finished = parse_utc_datetime(summary.get("finished_at"))
    if not started or not finished:
        return 0
    return max(0, int((finished - started).total_seconds()))


def summary_token_usage(summary: dict[str, Any]) -> int:
    return summary_token_accounting(summary)["effective_tokens"]


def summary_token_accounting(summary: dict[str, Any]) -> dict[str, int | str]:
    worker = summary.get("worker", {}) if isinstance(summary.get("worker"), dict) else {}
    usage = worker.get("actual_token_usage", {}) if isinstance(worker.get("actual_token_usage"), dict) else {}

    def token_int(name: str) -> int:
        value = usage.get(name)
        return max(0, value) if isinstance(value, int) and not isinstance(value, bool) else 0

    input_tokens = token_int("input_tokens")
    cached_input_tokens = token_int("cached_input_tokens")
    uncached_input_tokens = token_int("uncached_input_tokens")
    output_tokens = token_int("output_tokens")
    reasoning_output_tokens = token_int("reasoning_output_tokens")
    total_tokens = token_int("total_tokens")

    if not uncached_input_tokens and input_tokens:
        uncached_input_tokens = max(0, input_tokens - cached_input_tokens)
    if not total_tokens:
        total_tokens = input_tokens + output_tokens + reasoning_output_tokens

    has_detailed_usage = any((input_tokens, cached_input_tokens, uncached_input_tokens, output_tokens, reasoning_output_tokens))
    if has_detailed_usage:
        effective_tokens = uncached_input_tokens + output_tokens + reasoning_output_tokens
        mode = "uncached_input_plus_output_plus_reasoning"
    else:
        effective_tokens = total_tokens
        mode = "legacy_total_tokens"

    return {
        "budget_mode": mode,
        "effective_tokens": max(0, effective_tokens),
        "total_tokens": max(0, total_tokens),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": uncached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
    }


def update_goal_from_summary(task: Task, run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    context = task_goal_context(task)
    output_path = run_dir / "goal_state.json"
    if not context.get("enabled"):
        result = {"enabled": False, "status": "skipped", "output_path": str(output_path)}
        write_json(output_path, result)
        return result
    if context.get("status") == "missing":
        result = {
            "enabled": True,
            "status": "missing",
            "goal_id": context.get("goal_id"),
            "output_path": str(output_path),
            "reason": "goal_id specified but no goal exists and no goal_objective was provided",
        }
        write_json(output_path, result)
        return result

    goal = dict(context["goal"])
    spec = context.get("spec", {})
    status = str(summary.get("status") or "")
    run_id = Path(str(summary.get("run_dir") or run_dir)).name
    token_accounting = summary_token_accounting(summary)
    token_delta = int(token_accounting["effective_tokens"])
    total_token_delta = int(token_accounting["total_tokens"])
    time_delta = run_duration_seconds(summary)
    goal["tokens_used"] = int(goal.get("tokens_used") or 0) + token_delta
    goal["total_tokens_observed"] = int(goal.get("total_tokens_observed") or 0) + total_token_delta
    goal["token_accounting"] = {
        "budget_mode": token_accounting["budget_mode"],
        "last_delta": token_accounting,
    }
    goal["time_used_seconds"] = int(goal.get("time_used_seconds") or 0) + time_delta
    if task.task_id not in goal.setdefault("task_ids", []):
        goal["task_ids"].append(task.task_id)
    if run_id not in goal.setdefault("run_ids", []):
        goal["run_ids"].append(run_id)
    if status in {"needs-repair", "monitor-blocked"} or status.startswith("retryable-"):
        goal["blocked_count"] = int(goal.get("blocked_count") or 0) + 1
        goal.setdefault("blocked_audit", []).append(
            {
                "run_id": run_id,
                "task_id": task.task_id,
                "status": status,
                "reason": summary.get("worker_failure", {}).get("reason", ""),
                "created_at": utc_now(),
            }
        )

    requested_status = str(spec.get("goal_status") or "")
    if requested_status == "complete":
        audit = str(spec.get("goal_completion_audit") or "").strip()
        goal.setdefault("completion_audit", []).append(
            {
                "run_id": run_id,
                "task_id": task.task_id,
                "audit": audit,
                "created_at": utc_now(),
            }
        )
        goal["status"] = "complete" if audit else "active"
    elif requested_status == "blocked":
        goal["status"] = "blocked"
        goal.setdefault("blocked_audit", []).append(
            {
                "run_id": run_id,
                "task_id": task.task_id,
                "status": status,
                "reason": spec.get("goal_blocked_reason") or summary.get("worker_failure", {}).get("reason", ""),
                "created_at": utc_now(),
            }
        )
    elif requested_status in {"active", "paused"}:
        goal["status"] = requested_status

    token_budget_value = goal.get("token_budget")
    if goal.get("status") == "active" and isinstance(token_budget_value, int) and goal["tokens_used"] >= token_budget_value:
        goal["status"] = "budget_limited"
    write_goal(goal)
    result = {"enabled": True, "status": "updated", "goal": goal, "output_path": str(output_path)}
    write_json(output_path, result)
    return result


def active_goal_for_idle_continuation() -> dict[str, Any] | None:
    ensure_dirs()
    candidates: list[dict[str, Any]] = []
    for path in GOALS_DIR.glob("*.json"):
        goal = read_json_file(path)
        if not goal or goal.get("status") != "active":
            continue
        token_budget_value = goal.get("token_budget")
        tokens_used = int(goal.get("tokens_used") or 0)
        if isinstance(token_budget_value, int) and tokens_used >= token_budget_value:
            goal["status"] = "budget_limited"
            write_goal(goal)
            continue
        candidates.append(goal)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: str(item.get("updated_at") or ""), reverse=True)[0]


def requirements_method_packet() -> str:
    return """Requirements method packet:
- Canonical method source: docs/method.md.
- Top-level rule: debate before decision, execute after decision.
- debate_next means research/model/review/decision work only; do not implement production changes.
- execution_next means a decided slice with data/state contract, reference mechanism, acceptance, and allowed execution.
- Analysis worker may close-read, reverse-model, collect references, draft data/state flows, and produce review packets.
- Execution worker may implement only decided slices; if the packet is not decided, return a change request.
- Treat the user's words as business input, not automatically as the implementation plan.
- First restate the real problem, then translate it into system behavior.
- Data first: identify schema/state/event/object shape before polishing UI/API/code.
- Performance second: latency, stability, budget, retry, recovery, and soak expectations matter after data shape is right.
- Separate must/should/could and explicitly preserve out_of_scope.
- Product/mainline is a pressure role: market/reference research, scenario pressure, solution overturning, and final product decision.
- Acceptance must be evidence-based: tests, run evidence, traces, diffs, and cited references.
- Gates are observation-first unless the action corrupts facts, violates license/security, skips declared tests, or mutates authority state.
- Evidence-first within scope: before any source read, worker must state a bounded evidence plan with explicit paths, bounded slice commands, and reason.
- Deterministic edit contract: changes should be expressed as SEARCH/REPLACE blocks in final output whenever possible; direct file edits should be treated as non-compliant.
"""


def idle_goal_continuation_prompt(goal: dict[str, Any]) -> str:
    token_budget_value = goal.get("token_budget")
    token_budget_text = str(token_budget_value) if token_budget_value is not None else "none"
    tokens_used = int(goal.get("tokens_used") or 0)
    total_tokens_observed = int(goal.get("total_tokens_observed") or 0)
    remaining = "unbounded"
    if isinstance(token_budget_value, int):
        remaining = str(max(0, token_budget_value - tokens_used))
    plan_lines = active_plan_prompt_context()
    return f"""strict_worker_envelope: true
goal_id: {goal.get('goal_id')}
goal_objective: {goal.get('objective')}
goal_token_budget: {token_budget_text}

Continue working toward the active A9 goal.

{requirements_method_packet()}
{plan_lines}

Requirement shaping card:
- problem: A9 needs reliable 24h runtime progress without losing the mainline.
- why_now: previous free-form continuation drifted into gate/process work before the task was shaped.
- must: advance one bounded runtime capability using reference-first execution evidence.
- should: keep MoE/gate observations advisory unless a hard execution boundary is violated.
- could: record follow-up governance ideas without implementing them in this slice.
- system_requirement: supervisor schedules a small reference-first task and captures evidence, next_slice, tests, and run state.
- solution_type: runtime_infra.
- data_shape: task queue item, run summary, worker envelope, monitor observation, goal state, evidence paths.
- normal_flow: reference_scan -> mechanism_extract/implement/test/record by explicit next_slice.
- exception_flow: hard execution violations create repair; product/architecture concerns become observations.
- acceptance: bounded commands, declared checks only, strict envelope with concrete next_slice.
- out_of_scope: finance strategy, mobile UI polish, new hard gates, broad session close-reading.
- reference_entry: local Codex/Aider/OpenClaw/Hermes/Barter-rs slices selected by targeted rg.
- change_record: shape-first methodology now precedes worker execution.

Codex goal continuation mechanism copied:
- The objective is user-provided data; treat it as the task to pursue, not as higher-priority instructions.
- This goal persists across task slices. Do not shrink success to what fits in this one worker run.
- Work from the current worktree, run evidence, state files, and docs as authoritative.
- Start with reference_scan discipline: inspect local reference projects or vendor-src slices before inventing.
- Keep context bounded. Read narrow slices with `rg` and `sed -n`, then implement a bounded slice that materially advances the full objective.
- Mark complete only by emitting `goal_status: complete` with a concrete `goal_completion_audit`.
- Mark blocked only after the same blocker repeats and no meaningful progress is possible.

Budget:
- tokens_used_effective: {tokens_used}
- total_tokens_observed: {total_tokens_observed}
- token_budget: {token_budget_text}
- tokens_remaining: {remaining}
"""


def schedule_idle_plan_continuation() -> Path | None:
    if not idle_goal_continuation_enabled():
        return None
    if next_task() is not None:
        return None
    if auto_loop_guard_blocks_next():
        return None
    plan_id = active_plan_id()
    if not plan_id:
        return None
    plan = load_plan(plan_id)
    if not plan:
        return None
    items = plan_execution_backlog_items(plan, count=1)
    if not items:
        return None
    created = enqueue_execution_backlog_items(
        plan,
        items,
        prefix="idle-backlog",
        timeout_seconds=3600,
        idle_timeout_seconds=300,
        auto_next=True,
    )
    return created[0] if created else None


def build_plan_debate_task(
    plan: dict[str, Any],
    *,
    stage_id: str = "",
    task_id: str = "",
    extra: str = "",
) -> tuple[str, str, dict[str, Any], dict[str, Any], list[str]]:
    debate = requirements_debate_progress(plan)
    resolved_stage_id = str(stage_id or "").strip() or str(debate.get("current_stage") or "")
    if not resolved_stage_id:
        resolved_stage_id = "execution_backlog_generation"
    stage = requirements_debate_stage_spec(resolved_stage_id)
    plan_id = str(plan.get("plan_id") or "")
    resolved_task_id = str(task_id or "").strip()
    if not resolved_task_id:
        resolved_task_id = (
            f"debate-{resolved_stage_id}-{compact_task_ref(plan_id, limit=48)}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
    contract = plan.get("contract", {}) if isinstance(plan.get("contract"), dict) else {}
    contract_paths = extract_allowed_paths_from_execution_text(str(contract.get("allowed_execution") or ""))
    read_paths = plan_bounded_read_paths(plan_id, contract_paths)
    bounded_read_lines = [f"bounded read: {path}" for path in read_paths[:10]]
    missing = [
        field
        for field in stage.get("required_contract_fields", [])
        if not str(contract.get(str(field)) or "").strip()
    ]
    prompt_lines = [
        "decision_status: not_decided",
        "route: debate_next",
        f"plan_id: {plan_id}",
        f"goal_id: {plan.get('goal_id', '')}",
        f"debate_stage: {resolved_stage_id}",
        f"debate_stage_label: {stage.get('label', '')}",
        f"missing_contract_fields: {', '.join(str(item) for item in missing)}",
        f"problem: {contract.get('problem', '')}",
        f"why_now: {contract.get('why_now', '')}",
        f"system_requirement: {contract.get('system_requirement', '')}",
        f"data_shape: {contract.get('data_shape', '')}",
        f"normal_flow: {contract.get('normal_flow', '')}",
        f"exception_flow: {contract.get('exception_flow', '')}",
        f"acceptance: {contract.get('acceptance', '')}",
        f"out_of_scope: {contract.get('out_of_scope', '')}",
        "live_read_budget_policy: stop",
        *bounded_read_lines,
        "",
        "Debate task:",
        str(stage.get("prompt", "")),
        "",
        "Output requirements:",
        "- Append findings/progress/change_request to the active plan if evidence changes the contract.",
        "- Keep the final worker envelope compact and valid JSON; summarize decision packet deltas instead of dumping the full packet.",
        "- Produce a decision packet draft only when the missing fields are supported by evidence, but keep large evidence in files and cite paths.",
        "- Do not implement production code in this task.",
        "- Read only bounded slices from the declared bounded read paths; do not search /root/a9 or .a9 roots.",
        "- Use capped `rg -n -m 20` or `rg ... | head -n 40`; never run uncapped rg in read-heavy phases.",
        "- Keep each `sed -n` source window <= 120 lines and total requested source lines <= 180.",
        "- If the stage is ready, propose candidate execution_next backlog slices with allowed paths and checks.",
        "- If output.execution_backlog.items is non-empty, output.decision_status MUST be `decided` and output.change_request.status MUST be `none`; otherwise the backlog will be ignored as not closed.",
        "- If output.decision_status is `not_decided`, do not include execution_backlog.items; return output.change_request.status `required` with the missing decision reason.",
        "- When proposing execution slices, include at most 3 compact items under output.execution_backlog.items.",
        "- Each execution backlog item must use file-level allowed_paths or narrow file globs; do not use broad roots such as `scripts`, `crates`, `.a9`, `/root/a9`, or runtime evidence directories.",
        "- Each execution backlog item check must be an executable command such as `python3 -m unittest ...`; put natural-language validation notes in the prompt, not in checks.",
        "- Final envelope shape:",
        '  {"protocolVersion":1,"ok":true,"status":"ok","output":{"summary":"...","worker_commands_run":["..."],"supervisor_declared_checks":[],"decision_status":"not_decided|decided","change_request":{"status":"none|required","reason":"..."},"execution_backlog":{"items":[{"title":"...","phase":"reference_scan|mechanism_extract|implement|test|record","prompt":"...","allowed_paths":["..."],"checks":["..."]}]}}}',
    ]
    if extra:
        prompt_lines.extend(["", "Extra operator direction:", str(extra).strip()])
    return resolved_task_id, "\n".join(prompt_lines), debate, stage, read_paths


def enqueue_plan_debate_task(
    plan: dict[str, Any],
    *,
    stage_id: str = "",
    task_id: str = "",
    extra: str = "",
    phase: str = "reference_scan",
    timeout_seconds: int = 3600,
    idle_timeout_seconds: int = 300,
    auto_next: bool = False,
) -> tuple[Path, dict[str, Any]]:
    resolved_task_id, prompt, debate, _stage, read_paths = build_plan_debate_task(
        plan,
        stage_id=stage_id,
        task_id=task_id,
        extra=extra,
    )
    path = enqueue_task_file(
        resolved_task_id,
        prompt,
        phase=phase,
        checks=[],
        timeout_seconds=timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        max_attempts=1,
        allowed_paths=read_paths,
        auto_next=auto_next,
    )
    return path, debate


def schedule_idle_debate_continuation() -> Path | None:
    if not idle_goal_continuation_enabled():
        return None
    if next_task() is not None:
        return None
    if auto_loop_guard_blocks_next():
        return None
    plan_id = active_plan_id()
    if not plan_id:
        return None
    plan = load_plan(plan_id)
    if not plan:
        return None
    debate = requirements_debate_progress(plan)
    if debate.get("status") == "ready_for_execution_backlog":
        return None
    backlog = execution_backlog_state(plan)
    if any(isinstance(item, dict) for item in backlog.get("items", [])):
        return None
    stage_id = str(debate.get("current_stage") or "")
    plan_ref = compact_task_ref(plan_id, limit=48)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    task_id = f"idle-debate-{stage_id or 'requirements'}-{plan_ref}-{timestamp}"
    path, _ = enqueue_plan_debate_task(
        plan,
        stage_id=stage_id,
        task_id=task_id,
        extra=(
            "Idle 24h lane router selected requirements debate before execution. "
            "Close missing contract fields with evidence or produce a change_request; do not implement."
        ),
        phase="reference_scan",
        timeout_seconds=3600,
        idle_timeout_seconds=300,
        auto_next=True,
    )
    return path


def schedule_idle_lane_continuation() -> tuple[str, Path] | None:
    plan_path_result = schedule_idle_plan_continuation()
    if plan_path_result:
        return "plan-continuation", plan_path_result
    debate_path = schedule_idle_debate_continuation()
    if debate_path:
        return "debate-continuation", debate_path
    if active_plan_id():
        return None
    goal_path_result = schedule_idle_goal_continuation()
    if goal_path_result:
        return "goal-continuation", goal_path_result
    return None


def schedule_idle_goal_continuation() -> Path | None:
    if not idle_goal_continuation_enabled():
        return None
    if next_task() is not None:
        return None
    if auto_loop_guard_blocks_next():
        return None
    goal = active_goal_for_idle_continuation()
    if not goal:
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    task_id = f"goal-continuation-{compact_task_ref(str(goal.get('goal_id') or 'goal'))}-{timestamp}"
    return enqueue_task_file(
        task_id,
        idle_goal_continuation_prompt(goal),
        phase="reference_scan",
        checks=list(REFERENCE_SCAN_CHECKS),
        timeout_seconds=3600,
        idle_timeout_seconds=300,
        max_attempts=1,
        allowed_paths=[],
    )


def idle_goal_continuation_enabled() -> bool:
    value = os.environ.get("A9_IDLE_GOAL_CONTINUATION")
    if value is None:
        return DEFAULT_IDLE_GOAL_CONTINUATION_ENABLED
    return value.strip().lower() in {"1", "true", "yes", "on"}


def bounded_inline(text: str, limit: int = 500) -> str:
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def process_governance_prompt_summary(process_governance: dict[str, Any]) -> dict[str, Any]:
    findings = process_governance.get("findings", []) if isinstance(process_governance, dict) else []
    findings = findings if isinstance(findings, list) else []
    by_kind: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        kind = str(finding.get("kind") or "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if len(samples) < 3:
            sample = {
                "kind": kind,
                "message": bounded_inline(str(finding.get("message") or ""), 120),
            }
            if finding.get("command"):
                sample["command"] = bounded_inline(str(finding.get("command") or ""), 220)
            if finding.get("limit") is not None:
                sample["limit"] = finding.get("limit")
            if finding.get("lines") is not None:
                sample["lines"] = finding.get("lines")
            samples.append(sample)
    return {
        "status": process_governance.get("status", "") if isinstance(process_governance, dict) else "",
        "policy": process_governance.get("policy", "") if isinstance(process_governance, dict) else "",
        "findings_count": len(findings),
        "by_kind": by_kind,
        "samples": samples,
    }


def compact_worker_cost_usage(summary: dict[str, Any] | None) -> dict[str, int]:
    usage: dict[str, Any] = {}
    if summary:
        pressure = summary.get("context_pressure", {})
        if isinstance(pressure, dict):
            usage = pressure.get("actual_token_usage", {})
        if not usage:
            worker = summary.get("worker", {})
            if isinstance(worker, dict):
                usage = worker.get("actual_token_usage", {})
    if not isinstance(usage, dict):
        usage = {}
    return {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "cached_input_tokens": int(usage.get("cached_input_tokens", 0) or 0),
        "uncached_input_tokens": int(usage.get("uncached_input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "reasoning_output_tokens": int(usage.get("reasoning_output_tokens", 0) or 0),
    }


def worker_cost_usage_reasons(usage: dict[str, int]) -> list[str]:
    output_reasoning = usage["output_tokens"] + usage["reasoning_output_tokens"]
    reasons: list[str] = []
    if usage["input_tokens"] >= WORKER_COST_HIGH_INPUT_TOKENS:
        reasons.append("high_input_tokens")
    elif usage["input_tokens"] >= WORKER_COST_OBSERVE_INPUT_TOKENS:
        reasons.append("observe_input_tokens")
    if usage["uncached_input_tokens"] >= WORKER_COST_HIGH_UNCACHED_TOKENS:
        reasons.append("high_uncached_input_tokens")
    elif usage["uncached_input_tokens"] >= WORKER_COST_OBSERVE_UNCACHED_TOKENS:
        reasons.append("observe_uncached_input_tokens")
    if output_reasoning >= WORKER_COST_HIGH_OUTPUT_REASONING_TOKENS:
        reasons.append("high_output_reasoning_tokens")
    elif output_reasoning >= WORKER_COST_OBSERVE_OUTPUT_REASONING_TOKENS:
        reasons.append("observe_output_reasoning_tokens")
    return reasons


def worker_cost_process_reasons(process: dict[str, Any]) -> list[str]:
    by_kind = process.get("by_kind", {})
    if not isinstance(by_kind, dict):
        by_kind = {}
    reasons: list[str] = []
    broad_kinds = {
        "broad_file_slice_observation",
        "broad_rg_command",
        "uncapped_rg_command",
        "compound_wide_read_command",
        "runtime_evidence_root_read",
    }
    if any(int(by_kind.get(kind, 0) or 0) > 0 for kind in broad_kinds):
        reasons.append("broad_reads")
    if int(by_kind.get("direct_file_change_event", 0) or 0) > 0:
        reasons.append("direct_file_changes")
    if int(process.get("findings_count", 0) or 0) > 0 and not reasons:
        reasons.append("process_findings")
    return reasons


def worker_cost_risk(summary: dict[str, Any] | None) -> dict[str, Any]:
    usage = compact_worker_cost_usage(summary)
    process = process_governance_prompt_summary(summary.get("process_governance", {}) if summary else {})
    reasons: list[str] = []
    for reason in worker_cost_usage_reasons(usage) + worker_cost_process_reasons(process):
        if reason not in reasons:
            reasons.append(reason)
    high = any(reason.startswith("high_") for reason in reasons) or any(
        reason in {"broad_reads", "direct_file_changes"} for reason in reasons
    )
    level = "high" if high else "observe" if reasons else "ok"
    return {
        "level": level,
        "reasons": reasons,
        "actual_token_usage": usage,
        "process_findings": {
            "findings_count": int(process.get("findings_count", 0) or 0),
            "by_kind": process.get("by_kind", {}),
        },
    }


def is_selftest_summary(summary: dict[str, Any] | None) -> bool:
    if not summary:
        return False
    return is_selftest_run_id(summary.get("task_id")) or is_selftest_run_id(summary.get("run_dir"))


def latest_run_summaries() -> dict[str, Any]:
    latest = sorted(RUNS_DIR.glob("*/summary.json"), key=lambda path: path.stat().st_mtime)
    invalid_summaries = 0
    latest_any: dict[str, Any] = {}
    latest_real: dict[str, Any] = {}
    latest_selftest: dict[str, Any] = {}
    for summary_path in reversed(latest):
        data = read_json_file(summary_path)
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
        "latest_any": latest_any,
        "latest_real": latest_real,
        "latest_selftest": latest_selftest,
        "invalid_summaries": invalid_summaries,
    }


def latest_process_quality(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {}
    process = process_governance_prompt_summary(summary.get("process_governance", {}))
    usage = summary.get("context_pressure", {}).get("actual_token_usage", {})
    if not isinstance(usage, dict) or not usage:
        usage = summary.get("worker", {}).get("actual_token_usage", {})
    if not isinstance(usage, dict):
        usage = {}
    return {
        "process_governance": process,
        "actual_token_usage": usage,
    }


def next_phase_for(status: str, current_phase: str) -> str:
    if status in {"needs-repair", "monitor-blocked"} or status.startswith("retryable-"):
        return "repair"
    if status == "needs-followup":
        return current_phase or "implement"
    if current_phase not in PHASE_ORDER:
        return "compare"
    index = PHASE_ORDER.index(current_phase)
    return PHASE_ORDER[(index + 1) % len(PHASE_ORDER)]


NEXT_SLICE_PHASE_PREFIXES = {
    "reference_scan": "reference_scan",
    "mechanism_extract": "mechanism_extract",
    "implement": "implement",
    "test": "test",
    "repair": "repair",
    "record": "record",
}

NEXT_SLICE_RESOLUTION_REVISION = 1


def phase_from_next_slice(next_slice: Any) -> str | None:
    text = str(next_slice or "").strip()
    if not text or ":" not in text:
        return None
    prefix = text.split(":", 1)[0].strip().lower().replace("-", "_")
    return NEXT_SLICE_PHASE_PREFIXES.get(prefix)


def next_slice_is_operator_handoff(next_slice: Any) -> bool:
    text = str(next_slice or "").strip().lower()
    if not text:
        return False
    if phase_from_next_slice(text):
        return False
    return any(
        marker in text
        for marker in (
            "hand off",
            "handoff",
            "outer a9 supervisor",
            "outer supervisor",
            "declared-check",
            "declared check",
            "deferred to supervisor",
            "supervisor will run",
        )
    )


def next_slice_is_actionable_for_auto_next(next_slice: Any) -> bool:
    return phase_from_next_slice(next_slice) is not None


def resolve_next_slice_contract(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {
            "next_slice": "",
            "next_slice_source": "",
            "next_slice_resolution_revision": NEXT_SLICE_RESOLUTION_REVISION,
        }
    ordered_candidates = (
        ("next_slice", "worker_envelope.output.next_slice"),
        ("next_recommended_task", "worker_envelope.output.next_recommended_task"),
        ("next_task", "worker_envelope.output.next_task"),
        ("next", "worker_envelope.output.next"),
        ("slice", "worker_envelope.output.slice"),
    )
    for key, source in ordered_candidates:
        value = output.get(key)
        text = str(value).strip() if value is not None else ""
        if text:
            return {
                "next_slice": text,
                "next_slice_source": source,
                "next_slice_resolution_revision": NEXT_SLICE_RESOLUTION_REVISION,
            }
    return {
        "next_slice": "",
        "next_slice_source": "",
        "next_slice_resolution_revision": NEXT_SLICE_RESOLUTION_REVISION,
    }


def probe_action_to_followup(probe_action: Any, probe_action_reason: Any = "") -> dict[str, str]:
    action = str(probe_action or "").strip().lower()
    reason = str(probe_action_reason or "").strip()
    if action == "continue":
        return {
            "action": "continue",
            "status": "needs-followup",
            "phase": "implement",
            "reason": reason or "probe_continue",
        }
    if action == "repair":
        return {
            "action": "repair",
            "status": "needs-repair",
            "phase": "repair",
            "reason": reason or "probe_repair",
        }
    if action == "retry":
        return {
            "action": "retry",
            "status": "retryable-remote-probe",
            "phase": "repair",
            "reason": reason or "probe_retry",
        }
    return {
        "action": "retry",
        "status": "retryable-remote-probe",
        "phase": "repair",
        "reason": reason or "probe_action_unknown",
    }


def flow_status_for_task(phase: str, status: str) -> str:
    if status == "pass":
        return f"{phase}_done"
    if status == "needs-followup":
        return f"{phase}_followup"
    if status == "needs-repair":
        return f"{phase}_needs_repair"
    if status.startswith("retryable-"):
        return f"{phase}_retryable"
    return f"{phase}_{slugify(status).replace('-', '_')}"


def worker_output_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    envelope = summary.get("worker_envelope", {})
    if not isinstance(envelope, dict):
        return {}
    payload = envelope.get("envelope", {})
    if not isinstance(payload, dict):
        return {}
    output = payload.get("output", {})
    if not isinstance(output, dict):
        return {"raw_output": output}
    normalized = dict(output)
    next_slice_contract = resolve_next_slice_contract(output)
    normalized["next_slice"] = next_slice_contract["next_slice"]
    normalized["next_slice_source"] = next_slice_contract["next_slice_source"]
    normalized["next_slice_resolution_revision"] = next_slice_contract["next_slice_resolution_revision"]
    return normalized


def compact_monitor_repair_evidence(summary: dict[str, Any]) -> dict[str, Any]:
    process = process_governance_prompt_summary(summary.get("process_governance", {}))
    worker_output = worker_output_from_summary(summary)
    checks = summary.get("checks", [])
    checks = checks if isinstance(checks, list) else []
    check_summary = []
    for item in checks[:5]:
        if not isinstance(item, dict):
            continue
        check_summary.append(
            {
                "command": bounded_inline(str(item.get("command") or ""), 180),
                "return_code": item.get("return_code"),
                "status": item.get("status", ""),
            }
        )
    diff = summary.get("diff", {})
    diff = diff if isinstance(diff, dict) else {}
    changed_files = worker_output.get("changed_files", [])
    return {
        "task_id": summary.get("task_id", ""),
        "status": summary.get("status", ""),
        "run_dir": summary.get("run_dir", ""),
        "process_governance": process,
        "monitor_block": summary.get("monitor_block", {}),
        "checks": check_summary,
        "diff_bytes": diff.get("diff_bytes", 0),
        "changed_files": changed_files if isinstance(changed_files, list) else [],
    }


def slim_repair_next_task_prompt(task: Task, summary: dict[str, Any], phase: str) -> str:
    worker_output = worker_output_from_summary(summary)
    compact_evidence = compact_monitor_repair_evidence(summary)
    patch_apply = summary.get("patch_apply", {})
    patch_apply_hint = format_patch_apply_repair_hint(patch_apply, summary.get("git_governance", {}))
    declared_checks = checks_for_next_phase(phase, task)
    allowed_paths = task.allowed_paths if task.allowed_paths else []
    allowed_paths_text = "\n".join(f"- {path}" for path in allowed_paths) if allowed_paths else "- none declared"
    declared_checks_text = "\n".join(f"- {check}" for check in declared_checks) if declared_checks else "- none declared"
    repair_hint = f"\n{patch_apply_hint}\n" if patch_apply_hint else ""
    return f"""strict_worker_envelope: true
direct_file_change_policy: repair
decision_status: decided

Slim auto-repair task.
{("Monitor-blocked repair." if summary.get("status") == "monitor-blocked" else "").strip()}

Problem:
- Previous run status: {summary.get('status', '')}
- Previous task: {task.task_id}
- Previous run: {summary.get('run_dir', '')}
- Repair only the exact blocker shown below. Do not continue the broader pipeline.

Authority:
- Task frontmatter allowed_paths is the only write scope.
- Declared checks are authoritative.
- Declared checks below are authoritative and are run by the outer supervisor.
- Worker self-report is evidence only; do not invent changed_files or supervisor_declared_checks.
- If no file changes are needed, output changed_files: [] and no search_replace_blocks.

Allowed paths:
{allowed_paths_text}

Declared checks:
{declared_checks_text}

Compact repair evidence:
compact_monitor_evidence:
{bounded_inline(json.dumps(compact_evidence, ensure_ascii=False), 1800)}

Previous worker output:
- next_slice: {bounded_inline(worker_output.get('next_slice', ''), 500)}
- changed_files_claim: {bounded_inline(json.dumps(worker_output.get('changed_files', []), ensure_ascii=False), 500)}
- copied_mechanisms: {bounded_inline(json.dumps(worker_output.get('copied_mechanisms', []), ensure_ascii=False), 700)}
{repair_hint}
Repair discipline:
- Use the compact evidence above first.
- Before source reads, list exact bounded commands and reasons.
- Use `rg -n "<anchor>" <allowed-path> | head -n 40` before every sed source read.
- Each sed source window must be <= 120 lines.
- Do not read `.a9/runs`, raw sessions, broad docs, or reference projects unless an exact path above requires it.
- If compact evidence is insufficient, return a change request asking the monitor for the missing bounded evidence.
- Do not edit files directly. Put SEARCH/REPLACE blocks in `output.search_replace_blocks`.
- Do not run tests yourself. The outer supervisor runs the declared checks.

Final envelope:
- Return valid JSON with protocolVersion 1, status ok, worker_commands_run,
  supervisor_declared_checks copied exactly from the Declared checks section,
  changed_files matching actual proposed patch paths, copied_mechanisms, and next_slice.
"""


def next_task_prompt(task: Task, summary: dict[str, Any], phase: str) -> str:
    if phase == "repair":
        return slim_repair_next_task_prompt(task, summary, phase)
    focus_lines = "\n".join(f"- {name}: {focus}" for name, focus in PHASE_FOCUS.items())
    worker_output = worker_output_from_summary(summary)
    include_direct_file_change_repair = (
        parse_direct_file_change_policy(task.prompt) == "repair"
        or strict_worker_envelope_required_for_phase(phase)
    )
    direct_file_change_policy_line = (
        "direct_file_change_policy: repair\n" if include_direct_file_change_repair else ""
    )
    test_slice_command = extracted_test_command_from_next_slice(worker_output.get("next_slice", ""))
    check_scope_notice = ""
    if test_slice_command:
        declared_checks = checks_for_next_phase(phase, task)
        if command_matches_declared_check(test_slice_command, declared_checks):
            check_scope_notice = f"""
Test command sync:
- next_slice suggested executable test command: `{test_slice_command}`
- command is declared in task checks; do not execute it in the worker. The outer supervisor runs it after final output.
"""
        else:
            check_scope_notice = f"""
Test command sync:
- next_slice suggested executable test command: `{test_slice_command}`
- proposal-only: do not execute this command unless it is added to task.checks/frontmatter.
"""
    previous_output_lines = ""
    if worker_output:
        previous_output_lines = f"""
Previous worker output:
- next_slice: {bounded_inline(worker_output.get('next_slice', ''), 700)}
- next_slice_source: {bounded_inline(str(worker_output.get('next_slice_source', '')), 200)}
- next_slice_resolution_revision: {worker_output.get('next_slice_resolution_revision', '')}
- copied_mechanisms: {bounded_inline(json.dumps(worker_output.get('copied_mechanisms', []), ensure_ascii=False), 1200)}
- changed_files: {bounded_inline(json.dumps(worker_output.get('changed_files', []), ensure_ascii=False), 500)}
"""
    evidence_edit_contract = """
Evidence-and-edit contract:
- Before any reads, list a bounded evidence plan with:
  - 3 paths max you will inspect.
  - exact bounded read commands (rg/sed ranges) for each path.
  - one-line reason for each slice.
- Editing contract:
  - prefer SEARCH/REPLACE for all file changes.
  - include search_replace_blocks in strict-worker output (or return no-change if no edits).
  - avoid proposing unbounded re-reads unless explicitly required.
"""

    phase_lines = ""
    if phase == "reference_scan":
        phase_lines = """
Phase-specific bounds:
expected_file_changes: false
- Do not modify files in this phase.
- Do not `cat` full context, record, session, or reference files.
- Read only bounded snippets with `sed -n '1,120p'` or targeted capped `rg -n -m <N>`.
- Pick one concrete next mechanism and put it in `output.next_slice`.
"""
    elif phase in {"mechanism_extract", "vendor_import"}:
        phase_lines = """
Phase-specific bounds:
- Do not broaden into implementation unless the phase is `implement`.
- Do not `cat` full context, record, session, or reference files.
- Use targeted capped `rg -n -m <N>` and bounded `sed` snippets only.
"""
    repair_hint = ""
    patch_apply = summary.get("patch_apply", {})
    patch_apply_hint = format_patch_apply_repair_hint(patch_apply, summary.get("git_governance", {}))
    if summary.get("status") == "needs-repair" and patch_apply_hint:
        repair_hint = f"""
{patch_apply_hint}
"""
    if summary.get("status") == "monitor-blocked":
        compact_evidence = compact_monitor_repair_evidence(summary)
        repair_hint = f"""
Monitor-blocked repair:
- The previous run was blocked by monitor/process governance; do not continue the normal pipeline.
- compact_monitor_evidence: {bounded_inline(json.dumps(compact_evidence, ensure_ascii=False), 1400)}
- Use the compact evidence above first. Do not inspect raw runtime evidence, run summaries, event logs,
  or process_governance output files unless a monitor supplies a new exact bounded evidence path.
- Declared checks are authoritative. Do not rerun undeclared checks, especially broad pytest/cargo commands.
- If compact evidence is insufficient, return a change request asking the monitor for the missing
  bounded evidence instead of searching `.a9/runs`.
- Preserve data-first acceptance and performance-second constraints before applying or rewriting any patch.
"""
    flow = summary.get("flow_transition", {})
    flow_lines = ""
    if isinstance(flow, dict) and flow.get("flow_id") and flow.get("revision") is not None:
        next_seq_line = ""
        if flow.get("last_seq") is not None:
            next_seq_line = (
                f"- flow_expected_last_seq: {flow['last_seq']}\n"
                f"- flow_sequence: {int(flow['last_seq']) + 1}"
            )
        flow_lines = f"""
Managed flow:
- flow_id: {flow['flow_id']}
- flow_expected_revision: {flow['revision']}
{next_seq_line}
"""
    record_lines = ""
    if summary.get("deterministic_record_path"):
        record_lines = f"""
Deterministic record:
- record_path: {summary['deterministic_record_path']}
"""
    goal_lines = ""
    goal_state = summary.get("goal_state", {})
    goal = goal_state.get("goal", {}) if isinstance(goal_state, dict) else {}
    if isinstance(goal, dict) and goal.get("goal_id") and goal.get("status") in {"active", "budget_limited"}:
        token_budget_value = goal.get("token_budget")
        token_budget_text = str(token_budget_value) if token_budget_value is not None else "none"
        remaining = "unbounded"
        if isinstance(token_budget_value, int):
            remaining = str(max(0, token_budget_value - int(goal.get("tokens_used") or 0)))
        goal_lines = f"""
Active goal:
- goal_id: {goal.get('goal_id')}
- goal_objective: {goal.get('objective')}
- goal_status: {goal.get('status')}
- goal_token_budget: {token_budget_text}
- goal_tokens_used: {goal.get('tokens_used', 0)}
- goal_tokens_remaining: {remaining}

Codex-style goal continuation:
- Keep the full objective intact across task slices; do not shrink success to the easiest subset.
- Work from current files, run evidence, checks, and state as authoritative.
- Mark a goal complete only with explicit `goal_status: complete` and a concrete `goal_completion_audit`.
- Use `goal_status: blocked` only when the same blocker repeats and no meaningful progress is possible.
"""
    communication_acceptance_lines = communication_acceptance_hints(task, summary)
    plan_lines = active_plan_prompt_context()
    return f"""strict_worker_envelope: true
{direct_file_change_policy_line}

Continue A9 24-hour automation.

Previous task: {task.task_id}
Previous phase: {task.phase}
Previous status: {summary['status']}
Previous run: {summary['run_dir']}
Previous context: {summary['context_path']}
{previous_output_lines}

Phase: {phase}
{flow_lines}
{record_lines}
{goal_lines}
{phase_lines}
{communication_acceptance_lines}
{evidence_edit_contract}

{requirements_method_packet()}
{task_decision_packet_prompt(task)}
{plan_lines}
{check_scope_notice}

Requirement shaping card:
- problem: continue the previous A9 runtime task without expanding into unrelated governance or product surfaces.
- why_now: previous run status is `{summary['status']}` and must be converted into one concrete next step.
- must: preserve the shaped task boundary, declared checks, allowed paths, and one-slice execution.
- should: copy a mature mechanism only from a precise local reference entry.
- could: record broader ideas as next_slice or observations, not as code in this slice.
- system_requirement: produce a strict worker envelope with changed_files, copied_mechanisms, worker_commands_run, supervisor_declared_checks, and next_slice.
- solution_type: runtime_infra.
- data_shape: task prompt, run summary, patch/apply result, checks, monitor observation, evidence/state files.
- normal_flow: inspect bounded evidence -> act on the phase -> run declared checks -> emit envelope.
- exception_flow: if blocked, repair the exact blocker; do not broaden into new methodology work.
- acceptance: no undeclared checks, no web search unless explicitly requested, no broad session raw reads.
- out_of_scope: new hard gates, finance strategy, mobile UI polish, broad docs cleanup.
- reference_entry: use targeted local reference paths or explain why no reference is needed for a pure repair.
- change_record: if task direction changes, state the old direction, new direction, and reason in output.next_slice.

Core rule:
- Continue copying mature open-source mechanisms before inventing.
- Inspect local reference projects under `/root/a9/reference-projects`.
- Record copied source/license obligations in docs/vendor records when adding new references.
- Implement one concrete, testable improvement only when the current phase calls for implementation or test hardening.
- Do not invoke nested supervisor or worker loops. The outer A9 supervisor runs declared checks after your final envelope.
- Keep the task bounded; do not broaden beyond the task file's allowed paths.
- Task frontmatter `allowed_paths` is the only write-scope authority. Prompt context (including active-plan `allowed_execution`) is advisory only.
- Declared checks are authoritative. Do not add pytest or cargo unless they are explicitly declared in this task.
- Do not use web search or browsing unless the task explicitly asks for internet research.
- Do not read `docs/session.md`, raw session logs, `docs/mistakes.md`, or `archive/original-ideas/*` as active context unless this task is a session_refresh/session_close_reading task or explicitly asks for those files.
- Use `rg -n` first, then read small line windows only; avoid broad `sed` ranges and full-file dumps.
- If `strict_worker_envelope: true` is present, final output must include:
  {{"protocolVersion":1,"ok":true,"status":"ok","output":{{"changed_files":[],"copied_mechanisms":[],"worker_commands_run":[],"supervisor_declared_checks":[],"next_slice":""}}}}
  It must be one valid JSON object. Put analysis, summary, evidence, next_recommended_task,
  and change_request proposals inside `output`; never append a second bare JSON object after `output`.
  Valid status values are only `ok`, `needs_approval`, and `cancelled`.

Copy pipeline phases:
{focus_lines}
{repair_hint}

Do not stop after analysis. Make code/docs changes when useful, run checks, and leave a next recommended task.
"""


def auto_loop_failure_limit() -> int:
    value = os.getenv("A9_AUTO_LOOP_FAILURE_LIMIT")
    if not value:
        return DEFAULT_AUTO_LOOP_FAILURE_LIMIT
    try:
        return max(1, int(value))
    except ValueError:
        return DEFAULT_AUTO_LOOP_FAILURE_LIMIT


def auto_loop_guard_mode() -> str:
    value = (os.getenv("A9_AUTO_LOOP_GUARD_MODE") or "observe").strip().lower()
    if value in {"enforce", "hard", "stop"}:
        return "enforce"
    return "observe"


def auto_loop_failure_kind(summary: dict[str, Any]) -> str:
    status = str(summary.get("status") or "")
    worker_failure = summary.get("worker_failure", {})
    failure_status = str(worker_failure.get("status") or "") if isinstance(worker_failure, dict) else ""
    if status.startswith("retryable-"):
        return status
    if failure_status.startswith("retryable-"):
        return failure_status
    if status in {"needs-repair", "monitor-blocked", "worker-failed", "failed"}:
        return status
    envelope = summary.get("worker_envelope", {})
    if isinstance(envelope, dict) and envelope.get("status") == "fail":
        return "worker-envelope-fail"
    return ""


def worker_failure_short_circuits_checks(worker_failure: dict[str, Any]) -> bool:
    status = str(worker_failure.get("status") or "")
    if status.startswith("retryable-"):
        return True
    return status == "monitor-blocked"


def worker_model_fallback_model() -> str:
    return os.getenv("A9_SUPERVISOR_FALLBACK_MODEL", DEFAULT_WORKER_MODEL_FALLBACK).strip()


def maybe_apply_worker_model_fallback(task: Task, summary: dict[str, Any]) -> dict[str, Any]:
    worker = summary.get("worker", {}) if isinstance(summary.get("worker"), dict) else {}
    worker_failure = summary.get("worker_failure", {}) if isinstance(summary.get("worker_failure"), dict) else {}
    failure_status = str(worker_failure.get("status") or summary.get("status") or "")
    worker_model = str(worker.get("worker_model") or "")
    worker_model_source = str(worker.get("worker_model_source") or "")
    fallback = worker_model_fallback_model()
    if failure_status != "retryable-worker-transport":
        return {"status": "skipped", "reason": "not_transport_failure"}
    if worker_model != DEFAULT_WORKER_MODEL or worker_model_source != "DEFAULT_WORKER_MODEL":
        return {
            "status": "skipped",
            "reason": "worker_model_not_default",
            "worker_model": worker_model,
            "worker_model_source": worker_model_source,
        }
    if not fallback or fallback == worker_model:
        return {"status": "skipped", "reason": "missing_or_same_fallback_model", "fallback_model": fallback}
    state = write_worker_model_phase_override(
        task.phase,
        fallback,
        reason="retryable_worker_transport_from_default_model",
        task_id=task.task_id,
        run_dir=str(summary.get("run_dir") or ""),
    )
    return {
        "status": "applied",
        "phase": task.phase,
        "previous_model": worker_model,
        "fallback_model": fallback,
        "source": f"worker_model_policy.phase_models.{task.phase}",
        "policy_path": str(WORKER_MODEL_POLICY_PATH),
        "policy_updated_at": state.get("updated_at", ""),
    }


def update_auto_loop_guard(summary: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    kind = auto_loop_failure_kind(summary)
    previous = read_json_file(AUTO_LOOP_GUARD_PATH)
    limit = auto_loop_failure_limit()
    mode = auto_loop_guard_mode()
    if kind:
        consecutive = int(previous.get("consecutive_failures") or 0) + 1
        state = {
            "status": "tripped" if consecutive >= limit else "watching",
            "mode": mode,
            "consecutive_failures": consecutive,
            "failure_limit": limit,
            "latest_failure": kind,
            "latest_task_id": summary.get("task_id", ""),
            "latest_run_dir": summary.get("run_dir", ""),
            "updated_at": utc_now(),
        }
    else:
        state = {
            "status": "ok",
            "mode": mode,
            "consecutive_failures": 0,
            "failure_limit": limit,
            "latest_failure": "",
            "latest_task_id": summary.get("task_id", ""),
            "latest_run_dir": summary.get("run_dir", ""),
            "updated_at": utc_now(),
        }
    write_json(AUTO_LOOP_GUARD_PATH, state)
    return state


def auto_loop_guard_blocks_next(summary: dict[str, Any] | None = None) -> bool:
    if summary is not None:
        state = summary.get("auto_loop_guard", {})
        if not isinstance(state, dict):
            return False
        mode = str(state.get("mode") or auto_loop_guard_mode()).strip().lower()
        return mode == "enforce" and state.get("status") == "tripped"
    state = {}
    if not state:
        state = read_json_file(AUTO_LOOP_GUARD_PATH)
    mode = str(state.get("mode") or auto_loop_guard_mode()).strip().lower()
    return mode == "enforce" and state.get("status") == "tripped"


def task_quality_warnings_for_enqueue(
    *,
    phase: str,
    checks: list[str],
    allowed_paths: list[str],
    workspace_root: str = "",
) -> list[str]:
    warnings: list[str] = []
    workspace_text = str(workspace_root or "").strip()
    if workspace_text:
        workspace_path = Path(workspace_text).expanduser()
        if not workspace_path.is_absolute():
            workspace_path = ROOT / workspace_path
        if not (workspace_path / ".git").exists():
            warnings.append("workspace_root_not_git_repo")
    if strict_worker_envelope_required_for_phase(phase):
        for path in allowed_paths:
            normalized = str(path).strip().replace("\\", "/")
            if normalized == ".a9" or normalized.startswith(".a9/"):
                if "write_scope_runtime_ignored_path:.a9" not in warnings:
                    warnings.append("write_scope_runtime_ignored_path:.a9")
    shell_test_re = re.compile(r"""^\s*test\s+["'][^"'$()]+["']\s*[!=]=?\s*""")
    for check in checks:
        text = str(check).strip()
        if shell_test_re.search(text) and "$(" not in text and "`" not in text:
            if "declared_check_maybe_shell_expanded:test_literal" not in warnings:
                warnings.append("declared_check_maybe_shell_expanded:test_literal")
        for target in unresolved_unittest_targets(text):
            if unittest_target_allowed_for_future_test(target, allowed_paths):
                continue
            warning = f"declared_check_unresolved_unittest_target:{target}"
            if warning not in warnings:
                warnings.append(warning)
    return warnings


def enqueue_task_file(
    task_id: str,
    prompt: str,
    *,
    phase: str = "implement",
    checks: list[str] | None = None,
    timeout_seconds: int = 3600,
    idle_timeout_seconds: int = 300,
    max_attempts: int = 2,
    allowed_paths: list[str] | None = None,
    auto_next: bool = True,
    workspace_root: str = "",
) -> Path:
    ensure_dirs()
    clean_id = compact_task_ref(task_id, limit=120)
    path = QUEUE_DIR / f"{clean_id}.md"
    suffix = 1
    while path.exists():
        suffix += 1
        path = QUEUE_DIR / f"{clean_id}-{suffix}.md"
    checks = checks or []
    allowed_paths = allowed_paths or []
    workspace_root = str(workspace_root or "").strip()
    if strict_worker_envelope_required_for_phase(phase) and "strict_worker_envelope" not in parse_key_value_prompt(prompt):
        prompt = f"strict_worker_envelope: true\n{prompt.strip()}"
    checks_text = "\n".join(f"  - {frontmatter_quote(item)}" for item in checks)
    allowed_paths_text = "\n".join(f"  - {frontmatter_quote(item)}" for item in allowed_paths)
    quality_warnings = task_quality_warnings_for_enqueue(
        phase=phase,
        checks=checks,
        allowed_paths=allowed_paths,
        workspace_root=workspace_root,
    )
    quality_warnings_text = "\n".join(f"  - {frontmatter_quote(item)}" for item in quality_warnings)
    frontmatter = [
        "---",
        f"id: {frontmatter_quote(path.stem)}",
        f"phase: {frontmatter_quote(phase)}",
        f"workspace_root: {frontmatter_quote(workspace_root)}",
        f"timeout_seconds: {timeout_seconds}",
        f"idle_timeout_seconds: {idle_timeout_seconds}",
        f"max_attempts: {max_attempts}",
        f"auto_next: {str(bool(auto_next)).lower()}",
        "checks:",
        checks_text,
        "allowed_paths:",
        allowed_paths_text,
        "task_quality_warnings:",
        quality_warnings_text,
        "---",
        "",
        prompt.strip(),
        "",
    ]
    path.write_text("\n".join(frontmatter), encoding="utf-8")
    return path


def write_deterministic_record(task: Task, summary: dict[str, Any]) -> Path:
    ensure_dirs()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RECORDS_DIR / f"{timestamp}-{compact_task_ref(task.task_id)}.json"
    worker_envelope = summary.get("worker_envelope", {})
    worker_output = worker_output_from_summary(summary)
    if not isinstance(worker_output, dict):
        worker_output = {}
    record = {
        "recorded_at": utc_now(),
        "mode": "deterministic_supervisor_record",
        "task_id": task.task_id,
        "phase": task.phase,
        "status": summary.get("status"),
        "run_dir": summary.get("run_dir"),
        "context_path": summary.get("context_path"),
        "evidence_path": summary.get("evidence_path"),
        "state_path": summary.get("state_path"),
        "deep_marks_path": summary.get("deep_marks_path"),
        "worker_output": {
            "changed_files": worker_output.get("changed_files", []),
            "copied_mechanisms": worker_output.get("copied_mechanisms", []),
            "tests": worker_output.get("tests", []),
            "next_slice": worker_output.get("next_slice", ""),
            "next_slice_source": worker_output.get("next_slice_source", ""),
            "next_slice_resolution_revision": worker_output.get("next_slice_resolution_revision", 1),
        },
        "guards": {
            "worker_envelope": worker_envelope.get("status") if isinstance(worker_envelope, dict) else "",
            "patch_apply": summary.get("patch_apply", {}).get("status"),
            "patch_guard": summary.get("patch_guard", {}).get("status"),
            "scope_guard": summary.get("scope_guard", {}).get("status"),
            "git_governance": summary.get("git_governance", {}).get("status"),
        },
        "git": {
            "commit": summary.get("git_governance", {}).get("commit", ""),
            "rolled_back": summary.get("git_governance", {}).get("rolled_back", False),
        },
        "checks": summary.get("checks", []),
        "actual_token_usage": summary.get("worker", {}).get("actual_token_usage", {}),
        "context_pressure": summary.get("context_pressure", {}),
    }
    write_json(path, record)
    return path


def checks_for_next_phase(phase: str, task: Task) -> list[str]:
    if phase == "reference_scan":
        return list(REFERENCE_SCAN_CHECKS)
    if task.checks:
        return list(task.checks)
    return list(DEFAULT_NEXT_CHECKS)


def extracted_test_command_from_next_slice(next_slice: Any) -> str:
    text = str(next_slice or "").strip()
    if not text.lower().startswith("test:"):
        return ""
    body = text.split(":", 1)[1].strip().strip("`").strip()
    if not body:
        return ""
    candidates = [
        r"(python3?\s+-m\s+unittest\b[^\n]*)",
        r"(python3?\s+-m\s+pytest\b[^\n]*)",
        r"(\bpytest\b[^\n]*)",
        r"(\bcargo\s+test\b[^\n]*)",
        r"(\bnpm\s+test\b[^\n]*)",
        r"(\bpnpm\s+test\b[^\n]*)",
        r"(\byarn\s+test\b[^\n]*)",
    ]
    for pattern in candidates:
        match = re.search(pattern, body, flags=re.IGNORECASE)
        if not match:
            continue
        command = normalize_shell_command(match.group(1).strip().strip("`").rstrip(".,;:"))
        if not command:
            continue
        if re.search(r"[;&|><`$()]", command):
            continue
        if not command_looks_like_test(command):
            continue
        return command
    return ""


def monitor_blocked_repair_checks(task: Task, summary: dict[str, Any], phase: str) -> list[str]:
    checks = checks_for_next_phase(phase, task)
    if phase != "repair":
        return checks
    process_governance = summary.get("process_governance", {})
    findings = process_governance.get("findings", []) if isinstance(process_governance, dict) else []
    # Declared checks are the executable boundary; undeclared checks remain
    # governance observations/proposals in process_governance findings.
    for finding in findings:
        if not isinstance(finding, dict) or finding.get("kind") != "undeclared_check":
            continue
        # Keep undeclared-check details in process_governance findings only.
        continue
    return checks


def monitor_blocked_repair_command_is_test_case(command: str) -> bool:
    normalized = normalize_shell_command(command)
    if re.match(r"^(python3?\s+-m\s+unittest)\b", normalized):
        return True
    return re.match(
        r"^(python3?\s+-m\s+pytest|pytest|cargo\s+test|npm\s+test|pnpm\s+test|yarn\s+test)\b",
        normalized,
    ) is not None


def python_module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def pytest_command_to_unittest_command(command: str) -> str:
    normalized = normalize_shell_command(command)
    if not re.match(r"^(python3?\s+-m\s+pytest|pytest)\b", normalized):
        return ""
    try:
        parts = shlex.split(normalized)
    except ValueError:
        return ""
    if parts[:3] in (["python", "-m", "pytest"], ["python3", "-m", "pytest"]):
        args = parts[3:]
    elif parts and parts[0] == "pytest":
        args = parts[1:]
    else:
        return ""
    selector = next((item for item in args if item and not item.startswith("-")), "")
    target = pytest_selector_to_unittest_target(selector)
    if not target:
        return ""
    return f"python3 -m unittest {target}"


def pytest_selector_to_unittest_target(selector: str) -> str:
    if not selector:
        return ""
    selector = selector.split("[", 1)[0]
    node_parts = selector.split("::")
    if not node_parts:
        return ""
    file_part = node_parts[0]
    if not file_part.endswith(".py"):
        return ""
    module = file_part[:-3].replace("/", ".").replace("\\", ".").strip(".")
    if not module:
        return ""
    tail = [part.strip() for part in node_parts[1:] if part.strip()]
    return ".".join([module, *tail]) if tail else module


def communication_task_requires_gateway_runtime_evidence(task: Task, summary: dict[str, Any]) -> bool:
    worker_output = worker_output_from_summary(summary)
    repo_map_noise = re.compile(r"^- .+ score=\d+\s*$")
    prompt_lines = [
        line
        for line in task.prompt.splitlines()
        if "out_of_scope" not in line.lower()
        and "not_doing_now" not in line.lower()
        and "goal_objective" not in line.lower()
        and "active goal" not in line.lower()
        and not repo_map_noise.match(line.strip())
        and not line.strip().lower().startswith("symbols:")
    ]
    detection_units = [task.phase, str(worker_output.get("next_slice", "")), *prompt_lines]
    haystack = " ".join(detection_units).lower()
    units = [str(unit).lower() for unit in detection_units if str(unit).strip()]
    if any(communication_hint_present(haystack, hint) for hint in COMMUNICATION_GATE_HINTS):
        return True
    return any(
        all(communication_hint_present(unit, part) for part in combo)
        for combo in COMMUNICATION_GATE_COMBO_HINTS
        for unit in units
    )


def communication_hint_present(haystack: str, hint: str) -> bool:
    # Treat "*-like" wording as descriptive noise (e.g. "communication-like filenames"),
    # not an actual communication-runtime intent signal.
    if re.fullmatch(r"[a-z0-9]+", hint):
        return re.search(rf"(?<![a-z0-9]){re.escape(hint)}(?![a-z0-9-])", haystack) is not None
    return hint in haystack


def communication_acceptance_hints(task: Task, summary: dict[str, Any]) -> str:
    if not communication_task_requires_gateway_runtime_evidence(task, summary):
        return ""
    return """
Communication acceptance hints:
- Data model: prove node table shape, heartbeat/event stream fields, tmux evidence state transitions, and command status schema.
- Performance bounds: define latency/timeout targets, retry budget, reconnect stability expectations, and per-run event budget.
- Failure taxonomy -> recovery mapping: timeout/auth/network/protocol/rate_limit must map to retry/repair/quarantine/terminate actions.
"""


def gateway_runtime_gate() -> dict[str, Any]:
    control_path = ROOT / "scripts" / "a9_control_api.py"
    if not control_path.exists():
        return {
            "status": "unavailable",
            "action": "block",
            "reason": "control_api_missing",
        }
    spec = importlib.util.spec_from_file_location("a9_control_api_gateway_gate", control_path)
    if not spec or not spec.loader:
        return {
            "status": "unavailable",
            "action": "block",
            "reason": "control_api_load_failed",
        }
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    gateway = module.gateway_transport_contract(ROOT)
    runtime = gateway.get("runtime_evidence", {}) if isinstance(gateway, dict) else {}
    if not isinstance(runtime, dict):
        runtime = {}
    return {
        "status": runtime.get("status", gateway.get("status", "unknown") if isinstance(gateway, dict) else "unknown"),
        "action": runtime.get("action", "block"),
        "reason": runtime.get("reason", gateway.get("reason", "gateway_runtime_evidence_missing") if isinstance(gateway, dict) else "gateway_runtime_evidence_missing"),
        "gateway_status": gateway.get("status", "unknown") if isinstance(gateway, dict) else "unknown",
        "event_id": runtime.get("event_id", ""),
        "age_seconds": runtime.get("age_seconds"),
        "stale_seconds": runtime.get("stale_seconds"),
    }


def gateway_runtime_blocks_next(task: Task, summary: dict[str, Any]) -> bool:
    if not communication_task_requires_gateway_runtime_evidence(task, summary):
        summary["gateway_runtime_gate"] = {"status": "skip", "action": "continue", "reason": "not_communication_task"}
        return False
    gate = gateway_runtime_gate()
    summary["gateway_runtime_gate"] = gate
    return gate.get("action") != "continue"


def queued_operator_task() -> Path | None:
    for path in sorted(QUEUE_DIR.glob("*.md")):
        if not path.stem.startswith("auto-"):
            return path
    return None


def schedule_next_task(task: Task, summary: dict[str, Any]) -> Path | None:
    if flow_transition_blocks_next(summary):
        return None
    if auto_loop_guard_blocks_next(summary):
        return None
    if not task.auto_next_allowed:
        summary["auto_next_block"] = {
            "reason": "task_auto_next_disabled",
            "status": summary.get("status", ""),
            "task_id": task.task_id,
            "task_path": str(task.path),
        }
        return None
    fallback = maybe_apply_worker_model_fallback(task, summary)
    summary["worker_model_fallback"] = fallback
    if fallback.get("status") == "applied":
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        parent_ref = compact_task_ref(task.task_id)
        task_id = f"auto-retry-model-fallback-{parent_ref}-{timestamp}"
        retry_prompt = (
            task.prompt
            + "\n\nA9 supervisor retry note:\n"
            + f"- previous_status: {summary.get('status')}\n"
            + f"- previous_worker_failure: {summary.get('worker_failure', {}).get('reason', '') if isinstance(summary.get('worker_failure'), dict) else ''}\n"
            + f"- model_fallback: {fallback.get('previous_model')} -> {fallback.get('fallback_model')}\n"
            + f"- policy_path: {fallback.get('policy_path')}\n"
        )
        return enqueue_task_file(
            task_id,
            retry_prompt,
            phase=task.phase,
            checks=task.checks,
            timeout_seconds=task.timeout_seconds,
            idle_timeout_seconds=task.idle_timeout_seconds,
            max_attempts=1,
            allowed_paths=task.allowed_paths,
        )
    if task.phase == SESSION_REFRESH_PHASE:
        return schedule_next_session_refresh_task(task, summary)
    if task.phase == SESSION_CLOSE_READING_PHASE:
        return schedule_next_session_close_reading_task(task, summary)
    if summary["status"] == "monitor-blocked":
        phase = next_phase_for(summary["status"], task.phase)
        checks = monitor_blocked_repair_checks(task, summary, phase)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        parent_ref = compact_task_ref(task.task_id)
        task_id = f"auto-{phase}-{parent_ref}-{timestamp}"
        return enqueue_task_file(
            task_id,
            next_task_prompt(task, summary, phase),
            phase=phase,
            checks=checks,
            timeout_seconds=3600,
            idle_timeout_seconds=300,
            max_attempts=1,
            allowed_paths=task.allowed_paths,
        )
    if monitor_score_blocks_next(summary):
        return None
    if gateway_runtime_blocks_next(task, summary):
        return None
    if summary["status"] not in {"pass", "needs-followup", "needs-repair"}:
        return None
    explicit_decision = explicit_task_decision_packet(task)
    if explicit_decision and explicit_decision.get("route") == "debate_next":
        plan_update = summary.get("active_plan_update", {}) if isinstance(summary.get("active_plan_update"), dict) else {}
        backlog_update = (
            plan_update.get("execution_backlog_update", {}) if isinstance(plan_update.get("execution_backlog_update"), dict) else {}
        )
        plan_id = str(plan_update.get("plan_id") or parse_key_value_prompt(task.prompt).get("plan_id") or "").strip()
        plan = load_plan(plan_id) if plan_id else active_plan()
        if not plan:
            plan = active_plan()
        debate_state = requirements_debate_progress(plan) if isinstance(plan, dict) else {}
        plan_ready_for_execution_backlog = str(debate_state.get("status") or "") == "ready_for_execution_backlog"
        has_unclosed_backlog_draft = False
        if isinstance(plan, dict):
            terminal_backlog_statuses = {
                "pass",
                "passed",
                "done",
                "complete",
                "completed",
                "closed",
                "cancelled",
                "skipped",
            }
            has_unclosed_backlog_draft = any(
                isinstance(item, dict)
                and str(item.get("status") or "ready").strip().lower() not in terminal_backlog_statuses
                for item in execution_backlog_state(plan).get("items", [])
            )
        stale_debate_evidence = explicit_decision.get("decision_status") in {
            "not_decided",
            "partial_decision",
            "missing",
        }

        if (
            not plan_ready_for_execution_backlog
            and stale_debate_evidence
            and has_unclosed_backlog_draft
        ):
            summary["auto_next_block"] = {
                "reason": "review_closure_wait",
                "status": summary["status"],
                "plan_id": plan.get("plan_id") if isinstance(plan, dict) else "",
                "plan_ready_for_execution_backlog": False,
                "decision_status": explicit_decision.get("decision_status", "missing"),
                "missing_fields": explicit_decision.get("missing_fields", []),
                "recommendation": explicit_decision.get("recommendation", ""),
                "task_id": task.task_id,
            }
            return None

        if plan_ready_for_execution_backlog and (
            summary["status"] in {"needs-followup", "needs-repair"} or stale_debate_evidence
        ):
            summary["auto_next_block"] = {
                "reason": "review_closure_wait",
                "status": summary["status"],
                "plan_id": plan.get("plan_id") if isinstance(plan, dict) else "",
                "plan_ready_for_execution_backlog": True,
                "decision_status": explicit_decision.get("decision_status", "missing"),
                "missing_fields": explicit_decision.get("missing_fields", []),
                "recommendation": explicit_decision.get("recommendation", ""),
                "task_id": task.task_id,
            }
            return None
        if backlog_update.get("status") == "appended" and plan_id:
            next_path = schedule_execution_backlog_from_plan(plan_id)
            if next_path is not None:
                summary["auto_next_backlog"] = {
                    "status": "scheduled",
                    "plan_id": plan_id,
                    "added_count": backlog_update.get("added_count", 0),
                    "next_task_path": str(next_path),
                }
                summary.pop("auto_next_block", None)
                return next_path
        summary["auto_next_block"] = {
            "reason": "debate_next_requires_monitor_decision",
            "decision_status": explicit_decision.get("decision_status", "missing"),
            "missing_fields": explicit_decision.get("missing_fields", []),
            "recommendation": explicit_decision.get("recommendation", ""),
            "task_id": task.task_id,
        }
        return None
    phase = next_phase_for(summary["status"], task.phase)
    worker_output = worker_output_from_summary(summary)
    deterministic_record_ready = (
        phase == "record"
        and summary["status"] == "pass"
        and isinstance(summary.get("git_governance"), dict)
        and str(summary.get("git_governance", {}).get("status") or "") in {"committed", "skip"}
    )
    if summary["status"] in {"pass", "needs-followup"}:
        if "worker_envelope" in summary and not str(worker_output.get("next_slice", "")).strip():
            summary["auto_next_block"] = {
                "reason": "missing_worker_next_slice",
                "status": summary["status"],
                "task_id": task.task_id,
            }
            return None
        if next_slice_is_operator_handoff(worker_output.get("next_slice")):
            summary["auto_next_block"] = {
                "reason": "operator_handoff_next_slice_requires_monitor",
                "status": summary["status"],
                "task_id": task.task_id,
                "next_slice": worker_output.get("next_slice", ""),
                "next_slice_source": worker_output.get("next_slice_source", ""),
            }
            return None
        if (
            "worker_envelope" in summary
            and task.phase == "test"
            and not deterministic_record_ready
            and not next_slice_is_actionable_for_auto_next(worker_output.get("next_slice"))
        ):
            summary["auto_next_block"] = {
                "reason": "next_slice_missing_phase_prefix",
                "status": summary["status"],
                "task_id": task.task_id,
                "next_slice": worker_output.get("next_slice", ""),
                "next_slice_source": worker_output.get("next_slice_source", ""),
            }
            return None
        summary.pop("auto_next_block", None)
        routed_phase = phase_from_next_slice(worker_output.get("next_slice"))
        if routed_phase:
            phase = routed_phase
    if phase == "record" and summary["status"] == "pass":
        record_path = write_deterministic_record(task, summary)
        summary["deterministic_record_path"] = str(record_path)
        phase = next_phase_for("pass", "record")
    operator_task = queued_operator_task()
    if operator_task is not None:
        summary["auto_next_block"] = {
            "reason": "operator_priority_queued_input",
            "queued_task_id": operator_task.stem,
            "queued_task_path": str(operator_task),
        }
        return None
    checks = checks_for_next_phase(phase, task)
    suggested_test_command = extracted_test_command_from_next_slice(worker_output.get("next_slice", ""))
    if phase == "test" and suggested_test_command and not command_matches_declared_check(suggested_test_command, checks):
        checks.append(suggested_test_command)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parent_ref = compact_task_ref(task.task_id)
    task_id = f"auto-{phase}-{parent_ref}-{timestamp}"
    return enqueue_task_file(
        task_id,
        next_task_prompt(task, summary, phase),
        phase=phase,
        checks=checks,
        timeout_seconds=3600,
        idle_timeout_seconds=300,
        max_attempts=1,
        allowed_paths=task.allowed_paths,
    )


def flow_transition_blocks_next(summary: dict[str, Any]) -> bool:
    transition = summary.get("flow_transition")
    if not isinstance(transition, dict):
        return False
    return bool(transition.get("enabled")) and transition.get("status") == "fail"


def monitor_score_blocks_next(summary: dict[str, Any]) -> bool:
    return False


def monitor_block_summary(monitor_score: dict[str, Any]) -> dict[str, Any]:
    gates = monitor_score.get("gates") if isinstance(monitor_score.get("gates"), dict) else {}
    hard_gate = gates.get("hard_gate") if isinstance(gates.get("hard_gate"), dict) else {}
    advisory = hard_gate.get("status") == "fail"
    failed_experts = hard_gate.get("failed_experts")
    return {
        "blocked": False,
        "advisory": advisory,
        "reason": "monitor_hard_gate_advisory" if advisory else "",
        "recommended_action": monitor_score.get("recommended_action", ""),
        "failed_experts": failed_experts if isinstance(failed_experts, list) else [],
    }


def reconcile_status_with_monitor_block(
    status: str,
    monitor_block: dict[str, Any],
    worker_envelope_check_conflict: dict[str, Any] | None = None,
    worker_envelope: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    block = dict(monitor_block) if isinstance(monitor_block, dict) else {}
    if not block.get("blocked") or status != "pass":
        return status, block
    if isinstance(worker_envelope, dict) and worker_envelope.get("status") == "skip":
        previous_reason = str(block.get("reason") or "")
        previous_failed_experts = block.get("failed_experts")
        block["blocked"] = False
        block["reason"] = "monitor_block_advisory_for_non_strict_worker"
        block["override"] = {
            "status": "advisory",
            "source": "non_strict_worker_envelope",
            "previous_reason": previous_reason,
            "previous_failed_experts": previous_failed_experts if isinstance(previous_failed_experts, list) else [],
        }
        return "pass", block
    if isinstance(worker_envelope_check_conflict, dict) and worker_envelope_check_conflict.get("status") == "reconciled-pass":
        previous_reason = str(block.get("reason") or "")
        previous_failed_experts = block.get("failed_experts")
        block["blocked"] = False
        block["reason"] = "monitor_block_overridden_by_supervisor_reconciliation"
        block["override"] = {
            "status": "overridden",
            "source": "worker_envelope_check_conflict",
            "conflict_status": worker_envelope_check_conflict.get("status"),
            "conflict_reason": worker_envelope_check_conflict.get("reason", ""),
            "previous_reason": previous_reason,
            "previous_failed_experts": previous_failed_experts if isinstance(previous_failed_experts, list) else [],
        }
        return "pass", block
    if str(block.get("reason") or "") == "monitor_hard_gate_failed":
        previous_failed_experts = block.get("failed_experts")
        block["blocked"] = False
        block["advisory"] = True
        block["reason"] = "monitor_hard_gate_advisory"
        block["override"] = {
            "status": "advisory",
            "source": "shape_first_methodology",
            "previous_reason": "monitor_hard_gate_failed",
            "previous_failed_experts": previous_failed_experts if isinstance(previous_failed_experts, list) else [],
        }
        return "pass", block
    if not str(block.get("reason") or "").strip():
        block["reason"] = "monitor_hard_gate_failed"
    return "monitor-blocked", block


def schedule_next_session_refresh_task(task: Task, summary: dict[str, Any]) -> Path | None:
    if summary.get("status") != "pass":
        return None
    refresh = summary.get("session_refresh", {})
    if refresh.get("auto_close_reading", True) and refresh.get("extract_path"):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        parent_ref = compact_task_ref(task.task_id)
        task_id = f"auto-session-close-reading-{parent_ref}-{refresh.get('from_turn')}-{refresh.get('to_turn')}-{timestamp}"
        prompt = f"""extract_path: {refresh['extract_path']}
close_reading_doc: {refresh.get('close_reading_doc', 'docs/session.md')}
summary_doc: {refresh.get('summary_doc', 'docs/session.md')}
source_session_path: {refresh['source_session_path']}
to_turn: {refresh['to_turn']}
user_turn_count: {refresh['user_turn_count']}
batch_size: {refresh.get('batch_size', 10)}
auto_continue: {str(refresh.get('auto_continue', True)).lower()}
auto_close_reading: true
flow_id: {refresh.get('flow_id', '')}
flow_expected_revision: {refresh.get('flow_revision', '')}
flow_expected_last_seq: {refresh.get('flow_last_seq', '')}
flow_sequence: {refresh.get('flow_next_seq', '')}

Continue the managed external session flow. Append bounded deterministic close-reading notes,
then let the close-reading route decide whether to schedule the next session_refresh range.
"""
        return enqueue_task_file(
            task_id,
            prompt,
            phase=SESSION_CLOSE_READING_PHASE,
            checks=[],
            timeout_seconds=120,
            idle_timeout_seconds=120,
            max_attempts=1,
        )
    return schedule_next_session_refresh_range(task.task_id, refresh)


def schedule_next_session_refresh_range(parent_task_id: str, refresh: dict[str, Any]) -> Path | None:
    if not refresh.get("auto_continue", True):
        return None
    try:
        current_to = int(refresh["to_turn"])
        user_turn_count = int(refresh["user_turn_count"])
        batch_size = max(1, int(refresh.get("batch_size", 10)))
    except (KeyError, TypeError, ValueError):
        return None
    if current_to >= user_turn_count:
        return None

    next_from = current_to + 1
    next_to = min(current_to + batch_size, user_turn_count)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parent_ref = compact_task_ref(parent_task_id)
    task_id = f"auto-session-refresh-{parent_ref}-{next_from}-{next_to}-{timestamp}"
    prompt = f"""source_session_path: {refresh['source_session_path']}
from_turn: {next_from}
to_turn: {next_to}
batch_size: {batch_size}
auto_continue: true
auto_close_reading: {str(refresh.get('auto_close_reading', True)).lower()}
close_reading_doc: {refresh.get('close_reading_doc', 'docs/session.md')}
summary_doc: {refresh.get('summary_doc', 'docs/session.md')}
flow_id: {refresh.get('flow_id', '')}
flow_expected_revision: {refresh.get('flow_revision', '')}
flow_expected_last_seq: {refresh.get('flow_last_seq', '')}
flow_sequence: {refresh.get('flow_next_seq', '')}

Continue bounded external Codex/operator session refresh. Keep this route deterministic:
do not call a model, do not run a worker, and do not enter the copy-project pipeline.
"""
    return enqueue_task_file(
        task_id,
        prompt,
        phase=SESSION_REFRESH_PHASE,
        checks=[],
        timeout_seconds=120,
        idle_timeout_seconds=120,
        max_attempts=1,
    )


def schedule_next_session_close_reading_task(task: Task, summary: dict[str, Any]) -> Path | None:
    if summary.get("status") != "pass":
        return None
    reading = summary.get("session_close_reading", {})
    refresh = {
        "source_session_path": reading.get("source_session_path"),
        "to_turn": reading.get("to_turn"),
        "user_turn_count": reading.get("user_turn_count"),
        "batch_size": reading.get("batch_size", 10),
        "auto_continue": reading.get("auto_continue", True),
        "auto_close_reading": reading.get("auto_close_reading", True),
        "close_reading_doc": reading.get("close_reading_doc", "docs/session.md"),
        "summary_doc": reading.get("summary_doc", "docs/session.md"),
        "flow_id": reading.get("flow_id", ""),
        "flow_revision": reading.get("flow_revision"),
        "flow_last_seq": reading.get("flow_last_seq"),
        "flow_next_seq": reading.get("flow_next_seq"),
    }
    return schedule_next_session_refresh_range(task.task_id, refresh)


def service_progress(summary: dict[str, Any] | None = None, next_task_path: Path | None = None) -> dict[str, Any]:
    ensure_dirs()
    existing_next_task_path = next_task_path if next_task_path and next_task_path.exists() else None
    latest_collection = latest_run_summaries()
    latest_real = latest_collection.get("latest_real", {})
    current_plan = active_plan() if active_plan_id() else {}
    latest_plan = plan_latest_run_snapshot(current_plan) if current_plan else {}
    latest_plan_progress = (
        plan_progress_snapshot(current_plan)
        if current_plan
        else {"latest_progress": "", "latest_monitor_progress": "", "has_monitor_progress": False}
    )
    completed_runs = len(list(RUNS_DIR.glob("*/summary.json")))
    done_tasks = len(list(DONE_DIR.glob("*.json")))
    queued_tasks = len(list(QUEUE_DIR.glob("*.md")))
    running_tasks = len(list(RUNNING_DIR.glob("*.json")))
    task_quality = queued_task_quality_summary()
    worker_transport_health = worker_transport_health_state()
    capabilities = {
        "middleware_mysql_redis": True,
        "rust_gateway_streams": True,
        "supervisor_queue_loop": True,
        "evidence_state_deep_marks": True,
        "checkpoint_lineage_channel_history": True,
        "memory_adapter": True,
        "context_compression_noise_gating": True,
        "repo_map": True,
        "event_summaries": True,
        "copy_session": True,
        "auto_next_scheduler": True,
        "browser_or_tui_monitor": True,
        "native_rust_worker": True,
        "copy_pipeline_templates": True,
        "production_daemon_packaging": True,
        "patch_guard_evidence": True,
        "scope_guard_evidence": True,
        "deterministic_search_replace_apply": True,
        "already_applied_detection": True,
        "rollback_aware_repair_prompt": True,
        "worker_event_budget_gate": True,
        "auto_loop_failure_circuit_breaker": True,
        "external_session_refresh_route": True,
        "external_session_close_reading_route": True,
        "persistent_goal_runtime": True,
        "idle_goal_continuation": True,
        "eval_store_records": True,
        "eval_manual_overrides": True,
    }
    capability_groups = {
        "runtime": [
            "middleware_mysql_redis",
            "rust_gateway_streams",
            "supervisor_queue_loop",
            "native_rust_worker",
            "production_daemon_packaging",
        ],
        "context": [
            "evidence_state_deep_marks",
            "checkpoint_lineage_channel_history",
            "memory_adapter",
            "context_compression_noise_gating",
            "repo_map",
            "event_summaries",
            "copy_session",
            "external_session_refresh_route",
            "external_session_close_reading_route",
            "persistent_goal_runtime",
            "eval_store_records",
            "eval_manual_overrides",
        ],
        "automation": [
            "auto_next_scheduler",
            "idle_goal_continuation",
            "browser_or_tui_monitor",
            "copy_pipeline_templates",
        ],
        "governance": [
            "patch_guard_evidence",
            "scope_guard_evidence",
            "deterministic_search_replace_apply",
            "already_applied_detection",
            "rollback_aware_repair_prompt",
            "worker_event_budget_gate",
            "auto_loop_failure_circuit_breaker",
        ],
    }
    group_progress = {}
    for group, names in capability_groups.items():
        done = sum(1 for name in names if capabilities.get(name))
        group_progress[group] = {
            "done": done,
            "total": len(names),
            "percent": round(done / len(names) * 100, 1) if names else 0.0,
            "capabilities": {name: capabilities.get(name, False) for name in names},
        }
    done_capabilities = sum(1 for value in capabilities.values() if value)
    progress = {
        "updated_at": utc_now(),
        "service": "a9-24h-automation",
        "stage": "auto-loop-mvp" if existing_next_task_path else "supervisor-mvp",
        "progress_percent": round(done_capabilities / len(capabilities) * 100, 1),
        "completed_runs": completed_runs,
        "done_tasks": done_tasks,
        "queued_tasks": queued_tasks,
        "running_tasks": running_tasks,
        "task_quality": task_quality,
        "worker_transport_health": worker_transport_health,
        "latest_task_id": summary.get("task_id") if summary else None,
        "latest_status": summary.get("status") if summary else None,
        "latest_run": summary.get("run_dir") if summary else None,
        "latest_real_task_id": latest_real.get("task_id") if latest_real else None,
        "latest_real_status": latest_real.get("status") if latest_real else None,
        "latest_real_run": latest_real.get("run_dir") if latest_real else None,
        "latest_plan_summary": latest_plan.get("summary_path") if latest_plan else None,
        "latest_plan_status": latest_plan.get("status") if latest_plan else None,
        "latest_plan_phase": latest_plan.get("phase") if latest_plan else None,
        "latest_plan_progress": latest_plan_progress,
        "latest_guards": summary.get("guard_summary", compact_guard_summary(summary)) if summary else {},
        "latest_context_pressure": (
            summary.get("context_pressure", compact_context_pressure(summary)) if summary else {}
        ),
        "latest_git_governance": summary.get("git_governance", {}) if summary else {},
        "latest_worker_failure": summary.get("worker_failure", {}) if summary else {},
        "latest_worker_model": summary.get("worker", {}).get("worker_model", "") if summary else "",
        "latest_worker_model_source": summary.get("worker", {}).get("worker_model_source", "") if summary else "",
        "latest_monitor_block": summary.get("monitor_block", {}) if summary else {},
        "latest_process_quality": latest_process_quality(summary),
        "latest_worker_cost_risk": summary.get("worker_cost_risk", worker_cost_risk(summary)) if summary else worker_cost_risk(None),
        "auto_loop_guard": summary.get("auto_loop_guard", read_json_file(AUTO_LOOP_GUARD_PATH)) if summary else read_json_file(AUTO_LOOP_GUARD_PATH),
        "next_task_path": str(existing_next_task_path) if existing_next_task_path else "",
        "auto_next_scheduled": existing_next_task_path is not None,
        "runtime_state": "",
        "runtime_state_reason": "",
        "capabilities": capabilities,
        "capability_groups": group_progress,
        "next_goal": "Run the copy pipeline under the daemon for longer unattended soak tests.",
    }
    progress["runtime_state"], progress["runtime_state_reason"] = runtime_state_from_summary(queued_tasks, running_tasks, summary)
    write_json(PROGRESS_PATH, progress)
    return progress


def write_daemon_heartbeat(state: str, *, detail: str = "") -> dict[str, Any]:
    ensure_dirs()
    started_repo_head = supervisor_process_repo_head()
    try:
        current_repo_head = git_head()
    except RuntimeError:
        current_repo_head = "unknown"
    payload = {
        "updated_at": utc_now(),
        "state": state,
        "detail": detail,
        "pid": os.getpid(),
        "cwd": str(Path.cwd()),
        "started_repo_head": started_repo_head,
        "current_repo_head": current_repo_head,
        "repo_head_stale": bool(
            started_repo_head
            and current_repo_head
            and started_repo_head != "unknown"
            and current_repo_head != "unknown"
            and started_repo_head != current_repo_head
        ),
        "queued_tasks": len(list(QUEUE_DIR.glob("*.md"))),
        "running_tasks": len(list(RUNNING_DIR.glob("*.json"))),
        "done_tasks": len(list(DONE_DIR.glob("*.json"))),
    }
    write_json(DAEMON_HEARTBEAT_PATH, payload)
    return payload


def daemon_heartbeat_status() -> dict[str, Any]:
    heartbeat = read_json_file(DAEMON_HEARTBEAT_PATH)
    if not heartbeat:
        return {}
    try:
        current_repo_head = git_head()
    except RuntimeError:
        current_repo_head = "unknown"
    started_repo_head = str(heartbeat.get("started_repo_head") or "")
    stale = bool(
        started_repo_head
        and current_repo_head
        and started_repo_head != "unknown"
        and current_repo_head != "unknown"
        and started_repo_head != current_repo_head
    )
    heartbeat["current_repo_head"] = current_repo_head
    heartbeat["repo_head_stale"] = stale
    return heartbeat


def print_service_progress(progress: dict[str, Any]) -> None:
    print(
        "24h automation progress: "
        f"{progress['progress_percent']}% "
        f"stage={progress['stage']} "
        f"queued={progress['queued_tasks']} "
        f"done={progress['done_tasks']} "
        f"latest={progress['latest_task_id']}:{progress['latest_status']}"
    )
    if progress.get("next_task_path"):
        print(f"next task: {progress['next_task_path']}")
    groups = progress.get("capability_groups", {})
    if groups:
        rendered = " ".join(f"{name}={item.get('percent', 0)}%" for name, item in sorted(groups.items()))
        print(f"capability groups: {rendered}")
    latest_plan_progress = progress.get("latest_plan_progress", {})
    if isinstance(latest_plan_progress, dict):
        if latest_plan_progress.get("latest_progress"):
            print(f"latest_plan_progress: {latest_plan_progress.get('latest_progress')}")
        if latest_plan_progress.get("latest_monitor_progress"):
            print(f"latest_plan_progress_monitor: {latest_plan_progress.get('latest_monitor_progress')}")


def write_session_refresh_context(task: Task, run_dir: Path, summary: dict[str, Any]) -> Path:
    refresh = summary.get("session_refresh", {})
    content = f"""# Session Refresh Context: {task.task_id}

Updated: {summary['finished_at']}
Status: {summary['status']}
Phase: {task.phase}
Run: {summary['run_dir']}

## Boundary

This route is deterministic supervisor work. It indexes/extracts an external
Codex/operator session and does not call the Codex worker or any model API.

## Source

- source_session_path: {refresh.get('source_session_path', '')}
- from_turn: {refresh.get('from_turn', '')}
- to_turn: {refresh.get('to_turn', '')}
- batch_size: {refresh.get('batch_size', '')}
- auto_continue: {refresh.get('auto_continue', '')}
- auto_close_reading: {refresh.get('auto_close_reading', '')}
- flow_id: {refresh.get('flow_id', '')}
- flow_revision: {refresh.get('flow_revision', '')}
- user_turn_count: {refresh.get('user_turn_count', '')}
- jsonl_lines: {refresh.get('jsonl_lines', '')}
- approx_lines: {refresh.get('approx_lines', '')}

## Outputs

- index_path: {refresh.get('index_path', '')}
- extract_path: {refresh.get('extract_path', '')}
- output_path: {refresh.get('output_path', '')}
- return_code: {refresh.get('return_code', '')}
"""
    context_path = run_dir / "context.md"
    context_path.write_text(content, encoding="utf-8")
    return context_path


def write_session_refresh_evidence_and_state(
    task: Task,
    run_dir: Path,
    summary: dict[str, Any],
    context_path: Path,
) -> tuple[Path, Path, Path, list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    run_id = Path(summary["run_dir"]).name
    checkpoint_id = f"{run_id}:checkpoint:{summary['attempt']}"
    refresh = summary.get("session_refresh", {})
    records: list[dict[str, Any]] = []
    paths = [
        ("raw_task", refresh.get("raw_task_path", ""), {"task_id": task.task_id}),
        (
            "session_refresh_output",
            refresh.get("output_path", ""),
            {
                "return_code": refresh.get("return_code"),
                "source_session_path": refresh.get("source_session_path"),
                "from_turn": refresh.get("from_turn"),
                "to_turn": refresh.get("to_turn"),
            },
        ),
        ("external_session_index", refresh.get("index_path", ""), {"session_id": refresh.get("session_id")}),
        (
            "external_session_extract",
            refresh.get("extract_path", ""),
            {
                "session_id": refresh.get("session_id"),
                "from_turn": refresh.get("from_turn"),
                "to_turn": refresh.get("to_turn"),
            },
        ),
        ("context", context_path, {"status": summary["status"]}),
    ]
    for kind, raw_path, metadata in paths:
        if not str(raw_path):
            continue
        path = Path(raw_path)
        record = evidence_record(
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            kind=kind,
            path=path,
            metadata=metadata,
        )
        if record:
            record["session_id"] = task.task_id
            records.append(record)

    evidence_path = run_dir / "evidence.jsonl"
    with evidence_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    deep_marks: list[dict[str, Any]] = []
    for record in records:
        deep_marks.extend(extract_deep_marks(record))
    deep_marks_path = run_dir / "deep_marks.jsonl"
    with deep_marks_path.open("w", encoding="utf-8") as handle:
        for mark in deep_marks:
            handle.write(json.dumps(mark, ensure_ascii=False) + "\n")

    by_kind: dict[str, list[str]] = {}
    for record in records:
        by_kind.setdefault(record["kind"], []).append(record["evidence_id"])

    state = {
        "checkpoint_id": checkpoint_id,
        "session_id": task.task_id,
        "parent_checkpoint_id": summary.get("parent_checkpoint_id"),
        "step": summary["attempt"],
        "source": SESSION_REFRESH_PHASE,
        "created_at": utc_now(),
        "status": summary["status"],
        "channels": {
            "task": by_kind.get("raw_task", []),
            "external_session": by_kind.get("external_session_index", []) + by_kind.get("external_session_extract", []),
            "messages": by_kind.get("context", []),
            "tool_events": by_kind.get("session_refresh_output", []),
            "repo_state": [{"repo_head": summary["repo_head"]}],
            "deep_marks": [mark["mark_id"] for mark in deep_marks],
            "memories": [],
        },
        "updated_channels": ["task", "external_session", "messages", "tool_events", "repo_state", "deep_marks"],
        "evidence_ids": [record["evidence_id"] for record in records],
        "deep_mark_count": len(deep_marks),
    }
    state_path = run_dir / "state.json"
    write_json(state_path, state)
    return evidence_path, state_path, deep_marks_path, records, state, deep_marks


def build_close_reading_notes(extract: dict[str, Any], extract_path: Path) -> tuple[str, str]:
    from_turn = extract.get("from_turn")
    to_turn = extract.get("to_turn")
    approx_lines = extract.get("approx_lines", "")
    source_session_path = extract.get("source_session_path", "")
    session_id = extract.get("session_id", "")
    heading = f"## Auto Close Reading: Turn {from_turn}-{to_turn}"
    lines = [
        heading,
        "",
        "Source:",
        "",
        f"- session: `{source_session_path}`",
        f"- session_id: `{session_id}`",
        f"- extract: `{extract_path}`",
        f"- approx JSONL lines: `{approx_lines}`",
        f"- generated_at: `{utc_now()}`",
        "",
        "Boundary:",
        "",
        "- deterministic extraction only; no model call",
        "- preserves raw wording previews and tool evidence",
        "- does not replace human/worker deep interpretation",
        "",
    ]
    summary_lines = [
        f"- turn {from_turn}-{to_turn}: external session extract `{extract_path}` lines `{approx_lines}`.",
    ]
    for item in extract.get("turns", []):
        turn = item.get("turn")
        user_line = item.get("user_line")
        user_text = bounded_inline(item.get("user_text", ""), 700)
        assistants = item.get("assistant_messages") or []
        tool_calls = item.get("tool_calls") or []
        tool_names = [str(call.get("name") or "unknown") for call in tool_calls]
        lines.extend(
            [
                f"### Turn {turn}",
                "",
                "Original user intent:",
                "",
                f"- line `{user_line}`: {user_text}",
                "",
                "Execution evidence:",
                "",
                f"- assistant_messages: `{len(assistants)}`",
                f"- tool_calls: `{len(tool_calls)}`"
                + (f" ({', '.join(tool_names[:10])})" if tool_names else ""),
                f"- tool_outputs: `{item.get('tool_output_count', 0)}`",
                "",
            ]
        )
        if assistants:
            lines.extend(["Assistant preview:", "", f"- {bounded_inline(assistants[-1], 700)}", ""])
        summary_lines.append(f"- turn {turn}, line {user_line}: {bounded_inline(user_text, 180)}")
    return "\n".join(lines).rstrip() + "\n", "\n".join(summary_lines).rstrip() + "\n"


def append_once(path: Path, marker: str, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker in existing:
        return False
    separator = "\n\n" if existing.strip() else ""
    path.write_text(existing.rstrip() + separator + content, encoding="utf-8")
    return True


def write_session_close_reading_context(task: Task, run_dir: Path, summary: dict[str, Any]) -> Path:
    reading = summary.get("session_close_reading", {})
    content = f"""# Session Close Reading Context: {task.task_id}

Updated: {summary['finished_at']}
Status: {summary['status']}
Phase: {task.phase}
Run: {summary['run_dir']}

## Boundary

This route consumes a bounded external-session extract and appends deterministic
notes. It does not call Codex, any worker, or any model API.

## Inputs

- extract_path: {reading.get('extract_path', '')}
- from_turn: {reading.get('from_turn', '')}
- to_turn: {reading.get('to_turn', '')}
- user_turn_count: {reading.get('user_turn_count', '')}
- batch_size: {reading.get('batch_size', '')}
- auto_continue: {reading.get('auto_continue', '')}
- auto_close_reading: {reading.get('auto_close_reading', '')}
- flow_id: {reading.get('flow_id', '')}
- flow_revision: {reading.get('flow_revision', '')}
- approx_lines: {reading.get('approx_lines', '')}

## Outputs

- close_reading_doc: {reading.get('close_reading_doc', '')}
- summary_doc: {reading.get('summary_doc', '')}
- close_reading_appended: {reading.get('close_reading_appended', '')}
- summary_appended: {reading.get('summary_appended', '')}
"""
    context_path = run_dir / "context.md"
    context_path.write_text(content, encoding="utf-8")
    return context_path


def write_session_close_reading_evidence_and_state(
    task: Task,
    run_dir: Path,
    summary: dict[str, Any],
    context_path: Path,
) -> tuple[Path, Path, Path, list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    run_id = Path(summary["run_dir"]).name
    checkpoint_id = f"{run_id}:checkpoint:{summary['attempt']}"
    reading = summary.get("session_close_reading", {})
    records: list[dict[str, Any]] = []
    paths = [
        ("raw_task", reading.get("raw_task_path", ""), {"task_id": task.task_id}),
        ("external_session_extract", reading.get("extract_path", ""), {"session_id": reading.get("session_id")}),
        ("close_reading_doc", reading.get("close_reading_doc", ""), {"appended": reading.get("close_reading_appended")}),
        ("close_reading_summary", reading.get("summary_doc", ""), {"appended": reading.get("summary_appended")}),
        ("context", context_path, {"status": summary["status"]}),
    ]
    for kind, raw_path, metadata in paths:
        if not str(raw_path):
            continue
        record = evidence_record(
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            kind=kind,
            path=Path(raw_path),
            metadata=metadata,
        )
        if record:
            record["session_id"] = task.task_id
            records.append(record)

    evidence_path = run_dir / "evidence.jsonl"
    with evidence_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    deep_marks: list[dict[str, Any]] = []
    for record in records:
        deep_marks.extend(extract_deep_marks(record))
    deep_marks_path = run_dir / "deep_marks.jsonl"
    with deep_marks_path.open("w", encoding="utf-8") as handle:
        for mark in deep_marks:
            handle.write(json.dumps(mark, ensure_ascii=False) + "\n")

    by_kind: dict[str, list[str]] = {}
    for record in records:
        by_kind.setdefault(record["kind"], []).append(record["evidence_id"])
    state = {
        "checkpoint_id": checkpoint_id,
        "session_id": task.task_id,
        "parent_checkpoint_id": summary.get("parent_checkpoint_id"),
        "step": summary["attempt"],
        "source": SESSION_CLOSE_READING_PHASE,
        "created_at": utc_now(),
        "status": summary["status"],
        "channels": {
            "task": by_kind.get("raw_task", []),
            "external_session": by_kind.get("external_session_extract", []),
            "messages": by_kind.get("context", []) + by_kind.get("close_reading_doc", []),
            "summaries": by_kind.get("close_reading_summary", []),
            "repo_state": [{"repo_head": summary["repo_head"]}],
            "deep_marks": [mark["mark_id"] for mark in deep_marks],
            "memories": [],
        },
        "updated_channels": ["task", "external_session", "messages", "summaries", "repo_state", "deep_marks"],
        "evidence_ids": [record["evidence_id"] for record in records],
        "deep_mark_count": len(deep_marks),
    }
    state_path = run_dir / "state.json"
    write_json(state_path, state)
    return evidence_path, state_path, deep_marks_path, records, state, deep_marks


def run_session_refresh_task(task: Task, *, auto_next: bool = False) -> int:
    attempt = 1
    run_id = run_id_for_task(task.task_id, attempt)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True)
    lease = {
        "task_id": task.task_id,
        "attempt": attempt,
        "started_at": utc_now(),
        "run_dir": str(run_dir),
        "worktree": "",
        "repo_head": git_head(),
        "parent_checkpoint_id": previous_task_checkpoint_id(task),
    }
    task_ref = artifact_task_ref(task.task_id)
    lease_path = RUNNING_DIR / f"{task_ref}.json"
    write_json(lease_path, lease)
    raw_task_path = run_dir / "raw_task.md"
    raw_task_path.write_text(task.path.read_text(encoding="utf-8"), encoding="utf-8")
    output_path = run_dir / "session_refresh.json"

    refresh: dict[str, Any] = {
        "raw_task_path": str(raw_task_path),
        "output_path": str(output_path),
        "return_code": 1,
        "called_model": False,
        "called_worker": False,
    }
    status = "needs-repair"
    try:
        spec = parse_session_refresh_spec(task.prompt)
        source_path = Path(spec["source_session_path"])
        if not source_path.is_absolute():
            source_path = ROOT / source_path
        refresh.update({**spec, "source_session_path": str(source_path)})
        result = run_cmd_no_raise(
            [
                sys.executable,
                str(ROOT / "scripts" / "a9_session_refresh.py"),
                "refresh",
                str(source_path),
                "--from-turn",
                str(spec["from_turn"]),
                "--to-turn",
                str(spec["to_turn"]),
                "--batch-size",
                str(spec["batch_size"]),
                "--out-dir",
                str(EXTERNAL_SESSIONS_DIR),
            ]
        )
        refresh["return_code"] = result.returncode
        output_path.write_text(result.stdout, encoding="utf-8")
        if result.returncode == 0:
            data = json.loads(result.stdout)
            refresh.update(data)
            status = "pass"
    except (ValueError, json.JSONDecodeError) as exc:
        refresh["error"] = str(exc)
        output_path.write_text(json.dumps(refresh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        **lease,
        "finished_at": utc_now(),
        "status": status,
        "phase": task.phase,
        "task_path": str(task.path),
        "session_refresh": refresh,
        "checks": [],
        "guard_summary": {},
        "context_pressure": {},
        "persistence": {"mysql": {"status": "skipped"}, "redis": {"status": "skipped"}},
    }
    context_path = write_session_refresh_context(task, run_dir, summary)
    summary["context_path"] = str(context_path)
    evidence_path, state_path, deep_marks_path, evidence, state, deep_marks = write_session_refresh_evidence_and_state(
        task, run_dir, summary, context_path
    )
    summary["evidence_path"] = str(evidence_path)
    summary["state_path"] = str(state_path)
    summary["deep_marks_path"] = str(deep_marks_path)
    summary["evidence_count"] = len(evidence)
    summary["deep_mark_count"] = len(deep_marks)
    summary["checkpoint_id"] = state["checkpoint_id"]
    flow_transition = transition_managed_flow(
        flow_id=str(refresh.get("flow_id") or ""),
        expected_revision=refresh.get("flow_expected_revision"),
        expected_last_seq=refresh.get("flow_expected_last_seq"),
        sequence=refresh.get("flow_sequence"),
        next_status="refreshed" if status == "pass" else "refresh_failed",
        actor="a9_supervisor",
        reason=f"{task.phase}:{status}",
        evidence_id=summary["checkpoint_id"],
    )
    summary["flow_transition"] = flow_transition
    if flow_transition.get("revision") is not None:
        refresh["flow_revision"] = flow_transition["revision"]
    elif refresh.get("flow_expected_revision") is not None:
        refresh["flow_revision"] = refresh.get("flow_expected_revision")
    if flow_transition.get("last_seq") is not None:
        refresh["flow_last_seq"] = flow_transition["last_seq"]
        try:
            refresh["flow_next_seq"] = int(flow_transition["last_seq"]) + 1
        except (TypeError, ValueError):
            refresh["flow_next_seq"] = ""
    write_json(run_dir / "summary.json", summary)

    done_path = DONE_DIR / f"{task_ref}.json"
    write_json(done_path, summary)
    lease_path.unlink(missing_ok=True)
    target_task_path = DONE_DIR / task.path.name
    if task.path.exists():
        shutil.move(str(task.path), str(target_task_path))
    next_task_path = schedule_next_task(task, summary) if auto_next else None
    print(f"{task.task_id}: {status}")
    print(f"run: {run_dir}")
    print_service_progress(service_progress(summary, next_task_path))
    return 0 if status in {"pass", "needs-repair"} else 1


def run_session_close_reading_task(task: Task, *, auto_next: bool = False) -> int:
    attempt = 1
    run_id = run_id_for_task(task.task_id, attempt)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True)
    lease = {
        "task_id": task.task_id,
        "attempt": attempt,
        "started_at": utc_now(),
        "run_dir": str(run_dir),
        "worktree": "",
        "repo_head": git_head(),
        "parent_checkpoint_id": previous_task_checkpoint_id(task),
    }
    task_ref = artifact_task_ref(task.task_id)
    lease_path = RUNNING_DIR / f"{task_ref}.json"
    write_json(lease_path, lease)
    raw_task_path = run_dir / "raw_task.md"
    raw_task_path.write_text(task.path.read_text(encoding="utf-8"), encoding="utf-8")
    reading: dict[str, Any] = {
        "raw_task_path": str(raw_task_path),
        "called_model": False,
        "called_worker": False,
    }
    status = "needs-repair"
    try:
        spec = parse_session_close_reading_spec(task.prompt)
        extract_path = Path(spec["extract_path"])
        close_doc = Path(spec["close_reading_doc"])
        summary_doc = Path(spec["summary_doc"])
        if not extract_path.is_absolute():
            extract_path = ROOT / extract_path
        if not close_doc.is_absolute():
            close_doc = ROOT / close_doc
        if not summary_doc.is_absolute():
            summary_doc = ROOT / summary_doc
        extract = json.loads(extract_path.read_text(encoding="utf-8"))
        notes, summary_notes = build_close_reading_notes(extract, extract_path)
        marker = f"## Auto Close Reading: Turn {extract.get('from_turn')}-{extract.get('to_turn')}"
        summary_marker = f"- turn {extract.get('from_turn')}-{extract.get('to_turn')}: external session extract"
        close_appended = append_once(close_doc, marker, notes)
        summary_appended = append_once(summary_doc, summary_marker, "\n## Auto Session Extract Index\n\n" + summary_notes)
        reading.update(
            {
                **spec,
                "extract_path": str(extract_path),
                "close_reading_doc": str(close_doc),
                "summary_doc": str(summary_doc),
                "session_id": extract.get("session_id"),
                "source_session_path": spec.get("source_session_path") or extract.get("source_session_path"),
                "from_turn": extract.get("from_turn"),
                "to_turn": spec.get("to_turn") or extract.get("to_turn"),
                "user_turn_count": spec.get("user_turn_count"),
                "batch_size": spec.get("batch_size", 10),
                "auto_continue": spec.get("auto_continue", True),
                "auto_close_reading": spec.get("auto_close_reading", True),
                "approx_lines": extract.get("approx_lines"),
                "turn_count": len(extract.get("turns", [])),
                "close_reading_appended": close_appended,
                "summary_appended": summary_appended,
            }
        )
        status = "pass"
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        reading["error"] = str(exc)

    summary = {
        **lease,
        "finished_at": utc_now(),
        "status": status,
        "phase": task.phase,
        "task_path": str(task.path),
        "session_close_reading": reading,
        "checks": [],
        "guard_summary": {},
        "context_pressure": {},
        "persistence": {"mysql": {"status": "skipped"}, "redis": {"status": "skipped"}},
    }
    context_path = write_session_close_reading_context(task, run_dir, summary)
    summary["context_path"] = str(context_path)
    evidence_path, state_path, deep_marks_path, evidence, state, deep_marks = write_session_close_reading_evidence_and_state(
        task, run_dir, summary, context_path
    )
    summary["evidence_path"] = str(evidence_path)
    summary["state_path"] = str(state_path)
    summary["deep_marks_path"] = str(deep_marks_path)
    summary["evidence_count"] = len(evidence)
    summary["deep_mark_count"] = len(deep_marks)
    summary["checkpoint_id"] = state["checkpoint_id"]
    flow_transition = transition_managed_flow(
        flow_id=str(reading.get("flow_id") or ""),
        expected_revision=reading.get("flow_expected_revision"),
        expected_last_seq=reading.get("flow_expected_last_seq"),
        sequence=reading.get("flow_sequence"),
        next_status="close_read" if status == "pass" else "close_read_failed",
        actor="a9_supervisor",
        reason=f"{task.phase}:{status}",
        evidence_id=summary["checkpoint_id"],
    )
    summary["flow_transition"] = flow_transition
    if flow_transition.get("revision") is not None:
        reading["flow_revision"] = flow_transition["revision"]
    elif reading.get("flow_expected_revision") is not None:
        reading["flow_revision"] = reading.get("flow_expected_revision")
    if flow_transition.get("last_seq") is not None:
        reading["flow_last_seq"] = flow_transition["last_seq"]
        try:
            reading["flow_next_seq"] = int(flow_transition["last_seq"]) + 1
        except (TypeError, ValueError):
            reading["flow_next_seq"] = ""
    write_json(run_dir / "summary.json", summary)

    done_path = DONE_DIR / f"{task_ref}.json"
    write_json(done_path, summary)
    lease_path.unlink(missing_ok=True)
    target_task_path = DONE_DIR / task.path.name
    if task.path.exists():
        shutil.move(str(task.path), str(target_task_path))
    next_task_path = schedule_next_task(task, summary) if auto_next else None
    print(f"{task.task_id}: {status}")
    print(f"run: {run_dir}")
    print_service_progress(service_progress(summary, next_task_path))
    return 0 if status in {"pass", "needs-repair"} else 1


def run_one(*, auto_next: bool = False) -> int:
    ensure_dirs()
    task = claim_next_task()
    if not task:
        print("No queued tasks.")
        print_service_progress(service_progress())
        return 0
    if task.phase == SESSION_REFRESH_PHASE:
        return run_session_refresh_task(task, auto_next=auto_next)
    if task.phase == SESSION_CLOSE_READING_PHASE:
        return run_session_close_reading_task(task, auto_next=auto_next)

    attempt = 1
    while attempt <= task.max_attempts:
        run_id = run_id_for_task(task.task_id, attempt)
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True)
        workspace_root = task_workspace_root(task)
        worktree = create_worktree(task, attempt)
        lease = {
            "task_id": task.task_id,
            "attempt": attempt,
            "started_at": utc_now(),
            "run_dir": str(run_dir),
            "worktree": str(worktree),
            "workspace_root": str(workspace_root),
            "repo_head": git_head_for_workspace(workspace_root),
            "parent_checkpoint_id": previous_task_checkpoint_id(task),
        }
        task_ref = artifact_task_ref(task.task_id)
        lease_path = RUNNING_DIR / f"{task_ref}.json"
        write_json(lease_path, lease)

        worker = run_worker(task, worktree, run_dir, lease_path=lease_path)
        worker_envelope = validate_worker_envelope(task, worker, run_dir)
        patch_apply = apply_worker_search_replace(worker, worktree, run_dir, workspace_root)
        diff = capture_diff(worktree, run_dir)
        patch_guard = validate_captured_diff(diff, worktree, run_dir)
        scope_guard = validate_scope(diff, task, run_dir)
        process_governance = classify_process_governance(task, worker, run_dir)
        worker_failure = classify_worker_failure(worker)
        transport_observation = classify_transport_observation(worker)
        if worker_failure_short_circuits_checks(worker_failure):
            checks = []
            status = str(worker_failure["status"])
        else:
            checks = run_checks(task, worktree, run_dir)
            status = decide_status(
                worker,
                diff,
                checks,
                patch_guard,
                scope_guard,
                patch_apply,
                worker_envelope,
                process_governance,
                allow_no_diff=task_allows_no_diff(task),
            )
        worker_envelope_check_conflict = reconcile_worker_envelope_check_conflict(
            worker_envelope,
            checks,
            patch_apply=patch_apply,
            patch_guard=patch_guard,
            scope_guard=scope_guard,
            process_governance=process_governance,
        )
        if status == "needs-repair" and worker_envelope_check_conflict:
            status = "pass"
        monitor_score = create_monitor_score(run_dir)
        monitor_block = monitor_block_summary(monitor_score)
        status, monitor_block = reconcile_status_with_monitor_block(
        status,
        monitor_block,
        worker_envelope_check_conflict=worker_envelope_check_conflict,
        worker_envelope=worker_envelope,
    )
        git_governance = apply_git_governance(worktree, run_dir, task, status, diff)
        summary = {
            **lease,
            "finished_at": utc_now(),
            "status": status,
            "phase": task.phase,
            "task_path": str(task.path),
            "worker": worker,
            "worker_failure": worker_failure,
            "worker_envelope": worker_envelope,
            "patch_apply": patch_apply,
            "diff": diff,
            "patch_guard": patch_guard,
            "scope_guard": scope_guard,
            "process_governance": process_governance,
            "transport_observation": transport_observation,
            "worker_envelope_check_conflict": worker_envelope_check_conflict,
            "monitor_score": monitor_score,
            "monitor_block": monitor_block,
            "git_governance": git_governance,
            "checks": checks,
        }
        summary["worker_output"] = worker_output_from_summary(summary)
        summary["policy_attestation"] = create_policy_attestation(task, run_dir, summary)
        write_json(run_dir / "summary.json", summary)
        summary["context_pressure"] = compact_context_pressure(summary)
        summary["worker_cost_risk"] = worker_cost_risk(summary)
        summary["worker_transport_health"] = update_worker_transport_health_from_summary(summary)
        summary["guard_summary"] = compact_guard_summary(summary)
        context_path = write_context_summary(task, run_dir, summary)
        summary["context_path"] = str(context_path)
        summary["goal_state"] = update_goal_from_summary(task, run_dir, summary)
        summary["eval_store_record"] = write_eval_store_record(task, run_dir, summary)
        evidence_path, state_path, deep_marks_path, evidence, state, deep_marks = write_evidence_and_state(
            task, run_dir, summary, context_path
        )
        summary["evidence_path"] = str(evidence_path)
        summary["state_path"] = str(state_path)
        summary["deep_marks_path"] = str(deep_marks_path)
        write_runtime_monitor_contract_artifact(task, run_dir, summary)
        summary["persistence"] = persist_run_state(task, summary, evidence, state, deep_marks)
        task_flow = parse_task_flow_spec(task.prompt)
        if status == "needs-approval":
            flow_transition = set_managed_flow_wait(
                flow_id=str(task_flow.get("flow_id") or ""),
                expected_revision=task_flow.get("flow_expected_revision"),
                worker_envelope=worker_envelope,
                policy_attestation=summary["policy_attestation"],
                actor="a9_supervisor",
                evidence_id=state["checkpoint_id"],
            )
        else:
            policy_hash = str(summary["policy_attestation"].get("attestation_hash") or "")
            reason = f"{task.phase}:{status}"
            if policy_hash:
                reason = f"{reason}:policy:{policy_hash[:12]}"
            flow_transition = transition_managed_flow(
                flow_id=str(task_flow.get("flow_id") or ""),
                expected_revision=task_flow.get("flow_expected_revision"),
                expected_last_seq=task_flow.get("flow_expected_last_seq"),
                sequence=task_flow.get("flow_sequence"),
                next_status=flow_status_for_task(task.phase, status),
                actor="a9_supervisor",
                reason=reason,
                evidence_id=state["checkpoint_id"],
            )
        summary["flow_transition"] = flow_transition
        summary["auto_loop_guard"] = update_auto_loop_guard(summary)
        summary["active_plan_update"] = update_active_plan_from_run(task, run_dir, summary)
        write_json(run_dir / "summary.json", summary)

        retryable = status.startswith("retryable-")
        if retryable and attempt < task.max_attempts:
            attempt += 1
            continue

        done_path = DONE_DIR / f"{task_ref}.json"
        write_json(done_path, summary)
        lease_path.unlink(missing_ok=True)
        target_task_path = DONE_DIR / task.path.name
        if task.path.exists():
            shutil.move(str(task.path), str(target_task_path))
        next_task_path = schedule_next_task(task, summary) if auto_next else None
        summary["next_task_path"] = str(next_task_path) if next_task_path else ""
        if auto_next:
            write_json(run_dir / "summary.json", summary)
            write_json(done_path, summary)
        print(f"{task.task_id}: {status}")
        print(f"run: {run_dir}")
        print_service_progress(service_progress(summary, next_task_path))
        return 0 if status in {"pass", "needs-followup", "needs-repair", "needs-approval"} else 1

    return 1


@contextlib.contextmanager
def acquire_run_loop_lock() -> Any:
    ensure_dirs()
    RUN_LOOP_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = RUN_LOOP_LOCK_PATH.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            owner_text = handle.read().strip()
            owner: dict[str, Any] = {}
            if owner_text:
                try:
                    owner = json.loads(owner_text)
                except json.JSONDecodeError:
                    owner = {"raw": owner_text}
            yield {
                "schema": "a9.run_loop_lock.v1",
                "status": "already_locked",
                "lock_path": str(RUN_LOOP_LOCK_PATH),
                "owner_pid": owner.get("pid"),
                "owner_started_at": owner.get("started_at"),
            }
            return
        owner = {
            "schema": "a9.run_loop_lock.v1",
            "pid": os.getpid(),
            "started_at": utc_now(),
        }
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(owner, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        yield {"schema": "a9.run_loop_lock.v1", "status": "acquired", "lock_path": str(RUN_LOOP_LOCK_PATH), **owner}
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def run_loop(args: argparse.Namespace) -> int:
    with acquire_run_loop_lock() as lock:
        if lock.get("status") != "acquired":
            print(json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True))
            write_daemon_heartbeat("owner-exists", detail=str(lock.get("owner_pid") or ""))
            return 0
        return run_loop_locked(args)


def run_loop_locked(args: argparse.Namespace) -> int:
    ensure_dirs()
    completed = 0
    while True:
        reconcile_orphaned_running_tasks()
        write_daemon_heartbeat("polling", detail=f"completed={completed}")
        pause_gate = runtime_control_blocks_claim()
        if pause_gate:
            detail = str(pause_gate.get("reason") or "monitor_intervention_pause")
            write_daemon_heartbeat("paused", detail=detail)
            if args.max_tasks and completed >= args.max_tasks:
                return 0
            time.sleep(args.sleep_seconds)
            continue
        task = next_task()
        if not task:
            if args.auto_next:
                next_lane_task = schedule_idle_lane_continuation()
                if next_lane_task:
                    lane, next_task_path = next_lane_task
                    write_daemon_heartbeat(lane, detail=str(next_task_path))
                    task = next_task()
        if not task:
            write_daemon_heartbeat("idle", detail="no queued tasks")
            print("No queued tasks.")
            if getattr(args, "exit_when_idle", False) or (args.max_tasks and completed >= args.max_tasks):
                return 0
            time.sleep(args.sleep_seconds)
            continue
        worker_transport = resolved_worker_transport(task)
        transport_gate = worker_transport_cooldown_gate(
            requested_backend=str(worker_transport.get("backend") or "")
        )
        if transport_gate:
            detail = (
                f"{transport_gate.get('reason')} until={transport_gate.get('cooldown_until')} "
                f"consecutive_failures={transport_gate.get('consecutive_failures')}"
            )
            write_daemon_heartbeat("transport-cooldown", detail=detail)
            print(f"Worker transport cooldown: {detail}")
            if args.max_tasks and completed >= args.max_tasks:
                return 0
            time.sleep(args.sleep_seconds)
            continue
        write_daemon_heartbeat("running", detail=task.task_id)
        code = run_one(auto_next=args.auto_next)
        completed += 1
        write_daemon_heartbeat("sleeping", detail=f"last_code={code}")
        if code != 0 and not args.keep_going_on_error:
            return code
        if args.auto_next and auto_loop_guard_blocks_next():
            write_daemon_heartbeat("guard-tripped", detail="auto-loop failure limit reached")
            print("Auto-loop guard tripped; stopping run-loop.")
            return code if code != 0 else 1
        if args.max_tasks and completed >= args.max_tasks:
            return code
        time.sleep(args.sleep_seconds)


def enqueue(args: argparse.Namespace) -> int:
    path = enqueue_task_file(
        args.task_id,
        args.prompt,
        phase=args.phase,
        checks=args.check,
        timeout_seconds=args.timeout_seconds,
        idle_timeout_seconds=args.idle_timeout_seconds,
        max_attempts=args.max_attempts,
        allowed_paths=args.allow_path,
        auto_next=not args.no_auto_next,
        workspace_root=args.workspace_root,
    )
    print(path)
    return 0


def plan_create(args: argparse.Namespace) -> int:
    ensure_dirs()
    problem = str(args.problem or "").strip()
    if not problem:
        raise SystemExit("plan-create requires --problem")
    goal_objective = str(args.goal_objective or problem).strip()
    goal_id = str(args.goal_id or "").strip() or goal_id_for_objective(goal_objective)
    goal = load_goal(goal_id)
    if not goal:
        goal = create_goal_payload(goal_id, goal_objective, args.goal_token_budget)
        write_goal(goal)
    elif args.goal_token_budget is not None:
        goal["token_budget"] = args.goal_token_budget
        write_goal(goal)
    plan_id = str(args.plan_id or "").strip() or plan_id_for_problem(problem)
    contract = {
        "problem": problem,
        "why_now": str(args.why_now or "").strip(),
        "must": str(args.must or "").strip(),
        "should": str(args.should or "").strip(),
        "could": str(args.could or "").strip(),
        "system_requirement": str(args.system_requirement or "").strip(),
        "solution_type": str(args.solution_type or "runtime_infra").strip(),
        "data_shape": str(args.data_shape or "").strip(),
        "normal_flow": str(args.normal_flow or "").strip(),
        "exception_flow": str(args.exception_flow or "").strip(),
        "acceptance": str(args.acceptance or "").strip(),
        "out_of_scope": str(args.out_of_scope or "").strip(),
        "reference_entry": str(args.reference_entry or "").strip(),
        "change_record": str(args.change_record or "").strip(),
        "allowed_execution": str(args.allowed_execution or "").strip(),
    }
    plan = create_plan_payload(
        plan_id=plan_id,
        goal_id=goal_id,
        flow_id=str(args.flow_id or "").strip(),
        expected_flow_revision=args.expected_flow_revision,
        source="a9_supervisor_plan_create",
        contract=contract,
    )
    plan_dir = write_plan_files(plan, activate=not args.no_activate)
    print(plan_dir)
    return 0


def plan_status(args: argparse.Namespace) -> int:
    ensure_dirs()
    plan_id = str(args.plan_id or "").strip() or active_plan_id()
    if not plan_id:
        print("No active plan.")
        return 1
    plan = load_plan(plan_id)
    if not plan:
        print(f"Plan not found: {plan_id}")
        return 1
    contract = plan.get("contract", {}) if isinstance(plan.get("contract"), dict) else {}
    print(f"plan_id: {plan.get('plan_id', '')}")
    print(f"status: {plan.get('status', '')}")
    print(f"goal_id: {plan.get('goal_id', '')}")
    print(f"flow_id: {plan.get('flow_id', '')}")
    print(f"expected_flow_revision: {plan.get('expected_flow_revision', '')}")
    run_ids = plan.get("run_ids", []) if isinstance(plan.get("run_ids"), list) else []
    evidence_refs = plan.get("evidence_refs", []) if isinstance(plan.get("evidence_refs"), list) else []
    print(f"run_ids_count: {len(run_ids)}")
    latest_run_id = latest_plan_run_id(plan)
    if latest_run_id:
        print(f"latest_run_id: {bounded_inline(latest_run_id, 260)}")
    print(f"evidence_refs_count: {len(evidence_refs)}")
    latest_evidence = latest_plan_evidence_ref(plan)
    if latest_evidence:
        print(f"latest_evidence_ref: {bounded_inline(latest_evidence, 260)}")
    plan_dir = plan_path(str(plan.get("plan_id", "")))
    print(f"plan_dir: {plan_dir}")
    print(f"problem: {bounded_inline(contract.get('problem', ''), 260)}")
    print(f"must: {bounded_inline(contract.get('must', ''), 260)}")
    print(f"should: {bounded_inline(contract.get('should', ''), 260)}")
    print(f"could: {bounded_inline(contract.get('could', ''), 260)}")
    print(f"system_requirement: {bounded_inline(contract.get('system_requirement', ''), 260)}")
    print(f"data_shape: {bounded_inline(contract.get('data_shape', ''), 260)}")
    print(f"acceptance: {bounded_inline(contract.get('acceptance', ''), 260)}")
    debate = requirements_debate_progress(plan)
    missing = debate.get("missing_fields", [])
    print(f"requirements_debate_status: {debate.get('status', '')}")
    print(f"requirements_debate_current_stage: {debate.get('current_stage', '')}")
    print(f"requirements_debate_missing_fields: {', '.join(str(item) for item in missing) if isinstance(missing, list) else ''}")
    backlog = execution_backlog_state(plan)
    backlog_items = backlog.get("items", [])
    if not isinstance(backlog_items, list):
        backlog_items = []
    ready_count = 0
    queued_count = 0
    latest_queued_task_id = ""
    for item in backlog_items:
        if not isinstance(item, dict):
            continue
        item_status = str(item.get("status") or "ready").strip().lower()
        if item_status in {"", "ready", "pending"}:
            ready_count += 1
        if item_status == "queued":
            queued_count += 1
            queued_task_id = str(item.get("queued_task_id") or "").strip()
            if queued_task_id:
                latest_queued_task_id = queued_task_id
    generated_task_ids = backlog.get("generated_task_ids", [])
    if not isinstance(generated_task_ids, list):
        generated_task_ids = []
    print(f"execution_backlog_item_count: {len(backlog_items)}")
    print(f"execution_backlog_ready_count: {ready_count}")
    print(f"execution_backlog_queued_count: {queued_count}")
    print(f"execution_backlog_generated_task_ids_count: {len(generated_task_ids)}")
    if latest_queued_task_id:
        print(f"execution_backlog_latest_queued_task_id: {latest_queued_task_id}")
    last_progress = tail_recovery_line(plan_dir / "progress.md")
    last_findings = tail_recovery_line(plan_dir / "findings.md")
    last_mistake = tail_recovery_line(plan_dir / "mistakes.md")
    last_change_request = tail_change_request_line(plan_dir / "change_request.md")
    open_change_request = latest_plan_change_request(plan)
    latest_run = plan_latest_run_snapshot(plan)
    print(f"last_progress: {last_progress}")
    print(f"last_findings: {last_findings}")
    print(f"last_mistake: {last_mistake}")
    print(f"last_change_request: {last_change_request}")
    print(f"open_change_request: {open_change_request or 'none'}")
    print(f"latest_run_summary: {latest_run.get('summary_path', '')}")
    print(f"latest_run_phase: {latest_run.get('phase', '')}")
    print(f"latest_run_status: {latest_run.get('status', '')}")
    print("recovery_restatement:")
    print("- current_goal: read goal object, not plan status, for long-term completion.")
    print("- current_plan: use plan as task contract and prompt hydration view.")
    print("- plan_evidence_source: active plan contract + latest run summary + findings/progress/mistakes/change_request tails.")
    print(f"- reference_basis: {bounded_inline(contract.get('reference_entry', ''), 260)}")
    current_phase = latest_run.get("phase", "") or "unknown"
    print(f"- current_phase: {current_phase}")
    print(
        "- happened_since_last_action: reconcile latest progress/findings/mistakes/change_request "
        "before any new worker action."
    )
    print("- next_action: continue only after reconciling plan with goal/flow/run evidence.")
    print("- why_next_action: keeps continuation/handoff based on durable runtime evidence instead of chat memory.")
    print(f"- not_doing_now: {bounded_inline(contract.get('out_of_scope', ''), 260)}")
    print("- out_of_scope: do not let worker mutate contract fields; use change_request.")
    return 0


def plan_debate_next(args: argparse.Namespace) -> int:
    ensure_dirs()
    plan_id = str(args.plan_id or "").strip() or active_plan_id()
    if not plan_id:
        print("No active plan.")
        return 1
    plan = load_plan(plan_id)
    if not plan:
        print(f"Plan not found: {plan_id}")
        return 1
    path, debate = enqueue_plan_debate_task(
        plan,
        stage_id=str(args.stage or "").strip(),
        task_id=str(args.task_id or "").strip(),
        extra=str(args.extra or "").strip(),
        phase=str(args.phase or "reference_scan"),
        timeout_seconds=args.timeout_seconds,
        idle_timeout_seconds=args.idle_timeout_seconds,
        auto_next=bool(args.allow_auto_next),
    )
    print(path)
    print(f"requirements_debate_status: {debate.get('status', '')}")
    print(f"requirements_debate_current_stage: {debate.get('current_stage', '')}")
    print(f"task_auto_next: {str(bool(args.allow_auto_next)).lower()}")
    return 0


EXECUTION_BACKLOG_PHASES: tuple[tuple[str, str], ...] = (
    ("reference_scan", "Re-check the exact reference mechanisms for this decided slice before implementation."),
    ("mechanism_extract", "Extract the concrete mechanism, contracts, failure modes, and A9 adaptation plan."),
)


def extract_allowed_paths_from_execution_text(text: str) -> list[str]:
    file_re = re.compile(r"[\w./-]+\.(?:py|rs|ts|tsx|js|jsx|md|toml|yml|yaml|sql|json|sh)")
    paths: list[str] = []
    for match in file_re.finditer(str(text or "")):
        candidate = match.group(0).strip().strip(".,;:")
        if candidate.startswith("/"):
            continue
        if candidate.startswith(".a9/") or candidate.startswith("vendor-src/"):
            continue
        if candidate not in paths:
            paths.append(candidate)
    return paths


def merge_unique_paths(*groups: list[str]) -> list[str]:
    paths: list[str] = []
    for group in groups:
        for path in group:
            item = str(path).strip()
            if item and item not in paths:
                paths.append(item)
    return paths


REQUIREMENTS_DEBATE_READ_PATHS = ["docs/project.md", "docs/method.md"]


def plan_bounded_read_paths(plan_id: str, contract_paths: list[str] | None = None) -> list[str]:
    plan_paths = [
        str(plan_path(plan_id) / "plan.json"),
        str(plan_path(plan_id) / "progress.md"),
        str(plan_path(plan_id) / "change_request.md"),
        str(plan_path(plan_id) / "findings.md"),
        str(plan_path(plan_id) / "mistakes.md"),
    ] if plan_id else []
    return merge_unique_paths(REQUIREMENTS_DEBATE_READ_PATHS, plan_paths, contract_paths or [])


def execution_backlog_state(plan: dict[str, Any]) -> dict[str, Any]:
    backlog = plan.get("execution_backlog")
    if not isinstance(backlog, dict):
        backlog = default_execution_backlog_state()
        plan["execution_backlog"] = backlog
    if not isinstance(backlog.get("items"), list):
        backlog["items"] = []
    if not isinstance(backlog.get("generated_task_ids"), list):
        backlog["generated_task_ids"] = []
    if not backlog.get("schema"):
        backlog["schema"] = "a9.execution_backlog.v1"
    return backlog


def normalize_execution_backlog_item(raw: dict[str, Any], *, index: int, plan: dict[str, Any]) -> dict[str, Any]:
    contract = plan.get("contract", {}) if isinstance(plan.get("contract"), dict) else {}
    phase = str(raw.get("phase") or "implement").strip() or "implement"
    backlog_id = str(raw.get("id") or raw.get("backlog_id") or raw.get("task_id") or "").strip()
    if not backlog_id:
        title_for_id = str(raw.get("title") or raw.get("objective") or phase or "execution")
        backlog_id = f"backlog-{index:03d}-{slugify(title_for_id)[:40]}"
    task_id = str(raw.get("task_id") or "").strip()
    if not task_id:
        task_id = f"exec-{index:03d}-{phase}-{compact_task_ref(backlog_id, limit=40)}"
    allowed_paths: list[str] = []
    if isinstance(raw.get("allowed_paths"), list):
        allowed_paths = [str(path).strip() for path in raw["allowed_paths"] if str(path).strip()]
    if not allowed_paths:
        allowed_paths = extract_allowed_paths_from_execution_text(str(raw.get("allowed_execution") or ""))
    if not allowed_paths:
        allowed_paths = extract_allowed_paths_from_execution_text(str(contract.get("allowed_execution") or ""))
    checks = [str(check).strip() for check in raw.get("checks", []) if str(check).strip()] if isinstance(raw.get("checks"), list) else []
    read_commands = execution_backlog_read_commands(raw)
    if not read_commands:
        read_commands = default_bounded_read_commands_for_paths(allowed_paths)
    title = str(raw.get("title") or raw.get("objective") or phase).strip()
    objective = str(raw.get("objective") or raw.get("prompt") or title).strip()
    prompt_body = str(raw.get("prompt") or objective).strip()
    acceptance = str(raw.get("acceptance") or contract.get("acceptance") or "").strip()
    allowed_execution_text = str(raw.get("allowed_execution") or contract.get("allowed_execution") or "").strip()
    bounded_read_lines = [f"bounded read: {path}" for path in allowed_paths[:8]]
    prompt = "\n".join(
        [
            "decision_status: decided",
            "route: execution_next",
            f"plan_id: {plan.get('plan_id', '')}",
            f"goal_id: {plan.get('goal_id', '')}",
            f"problem: {contract.get('problem', '')}",
            f"system_requirement: {contract.get('system_requirement', '')}",
            f"data_contract: {contract.get('data_shape', '')}",
            f"state_flow: {contract.get('normal_flow', '')}",
            f"exception_flow: {contract.get('exception_flow', '')}",
            f"acceptance: {acceptance}",
            f"out_of_scope: {contract.get('out_of_scope', '')}",
            f"allowed_execution: {allowed_execution_text}",
            *bounded_read_lines,
            f"change_record: {contract.get('change_record', '') or 'Generated from requirements debate ready_for_execution_backlog.'}",
            "role_signoff: requirements debate pipeline reached ready_for_execution_backlog.",
            f"execution_backlog_id: {backlog_id}",
            f"execution_backlog_index: {index}",
            f"execution_backlog_phase: {phase}",
            f"execution_backlog_title: {title}",
            "",
            "Execution slice:",
            prompt_body,
            "",
            "Rules:",
            "- Execute only this bounded slice.",
            "- Before reading source, use only the exact read_commands/anchors supplied in this task packet.",
            "- Use reference-first copying where the slice requires it.",
            "- live_read_budget_policy: stop.",
            "- Read only bounded slices from allowed_paths; do not cd to /root/a9 or search broad roots.",
            "- Use capped `rg -n -m 20` or `rg ... | head -n 40`; never run uncapped rg in read-heavy phases.",
            "- Keep each `sed -n` source window <= 120 lines and total requested source lines <= 180.",
            "- Do not search `.a9` roots; use exact evidence paths already provided in the prompt.",
            "- Do not change product scope, data contract, state flow, acceptance, or out_of_scope.",
            "- If the contract is wrong, append a plan change_request instead of silently changing it.",
            "",
            "Bounded read commands:",
            *(f"- {command}" for command in read_commands[:8]),
        ]
    )
    return {
        "backlog_id": backlog_id,
        "task_id": task_id,
        "phase": phase,
        "prompt": prompt,
        "allowed_paths": allowed_paths,
        "checks": checks,
        "source": "plan.execution_backlog.items",
        "status": str(raw.get("status") or "ready").strip() or "ready",
    }


def execution_backlog_task_was_generated(task_id: str, generated_task_ids: set[str]) -> bool:
    normalized = str(task_id or "").strip()
    if not normalized:
        return False
    return any(generated == normalized or generated.endswith(f"-{normalized}") for generated in generated_task_ids)


def plan_change_request_continuation_item(
    plan: dict[str, Any],
    *,
    generated_task_ids: set[str],
) -> dict[str, Any] | None:
    change_request = latest_plan_change_request(plan)
    if not change_request:
        return None
    plan_ref = compact_task_ref(str(plan.get("plan_id") or "plan"), limit=48)
    task_id = f"exec-change-request-review-{plan_ref}"
    if execution_backlog_task_was_generated(task_id, generated_task_ids):
        return None
    contract = plan.get("contract", {}) if isinstance(plan.get("contract"), dict) else {}
    allowed_paths = extract_allowed_paths_from_execution_text(str(contract.get("allowed_execution") or ""))
    bounded_read_paths = plan_bounded_read_paths(str(plan.get("plan_id") or ""), allowed_paths)
    bounded_read_lines = [f"bounded read: {path}" for path in bounded_read_paths[:8]]
    prompt = "\n".join(
        [
            "decision_status: debate_next",
            "route: debate_next",
            f"plan_id: {plan.get('plan_id', '')}",
            f"goal_id: {plan.get('goal_id', '')}",
            f"problem: {contract.get('problem', '')}",
            f"system_requirement: {contract.get('system_requirement', '')}",
            f"data_contract: {contract.get('data_shape', '')}",
            f"state_flow: {contract.get('normal_flow', '')}",
            f"exception_flow: {contract.get('exception_flow', '')}",
            f"acceptance: {contract.get('acceptance', '')}",
            f"out_of_scope: {contract.get('out_of_scope', '')}",
            f"allowed_execution: {contract.get('allowed_execution', '')}",
            *bounded_read_lines,
            "role_signoff: active plan has no ready backlog; change_request requires shaping before execution.",
            "execution_backlog_id: change_request_review",
            "execution_backlog_phase: mechanism_extract",
            "execution_backlog_title: Convert latest change_request into decided execution backlog candidates",
            "",
            "Latest change_request:",
            change_request,
            "",
            "Execution slice:",
            "Reference-scan existing planning/backlog/auto-next tests, then produce a bounded mechanism_extract result. "
            "If the change_request is already satisfied, say so with evidence. If work remains, output proposed "
            "execution_backlog items or a more specific plan change_request; do not implement production changes in this slice.",
            "",
            "Rules:",
            "- Treat this as requirements/debate shaping, not direct implementation.",
            "- Use reference-first copying where the slice requires it.",
            "- Do not change product scope, data contract, state flow, acceptance, or out_of_scope.",
            "- If the contract is wrong, append a plan change_request instead of silently changing it.",
        ]
    )
    return {
        "backlog_id": "change_request_review",
        "task_id": task_id,
        "phase": "mechanism_extract",
        "prompt": prompt,
        "allowed_paths": bounded_read_paths,
        "checks": [],
        "source": "plan.change_request",
        "status": "ready",
    }


def latest_backlog_generation_summary(plan_ref: str) -> dict[str, Any]:
    prefix = f"exec-backlog-generation-{plan_ref}-"
    summaries: list[tuple[float, dict[str, Any]]] = []
    for summary_path in RUNS_DIR.glob("*/summary.json"):
        try:
            mtime = summary_path.stat().st_mtime
        except OSError:
            continue
        data = read_json_file(summary_path)
        if not data:
            continue
        task_id = str(data.get("task_id") or "")
        if prefix not in task_id:
            continue
        summaries.append((mtime, data))
    if not summaries:
        return {}
    summaries.sort(key=lambda item: item[0], reverse=True)
    return summaries[0][1]


def backlog_generation_retryable_budget_summary(summary: dict[str, Any]) -> bool:
    status = str(summary.get("status") or "")
    worker_failure = summary.get("worker_failure") if isinstance(summary.get("worker_failure"), dict) else {}
    return status == "retryable-worker-budget" or worker_failure.get("category") == "budget"


def backlog_generation_retryable_interrupted_summary(summary: dict[str, Any]) -> bool:
    status = str(summary.get("status") or "")
    worker_failure = summary.get("worker_failure") if isinstance(summary.get("worker_failure"), dict) else {}
    return (
        status == "retryable-worker-interrupted"
        and worker_failure.get("category") == "interrupted"
        and worker_failure.get("reason") == "no_live_worker_process"
    )


def backlog_generation_retryable_timeout_summary(summary: dict[str, Any]) -> bool:
    status = str(summary.get("status") or "")
    worker_failure = summary.get("worker_failure") if isinstance(summary.get("worker_failure"), dict) else {}
    return status == "retryable-timeout" or worker_failure.get("category") == "timeout"


def backlog_generation_needs_retry_after_code_update(summary: dict[str, Any]) -> bool:
    status = str(summary.get("status") or "")
    if status not in {"needs-followup", "needs-repair", "retryable-worker-budget", "retryable-timeout"}:
        return False
    summary_head = str(summary.get("repo_head") or "").strip()
    if not summary_head:
        return False
    try:
        current_head = git_head()
    except RuntimeError:
        return False
    return bool(current_head and current_head != summary_head)


def backlog_generation_has_monitor_closure_after_summary(plan: dict[str, Any], summary: dict[str, Any]) -> bool:
    status = str(summary.get("status") or "")
    if status != "needs-followup":
        return False
    plan_dir = PLANS_DIR / str(plan.get("plan_id") or "")
    progress_path = plan_dir / "progress.md"
    change_request_path = plan_dir / "change_request.md"
    summary_path = Path(str(summary.get("run_dir") or "")) / "summary.json"
    try:
        summary_mtime = summary_path.stat().st_mtime
    except OSError:
        summary_mtime = 0.0
    for path in (progress_path, change_request_path):
        try:
            if path.stat().st_mtime <= summary_mtime:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")[-4000:]
        except OSError:
            continue
        if "monitor_closure" in text and "approved next backlog-generation" in text:
            return True
    return False


def backlog_generation_retryable_budget_count(plan_ref: str) -> int:
    prefix = f"exec-backlog-generation-{plan_ref}-"
    count = 0
    for summary_path in RUNS_DIR.glob("*/summary.json"):
        data = read_json_file(summary_path)
        if not data:
            continue
        task_id = str(data.get("task_id") or "")
        if prefix not in task_id:
            continue
        if backlog_generation_retryable_budget_summary(data):
            count += 1
    return count


def backlog_generation_consecutive_retryable_interrupted_count(plan_ref: str) -> int:
    prefix = f"exec-backlog-generation-{plan_ref}-"
    summaries: list[tuple[float, dict[str, Any]]] = []
    for summary_path in RUNS_DIR.glob("*/summary.json"):
        try:
            mtime = summary_path.stat().st_mtime
        except OSError:
            continue
        data = read_json_file(summary_path)
        if not data:
            continue
        task_id = str(data.get("task_id") or "")
        if prefix not in task_id:
            continue
        summaries.append((mtime, data))
    summaries.sort(key=lambda item: item[0], reverse=True)
    count = 0
    for _, summary in summaries:
        if not backlog_generation_retryable_interrupted_summary(summary):
            break
        count += 1
    return count


def backlog_generation_consecutive_retryable_timeout_count(plan_ref: str) -> int:
    prefix = f"exec-backlog-generation-{plan_ref}-"
    summaries: list[tuple[float, dict[str, Any]]] = []
    for summary_path in RUNS_DIR.glob("*/summary.json"):
        try:
            mtime = summary_path.stat().st_mtime
        except OSError:
            continue
        data = read_json_file(summary_path)
        if not data:
            continue
        task_id = str(data.get("task_id") or "")
        if prefix not in task_id:
            continue
        summaries.append((mtime, data))
    summaries.sort(key=lambda item: item[0], reverse=True)
    count = 0
    for _, summary in summaries:
        if not backlog_generation_retryable_timeout_summary(summary):
            break
        count += 1
    return count


def backlog_generation_can_continue(plan_ref: str, generated_task_ids: set[str], *, plan: dict[str, Any] | None = None) -> bool:
    prefix = f"exec-backlog-generation-{plan_ref}-"
    if not any(prefix in str(task_id) for task_id in generated_task_ids):
        return True
    summary = latest_backlog_generation_summary(plan_ref)
    if not summary:
        return False
    if backlog_generation_retryable_budget_summary(summary):
        if backlog_generation_needs_retry_after_code_update(summary):
            return True
        return backlog_generation_retryable_budget_count(plan_ref) < 3
    if backlog_generation_retryable_interrupted_summary(summary):
        return backlog_generation_consecutive_retryable_interrupted_count(plan_ref) < 3
    if backlog_generation_retryable_timeout_summary(summary):
        return backlog_generation_consecutive_retryable_timeout_count(plan_ref) < 3
    if backlog_generation_needs_retry_after_code_update(summary):
        return True
    if plan is not None and backlog_generation_has_monitor_closure_after_summary(plan, summary):
        return True
    if str(summary.get("status") or "") != "pass":
        return False
    plan_update = summary.get("active_plan_update", {})
    if not isinstance(plan_update, dict):
        return False
    backlog_update = plan_update.get("execution_backlog_update", {})
    if not isinstance(backlog_update, dict):
        return False
    return str(backlog_update.get("status") or "") == "appended" and int(backlog_update.get("added_count") or 0) > 0


def plan_backlog_generation_continuation_item(
    plan: dict[str, Any],
    *,
    generated_task_ids: set[str],
) -> dict[str, Any] | None:
    contract = plan.get("contract", {}) if isinstance(plan.get("contract"), dict) else {}
    allowed_paths = extract_allowed_paths_from_execution_text(str(contract.get("allowed_execution") or ""))
    plan_ref = compact_task_ref(str(plan.get("plan_id") or "plan"), limit=48)
    bounded_read_paths = plan_bounded_read_paths(str(plan.get("plan_id") or ""), allowed_paths)
    bounded_read_lines = [f"bounded read: {path}" for path in bounded_read_paths[:10]]
    if not backlog_generation_can_continue(plan_ref, generated_task_ids, plan=plan):
        return None
    latest_generation = latest_backlog_generation_summary(plan_ref)
    retry_budget = backlog_generation_retryable_budget_summary(latest_generation)
    retry_interrupted = backlog_generation_retryable_interrupted_summary(latest_generation)
    retry_timeout = backlog_generation_retryable_timeout_summary(latest_generation)
    retry_after_code_update = backlog_generation_needs_retry_after_code_update(latest_generation)
    retry_after_monitor_closure = backlog_generation_has_monitor_closure_after_summary(plan, latest_generation)
    retry_lines: list[str] = []
    if retry_budget:
        worker_failure = latest_generation.get("worker_failure") if isinstance(latest_generation.get("worker_failure"), dict) else {}
        process = latest_generation.get("process_governance") if isinstance(latest_generation.get("process_governance"), dict) else {}
        findings = process.get("findings") if isinstance(process.get("findings"), list) else []
        bad_paths = sorted({
            str(item.get("path") or "")
            for item in findings
            if isinstance(item, dict) and str(item.get("path") or "").strip()
        })
        retry_lines = [
            "previous_backlog_generation_status: retryable-worker-budget",
            f"previous_budget_reason: {worker_failure.get('reason', '')}",
            f"previous_forbidden_read_paths: {', '.join(bad_paths[:8])}",
            "retry_policy: generate backlog from the active plan contract and allowed bounded sources only; do not reread stale closure docs.",
            "retry_scope: use docs/project.md, docs/method.md, docs/session.md, and active plan files only.",
        ]
    elif retry_interrupted:
        worker_failure = latest_generation.get("worker_failure") if isinstance(latest_generation.get("worker_failure"), dict) else {}
        retry_lines = [
            "previous_backlog_generation_status: retryable-worker-interrupted",
            f"previous_interruption_reason: {worker_failure.get('reason', '')}",
            "retry_policy: previous worker had no live process; resume the same backlog-generation intent with bounded sources only.",
            "retry_scope: use docs/project.md, docs/method.md, docs/session.md, and active plan files only.",
        ]
    elif retry_timeout:
        worker_failure = latest_generation.get("worker_failure") if isinstance(latest_generation.get("worker_failure"), dict) else {}
        retry_lines = [
            "previous_backlog_generation_status: retryable-timeout",
            f"previous_timeout_reason: {worker_failure.get('reason', '')}",
            "retry_policy: previous worker timed out during transport/model response; retry the same backlog-generation intent with bounded sources only.",
            "retry_scope: use docs/project.md, docs/method.md, docs/session.md, and active plan files only.",
        ]
    elif retry_after_code_update:
        retry_lines = [
            f"previous_backlog_generation_status: {latest_generation.get('status', '')}",
            f"previous_repo_head: {latest_generation.get('repo_head', '')}",
            "retry_policy: previous backlog-generation result came from an older supervisor revision; rerun with current bounded plan evidence before accepting its change_request.",
            "retry_scope: use docs/project.md, docs/method.md, docs/session.md, and active plan files only.",
        ]
    elif retry_after_monitor_closure:
        retry_lines = [
            f"previous_backlog_generation_status: {latest_generation.get('status', '')}",
            "previous_followup_resolution: monitor_closure",
            "retry_policy: monitor applied review closure after previous needs-followup; generate the next compact backlog from current bounded plan evidence.",
            "retry_scope: use docs/project.md, docs/method.md, docs/session.md, and active plan files only.",
        ]
    prefix = f"exec-backlog-generation-{plan_ref}-"
    existing_rounds = [
        str(task_id)
        for task_id in generated_task_ids
        if prefix in str(task_id)
    ]
    round_no = len(existing_rounds) + 1
    task_id = f"{prefix}{round_no:03d}"
    prompt = "\n".join(
        [
            "decision_status: not_decided",
            "route: debate_next",
            f"plan_id: {plan.get('plan_id', '')}",
            f"goal_id: {plan.get('goal_id', '')}",
            "debate_stage: execution_backlog_generation",
            "debate_stage_label: Generate next execution backlog batch",
            f"problem: {contract.get('problem', '')}",
            f"system_requirement: {contract.get('system_requirement', '')}",
            f"data_contract: {contract.get('data_shape', '')}",
            f"state_flow: {contract.get('normal_flow', '')}",
            f"exception_flow: {contract.get('exception_flow', '')}",
            f"acceptance: {contract.get('acceptance', '')}",
            f"out_of_scope: {contract.get('out_of_scope', '')}",
            f"allowed_execution: {contract.get('allowed_execution', '')}",
            *bounded_read_lines,
            *retry_lines,
            "role_signoff: requirements are closed; active plan backlog is exhausted and needs the next decided batch.",
            "execution_backlog_id: execution_backlog_generation",
            "execution_backlog_phase: reference_scan",
            "execution_backlog_title: Generate next decided execution backlog batch",
            "",
            "Debate slice:",
            "Review the active plan contract, latest progress, findings, mistakes, and current repository evidence. "
            "Generate the next compact execution_next backlog batch only if the contract still supports it. "
            "Do not implement code in this task.",
            "",
            "Output requirements:",
            "- Return strict_worker_envelope JSON.",
            "- If more implementation work is justified, set output.decision_status to decided, change_request.status to none,",
            "  and include at most 3 compact output.execution_backlog.items.",
            "- Each backlog item must include title, phase, prompt, allowed_paths, read_commands, checks, and acceptance or clear validation notes.",
            "- `checks` must contain executable commands only. Put prose acceptance criteria under `acceptance` or `validation_notes`, never under `checks`.",
            "- Each backlog item read_commands must be exact bounded commands such as `rg -n -m 20 'pattern' path` or `sed -n '10,80p' path`; no broad aliases like `scripts`, `tests`, `.a9`, or `/root/a9`.",
            "- If the contract is stale or insufficient, set output.decision_status to not_decided and output.change_request.status to required.",
            "- Do not mutate plan contract fields directly; use change_request for contract changes.",
            "",
            "Rules:",
            "- This is requirements/backlog shaping, not execution.",
            "- live_read_budget_policy: stop.",
            "- Read only bounded slices from the exact read_commands you output; do not cd to /root/a9 or search broad roots.",
            "- Use capped `rg -n -m 20` or `rg ... | head -n 40`; never run uncapped rg in read-heavy phases.",
            "- Keep each `sed -n` source window <= 120 lines and total requested source lines <= 180.",
            "- Do not search `.a9` roots; use exact evidence paths already provided in the prompt.",
            "- Use reference-first copying where a next slice requires it.",
            "- Preserve data-first and performance-second acceptance.",
            "- Do not read stale closure drafts such as docs/a9-current-decision-packet.md, docs/requirements-review-closure.md, or docs/a9-24h-two-lane-review-closure.md unless they are explicitly listed in bounded read paths.",
            "- Avoid stale one-doc closure artifacts; current authority is AGENTS.md, docs/project.md, docs/method.md, docs/session.md, docs/reference.md and active plan evidence.",
        ]
    )
    return {
        "backlog_id": f"execution_backlog_generation_{round_no:03d}",
        "task_id": task_id,
        "phase": "reference_scan",
        "prompt": prompt,
        "allowed_paths": bounded_read_paths,
        "checks": [],
        "source": "plan.execution_backlog_generation",
        "status": "ready",
    }


def plan_execution_backlog_items(plan: dict[str, Any], *, count: int = 0) -> list[dict[str, Any]]:
    debate = requirements_debate_progress(plan)
    if debate.get("status") != "ready_for_execution_backlog":
        return []
    contract = plan.get("contract", {}) if isinstance(plan.get("contract"), dict) else {}
    backlog = execution_backlog_state(plan)
    generated_task_ids = {str(item) for item in backlog.get("generated_task_ids", []) if str(item).strip()}
    raw_items = [item for item in backlog.get("items", []) if isinstance(item, dict)]
    ready_items = [
        normalize_execution_backlog_item(item, index=index, plan=plan)
        for index, item in enumerate(raw_items, start=1)
        if str(item.get("status") or "ready").strip() in ("", "ready", "pending")
    ]
    if ready_items:
        return ready_items[:count] if count > 0 else ready_items
    if raw_items:
        terminal_statuses = {
            "pass",
            "passed",
            "done",
            "complete",
            "completed",
            "closed",
            "cancelled",
            "skipped",
        }
        raw_statuses = {str(item.get("status") or "").strip().lower() for item in raw_items}
        if any(status not in terminal_statuses for status in raw_statuses):
            return []
    allowed_paths = extract_allowed_paths_from_execution_text(str(contract.get("allowed_execution") or ""))
    bounded_read_lines = [f"bounded read: {path}" for path in allowed_paths[:8]]
    selected_phases = list(EXECUTION_BACKLOG_PHASES)
    plan_ref = compact_task_ref(str(plan.get("plan_id") or "plan"), limit=48)
    items: list[dict[str, Any]] = []
    for index, (phase, purpose) in enumerate(selected_phases, start=1):
        task_id = f"exec-{index:03d}-{phase}-{plan_ref}"
        if execution_backlog_task_was_generated(task_id, generated_task_ids):
            continue
        prompt = "\n".join(
            [
                "decision_status: decided",
                "route: execution_next",
                f"plan_id: {plan.get('plan_id', '')}",
                f"goal_id: {plan.get('goal_id', '')}",
                f"problem: {contract.get('problem', '')}",
                f"system_requirement: {contract.get('system_requirement', '')}",
                f"data_contract: {contract.get('data_shape', '')}",
                f"state_flow: {contract.get('normal_flow', '')}",
                f"exception_flow: {contract.get('exception_flow', '')}",
                f"acceptance: {contract.get('acceptance', '')}",
                f"out_of_scope: {contract.get('out_of_scope', '')}",
                f"allowed_execution: {contract.get('allowed_execution', '')}",
                *bounded_read_lines,
                f"change_record: {contract.get('change_record', '') or 'Generated from requirements debate ready_for_execution_backlog.'}",
                "role_signoff: requirements debate pipeline reached ready_for_execution_backlog.",
                f"execution_backlog_index: {index}",
                f"execution_backlog_phase: {phase}",
                "",
                "Execution slice:",
                purpose,
                "",
                "Rules:",
                "- Execute only this bounded phase.",
                "- Use reference-first copying where the phase requires it.",
                "- live_read_budget_policy: stop.",
                "- Read only bounded slices from allowed_paths; do not cd to /root/a9 or search broad roots.",
                "- Use capped `rg -n -m 20` or `rg ... | head -n 40`; never run uncapped rg in read-heavy phases.",
                "- Keep each `sed -n` source window <= 120 lines and total requested source lines <= 180.",
                "- Do not search `.a9` roots; use exact evidence paths already provided in the prompt.",
                "- Do not change product scope, data contract, state flow, acceptance, or out_of_scope.",
                "- If the contract is wrong, append a plan change_request instead of silently changing it.",
            ]
        )
        items.append(
            {
                "task_id": task_id,
                "phase": phase,
                "prompt": prompt,
                "allowed_paths": allowed_paths,
                "checks": [],
                "source": "plan.execution_backlog.items",
            }
        )
        if count > 0 and len(items) >= count:
            break
    if not items:
        change_request_item = plan_change_request_continuation_item(plan, generated_task_ids=generated_task_ids)
        if change_request_item:
            items.append(change_request_item)
    if not items:
        backlog_generation_item = plan_backlog_generation_continuation_item(
            plan,
            generated_task_ids=generated_task_ids,
        )
        if backlog_generation_item:
            items.append(backlog_generation_item)
    return items


def mark_execution_backlog_items_queued(plan: dict[str, Any], queued_items: list[dict[str, Any]], created_paths: list[Path]) -> None:
    if not queued_items:
        return
    backlog = execution_backlog_state(plan)
    raw_items = [item for item in backlog.get("items", []) if isinstance(item, dict)]
    by_backlog_id = {str(item.get("backlog_id") or ""): (item, path) for item, path in zip(queued_items, created_paths)}
    now = utc_now()
    for index, raw in enumerate(raw_items, start=1):
        normalized = normalize_execution_backlog_item(raw, index=index, plan=plan)
        queued = by_backlog_id.get(str(normalized.get("backlog_id") or ""))
        if not queued:
            continue
        item, path = queued
        raw["status"] = "queued"
        raw["queued_task_id"] = str(item.get("task_id") or "")
        raw["queued_task_path"] = str(path)
        raw["queued_at"] = now
    generated = backlog.get("generated_task_ids")
    if not isinstance(generated, list):
        generated = []
        backlog["generated_task_ids"] = generated
    for item in queued_items:
        task_id = str(item.get("task_id") or "")
        if task_id and task_id not in generated:
            generated.append(task_id)
    debate_state = plan.get("requirements_debate")
    if isinstance(debate_state, dict):
        debate_state["generated_execution_next_count"] = len(generated)


def enqueue_execution_backlog_items(
    plan: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    prefix: str = "",
    timeout_seconds: int = 3600,
    idle_timeout_seconds: int = 300,
    auto_next: bool = True,
) -> list[Path]:
    created: list[Path] = []
    queued_items: list[dict[str, Any]] = []
    for item in items:
        task_id = str(item["task_id"])
        if prefix:
            task_id = f"{prefix}-{task_id}"
        path = enqueue_task_file(
            task_id,
            str(item["prompt"]),
            phase=str(item["phase"]),
            checks=[str(check) for check in item.get("checks", [])],
            timeout_seconds=timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
            max_attempts=1,
            allowed_paths=[str(path) for path in item.get("allowed_paths", [])],
            auto_next=auto_next,
        )
        queued_item = dict(item)
        queued_item["task_id"] = task_id
        queued_items.append(queued_item)
        created.append(path)
    if any(
        str(item.get("source") or "")
        in {"plan.execution_backlog.items", "plan.change_request", "plan.execution_backlog_generation"}
        for item in queued_items
    ):
        mark_execution_backlog_items_queued(plan, queued_items, created)
        write_plan_files(plan)
    return created


def schedule_execution_backlog_from_plan(plan_id: str, *, prefix: str = "auto-backlog") -> Path | None:
    plan = load_plan(plan_id)
    if not plan:
        return None
    items = plan_execution_backlog_items(plan)
    if not items:
        return None
    created = enqueue_execution_backlog_items(plan, items, prefix=prefix, auto_next=True)
    return created[0] if created else None


def append_execution_backlog_item(
    *,
    plan_id: str,
    title: str,
    phase: str,
    prompt: str,
    allowed_paths: list[str],
    checks: list[str],
    task_id: str = "",
) -> dict[str, Any]:
    plan = load_plan(plan_id)
    if not plan:
        return {"status": "missing_plan", "path": ""}
    backlog = execution_backlog_state(plan)
    items = backlog.get("items")
    if not isinstance(items, list):
        items = []
        backlog["items"] = items
    item_index = len([item for item in items if isinstance(item, dict)]) + 1
    item = {
        "id": f"backlog-{item_index:03d}-{slugify(title or phase or 'execution')[:40]}",
        "title": title.strip(),
        "phase": phase.strip() or "implement",
        "prompt": prompt.strip(),
        "allowed_paths": [path.strip() for path in allowed_paths if path.strip()],
        "checks": [check.strip() for check in checks if check.strip()],
        "status": "ready",
        "created_at": utc_now(),
    }
    if task_id.strip():
        item["task_id"] = task_id.strip()
    items.append(item)
    plan_dir = write_plan_files(plan)
    append_plan_progress(plan_dir, f"execution_backlog_add: {item['id']} phase={item['phase']} title={item['title']}")
    return {"status": "appended", "path": str(plan_dir / "plan.json"), "item": item}


def extract_execution_backlog_payload(value: dict[str, Any]) -> list[dict[str, Any]]:
    raw: Any = None
    if isinstance(value.get("execution_backlog"), dict):
        raw = value["execution_backlog"].get("items")
    elif isinstance(value.get("execution_backlog"), list):
        raw = value.get("execution_backlog")
    elif isinstance(value.get("execution_backlog_items"), list):
        raw = value.get("execution_backlog_items")
    elif isinstance(value.get("backlog_items"), list):
        raw = value.get("backlog_items")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def extract_execution_backlog_items_from_final(final_path: Path) -> list[dict[str, Any]]:
    if not final_path.exists():
        return []
    text = final_path.read_text(encoding="utf-8", errors="backslashreplace")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in find_json_objects(text):
        for item in extract_execution_backlog_payload(value):
            title = str(item.get("title") or item.get("objective") or "").strip()
            prompt = str(item.get("prompt") or item.get("objective") or "").strip()
            phase = str(item.get("phase") or "implement").strip()
            fingerprint = hashlib.sha256(f"{title}\n{phase}\n{prompt}".encode("utf-8")).hexdigest()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            items.append(item)
    return items


def execution_backlog_allowed_path_findings(paths: list[str]) -> list[str]:
    findings: list[str] = []
    if not paths:
        return ["allowed_paths_missing"]
    broad_roots = {
        ".",
        "./",
        "scripts",
        "scripts/",
        "crates",
        "crates/",
        "crates/a9-supervisor",
        "crates/a9-supervisor/",
        "crates/a9-worker",
        "crates/a9-worker/",
        ".a9",
        ".a9/",
        "/root/a9/.a9",
        "/root/a9/.a9/",
    }
    for raw_path in paths:
        path = str(raw_path or "").strip()
        if not path:
            continue
        normalized = path.rstrip("/")
        if path in broad_roots or normalized in broad_roots:
            findings.append(f"broad_allowed_path:{path}")
            continue
        if path.startswith(".a9/") or path.startswith("/root/a9/.a9/"):
            if path.startswith(".a9/plans/"):
                continue
            if path.startswith("/root/a9/.a9/plans/") and Path(path).suffix:
                continue
            findings.append(f"runtime_root_allowed_path:{path}")
            continue
        if "*" in path and not Path(path.replace("*", "x")).suffix:
            findings.append(f"broad_glob_allowed_path:{path}")
    return findings


def execution_backlog_check_looks_executable(check: str) -> bool:
    text = str(check or "").strip()
    if not text:
        return False
    executable_prefixes = (
        "python",
        "python3",
        "pytest",
        "cargo ",
        "npm ",
        "pnpm ",
        "yarn ",
        "node ",
        "bash ",
        "sh ",
        "test ",
        "rg ",
        "grep ",
        "curl ",
        "redis-cli ",
        "git ",
    )
    return text.startswith(executable_prefixes)


def execution_backlog_check_findings(checks: list[str]) -> list[str]:
    findings: list[str] = []
    for check in checks:
        if not execution_backlog_check_looks_executable(check):
            findings.append(f"non_executable_check:{bounded_inline(check, 80)}")
    return findings


def split_execution_backlog_checks(checks: list[str]) -> tuple[list[str], list[str]]:
    executable: list[str] = []
    validation_notes: list[str] = []
    for check in checks:
        text = str(check or "").strip()
        if not text:
            continue
        if execution_backlog_check_looks_executable(text):
            executable.append(text)
        else:
            validation_notes.append(text)
    return executable, validation_notes


def execution_backlog_read_commands(raw: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    for key in ("read_commands", "bounded_read_commands", "evidence_commands"):
        value = raw.get(key)
        if isinstance(value, list):
            commands.extend(str(item).strip() for item in value if str(item).strip())
    return commands


def default_bounded_read_commands_for_paths(paths: list[str]) -> list[str]:
    commands: list[str] = []
    for raw_path in paths:
        path = str(raw_path or "").strip()
        if not path or path.endswith("/") or "*" in path:
            continue
        if not Path(path).suffix:
            continue
        commands.append(f"sed -n '1,120p' {path}")
    return commands[:8]


def execution_backlog_read_command_findings(commands: list[str], allowed_paths: list[str]) -> list[str]:
    findings: list[str] = []
    if not commands:
        return ["read_commands_missing"]
    broad_terms = (
        " . ",
        " scripts ",
        " tests ",
        " crates ",
        " .a9 ",
        "find ",
        "ls -R",
        "tree ",
    )
    allowed = [path.rstrip("/") for path in allowed_paths if path.strip()]
    broad_targets = {".", "./", "scripts", "tests", "crates", ".a9", "/root/a9", "/root/a9/.a9"}
    for command in commands:
        text = str(command or "").strip()
        if not text:
            continue
        if not re.search(r"\b(rg|sed|nl)\b", text):
            findings.append(f"non_bounded_read_command:{bounded_inline(text, 80)}")
            continue
        tokens = [token.strip("'\"") for token in shlex.split(text, posix=True)]
        if any(token.rstrip("/") in broad_targets for token in tokens):
            findings.append(f"broad_read_command:{bounded_inline(text, 80)}")
            continue
        if any(term in f" {text} " for term in broad_terms):
            findings.append(f"broad_read_command:{bounded_inline(text, 80)}")
            continue
        if allowed and not any(path and path in text for path in allowed):
            findings.append(f"read_command_outside_allowed_paths:{bounded_inline(text, 80)}")
    return findings


def execution_backlog_final_decision(final_path: Path) -> dict[str, Any]:
    if not final_path.exists():
        return {"status": "missing", "reason": "final_path_missing"}
    text = final_path.read_text(encoding="utf-8", errors="backslashreplace")
    candidates = [item for item in find_json_objects(text) if is_worker_envelope_candidate(item)]
    if not candidates:
        return {"status": "legacy", "reason": "worker_envelope_missing"}
    envelope = candidates[-1]
    output = envelope.get("output") if isinstance(envelope.get("output"), dict) else {}
    decision_status = str(output.get("decision_status") or "").strip().lower() if isinstance(output, dict) else ""
    change_request = output.get("change_request") if isinstance(output, dict) else {}
    change_status = str(change_request.get("status") or "").strip().lower() if isinstance(change_request, dict) else ""
    if decision_status != "decided":
        return {"status": "blocked", "reason": "decision_not_decided", "decision_status": decision_status or "missing"}
    if change_status in {"required", "open", "pending"}:
        return {"status": "blocked", "reason": "change_request_required", "decision_status": decision_status, "change_request_status": change_status}
    return {"status": "allowed", "reason": "decision_decided", "decision_status": decision_status, "change_request_status": change_status or "none"}


def append_execution_backlog_items_from_debate_run(
    plan: dict[str, Any],
    task: Task,
    run_dir: Path,
    summary: dict[str, Any],
) -> dict[str, Any]:
    fields = parse_key_value_prompt(task.prompt)
    if str(fields.get("route") or "").strip() != "debate_next":
        return {"status": "skipped", "reason": "not_debate_next"}
    if str(summary.get("status") or "") not in {"pass", "needs-followup"}:
        return {"status": "skipped", "reason": "run_not_pass"}
    worker = summary.get("worker", {}) if isinstance(summary.get("worker"), dict) else {}
    final_path_text = str(worker.get("final_path") or "").strip()
    if not final_path_text:
        return {"status": "skipped", "reason": "final_path_missing"}
    decision = execution_backlog_final_decision(Path(final_path_text))
    if decision.get("status") == "blocked":
        return {"status": "skipped", "reason": decision.get("reason", "decision_not_decided"), "decision": decision}
    extracted = extract_execution_backlog_items_from_final(Path(final_path_text))
    if not extracted:
        return {"status": "skipped", "reason": "no_execution_backlog_json"}
    backlog = execution_backlog_state(plan)
    items = backlog.get("items")
    if not isinstance(items, list):
        items = []
        backlog["items"] = items
    existing_fingerprints = {
        hashlib.sha256(
            (
                str(item.get("title") or item.get("objective") or "")
                + "\n"
                + str(item.get("phase") or "implement")
                + "\n"
                + str(item.get("prompt") or item.get("objective") or "")
            ).encode("utf-8")
        ).hexdigest()
        for item in items
        if isinstance(item, dict)
    }
    added: list[dict[str, Any]] = []
    for raw in extracted:
        title = str(raw.get("title") or raw.get("objective") or "").strip()
        prompt = str(raw.get("prompt") or raw.get("objective") or "").strip()
        phase = str(raw.get("phase") or "implement").strip() or "implement"
        if not title or not prompt:
            continue
        fingerprint = hashlib.sha256(f"{title}\n{phase}\n{prompt}".encode("utf-8")).hexdigest()
        if fingerprint in existing_fingerprints:
            continue
        existing_fingerprints.add(fingerprint)
        item_index = len([item for item in items if isinstance(item, dict)]) + 1
        allowed_paths = (
            [str(path).strip() for path in raw.get("allowed_paths", []) if str(path).strip()]
            if isinstance(raw.get("allowed_paths"), list)
            else extract_allowed_paths_from_execution_text(str(raw.get("allowed_execution") or ""))
        )
        raw_checks = (
            [str(check).strip() for check in raw.get("checks", []) if str(check).strip()]
            if isinstance(raw.get("checks"), list)
            else []
        )
        checks, validation_notes = split_execution_backlog_checks(raw_checks)
        if isinstance(raw.get("validation_notes"), list):
            validation_notes.extend(str(note).strip() for note in raw.get("validation_notes", []) if str(note).strip())
        read_commands = execution_backlog_read_commands(raw)
        quality_findings = execution_backlog_allowed_path_findings(allowed_paths)
        quality_findings.extend(execution_backlog_check_findings(checks))
        quality_findings.extend(execution_backlog_read_command_findings(read_commands, allowed_paths))
        item = {
            "id": str(raw.get("id") or raw.get("backlog_id") or f"backlog-{item_index:03d}-{slugify(title)[:40]}"),
            "title": title,
            "phase": phase,
            "prompt": prompt,
            "allowed_paths": allowed_paths,
            "read_commands": read_commands,
            "checks": checks,
            "validation_notes": validation_notes,
            "status": "blocked_not_decided" if quality_findings else "ready",
            "source": "debate_final_json",
            "source_run": str(run_dir),
            "created_at": utc_now(),
        }
        if quality_findings:
            item["blocked_reason"] = "backlog_item_contract_quality"
            item["quality_findings"] = quality_findings
            item["blocked_at"] = utc_now()
        if str(raw.get("task_id") or "").strip():
            item["task_id"] = str(raw.get("task_id")).strip()
        items.append(item)
        added.append(item)
    return {
        "status": "appended" if added else "skipped",
        "reason": "" if added else "no_new_valid_items",
        "added_count": len(added),
        "item_ids": [str(item.get("id") or "") for item in added],
    }


def plan_backlog_add(args: argparse.Namespace) -> int:
    ensure_dirs()
    plan_id = str(args.plan_id or "").strip() or active_plan_id()
    if not plan_id:
        print("No active plan.")
        return 1
    result = append_execution_backlog_item(
        plan_id=plan_id,
        title=str(args.title or "").strip(),
        phase=str(args.phase or "implement").strip(),
        prompt=str(args.prompt or "").strip(),
        allowed_paths=[str(path) for path in args.allowed_path],
        checks=[str(check) for check in args.check],
        task_id=str(args.task_id or "").strip(),
    )
    if result["status"] != "appended":
        print(f"Plan not found: {plan_id}")
        return 1
    item = result.get("item", {}) if isinstance(result.get("item"), dict) else {}
    print(result["path"])
    print(f"execution_backlog_added: {item.get('id', '')}")
    print(f"execution_backlog_status: {item.get('status', '')}")
    return 0


def plan_backlog_next(args: argparse.Namespace) -> int:
    ensure_dirs()
    plan_id = str(args.plan_id or "").strip() or active_plan_id()
    if not plan_id:
        print("No active plan.")
        return 1
    plan = load_plan(plan_id)
    if not plan:
        print(f"Plan not found: {plan_id}")
        return 1
    debate = requirements_debate_progress(plan)
    if debate.get("status") != "ready_for_execution_backlog":
        print(f"requirements_debate_status: {debate.get('status', '')}")
        print(f"requirements_debate_current_stage: {debate.get('current_stage', '')}")
        print("No execution backlog generated.")
        return 1
    items = plan_execution_backlog_items(plan, count=max(0, int(args.count or 0)))
    if not items:
        print("No execution backlog generated.")
        return 1
    created = enqueue_execution_backlog_items(
        plan,
        items,
        prefix=str(args.prefix or ""),
        timeout_seconds=args.timeout_seconds,
        idle_timeout_seconds=args.idle_timeout_seconds,
        auto_next=not args.no_auto_next,
    )
    for path in created:
        print(path)
    print(f"requirements_debate_status: {debate.get('status', '')}")
    print(f"execution_backlog_created: {len(created)}")
    print(f"task_auto_next: {str(not args.no_auto_next).lower()}")
    return 0


def plan_change_request(args: argparse.Namespace) -> int:
    ensure_dirs()
    plan_id = str(args.plan_id or "").strip() or active_plan_id()
    if not plan_id:
        print("No active plan.")
        return 1
    result = append_plan_change_request(
        plan_id=plan_id,
        field=str(args.field or "").strip(),
        proposal=str(args.proposal or "").strip(),
        reason=str(args.reason or "").strip(),
        actor=str(args.actor or "worker").strip(),
        evidence_refs=[str(item) for item in args.evidence_ref],
    )
    if result["status"] != "appended":
        print(f"Plan not found: {plan_id}")
        return 1
    print(result["path"])
    print(f"request_id: {result['request_id']}")
    return 0


def plan_note(args: argparse.Namespace) -> int:
    ensure_dirs()
    plan_id = str(args.plan_id or "").strip() or active_plan_id()
    if not plan_id:
        print("No active plan.")
        return 1
    result = append_plan_note(
        plan_id=plan_id,
        note_type=str(args.type or "").strip(),
        note=str(args.note or "").strip(),
        actor=str(args.actor or "worker").strip(),
        evidence_refs=[str(item) for item in args.evidence_ref],
    )
    if result["status"] == "missing":
        print(f"Plan not found: {plan_id}")
        return 1
    if result["status"] == "invalid_type":
        print(f"Invalid note type: {args.type}")
        return 1
    print(result["path"])
    return 0


def status() -> int:
    ensure_dirs()
    reconciled = reconcile_orphaned_running_tasks()
    control_state = runtime_control_state()
    task_quality = queued_task_quality_summary()
    transport_health = worker_transport_health_state()
    daemon_heartbeat = daemon_heartbeat_status()
    print(f"queued: {len(list(QUEUE_DIR.glob('*.md')))}")
    print(f"running: {len(list(RUNNING_DIR.glob('*.json')))}")
    print(f"done: {len(list(DONE_DIR.glob('*.json')))}")
    print(f"runtime_control: {control_state.get('status', 'running')}")
    print(f"worker_transport_health: {transport_health.get('status', 'unknown')}")
    if daemon_heartbeat:
        print(
            "daemon_heartbeat: "
            f"{daemon_heartbeat.get('state', 'unknown')} "
            f"pid={daemon_heartbeat.get('pid', '')} "
            f"detail={daemon_heartbeat.get('detail', '')}"
        )
        print(
            "daemon_revision: "
            f"started={str(daemon_heartbeat.get('started_repo_head', ''))[:12]} "
            f"current={str(daemon_heartbeat.get('current_repo_head', ''))[:12]} "
            f"stale={str(bool(daemon_heartbeat.get('repo_head_stale', False))).lower()}"
        )
    if transport_health.get("cooldown_until"):
        print(f"worker_transport_cooldown_until: {transport_health.get('cooldown_until')}")
    print(f"task_quality_warning_tasks: {task_quality.get('warning_task_count', 0)}")
    print(f"task_quality_warnings_count: {task_quality.get('warnings_count', 0)}")
    print(f"task_quality_blocker_tasks: {task_quality.get('blocker_task_count', 0)}")
    print(f"task_quality_blockers_count: {task_quality.get('blockers_count', 0)}")
    warning_codes = task_quality.get("warnings_by_code", {})
    if isinstance(warning_codes, dict) and warning_codes:
        warning_codes_text = ",".join(f"{code}={count}" for code, count in sorted(warning_codes.items()))
        print(f"task_quality_warning_codes: {warning_codes_text}")
    blocker_codes = task_quality.get("blockers_by_code", {})
    if isinstance(blocker_codes, dict) and blocker_codes:
        blocker_codes_text = ",".join(f"{code}={count}" for code, count in sorted(blocker_codes.items()))
        print(f"task_quality_blocker_codes: {blocker_codes_text}")
    for item in task_quality.get("tasks", [])[:5]:
        warnings = item.get("warnings", []) if isinstance(item, dict) else []
        warning_text = ",".join(str(warning) for warning in warnings)
        print(f"task_quality_warning_task: {item.get('task_id', '')} {warning_text}")
    if reconciled:
        print(f"interrupted_reconciled: {len(reconciled)}")
    latest_summary: dict[str, Any] | None = None
    latest_collection = latest_run_summaries()
    data = latest_collection.get("latest_any", {})
    latest_real = latest_collection.get("latest_real", {})
    invalid_summaries = int(latest_collection.get("invalid_summaries", 0) or 0)
    if invalid_summaries and not data:
        print(f"latest: unavailable invalid_summaries={invalid_summaries}")
    elif invalid_summaries:
        print(f"latest skipped invalid summaries: {invalid_summaries}")
    if data:
        latest_summary = data
        print(f"latest: {data['task_id']} {data['status']} {data['run_dir']}")
        if latest_real and latest_real.get("run_dir") != data.get("run_dir"):
            print(
                f"latest_real: {latest_real['task_id']} "
                f"{latest_real['status']} {latest_real['run_dir']}"
            )
        current_plan = active_plan() if active_plan_id() else {}
        latest_plan = plan_latest_run_snapshot(current_plan) if current_plan else {}
        if latest_plan.get("summary_path"):
            print(
                "latest_plan: "
                f"{latest_plan.get('phase', '')} "
                f"{latest_plan.get('status', '')} "
                f"{latest_plan.get('summary_path', '')}"
            )
        latest_plan_progress = plan_progress_snapshot(current_plan) if current_plan else {}
        if latest_plan_progress.get("latest_progress"):
            print(f"latest_plan_progress: {latest_plan_progress.get('latest_progress')}")
        if latest_plan_progress.get("latest_monitor_progress"):
            print(f"latest_plan_progress_monitor: {latest_plan_progress.get('latest_monitor_progress')}")
        guards = data.get("guard_summary") or compact_guard_summary(data)
        if guards:
            patch_status = guards.get("patch_guard", {}).get("status", "missing")
            scope_status = guards.get("scope_guard", {}).get("status", "missing")
            print(f"latest guards: patch={patch_status} scope={scope_status}")
        git_governance = data.get("git_governance", {})
        if git_governance:
            print(
                "latest git: "
                f"{git_governance.get('status', 'missing')} "
                f"commit={git_governance.get('commit', '')} "
                f"rolled_back={git_governance.get('rolled_back', False)}"
            )
        pressure = data.get("context_pressure") or compact_context_pressure(data)
        if pressure:
            print(
                "latest context: "
                f"tokens={pressure.get('prompt_approx_tokens', 'missing')}/"
                f"{pressure.get('prompt_budget_tokens', 'missing')} "
                f"ratio={pressure.get('budget_ratio', 'missing')}"
            )
            usage = pressure.get("actual_token_usage") or data.get("worker", {}).get("actual_token_usage", {})
            if usage:
                print(
                    "latest actual tokens: "
                    f"input={usage.get('input_tokens', 0)} "
                    f"cached={usage.get('cached_input_tokens', 0)} "
                    f"uncached={usage.get('uncached_input_tokens', 0)} "
                    f"output={usage.get('output_tokens', 0)} "
                    f"reasoning={usage.get('reasoning_output_tokens', 0)}"
                )
        process_quality = latest_process_quality(data)
        process_summary = process_quality.get("process_governance", {}) if isinstance(process_quality, dict) else {}
        if process_summary:
            by_kind = process_summary.get("by_kind", {})
            by_kind_text = (
                ",".join(f"{kind}={count}" for kind, count in sorted(by_kind.items()))
                if isinstance(by_kind, dict) and by_kind
                else "none"
            )
            print(
                "latest process: "
                f"status={process_summary.get('status', '')} "
                f"findings={process_summary.get('findings_count', 0)} "
                f"by_kind={by_kind_text}"
            )
            replay = replay_process_governance_for_summary(data)
            replay_summary = process_governance_prompt_summary(replay)
            replay_by_kind = replay_summary.get("by_kind", {})
            replay_by_kind_text = (
                ",".join(f"{kind}={count}" for kind, count in sorted(replay_by_kind.items()))
                if isinstance(replay_by_kind, dict) and replay_by_kind
                else "none"
            )
            if replay_summary.get("status") != "unavailable" and (
                replay_summary.get("status") != process_summary.get("status")
                or replay_summary.get("findings_count") != process_summary.get("findings_count")
                or replay_by_kind_text != by_kind_text
            ):
                print(
                    "latest process replay: "
                    f"status={replay_summary.get('status', '')} "
                    f"findings={replay_summary.get('findings_count', 0)} "
                    f"by_kind={replay_by_kind_text}"
                )
        cost = data.get("worker_cost_risk") or worker_cost_risk(data)
        reasons = cost.get("reasons", [])
        reasons_text = ",".join(str(reason) for reason in reasons) if reasons else "none"
        print(f"worker_cost_risk: level={cost.get('level', 'missing')} reasons={reasons_text}")
        transport = data.get("transport_observation", {})
        if isinstance(transport, dict) and transport.get("status") == "observed":
            print(
                "latest transport: "
                f"status=observed count={transport.get('count', 0)} "
                f"category={transport.get('category', '')}"
            )
    progress = service_progress(latest_summary)
    print(f"24h: {progress['progress_percent']}% {progress['stage']} next={progress['next_task_path']}")
    print(
        f"runtime_state: {progress['runtime_state']} "
        f"runtime_state_reason: {progress['runtime_state_reason']}"
    )
    groups = progress.get("capability_groups", {})
    if groups:
        rendered = " ".join(f"{name}={item.get('percent', 0)}%" for name, item in sorted(groups.items()))
        print(f"24h groups: {rendered}")
    current_plan_id = active_plan_id()
    if current_plan_id:
        plan = load_plan(current_plan_id)
        plan_status_text = plan.get("status", "missing") if plan else "missing"
        print(f"active plan: {current_plan_id} status={plan_status_text}")
    return 0


def init() -> int:
    ensure_dirs()
    print(STATE_DIR)
    return 0


def transport_probe(args: argparse.Namespace) -> int:
    probe = worker_transport_probe(
        timeout_seconds=args.timeout_seconds,
        ignore_user_config=args.ignore_user_config,
    )
    print(json.dumps(probe, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if probe.get("status") in {"ok", "skipped"} else 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 supervisor")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    run_one_parser = sub.add_parser("run-one")
    run_one_parser.add_argument("--auto-next", action="store_true")
    sub.add_parser("status")
    probe_parser = sub.add_parser("transport-probe")
    probe_parser.add_argument("--timeout-seconds", type=int, default=45)
    probe_parser.add_argument("--ignore-user-config", action="store_true")

    loop_parser = sub.add_parser("run-loop")
    loop_parser.add_argument("--sleep-seconds", type=float, default=5.0)
    loop_parser.add_argument("--max-tasks", type=int, default=0)
    loop_parser.add_argument("--keep-going-on-error", action="store_true")
    loop_parser.add_argument("--auto-next", action="store_true")
    loop_parser.add_argument("--exit-when-idle", action="store_true")

    enqueue_parser = sub.add_parser("enqueue")
    enqueue_parser.add_argument("task_id")
    enqueue_parser.add_argument("prompt")
    enqueue_parser.add_argument("--phase", default="implement")
    enqueue_parser.add_argument("--check", action="append", default=[])
    enqueue_parser.add_argument("--allow-path", action="append", default=[])
    enqueue_parser.add_argument("--timeout-seconds", type=int, default=3600)
    enqueue_parser.add_argument("--idle-timeout-seconds", type=int, default=300)
    enqueue_parser.add_argument("--max-attempts", type=int, default=2)
    enqueue_parser.add_argument("--no-auto-next", action="store_true")
    enqueue_parser.add_argument("--workspace-root", default="")

    session_latest_parser = sub.add_parser("session-lane-latest")
    session_latest_parser.add_argument("--session-path", default="")
    session_latest_parser.add_argument("--tail-turns", type=int, default=1)
    session_latest_parser.add_argument("--batch-size", type=int, default=1)
    session_latest_parser.add_argument("--task-id", default="")
    session_latest_parser.add_argument("--auto-continue", action="store_true")
    session_latest_parser.add_argument("--no-auto-close-reading", action="store_true")
    session_latest_parser.add_argument("--close-reading-doc", default="docs/session.md")
    session_latest_parser.add_argument("--summary-doc", default="docs/session.md")
    session_latest_parser.add_argument("--timeout-seconds", type=int, default=120)
    session_latest_parser.add_argument("--idle-timeout-seconds", type=int, default=120)

    plan_create_parser = sub.add_parser("plan-create")
    plan_create_parser.add_argument("--plan-id", default="")
    plan_create_parser.add_argument("--goal-id", default="")
    plan_create_parser.add_argument("--goal-objective", default="")
    plan_create_parser.add_argument("--goal-token-budget", type=int, default=None)
    plan_create_parser.add_argument("--flow-id", default="")
    plan_create_parser.add_argument("--expected-flow-revision", type=int, default=None)
    plan_create_parser.add_argument("--problem", required=True)
    plan_create_parser.add_argument("--why-now", default="")
    plan_create_parser.add_argument("--must", default="")
    plan_create_parser.add_argument("--should", default="")
    plan_create_parser.add_argument("--could", default="")
    plan_create_parser.add_argument("--system-requirement", default="")
    plan_create_parser.add_argument("--solution-type", default="runtime_infra")
    plan_create_parser.add_argument("--data-shape", default="")
    plan_create_parser.add_argument("--normal-flow", default="")
    plan_create_parser.add_argument("--exception-flow", default="")
    plan_create_parser.add_argument("--acceptance", default="")
    plan_create_parser.add_argument("--out-of-scope", default="")
    plan_create_parser.add_argument("--reference-entry", default="")
    plan_create_parser.add_argument("--change-record", default="")
    plan_create_parser.add_argument("--allowed-execution", default="")
    plan_create_parser.add_argument("--no-activate", action="store_true")

    plan_status_parser = sub.add_parser("plan-status")
    plan_status_parser.add_argument("--plan-id", default="")

    plan_debate_parser = sub.add_parser("plan-debate-next")
    plan_debate_parser.add_argument("--plan-id", default="")
    plan_debate_parser.add_argument("--stage", default="")
    plan_debate_parser.add_argument("--phase", default="reference_scan")
    plan_debate_parser.add_argument("--task-id", default="")
    plan_debate_parser.add_argument("--extra", default="")
    plan_debate_parser.add_argument("--timeout-seconds", type=int, default=3600)
    plan_debate_parser.add_argument("--idle-timeout-seconds", type=int, default=300)
    plan_debate_parser.add_argument("--allow-auto-next", action="store_true")

    plan_backlog_add_parser = sub.add_parser("plan-backlog-add")
    plan_backlog_add_parser.add_argument("--plan-id", default="")
    plan_backlog_add_parser.add_argument("--title", required=True)
    plan_backlog_add_parser.add_argument("--phase", default="implement")
    plan_backlog_add_parser.add_argument("--prompt", required=True)
    plan_backlog_add_parser.add_argument("--task-id", default="")
    plan_backlog_add_parser.add_argument("--allowed-path", action="append", default=[])
    plan_backlog_add_parser.add_argument("--check", action="append", default=[])

    plan_backlog_parser = sub.add_parser("plan-backlog-next")
    plan_backlog_parser.add_argument("--plan-id", default="")
    plan_backlog_parser.add_argument("--count", type=int, default=0)
    plan_backlog_parser.add_argument("--prefix", default="")
    plan_backlog_parser.add_argument("--timeout-seconds", type=int, default=3600)
    plan_backlog_parser.add_argument("--idle-timeout-seconds", type=int, default=300)
    plan_backlog_parser.add_argument("--no-auto-next", action="store_true")

    change_request_parser = sub.add_parser("plan-change-request")
    change_request_parser.add_argument("--plan-id", default="")
    change_request_parser.add_argument("--field", required=True)
    change_request_parser.add_argument("--proposal", required=True)
    change_request_parser.add_argument("--reason", required=True)
    change_request_parser.add_argument("--actor", default="worker")
    change_request_parser.add_argument("--evidence-ref", action="append", default=[])

    plan_note_parser = sub.add_parser("plan-note")
    plan_note_parser.add_argument("--plan-id", default="")
    plan_note_parser.add_argument("--type", required=True, choices=["findings", "progress", "mistakes"])
    plan_note_parser.add_argument("--note", required=True)
    plan_note_parser.add_argument("--actor", default="worker")
    plan_note_parser.add_argument("--evidence-ref", action="append", default=[])

    override_parser = sub.add_parser("eval-override")
    override_parser.add_argument("run_id")
    override_parser.add_argument("--action", required=True, choices=sorted(EVAL_OVERRIDE_ACTIONS))
    override_parser.add_argument("--reason", required=True)
    override_parser.add_argument("--actor", default="operator")
    override_parser.add_argument("--evidence-ref", action="append", default=[])

    args = parser.parse_args(argv)
    if args.command == "init":
        return init()
    if args.command == "run-one":
        return run_one(auto_next=args.auto_next)
    if args.command == "run-loop":
        return run_loop(args)
    if args.command == "status":
        return status()
    if args.command == "transport-probe":
        return transport_probe(args)
    if args.command == "enqueue":
        return enqueue(args)
    if args.command == "session-lane-latest":
        return session_lane_latest(args)
    if args.command == "plan-create":
        return plan_create(args)
    if args.command == "plan-status":
        return plan_status(args)
    if args.command == "plan-debate-next":
        return plan_debate_next(args)
    if args.command == "plan-backlog-add":
        return plan_backlog_add(args)
    if args.command == "plan-backlog-next":
        return plan_backlog_next(args)
    if args.command == "plan-change-request":
        return plan_change_request(args)
    if args.command == "plan-note":
        return plan_note(args)
    if args.command == "eval-override":
        return eval_override(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
