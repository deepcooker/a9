#!/usr/bin/env python3
"""A9 Codex supervisor MVP.

Runs queued markdown tasks through `codex exec --json`, stores traces, captures
git diffs, executes declared checks, and classifies the result without scraping
the interactive UI.
"""

from __future__ import annotations

import argparse
import hashlib
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
WORKER_CODEX_HOME = STATE_DIR / "codex-home"
WORKER_TMP_DIR = STATE_DIR / "tmp"
EXTERNAL_SESSIONS_DIR = STATE_DIR / "external_sessions"
RECORDS_DIR = STATE_DIR / "records"
PROGRESS_PATH = STATE_DIR / "progress.json"
DAEMON_HEARTBEAT_PATH = STATE_DIR / "daemon_heartbeat.json"
AUTO_LOOP_GUARD_PATH = STATE_DIR / "auto_loop_guard.json"
DEFAULT_CONTEXT_TOKEN_BUDGET = 24000
DEFAULT_WORKER_MODEL = "gpt-5.3-codex"
DEFAULT_MAX_WORKER_EVENTS = 80
DEFAULT_MAX_WORKER_EVENT_BYTES = 120_000
DEFAULT_AUTO_LOOP_FAILURE_LIMIT = 2
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
SESSION_REFRESH_PHASE = "session_refresh"
SESSION_CLOSE_READING_PHASE = "session_close_reading"
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
    SESSION_REFRESH_PHASE: "Index and extract external Codex/operator sessions without calling an AI worker.",
    SESSION_CLOSE_READING_PHASE: "Append bounded external-session close-reading notes from extracted evidence.",
}
SECTION_TOKEN_BUDGETS = {
    "doctrine": 5000,
    "task": 4000,
    "previous_context": 3000,
    "repo_map": 2500,
    "reference_mechanisms": 2500,
    "contract": 1500,
}
SUMMARY_MIN_SPLIT = 4
SUMMARY_MAX_DEPTH = 3
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
        RUNS_DIR,
        WORKTREES_DIR,
        WORKER_CODEX_HOME,
        WORKER_TMP_DIR,
        EXTERNAL_SESSIONS_DIR,
        RECORDS_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


@dataclass
class Task:
    path: Path
    task_id: str
    prompt: str
    phase: str = "implement"
    timeout_seconds: int = 3600
    idle_timeout_seconds: int = 300
    max_attempts: int = 2
    checks: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)


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
    allowed_paths = [str(item) for item in meta.get("allowed_paths", [])]
    return Task(
        path=path,
        task_id=task_id,
        prompt=body.strip(),
        phase=str(meta.get("phase", "implement")),
        timeout_seconds=int(meta.get("timeout_seconds", 3600)),
        idle_timeout_seconds=int(meta.get("idle_timeout_seconds", 300)),
        max_attempts=int(meta.get("max_attempts", 2)),
        checks=checks,
        allowed_paths=allowed_paths,
    )


def next_task() -> Task | None:
    tasks = sorted(QUEUE_DIR.glob("*.md"))
    return parse_task(tasks[0]) if tasks else None


def git_head() -> str:
    return run_cmd(["git", "rev-parse", "HEAD"]).stdout.strip()


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
    return [{"role": "user", "content": truncate_to_token_budget(summary, budget, keep="middle")}]


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

    tail_tokens = 0
    split_index = len(messages)
    half_max_tokens = max_tokens // 2
    for index in range(len(sized) - 1, -1, -1):
        tokens, _message = sized[index]
        if tail_tokens + tokens < half_max_tokens:
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
    summary_budget = max(256, max_tokens - tail_tokens)
    summary = summarize_messages_deterministic(head, summary_budget)
    combined = summary + tail
    combined_tokens = sum(approx_token_count(message["content"]) for message in combined)
    if combined_tokens <= max_tokens:
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


def git_tracked_files() -> list[str]:
    result = run_cmd_no_raise(["git", "ls-files"])
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


def extract_repo_symbols(rel_path: str, limit: int = 8) -> list[str]:
    path = ROOT / rel_path
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
        "docs/communication-governance-framework.md",
        "docs/copied-mechanisms.md",
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


def build_repo_map(task_prompt: str, budget: int) -> tuple[str, dict[str, Any]]:
    terms = prompt_terms(task_prompt)
    candidates: list[tuple[int, str, list[str]]] = []
    scanned = 0
    for rel_path in git_tracked_files():
        if not repo_map_allowed_file(rel_path):
            continue
        scanned += 1
        symbols = extract_repo_symbols(rel_path)
        score = score_repo_file(rel_path, symbols, terms)
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


def build_context_packet(task: Task) -> dict[str, Any]:
    """Build a bounded prompt packet from durable channels.

    This copies the Codex/Aider shape: assemble only what is needed for prompt
    time, track approximate token pressure, keep recent task context as tail,
    and leave raw evidence on disk instead of inlining everything.
    """
    total_budget = token_budget()
    section_budgets = SECTION_TOKEN_BUDGETS.copy()
    scale = min(1.0, total_budget / sum(section_budgets.values()))
    if scale < 1.0:
        section_budgets = {
            name: max(256, int(value * scale)) for name, value in section_budgets.items()
        }

    doctrine_parts = []
    for path in [ROOT / "原始想法需求.md", ROOT / "session-governance.md"]:
        text = read_budgeted(path, max(512, section_budgets["doctrine"] // 3), keep="head")
        if text:
            doctrine_parts.append(f"## {path.name}\n\n{text}")
    doctrine = "\n\n".join(doctrine_parts)

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

    repo_map, repo_map_meta = build_repo_map(task.prompt, section_budgets["repo_map"])

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

    task_prompt = truncate_to_token_budget(task.prompt, section_budgets["task"], keep="tail")
    contract = truncate_to_token_budget(
        """Run under the A9 supervisor.

Hard rules:
- The project core is copying mature mechanisms, then adapting them with license awareness.
- Prefer Codex session/compaction/context governance before weaker alternatives.
- Do not inline huge raw logs or whole reference repositories.
- Cite local source paths when borrowing ideas from reference projects.
- Preserve details by writing artifacts, evidence, state, checks, and patches.
- Final answer must include files changed, reference ideas used, commands run, test result, and next recommended task.
- If the task asks for `strict_worker_envelope: true`, the final answer must include a JSON object
  shaped like OpenClaw/Lobster tool envelopes: protocolVersion, ok, status/output or error.
""",
        section_budgets["contract"],
    )

    sections = [
        ("A9 Bounded Context Packet", ""),
        ("Token Budget", f"approx_budget: {total_budget} tokens"),
        ("Contract", contract),
        ("Current Task", task_prompt),
        ("Previous Task Context Tail", previous_context or "(none)"),
        ("Repository Map", repo_map or "(none)"),
        ("Reference Mechanisms To Copy", reference_mechanisms),
        ("Doctrine Excerpts", doctrine or "(none)"),
    ]
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
    }


def create_worktree(task: Task, attempt: int) -> Path:
    task_ref = artifact_task_ref(task.task_id)
    worktree = WORKTREES_DIR / f"{task_ref}-attempt-{attempt}"
    branch_scope = hashlib.sha256(str(WORKTREES_DIR.resolve()).encode("utf-8")).hexdigest()[:10]
    branch = f"a9-supervisor/{task_ref}-{attempt}-{branch_scope}"
    if worktree.exists():
        return reset_existing_worktree(worktree)
    add_args = ["git", "worktree", "add", "-B", branch, str(worktree), "HEAD"]
    result = run_cmd_no_raise(add_args)
    if result.returncode != 0:
        run_cmd_no_raise(["git", "worktree", "prune"])
        result = run_cmd_no_raise(add_args)
    if result.returncode != 0:
        if "Read-only file system" in result.stdout or "cannot lock ref" in result.stdout:
            worktree = create_isolated_git_copy(worktree)
            hydrate_worker_reference_slices(worktree)
            return worktree
        raise subprocess.CalledProcessError(result.returncode, add_args, output=result.stdout)
    hydrate_worker_reference_slices(worktree)
    return worktree


def reset_existing_worktree(worktree: Path) -> Path:
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
        worktree = create_isolated_git_copy(worktree, replace_existing=True)
        hydrate_worker_reference_slices(worktree)
        return worktree
    base_head = git_head()
    commands = (
        ["git", "restore", "--staged", "."],
        ["git", "reset", "--hard", base_head],
        ["git", "clean", "-fdq"],
    )
    for command in commands:
        result = run_cmd_no_raise(command, cwd=worktree)
        if result.returncode != 0:
            if "Read-only file system" in result.stdout or "cannot lock" in result.stdout:
                worktree = create_isolated_git_copy(worktree, replace_existing=True)
                hydrate_worker_reference_slices(worktree)
                return worktree
            raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout)
    hydrate_worker_reference_slices(worktree)
    return worktree


def create_isolated_git_copy(worktree: Path, *, replace_existing: bool = False) -> Path:
    """Fallback for sandboxes that cannot mutate the shared git metadata."""
    if worktree.exists():
        if not replace_existing:
            return worktree
        shutil.rmtree(worktree)
    worktree.mkdir(parents=True, exist_ok=True)
    for rel in git_tracked_files():
        src = ROOT / rel
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
        "reference-projects/openclaw/extensions/lobster",
        "reference-projects/openclaw/extensions/policy",
        "reference-projects/openclaw/extensions/memory-core",
        "reference-projects/openclaw/extensions/memory-wiki",
        "reference-projects/barter-rs/barter-integration/src/socket",
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


def build_worker_cmd(
    task: Task,
    worktree: Path,
    run_dir: Path,
    final_path: Path,
    prompt_text: str,
) -> list[str]:
    override = os.getenv("A9_SUPERVISOR_WORKER_CMD")
    prompt_file = run_dir / "prompt.md"
    if override:
        formatted = (
            override.replace("{prompt_file}", shlex.quote(str(prompt_file)))
            .replace("{run_dir}", shlex.quote(str(run_dir)))
            .replace("{worktree}", shlex.quote(str(worktree)))
        )
        return ["bash", "-lc", formatted]
    model = os.getenv("A9_SUPERVISOR_MODEL", DEFAULT_WORKER_MODEL)
    prepare_worker_codex_home()
    return [
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
    elif item_type == "mcp_tool_call":
        result = item.get("result") or {}
        summary.update(
            {
                "server": item.get("server"),
                "tool": item.get("tool"),
                "status": item.get("status"),
                "duration_ms": item.get("duration_ms"),
                "has_meta": isinstance(result, dict) and "_meta" in result,
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


def blocked_worker_command(command: str) -> str:
    normalized = " ".join(command.split())
    for pattern in BLOCKED_WORKER_COMMAND_PATTERNS:
        if pattern in normalized:
            return pattern
    return ""


def run_worker(task: Task, worktree: Path, run_dir: Path) -> dict[str, Any]:
    prompt_path = run_dir / "prompt.md"
    raw_task_path = run_dir / "raw_task.md"
    final_path = run_dir / "final.md"
    events_path = run_dir / "events.jsonl"
    event_summaries_path = run_dir / "event_summaries.jsonl"
    stderr_path = run_dir / "stderr.log"
    context_packet = build_context_packet(task)
    raw_task_path.write_text(task.prompt + "\n", encoding="utf-8")
    prompt_path.write_text(context_packet["prompt"], encoding="utf-8")

    cmd = build_worker_cmd(task, worktree, run_dir, final_path, context_packet["prompt"])
    started = time.monotonic()
    last_output = started
    event_counts: dict[str, int] = {}
    event_summaries: list[dict[str, Any]] = []
    seen_event_summaries: set[str] = set()
    timed_out = False
    idle_timed_out = False
    budget_stopped = False
    budget_reason = ""
    event_count = 0
    event_bytes = 0
    max_events = worker_budget_limit("A9_WORKER_MAX_EVENTS", DEFAULT_MAX_WORKER_EVENTS)
    max_event_bytes = worker_budget_limit("A9_WORKER_MAX_EVENT_BYTES", DEFAULT_MAX_WORKER_EVENT_BYTES)

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
                    event_count += 1
                    event_bytes += len(line.encode("utf-8"))
                    events.write(line)
                    events.flush()
                    event_type = classify_event(line)
                    if event_type:
                        event_counts[event_type] = event_counts.get(event_type, 0) + 1
                    payload = parse_event_payload(line)
                    if payload:
                        event_summary = summarize_thread_event(payload)
                        if event_summary:
                            fingerprint = json_compact(event_summary)
                            if fingerprint not in seen_event_summaries:
                                seen_event_summaries.add(fingerprint)
                                event_summaries.append(event_summary)
                        if event_summary and event_summary.get("item_type") == "command_execution":
                            blocked = blocked_worker_command(str(event_summary.get("command", "")))
                            if blocked:
                                budget_stopped = True
                                budget_reason = f"blocked nested worker command: {blocked}"
                                proc.kill()
                                break
                    if event_count > max_events:
                        budget_stopped = True
                        budget_reason = f"worker event count exceeded {max_events}"
                        proc.kill()
                        break
                    if event_bytes > max_event_bytes:
                        budget_stopped = True
                        budget_reason = f"worker event bytes exceeded {max_event_bytes}"
                        proc.kill()
                        break
                elif proc.poll() is not None:
                    break
            elif proc.poll() is not None:
                break

        return_code = proc.wait()

    with event_summaries_path.open("w", encoding="utf-8") as summaries:
        for item in event_summaries:
            summaries.write(json.dumps(item, ensure_ascii=False) + "\n")

    actual_token_usage = aggregate_token_usage(event_summaries)
    return {
        "command": cmd,
        "return_code": return_code,
        "timed_out": timed_out,
        "idle_timed_out": idle_timed_out,
        "budget_stopped": budget_stopped,
        "budget_reason": budget_reason,
        "event_count": event_count,
        "event_bytes": event_bytes,
        "event_budget": {"max_events": max_events, "max_event_bytes": max_event_bytes},
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
    }


def capture_diff(worktree: Path, run_dir: Path) -> dict[str, Any]:
    run_cmd(["git", "add", "-A"], cwd=worktree)
    diff = run_cmd(["git", "diff", "--cached", "--binary"], cwd=worktree).stdout
    diff_path = run_dir / "patch.diff"
    diff_path.write_text(diff, encoding="utf-8", errors="backslashreplace")
    return {"diff_path": str(diff_path), "diff_bytes": len(diff.encode("utf-8"))}


def apply_worker_search_replace(worker: dict[str, Any], worktree: Path, run_dir: Path) -> dict[str, Any]:
    output_path = run_dir / "patch_apply.json"
    patch_path = run_dir / "model_patch.search_replace"
    final_path = Path(worker["final_path"])
    result: dict[str, Any] = {
        "status": "skip",
        "kind": "search_replace_apply",
        "return_code": 0,
        "output_path": str(output_path),
        "patch_path": str(patch_path),
        "findings": [{"level": "info", "message": "no SEARCH/REPLACE patch in final message"}],
    }
    if not final_path.exists():
        write_json(output_path, result)
        return result

    text = final_path.read_text(encoding="utf-8", errors="backslashreplace")
    if "<<<<<<< SEARCH" not in text or ">>>>>>> REPLACE" not in text:
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

    patch_path.write_text(text, encoding="utf-8")
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
    fields = parse_key_value_prompt(task.prompt)
    required = parse_bool_field(fields, "strict_worker_envelope", False)
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


def decide_status(
    worker: dict[str, Any],
    diff: dict[str, Any],
    checks: list[dict[str, Any]],
    patch_guard: dict[str, Any] | None = None,
    scope_guard: dict[str, Any] | None = None,
    patch_apply: dict[str, Any] | None = None,
    worker_envelope: dict[str, Any] | None = None,
    allow_no_diff: bool = False,
) -> str:
    failure = classify_worker_failure(worker)
    if failure.get("status"):
        return str(failure["status"])
    if worker_envelope and worker_envelope.get("status") == "needs-approval":
        return "needs-approval"
    if worker_envelope and worker_envelope.get("status") == "fail":
        return "needs-repair"
    if patch_apply and patch_apply.get("status") == "fail":
        return "needs-repair"
    if patch_guard and patch_guard.get("status") == "fail":
        return "needs-repair"
    if scope_guard and scope_guard.get("status") == "fail":
        return "needs-repair"
    failed_checks = [item for item in checks if item["return_code"] != 0]
    if failed_checks:
        return "needs-repair"
    if diff["diff_bytes"] == 0:
        if allow_no_diff:
            return "pass"
        return "needs-followup"
    return "pass"


def task_allows_no_diff(task: Task) -> bool:
    fields = parse_key_value_prompt(task.prompt)
    if parse_bool_field(fields, "allow_no_diff", False):
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
    }


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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


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
        "worker_model": os.getenv("A9_SUPERVISOR_MODEL", DEFAULT_WORKER_MODEL),
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
            "checks": by_kind.get("check_log", []),
            "deep_marks": [mark["mark_id"] for mark in deep_marks],
            "memories": [],
        },
        "updated_channels": [
            "task",
            "messages",
            "tool_events",
            "event_summaries",
            "worker_envelopes",
            "repo_state",
            "patches",
            "guards",
            "git_governance",
            "policy_attestations",
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
    return run_cmd_no_raise(["docker", "exec", "a9-redis", "redis-cli", *args])


def redis_available() -> bool:
    return redis_cli(["PING"]).stdout.strip().endswith("PONG")


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
    for mark in deep_marks:
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
        "deep_mark_events": len(deep_marks),
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
    for key in ("budget_reason",):
        if worker.get(key):
            parts.append(str(worker[key]))
    for key in ("event_summaries_path", "stderr_path", "final_path"):
        raw_path = worker.get(key)
        if not raw_path:
            continue
        path = Path(str(raw_path))
        parts.append(read_text_if_exists(path, limit=limit // 3))
    return "\n".join(part for part in parts if part).strip()[:limit]


def classify_worker_failure(worker: dict[str, Any]) -> dict[str, Any]:
    if worker.get("budget_stopped"):
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
    context_path = run_dir / "context.md"
    context_path.write_text(content, encoding="utf-8")
    task_context_path = STATE_DIR / "tasks" / "done" / f"{artifact_task_ref(task.task_id)}.context.md"
    task_context_path.write_text(content, encoding="utf-8")
    return context_path


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
        "close_reading_doc": fields.get("close_reading_doc", "docs/session-raw-close-reading.md"),
        "summary_doc": fields.get("summary_doc", "docs/session-raw-summary.md"),
        "flow_id": fields.get("flow_id", ""),
        "flow_expected_revision": parse_optional_int(fields.get("flow_expected_revision")),
        "flow_expected_last_seq": parse_optional_int(fields.get("flow_expected_last_seq")),
        "flow_sequence": parse_optional_int(fields.get("flow_sequence")),
    }


def parse_bool_field(fields: dict[str, str], name: str, default: bool) -> bool:
    if name not in fields:
        return default
    return str(fields[name]).strip().lower() not in {"0", "false", "no", "off"}


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


def parse_session_close_reading_spec(prompt: str) -> dict[str, Any]:
    fields = parse_key_value_prompt(prompt)
    extract_path = fields.get("extract_path") or fields.get("path")
    if not extract_path:
        raise ValueError("missing session_close_reading fields: extract_path")
    spec: dict[str, Any] = {
        "extract_path": extract_path,
        "close_reading_doc": fields.get("close_reading_doc", "docs/session-raw-close-reading.md"),
        "summary_doc": fields.get("summary_doc", "docs/session-raw-summary.md"),
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


def bounded_inline(text: str, limit: int = 500) -> str:
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def next_phase_for(status: str, current_phase: str) -> str:
    if status == "needs-repair" or status.startswith("retryable-"):
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


def phase_from_next_slice(next_slice: Any) -> str | None:
    text = str(next_slice or "").strip()
    if not text or ":" not in text:
        return None
    prefix = text.split(":", 1)[0].strip().lower().replace("-", "_")
    return NEXT_SLICE_PHASE_PREFIXES.get(prefix)


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
    return output if isinstance(output, dict) else {"raw_output": output}


def next_task_prompt(task: Task, summary: dict[str, Any], phase: str) -> str:
    focus_lines = "\n".join(f"- {name}: {focus}" for name, focus in PHASE_FOCUS.items())
    worker_output = worker_output_from_summary(summary)
    previous_output_lines = ""
    if worker_output:
        previous_output_lines = f"""
Previous worker output:
- next_slice: {bounded_inline(worker_output.get('next_slice', ''), 700)}
- copied_mechanisms: {bounded_inline(json.dumps(worker_output.get('copied_mechanisms', []), ensure_ascii=False), 1200)}
- changed_files: {bounded_inline(json.dumps(worker_output.get('changed_files', []), ensure_ascii=False), 500)}
"""
    phase_lines = ""
    if phase == "reference_scan":
        phase_lines = """
Phase-specific bounds:
expected_file_changes: false
- Do not modify files in this phase.
- Do not `cat` full context, record, session, or reference files.
- Read only bounded snippets with `sed -n '1,120p'` or targeted `rg -n`.
- Pick one concrete next mechanism and put it in `output.next_slice`.
"""
    elif phase in {"mechanism_extract", "vendor_import"}:
        phase_lines = """
Phase-specific bounds:
- Do not broaden into implementation unless the phase is `implement`.
- Do not `cat` full context, record, session, or reference files.
- Use targeted `rg -n` and bounded `sed` snippets only.
"""
    repair_hint = ""
    patch_apply = summary.get("patch_apply", {})
    patch_apply_hint = format_patch_apply_repair_hint(patch_apply, summary.get("git_governance", {}))
    if summary.get("status") == "needs-repair" and patch_apply_hint:
        repair_hint = f"""
{patch_apply_hint}
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
    return f"""strict_worker_envelope: true

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
{phase_lines}

Core rule:
- Continue copying mature open-source mechanisms before inventing.
- Inspect local reference projects under `/root/a9/reference-projects`.
- Record copied source/license obligations in docs/vendor records when adding new references.
- Implement one concrete, testable improvement only when the current phase calls for implementation or test hardening.
- Run the declared checks.
- Keep the task bounded; do not broaden beyond the task file's allowed paths.
- Declared checks are authoritative. Do not add pytest or cargo unless they are explicitly declared in this task.
- Do not read `docs/session-raw-summary.md`, `docs/session-raw-close-reading.md`, raw session logs, or service/process status unless this task is a session_refresh/session_close_reading task or explicitly asks for those files.
- Use `rg -n` first, then read small line windows only; avoid broad `sed` ranges and full-file dumps.
- If `strict_worker_envelope: true` is present, final output must include:
  {{"protocolVersion":1,"ok":true,"status":"ok","output":{{"changed_files":[],"copied_mechanisms":[],"tests":[],"next_slice":""}}}}
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


def auto_loop_failure_kind(summary: dict[str, Any]) -> str:
    status = str(summary.get("status") or "")
    worker_failure = summary.get("worker_failure", {})
    failure_status = str(worker_failure.get("status") or "") if isinstance(worker_failure, dict) else ""
    if status.startswith("retryable-"):
        return status
    if failure_status.startswith("retryable-"):
        return failure_status
    if status in {"needs-repair", "worker-failed", "failed"}:
        return status
    envelope = summary.get("worker_envelope", {})
    if isinstance(envelope, dict) and envelope.get("status") == "fail":
        return "worker-envelope-fail"
    return ""


def worker_failure_short_circuits_checks(worker_failure: dict[str, Any]) -> bool:
    return str(worker_failure.get("status") or "").startswith("retryable-")


def update_auto_loop_guard(summary: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    kind = auto_loop_failure_kind(summary)
    previous = read_json_file(AUTO_LOOP_GUARD_PATH)
    limit = auto_loop_failure_limit()
    if kind:
        consecutive = int(previous.get("consecutive_failures") or 0) + 1
        state = {
            "status": "tripped" if consecutive >= limit else "watching",
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
        return isinstance(state, dict) and state.get("status") == "tripped"
    state = {}
    if not state:
        state = read_json_file(AUTO_LOOP_GUARD_PATH)
    return state.get("status") == "tripped"


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
    checks_text = "\n".join(f'  - "{item}"' for item in checks)
    allowed_paths_text = "\n".join(f'  - "{item}"' for item in allowed_paths)
    frontmatter = [
        "---",
        f'id: "{path.stem}"',
        f'phase: "{phase}"',
        f"timeout_seconds: {timeout_seconds}",
        f"idle_timeout_seconds: {idle_timeout_seconds}",
        f"max_attempts: {max_attempts}",
        "checks:",
        checks_text,
        "allowed_paths:",
        allowed_paths_text,
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
    envelope = worker_envelope.get("envelope", {}) if isinstance(worker_envelope, dict) else {}
    output = envelope.get("output", {}) if isinstance(envelope, dict) else {}
    if not isinstance(output, dict):
        output = {"raw_output": output}
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
            "changed_files": output.get("changed_files", []),
            "copied_mechanisms": output.get("copied_mechanisms", []),
            "tests": output.get("tests", []),
            "next_slice": output.get("next_slice", ""),
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


def schedule_next_task(task: Task, summary: dict[str, Any]) -> Path | None:
    if flow_transition_blocks_next(summary):
        return None
    if auto_loop_guard_blocks_next(summary):
        return None
    if task.phase == SESSION_REFRESH_PHASE:
        return schedule_next_session_refresh_task(task, summary)
    if task.phase == SESSION_CLOSE_READING_PHASE:
        return schedule_next_session_close_reading_task(task, summary)
    if summary["status"] not in {"pass", "needs-followup", "needs-repair"}:
        return None
    phase = next_phase_for(summary["status"], task.phase)
    if summary["status"] in {"pass", "needs-followup"}:
        worker_output = worker_output_from_summary(summary)
        routed_phase = phase_from_next_slice(worker_output.get("next_slice"))
        if routed_phase:
            phase = routed_phase
    if phase == "record" and summary["status"] == "pass":
        record_path = write_deterministic_record(task, summary)
        summary["deterministic_record_path"] = str(record_path)
        phase = next_phase_for("pass", "record")
    checks = checks_for_next_phase(phase, task)
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


def schedule_next_session_refresh_task(task: Task, summary: dict[str, Any]) -> Path | None:
    if summary.get("status") != "pass":
        return None
    refresh = summary.get("session_refresh", {})
    if refresh.get("auto_close_reading", True) and refresh.get("extract_path"):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        parent_ref = compact_task_ref(task.task_id)
        task_id = f"auto-session-close-reading-{parent_ref}-{refresh.get('from_turn')}-{refresh.get('to_turn')}-{timestamp}"
        prompt = f"""extract_path: {refresh['extract_path']}
close_reading_doc: {refresh.get('close_reading_doc', 'docs/session-raw-close-reading.md')}
summary_doc: {refresh.get('summary_doc', 'docs/session-raw-summary.md')}
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
close_reading_doc: {refresh.get('close_reading_doc', 'docs/session-raw-close-reading.md')}
summary_doc: {refresh.get('summary_doc', 'docs/session-raw-summary.md')}
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
        "close_reading_doc": reading.get("close_reading_doc", "docs/session-raw-close-reading.md"),
        "summary_doc": reading.get("summary_doc", "docs/session-raw-summary.md"),
        "flow_id": reading.get("flow_id", ""),
        "flow_revision": reading.get("flow_revision"),
        "flow_last_seq": reading.get("flow_last_seq"),
        "flow_next_seq": reading.get("flow_next_seq"),
    }
    return schedule_next_session_refresh_range(task.task_id, refresh)


def service_progress(summary: dict[str, Any] | None = None, next_task_path: Path | None = None) -> dict[str, Any]:
    ensure_dirs()
    completed_runs = len(list(RUNS_DIR.glob("*/summary.json")))
    done_tasks = len(list(DONE_DIR.glob("*.json")))
    queued_tasks = len(list(QUEUE_DIR.glob("*.md")))
    running_tasks = len(list(RUNNING_DIR.glob("*.json")))
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
        ],
        "automation": [
            "auto_next_scheduler",
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
        "stage": "auto-loop-mvp" if next_task_path else "supervisor-mvp",
        "progress_percent": round(done_capabilities / len(capabilities) * 100, 1),
        "completed_runs": completed_runs,
        "done_tasks": done_tasks,
        "queued_tasks": queued_tasks,
        "running_tasks": running_tasks,
        "latest_task_id": summary.get("task_id") if summary else None,
        "latest_status": summary.get("status") if summary else None,
        "latest_run": summary.get("run_dir") if summary else None,
        "latest_guards": summary.get("guard_summary", compact_guard_summary(summary)) if summary else {},
        "latest_context_pressure": (
            summary.get("context_pressure", compact_context_pressure(summary)) if summary else {}
        ),
        "latest_git_governance": summary.get("git_governance", {}) if summary else {},
        "latest_worker_failure": summary.get("worker_failure", {}) if summary else {},
        "auto_loop_guard": summary.get("auto_loop_guard", read_json_file(AUTO_LOOP_GUARD_PATH)) if summary else read_json_file(AUTO_LOOP_GUARD_PATH),
        "next_task_path": str(next_task_path) if next_task_path else "",
        "auto_next_scheduled": next_task_path is not None,
        "capabilities": capabilities,
        "capability_groups": group_progress,
        "next_goal": "Run the copy pipeline under the daemon for longer unattended soak tests.",
    }
    write_json(PROGRESS_PATH, progress)
    return progress


def write_daemon_heartbeat(state: str, *, detail: str = "") -> dict[str, Any]:
    ensure_dirs()
    payload = {
        "updated_at": utc_now(),
        "state": state,
        "detail": detail,
        "queued_tasks": len(list(QUEUE_DIR.glob("*.md"))),
        "running_tasks": len(list(RUNNING_DIR.glob("*.json"))),
        "done_tasks": len(list(DONE_DIR.glob("*.json"))),
    }
    write_json(DAEMON_HEARTBEAT_PATH, payload)
    return payload


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
    task = next_task()
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
        worktree = create_worktree(task, attempt)
        lease = {
            "task_id": task.task_id,
            "attempt": attempt,
            "started_at": utc_now(),
            "run_dir": str(run_dir),
            "worktree": str(worktree),
            "repo_head": git_head(),
            "parent_checkpoint_id": previous_task_checkpoint_id(task),
        }
        task_ref = artifact_task_ref(task.task_id)
        lease_path = RUNNING_DIR / f"{task_ref}.json"
        write_json(lease_path, lease)

        worker = run_worker(task, worktree, run_dir)
        worker_envelope = validate_worker_envelope(task, worker, run_dir)
        patch_apply = apply_worker_search_replace(worker, worktree, run_dir)
        diff = capture_diff(worktree, run_dir)
        patch_guard = validate_captured_diff(diff, worktree, run_dir)
        scope_guard = validate_scope(diff, task, run_dir)
        worker_failure = classify_worker_failure(worker)
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
                allow_no_diff=task_allows_no_diff(task),
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
            "git_governance": git_governance,
            "checks": checks,
        }
        summary["policy_attestation"] = create_policy_attestation(task, run_dir, summary)
        summary["context_pressure"] = compact_context_pressure(summary)
        summary["guard_summary"] = compact_guard_summary(summary)
        context_path = write_context_summary(task, run_dir, summary)
        summary["context_path"] = str(context_path)
        evidence_path, state_path, deep_marks_path, evidence, state, deep_marks = write_evidence_and_state(
            task, run_dir, summary, context_path
        )
        summary["evidence_path"] = str(evidence_path)
        summary["state_path"] = str(state_path)
        summary["deep_marks_path"] = str(deep_marks_path)
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


def run_loop(args: argparse.Namespace) -> int:
    ensure_dirs()
    completed = 0
    while True:
        write_daemon_heartbeat("polling", detail=f"completed={completed}")
        task = next_task()
        if not task:
            write_daemon_heartbeat("idle", detail="no queued tasks")
            print("No queued tasks.")
            return 0
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
    )
    print(path)
    return 0


def status() -> int:
    ensure_dirs()
    print(f"queued: {len(list(QUEUE_DIR.glob('*.md')))}")
    print(f"running: {len(list(RUNNING_DIR.glob('*.json')))}")
    print(f"done: {len(list(DONE_DIR.glob('*.json')))}")
    latest = sorted(RUNS_DIR.glob("*/summary.json"), key=lambda path: path.stat().st_mtime)
    if latest:
        data = json.loads(latest[-1].read_text(encoding="utf-8"))
        print(f"latest: {data['task_id']} {data['status']} {data['run_dir']}")
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
    if PROGRESS_PATH.exists():
        progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        print(f"24h: {progress['progress_percent']}% {progress['stage']} next={progress['next_task_path']}")
        groups = progress.get("capability_groups", {})
        if groups:
            rendered = " ".join(f"{name}={item.get('percent', 0)}%" for name, item in sorted(groups.items()))
            print(f"24h groups: {rendered}")
    return 0


def init() -> int:
    ensure_dirs()
    print(STATE_DIR)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 supervisor")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    run_one_parser = sub.add_parser("run-one")
    run_one_parser.add_argument("--auto-next", action="store_true")
    sub.add_parser("status")

    loop_parser = sub.add_parser("run-loop")
    loop_parser.add_argument("--sleep-seconds", type=float, default=5.0)
    loop_parser.add_argument("--max-tasks", type=int, default=0)
    loop_parser.add_argument("--keep-going-on-error", action="store_true")
    loop_parser.add_argument("--auto-next", action="store_true")

    enqueue_parser = sub.add_parser("enqueue")
    enqueue_parser.add_argument("task_id")
    enqueue_parser.add_argument("prompt")
    enqueue_parser.add_argument("--phase", default="implement")
    enqueue_parser.add_argument("--check", action="append", default=[])
    enqueue_parser.add_argument("--allow-path", action="append", default=[])
    enqueue_parser.add_argument("--timeout-seconds", type=int, default=3600)
    enqueue_parser.add_argument("--idle-timeout-seconds", type=int, default=300)
    enqueue_parser.add_argument("--max-attempts", type=int, default=2)

    args = parser.parse_args(argv)
    if args.command == "init":
        return init()
    if args.command == "run-one":
        return run_one(auto_next=args.auto_next)
    if args.command == "run-loop":
        return run_loop(args)
    if args.command == "status":
        return status()
    if args.command == "enqueue":
        return enqueue(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
