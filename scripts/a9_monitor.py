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
REFERENCE_HINTS = ("reference-projects/", "vendor-src/", "docs/copied-mechanisms.md", "docs/vendor-strategy.md")
MAINLINE_HINTS = ("主线", "mainline", "philosophy", "哲学", "业务逻辑", "causal", "原始想法", "requirements", "需求")
PRODUCT_PRESSURE_HINTS = ("tradeoff", "权衡", "reject", "拒绝", "推翻", "压榨", "shrink", "收缩", "scope", "边界")
DATA_MODEL_HINTS = ("data", "schema", "model", "table", "event", "state", "数据", "表", "结构", "状态", "事件")
PERFORMANCE_HINTS = ("performance", "latency", "throughput", "budget", "timeout", "cache", "性能", "延迟", "吞吐", "压测", "稳定")
COMMUNICATION_HINTS = ("communication", "gateway", "control api", "ssh", "tmux", "redis", "reconnect", "通讯", "控制")
COMMUNICATION_RUNTIME_HINTS = (
    "gateway",
    "control api",
    "ssh",
    "tmux",
    "redis",
    "reconnect",
    "websocket",
    "remote",
    "node",
    "heartbeat",
    "通讯",
    "远程",
)
COMMUNICATION_MONITOR_EXEMPT_HINTS = (
    "repo map",
    "context packet",
    "token governance",
    "prompt repo map",
    "allowed_paths",
    "session-governance",
    "session-raw",
    "context router",
    "context-router",
    "context_pressure",
    "promptware",
)
FAILURE_CLASS_HINTS = ("timeout", "auth", "network", "protocol", "rate_limit")
RECOVERY_ACTION_HINTS = ("retry", "repair", "quarantine", "terminate")


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


def read_text(path: Path) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return ""


def run_text(summary: dict[str, Any], run_dir: Path) -> str:
    parts: list[str] = []
    task_path = summary.get("task_path")
    if isinstance(task_path, str):
        parts.append(read_text(Path(task_path)))
    worker = summary.get("worker") if isinstance(summary.get("worker"), dict) else {}
    raw_task_path = worker.get("raw_task_path")
    if isinstance(raw_task_path, str):
        parts.append(read_text(Path(raw_task_path)))
    parts.append(read_text(run_dir / "raw_task.md"))
    parts.append(read_text(run_dir / "prompt.md"))
    return "\n".join(part for part in parts if part)


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
    normalized_variants = command_equivalence_variants(normalized)
    declared_variants = [variant for item in declared for variant in command_equivalence_variants(item)]
    return any(
        command_variant == declared_variant
        or command_variant in declared_variant
        or declared_variant in command_variant
        for command_variant in normalized_variants
        for declared_variant in declared_variants
    )


def command_equivalence_variants(command: str) -> set[str]:
    normalized = normalize_command(command)
    variants = {normalized}
    match = re.search(r"python3?\s+-m\s+unittest\s+([A-Za-z0-9_./-]+\.py)\b", normalized)
    if match:
        module = match.group(1)[:-3].replace("/", ".").replace("\\", ".")
        variants.add(normalized[: match.start(1)] + module + normalized[match.end(1) :])
    match = re.search(r"python3?\s+-m\s+unittest\s+([A-Za-z0-9_.-]+)\b", normalized)
    if match and "." in match.group(1):
        path = match.group(1).replace(".", "/") + ".py"
        variants.add(normalized[: match.start(1)] + path + normalized[match.end(1) :])
    return variants


def looks_like_test_command(command: str) -> bool:
    normalized = normalize_command(command)
    return any(hint in normalized for hint in TEST_COMMAND_HINTS)


def finding(level: str, kind: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"level": level, "kind": kind, "message": message}
    payload.update(extra)
    return payload


def contains_any(text: str, needles: tuple[str, ...] | list[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def contains_domain_hint(text: str, needles: tuple[str, ...] | list[str]) -> bool:
    lowered = text.lower()
    for needle in needles:
        lowered_needle = needle.lower()
        if lowered_needle.isascii() and re.fullmatch(r"[a-z0-9_]+", lowered_needle):
            if re.search(rf"(?<![a-z0-9_]){re.escape(lowered_needle)}(?![a-z0-9_])", lowered):
                return True
        elif lowered_needle in lowered:
            return True
    return False


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
        "needs_tradeoff": 2,
        "narrow_task": 2,
        "repair": 3,
        "product_rewrite": 4,
        "block_and_rewrite_task": 4,
    }
    return ranks.get(action, 1)


def action_from_score(score: float) -> str:
    if score >= 0.75:
        return "block_and_rewrite_task"
    if score >= 0.35:
        return "monitor_review"
    return "continue"


def evaluate_why_expert(text: str, summary: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    if not contains_any(text, ("goal:", "目标", "why", "为什么", "background", "背景", "problem", "问题")):
        score = add_score(score, 0.35)
        findings.append(finding("error", "missing_real_problem", "task lacks explicit goal/background/real problem"))
    if str(summary.get("status") or "").startswith("retryable-"):
        score = add_score(score, 0.15)
        findings.append(finding("warn", "why_not_advanced", "retryable run needs renewed why before continuing"))
    action = "block_and_rewrite_task" if score >= 0.5 else action_from_score(score)
    return expert_result("why_expert", score, action, findings)


def evaluate_scope_dependency_expert(text: str, summary: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    scope_guard = summary.get("scope_guard") if isinstance(summary.get("scope_guard"), dict) else {}
    allowed_paths = scope_guard.get("allowed_paths", []) if isinstance(scope_guard.get("allowed_paths"), list) else []
    changed_files = scope_guard.get("changed_files", []) if isinstance(scope_guard.get("changed_files"), list) else []
    if changed_files and len(changed_files) > 4:
        score = add_score(score, 0.25)
        findings.append(finding("warn", "large_change_surface", "task changed too many files for one bounded worker slice", changed_files=changed_files))
    if changed_files and allowed_paths and not all(any(str(path).startswith(str(allowed)) for allowed in allowed_paths) for path in changed_files):
        score = add_score(score, 0.45)
        findings.append(finding("error", "scope_guard_mismatch", "changed files do not fit allowed paths", changed_files=changed_files, allowed_paths=allowed_paths))
    if not contains_any(text, ("allowed_paths", "Hard bounds", "边界", "scope", "范围")):
        score = add_score(score, 0.18)
        findings.append(finding("warn", "scope_not_explicit", "task prompt does not make scope/bounds explicit"))
    return expert_result("scope_dependency_expert", score, "narrow_task" if score >= 0.25 else "continue", findings)


def evaluate_system_requirement_expert(text: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    if not contains_any(text, ("input", "output", "state", "error", "contract", "行为", "输入", "输出", "状态", "错误", "接口")):
        score = add_score(score, 0.28)
        findings.append(finding("warn", "system_behavior_unclear", "task does not translate intent into system behavior"))
    return expert_result("system_requirement_expert", score, action_from_score(score), findings)


def evaluate_tradeoff_architecture_expert(text: str, commands: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    if not contains_any(text, ("tradeoff", "权衡", "方案", "option", "复杂度", "耦合", "risk", "风险")):
        score = add_score(score, 0.22)
        findings.append(finding("warn", "missing_tradeoff", "task lacks explicit option/tradeoff/risk framing"))
    for event in commands:
        command = normalize_command(str(event.get("command") or ""))
        if any(re.search(pattern, command) for pattern in BROAD_SCAN_PATTERNS):
            score = add_score(score, 0.25)
            findings.append(finding("warn", "broad_reference_scan", "worker ran broad reference-projects scan", command=command))
    action = "needs_tradeoff" if any(item["kind"] == "missing_tradeoff" for item in findings) else "continue"
    if any(item["kind"] == "broad_reference_scan" for item in findings):
        action = "narrow_task"
    return expert_result("tradeoff_architecture_expert", score, action, findings)


def evaluate_role_boundary_expert(text: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    if contains_any(text, ("worker decide", "worker decides", "自己决定主线", "自动决定主线")):
        score = add_score(score, 0.5)
        findings.append(finding("error", "worker_oversteps_strategy", "worker appears to own strategic direction"))
    if not contains_any(text, ("human", "monitor", "worker", "supervisor", "监控", "执行机器")):
        score = add_score(score, 0.16)
        findings.append(finding("warn", "roles_not_explicit", "task does not state human/monitor/worker/runtime boundaries"))
    action = "block_and_rewrite_task" if score >= 0.5 else action_from_score(score)
    return expert_result("role_boundary_expert", score, action, findings)


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
    return expert_result("execution_governance_expert", score, action, findings)


def evaluate_testing(summary: dict[str, Any], commands: list[dict[str, Any]], checks: list[str], text: str) -> dict[str, Any]:
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
    data_sensitive = str(summary.get("phase") or "") in {"implement", "test"} or contains_any(
        text, ("api", "control", "session", "flow", "run", "memory", "redis", "mysql", "业务", "页面")
    )
    data_terms = ("schema", "table", "event", "state", "数据", "表结构", "状态", "事件")
    has_data_acceptance = contains_domain_hint(text, data_terms)
    test_commands = " ".join(normalize_command(str(event.get("command") or "")) for event in commands if looks_like_test_command(str(event.get("command") or "")))
    checks_text = " ".join(checks)
    has_data_test = contains_domain_hint(test_commands + " " + checks_text + " " + text, data_terms)
    if data_sensitive and not (has_data_acceptance and has_data_test):
        score = add_score(score, 0.35)
        findings.append(
            finding(
                "error",
                "data_structure_acceptance_missing",
                "data-sensitive task lacks test/acceptance coverage for schema/table/state/event structure",
            )
        )
    action = "repair" if any(item["kind"] == "declared_check_failed" for item in findings) else action_from_score(score)
    return expert_result("test_verifiability_expert", score, action, findings)


def evaluate_quality_expert(summary: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    patch_guard = summary.get("patch_guard") if isinstance(summary.get("patch_guard"), dict) else {}
    scope_guard = summary.get("scope_guard") if isinstance(summary.get("scope_guard"), dict) else {}
    if patch_guard.get("status") == "fail":
        score = add_score(score, 0.35)
        findings.append(finding("error", "patch_guard_failed", "patch guard failed", output_path=patch_guard.get("output_path", "")))
    if scope_guard.get("status") == "fail":
        score = add_score(score, 0.35)
        findings.append(finding("error", "scope_guard_failed", "scope guard failed", output_path=scope_guard.get("output_path", "")))
    if summary.get("status") == "pass" and not (patch_guard or scope_guard or summary.get("checks")):
        score = add_score(score, 0.2)
        findings.append(finding("warn", "thin_evidence", "pass status has thin patch/scope/check evidence"))
    return expert_result("quality_expert", score, "repair" if score >= 0.35 else action_from_score(score), findings)


def evaluate_exception_governance_expert(summary: dict[str, Any], worker: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    failure = summary.get("worker_failure") if isinstance(summary.get("worker_failure"), dict) else {}
    text = str(summary.get("_monitor_task_text") or "")
    if failure.get("category") or str(summary.get("status") or "").startswith("retryable-"):
        score = add_score(score, 0.22)
        findings.append(finding("warn", "worker_failure_requires_policy", "worker failure/retryable state needs explicit recovery policy", worker_failure=failure))
    communication_task = contains_any(text, COMMUNICATION_HINTS)
    if communication_task and contains_any(text, COMMUNICATION_MONITOR_EXEMPT_HINTS):
        communication_task = contains_any(text, COMMUNICATION_RUNTIME_HINTS) and contains_any(
            text,
            ("failure taxonomy", "recovery mapping", "error action", "异常", "失败", "恢复"),
        )
    if communication_task:
        lowered = text.lower()
        failure_classes = [item for item in FAILURE_CLASS_HINTS if re.search(rf"(?<![a-z0-9_]){re.escape(item)}(?![a-z0-9_])", lowered)]
        recovery_actions = [item for item in RECOVERY_ACTION_HINTS if re.search(rf"(?<![a-z0-9_]){re.escape(item)}(?![a-z0-9_])", lowered)]
        has_mapping = "->" in text or "map" in lowered or "mapping" in lowered or "映射" in text
        if len(failure_classes) < len(FAILURE_CLASS_HINTS) or len(recovery_actions) < 3 or not has_mapping:
            score = add_score(score, 0.35)
            findings.append(
                finding(
                    "error",
                    "communication_failure_taxonomy_missing",
                    "communication task must state failure classes and mapped recovery actions",
                    required_failure_classes=list(FAILURE_CLASS_HINTS),
                    required_recovery_actions=list(RECOVERY_ACTION_HINTS),
                )
            )
    if worker.get("idle_timed_out") or worker.get("timed_out"):
        score = add_score(score, 0.3)
        findings.append(finding("error", "worker_timeout", "worker timed out or idle timed out"))

    # Make context-router promptware blocking visible to monitor/control without leaking raw section bodies.
    blocked_sources: list[dict[str, Any]] = []
    worker_context_router = worker.get("context_router") if isinstance(worker.get("context_router"), dict) else {}
    if worker_context_router:
        blocked_sources.append(worker_context_router)
    context_pressure = summary.get("context_pressure") if isinstance(summary.get("context_pressure"), dict) else {}
    pressure_context_router = (
        context_pressure.get("context_router") if isinstance(context_pressure.get("context_router"), dict) else {}
    )
    if pressure_context_router:
        blocked_sources.append(pressure_context_router)

    blocked_sections_value = 0
    blocked_section_names: list[str] = []
    for source in blocked_sources:
        raw_count = source.get("blocked_sections")
        if isinstance(raw_count, int):
            blocked_sections_value = max(blocked_sections_value, raw_count)
        elif isinstance(raw_count, list):
            blocked_sections_value = max(blocked_sections_value, len(raw_count))
            for item in raw_count:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("section") or item.get("id")
                    if isinstance(name, str) and name.strip():
                        blocked_section_names.append(name.strip())
                elif isinstance(item, str) and item.strip():
                    blocked_section_names.append(item.strip())
        names = source.get("blocked_section_names")
        if isinstance(names, list):
            for item in names:
                if isinstance(item, str) and item.strip():
                    blocked_section_names.append(item.strip())

    if blocked_sections_value > 0:
        dedup_names = list(dict.fromkeys(blocked_section_names))
        findings.append(
            finding(
                "warn",
                "context_router_blocked_promptware",
                "context-router blocked reference-only prompt sections; monitor-visible for governance",
                blocked_sections=blocked_sections_value,
                blocked_section_names=dedup_names,
            )
        )
    return expert_result("exception_governance_expert", score, "repair" if score >= 0.3 else action_from_score(score), findings)


def evaluate_nfr_security_expert(text: str, commands: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    if contains_any(text, ("mobile", "control api", "ssh", "tailscale", "remote", "远程", "手机")) and not contains_any(text, ("audit", "permission", "权限", "审计", "token", "secret", "安全")):
        score = add_score(score, 0.22)
        findings.append(finding("warn", "remote_security_not_explicit", "remote/control task lacks explicit permission/audit/security framing"))
    for event in commands:
        command = normalize_command(str(event.get("command") or ""))
        if any(secret in command.lower() for secret in ("id_ed25519", "secret", "token=", "password")):
            score = add_score(score, 0.35)
            findings.append(finding("error", "sensitive_surface_touched", "worker command touched sensitive credential/token surface", command=command))
    action = "block_and_rewrite_task" if score >= 0.35 else action_from_score(score)
    return expert_result("nfr_security_expert", score, action, findings)


def evaluate_product_mainline(summary: dict[str, Any], text: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    phase = str(summary.get("phase") or "")
    status = str(summary.get("status") or "")
    if not contains_any(text, MAINLINE_HINTS):
        score = add_score(score, 0.2)
        findings.append(finding("warn", "mainline_not_named", "task does not name product mainline/philosophy/business logic"))
    if phase == "vendor_import" and status == "pass":
        score = add_score(score, 0.15)
        findings.append(finding("info", "vendor_import_requires_license_review", "vendor import should be license-reviewed"))
    if status.startswith("retryable-"):
        score = add_score(score, 0.25)
        findings.append(finding("warn", "mainline_not_advanced", "retryable run did not advance product mainline"))
    action = "product_rewrite" if score >= 0.45 else action_from_score(score)
    return expert_result("product_mainline_expert", score, action, findings)


def evaluate_external_learning_expert(text: str, commands: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    phase = str(summary.get("phase") or "")
    references_needed = phase in {"reference_scan", "mechanism_extract", "vendor_import"} or contains_any(
        text, ("抄", "copy", "mature", "reference", "顶级", "外部", "上网")
    )
    touched_reference = contains_any(text, REFERENCE_HINTS) or any(
        contains_any(normalize_command(str(event.get("command") or "")), REFERENCE_HINTS) for event in commands
    )
    touched_web_or_docs = any(
        contains_any(normalize_command(str(event.get("command") or "")), ("web", "curl ", "docs/", "reference-projects/", "vendor-src/"))
        for event in commands
    )
    if references_needed and not (touched_reference or touched_web_or_docs):
        score = add_score(score, 0.35)
        findings.append(finding("error", "no_external_or_reference_learning", "copy/reference task lacks observable reference or external learning evidence"))
    action = "block_and_rewrite_task" if score >= 0.35 else action_from_score(score)
    return expert_result("external_learning_expert", score, action, findings)


def evaluate_product_pressure_expert(text: str, summary: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    scope_guard = summary.get("scope_guard") if isinstance(summary.get("scope_guard"), dict) else {}
    changed_files = scope_guard.get("changed_files", []) if isinstance(scope_guard.get("changed_files"), list) else []
    if not contains_any(text, PRODUCT_PRESSURE_HINTS):
        score = add_score(score, 0.22)
        findings.append(finding("warn", "no_pressure_or_rejection_frame", "task lacks product pressure: no tradeoff/rejection/shrink criteria"))
    if summary.get("status") == "pass" and not changed_files and summary.get("phase") not in {"reference_scan", "mechanism_extract", "record"}:
        score = add_score(score, 0.28)
        findings.append(finding("warn", "pass_without_material_change", "implementation/test pass produced no material change; pressure for stronger artifact needed"))
    action = "product_rewrite" if score >= 0.45 else action_from_score(score)
    return expert_result("product_pressure_expert", score, action, findings)


def evaluate_data_model_expert(text: str, summary: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    phase = str(summary.get("phase") or "")
    data_sensitive = phase in {"implement", "mechanism_extract", "vendor_import"} or contains_any(
        text, ("api", "control", "session", "flow", "run", "memory", "redis", "mysql", "页面", "业务")
    )
    if data_sensitive and not contains_domain_hint(text, DATA_MODEL_HINTS):
        score = add_score(score, 0.35)
        findings.append(
            finding(
                "error",
                "data_model_not_explicit",
                "task does not state the data/event/state/table model that reflects real business structure",
            )
        )
    return expert_result("data_model_expert", score, "block_and_rewrite_task" if score >= 0.35 else action_from_score(score), findings)


def evaluate_performance_depth_expert(text: str, summary: dict[str, Any], worker: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    phase = str(summary.get("phase") or "")
    performance_sensitive = phase in {"implement", "test"} or contains_any(text, ("gateway", "redis", "stream", "ws", "ssh", "tailscale", "tmux", "mobile", "control"))
    if performance_sensitive and not contains_any(text, PERFORMANCE_HINTS):
        score = add_score(score, 0.22)
        findings.append(finding("warn", "performance_depth_not_explicit", "task lacks performance/stability/budget framing"))
    event_bytes = int(worker.get("event_bytes") or 0)
    if event_bytes > 100000:
        score = add_score(score, 0.2)
        findings.append(finding("warn", "trace_heavy", "worker trace is heavy and may indicate low execution efficiency", event_bytes=event_bytes))
    return expert_result("performance_depth_expert", score, "needs_tradeoff" if score >= 0.22 else action_from_score(score), findings)


def evaluate_business_boundary(commands: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 0.0
    business_terms = ("quant", "trading", "trading_strategy", "backtest", "finance", "金融", "交易", "量化")
    for event in commands:
        command = normalize_command(str(event.get("command") or "")).lower()
        if any(term in command for term in business_terms):
            score = add_score(score, 0.25)
            findings.append(finding("warn", "business_scope_drift", "worker touched business/quant surface during runtime work", command=command))
    return expert_result("business_boundary_expert", score, action_from_score(score), findings)


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


def gate_state(experts: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {str(item.get("name")): item for item in experts}

    def failed(names: list[str], threshold: float = 0.35) -> list[str]:
        return [name for name in names if float(by_name.get(name, {}).get("score", 0.0)) >= threshold]

    hard_failed = failed(["why_expert", "test_verifiability_expert", "exception_governance_expert", "nfr_security_expert", "data_model_expert"])
    tradeoff_failed = failed(["tradeoff_architecture_expert", "product_pressure_expert"], threshold=0.22)
    execution_failed = failed(["execution_governance_expert", "quality_expert"], threshold=0.35)
    progress_failed = failed(["product_mainline_expert", "external_learning_expert", "performance_depth_expert"], threshold=0.35)
    return {
        "hard_gate": {"status": "fail" if hard_failed else "pass", "failed_experts": hard_failed},
        "tradeoff_gate": {"status": "fail" if tradeoff_failed else "pass", "failed_experts": tradeoff_failed},
        "execution_gate": {"status": "fail" if execution_failed else "pass", "failed_experts": execution_failed},
        "progress_gate": {"status": "fail" if progress_failed else "pass", "failed_experts": progress_failed},
    }


def apply_gate_action(action: str, gates: dict[str, Any]) -> str:
    if gates["hard_gate"]["status"] == "fail":
        return "block_and_rewrite_task"
    if gates["execution_gate"]["status"] == "fail" and action_rank(action) < action_rank("repair"):
        return "repair"
    if gates["tradeoff_gate"]["status"] == "fail" and action_rank(action) < action_rank("needs_tradeoff"):
        return "needs_tradeoff"
    if gates["progress_gate"]["status"] == "fail" and action_rank(action) < action_rank("monitor_review"):
        return "monitor_review"
    return action


def score_run(run_dir: Path) -> dict[str, Any]:
    summary = read_json(run_dir / "summary.json")
    worker = summary.get("worker") if isinstance(summary.get("worker"), dict) else {}
    event_path = Path(worker.get("event_summaries_path") or run_dir / "event_summaries.jsonl")
    events = read_jsonl(event_path)
    commands = command_events(events)
    checks = declared_checks(summary)
    text = run_text(summary, run_dir)
    summary["_monitor_task_text"] = text
    experts = [
        evaluate_why_expert(text, summary),
        evaluate_scope_dependency_expert(text, summary),
        evaluate_system_requirement_expert(text),
        evaluate_tradeoff_architecture_expert(text, commands),
        evaluate_role_boundary_expert(text),
        evaluate_testing(summary, commands, checks, text),
        evaluate_quality_expert(summary),
        evaluate_exception_governance_expert(summary, worker),
        evaluate_nfr_security_expert(text, commands),
        evaluate_governance(summary, worker, commands),
        evaluate_product_mainline(summary, text),
        evaluate_external_learning_expert(text, commands, summary),
        evaluate_product_pressure_expert(text, summary),
        evaluate_data_model_expert(text, summary),
        evaluate_performance_depth_expert(text, summary, worker),
        evaluate_business_boundary(commands),
    ]
    score, recommended_action, findings = merge_experts(experts)
    gates = gate_state(experts)
    recommended_action = apply_gate_action(recommended_action, gates)

    payload = {
        "status": "ok",
        "run_dir": str(run_dir),
        "score": score,
        "recommended_action": recommended_action,
        "decision_model": "requirements_review_council_v1",
        "gates": gates,
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
