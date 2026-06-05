#!/usr/bin/env python3
"""A9 strict-envelope worker for OpenAI-compatible chat APIs.

The script is intentionally small and dependency-free so it can be used as a
`custom_command` worker transport for OpenAI, vLLM, SGLang, NIM, or an internal
model gateway. It does not edit files directly; it writes the model's strict
worker envelope to the supervisor-provided final path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TIMEOUT_SECONDS = 120


def compact_text(value: str, limit: int = 1000) -> str:
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


def find_json_objects(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(value)
    return objects


def is_worker_envelope(value: dict[str, Any]) -> bool:
    return value.get("protocolVersion") in {1, "1"} and isinstance(value.get("ok"), bool)


def error_envelope(message: str, *, task_id: str, phase: str, declared_checks: list[str]) -> dict[str, Any]:
    return {
        "protocolVersion": 1,
        "ok": False,
        "status": "error",
        "error": {
            "type": "a9_openai_compatible_worker_error",
            "message": compact_text(message),
        },
        "output": {
            "worker_backend": "a9_openai_compatible_worker",
            "task_id": task_id,
            "phase": phase,
            "changed_files": [],
            "search_replace_blocks": [],
            "worker_commands_run": [],
            "supervisor_declared_checks": declared_checks,
            "next_slice": "Fix the OpenAI-compatible worker configuration or model envelope output.",
        },
    }


def strict_envelope_instruction(task_id: str, phase: str, declared_checks: list[str]) -> str:
    return (
        "You are an A9 custom worker. Return exactly one valid JSON object and no Markdown. "
        "The object must follow this protocol: "
        '{"protocolVersion":1,"ok":true,"status":"ok","output":{...}}. '
        "Do not edit files directly and do not run shell commands. If file changes are needed, "
        "put deterministic SEARCH/REPLACE entries in output.search_replace_blocks. "
        "Always include output.changed_files, output.worker_commands_run, "
        "output.supervisor_declared_checks, output.copied_mechanisms, output.files_validated, "
        "output.repo_metadata_evidence, and output.next_slice. "
        f"task_id={task_id}; phase={phase}; supervisor_declared_checks={json.dumps(declared_checks, ensure_ascii=False)}."
    )


def chat_completion_request(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    task_id: str,
    phase: str,
    declared_checks: list[str],
    timeout_seconds: int,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": strict_envelope_instruction(task_id, phase, declared_checks),
            },
            {"role": "user", "content": prompt},
        ],
    }
    temperature = os.getenv("A9_LLM_WORKER_TEMPERATURE", "").strip()
    if temperature:
        payload["temperature"] = float(temperature)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        response_body = response.read().decode("utf-8", errors="backslashreplace")
    data = json.loads(response_body)
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("chat completion response missing choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("chat completion response missing message.content")
    return content


def write_final(path: Path, value: str | dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, dict):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    path.write_text(value.strip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--final-path", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--model", default=os.getenv("A9_LLM_WORKER_MODEL", ""))
    parser.add_argument("--base-url", default=os.getenv("A9_LLM_WORKER_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key-env", default="A9_LLM_WORKER_API_KEY")
    parser.add_argument("--timeout-seconds", type=int, default=int(os.getenv("A9_LLM_WORKER_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)))
    args = parser.parse_args()

    prompt = args.prompt_file.read_text(encoding="utf-8", errors="backslashreplace")
    declared_checks = extract_declared_checks(prompt)
    api_key = os.getenv(args.api_key_env) or os.getenv("OPENAI_API_KEY", "")
    model = str(args.model or "").strip()
    print(json.dumps({"type": "thread.started", "worker": "a9_openai_compatible_worker"}, ensure_ascii=False), flush=True)
    try:
        if not api_key:
            raise RuntimeError(f"missing API key env: {args.api_key_env} or OPENAI_API_KEY")
        if not model:
            raise RuntimeError("missing model: pass --model or set A9_LLM_WORKER_MODEL")
        content = chat_completion_request(
            base_url=args.base_url,
            api_key=api_key,
            model=model,
            prompt=prompt,
            task_id=args.task_id,
            phase=args.phase,
            declared_checks=declared_checks,
            timeout_seconds=max(1, args.timeout_seconds),
        )
        envelopes = [item for item in find_json_objects(content) if is_worker_envelope(item)]
        if not envelopes:
            raise RuntimeError("model response did not contain a valid A9 strict worker envelope")
        write_final(args.final_path, envelopes[-1])
        print(json.dumps({"type": "thread.completed", "status": "ok"}, ensure_ascii=False), flush=True)
        return 0
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        write_final(
            args.final_path,
            error_envelope(str(exc), task_id=args.task_id, phase=args.phase, declared_checks=declared_checks),
        )
        print(
            json.dumps(
                {"type": "thread.failed", "status": "error", "error": compact_text(str(exc), 500)},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
