#!/usr/bin/env python3
"""A9 node recovery planning loop.

This loop is intentionally planning-only. It observes the controller recovery
cycle on a schedule and writes the latest payload to disk. Execution remains
behind phone-control and explicit operator action.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, build_opener, ProxyHandler


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".a9" / "services"
LATEST_PATH = STATE_DIR / "recovery-loop-latest.json"
COMMUNICATION_OBSERVATION_PATH = STATE_DIR / "communication-observation.json"
COMMUNICATION_REPAIR_SUGGESTIONS_PATH = STATE_DIR / "communication-repair-suggestions.json"
LOCAL_CONTROLLER_OPENER = build_opener(ProxyHandler({}))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json_url(url: str, *, timeout: int = 10) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    with LOCAL_CONTROLLER_OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def communication_observation_update(result: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    path = path or COMMUNICATION_OBSERVATION_PATH
    now = str(result.get("checked_at") or utc_now())
    action = str(result.get("communication_action") or "unknown")
    source = str(result.get("communication_priority_source") or "unknown")
    plan_status = str(result.get("communication_plan_status") or "unknown")
    route = result.get("communication_route") if isinstance(result.get("communication_route"), dict) else {}
    key = f"{source}:{action}:{plan_status}"
    previous = read_json_file(path)
    previous_key = str(previous.get("current_key") or "")
    streak = int(previous.get("streak") or 0) + 1 if previous_key == key else 1
    first_seen = str(previous.get("first_seen_at") or now) if previous_key == key else now
    recommendation = "continue_observation"
    if action not in {"continue", "observe"} and plan_status not in {"noop", "unknown"}:
        recommendation = "operator_review"
        if streak >= 2:
            recommendation = "candidate_for_repair_one"
    observation = {
        "status": "ok",
        "kind": "communication_observation",
        "updated_at": now,
        "current_key": key,
        "action": action,
        "priority_source": source,
        "plan_status": plan_status,
        "streak": streak,
        "first_seen_at": first_seen,
        "last_seen_at": now,
        "recommendation": recommendation,
        "route": route,
        "auto_execute": False,
        "policy": {
            "mode": "observe_only",
            "reason": "collect_stable_action_evidence_before_auto_repair",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(observation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return observation


def communication_repair_suggestions_update(
    observation: dict[str, Any],
    result: dict[str, Any],
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    path = path or COMMUNICATION_REPAIR_SUGGESTIONS_PATH
    now = str(observation.get("last_seen_at") or utc_now())
    route = observation.get("route") if isinstance(observation.get("route"), dict) else {}
    is_candidate = observation.get("recommendation") == "candidate_for_repair_one"
    suggestion = {
        "suggestion_id": str(observation.get("current_key") or "unknown").replace(":", "-"),
        "status": "pending",
        "created_at": str(observation.get("first_seen_at") or now),
        "updated_at": now,
        "current_key": observation.get("current_key"),
        "action": observation.get("action"),
        "priority_source": observation.get("priority_source"),
        "plan_status": observation.get("plan_status"),
        "streak": observation.get("streak"),
        "recommendation": observation.get("recommendation"),
        "route": route,
        "auto_execute": False,
        "evidence": {
            "recovery_loop_latest": str(LATEST_PATH),
            "communication_observation": str(COMMUNICATION_OBSERVATION_PATH),
            "cycle_status": result.get("cycle_status"),
            "risk_count": result.get("risk_count"),
        },
        "operator_action": "review_then_arm_and_repair_one",
    }
    queue = {
        "status": "ok",
        "kind": "communication_repair_suggestions",
        "updated_at": now,
        "mode": "observe_only",
        "pending_count": 1 if is_candidate else 0,
        "pending": [suggestion] if is_candidate else [],
        "last_observation": {
            "current_key": observation.get("current_key"),
            "streak": observation.get("streak"),
            "recommendation": observation.get("recommendation"),
            "auto_execute": False,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return queue


def recovery_cycle_once(controller_url: str, *, timeout: int = 10, max_actions: int = 3) -> dict[str, Any]:
    base = controller_url.rstrip("/")
    plan_url = f"{base}/api/communication/action-plan"
    url = f"{base}/api/nodes/recovery-cycle"
    if max_actions:
        url = f"{url}?max_actions={int(max_actions)}"
    try:
        communication_plan = read_json_url(plan_url, timeout=timeout)
        cycle = read_json_url(url, timeout=timeout)
        status = str(cycle.get("status") or "unknown")
        plan_status = str(communication_plan.get("plan_status") or "unknown")
        result = {
            "status": "ok" if status in {"ok", "needs_attention", "blocked"} else "degraded",
            "kind": "recovery_loop_observation",
            "checked_at": utc_now(),
            "controller_url": base,
            "communication_plan_status": plan_status,
            "communication_action": (communication_plan.get("communication") or {}).get("action"),
            "communication_priority_source": (communication_plan.get("communication") or {}).get("priority_source"),
            "communication_route": communication_plan.get("route") or {},
            "cycle_status": status,
            "step_count": int(cycle.get("step_count") or 0),
            "risk_count": int((cycle.get("summary") or {}).get("risk_count") or 0),
            "execute": bool(cycle.get("execute")),
            "communication_plan": communication_plan,
            "cycle": cycle,
        }
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        result = {
            "status": "degraded",
            "kind": "recovery_loop_observation",
            "checked_at": utc_now(),
            "controller_url": base,
            "communication_plan_status": "unavailable",
            "communication_action": "intervene",
            "communication_priority_source": "controller",
            "communication_route": {},
            "cycle_status": "unavailable",
            "step_count": 0,
            "risk_count": 0,
            "execute": False,
            "error": str(exc),
        }
    communication_observation = communication_observation_update(result)
    communication_repair_suggestions = communication_repair_suggestions_update(communication_observation, result)
    result["communication_observation"] = communication_observation
    result["communication_repair_suggestions"] = communication_repair_suggestions
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def recovery_loop(
    controller_url: str,
    *,
    interval_seconds: float = 60.0,
    timeout: int = 10,
    max_actions: int = 3,
    max_iterations: int = 0,
    emit=None,
) -> dict[str, Any]:
    safe_interval = max(1.0, float(interval_seconds))
    safe_max = max(0, int(max_iterations))
    iterations = 0
    degraded = 0
    last_result: dict[str, Any] = {}
    while safe_max == 0 or iterations < safe_max:
        iterations += 1
        last_result = recovery_cycle_once(controller_url, timeout=timeout, max_actions=max_actions)
        if last_result.get("status") != "ok":
            degraded += 1
        if emit is not None:
            emit(last_result)
        if safe_max == 0 or iterations < safe_max:
            time.sleep(safe_interval)
    return {
        "status": "ok" if degraded == 0 else "degraded",
        "kind": "recovery_loop_summary",
        "checked_at": utc_now(),
        "controller_url": controller_url.rstrip("/"),
        "iterations": iterations,
        "degraded": degraded,
        "latest_path": str(LATEST_PATH),
        "last_result": last_result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A9 recovery planning loop")
    parser.add_argument("--controller-url", default="http://127.0.0.1:8787")
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--max-actions", type=int, default=3)
    parser.add_argument("--max-iterations", type=int, default=0)
    args = parser.parse_args(argv)

    def emit(payload: dict[str, Any]) -> None:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)

    summary = recovery_loop(
        args.controller_url,
        interval_seconds=args.interval_seconds,
        timeout=args.timeout,
        max_actions=args.max_actions,
        max_iterations=args.max_iterations,
        emit=emit,
    )
    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0 if summary.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
