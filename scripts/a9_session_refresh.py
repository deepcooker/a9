#!/usr/bin/env python3
"""Index and extract external Codex/operator sessions.

External Codex JSONL sessions are evidence sources, not A9 runtime sessions and
not mem0 memories. This tool gives A9 a bounded, testable session_refresh task:
locate turns, keep approximate JSONL line numbers, and write extracted ranges as
durable evidence for later close-reading.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Turn:
    turn: int
    line: int
    timestamp: str
    text: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_compact(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no}: invalid JSONL: {exc}") from exc
    return rows


def message_text(payload: dict[str, Any], *, assistant: bool = False) -> str:
    want = "output_text" if assistant else "input_text"
    chunks: list[str] = []
    for item in payload.get("content") or []:
        if item.get("type") == want:
            chunks.append(str(item.get("text") or ""))
    return "".join(chunks).strip()


def is_environment_context(text: str) -> bool:
    return "<environment_context>" in text


def user_turns(rows: list[dict[str, Any]]) -> list[Turn]:
    turns: list[Turn] = []
    for line_no, row in enumerate(rows, start=1):
        payload = row.get("payload") or {}
        if row.get("type") != "response_item":
            continue
        if payload.get("type") != "message" or payload.get("role") != "user":
            continue
        text = message_text(payload)
        if not text or is_environment_context(text):
            continue
        turns.append(
            Turn(
                turn=len(turns) + 1,
                line=line_no,
                timestamp=str(row.get("timestamp") or ""),
                text=text,
            )
        )
    return turns


def session_id_from_path(path: Path, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("type") == "session_meta":
            payload = row.get("payload") or {}
            if payload.get("id"):
                return str(payload["id"])
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    return f"external-session-{digest}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compact_text(text: str, limit: int = 160) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def batch_index(turns: list[Turn], batch_size: int) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    for start in range(1, len(turns) + 1, batch_size):
        end = min(start + batch_size - 1, len(turns))
        first = turns[start - 1]
        last = turns[end - 1]
        batches.append(
            {
                "turns": f"{start}-{end}",
                "from_turn": start,
                "to_turn": end,
                "approx_lines": f"{first.line}-{last.line}",
                "from_line": first.line,
                "to_line": last.line,
                "from_timestamp": first.timestamp,
                "to_timestamp": last.timestamp,
            }
        )
    return batches


def session_index(path: Path, *, batch_size: int) -> dict[str, Any]:
    rows = read_jsonl(path)
    turns = user_turns(rows)
    return {
        "kind": "external_codex_session_index",
        "session_id": session_id_from_path(path, rows),
        "source_session_path": str(path),
        "source_sha256": sha256_file(path),
        "jsonl_lines": len(rows),
        "user_turn_count": len(turns),
        "batch_size": batch_size,
        "indexed_at": utc_now(),
        "batches": batch_index(turns, batch_size),
        "turns": [
            {
                "turn": t.turn,
                "line": t.line,
                "timestamp": t.timestamp,
                "preview": compact_text(t.text, 120),
            }
            for t in turns
        ],
    }


def extract_turn_range(path: Path, from_turn: int, to_turn: int) -> dict[str, Any]:
    if from_turn < 1 or to_turn < from_turn:
        raise SystemExit("--from-turn must be >= 1 and --to-turn must be >= --from-turn")
    rows = read_jsonl(path)
    turns = user_turns(rows)
    if to_turn > len(turns):
        raise SystemExit(f"requested turn {to_turn}, but session only has {len(turns)} user turns")
    session_id = session_id_from_path(path, rows)
    output_turns: list[dict[str, Any]] = []
    for turn in turns[from_turn - 1 : to_turn]:
        next_line = turns[turn.turn].line if turn.turn < len(turns) else len(rows) + 1
        assistants: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        tool_outputs = 0
        for row in rows[turn.line : next_line - 1]:
            payload = row.get("payload") or {}
            if row.get("type") != "response_item":
                continue
            if payload.get("type") == "message" and payload.get("role") == "assistant":
                text = message_text(payload, assistant=True)
                if text:
                    assistants.append(text)
            elif payload.get("type") == "function_call":
                tool_calls.append(
                    {
                        "name": payload.get("name"),
                        "arguments_preview": compact_text(str(payload.get("arguments") or ""), 220),
                    }
                )
            elif payload.get("type") == "function_call_output":
                tool_outputs += 1
        output_turns.append(
            {
                "turn": turn.turn,
                "user_line": turn.line,
                "next_user_line": next_line if next_line <= len(rows) else None,
                "timestamp": turn.timestamp,
                "user_text": turn.text,
                "assistant_messages": assistants,
                "tool_calls": tool_calls,
                "tool_output_count": tool_outputs,
            }
        )
    return {
        "kind": "external_codex_session_extract",
        "session_id": session_id,
        "source_session_path": str(path),
        "source_sha256": sha256_file(path),
        "from_turn": from_turn,
        "to_turn": to_turn,
        "approx_lines": f"{turns[from_turn - 1].line}-{turns[to_turn - 1].line}",
        "extracted_at": utc_now(),
        "turns": output_turns,
    }


def write_refresh(path: Path, from_turn: int, to_turn: int, out_dir: Path, batch_size: int) -> dict[str, Any]:
    index = session_index(path, batch_size=batch_size)
    extract = extract_turn_range(path, from_turn, to_turn)
    session_dir = out_dir / index["session_id"]
    session_dir.mkdir(parents=True, exist_ok=True)
    index_path = session_dir / "index.json"
    extract_path = session_dir / f"turns-{from_turn}-{to_turn}.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    extract_path.write_text(json.dumps(extract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "written",
        "session_id": index["session_id"],
        "source_session_path": str(path),
        "user_turn_count": index["user_turn_count"],
        "jsonl_lines": index["jsonl_lines"],
        "index_path": str(index_path),
        "extract_path": str(extract_path),
        "from_turn": from_turn,
        "to_turn": to_turn,
        "approx_lines": extract["approx_lines"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Index and extract external Codex session JSONL")
    sub = parser.add_subparsers(dest="command", required=True)

    index_parser = sub.add_parser("index")
    index_parser.add_argument("session_jsonl")
    index_parser.add_argument("--batch-size", type=int, default=10)

    extract_parser = sub.add_parser("extract")
    extract_parser.add_argument("session_jsonl")
    extract_parser.add_argument("--from-turn", type=int, required=True)
    extract_parser.add_argument("--to-turn", type=int, required=True)

    refresh_parser = sub.add_parser("refresh")
    refresh_parser.add_argument("session_jsonl")
    refresh_parser.add_argument("--from-turn", type=int, required=True)
    refresh_parser.add_argument("--to-turn", type=int, required=True)
    refresh_parser.add_argument("--batch-size", type=int, default=10)
    refresh_parser.add_argument("--out-dir", default=str(ROOT / ".a9" / "external_sessions"))

    args = parser.parse_args()
    path = Path(args.session_jsonl)
    if not path.exists():
        raise SystemExit(f"session JSONL not found: {path}")

    if args.command == "index":
        print(json.dumps(session_index(path, batch_size=args.batch_size), ensure_ascii=False, indent=2))
    elif args.command == "extract":
        print(json.dumps(extract_turn_range(path, args.from_turn, args.to_turn), ensure_ascii=False, indent=2))
    elif args.command == "refresh":
        print(
            json.dumps(
                write_refresh(path, args.from_turn, args.to_turn, Path(args.out_dir), args.batch_size),
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
