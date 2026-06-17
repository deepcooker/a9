#!/usr/bin/env python3
"""Convert Codex raw session JSONL into MemPalace-compatible drawer records.

This is the new primary adapter for external Codex/operator sessions. It keeps
the raw JSONL as the fact source and emits one traceable record per user,
assistant or tool event. It does not summarize and does not decide truth.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PALACE = ROOT / ".a9" / "mempalace"
DEFAULT_NATIVE_WING = "operator-codex-native"
DEFAULT_NATIVE_ROOM = "codex-message"
MEMPALACE_SOURCE = ROOT / "reference-projects" / "mempalace"
NATIVE_CHUNK_CHARS = 8000
DEFAULT_DRAWERS = DEFAULT_PALACE / "operator-session-drawers.jsonl"
DEFAULT_CURSOR = DEFAULT_PALACE / "operator-session-ingest-cursor.json"


@contextlib.contextmanager
def suppress_native_stderr() -> Iterable[None]:
    saved = os.dup(2)
    try:
        with open(os.devnull, "w", encoding="utf-8") as sink:
            os.dup2(sink.fileno(), 2)
            yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)


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


def source_fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"incremental-unhashed:size={stat.st_size}:mtime_ns={stat.st_mtime_ns}"


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


def read_jsonl_from_offset(
    path: Path,
    *,
    offset: int,
    start_line: int,
) -> tuple[list[tuple[int, str, dict[str, Any]]], int, int]:
    rows: list[tuple[int, str, dict[str, Any]]] = []
    with path.open("rb") as handle:
        handle.seek(offset)
        line_no = start_line
        while True:
            raw_bytes = handle.readline()
            if not raw_bytes:
                break
            line_no += 1
            raw_line = raw_bytes.rstrip(b"\n").decode("utf-8")
            if not raw_line.strip():
                continue
            try:
                rows.append((line_no, raw_line, json.loads(raw_line)))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no}: invalid JSONL: {exc}") from exc
        return rows, handle.tell(), line_no


def read_cursor(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: invalid cursor JSON: {exc}") from exc


def write_cursor(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_last_jsonl_record(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        raise SystemExit(f"drawer JSONL is empty or missing: {path}")
    with path.open("rb") as handle:
        position = handle.seek(0, os.SEEK_END)
        buffer = bytearray()
        while position > 0:
            position -= 1
            handle.seek(position)
            char = handle.read(1)
            if char == b"\n" and buffer:
                break
            if char != b"\n":
                buffer.extend(char)
        line = bytes(reversed(buffer)).decode("utf-8")
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: invalid last drawer JSONL record: {exc}") from exc


def byte_offset_after_line(path: Path, target_line: int) -> int:
    if target_line <= 0:
        return 0
    with path.open("rb") as handle:
        for line_no, _ in enumerate(handle, start=1):
            if line_no >= target_line:
                return handle.tell()
        return handle.tell()


def ordinal_from_drawer(record: dict[str, Any]) -> int:
    message_id = str(record.get("message_id") or record.get("drawer_id") or "")
    match = re.search(r":(\d+)$", message_id)
    if match:
        return int(match.group(1))
    return int(record.get("ordinal") or 0)


def init_incremental_cursor_from_drawers(
    session_path: Path,
    *,
    drawers_path: Path = DEFAULT_DRAWERS,
    cursor_path: Path = DEFAULT_CURSOR,
    dry_run: bool = False,
) -> dict[str, Any]:
    last = read_last_jsonl_record(drawers_path)
    source_path = str(last.get("source_path") or "")
    if source_path and source_path != str(session_path):
        raise SystemExit(
            f"last drawer source_path does not match session: {source_path} != {session_path}"
        )
    source_line = int(last.get("source_line") or 0)
    byte_offset = byte_offset_after_line(session_path, source_line)
    payload = {
        "schema": "a9.codex_session_incremental_cursor.v1",
        "source_session_path": str(session_path),
        "source_sha256": str(last.get("source_sha256") or source_fingerprint(session_path)),
        "session_id": str(last.get("session_id") or f"external-session-{sha256_text(str(session_path))[:12]}"),
        "byte_offset": byte_offset,
        "line_no": source_line,
        "ordinal": ordinal_from_drawer(last),
        "drawers_path": str(drawers_path),
        "updated_at": utc_now(),
        "initialized_from": "last_drawer_record",
        "last_drawer_id": str(last.get("drawer_id") or ""),
    }
    if not dry_run:
        write_cursor(cursor_path, payload)
    return {
        "status": "dry-run" if dry_run else "written",
        "schema": "a9.codex_session_incremental_cursor_init.v1",
        "cursor_path": str(cursor_path),
        **payload,
    }


def session_id_from_rows(path: Path, rows: list[tuple[int, str, dict[str, Any]]]) -> str:
    for _, _, row in rows:
        if row.get("type") == "session_meta":
            payload = row.get("payload") or {}
            if payload.get("id"):
                return str(payload["id"])
    return f"external-session-{sha256_text(str(path))[:12]}"


def session_id_from_rows_or_cursor(
    path: Path,
    rows: list[tuple[int, str, dict[str, Any]]],
    cursor: dict[str, Any],
) -> str:
    if cursor.get("session_id"):
        return str(cursor["session_id"])
    return session_id_from_rows(path, rows)


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


def rows_to_drawers(
    path: Path,
    *,
    rows: list[tuple[int, str, dict[str, Any]]],
    session_id: str,
    source_sha256: str,
    start_ordinal: int = 0,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    ordinal = start_ordinal
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
                    metadata={"payload_type": payload_type, "ingest_mode": "incremental"},
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
                    metadata={"tool_name": name, "call_id": payload.get("call_id"), "ingest_mode": "incremental"},
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
                    metadata={"call_id": payload.get("call_id"), "ingest_mode": "incremental"},
                )
            )
    return records


def append_drawers(records: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def native_upsert_records(
    records: list[dict[str, Any]],
    *,
    palace: Path = DEFAULT_PALACE,
    wing: str = DEFAULT_NATIVE_WING,
    include_tools: bool = False,
    context_only: bool = False,
    rewrite_existing: bool = False,
    chunk_chars: int = NATIVE_CHUNK_CHARS,
    agent: str = "a9-monitor",
    dry_run: bool = False,
) -> dict[str, Any]:
    ids, docs, metas = native_documents_from_records(
        records,
        wing=wing,
        include_tools=include_tools,
        context_only=context_only,
        chunk_chars=chunk_chars,
        agent=agent,
    )
    if dry_run:
        return {"native_docs": len(docs), "native_added": 0, "native_already_present": 0, "native_rewritten": 0}
    if not ids:
        return {"native_docs": 0, "native_added": 0, "native_already_present": 0, "native_rewritten": 0}
    get_collection = import_mempalace_get_collection()
    with suppress_native_stderr():
        collection = get_collection(str(palace), create=True)
    existing_count = 0
    added_count = 0
    rewritten_count = 0
    batch_size = 128
    for start in range(0, len(ids), batch_size):
        batch_ids = ids[start : start + batch_size]
        batch_docs = docs[start : start + batch_size]
        batch_metas = metas[start : start + batch_size]
        try:
            existing = collection.get(ids=batch_ids, include=[])
            present = set(existing.get("ids") or [])
        except Exception:
            present = set()
        existing_count += len(present)
        write_indexes = [
            index for index, drawer_id in enumerate(batch_ids) if rewrite_existing or drawer_id not in present
        ]
        added_count += sum(1 for index in write_indexes if batch_ids[index] not in present)
        rewritten_count += sum(1 for index in write_indexes if batch_ids[index] in present)
        if not write_indexes:
            continue
        with suppress_native_stderr():
            collection.upsert(
                ids=[batch_ids[index] for index in write_indexes],
                documents=[batch_docs[index] for index in write_indexes],
                metadatas=[batch_metas[index] for index in write_indexes],
            )
    return {
        "native_docs": len(docs),
        "native_added": added_count,
        "native_already_present": existing_count,
        "native_rewritten": rewritten_count,
    }


def incremental_ingest(
    path: Path,
    *,
    out_path: Path = DEFAULT_DRAWERS,
    cursor_path: Path = DEFAULT_CURSOR,
    source_sha256: str | None = None,
    native: bool = False,
    palace: Path = DEFAULT_PALACE,
    wing: str = DEFAULT_NATIVE_WING,
    include_tools: bool = False,
    context_only: bool = False,
    rewrite_existing: bool = False,
    chunk_chars: int = NATIVE_CHUNK_CHARS,
    agent: str = "a9-monitor",
    dry_run: bool = False,
) -> dict[str, Any]:
    cursor = read_cursor(cursor_path)
    cursor_source = str(cursor.get("source_session_path") or "")
    offset = int(cursor.get("byte_offset") or 0) if cursor_source in {"", str(path)} else 0
    start_line = int(cursor.get("line_no") or 0) if cursor_source in {"", str(path)} else 0
    start_ordinal = int(cursor.get("ordinal") or 0) if cursor_source in {"", str(path)} else 0
    if path.stat().st_size < offset:
        offset = 0
        start_line = 0
        start_ordinal = 0

    rows, new_offset, new_line = read_jsonl_from_offset(path, offset=offset, start_line=start_line)
    session_id = session_id_from_rows_or_cursor(path, rows, cursor if offset > 0 else {})
    effective_source_sha256 = source_sha256 or str(cursor.get("source_sha256") or "") or source_fingerprint(path)
    records = rows_to_drawers(
        path,
        rows=rows,
        session_id=session_id,
        source_sha256=effective_source_sha256,
        start_ordinal=start_ordinal,
    )
    native_result = {
        "native_docs": 0,
        "native_added": 0,
        "native_already_present": 0,
        "native_rewritten": 0,
    }
    if not dry_run:
        append_drawers(records, out_path)
    if native:
        native_result = native_upsert_records(
            records,
            palace=palace,
            wing=wing,
            include_tools=include_tools,
            context_only=context_only,
            rewrite_existing=rewrite_existing,
            chunk_chars=chunk_chars,
            agent=agent,
            dry_run=dry_run,
        )

    next_ordinal = start_ordinal + len(records)
    next_cursor = {
        "schema": "a9.codex_session_incremental_cursor.v1",
        "source_session_path": str(path),
        "source_sha256": effective_source_sha256,
        "session_id": session_id,
        "byte_offset": new_offset,
        "line_no": new_line,
        "ordinal": next_ordinal,
        "drawers_path": str(out_path),
        "updated_at": utc_now(),
    }
    if not dry_run:
        write_cursor(cursor_path, next_cursor)
    return {
        "status": "dry-run" if dry_run else "written",
        "schema": "a9.codex_session_incremental_ingest.v1",
        "session_id": session_id,
        "source_session_path": str(path),
        "previous_byte_offset": offset,
        "byte_offset": new_offset,
        "previous_line_no": start_line,
        "line_no": new_line,
        "rows_read": len(rows),
        "drawers_written": len(records) if not dry_run else 0,
        "drawers_found": len(records),
        "out_path": str(out_path),
        "cursor_path": str(cursor_path),
        **native_result,
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


def chunk_text(text: str, limit: int = NATIVE_CHUNK_CHARS) -> list[str]:
    if limit <= 0:
        raise ValueError("chunk limit must be positive")
    if not text:
        return []
    return [text[index : index + limit] for index in range(0, len(text), limit)]


def native_room_for(record: dict[str, Any]) -> str:
    if is_context_injection(str(record.get("content") or "")):
        return "codex-context"
    return "codex-tool" if str(record.get("event_kind") or "").startswith("tool_") else DEFAULT_NATIVE_ROOM


def is_context_injection(content: str) -> bool:
    text = (content or "").lstrip()
    return text.startswith("# AGENTS.md instructions for ") or (
        "<INSTRUCTIONS>" in text and "<environment_context>" in text
    )


def native_drawer_id(record: dict[str, Any], chunk_index: int) -> str:
    basis = "|".join(
        [
            str(record.get("session_id") or ""),
            str(record.get("source_line") or ""),
            str(record.get("event_kind") or ""),
            str(record.get("role") or ""),
            str(chunk_index),
            str(record.get("content_hash") or ""),
        ]
    )
    return f"a9_codex_{sha256_text(basis)[:32]}"


def native_documents_from_records(
    records: Iterable[dict[str, Any]],
    *,
    wing: str = DEFAULT_NATIVE_WING,
    include_tools: bool = False,
    context_only: bool = False,
    chunk_chars: int = NATIVE_CHUNK_CHARS,
    agent: str = "a9-monitor",
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict[str, Any]] = []
    for record in records:
        event_kind = str(record.get("event_kind") or "")
        if event_kind.startswith("tool_") and not include_tools:
            continue
        if context_only and not is_context_injection(str(record.get("content") or "")):
            continue
        content = str(record.get("content") or "")
        chunks = chunk_text(content, chunk_chars)
        for index, chunk in enumerate(chunks):
            ids.append(native_drawer_id(record, index))
            docs.append(chunk)
            metas.append(
                {
                    "wing": wing,
                    "room": native_room_for(record),
                    "hall": "technical",
                    "source_file": str(record.get("source_path") or ""),
                    "source_ref": str(record.get("source_ref") or ""),
                    "source_sha256": str(record.get("source_sha256") or ""),
                    "raw_line_sha256": str(record.get("raw_line_sha256") or ""),
                    "content_hash": str(record.get("content_hash") or ""),
                    "session_id": str(record.get("session_id") or ""),
                    "source_line": int(record.get("source_line") or 0),
                    "role": str(record.get("role") or ""),
                    "event_kind": event_kind,
                    "message_id": str(record.get("message_id") or ""),
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                    "added_by": agent,
                    "filed_at": utc_now(),
                    "ingest_mode": "a9_codex_session_native",
                    "source_type": "codex_jsonl",
                    "schema": "a9.mempalace.native_codex_drawer.v1",
                }
            )
    return ids, docs, metas


def import_mempalace_get_collection():
    if not MEMPALACE_SOURCE.exists():
        raise SystemExit(f"MemPalace source not found: {MEMPALACE_SOURCE}")
    import sys

    sys.path.insert(0, str(MEMPALACE_SOURCE))
    with suppress_native_stderr():
        from mempalace.palace import get_collection  # type: ignore

    return get_collection


def native_sweep(
    path: Path,
    *,
    palace: Path = DEFAULT_PALACE,
    wing: str = DEFAULT_NATIVE_WING,
    include_tools: bool = False,
    context_only: bool = False,
    rewrite_existing: bool = False,
    chunk_chars: int = NATIVE_CHUNK_CHARS,
    agent: str = "a9-monitor",
    dry_run: bool = False,
) -> dict[str, Any]:
    payload = codex_jsonl_to_drawers(path)
    ids, docs, metas = native_documents_from_records(
        payload["records"],
        wing=wing,
        include_tools=include_tools,
        context_only=context_only,
        chunk_chars=chunk_chars,
        agent=agent,
    )
    if dry_run:
        return {
            "status": "dry-run",
            "session_id": payload["session_id"],
            "source_session_path": payload["source_session_path"],
            "source_sha256": payload["source_sha256"],
            "native_ids": len(ids),
            "native_docs": len(docs),
            "include_tools": include_tools,
            "context_only": context_only,
            "rewrite_existing": rewrite_existing,
            "wing": wing,
            "palace": str(palace),
        }
    get_collection = import_mempalace_get_collection()
    with suppress_native_stderr():
        collection = get_collection(str(palace), create=True)
    existing_count = 0
    added_count = 0
    rewritten_count = 0
    batch_size = 128
    for start in range(0, len(ids), batch_size):
        batch_ids = ids[start : start + batch_size]
        batch_docs = docs[start : start + batch_size]
        batch_metas = metas[start : start + batch_size]
        try:
            existing = collection.get(ids=batch_ids, include=[])
            present = set(existing.get("ids") or [])
        except Exception:
            present = set()
        existing_count += len(present)
        write_indexes = [
            index for index, drawer_id in enumerate(batch_ids) if rewrite_existing or drawer_id not in present
        ]
        added_count += sum(1 for index in write_indexes if batch_ids[index] not in present)
        rewritten_count += sum(1 for index in write_indexes if batch_ids[index] in present)
        if not write_indexes:
            continue
        with suppress_native_stderr():
            collection.upsert(
                ids=[batch_ids[index] for index in write_indexes],
                documents=[batch_docs[index] for index in write_indexes],
                metadatas=[batch_metas[index] for index in write_indexes],
            )
    return {
        "status": "written",
        "schema": "a9.mempalace.native_codex_sweep.v1",
        "session_id": payload["session_id"],
        "source_session_path": payload["source_session_path"],
        "source_sha256": payload["source_sha256"],
        "native_docs": len(docs),
        "native_added": added_count,
        "native_already_present": existing_count,
        "native_rewritten": rewritten_count,
        "include_tools": include_tools,
        "context_only": context_only,
        "rewrite_existing": rewrite_existing,
        "wing": wing,
        "palace": str(palace),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Codex session JSONL to MemPalace drawer JSONL")
    sub = parser.add_subparsers(dest="command", required=True)

    convert = sub.add_parser("convert")
    convert.add_argument("session_jsonl")
    convert.add_argument("--out", help="Write newline-delimited drawer records to this path")
    convert.add_argument("--pretty", action="store_true", help="Print a pretty JSON envelope instead of JSONL")

    native = sub.add_parser("native-sweep")
    native.add_argument("session_jsonl")
    native.add_argument("--palace", default=str(DEFAULT_PALACE))
    native.add_argument("--wing", default=DEFAULT_NATIVE_WING)
    native.add_argument("--agent", default="a9-monitor")
    native.add_argument("--chunk-chars", type=int, default=NATIVE_CHUNK_CHARS)
    native.add_argument("--include-tools", action="store_true")
    native.add_argument("--context-only", action="store_true")
    native.add_argument("--rewrite-existing", action="store_true")
    native.add_argument("--dry-run", action="store_true")

    incremental = sub.add_parser("incremental")
    incremental.add_argument("session_jsonl")
    incremental.add_argument("--out", default=str(DEFAULT_DRAWERS))
    incremental.add_argument("--cursor", default=str(DEFAULT_CURSOR))
    incremental.add_argument("--source-sha256")
    incremental.add_argument("--native", action="store_true")
    incremental.add_argument("--palace", default=str(DEFAULT_PALACE))
    incremental.add_argument("--wing", default=DEFAULT_NATIVE_WING)
    incremental.add_argument("--agent", default="a9-monitor")
    incremental.add_argument("--chunk-chars", type=int, default=NATIVE_CHUNK_CHARS)
    incremental.add_argument("--include-tools", action="store_true")
    incremental.add_argument("--context-only", action="store_true")
    incremental.add_argument("--rewrite-existing", action="store_true")
    incremental.add_argument("--dry-run", action="store_true")

    init_cursor = sub.add_parser("init-cursor")
    init_cursor.add_argument("session_jsonl")
    init_cursor.add_argument("--drawers", default=str(DEFAULT_DRAWERS))
    init_cursor.add_argument("--cursor", default=str(DEFAULT_CURSOR))
    init_cursor.add_argument("--dry-run", action="store_true")

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
    elif args.command == "native-sweep":
        print(
            json.dumps(
                native_sweep(
                    session_path,
                    palace=Path(args.palace),
                    wing=args.wing,
                    include_tools=args.include_tools,
                    context_only=args.context_only,
                    rewrite_existing=args.rewrite_existing,
                    chunk_chars=args.chunk_chars,
                    agent=args.agent,
                    dry_run=args.dry_run,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    elif args.command == "incremental":
        print(
            json.dumps(
                incremental_ingest(
                    session_path,
                    out_path=Path(args.out),
                    cursor_path=Path(args.cursor),
                    source_sha256=args.source_sha256,
                    native=args.native,
                    palace=Path(args.palace),
                    wing=args.wing,
                    include_tools=args.include_tools,
                    context_only=args.context_only,
                    rewrite_existing=args.rewrite_existing,
                    chunk_chars=args.chunk_chars,
                    agent=args.agent,
                    dry_run=args.dry_run,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    elif args.command == "init-cursor":
        print(
            json.dumps(
                init_incremental_cursor_from_drawers(
                    session_path,
                    drawers_path=Path(args.drawers),
                    cursor_path=Path(args.cursor),
                    dry_run=args.dry_run,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
