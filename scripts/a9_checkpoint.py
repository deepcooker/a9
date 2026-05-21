#!/usr/bin/env python3
"""A9 checkpoint adapter.

This copies LangGraph's core checkpoint shape into A9's storage model:
stable thread/session identity, per-run checkpoint IDs, parent lineage, channel
values, updated channels, token usage, and evidence IDs.
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


def parse_json_value(value: str, name: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{name} must be valid JSON: {exc}") from exc


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


def mysql_data_lines(output: str) -> list[str]:
    return [
        line
        for line in output.splitlines()
        if line and not line.startswith("mysql: [Warning]")
    ]


def redis(args: list[str]) -> subprocess.CompletedProcess[str]:
    return run(["docker", "exec", "a9-redis", "redis-cli", *args])


def next_step(session_id: str) -> int:
    result = mysql(
        "SELECT COALESCE(MAX(step), 0) + 1 FROM checkpoints "
        f"WHERE session_id={sql_quote(session_id)};"
    )
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        raise SystemExit(result.returncode)
    lines = mysql_data_lines(result.stdout)
    return int((lines[-1] if lines else "1").strip())


def latest_checkpoint_id(session_id: str) -> str | None:
    result = mysql(
        "SELECT checkpoint_id FROM checkpoints "
        f"WHERE session_id={sql_quote(session_id)} ORDER BY step DESC LIMIT 1;"
    )
    if result.returncode != 0:
        return None
    lines = mysql_data_lines(result.stdout)
    return lines[-1].strip() if lines else None


def load_checkpoint(checkpoint_id: str) -> dict[str, Any] | None:
    result = mysql(
        "SELECT checkpoint_id, parent_checkpoint_id, step, source, status, "
        "channels, updated_channels, token_usage, evidence_ids "
        f"FROM checkpoints WHERE checkpoint_id={sql_quote(checkpoint_id)};"
    )
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        raise SystemExit(result.returncode)
    lines = mysql_data_lines(result.stdout)
    if not lines:
        return None
    parts = lines[0].split("\t", 8)
    if len(parts) < 9:
        return None
    parent = parts[1] if parts[1] != "NULL" else None
    return {
        "checkpoint_id": parts[0],
        "parent_checkpoint_id": parent,
        "step": int(parts[2]),
        "source": parts[3],
        "status": parts[4],
        "channels": json.loads(parts[5] or "{}"),
        "updated_channels": json.loads(parts[6] or "[]"),
        "token_usage": json.loads(parts[7] or "{}"),
        "evidence_ids": json.loads(parts[8] or "[]"),
    }


def put(args: argparse.Namespace) -> int:
    channels = parse_json_value(args.channels, "channels")
    if not isinstance(channels, dict):
        raise SystemExit("channels must be a JSON object")
    updated_channels = args.updated_channel or sorted(channels.keys())
    token_usage = parse_json_value(args.token_usage, "token-usage")
    evidence_ids = args.evidence_id
    checkpoint_id = args.checkpoint_id or f"{args.session_id}:checkpoint:{uuid.uuid4()}"
    parent_checkpoint_id = args.parent_checkpoint_id
    if parent_checkpoint_id and parent_checkpoint_id.lower() in {"none", "null"}:
        parent_checkpoint_id = None
    if parent_checkpoint_id == "":
        parent_checkpoint_id = None
    if parent_checkpoint_id == "latest":
        parent_checkpoint_id = latest_checkpoint_id(args.session_id)
    step = args.step or next_step(args.session_id)

    sql = f"""
INSERT INTO sessions (session_id, project_id, root_path, status, current_checkpoint_id, source)
VALUES (
  {sql_quote(args.session_id)}, 'a9', {sql_quote(str(ROOT))}, 'running',
  {sql_quote(checkpoint_id)}, {sql_quote(args.source)}
)
ON DUPLICATE KEY UPDATE
  status='running',
  current_checkpoint_id=VALUES(current_checkpoint_id),
  updated_at=CURRENT_TIMESTAMP(6);

INSERT INTO checkpoints (
  checkpoint_id, session_id, parent_checkpoint_id, step, source, status,
  channels, updated_channels, token_usage, evidence_ids
) VALUES (
  {sql_quote(checkpoint_id)},
  {sql_quote(args.session_id)},
  {sql_quote(parent_checkpoint_id)},
  {int(step)},
  {sql_quote(args.source)},
  {sql_quote(args.status)},
  {sql_quote(json_compact(channels))},
  {sql_quote(json_compact(updated_channels))},
  {sql_quote(json_compact(token_usage))},
  {sql_quote(json_compact(evidence_ids))}
)
ON DUPLICATE KEY UPDATE
  status=VALUES(status),
  parent_checkpoint_id=VALUES(parent_checkpoint_id),
  channels=VALUES(channels),
  updated_channels=VALUES(updated_channels),
  token_usage=VALUES(token_usage),
  evidence_ids=VALUES(evidence_ids);
"""
    result = mysql_stdin(sql)
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        return result.returncode

    payload = {
        "checkpoint_id": checkpoint_id,
        "session_id": args.session_id,
        "parent_checkpoint_id": parent_checkpoint_id,
        "step": step,
        "source": args.source,
        "status": args.status,
        "channels": channels,
        "updated_channels": updated_channels,
        "token_usage": token_usage,
        "evidence_ids": evidence_ids,
        "created_at": utc_now(),
    }
    redis(["JSON.SET", f"a9:checkpoint:{checkpoint_id}", "$", json_compact(payload)])
    redis(
        [
            "JSON.SET",
            f"a9:session:{args.session_id}",
            "$",
            json_compact(
                {
                    "session_id": args.session_id,
                    "current_checkpoint_id": checkpoint_id,
                    "status": args.status,
                    "updated_at": utc_now(),
                }
            ),
        ]
    )
    redis(
        [
            "XADD",
            "a9:events",
            "*",
            "type",
            "checkpoint_put",
            "session_id",
            args.session_id,
            "checkpoint_id",
            checkpoint_id,
            "source",
            args.source,
        ]
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def get(args: argparse.Namespace) -> int:
    checkpoint_id = args.checkpoint_id
    if checkpoint_id == "latest":
        checkpoint_id = latest_checkpoint_id(args.session_id or "")
        if not checkpoint_id:
            raise SystemExit("no latest checkpoint")
    result = mysql(
        "SELECT checkpoint_id, session_id, parent_checkpoint_id, step, source, status, "
        "channels, updated_channels, token_usage, evidence_ids "
        f"FROM checkpoints WHERE checkpoint_id={sql_quote(checkpoint_id)};"
    )
    print("\n".join(mysql_data_lines(result.stdout)))
    return result.returncode


def list_checkpoints(args: argparse.Namespace) -> int:
    result = mysql(
        "SELECT checkpoint_id, parent_checkpoint_id, step, source, status "
        "FROM checkpoints "
        f"WHERE session_id={sql_quote(args.session_id)} ORDER BY step DESC LIMIT {int(args.limit)};"
    )
    print("\n".join(mysql_data_lines(result.stdout)))
    return result.returncode


def lineage(args: argparse.Namespace) -> int:
    checkpoint_id = args.checkpoint_id
    if checkpoint_id == "latest":
        checkpoint_id = latest_checkpoint_id(args.session_id or "")
    rows: list[str] = []
    seen: set[str] = set()
    while checkpoint_id and checkpoint_id not in seen:
        seen.add(checkpoint_id)
        result = mysql(
            "SELECT checkpoint_id, parent_checkpoint_id, step, source, status "
            f"FROM checkpoints WHERE checkpoint_id={sql_quote(checkpoint_id)};"
        )
        lines = mysql_data_lines(result.stdout)
        if result.returncode != 0 or not lines:
            break
        line = lines[0]
        rows.append(line)
        parts = line.split("\t")
        checkpoint_id = parts[1] if len(parts) > 1 and parts[1] != "NULL" else None
    print("\n".join(rows))
    return 0


def channel_history(args: argparse.Namespace) -> int:
    checkpoint_id = args.checkpoint_id
    if checkpoint_id == "latest":
        checkpoint_id = latest_checkpoint_id(args.session_id or "")
        if not checkpoint_id:
            raise SystemExit("no latest checkpoint")

    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    while checkpoint_id and checkpoint_id not in seen:
        seen.add(checkpoint_id)
        row = load_checkpoint(checkpoint_id)
        if not row:
            break
        chain.append(row)
        checkpoint_id = row["parent_checkpoint_id"]

    seed = None
    writes: list[dict[str, Any]] = []
    for row in reversed(chain):
        channels = row["channels"]
        updated_channels = set(row["updated_channels"] or [])
        if args.channel not in channels:
            continue
        entry = {
            "checkpoint_id": row["checkpoint_id"],
            "step": row["step"],
            "source": row["source"],
            "value": channels[args.channel],
        }
        if args.channel in updated_channels:
            writes.append(entry)
        elif seed is None:
            seed = entry

    payload = {
        "checkpoint_id": args.checkpoint_id,
        "channel": args.channel,
        "seed": seed,
        "writes": writes,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 checkpoint adapter")
    sub = parser.add_subparsers(dest="command", required=True)

    put_parser = sub.add_parser("put")
    put_parser.add_argument("session_id")
    put_parser.add_argument("--channels", required=True)
    put_parser.add_argument("--updated-channel", action="append", default=[])
    put_parser.add_argument("--evidence-id", action="append", default=[])
    put_parser.add_argument("--token-usage", default="{}")
    put_parser.add_argument("--checkpoint-id")
    put_parser.add_argument("--parent-checkpoint-id", default="latest")
    put_parser.add_argument("--step", type=int)
    put_parser.add_argument("--source", default="manual")
    put_parser.add_argument("--status", default="running")

    get_parser = sub.add_parser("get")
    get_parser.add_argument("checkpoint_id")
    get_parser.add_argument("--session-id")

    list_parser = sub.add_parser("list")
    list_parser.add_argument("session_id")
    list_parser.add_argument("--limit", type=int, default=10)

    lineage_parser = sub.add_parser("lineage")
    lineage_parser.add_argument("checkpoint_id")
    lineage_parser.add_argument("--session-id")

    channel_history_parser = sub.add_parser("channel-history")
    channel_history_parser.add_argument("checkpoint_id")
    channel_history_parser.add_argument("--session-id")
    channel_history_parser.add_argument("--channel", required=True)

    args = parser.parse_args(argv)
    if args.command == "put":
        return put(args)
    if args.command == "get":
        return get(args)
    if args.command == "list":
        return list_checkpoints(args)
    if args.command == "lineage":
        return lineage(args)
    if args.command == "channel-history":
        return channel_history(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
