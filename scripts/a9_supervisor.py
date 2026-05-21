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
DEFAULT_CONTEXT_TOKEN_BUDGET = 24000
SECTION_TOKEN_BUDGETS = {
    "doctrine": 5000,
    "task": 4000,
    "previous_context": 3000,
    "reference_mechanisms": 2500,
    "contract": 1500,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return value.strip("-") or f"task-{int(time.time())}"


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


def ensure_dirs() -> None:
    for path in [QUEUE_DIR, RUNNING_DIR, DONE_DIR, RUNS_DIR, WORKTREES_DIR]:
        path.mkdir(parents=True, exist_ok=True)


@dataclass
class Task:
    path: Path
    task_id: str
    prompt: str
    timeout_seconds: int = 3600
    idle_timeout_seconds: int = 300
    max_attempts: int = 2
    checks: list[str] = field(default_factory=list)


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
    return Task(
        path=path,
        task_id=task_id,
        prompt=body.strip(),
        timeout_seconds=int(meta.get("timeout_seconds", 3600)),
        idle_timeout_seconds=int(meta.get("idle_timeout_seconds", 300)),
        max_attempts=int(meta.get("max_attempts", 2)),
        checks=checks,
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
    for path in [ROOT / "需求.md", ROOT / "codex.md", ROOT / "session-governance.md"]:
        text = read_budgeted(path, max(512, section_budgets["doctrine"] // 3), keep="head")
        if text:
            doctrine_parts.append(f"## {path.name}\n\n{text}")
    doctrine = "\n\n".join(doctrine_parts)

    previous_context_path = DONE_DIR / f"{task.task_id}.context.md"
    previous_context = read_budgeted(
        previous_context_path,
        section_budgets["previous_context"],
        keep="tail",
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
""",
        section_budgets["contract"],
    )

    sections = [
        ("A9 Bounded Context Packet", ""),
        ("Token Budget", f"approx_budget: {total_budget} tokens"),
        ("Contract", contract),
        ("Current Task", task_prompt),
        ("Previous Task Context Tail", previous_context or "(none)"),
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
    }


def create_worktree(task: Task, attempt: int) -> Path:
    worktree = WORKTREES_DIR / f"{task.task_id}-attempt-{attempt}"
    branch = f"a9-supervisor/{task.task_id}-{attempt}"
    if worktree.exists():
        return worktree
    run_cmd(["git", "worktree", "add", "-B", branch, str(worktree), "HEAD"], capture=True)
    return worktree


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
    return [
        "codex",
        "exec",
        "--json",
        "-C",
        str(worktree),
        "--output-last-message",
        str(final_path),
        prompt_text,
    ]


def classify_event(line: str) -> str | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    event_type = payload.get("type") or payload.get("event") or payload.get("msg", {}).get("type")
    return str(event_type) if event_type else None


def run_worker(task: Task, worktree: Path, run_dir: Path) -> dict[str, Any]:
    prompt_path = run_dir / "prompt.md"
    raw_task_path = run_dir / "raw_task.md"
    final_path = run_dir / "final.md"
    events_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    context_packet = build_context_packet(task)
    raw_task_path.write_text(task.prompt + "\n", encoding="utf-8")
    prompt_path.write_text(context_packet["prompt"], encoding="utf-8")

    cmd = build_worker_cmd(task, worktree, run_dir, final_path, context_packet["prompt"])
    started = time.monotonic()
    last_output = started
    event_counts: dict[str, int] = {}
    timed_out = False
    idle_timed_out = False

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
                    events.write(line)
                    events.flush()
                    event_type = classify_event(line)
                    if event_type:
                        event_counts[event_type] = event_counts.get(event_type, 0) + 1
                elif proc.poll() is not None:
                    break
            elif proc.poll() is not None:
                break

        return_code = proc.wait()

    return {
        "command": cmd,
        "return_code": return_code,
        "timed_out": timed_out,
        "idle_timed_out": idle_timed_out,
        "event_counts": event_counts,
        "events_path": str(events_path),
        "stderr_path": str(stderr_path),
        "final_path": str(final_path),
        "raw_task_path": str(raw_task_path),
        "prompt_approx_tokens": context_packet["approx_tokens"],
        "prompt_budget_tokens": context_packet["budget_tokens"],
        "prompt_section_budgets": context_packet["section_budgets"],
        "previous_context_path": context_packet["previous_context_path"],
    }


def capture_diff(worktree: Path, run_dir: Path) -> dict[str, Any]:
    run_cmd(["git", "add", "-A"], cwd=worktree)
    diff = run_cmd(["git", "diff", "--cached", "--binary"], cwd=worktree).stdout
    diff_path = run_dir / "patch.diff"
    diff_path.write_text(diff, encoding="utf-8", errors="backslashreplace")
    return {"diff_path": str(diff_path), "diff_bytes": len(diff.encode("utf-8"))}


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


def decide_status(worker: dict[str, Any], diff: dict[str, Any], checks: list[dict[str, Any]]) -> str:
    if worker["timed_out"] or worker["idle_timed_out"]:
        return "retryable-timeout"
    if worker["return_code"] != 0:
        return "retryable-worker-failed"
    failed_checks = [item for item in checks if item["return_code"] != 0]
    if failed_checks:
        return "needs-repair"
    if diff["diff_bytes"] == 0:
        return "needs-followup"
    return "pass"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
        "session_id": record["run_id"],
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
        if not stripped:
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
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
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
        marks.append(
            mark_record(
                record=record,
                index=len(marks) + 1,
                kind="event",
                label=str(event_type or "unknown"),
                value=json.dumps(payload, ensure_ascii=False)[:1000],
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
) -> tuple[Path, Path]:
    run_id = Path(summary["run_dir"]).name
    checkpoint_id = f"{run_id}:checkpoint:{summary['attempt']}"
    records: list[dict[str, Any]] = []

    paths = [
        ("raw_task", Path(summary["worker"]["raw_task_path"]), {"task_id": task.task_id}),
        ("prompt", run_dir / "prompt.md", {"task_id": task.task_id}),
        ("events", Path(summary["worker"]["events_path"]), summary["worker"]["event_counts"]),
        ("stderr", Path(summary["worker"]["stderr_path"]), {}),
        ("final_message", Path(summary["worker"]["final_path"]), {}),
        ("patch", Path(summary["diff"]["diff_path"]), {"diff_bytes": summary["diff"]["diff_bytes"]}),
        ("context", context_path, {"status": summary["status"]}),
    ]
    for kind, path, metadata in paths:
        record = evidence_record(
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            kind=kind,
            path=path,
            metadata=metadata,
        )
        if record:
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
        "parent_checkpoint_id": None,
        "step": summary["attempt"],
        "source": "loop",
        "created_at": utc_now(),
        "status": summary["status"],
        "channels": {
            "task": by_kind.get("prompt", []),
            "messages": by_kind.get("final_message", []) + by_kind.get("context", []),
            "tool_events": by_kind.get("events", []) + by_kind.get("stderr", []),
            "repo_state": [
                {
                    "repo_head": summary["repo_head"],
                    "worktree": summary["worktree"],
                }
            ],
            "patches": by_kind.get("patch", []),
            "checks": by_kind.get("check_log", []),
            "deep_marks": [mark["mark_id"] for mark in deep_marks],
            "memories": [],
        },
        "updated_channels": [
            "task",
            "messages",
            "tool_events",
            "repo_state",
            "patches",
            "checks",
            "deep_marks",
        ],
        "evidence_ids": [record["evidence_id"] for record in records],
        "deep_mark_count": len(deep_marks),
    }
    state_path = run_dir / "state.json"
    write_json(state_path, state)
    return evidence_path, state_path, deep_marks_path


def read_text_if_exists(path: Path, limit: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="backslashreplace")
    if len(text) > limit:
        return text[:limit] + "\n...[truncated]\n"
    return text


def write_context_summary(task: Task, run_dir: Path, summary: dict[str, Any]) -> Path:
    final_text = read_text_if_exists(Path(summary["worker"]["final_path"]), limit=3000).strip()
    diff_text = read_text_if_exists(Path(summary["diff"]["diff_path"]), limit=3000).strip()
    failed_checks = [item for item in summary["checks"] if item["return_code"] != 0]
    checks_text = "\n".join(
        f"- `{item['command']}` -> {item['return_code']} ({item['output_path']})"
        for item in summary["checks"]
    )
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
- events: {json.dumps(summary['worker']['event_counts'], ensure_ascii=False)}

## Checks

{checks_text or '- none'}

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
    task_context_path = STATE_DIR / "tasks" / "done" / f"{task.task_id}.context.md"
    task_context_path.write_text(content, encoding="utf-8")
    return context_path


def run_one() -> int:
    ensure_dirs()
    task = next_task()
    if not task:
        print("No queued tasks.")
        return 0

    attempt = 1
    while attempt <= task.max_attempts:
        run_id = f"{task.task_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-a{attempt}"
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
        }
        lease_path = RUNNING_DIR / f"{task.task_id}.json"
        write_json(lease_path, lease)

        worker = run_worker(task, worktree, run_dir)
        diff = capture_diff(worktree, run_dir)
        checks = run_checks(task, worktree, run_dir)
        status = decide_status(worker, diff, checks)
        summary = {
            **lease,
            "finished_at": utc_now(),
            "status": status,
            "task_path": str(task.path),
            "worker": worker,
            "diff": diff,
            "checks": checks,
        }
        context_path = write_context_summary(task, run_dir, summary)
        summary["context_path"] = str(context_path)
        evidence_path, state_path, deep_marks_path = write_evidence_and_state(
            task, run_dir, summary, context_path
        )
        summary["evidence_path"] = str(evidence_path)
        summary["state_path"] = str(state_path)
        summary["deep_marks_path"] = str(deep_marks_path)
        write_json(run_dir / "summary.json", summary)

        retryable = status.startswith("retryable-")
        if retryable and attempt < task.max_attempts:
            attempt += 1
            continue

        done_path = DONE_DIR / f"{task.task_id}.json"
        write_json(done_path, summary)
        lease_path.unlink(missing_ok=True)
        target_task_path = DONE_DIR / task.path.name
        shutil.move(str(task.path), str(target_task_path))
        print(f"{task.task_id}: {status}")
        print(f"run: {run_dir}")
        return 0 if status in {"pass", "needs-followup", "needs-repair"} else 1

    return 1


def run_loop(args: argparse.Namespace) -> int:
    ensure_dirs()
    completed = 0
    while True:
        task = next_task()
        if not task:
            print("No queued tasks.")
            return 0
        code = run_one()
        completed += 1
        if code != 0 and not args.keep_going_on_error:
            return code
        if args.max_tasks and completed >= args.max_tasks:
            return code
        time.sleep(args.sleep_seconds)


def enqueue(args: argparse.Namespace) -> int:
    ensure_dirs()
    task_id = slugify(args.task_id)
    path = QUEUE_DIR / f"{task_id}.md"
    if path.exists():
        raise SystemExit(f"Task already exists: {path}")
    checks = "\n".join(f'  - "{item}"' for item in args.check)
    frontmatter = [
        "---",
        f'id: "{task_id}"',
        f"timeout_seconds: {args.timeout_seconds}",
        f"idle_timeout_seconds: {args.idle_timeout_seconds}",
        f"max_attempts: {args.max_attempts}",
        "checks:",
        checks,
        "---",
        "",
        args.prompt.strip(),
        "",
    ]
    path.write_text("\n".join(frontmatter), encoding="utf-8")
    print(path)
    return 0


def status() -> int:
    ensure_dirs()
    print(f"queued: {len(list(QUEUE_DIR.glob('*.md')))}")
    print(f"running: {len(list(RUNNING_DIR.glob('*.json')))}")
    print(f"done: {len(list(DONE_DIR.glob('*.json')))}")
    latest = sorted(RUNS_DIR.glob("*/summary.json"))
    if latest:
        data = json.loads(latest[-1].read_text(encoding="utf-8"))
        print(f"latest: {data['task_id']} {data['status']} {data['run_dir']}")
    return 0


def init() -> int:
    ensure_dirs()
    print(STATE_DIR)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 supervisor")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("run-one")
    sub.add_parser("status")

    loop_parser = sub.add_parser("run-loop")
    loop_parser.add_argument("--sleep-seconds", type=float, default=5.0)
    loop_parser.add_argument("--max-tasks", type=int, default=0)
    loop_parser.add_argument("--keep-going-on-error", action="store_true")

    enqueue_parser = sub.add_parser("enqueue")
    enqueue_parser.add_argument("task_id")
    enqueue_parser.add_argument("prompt")
    enqueue_parser.add_argument("--check", action="append", default=[])
    enqueue_parser.add_argument("--timeout-seconds", type=int, default=3600)
    enqueue_parser.add_argument("--idle-timeout-seconds", type=int, default=300)
    enqueue_parser.add_argument("--max-attempts", type=int, default=2)

    args = parser.parse_args(argv)
    if args.command == "init":
        return init()
    if args.command == "run-one":
        return run_one()
    if args.command == "run-loop":
        return run_loop(args)
    if args.command == "status":
        return status()
    if args.command == "enqueue":
        return enqueue(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
