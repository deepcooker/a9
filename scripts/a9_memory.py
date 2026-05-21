#!/usr/bin/env python3
"""A9 memory adapter.

Mem0 is the reference shape: add/search/get_all/history with scoped filters,
metadata, and evidence links. This adapter keeps A9's canonical store in MySQL
and hot retrieval docs in Redis Stack, so Python owns memory business logic while
Rust can own gateway/governance.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_compact(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def sql_quote(value: Any) -> str:
    if value is None:
        return "NULL"
    text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def mysql(sql: str) -> subprocess.CompletedProcess[str]:
    return run(
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
            "-NBe",
            sql,
        ]
    )


def mysql_stdin(sql: str) -> subprocess.CompletedProcess[str]:
    return run(
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
        input_text=sql,
    )


def redis(args: list[str]) -> subprocess.CompletedProcess[str]:
    return run(["docker", "exec", "a9-redis", "redis-cli", *args])


def memory_payload(args: argparse.Namespace, memory_id: str) -> dict[str, Any]:
    return {
        "memory_id": memory_id,
        "project_id": args.project_id,
        "user_id": args.user_id,
        "agent_id": args.agent_id,
        "run_id": args.run_id,
        "memory_type": args.memory_type,
        "memory": args.memory,
        "confidence": args.confidence,
        "evidence_ids": args.evidence_id,
        "supersedes": args.supersedes,
        "metadata": parse_metadata(args.metadata),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def parse_metadata(items: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"metadata must be key=value: {item}")
        key, value = item.split("=", 1)
        metadata[key] = value
    return metadata


def tokenize(text: str) -> set[str]:
    return {part.lower() for part in text.replace("_", " ").replace("-", " ").split() if part}


def normalize_bm25(raw_score: float, midpoint: float, steepness: float) -> float:
    return 1.0 / (1.0 + math.exp(-steepness * (raw_score - midpoint)))


def bm25_params(query: str) -> tuple[float, float]:
    terms = len(tokenize(query)) or 1
    if terms <= 3:
        return 5.0, 0.7
    if terms <= 6:
        return 7.0, 0.6
    if terms <= 9:
        return 9.0, 0.5
    if terms <= 15:
        return 10.0, 0.5
    return 12.0, 0.5


def lexical_score(query: str, memory: str) -> float:
    query_terms = tokenize(query)
    memory_terms = tokenize(memory)
    if not query_terms or not memory_terms:
        return 0.0
    overlap = len(query_terms & memory_terms)
    raw = overlap * 3.0
    if query.lower() in memory.lower():
        raw += 4.0
    midpoint, steepness = bm25_params(query)
    return normalize_bm25(raw, midpoint, steepness)


def format_ranked(rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        "\t".join(
            [
                item["memory_id"],
                item["memory_type"],
                f"{item['score']:.4f}",
                f"{item['confidence']:.3f}",
                item["memory"],
            ]
        )
        for item in rows
    )


def add_memory(args: argparse.Namespace) -> int:
    memory_id = str(uuid.uuid4())
    payload = memory_payload(args, memory_id)
    sql = f"""
INSERT INTO memories (
  memory_id, project_id, user_id, agent_id, run_id, memory_type, memory,
  confidence, evidence_ids, supersedes, metadata
) VALUES (
  {sql_quote(memory_id)},
  {sql_quote(payload['project_id'])},
  {sql_quote(payload['user_id'])},
  {sql_quote(payload['agent_id'])},
  {sql_quote(payload['run_id'])},
  {sql_quote(payload['memory_type'])},
  {sql_quote(payload['memory'])},
  {float(payload['confidence'])},
  {sql_quote(json_compact(payload['evidence_ids']))},
  {sql_quote(json_compact(payload['supersedes']))},
  {sql_quote(json_compact(payload['metadata']))}
);
INSERT INTO memory_history (memory_id, action, previous_value, new_value)
VALUES ({sql_quote(memory_id)}, 'ADD', NULL, {sql_quote(json_compact(payload))});
"""
    result = mysql_stdin(sql)
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        return result.returncode
    redis(["JSON.SET", f"a9:memory:{memory_id}", "$", json_compact(payload)])
    redis(
        [
            "XADD",
            "a9:events",
            "*",
            "type",
            "memory_added",
            "memory_id",
            memory_id,
            "project_id",
            payload["project_id"],
            "memory_type",
            payload["memory_type"],
        ]
    )
    print(json.dumps({"memory_id": memory_id, "status": "added"}, ensure_ascii=False))
    return 0


def search_memory(args: argparse.Namespace) -> int:
    sql = f"""
SELECT memory_id, memory_type, confidence, memory, UNIX_TIMESTAMP(updated_at)
FROM memories
WHERE project_id={sql_quote(args.project_id)}
ORDER BY updated_at DESC
LIMIT {max(int(args.limit) * 4, 40)};
"""
    result = mysql(sql)
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        return result.returncode
    rows: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 4)
        if len(parts) < 5:
            continue
        memory_id, memory_type, confidence, memory, updated_at = parts
        confidence_f = float(confidence or 0.0)
        lexical = lexical_score(args.query, memory)
        type_boost = 0.08 if memory_type in {"decision", "procedure", "risk"} else 0.0
        confidence_boost = min(confidence_f, 1.0) * 0.12
        score = min(1.0, lexical + type_boost + confidence_boost)
        if score < args.threshold:
            continue
        rows.append(
            {
                "memory_id": memory_id,
                "memory_type": memory_type,
                "confidence": confidence_f,
                "memory": memory,
                "updated_at": float(updated_at or 0.0),
                "score": score,
            }
        )
    rows.sort(key=lambda item: (item["score"], item["updated_at"]), reverse=True)
    print(format_ranked(rows[: args.limit]))
    return 0


def get_all(args: argparse.Namespace) -> int:
    sql = f"""
SELECT memory_id, memory_type, confidence, memory
FROM memories
WHERE project_id={sql_quote(args.project_id)}
ORDER BY updated_at DESC
LIMIT {int(args.limit)};
"""
    result = mysql(sql)
    print(result.stdout)
    return result.returncode


def history(args: argparse.Namespace) -> int:
    sql = f"""
SELECT history_id, action, created_at, new_value
FROM memory_history
WHERE memory_id={sql_quote(args.memory_id)}
ORDER BY history_id ASC;
"""
    result = mysql(sql)
    print(result.stdout)
    return result.returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 memory adapter")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add")
    add.add_argument("memory")
    add.add_argument("--project-id", default="a9")
    add.add_argument("--user-id")
    add.add_argument("--agent-id", default="a9")
    add.add_argument("--run-id")
    add.add_argument("--memory-type", default="fact")
    add.add_argument("--confidence", type=float, default=0.8)
    add.add_argument("--evidence-id", action="append", default=[])
    add.add_argument("--supersedes", action="append", default=[])
    add.add_argument("--metadata", action="append", default=[])

    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--project-id", default="a9")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--threshold", type=float, default=0.05)

    all_parser = sub.add_parser("get-all")
    all_parser.add_argument("--project-id", default="a9")
    all_parser.add_argument("--limit", type=int, default=20)

    hist = sub.add_parser("history")
    hist.add_argument("memory_id")

    args = parser.parse_args(argv)
    if args.command == "add":
        return add_memory(args)
    if args.command == "search":
        return search_memory(args)
    if args.command == "get-all":
        return get_all(args)
    if args.command == "history":
        return history(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
