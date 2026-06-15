#!/usr/bin/env python3
"""Deterministic eval harness for A9 MemPalace causal-memory compiler."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROVIDER_PATH = ROOT / "scripts" / "a9_mempalace_provider.py"
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "mempalace_causal_eval.jsonl"
LABELS = ("current", "stale", "causal")
RISK_TERMS = (
    "过期",
    "不再",
    "不是主",
    "旧",
    "fallback",
    "不要",
    "没有",
    "当前",
    "主线",
    "因为",
    "所以",
    "变成",
    "从",
    "迁移",
    "保留",
    "raw evidence",
    "source hash",
)
DOMAIN_TERMS = (
    "A9",
    "主线",
    "supervisor",
    "MemPalace",
    "session",
    "页面监控",
    "24h",
    "24小时",
    "worker",
    "monitor",
    "evidence",
    "raw evidence",
    "需求分析",
    "博弈",
    "fallback",
    "KG",
    "diary",
)


def load_provider() -> Any:
    spec = importlib.util.spec_from_file_location("a9_mempalace_provider_eval", PROVIDER_PATH)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load provider: {PROVIDER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_fixture(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not row.get("id") or not isinstance(row.get("expected"), dict):
                raise SystemExit(f"{path}:{line_no}: id and expected are required")
            rows.append(row)
    return rows


def recall_packet_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "a9.mempalace_recall_packet.v1",
        "source": "a9_eval_fixture",
        "status": "ok",
        "query": "A9 causal memory quality eval",
        "truth_policy": "recall_not_truth",
        "search_hits": [],
        "fallback_recall": [],
        "fallback_evidence_refs": [],
        "hydrated_drawers": [
            {
                "drawer_id": f"eval:{row['id']}",
                "content": row.get("content") or "",
                "metadata": {
                    "drawer_id": f"eval:{row['id']}",
                    "source_ref": f"{row['id']}:1",
                    "source_sha256": row.get("source_sha256") or "eval-fixture",
                    "content_hash": row.get("id"),
                    "role": "fixture",
                    "event_kind": "message",
                    "filed_at": row.get("timestamp") or "2026-06-16T00:00:00Z",
                },
            }
            for row in rows
        ],
    }


def predictions_by_id(packet: dict[str, Any]) -> dict[str, set[str]]:
    predictions: dict[str, set[str]] = {}
    kg = packet.get("kg_candidates") if isinstance(packet.get("kg_candidates"), dict) else {}
    mapping = {
        "current": kg.get("current_facts") or [],
        "stale": kg.get("stale_branches") or [],
        "causal": kg.get("causal_changes") or [],
    }
    for label, items in mapping.items():
        for item in items:
            if not isinstance(item, dict):
                continue
            evidence_ref = item.get("evidence_ref") if isinstance(item.get("evidence_ref"), dict) else {}
            drawer_id = str(evidence_ref.get("drawer_id") or "")
            if not drawer_id.startswith("eval:"):
                continue
            sample_id = drawer_id.split("eval:", 1)[1]
            predictions.setdefault(sample_id, set()).add(label)
    return predictions


def score(rows: list[dict[str, Any]], predictions: dict[str, set[str]], elapsed_seconds: float) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    aggregate = {label: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for label in LABELS}
    for row in rows:
        sample_id = str(row["id"])
        expected = {label for label in LABELS if bool(row["expected"].get(label))}
        predicted = predictions.get(sample_id, set())
        false_negatives = sorted(expected - predicted)
        false_positives = sorted(predicted - expected)
        for label in LABELS:
            exp = label in expected
            pred = label in predicted
            if exp and pred:
                aggregate[label]["tp"] += 1
            elif not exp and pred:
                aggregate[label]["fp"] += 1
            elif exp and not pred:
                aggregate[label]["fn"] += 1
            else:
                aggregate[label]["tn"] += 1
        samples.append(
            {
                "id": sample_id,
                "expected": sorted(expected),
                "predicted": sorted(predicted),
                "status": "pass" if not false_negatives and not false_positives else "fail",
                "false_negatives": false_negatives,
                "false_positives": false_positives,
            }
        )

    metrics: dict[str, Any] = {}
    total_tp = total_fp = total_fn = 0
    for label, counts in aggregate.items():
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        total_tp += tp
        total_fp += fp
        total_fn += fn
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics[label] = {
            **counts,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }
    micro_precision = total_tp / (total_tp + total_fp) if total_tp + total_fp else 1.0
    micro_recall = total_tp / (total_tp + total_fn) if total_tp + total_fn else 1.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if micro_precision + micro_recall
        else 0.0
    )
    return {
        "schema": "a9.mempalace_causal_eval.v1",
        "status": "pass" if all(sample["status"] == "pass" for sample in samples) else "fail",
        "truth_policy": "fixture_expected_labels_are_eval_truth; compiler_output_remains_candidate_memory",
        "copied_protocols": [
            "MemPalace uses deterministic tests to pin documented behavior",
            "MemPalace recall metrics report recall/ndcg against fixtures",
            "A9 evaluates compiler labels against evidence-backed fixture drawers",
        ],
        "sample_count": len(rows),
        "elapsed_seconds": round(elapsed_seconds, 4),
        "metrics": metrics,
        "micro": {
            "precision": round(micro_precision, 4),
            "recall": round(micro_recall, 4),
            "f1": round(micro_f1, 4),
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
        },
        "samples": samples,
        "wrongbook_candidates": [sample for sample in samples if sample["status"] != "pass"],
    }


def run_eval(fixture: Path) -> dict[str, Any]:
    provider = load_provider()
    rows = read_fixture(fixture)
    recall_packet = recall_packet_from_rows(rows)
    start = time.perf_counter()
    packet = provider.build_causal_memory_packet(recall_packet, query="A9 causal memory quality eval", max_items=64)
    elapsed = time.perf_counter() - start
    result = score(rows, predictions_by_id(packet), elapsed)
    result["compiler"] = {
        "schema": packet.get("schema"),
        "current_facts": len(packet.get("kg_candidates", {}).get("current_facts") or []),
        "stale_branches": len(packet.get("kg_candidates", {}).get("stale_branches") or []),
        "causal_changes": len(packet.get("kg_candidates", {}).get("causal_changes") or []),
    }
    return result


def candidate_labels(provider: Any, content: str) -> set[str]:
    stale_signal = provider.has_stale_signal(content)
    causal_signal = provider.has_any(content, provider.CAUSAL_MARKERS)
    labels: set[str] = set()
    if provider.has_current_signal(content, stale_signal=stale_signal) or (causal_signal and not stale_signal):
        labels.add("current")
    if stale_signal:
        labels.add("stale")
    if causal_signal:
        labels.add("causal")
    return labels


def candidate_reasons(content: str, labels: set[str]) -> list[str]:
    lower = content.lower()
    reasons: list[str] = []
    if {"current", "stale"}.issubset(labels):
        reasons.append("same_text_current_and_stale")
    if "stale" in labels and any(term in lower for term in ("fallback", "不再", "不是主", "旧")):
        reasons.append("stale_branch_candidate")
    if "causal" in labels:
        reasons.append("causal_change_candidate")
    if any(term in lower for term in ("没有", "不要", "not ", "no ")):
        reasons.append("negation_edge_case")
    if any(term in lower for term in ("从", "变成", "迁移", "replaced", "became")):
        reasons.append("migration_or_replacement")
    if any(term in lower for term in ("raw evidence", "source hash", "事实源")):
        reasons.append("evidence_authority")
    if not reasons:
        reasons.append("marker_overlap")
    return reasons


def candidate_score(content: str, labels: set[str], reasons: list[str]) -> int:
    lower = content.lower()
    score_value = len(labels) * 5 + len(reasons) * 3
    score_value += sum(4 for term in DOMAIN_TERMS if term.lower() in lower)
    if {"current", "stale"}.issubset(labels):
        score_value += 8
    if {"current", "causal"}.issubset(labels):
        score_value += 5
    if "marker_overlap" == reasons[0]:
        score_value -= 4
    return score_value


def generate_eval_candidates(drawers: Path, *, limit: int = 20, scan_limit: int = 5000) -> dict[str, Any]:
    provider = load_provider()
    candidates: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    scanned = 0
    for row in provider.read_drawers(drawers):
        if scan_limit > 0 and scanned >= scan_limit:
            break
        scanned += 1
        if row.get("event_kind") != "message":
            continue
        content = str(row.get("content") or "")
        if not content.strip() or provider.is_context_injection(content):
            continue
        compacted = provider.compact(content, 260)
        lower = compacted.lower()
        if not any(term.lower() in lower for term in RISK_TERMS):
            continue
        labels = candidate_labels(provider, compacted)
        if not labels:
            continue
        reasons = candidate_reasons(compacted, labels)
        score_value = candidate_score(compacted, labels, reasons)
        if score_value < 10:
            continue
        key = str(row.get("content_hash") or compacted)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            (
                score_value,
                {
                    "schema": "a9.mempalace_causal_eval_candidate.v1",
                    "id": "",
                    "content": compacted,
                    "suggested_expected": {label: label in labels for label in LABELS},
                    "candidate_reasons": reasons,
                    "score": score_value,
                    "source_ref": row.get("source_ref"),
                    "source_sha256": row.get("source_sha256"),
                    "content_hash": row.get("content_hash"),
                    "drawer_id": row.get("drawer_id"),
                    "role": row.get("role"),
                    "timestamp": row.get("timestamp"),
                    "review_required": True,
                    "fixture_line": {
                        "id": "",
                        "content": compacted,
                        "expected": {label: label in labels for label in LABELS},
                    },
                },
            )
        )
    selected = [item for _, item in sorted(candidates, key=lambda entry: (-entry[0], str(entry[1].get("source_ref") or "")))[:limit]]
    for index, candidate in enumerate(selected, start=1):
        candidate_id = f"candidate-{index:04d}"
        candidate["id"] = candidate_id
        candidate["fixture_line"]["id"] = candidate_id
    return {
        "schema": "a9.mempalace_causal_eval_candidates.v1",
        "status": "ok",
        "truth_policy": "candidate_expected_labels_are_suggestions; human_or_monitor_review_required_before_fixture_merge",
        "copied_protocols": [
            "MemPalace keeps source refs with drawers so eval candidates remain auditable",
            "MemPalace tests pin behavior after review instead of trusting summaries",
            "A9 candidates are review material, not fixture truth",
        ],
        "drawers_path": str(drawers),
        "scanned_rows": scanned,
        "scan_limit": scan_limit,
        "candidate_count": len(selected),
        "candidates": selected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate A9 MemPalace causal-memory compiler quality")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--generate-candidates", action="store_true")
    parser.add_argument("--drawers", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--scan-limit", type=int, default=5000)
    args = parser.parse_args()
    if args.generate_candidates:
        provider = load_provider()
        drawers = args.drawers or provider.DEFAULT_DRAWERS
        result = generate_eval_candidates(drawers, limit=args.limit, scan_limit=args.scan_limit)
    else:
        result = run_eval(args.fixture)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["status"] in {"ok", "pass"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
