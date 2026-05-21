#!/usr/bin/env python3
"""Manage A9 local middleware."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def compose_cmd() -> list[str]:
    if subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        return ["docker", "compose"]
    return ["docker-compose"]


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, check=check, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def up(_: argparse.Namespace) -> int:
    print(run(compose_cmd() + ["up", "-d", "--remove-orphans"]).stdout, end="")
    init_redis_runtime()
    return status(_)


def down(_: argparse.Namespace) -> int:
    print(run(compose_cmd() + ["down"]).stdout, end="")
    return 0


def status(_: argparse.Namespace) -> int:
    print(run(compose_cmd() + ["ps"]).stdout, end="")
    redis = run(["docker", "exec", "a9-redis", "redis-cli", "ping"], check=False)
    print(f"redis_ping: {redis.stdout.strip()}")
    mysql = run(
        [
            "docker",
            "exec",
            "a9-mysql",
            "mysql",
            "-h127.0.0.1",
            "-u",
            "a9",
            "-pa9_dev_password",
            "a9",
            "-NBe",
            "select count(*) from information_schema.tables where table_schema=database();",
        ],
        check=False,
    )
    print(f"mysql_tables: {mysql.stdout.strip()}")
    return 0 if redis.returncode == 0 and mysql.returncode == 0 else 1


def init_redis_runtime() -> None:
    streams = ["a9:tasks", "a9:events", "a9:deep_marks", "a9:heartbeats"]
    for stream in streams:
        run(["docker", "exec", "a9-redis", "redis-cli", "XGROUP", "CREATE", stream, "a9-workers", "$", "MKSTREAM"], check=False)

    function = r"""#!lua name=a9
redis.register_function('lease_task', function(keys, args)
  local stream = keys[1]
  local group = args[1]
  local consumer = args[2]
  local count = tonumber(args[3]) or 1
  return redis.call('XREADGROUP', 'GROUP', group, consumer, 'COUNT', count, 'BLOCK', 1, 'STREAMS', stream, '>')
end)
redis.register_function('ack_task', function(keys, args)
  return redis.call('XACK', keys[1], args[1], args[2])
end)
"""
    subprocess.run(
        ["docker", "exec", "-i", "a9-redis", "redis-cli", "-x", "FUNCTION", "LOAD", "REPLACE"],
        cwd=ROOT,
        text=True,
        input=function,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    init_redis_stack_objects()


def init_redis_stack_objects() -> None:
    run(
        [
            "docker",
            "exec",
            "a9-redis",
            "redis-cli",
            "FT.CREATE",
            "a9:idx:deep_marks",
            "ON",
            "JSON",
            "PREFIX",
            "1",
            "a9:deep_mark:",
            "SCHEMA",
            "$.session_id",
            "AS",
            "session_id",
            "TAG",
            "$.kind",
            "AS",
            "kind",
            "TAG",
            "$.label",
            "AS",
            "label",
            "TAG",
            "$.value",
            "AS",
            "value",
            "TEXT",
            "WEIGHT",
            "1.0",
        ],
        check=False,
    )
    run(
        [
            "docker",
            "exec",
            "a9-redis",
            "redis-cli",
            "FT.CREATE",
            "a9:idx:memories",
            "ON",
            "JSON",
            "PREFIX",
            "1",
            "a9:memory:",
            "SCHEMA",
            "$.project_id",
            "AS",
            "project_id",
            "TAG",
            "$.memory_type",
            "AS",
            "memory_type",
            "TAG",
            "$.memory",
            "AS",
            "memory",
            "TEXT",
            "WEIGHT",
            "1.0",
        ],
        check=False,
    )
    run(["docker", "exec", "a9-redis", "redis-cli", "BF.RESERVE", "a9:dedupe:evidence", "0.001", "1000000"], check=False)
    for metric in ["heartbeat", "task_latency_ms", "tokens_in", "tokens_out", "retry"]:
        run(["docker", "exec", "a9-redis", "redis-cli", "TS.CREATE", f"a9:ts:{metric}", "RETENTION", "604800000"], check=False)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 middleware manager")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("up")
    sub.add_parser("down")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    if args.command == "up":
        return up(args)
    if args.command == "down":
        return down(args)
    if args.command == "status":
        return status(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
