#!/usr/bin/env python3
"""Convert Codex raw session JSONL into MemPalace-compatible drawer records.

This is the new primary adapter for external Codex/operator sessions. It keeps
the raw JSONL as the fact source and emits one traceable record per user,
assistant or tool event. It does not summarize and does not decide truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl_with_lines(path: Path) -> list[tuple[int, str, dict[str, Any]]]:
    rows: list[tuple[int, str, dict[str, Any]]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            raw_line = line.rstrip("\n")
            if not raw_line.strip():
                continue
            try:
                rows.append((line_no, raw_line, json.loads(raw_line)))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no}: invalid JSONL: {exc}") from exc
    return rows


def session_id_from_rows(path: Path, rows: list[tuple[int, str, dict[str, Any]]]) -> str:
    for _, _, row in rows:
        if row.get("type") == "session_meta":
            payload = row.get("payload") or {}
            if payload.get("id"):
                return str(payload["id"])
    return f"external-session-{sha256_text(str(path))[:12]}"


def content_text(payload: dict[str, Any], role: str) -> str:
    want = "output_text" if role == "assistant" else "input_text"
    chunks: list[str] = []
    for item in payload.get("content") or []:
        if item.get("type") == want:
            chunks.append(str(item.get("text") or ""))
    return "".join(chunks).strip()


def compact_tool_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def drawer_record(
    *,
    session_id: str,
    source_path: Path,
    source_sha256: str,
    source_line: int,
    raw_line: str,
    row: dict[str, Any],
    event_kind: str,
    role: str,
    content: str,
    ordinal: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = str(row.get("timestamp") or "")
    raw_hash = sha256_text(raw_line)
    content_hash = sha256_text(content)
    message_id = f"{session_id}:L{source_line}:{event_kind}:{ordinal}"
    return {
        "schema": "a9.mempalace.drawer.v1",
        "message_id": message_id,
        "drawer_id": message_id,
        "session_id": session_id,
        "source_type": "codex_jsonl",
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "source_line": source_line,
        "source_ref": f"{source_path}:{source_line}",
        "raw_line_sha256": raw_hash,
        "role": role,
        "event_kind": event_kind,
        "timestamp": timestamp,
        "content": content,
        "content_hash": content_hash,
        "palace_path": "operator/codex/session",
        "wing": "operator",
        "room": "codex-session",
        "closet": event_kind,
        "tags": ["a9", "operator-session", "codex-jsonl", event_kind, role],
        "metadata": metadata or {},
    }


def codex_jsonl_to_drawers(path: Path) -> dict[str, Any]:
    rows = read_jsonl_with_lines(path)
    session_id = session_id_from_rows(path, rows)
    source_sha256 = sha256_file(path)
    records: list[dict[str, Any]] = []
    ordinal = 0
    for source_line, raw_line, row in rows:
        payload = row.get("payload") or {}
        if row.get("type") != "response_item":
            continue
        payload_type = payload.get("type")
        if payload_type == "message":
            role = str(payload.get("role") or "unknown")
            content = content_text(payload, role)
            if not content:
                continue
            ordinal += 1
            records.append(
                drawer_record(
                    session_id=session_id,
                    source_path=path,
                    source_sha256=source_sha256,
                    source_line=source_line,
                    raw_line=raw_line,
                    row=row,
                    event_kind="message",
                    role=role,
                    content=content,
                    ordinal=ordinal,
                    metadata={"payload_type": payload_type},
                )
            )
        elif payload_type == "function_call":
            name = str(payload.get("name") or "unknown_tool")
            content = compact_tool_payload(payload.get("arguments") or "")
            ordinal += 1
            records.append(
                drawer_record(
                    session_id=session_id,
                    source_path=path,
                    source_sha256=source_sha256,
                    source_line=source_line,
                    raw_line=raw_line,
                    row=row,
                    event_kind="tool_call",
                    role="tool",
                    content=content,
                    ordinal=ordinal,
                    metadata={"tool_name": name, "call_id": payload.get("call_id")},
                )
            )
        elif payload_type == "function_call_output":
            content = compact_tool_payload(payload.get("output") or "")
            ordinal += 1
            records.append(
                drawer_record(
                    session_id=session_id,
                    source_path=path,
                    source_sha256=source_sha256,
                    source_line=source_line,
                    raw_line=raw_line,
                    row=row,
                    event_kind="tool_output",
                    role="tool",
                    content=content,
                    ordinal=ordinal,
                    metadata={"call_id": payload.get("call_id")},
                )
            )
    return {
        "kind": "a9_codex_session_mempalace_drawers",
        "schema": "a9.mempalace.drawer_set.v1",
        "session_id": session_id,
        "source_session_path": str(path),
        "source_sha256": source_sha256,
        "jsonl_lines": len(rows),
        "drawer_count": len(records),
        "generated_at": utc_now(),
        "records": records,
    }


def write_drawers(path: Path, out_path: Path) -> dict[str, Any]:
    payload = codex_jsonl_to_drawers(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in payload["records"]:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "status": "written",
        "session_id": payload["session_id"],
        "source_session_path": payload["source_session_path"],
        "source_sha256": payload["source_sha256"],
        "drawer_count": payload["drawer_count"],
        "out_path": str(out_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Codex session JSONL to MemPalace drawer JSONL")
    sub = parser.add_subparsers(dest="command", required=True)

    convert = sub.add_parser("convert")
    convert.add_argument("session_jsonl")
    convert.add_argument("--out", help="Write newline-delimited drawer records to this path")
    convert.add_argument("--pretty", action="store_true", help="Print a pretty JSON envelope instead of JSONL")

    args = parser.parse_args()
    session_path = Path(args.session_jsonl)
    if not session_path.exists():
        raise SystemExit(f"session JSONL not found: {session_path}")

    if args.command == "convert":
        if args.out:
            print(json.dumps(write_drawers(session_path, Path(args.out)), ensure_ascii=False, indent=2))
        else:
            payload = codex_jsonl_to_drawers(session_path)
            if args.pretty:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                for record in payload["records"]:
                    print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
