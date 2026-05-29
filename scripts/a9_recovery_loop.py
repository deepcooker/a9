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
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".a9" / "services"
LATEST_PATH = STATE_DIR / "recovery-loop-latest.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json_url(url: str, *, timeout: int = 10) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def recovery_cycle_once(controller_url: str, *, timeout: int = 10, max_actions: int = 3) -> dict[str, Any]:
    base = controller_url.rstrip("/")
    url = f"{base}/api/nodes/recovery-cycle"
    if max_actions:
        url = f"{url}?max_actions={int(max_actions)}"
    try:
        cycle = read_json_url(url, timeout=timeout)
        status = str(cycle.get("status") or "unknown")
        result = {
            "status": "ok" if status in {"ok", "needs_attention", "blocked"} else "degraded",
            "kind": "recovery_loop_observation",
            "checked_at": utc_now(),
            "controller_url": base,
            "cycle_status": status,
            "step_count": int(cycle.get("step_count") or 0),
            "risk_count": int((cycle.get("summary") or {}).get("risk_count") or 0),
            "execute": bool(cycle.get("execute")),
            "cycle": cycle,
        }
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        result = {
            "status": "degraded",
            "kind": "recovery_loop_observation",
            "checked_at": utc_now(),
            "controller_url": base,
            "cycle_status": "unavailable",
            "step_count": 0,
            "risk_count": 0,
            "execute": False,
            "error": str(exc),
        }
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
