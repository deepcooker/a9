#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


FORBIDDEN_COMMAND_PATTERNS = {
    "service_status": [
        "scripts/a9_service.py ps",
        " ps ",
        "pgrep",
        "systemctl status",
    ],
    "session_docs": [
        "docs/session-raw-summary.md",
        "docs/session-raw-close-reading.md",
        "/root/.codex/sessions",
    ],
    "run_artifacts": [
        ".a9/runs",
    ],
}

BROAD_SCAN_PATTERNS = [
    r"rg .*reference-projects\b(?!/[^ ]+/[^ ]+)",
    r"rg .*reference-projects/(aider|codex|cline|barter-rs)\b(?!/[^ ]+/[^ ]+)",
]

TEST_COMMAND_HINTS = ("pytest", "unittest", "cargo test", "npm test", "pnpm test", "yarn test")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def command_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_command: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("item_type") != "command_execution" or not isinstance(event.get("command"), str):
            continue
        command = normalize_command(str(event.get("command") or ""))
        existing = by_command.get(command)
        if not existing:
            by_command[command] = event
            continue
        if event.get("status") == "completed" or event.get("output_preview"):
            by_command[command] = event
    return list(by_command.values())


def normalize_command(command: str) -> str:
    return " ".join(command.split())


def declared_checks(summary: dict[str, Any]) -> list[str]:
    checks = summary.get("checks") or []
    result: list[str] = []
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict) and isinstance(check.get("command"), str):
                result.append(normalize_command(check["command"]))
            elif isinstance(check, str):
                result.append(normalize_command(check))
    return result


def is_declared_command(command: str, declared: list[str]) -> bool:
    normalized = normalize_command(command)
    return any(normalized == item or normalized in item or item in normalized for item in declared)


def looks_like_test_command(command: str) -> bool:
    normalized = normalize_command(command)
    return any(hint in normalized for hint in TEST_COMMAND_HINTS)


def finding(level: str, kind: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"level": level, "kind": kind, "message": message}
    payload.update(extra)
    return payload


def add_score(score: float, amount: float) -> float:
    return min(1.0, round(score + amount, 3))


def expert_result(name: str, score: float, action: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": name,
        "score": min(1.0, round(score, 3)),
        "recommended_action": action,
        "findings": findings,
    }


def action_rank(action: str) -> int:
    ranks = {
        "continue": 0,
        "monitor_review": 1,
        "narrow_task": 2,
        "repair": 3,
        "block_and_rewrite_task": 4,
    }
    return ranks.get(action, 1)


def action_from_score(score: float) -> str:
    if score >= 0.75:
        return "block_and_rewrite_task"
    if score >= 0.35:
        return "monitor_review"
    return "continue"


def evaluate_governance(summary: dict[str, Any], worker: dict[str, Any], commands: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    if worker.get("budget_stopped"):
        score = add_score(score, 0.35)
        findings.append(
            finding(
                "error",
                "budget_stopped",
                "worker stopped by event budget",
                reason=worker.get("budget_reason", ""),
                event_bytes=worker.get("event_bytes", 0),
            )
        )

    envelope = summary.get("worker_envelope") if isinstance(summary.get("worker_envelope"), dict) else {}
    if envelope.get("status") == "fail":
        score = add_score(score, 0.25)
        findings.append(finding("error", "worker_envelope_fail", "worker final envelope missing or invalid"))

    for event in commands:
        command = normalize_command(str(event.get("command") or ""))
        for kind, patterns in FORBIDDEN_COMMAND_PATTERNS.items():
            if any(pattern in command for pattern in patterns):
                score = add_score(score, 0.22)
                findings.append(
                    finding("error", kind, "worker command touched forbidden observation surface", command=command)
                )
    action = "narrow_task" if worker.get("budget_stopped") else action_from_score(score)
    if score >= 0.75:
        action = "block_and_rewrite_task"
    return expert_result("governance", score, action, findings)


def evaluate_testing(summary: dict[str, Any], commands: list[dict[str, Any]], checks: list[str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    for check in summary.get("checks", []) or []:
        if isinstance(check, dict) and check.get("return_code") not in (0, None):
            score = add_score(score, 0.35)
            findings.append(
                finding(
                    "error",
                    "declared_check_failed",
                    "declared check failed",
                    command=check.get("command", ""),
                    return_code=check.get("return_code"),
                )
            )
    for event in commands:
        command = normalize_command(str(event.get("command") or ""))
        output_preview = str(event.get("output_preview") or "")
        if looks_like_test_command(command) and checks and not is_declared_command(command, checks):
            score = add_score(score, 0.18)
            findings.append(finding("warn", "undeclared_check", "worker ran a test/check outside declared checks", command=command))
        if "No module named pytest" in output_preview:
            score = add_score(score, 0.2)
            findings.append(finding("warn", "pytest_not_declared", "worker treated missing pytest as task direction", command=command))
    action = "repair" if any(item["kind"] == "declared_check_failed" for item in findings) else action_from_score(score)
    return expert_result("testing", score, action, findings)


def evaluate_architecture(commands: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    for event in commands:
        command = normalize_command(str(event.get("command") or ""))
        if any(re.search(pattern, command) for pattern in BROAD_SCAN_PATTERNS):
            score = add_score(score, 0.25)
            findings.append(
                finding("warn", "broad_reference_scan", "worker ran broad reference-projects scan", command=command)
            )
    action = "narrow_task" if findings else "continue"
    return expert_result("architecture", score, action, findings)


def evaluate_product_mainline(summary: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    phase = str(summary.get("phase") or "")
    status = str(summary.get("status") or "")
    if phase == "vendor_import" and status == "pass":
        score = add_score(score, 0.15)
        findings.append(finding("info", "vendor_import_requires_license_review", "vendor import should be license-reviewed"))
    if status.startswith("retryable-"):
        score = add_score(score, 0.25)
        findings.append(finding("warn", "mainline_not_advanced", "retryable run did not advance product mainline"))
    return expert_result("product_mainline", score, action_from_score(score), findings)


def evaluate_business_boundary(commands: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    business_terms = ("quant", "trading", "strategy", "backtest", "finance", "金融", "交易", "量化")
    for event in commands:
        command = normalize_command(str(event.get("command") or "")).lower()
        if any(term in command for term in business_terms):
            score = add_score(score, 0.25)
            findings.append(finding("warn", "business_scope_drift", "worker touched business/quant surface during runtime work", command=command))
    return expert_result("business_boundary", score, action_from_score(score), findings)


def merge_experts(experts: list[dict[str, Any]]) -> tuple[float, str, list[dict[str, Any]]]:
    score = min(1.0, round(max((item["score"] for item in experts), default=0.0), 3))
    action = "continue"
    findings: list[dict[str, Any]] = []
    for expert in experts:
        if action_rank(str(expert.get("recommended_action"))) > action_rank(action):
            action = str(expert.get("recommended_action"))
        for item in expert.get("findings", []) or []:
            enriched = dict(item)
            enriched["expert"] = expert["name"]
            findings.append(enriched)
    return score, action, findings


def score_run(run_dir: Path) -> dict[str, Any]:
    summary = read_json(run_dir / "summary.json")
    worker = summary.get("worker") if isinstance(summary.get("worker"), dict) else {}
    event_path = Path(worker.get("event_summaries_path") or run_dir / "event_summaries.jsonl")
    events = read_jsonl(event_path)
    commands = command_events(events)
    checks = declared_checks(summary)
    experts = [
        evaluate_product_mainline(summary),
        evaluate_testing(summary, commands, checks),
        evaluate_architecture(commands),
        evaluate_business_boundary(commands),
        evaluate_governance(summary, worker, commands),
    ]
    score, recommended_action, findings = merge_experts(experts)

    payload = {
        "status": "ok",
        "run_dir": str(run_dir),
        "score": score,
        "recommended_action": recommended_action,
        "experts": experts,
        "findings": findings,
        "observed": {
            "commands": len(commands),
            "declared_checks": checks,
            "event_summaries_path": str(event_path),
            "worker_status": summary.get("status", ""),
            "budget_stopped": bool(worker.get("budget_stopped")),
        },
    }
    return payload


def write_score(run_dir: Path, payload: dict[str, Any]) -> Path:
    output_path = run_dir / "monitor_score.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 externalized worker trace monitor")
    sub = parser.add_subparsers(dest="command", required=True)
    score_parser = sub.add_parser("score")
    score_parser.add_argument("run_dir")
    score_parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "score":
        payload = score_run(Path(args.run_dir))
        if not args.no_write:
            write_score(Path(args.run_dir), payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["status"] == "ok" else 1
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
