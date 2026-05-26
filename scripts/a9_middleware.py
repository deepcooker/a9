#!/usr/bin/env python3
"""Manage A9 local middleware."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FLOW_PREFIX = "a9:flow:"


def compose_cmd() -> list[str]:
    if subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        return ["docker", "compose"]
    return ["docker-compose"]


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, check=check, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_compact(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def redis(args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return run(["docker", "exec", "a9-redis", "redis-cli", *args], check=check)


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


def initial_flow_state(flow_id: str, kind: str, *, status: str = "created", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    now = utc_now()
    return {
        "flow_id": flow_id,
        "kind": kind,
        "status": status,
        "revision": 0,
        "created_at": now,
        "updated_at": now,
        "metadata": metadata or {},
        "history": [],
    }


def transition_flow_state(
    state: dict[str, Any],
    *,
    expected_revision: int,
    next_status: str,
    actor: str,
    reason: str = "",
    evidence_id: str = "",
    now: str | None = None,
) -> dict[str, Any]:
    current_revision = int(state.get("revision", 0))
    if current_revision != expected_revision:
        raise ValueError(f"revision_mismatch current={current_revision} expected={expected_revision}")
    updated = dict(state)
    history = list(updated.get("history") or [])
    timestamp = now or utc_now()
    history.append(
        {
            "revision": current_revision + 1,
            "from_status": state.get("status", ""),
            "to_status": next_status,
            "actor": actor,
            "reason": reason,
            "evidence_id": evidence_id,
            "at": timestamp,
        }
    )
    updated["status"] = next_status
    updated["revision"] = current_revision + 1
    updated["updated_at"] = timestamp
    updated["history"] = history
    return updated


def set_waiting_flow_state(
    state: dict[str, Any],
    *,
    expected_revision: int,
    actor: str,
    prompt: str,
    approval_id: str = "",
    resume_token: str = "",
    waiting_step: str = "",
    now: str | None = None,
) -> dict[str, Any]:
    current_revision = int(state.get("revision", 0))
    if current_revision != expected_revision:
        raise ValueError(f"revision_mismatch current={current_revision} expected={expected_revision}")
    timestamp = now or utc_now()
    next_revision = current_revision + 1
    effective_approval_id = approval_id or f"{state.get('flow_id', 'flow')}:approval:{next_revision}"
    waiting = {
        "kind": "approval_request",
        "approval_id": effective_approval_id,
        "resume_token": resume_token,
        "prompt": prompt,
        "waiting_step": waiting_step,
        "actor": actor,
        "created_at": timestamp,
    }
    updated = dict(state)
    history = list(updated.get("history") or [])
    history.append(
        {
            "revision": next_revision,
            "from_status": state.get("status", ""),
            "to_status": "waiting",
            "actor": actor,
            "reason": prompt,
            "approval_id": effective_approval_id,
            "at": timestamp,
        }
    )
    updated["status"] = "waiting"
    updated["revision"] = next_revision
    updated["updated_at"] = timestamp
    updated["waiting"] = waiting
    updated["history"] = history
    return updated


def resume_waiting_flow_state(
    state: dict[str, Any],
    *,
    expected_revision: int,
    actor: str,
    approve: bool,
    approval_id: str = "",
    resume_token: str = "",
    reason: str = "",
    now: str | None = None,
) -> dict[str, Any]:
    current_revision = int(state.get("revision", 0))
    if current_revision != expected_revision:
        raise ValueError(f"revision_mismatch current={current_revision} expected={expected_revision}")
    if state.get("status") != "waiting":
        raise ValueError(f"flow_not_waiting status={state.get('status', '')}")
    waiting = dict(state.get("waiting") or {})
    if approval_id and approval_id != waiting.get("approval_id", ""):
        raise ValueError("approval_mismatch")
    if resume_token and resume_token != waiting.get("resume_token", ""):
        raise ValueError("token_mismatch")
    if not approval_id and not resume_token:
        raise ValueError("resume_identity_required")
    timestamp = now or utc_now()
    next_status = "running" if approve else "rejected"
    next_revision = current_revision + 1
    updated = dict(state)
    history = list(updated.get("history") or [])
    history.append(
        {
            "revision": next_revision,
            "from_status": "waiting",
            "to_status": next_status,
            "actor": actor,
            "reason": reason,
            "approval_id": approval_id or waiting.get("approval_id", ""),
            "at": timestamp,
        }
    )
    updated["status"] = next_status
    updated["revision"] = next_revision
    updated["updated_at"] = timestamp
    updated["waiting"] = None
    updated["last_approval"] = {
        "approval_id": approval_id or waiting.get("approval_id", ""),
        "resume_token": resume_token,
        "approved": approve,
        "actor": actor,
        "reason": reason,
        "at": timestamp,
    }
    updated["history"] = history
    return updated


def redis_flow_key(flow_id: str) -> str:
    return f"{FLOW_PREFIX}{flow_id}"


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
redis.register_function('transition_flow', function(keys, args)
  local key = keys[1]
  local expected = tonumber(args[1])
  local next_status = args[2]
  local actor = args[3] or ''
  local reason = args[4] or ''
  local evidence_id = args[5] or ''
  local now = args[6] or ''
  local raw = redis.call('JSON.GET', key, '$')
  if not raw then
    return redis.error_reply('flow_not_found')
  end
  local parsed = cjson.decode(raw)
  local state = parsed[1]
  local current = tonumber(state['revision'] or 0)
  if current ~= expected then
    return redis.error_reply('revision_mismatch current=' .. tostring(current) .. ' expected=' .. tostring(expected))
  end
  local history = state['history'] or {}
  table.insert(history, {
    revision = current + 1,
    from_status = state['status'] or '',
    to_status = next_status,
    actor = actor,
    reason = reason,
    evidence_id = evidence_id,
    at = now
  })
  state['status'] = next_status
  state['revision'] = current + 1
  state['updated_at'] = now
  state['history'] = history
  redis.call('JSON.SET', key, '$', cjson.encode(state))
  redis.call('XADD', 'a9:events', '*', 'kind', 'flow_transition', 'flow_id', key, 'revision', tostring(current + 1), 'status', next_status, 'actor', actor)
  return cjson.encode(state)
end)
redis.register_function('set_waiting_flow', function(keys, args)
  local key = keys[1]
  local expected = tonumber(args[1])
  local actor = args[2] or ''
  local prompt = args[3] or ''
  local approval_id = args[4] or ''
  local resume_token = args[5] or ''
  local waiting_step = args[6] or ''
  local now = args[7] or ''
  local raw = redis.call('JSON.GET', key, '$')
  if not raw then
    return redis.error_reply('flow_not_found')
  end
  local parsed = cjson.decode(raw)
  local state = parsed[1]
  local current = tonumber(state['revision'] or 0)
  if current ~= expected then
    return redis.error_reply('revision_mismatch current=' .. tostring(current) .. ' expected=' .. tostring(expected))
  end
  local next_revision = current + 1
  if approval_id == '' then
    approval_id = tostring(state['flow_id'] or key) .. ':approval:' .. tostring(next_revision)
  end
  local waiting = {
    kind = 'approval_request',
    approval_id = approval_id,
    resume_token = resume_token,
    prompt = prompt,
    waiting_step = waiting_step,
    actor = actor,
    created_at = now
  }
  local history = state['history'] or {}
  table.insert(history, {
    revision = next_revision,
    from_status = state['status'] or '',
    to_status = 'waiting',
    actor = actor,
    reason = prompt,
    approval_id = approval_id,
    at = now
  })
  state['status'] = 'waiting'
  state['revision'] = next_revision
  state['updated_at'] = now
  state['waiting'] = waiting
  state['history'] = history
  redis.call('JSON.SET', key, '$', cjson.encode(state))
  redis.call('XADD', 'a9:events', '*', 'kind', 'flow_waiting', 'flow_id', key, 'revision', tostring(next_revision), 'approval_id', approval_id, 'actor', actor)
  return cjson.encode(state)
end)
redis.register_function('resume_flow', function(keys, args)
  local key = keys[1]
  local expected = tonumber(args[1])
  local actor = args[2] or ''
  local approve = args[3] or ''
  local approval_id = args[4] or ''
  local resume_token = args[5] or ''
  local reason = args[6] or ''
  local now = args[7] or ''
  local raw = redis.call('JSON.GET', key, '$')
  if not raw then
    return redis.error_reply('flow_not_found')
  end
  local parsed = cjson.decode(raw)
  local state = parsed[1]
  local current = tonumber(state['revision'] or 0)
  if current ~= expected then
    return redis.error_reply('revision_mismatch current=' .. tostring(current) .. ' expected=' .. tostring(expected))
  end
  if state['status'] ~= 'waiting' then
    return redis.error_reply('flow_not_waiting status=' .. tostring(state['status'] or ''))
  end
  local waiting = state['waiting'] or {}
  if approval_id == '' and resume_token == '' then
    return redis.error_reply('resume_identity_required')
  end
  if approval_id ~= '' and approval_id ~= tostring(waiting['approval_id'] or '') then
    return redis.error_reply('approval_mismatch')
  end
  if resume_token ~= '' and resume_token ~= tostring(waiting['resume_token'] or '') then
    return redis.error_reply('token_mismatch')
  end
  local next_status = 'rejected'
  local approved = false
  if approve == '1' or approve == 'true' or approve == 'yes' then
    next_status = 'running'
    approved = true
  end
  local next_revision = current + 1
  local history = state['history'] or {}
  table.insert(history, {
    revision = next_revision,
    from_status = 'waiting',
    to_status = next_status,
    actor = actor,
    reason = reason,
    approval_id = approval_id,
    at = now
  })
  state['status'] = next_status
  state['revision'] = next_revision
  state['updated_at'] = now
  state['waiting'] = cjson.null
  state['last_approval'] = {
    approval_id = approval_id,
    resume_token = resume_token,
    approved = approved,
    actor = actor,
    reason = reason,
    at = now
  }
  state['history'] = history
  redis.call('JSON.SET', key, '$', cjson.encode(state))
  redis.call('XADD', 'a9:events', '*', 'kind', 'flow_resume', 'flow_id', key, 'revision', tostring(next_revision), 'status', next_status, 'approval_id', approval_id, 'actor', actor)
  return cjson.encode(state)
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


def flow_create(args: argparse.Namespace) -> int:
    payload = initial_flow_state(args.flow_id, args.kind, status=args.status, metadata=dict(item.split("=", 1) for item in args.metadata))
    result = redis(["JSON.SET", redis_flow_key(args.flow_id), "$", json_compact(payload)])
    print(result.stdout, end="")
    if result.returncode == 0:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return result.returncode


def flow_get(args: argparse.Namespace) -> int:
    result = redis(["JSON.GET", redis_flow_key(args.flow_id), "$"])
    print(result.stdout, end="")
    return result.returncode


def flow_transition(args: argparse.Namespace) -> int:
    result = redis(
        [
            "FCALL",
            "transition_flow",
            "1",
            redis_flow_key(args.flow_id),
            str(args.expected_revision),
            args.status,
            args.actor,
            args.reason,
            args.evidence_id,
            utc_now(),
        ]
    )
    print(result.stdout, end="")
    return result.returncode


def flow_wait(args: argparse.Namespace) -> int:
    result = redis(
        [
            "FCALL",
            "set_waiting_flow",
            "1",
            redis_flow_key(args.flow_id),
            str(args.expected_revision),
            args.actor,
            args.prompt,
            args.approval_id,
            args.resume_token,
            args.waiting_step,
            utc_now(),
        ]
    )
    print(result.stdout, end="")
    return result.returncode


def flow_resume(args: argparse.Namespace) -> int:
    result = redis(
        [
            "FCALL",
            "resume_flow",
            "1",
            redis_flow_key(args.flow_id),
            str(args.expected_revision),
            args.actor,
            "true" if args.approve else "false",
            args.approval_id,
            args.resume_token,
            args.reason,
            utc_now(),
        ]
    )
    print(result.stdout, end="")
    return result.returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 middleware manager")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("up")
    sub.add_parser("down")
    sub.add_parser("status")
    create_parser = sub.add_parser("flow-create")
    create_parser.add_argument("flow_id")
    create_parser.add_argument("--kind", default="managed_flow")
    create_parser.add_argument("--status", default="created")
    create_parser.add_argument("--metadata", action="append", default=[])

    get_parser = sub.add_parser("flow-get")
    get_parser.add_argument("flow_id")

    transition_parser = sub.add_parser("flow-transition")
    transition_parser.add_argument("flow_id")
    transition_parser.add_argument("--expected-revision", type=int, required=True)
    transition_parser.add_argument("--status", required=True)
    transition_parser.add_argument("--actor", default="operator")
    transition_parser.add_argument("--reason", default="")
    transition_parser.add_argument("--evidence-id", default="")

    wait_parser = sub.add_parser("flow-wait")
    wait_parser.add_argument("flow_id")
    wait_parser.add_argument("--expected-revision", type=int, required=True)
    wait_parser.add_argument("--prompt", required=True)
    wait_parser.add_argument("--actor", default="supervisor")
    wait_parser.add_argument("--approval-id", default="")
    wait_parser.add_argument("--resume-token", default="")
    wait_parser.add_argument("--waiting-step", default="")

    resume_parser = sub.add_parser("flow-resume")
    resume_parser.add_argument("flow_id")
    resume_parser.add_argument("--expected-revision", type=int, required=True)
    resume_parser.add_argument("--actor", default="operator")
    resume_parser.add_argument("--approval-id", default="")
    resume_parser.add_argument("--resume-token", default="")
    resume_parser.add_argument("--reason", default="")
    decision = resume_parser.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "up":
        return up(args)
    if args.command == "down":
        return down(args)
    if args.command == "status":
        return status(args)
    if args.command == "flow-create":
        return flow_create(args)
    if args.command == "flow-get":
        return flow_get(args)
    if args.command == "flow-transition":
        return flow_transition(args)
    if args.command == "flow-wait":
        return flow_wait(args)
    if args.command == "flow-resume":
        return flow_resume(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
