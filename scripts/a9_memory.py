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
    query = args.query or "*"
    if query != "*":
        query = query.replace('"', "")
    redis_query = query if query == "*" else f"({query})"
    result = redis(["FT.SEARCH", "a9:idx:memories", redis_query, "LIMIT", "0", str(args.limit)])
    if result.returncode == 0 and not result.stdout.startswith("0"):
        print(result.stdout)
        return 0

    sql = f"""
SELECT memory_id, memory_type, confidence, memory
FROM memories
WHERE project_id={sql_quote(args.project_id)}
  AND ({sql_quote(args.query)}='' OR memory LIKE {sql_quote('%' + args.query + '%')})
ORDER BY updated_at DESC
LIMIT {int(args.limit)};
"""
    fallback = mysql(sql)
    print(fallback.stdout)
    return fallback.returncode


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
