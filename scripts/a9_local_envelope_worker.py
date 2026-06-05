#!/usr/bin/env python3
"""Deterministic local worker for A9 transport smoke and fallback records.

This is not an LLM replacement. It proves that the A9 supervisor can run a
non-Codex worker transport, parse a strict worker envelope, execute declared
checks, and write normal run evidence when Codex exec transport is unhealthy.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def compact_text(value: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def extract_declared_checks(prompt: str) -> list[str]:
    lines = prompt.splitlines()
    checks: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and in_section:
            break
        if stripped.lower() == "# task declared checks":
            in_section = True
            continue
        if not in_section or not stripped.startswith("- "):
            continue
        item = stripped[2:].strip()
        if item and item.lower() != "none":
            checks.append(item)
    return checks


def build_envelope(args: argparse.Namespace, prompt: str) -> dict[str, Any]:
    declared_checks = extract_declared_checks(prompt)
    return {
        "protocolVersion": 1,
        "ok": True,
        "status": "ok",
        "output": {
            "worker_backend": "a9_local_envelope_worker",
            "task_id": args.task_id,
            "phase": args.phase,
            "summary": compact_text(args.summary or "local envelope worker completed without repository edits"),
            "changed_files": [],
            "search_replace_blocks": [],
            "worker_commands_run": [],
            "supervisor_declared_checks": declared_checks,
            "copied_mechanisms": [],
            "files_validated": [],
            "repo_metadata_evidence": [str(args.prompt_file)],
            "next_slice": compact_text(
                args.next_slice
                or "operator_handoff: local envelope smoke completed; use a real LLM-capable backend for the next task.",
                700,
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--final-path", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--summary", default="")
    parser.add_argument("--next-slice", default="")
    args = parser.parse_args()

    prompt = args.prompt_file.read_text(encoding="utf-8", errors="backslashreplace")
    envelope = build_envelope(args, prompt)
    args.final_path.parent.mkdir(parents=True, exist_ok=True)
    args.final_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"type": "thread.started", "worker": "a9_local_envelope_worker"}, ensure_ascii=False), flush=True)
    print(json.dumps({"type": "thread.completed", "status": "ok"}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
