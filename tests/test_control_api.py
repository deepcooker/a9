#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import http.client
import io
import os
import json
import argparse
import contextlib
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CONTROL_API_PATH = ROOT / "scripts" / "a9_control_api.py"
NODE_PATH = ROOT / "scripts" / "a9_node.py"


def load_control_api():
    spec = importlib.util.spec_from_file_location("a9_control_api", CONTROL_API_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_node():
    spec = importlib.util.spec_from_file_location("a9_node", NODE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ControlApiTests(unittest.TestCase):
    def test_compact_summary_exposes_mobile_control_fields(self):
        mod = load_control_api()
        summary = {
            "task_id": "task-1",
            "status": "pass",
            "phase": "implement",
            "run_dir": "/tmp/run",
            "context_path": "/tmp/run/context.md",
            "evidence_path": "/tmp/run/evidence.jsonl",
            "state_path": "/tmp/run/state.json",
            "deep_marks_path": "/tmp/run/deep_marks.jsonl",
            "worker": {"actual_token_usage": {"input_tokens": 10}},
            "worker_failure": {"status": ""},
            "worker_envelope": {"status": "pass", "required": True},
            "checks": [{"command": "true", "return_code": 0}],
            "patch_guard": {"status": "pass"},
            "scope_guard": {"status": "pass"},
            "git_governance": {"status": "skip"},
            "policy_attestation": {"attestation_hash": "abc"},
            "monitor_block": {
                "blocked": True,
                "reason": "monitor_hard_gate_failed",
                "failed_experts": ["data_model_expert"],
            },
            "monitor_score": {
                "decision_model": "requirements_review_council",
                "score": 0.41,
                "recommended_action": "repair",
                "gates": {
                    "data_model": {"status": "fail", "reason": "schema missing"},
                    "performance_depth": {"status": "pass"},
                },
                "findings": [
                    {"gate": "data_model", "severity": "high", "message": "missing state field"},
                ],
                "experts": [
                    {"name": "product_mainline", "vote": "fail"},
                ],
            },
            "context_pressure": {"budget_ratio": 0.25},
            "runtime_monitor_contract": {
                "schema": "a9.runtime_monitor_contract.v1",
                "task": {
                    "task_id": "task-1",
                    "phase": "implement",
                    "route": "execution_next",
                    "plan_revision": 3,
                    "allowed_paths": ["scripts/"],
                    "declared_checks": ["python3 -m py_compile scripts/a9_supervisor.py"],
                },
                "run": {
                    "run_id": "run-1",
                    "status": "pass",
                    "attempt": 1,
                    "run_dir": "/tmp/run",
                },
                "worker_intent": {
                    "status": "visible",
                    "phase_focus": "Implement",
                    "reference_gate_status": "pass",
                },
                "worker_prompt": {
                    "prompt_path": "/tmp/run/prompt.md",
                    "raw_task_path": "/tmp/run/raw_task.md",
                    "prompt_approx_tokens": 100,
                    "prompt_budget_tokens": 24000,
                },
                "command_envelope": {
                    "command_id": "task-1",
                    "target_node": "local-supervisor",
                    "expected_revision": 1,
                    "idempotency_key": "task-1:1",
                    "evidence_path": "/tmp/run/evidence.jsonl",
                },
                "execution": {
                    "worker_model": "gpt-5.3-codex-spark",
                    "return_code": 0,
                    "timed_out": False,
                    "idle_timed_out": False,
                    "budget_stopped": False,
                },
                "diff_and_checks": {
                    "changed_files": ["scripts/a9_supervisor.py"],
                    "checks_count": 1,
                    "failed_checks_count": 0,
                    "diff_path": "/tmp/run/patch.diff",
                },
                "monitor": {
                    "next_action": "continue",
                    "recommended_action": "continue",
                    "decision_model": "requirements_review_council",
                    "score": 0.9,
                    "intervention_options": ["pause", "repair"],
                    "block": {"blocked": False},
                },
                "evidence_refs": {
                    "runtime_monitor_contract_path": "/tmp/run/runtime_monitor_contract.json",
                    "summary_path": "/tmp/run/summary.json",
                    "execution_chain_path": "/tmp/run/execution_chain.json",
                    "evidence_path": "/tmp/run/evidence.jsonl",
                    "state_path": "/tmp/run/state.json",
                },
                "guardrails": {"page_details_frozen": True, "no_nzx_business_code": True},
            },
        }
        summary["context_pressure"]["context_router"] = {
            "strategy": "hermes_context_router_v1",
            "blocked_sections": 2,
        }

        compact = mod.compact_summary(summary)

        self.assertEqual(compact["task_id"], "task-1")
        self.assertEqual(compact["worker_envelope"]["status"], "pass")
        self.assertEqual(compact["policy_attestation"]["attestation_hash"], "abc")
        self.assertTrue(compact["monitor_block"]["blocked"])
        self.assertEqual(compact["monitor_block"]["failed_experts"], ["data_model_expert"])
        self.assertEqual(compact["monitor_score"]["decision_model"], "requirements_review_council")
        self.assertEqual(compact["monitor_score"]["recommended_action"], "repair")
        self.assertEqual(compact["monitor_score"]["gates"]["data_model"]["status"], "fail")
        self.assertEqual(compact["monitor_score"]["findings"][0]["gate"], "data_model")
        self.assertNotIn("experts", compact["monitor_score"])
        self.assertEqual(compact["actual_token_usage"]["input_tokens"], 10)
        self.assertEqual(compact["context_path"], "/tmp/run/context.md")
        self.assertEqual(compact["evidence_path"], "/tmp/run/evidence.jsonl")
        self.assertEqual(compact["context_router"]["strategy"], "hermes_context_router_v1")
        self.assertEqual(compact["context_router"]["blocked_sections"], 2)
        runtime_contract = compact["runtime_monitor_contract"]
        self.assertEqual(runtime_contract["schema"], "a9.runtime_monitor_contract.v1")
        self.assertEqual(runtime_contract["task"]["route"], "execution_next")
        self.assertEqual(runtime_contract["command_envelope"]["idempotency_key"], "task-1:1")
        self.assertEqual(runtime_contract["monitor"]["next_action"], "continue")
        self.assertTrue(runtime_contract["guardrails"]["page_details_frozen"])

    def test_compact_summary_falls_back_to_worker_context_router(self):
        mod = load_control_api()
        compact = mod.compact_summary(
            {
                "task_id": "task-2",
                "worker": {
                    "context_router": {
                        "strategy": "hermes_context_router_v1",
                        "blocked_sections": 1,
                        "sections": [{"name": "Previous Task Context Tail"}],
                    }
                },
                "context_pressure": {},
            }
        )

        self.assertEqual(compact["context_router"]["strategy"], "hermes_context_router_v1")
        self.assertEqual(compact["context_router"]["blocked_sections"], 1)
        self.assertEqual(compact["context_router"]["section_count"], 1)

    def test_operator_tail_reads_latest_codex_session_under_allowed_root(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            session = base / "2026" / "05" / "24" / "rollout.jsonl"
            session.parent.mkdir(parents=True)
            rows = [
                {"type": "session_meta", "payload": {"id": "sess-1"}},
                {
                    "type": "response_item",
                    "timestamp": "2026-05-24T00:00:00Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "first instruction"}],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-24T00:01:00Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "second instruction"}],
                    },
                },
            ]
            session.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            old_base = mod.CODEX_SESSIONS_DIR
            mod.CODEX_SESSIONS_DIR = base
            try:
                tail = mod.operator_tail(limit=1)
            finally:
                mod.CODEX_SESSIONS_DIR = old_base

        self.assertEqual(tail["status"], "ok")
        self.assertEqual(tail["session_id"], "sess-1")
        self.assertEqual(len(tail["turns"]), 1)
        self.assertEqual(tail["turns"][0]["preview"], "second instruction")

    def test_mempalace_search_returns_source_preserving_recall(self):
        mod = load_control_api()
        provider = SimpleNamespace(
            DEFAULT_DRAWERS=Path("/tmp/drawers.jsonl"),
            search_drawers=lambda drawers, query, limit, role=None, event_kind=None: [
                {
                    "source_ref": "session.jsonl:10",
                    "source_sha256": "sourcehash",
                    "content_hash": "contenthash",
                    "role": role or "user",
                    "event_kind": event_kind or "message",
                    "content": "MemPalace first",
                }
            ],
        )
        with mock.patch.object(mod, "mempalace_provider", return_value=provider):
            result = mod.mempalace_search(
                {"query": "MemPalace first", "limit": 99, "role": "user", "event_kind": "message"}
            )

        self.assertEqual(result["schema"], "a9.control_api.mempalace_search.v1")
        self.assertEqual(result["truth_policy"], "recall_not_truth")
        self.assertEqual(result["results"][0]["source_ref"], "session.jsonl:10")
        self.assertEqual(result["results"][0]["content_hash"], "contenthash")

    def test_mempalace_wakeup_does_not_claim_truth(self):
        mod = load_control_api()

        def fake_wakeup(drawers, query, limit):
            return {
                "schema": "a9.wakeup_pack.v1",
                "truth_policy": "recall_not_truth",
                "evidence_refs": [{"source_ref": "session.jsonl:11", "content_hash": "hash"}],
                "recall": [],
            }

        provider = SimpleNamespace(DEFAULT_DRAWERS=Path("/tmp/drawers.jsonl"), build_wakeup=fake_wakeup)
        with mock.patch.object(mod, "mempalace_provider", return_value=provider):
            result = mod.mempalace_wakeup({"query": "mainline", "limit": 2})

        self.assertEqual(result["schema"], "a9.control_api.mempalace_wakeup.v1")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["truth_policy"], "recall_not_truth")
        self.assertEqual(result["evidence_refs"][0]["source_ref"], "session.jsonl:11")

    def test_mempalace_recall_uses_official_style_packet(self):
        mod = load_control_api()

        def fake_recall(drawers, query, limit, hydrate, wing, room):
            return {
                "schema": "a9.mempalace_recall_packet.v1",
                "status": "ok",
                "query": query,
                "truth_policy": "recall_not_truth",
                "official_protocol": ["verbatim drawer hits", "drawer_id hydration"],
                "filters": {"wing": wing, "room": room},
                "search_hits": [{"drawer_id": "d1"}],
                "hydrated_drawers": [{"drawer_id": "d1", "content": "full text"}],
                "fallback_evidence_refs": [],
                "fallback_recall": [],
            }

        provider = SimpleNamespace(
            DEFAULT_DRAWERS=Path("/tmp/drawers.jsonl"),
            DEFAULT_NATIVE_WING="operator-codex-native",
            DEFAULT_NATIVE_ROOM="codex-message",
            build_recall_packet=fake_recall,
        )
        with mock.patch.object(mod, "mempalace_provider", return_value=provider):
            result = mod.mempalace_recall({"query": "session governance", "limit": 2, "hydrate": 1})

        self.assertEqual(result["schema"], "a9.control_api.mempalace_recall.v1")
        self.assertEqual(result["truth_policy"], "recall_not_truth")
        self.assertEqual(result["search_hits"][0]["drawer_id"], "d1")
        self.assertEqual(result["hydrated_drawers"][0]["content"], "full text")

    def test_mempalace_causal_compile_returns_candidate_memory_packet(self):
        mod = load_control_api()

        def fake_compile(drawers, query, limit, hydrate, wing, room):
            return {
                "schema": "a9.causal_memory_packet.v1",
                "status": "ok",
                "query": query,
                "truth_policy": "candidate_memory_not_truth",
                "kg_candidates": {
                    "current_facts": [{"text": "current", "kg_action": "add_fact_candidate"}],
                    "stale_branches": [{"text": "old", "kg_action": "invalidate_candidate"}],
                    "causal_changes": [{"change": "old -> current"}],
                },
                "role_packets": {"monitor": {"entries": []}},
                "next_task_memory": {"must_include": []},
            }

        provider = SimpleNamespace(
            DEFAULT_DRAWERS=Path("/tmp/drawers.jsonl"),
            DEFAULT_NATIVE_WING="operator-codex-native",
            DEFAULT_NATIVE_ROOM="codex-message",
            build_causal_memory_from_query=fake_compile,
        )
        with mock.patch.object(mod, "mempalace_provider", return_value=provider):
            result = mod.mempalace_causal_compile({"query": "mainline changed", "limit": 2, "hydrate": 1})

        self.assertEqual(result["schema"], "a9.control_api.mempalace_causal_compile.v1")
        self.assertEqual(result["truth_policy"], "candidate_memory_not_truth")
        self.assertEqual(result["kg_candidates"]["stale_branches"][0]["kg_action"], "invalidate_candidate")
        self.assertIn("monitor", result["role_packets"])

    def test_mempalace_causal_commit_requires_packet_and_returns_dry_run(self):
        mod = load_control_api()

        def fake_commit(packet, approved_by, approval_reason, dry_run):
            return {
                "schema": "a9.causal_memory_commit_result.v1",
                "status": "dry_run" if dry_run else "ok",
                "plan": {
                    "approved_by": approved_by,
                    "approval_reason": approval_reason,
                    "operations": [{"operation": "kg_add"}],
                },
                "results": [],
            }

        provider = SimpleNamespace(commit_causal_memory_packet=fake_commit)
        with mock.patch.object(mod, "mempalace_provider", return_value=provider):
            invalid = mod.mempalace_causal_commit({"approved_by": "monitor"})
            result = mod.mempalace_causal_commit(
                {
                    "causal_packet": {"schema": "a9.causal_memory_packet.v1"},
                    "approved_by": "codex-monitor",
                    "approval_reason": "reviewed",
                    "commit": False,
                }
            )

        self.assertEqual(invalid["status"], "invalid_request")
        self.assertEqual(result["schema"], "a9.control_api.mempalace_causal_commit.v1")
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["plan"]["approved_by"], "codex-monitor")

    def test_mempalace_causal_audit_returns_side_effect_free_report(self):
        mod = load_control_api()

        def fake_audit(subject):
            return {
                "schema": "a9.causal_memory_audit.v1",
                "status": "review_required",
                "subject": subject,
                "conflict_count": 1,
                "invalidation_candidates": [{"operation": "kg_invalidate_candidate"}],
            }

        provider = SimpleNamespace(audit_causal_memory_state=fake_audit)
        with mock.patch.object(mod, "mempalace_provider", return_value=provider):
            result = mod.mempalace_causal_audit({"subject": "A9"})

        self.assertEqual(result["schema"], "a9.control_api.mempalace_causal_audit.v1")
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["subject"], "A9")
        self.assertEqual(result["invalidation_candidates"][0]["operation"], "kg_invalidate_candidate")

    def test_mempalace_causal_repair_propose_returns_review_candidates(self):
        mod = load_control_api()

        def fake_repair(audit_report, subject):
            return {
                "schema": "a9.causal_memory_repair_proposal.v1",
                "status": "review_required",
                "subject": subject,
                "truth_policy": "side_effect_free_repair_candidates_not_truth",
                "proposal_count": 1,
                "invalidation_candidates": [
                    {
                        "operation": "kg_invalidate_candidate",
                        "object": "A9 old route is stale.",
                        "requires_monitor_decision": True,
                    }
                ],
            }

        provider = SimpleNamespace(propose_causal_memory_repairs=fake_repair)
        with mock.patch.object(mod, "mempalace_provider", return_value=provider):
            invalid = mod.mempalace_causal_repair_propose({"audit_report": []})
            result = mod.mempalace_causal_repair_propose(
                {
                    "subject": "A9",
                    "audit_report": {
                        "schema": "a9.causal_memory_audit.v1",
                        "status": "review_required",
                    },
                }
            )

        self.assertEqual(invalid["status"], "invalid_request")
        self.assertEqual(result["schema"], "a9.control_api.mempalace_causal_repair_propose.v1")
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["truth_policy"], "side_effect_free_repair_candidates_not_truth")
        self.assertEqual(result["invalidation_candidates"][0]["operation"], "kg_invalidate_candidate")

    def test_mempalace_causal_invalidate_requires_candidates_and_returns_dry_run(self):
        mod = load_control_api()

        def fake_invalidate(candidates, approved_by, approval_reason, dry_run):
            return {
                "schema": "a9.causal_memory_invalidation_result.v1",
                "status": "dry_run" if dry_run else "ok",
                "plan": {
                    "approved_by": approved_by,
                    "approval_reason": approval_reason,
                    "operations": [{"operation": "kg_invalidate"}],
                },
                "results": [],
            }

        provider = SimpleNamespace(apply_approved_invalidations=fake_invalidate)
        with mock.patch.object(mod, "mempalace_provider", return_value=provider):
            invalid = mod.mempalace_causal_invalidate({"approved_by": "monitor"})
            result = mod.mempalace_causal_invalidate(
                {
                    "invalidation_candidates": [{"operation": "kg_invalidate_candidate"}],
                    "approved_by": "codex-monitor",
                    "approval_reason": "stale branch selected",
                    "commit": False,
                }
            )

        self.assertEqual(invalid["status"], "invalid_request")
        self.assertEqual(result["schema"], "a9.control_api.mempalace_causal_invalidate.v1")
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["plan"]["operations"][0]["operation"], "kg_invalidate")

    def test_mempalace_causal_eval_generate_latest_and_merge_reviewed(self):
        mod = load_control_api()

        def fake_generate(drawers, limit, scan_limit):
            return {
                "schema": "a9.mempalace_causal_eval_candidates.v1",
                "status": "ok",
                "drawers_path": str(drawers),
                "candidate_count": 1,
                "candidates": [
                    {
                        "id": "candidate-0001",
                        "review_status": "approved",
                        "fixture_line": {
                            "id": "reviewed-0001",
                            "content": "当前主线是 supervisor runtime。",
                            "expected": {"current": True, "stale": False, "causal": False},
                        },
                    }
                ],
                "scanned_rows": scan_limit,
            }

        def fake_merge(path, fixture, approved_by, approval_reason, commit):
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            return {
                "schema": "a9.mempalace_causal_fixture_merge.v1",
                "status": "dry_run" if not commit else "committed",
                "fixture": str(fixture),
                "approved_by": approved_by,
                "approval_reason": approval_reason,
                "merged_count": len(payload.get("candidates", [])),
            }

        evaluator = SimpleNamespace(
            DEFAULT_FIXTURE=Path("/tmp/fixture.jsonl"),
            generate_eval_candidates=fake_generate,
            merge_reviewed_candidates=fake_merge,
        )
        provider = SimpleNamespace(DEFAULT_DRAWERS=Path("/tmp/drawers.jsonl"))
        old_root = mod.ROOT
        with tempfile.TemporaryDirectory() as tmp:
            mod.ROOT = Path(tmp)
            try:
                with mock.patch.object(mod, "mempalace_eval", return_value=evaluator), mock.patch.object(
                    mod, "mempalace_provider", return_value=provider
                ):
                    generated = mod.mempalace_causal_eval_generate_candidates({"limit": 1, "scan_limit": 7})
                    generated_output_exists = Path(generated["output_path"]).exists()
                    latest = mod.mempalace_causal_eval_latest_candidates()
                    merged = mod.mempalace_causal_eval_merge_reviewed(
                        {
                            "candidates": generated["candidates"],
                            "approved_by": "codex-monitor",
                            "approval_reason": "reviewed",
                            "commit": False,
                        }
                    )
            finally:
                mod.ROOT = old_root

        self.assertEqual(generated["schema"], "a9.control_api.mempalace_causal_eval_generate_candidates.v1")
        self.assertEqual(generated["candidate_count"], 1)
        self.assertTrue(generated_output_exists)
        self.assertEqual(latest["schema"], "a9.control_api.mempalace_causal_eval_latest_candidates.v1")
        self.assertEqual(latest["candidate_count"], 1)
        self.assertEqual(merged["schema"], "a9.control_api.mempalace_causal_eval_merge_reviewed.v1")
        self.assertEqual(merged["status"], "dry_run")
        self.assertEqual(merged["merged_count"], 1)

    def test_supervisor_status_reads_existing_a9_state(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".a9" / "tasks" / "queue").mkdir(parents=True)
            (root / ".a9" / "tasks" / "running").mkdir(parents=True)
            (root / ".a9" / "tasks" / "done").mkdir(parents=True)
            (root / ".a9" / "runs" / "run-1").mkdir(parents=True)
            (root / ".a9" / "runtime").mkdir(parents=True)
            (root / ".a9" / "tasks" / "queue" / "task.md").write_text(
                """---
id: "task"
phase: "implement"
checks:
  - "test \\"alpha\\" = beta"
allowed_paths:
  - ".a9/smoke/file.txt"
task_quality_warnings:
  - "write_scope_runtime_ignored_path:.a9"
  - "declared_check_maybe_shell_expanded:test_literal"
---
demo
""",
                encoding="utf-8",
            )
            (root / ".a9" / "progress.json").write_text('{"progress_percent": 1}', encoding="utf-8")
            (root / ".a9" / "runtime" / "worker_transport_health.json").write_text(
                json.dumps({"schema": "a9.worker_transport_health.v1", "status": "cooldown"}),
                encoding="utf-8",
            )
            (root / ".a9" / "runs" / "run-1" / "summary.json").write_text(
                json.dumps({"task_id": "task", "status": "pass", "run_dir": str(root / ".a9" / "runs" / "run-1")}),
                encoding="utf-8",
            )

            original_run = mod.subprocess.run
            mod.subprocess.run = lambda *args, **kwargs: type(
                "FakeProc",
                (),
                {
                    "returncode": 0,
                    "stdout": "101 1 00:10 python3 scripts/a9_control_api.py serve --host 0.0.0.0 --port 8787\n",
                },
            )()
            try:
                status = mod.supervisor_status(root)
            finally:
                mod.subprocess.run = original_run

        self.assertEqual(status["queued"], 1)
        self.assertEqual(status["task_quality"]["status"], "warning")
        self.assertEqual(status["task_quality"]["warning_task_count"], 1)
        self.assertEqual(status["task_quality"]["warnings_count"], 2)
        self.assertEqual(status["task_quality"]["warnings_by_code"]["write_scope_runtime_ignored_path"], 1)
        self.assertEqual(status["latest_run"]["task_id"], "task")
        self.assertEqual(status["progress"]["progress_percent"], 1)
        self.assertEqual(status["worker_transport_health"]["status"], "cooldown")
        self.assertEqual(status["nodes"]["count"], 0)
        self.assertEqual(status["gateway"]["status"], "missing")
        service_observation = status["service_observation"]
        self.assertEqual(service_observation["status"], "ok")
        self.assertEqual(service_observation["observed"]["missing_count"], 3)
        self.assertIn("supervisor", service_observation["observed"]["missing_services"])
        self.assertEqual(service_observation["observed"]["next_action"], "start_missing_services")
        self.assertEqual(service_observation["intent"]["services"][0]["service"], "control-api")
        control_api = next(item for item in service_observation["observed"]["services"] if item["service"] == "control-api")
        self.assertTrue(control_api["observed_running"])
        self.assertEqual(control_api["observation_status"], "running")
        self.assertEqual(control_api["next_action"], "observe")

    def test_supervisor_status_exposes_latest_run_lanes_for_mobile_monitor(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / ".a9"
            for name in ["queue", "running", "done"]:
                (state_dir / "tasks" / name).mkdir(parents=True)
            runs_dir = state_dir / "runs"
            real_run = runs_dir / "real-run"
            plan_run = runs_dir / "plan-run"
            selftest_run = runs_dir / "selftest-status"
            for path in [real_run, plan_run, selftest_run]:
                path.mkdir(parents=True)
            (real_run / "summary.json").write_text(
                json.dumps({"task_id": "real-task", "status": "pass", "run_dir": str(real_run)}),
                encoding="utf-8",
            )
            (plan_run / "summary.json").write_text(
                json.dumps(
                    {
                        "task_id": "plan-task",
                        "status": "needs-followup",
                        "phase": "mechanism_extract",
                        "run_dir": str(plan_run),
                    }
                ),
                encoding="utf-8",
            )
            (selftest_run / "summary.json").write_text(
                json.dumps({"task_id": "selftest-status", "status": "pass", "run_dir": str(selftest_run)}),
                encoding="utf-8",
            )
            plan_dir = state_dir / "plans" / "active-plan"
            plan_dir.mkdir(parents=True)
            (state_dir / "plans" / ".active_plan").write_text("active-plan\n", encoding="utf-8")
            (plan_dir / "plan.json").write_text(
                json.dumps(
                    {
                        "schema": "a9.plan.v1",
                        "plan_id": "active-plan",
                        "run_ids": ["plan-run"],
                        "evidence_refs": [str(plan_run / "summary.json")],
                    }
                ),
                encoding="utf-8",
            )
            (plan_dir / "progress.md").write_text(
                "# Progress\n\n"
                "- 2026-06-07 actor=worker note=plan execution continuing\n"
                "- 2026-06-07 actor=monitor note=monitor intervention completed intervention_id=resume-001\n",
                encoding="utf-8",
            )
            os.utime(real_run / "summary.json", (1000, 1000))
            os.utime(plan_run / "summary.json", (1001, 1001))
            os.utime(selftest_run / "summary.json", (1002, 1002))

            status = mod.supervisor_status(root)

        self.assertEqual(status["latest_run"]["task_id"], "selftest-status")
        lanes = status["latest_run_lanes"]
        self.assertEqual(lanes["latest_any"]["task_id"], "selftest-status")
        self.assertEqual(lanes["latest_selftest"]["task_id"], "selftest-status")
        self.assertEqual(lanes["latest_real"]["task_id"], "plan-task")
        self.assertEqual(lanes["latest_plan"]["task_id"], "plan-task")
        self.assertEqual(lanes["latest_plan"]["phase"], "mechanism_extract")
        self.assertEqual(lanes["latest_plan"]["summary_path"], str(plan_run / "summary.json"))
        self.assertEqual(
            lanes["latest_plan_progress"]["latest_progress"],
            "- 2026-06-07 actor=monitor note=monitor intervention completed intervention_id=resume-001",
        )
        self.assertEqual(
            lanes["latest_plan_progress"]["latest_monitor_progress"],
            "- 2026-06-07 actor=monitor note=monitor intervention completed intervention_id=resume-001",
        )
        self.assertTrue(lanes["latest_plan_progress"]["has_monitor_progress"])

    def test_gateway_transport_contract_runs_local_binary(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "target" / "debug" / "a9-gateway"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n", encoding="utf-8")

            class FakeProc:
                returncode = 0
                stdout = json.dumps(
                    {
                        "status": "ok",
                        "kind": "gateway_transport_contract",
                        "capacity": 128,
                        "overload_error_code": -32001,
                        "request_overload_returns_retry_error": True,
                        "response_waits_on_backpressure": True,
                        "writer_full_preserves_existing_message": True,
                    }
                )

            original_run = mod.subprocess.run
            original_redis = mod.redis_cli
            try:
                calls = []

                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.subprocess.run = fake_run
                mod.redis_cli = lambda *args, **kwargs: type("FakeRedis", (), {"returncode": 0, "stdout": ""})()
                result = mod.gateway_transport_contract(root)
            finally:
                mod.subprocess.run = original_run
                mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reason"], "gateway_contract_pass")
        self.assertEqual(calls[0][0], [str(binary), "transport-contract"])
        self.assertEqual(result["latest_event"]["status"], "missing")
        self.assertEqual(result["runtime_evidence"]["status"], "degraded")
        self.assertEqual(result["runtime_evidence"]["action"], "emit_runtime_event")

    def test_gateway_transport_contract_can_request_event_emission(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "target" / "debug" / "a9-gateway"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n", encoding="utf-8")

            class FakeProc:
                returncode = 0
                stdout = json.dumps(
                    {
                        "status": "ok",
                        "kind": "gateway_transport_contract",
                        "capacity": 128,
                        "overload_error_code": -32001,
                        "request_overload_returns_retry_error": True,
                        "response_waits_on_backpressure": True,
                        "writer_full_preserves_existing_message": True,
                        "event_id": "1700000000-0",
                    }
                )

            original_run = mod.subprocess.run
            original_redis = mod.redis_cli
            try:
                calls = []

                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.subprocess.run = fake_run
                mod.redis_cli = lambda *args, **kwargs: type("FakeRedis", (), {"returncode": 0, "stdout": ""})()
                result = mod.gateway_transport_contract(root, emit_event=True)
            finally:
                mod.subprocess.run = original_run
                mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["event_id"], "1700000000-0")
        self.assertEqual(calls[0][0], [str(binary), "transport-contract", "--emit-event"])

    def test_gateway_transport_contract_fails_invalid_contract(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "target" / "debug" / "a9-gateway"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n", encoding="utf-8")

            class FakeProc:
                returncode = 0
                stdout = '{"status":"ok","capacity":999}'

            original_run = mod.subprocess.run
            original_redis = mod.redis_cli
            try:
                mod.subprocess.run = lambda *args, **kwargs: FakeProc()
                mod.redis_cli = lambda *args, **kwargs: type("FakeRedis", (), {"returncode": 0, "stdout": ""})()
                result = mod.gateway_transport_contract(root)
            finally:
                mod.subprocess.run = original_run
                mod.redis_cli = original_redis

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["reason"], "gateway_contract_failed")

    def test_gateway_reconnect_diagnostic_runs_success_probe(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "target" / "debug" / "a9-gateway"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n", encoding="utf-8")

            class FakeProc:
                returncode = 0
                stdout = json.dumps(
                    {
                        "status": "ok",
                        "kind": "gateway_reconnect_decision",
                        "diagnostic": "success",
                        "event_id": "1779900000-0",
                    }
                )

            calls = []
            original_run = mod.subprocess.run
            original_redis = mod.redis_cli
            try:
                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.subprocess.run = fake_run
                mod.redis_cli = lambda *args, **kwargs: type("FakeRedis", (), {"returncode": 0, "stdout": ""})()
                result = mod.gateway_reconnect_diagnostic(root, success=True)
            finally:
                mod.subprocess.run = original_run
                mod.redis_cli = original_redis

        self.assertEqual(calls[0][0], [str(binary), "reconnect-diagnostic", "--success"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["kind"], "gateway_reconnect_diagnostic")
        self.assertEqual(result["event_id"], "1779900000-0")
        self.assertEqual(result["latest_event"]["status"], "missing")

    def test_gateway_reconnect_diagnostic_requires_success_flag(self):
        mod = load_control_api()
        result = mod.gateway_reconnect_diagnostic(success=False)
        self.assertEqual(result["status"], "needs_approval")
        self.assertEqual(result["reason"], "diagnostic_success_flag_required")

    def test_latest_gateway_transport_contract_event_reads_newest_matching_event(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = "\n".join(
                [
                    "1779893553470-0",
                    "type",
                    "gateway_transport_contract",
                    "kind",
                    "gateway_transport_contract",
                    "status",
                    "ok",
                    "capacity",
                    "128",
                    "overload_error_code",
                    "-32001",
                    "request_overload_returns_retry_error",
                    "true",
                    "response_waits_on_backpressure",
                    "true",
                    "writer_full_preserves_existing_message",
                    "true",
                    "ts",
                    "1779893553000",
                ]
            )

        calls = []

        def fake_redis(args, *, timeout=2):
            calls.append(args)
            return FakeProc()

        original_redis = mod.redis_cli
        try:
            mod.redis_cli = fake_redis
            event = mod.latest_gateway_transport_contract_event()
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(calls[0], ["--raw", "XREVRANGE", "a9:events", "+", "-", "COUNT", "50"])
        self.assertEqual(event["status"], "ok")
        self.assertEqual(event["event_id"], "1779893553470-0")
        self.assertEqual(event["capacity"], 128)
        self.assertEqual(event["overload_error_code"], -32001)
        self.assertTrue(event["request_overload_returns_retry_error"])
        self.assertTrue(event["response_waits_on_backpressure"])
        self.assertTrue(event["writer_full_preserves_existing_message"])

    def test_latest_gateway_reconnect_decision_event_reads_reset_state(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = "\n".join(
                [
                    "1779893553471-0",
                    "type",
                    "gateway_reconnect_decision",
                    "kind",
                    "gateway_reconnect_decision",
                    "phase",
                    "connect",
                    "action",
                    "continue",
                    "error_class",
                    "none",
                    "attempt",
                    "1",
                    "delay_ms",
                    "0",
                    "policy_budget_remaining",
                    "2",
                    "origin",
                    "connect_success",
                    "reset_on_success",
                    "true",
                    "ts",
                    "1779893553000",
                ]
            )

        calls = []

        def fake_redis(args, *, timeout=2):
            calls.append(args)
            return FakeProc()

        original_redis = mod.redis_cli
        try:
            mod.redis_cli = fake_redis
            event = mod.latest_gateway_reconnect_decision_event()
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(calls[0], ["--raw", "XREVRANGE", "a9:events", "+", "-", "COUNT", "50"])
        self.assertEqual(event["status"], "ok")
        self.assertEqual(event["kind"], "gateway_reconnect_decision")
        self.assertEqual(event["event_id"], "1779893553471-0")
        self.assertEqual(event["phase"], "connect")
        self.assertEqual(event["action"], "continue")
        self.assertEqual(event["error_class"], "none")
        self.assertEqual(event["attempt"], 1)
        self.assertEqual(event["delay_ms"], 0)
        self.assertEqual(event["policy_budget_remaining"], 2)
        self.assertEqual(event["origin"], "connect_success")
        self.assertTrue(event["reset_on_success"])

    def test_latest_gateway_reconnect_decision_event_preserves_reconnect_state_fields(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = "\n".join(
                [
                    "1779893553472-0",
                    "type",
                    "gateway_reconnect_decision",
                    "kind",
                    "gateway_reconnect_decision",
                    "phase",
                    "stream",
                    "action",
                    "reconnect",
                    "error_class",
                    "timeout",
                    "attempt",
                    "3",
                    "delay_ms",
                    "128",
                    "policy_budget_remaining",
                    "1",
                    "origin",
                    "connect_error",
                    "flow_id",
                    "flow-a9-main",
                    "flow_revision",
                    "7",
                    "node_id",
                    "node-a",
                    "reset_on_success",
                    "false",
                    "ts",
                    "1779893553000",
                ]
            )

        original_redis = mod.redis_cli
        try:
            mod.redis_cli = lambda *args, **kwargs: FakeProc()
            event = mod.latest_gateway_reconnect_decision_event()
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(event["status"], "ok")
        self.assertEqual(event["flow_id"], "flow-a9-main")
        self.assertEqual(event["flow_revision"], 7)
        self.assertEqual(event["node_id"], "node-a")
        self.assertEqual(event["phase"], "stream")
        self.assertEqual(event["action"], "reconnect")
        self.assertEqual(event["error_class"], "timeout")

    def test_gateway_runtime_evidence_decision_requires_fresh_event(self):
        mod = load_control_api()
        local = {"status": "ok"}

        missing = mod.gateway_runtime_evidence_decision(local, {"status": "missing"}, now_ms_value=1_000_000)
        self.assertEqual(missing["status"], "degraded")
        self.assertEqual(missing["action"], "emit_runtime_event")
        self.assertEqual(missing["reason"], "gateway_runtime_event_missing")

        failed = mod.gateway_runtime_evidence_decision(
            local,
            {"status": "fail", "event_id": "1-0", "ts": "900000"},
            now_ms_value=1_000_000,
        )
        self.assertEqual(failed["status"], "fail")
        self.assertEqual(failed["action"], "block")
        self.assertEqual(failed["reason"], "gateway_runtime_event_failed")

        stale = mod.gateway_runtime_evidence_decision(
            local,
            {"status": "ok", "event_id": "2-0", "ts": "600000"},
            stale_seconds=300,
            now_ms_value=1_000_000,
        )
        self.assertEqual(stale["status"], "degraded")
        self.assertEqual(stale["action"], "emit_runtime_event")
        self.assertEqual(stale["reason"], "gateway_runtime_event_stale")
        self.assertEqual(stale["age_seconds"], 400)

        fresh = mod.gateway_runtime_evidence_decision(
            local,
            {"status": "ok", "event_id": "3-0", "ts": "900000"},
            stale_seconds=300,
            now_ms_value=1_000_000,
        )
        self.assertEqual(fresh["status"], "ok")
        self.assertEqual(fresh["action"], "continue")
        self.assertEqual(fresh["reason"], "gateway_runtime_event_fresh")

    def test_gateway_reconnect_evidence_decision_reports_missing_stale_and_fresh(self):
        mod = load_control_api()

        missing = mod.gateway_reconnect_evidence_decision({"status": "missing"}, now_ms_value=1_000_000)
        self.assertEqual(missing["status"], "degraded")
        self.assertEqual(missing["action"], "observe")
        self.assertEqual(missing["reason"], "gateway_reconnect_event_missing")

        stale = mod.gateway_reconnect_evidence_decision(
            {"status": "ok", "event_id": "1-0", "ts": "600000"},
            stale_seconds=300,
            now_ms_value=1_000_000,
        )
        self.assertEqual(stale["status"], "degraded")
        self.assertEqual(stale["action"], "observe")
        self.assertEqual(stale["reason"], "gateway_reconnect_event_stale")
        self.assertEqual(stale["age_seconds"], 400)

        fresh = mod.gateway_reconnect_evidence_decision(
            {"status": "ok", "event_id": "2-0", "ts": "900000"},
            stale_seconds=300,
            now_ms_value=1_000_000,
        )
        self.assertEqual(fresh["status"], "ok")
        self.assertEqual(fresh["action"], "continue")
        self.assertEqual(fresh["reason"], "gateway_reconnect_event_fresh")

    def test_gateway_health_refresh_emits_contract_and_reports_reconnect_gap(self):
        mod = load_control_api()
        calls = []
        original_contract = mod.gateway_transport_contract
        original_reconnect = mod.latest_gateway_reconnect_decision_event
        try:
            mod.gateway_transport_contract = lambda root=mod.ROOT, *, emit_event=False: (
                calls.append(emit_event)
                or {
                    "status": "ok",
                    "kind": "gateway_transport_contract",
                    "runtime_evidence": {"status": "ok", "action": "continue"},
                }
            )
            mod.latest_gateway_reconnect_decision_event = lambda: {
                "status": "missing",
                "kind": "gateway_reconnect_decision",
            }
            result = mod.gateway_health_refresh()
        finally:
            mod.gateway_transport_contract = original_contract
            mod.latest_gateway_reconnect_decision_event = original_reconnect

        self.assertEqual(calls, [True])
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["kind"], "gateway_health_refresh")
        self.assertEqual(result["reconnect"]["runtime_evidence"]["action"], "observe")
        self.assertEqual(result["reconnect"]["runtime_evidence"]["reason"], "gateway_reconnect_event_missing")

    def test_register_and_heartbeat_node_write_controller_registry(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            registered = mod.register_node(
                {
                    "node_id": "node/a",
                    "host": "worker-a",
                    "ssh_target": "root@worker-a",
                    "capabilities": {"python3": "/usr/bin/python3"},
                },
                root=root,
            )
            heartbeat = mod.heartbeat_node({"node_id": "node/a", "status": "online", "message": "ready"}, root=root)
            status = mod.node_status(root)

        self.assertEqual(registered["status"], "registered")
        self.assertEqual(registered["node"]["node_id"], "node-a")
        self.assertEqual(heartbeat["node"]["status"], "online")
        self.assertEqual(heartbeat["node"]["message"], "ready")
        self.assertEqual(status["count"], 1)
        self.assertEqual(status["nodes"][0]["capabilities"]["python3"], "/usr/bin/python3")
        self.assertEqual(status["nodes"][0]["connection_state"], "online")
        self.assertEqual(status["nodes"][0]["connection_action"], "continue")

    def test_register_node_persists_reconnect_governance_fields_for_node_status(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node(
                {
                    "node_id": "node/a",
                    "ssh_target": "root@worker-a",
                    "reconnect_action": "reconnect",
                    "reconnect_reason": "ssh_exec_error",
                    "reconnect_attempt": 3,
                    "reconnect_backoff_seconds": 8,
                    "stream_action": "continue",
                    "stream_reason": "decode_error",
                    "reconnect_lifecycle": {"event": "reconnecting"},
                },
                root=root,
            )
            status = mod.node_status(root)
        node = status["nodes"][0]
        self.assertEqual(node["reconnect_action"], "reconnect")
        self.assertEqual(node["reconnect_reason"], "ssh_exec_error")
        self.assertEqual(node["reconnect_attempt"], 3)
        self.assertEqual(node["reconnect_backoff_seconds"], 8)
        self.assertEqual(node["stream_action"], "continue")
        self.assertEqual(node["stream_reason"], "decode_error")
        self.assertEqual(node["reconnect_lifecycle"]["event"], "reconnecting")

    def test_api_nodes_endpoint_includes_connection_action_fields(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node(
                {
                    "node_id": "node/a",
                    "host": "worker-a",
                    "ssh_target": "root@worker-a",
                    "capabilities": {"python3": "/usr/bin/python3"},
                },
                root=root,
            )
            mod.heartbeat_node({"node_id": "node/a", "status": "online", "message": "ready"}, root=root)

            captured = {"status": None, "payload": None}

            class DummyHandler:
                path = "/api/nodes"
                headers = {}

                def write_json(self, status, payload):
                    captured["status"] = status
                    captured["payload"] = payload

                def write_sse(self, status, payload):
                    raise AssertionError("write_sse should not be used for /api/nodes")

            original_node_status = mod.node_status
            mod.node_status = lambda: original_node_status(root)
            try:
                mod.ControlHandler.do_GET(DummyHandler())
            finally:
                mod.node_status = original_node_status

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["count"], 1)
        node = captured["payload"]["nodes"][0]
        self.assertEqual(node["connection_action"], "continue")
        self.assertEqual(node["connection_action_reason"], "heartbeat_fresh")

    def test_node_connection_summary_aggregates_risk_and_action_buckets(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@worker-a"}, root=root)
            mod.heartbeat_node({"node_id": "node/a", "status": "online"}, root=root)
            mod.register_node({"node_id": "node/b", "ssh_target": "root@worker-b"}, root=root)
            node_b_path = mod.node_path("node/b", root)
            node_b = mod.read_json(node_b_path)
            stale_at = (mod.utc_now_dt() - mod.timedelta(seconds=120)).isoformat(timespec="seconds")
            node_b["updated_at"] = stale_at
            node_b["last_heartbeat_at"] = stale_at
            node_b_path.write_text(json.dumps(node_b, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmux_path = mod.write_node_evidence(
                "tmux-status",
                "node/b",
                {
                    "status": "missing",
                    "tmux_action": "repair",
                    "tmux_action_reason": "tmux_session_missing",
                },
                root=root,
            )

            summary = mod.node_connection_summary(root)

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["connection_states"]["online"], 1)
        self.assertEqual(summary["connection_states"]["stale"], 1)
        self.assertEqual(summary["recovery_actions"]["observe"], 1)
        self.assertEqual(summary["recovery_actions"]["tmux"], 1)
        self.assertEqual(summary["tmux_actions"]["repair"], 1)
        self.assertEqual(summary["connection_actions"].get("unknown"), 2)
        self.assertEqual(summary["risk_count"], 1)
        self.assertEqual(summary["risk_nodes"][0]["node_id"], "node-b")
        self.assertEqual(summary["risk_nodes"][0]["route"]["endpoint"], "/api/nodes/tmux-ensure")
        self.assertIn(str(tmux_path), summary["latest_evidence_paths"])

    def test_node_connection_summary_separates_smoke_noise_from_remote_risk(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node(
                {
                    "node_id": "local-service-smoke",
                    "ssh_target": "root@127.0.0.1",
                    "message": "service-smoke",
                },
                root=root,
            )
            mod.register_node(
                {
                    "node_id": "remote/a",
                    "ssh_target": "root@100.74.166.86:2200",
                    "labels": ["mobile-added"],
                },
                root=root,
            )
            old_at = (mod.utc_now_dt() - mod.timedelta(seconds=600)).isoformat(timespec="seconds")
            for node_id in ["local-service-smoke", "remote/a"]:
                node_path = mod.node_path(node_id, root)
                node = mod.read_json(node_path)
                node["updated_at"] = old_at
                node["last_heartbeat_at"] = old_at
                node_path.write_text(json.dumps(node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            summary = mod.node_connection_summary(root)

        self.assertEqual(summary["hygiene_categories"]["test_smoke"], 1)
        self.assertEqual(summary["hygiene_categories"]["remote_candidate"], 1)
        self.assertEqual(summary["risk_count"], 1)
        self.assertEqual(summary["risk_nodes"][0]["node_id"], "remote-a")
        self.assertEqual(summary["skipped_noise_count"], 1)
        self.assertEqual(summary["skipped_noise_nodes"][0]["node_id"], "local-service-smoke")

    def test_node_connection_summary_dedupes_same_ssh_target_risk(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node(
                {
                    "node_id": "remote/old",
                    "ssh_target": "root@100.74.166.86:2200",
                    "labels": ["mobile-probed"],
                },
                root=root,
            )
            mod.register_node(
                {
                    "node_id": "remote/new",
                    "ssh_target": "root@100.74.166.86:2200",
                    "labels": ["mobile-added"],
                },
                root=root,
            )
            old_at = (mod.utc_now_dt() - mod.timedelta(seconds=900)).isoformat(timespec="seconds")
            new_at = (mod.utc_now_dt() - mod.timedelta(seconds=600)).isoformat(timespec="seconds")
            for node_id, seen_at in [("remote/old", old_at), ("remote/new", new_at)]:
                node_path = mod.node_path(node_id, root)
                node = mod.read_json(node_path)
                node["updated_at"] = seen_at
                node["last_heartbeat_at"] = seen_at
                node_path.write_text(json.dumps(node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            summary = mod.node_connection_summary(root)

        self.assertEqual(summary["risk_count"], 1)
        self.assertEqual(summary["risk_nodes"][0]["node_id"], "remote-new")
        self.assertEqual(summary["duplicate_node_count"], 1)
        self.assertEqual(summary["duplicate_nodes"][0]["node_id"], "remote-old")
        self.assertEqual(summary["duplicate_target_groups"][0]["primary_node_id"], "remote-new")

    def test_node_connection_summary_uses_probe_connection_fields(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@worker-a"}, root=root)
            mod.heartbeat_node({"node_id": "node/a", "status": "online"}, root=root)
            probe_evidence_path = mod.write_node_evidence(
                "probe",
                "node/a",
                {
                    "status": "failed",
                    "return_code": 255,
                    "timed_out": False,
                    "probe_action": "retry",
                    "probe_action_reason": "ssh_exec_error",
                    "checked_at": "2026-05-28T00:00:00Z",
                    "connection_summary": {
                        "connection_state": "disconnected",
                        "action": "reconnect",
                        "action_reason": "ssh_exec_error",
                        "retry_delay_ms": 8000,
                    },
                },
                root=root,
            )

            summary = mod.node_connection_summary(root)

        self.assertEqual(summary["connection_states"]["disconnected"], 1)
        self.assertEqual(summary["connection_actions"]["reconnect"], 1)
        self.assertEqual(summary["risk_count"], 1)
        self.assertEqual(summary["risk_nodes"][0]["connection_state"], "disconnected")
        self.assertEqual(summary["risk_nodes"][0]["action"], "reconnect")
        self.assertEqual(summary["risk_nodes"][0]["retry_delay_ms"], 8000)
        self.assertEqual(summary["risk_nodes"][0]["connection_evidence_path"], str(probe_evidence_path))

    def test_connection_summary_includes_stream_recovery_next_action(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_node_status = mod.node_status
            top_consumers = [
                {"name": "node-a", "pending": 7, "idle": 41000},
                {"name": "node-b", "pending": 2, "idle": 1200},
            ]
            try:
                mod.node_status = lambda root=root: {
                    "count": 1,
                    "nodes": [],
                    "tasks_stream": {
                        "lag": 123,
                        "pending": 9,
                        "stream_action": "intervene",
                        "stream_action_reason": "pending_stuck",
                        "recommended_action": "recover_stale_commands",
                        "top_consumers": top_consumers,
                    },
                    "communication_followup": {"action": "continue", "reason": "healthy"},
                }
                summary = mod.node_connection_summary(root)
            finally:
                mod.node_status = original_node_status

        self.assertEqual(summary["recovery_next_action"]["action"], "repair")
        self.assertEqual(summary["recovery_next_action"]["reason"], "recover_stale_commands")
        self.assertEqual(summary["stream_evidence"]["lag"], 123)
        self.assertEqual(summary["stream_evidence"]["pending_total"], 9)
        self.assertEqual(summary["stream_evidence"]["pending"], 9)
        self.assertEqual(summary["stream_evidence"]["stream_action"], "intervene")
        self.assertEqual(summary["stream_evidence"]["stream_action_reason"], "pending_stuck")
        self.assertEqual(summary["stream_evidence"]["recommended_action"], "recover_stale_commands")
        self.assertEqual(summary["stream_evidence"]["top_consumers"], top_consumers)

    def test_connection_summary_stream_recovery_next_action_observes_watch_tier(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_node_status = mod.node_status
            try:
                mod.node_status = lambda root=root: {
                    "count": 0,
                    "nodes": [],
                    "tasks_stream": {
                        "lag": 72,
                        "pending": 4,
                        "stream_action": "watch",
                        "stream_action_reason": "lag_warn",
                    },
                    "communication_followup": {"action": "continue", "reason": "healthy"},
                }
                summary = mod.node_connection_summary(root)
            finally:
                mod.node_status = original_node_status

        self.assertEqual(summary["recovery_next_action"]["action"], "watch")
        self.assertEqual(summary["recovery_next_action"]["reason"], "lag_warn")
        self.assertEqual(summary["stream_evidence"]["lag"], 72)
        self.assertEqual(summary["stream_evidence"]["pending_total"], 4)
        self.assertEqual(summary["stream_evidence"]["stream_action"], "watch")
        self.assertEqual(summary["stream_evidence"]["stream_action_reason"], "lag_warn")

    def test_api_nodes_connection_summary_endpoint_uses_summary_payload(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}

        class DummyNodesConnectionSummaryHandler:
            path = "/api/nodes/connection-summary"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

            def write_sse(self, status, payload):
                raise AssertionError("write_sse should not be used for /api/nodes/connection-summary")

        original_summary = mod.node_connection_summary
        try:
            mod.node_connection_summary = lambda: {"status": "ok", "count": 0, "risk_count": 0}
            mod.ControlHandler.do_GET(DummyNodesConnectionSummaryHandler())
        finally:
            mod.node_connection_summary = original_summary

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["status"], "ok")
        self.assertEqual(captured["payload"]["risk_count"], 0)

    def test_communication_status_prioritizes_missing_services_over_observe(self):
        mod = load_control_api()
        originals = {
            "tailscale_status": mod.tailscale_status,
            "service_observation_status": mod.service_observation_status,
            "node_connection_summary": mod.node_connection_summary,
            "recovery_loop_latest": mod.recovery_loop_latest,
        }
        try:
            mod.tailscale_status = lambda: {"status": "ok"}
            mod.service_observation_status = lambda root=mod.ROOT: {
                "status": "ok",
                "observed": {
                    "missing_count": 1,
                    "missing_services": ["node-worker"],
                    "next_action": "start_missing_services",
                },
            }
            mod.node_connection_summary = lambda root=mod.ROOT: {
                "status": "ok",
                "risk_count": 0,
                "tasks_stream": {"stream_action": "continue", "stream_action_reason": "none"},
                "communication_followup": {"action": "continue", "reason": "healthy"},
            }
            mod.recovery_loop_latest = lambda *, root=mod.ROOT: {"status": "ok"}

            status = mod.communication_status()
        finally:
            mod.tailscale_status = originals["tailscale_status"]
            mod.service_observation_status = originals["service_observation_status"]
            mod.node_connection_summary = originals["node_connection_summary"]
            mod.recovery_loop_latest = originals["recovery_loop_latest"]

        self.assertEqual(status["status"], "degraded")
        self.assertEqual(status["action"], "start_missing_services")
        self.assertEqual(status["priority_source"], "services")
        self.assertEqual(status["layers"]["services"]["observed"]["missing_services"], ["node-worker"])

    def test_communication_status_prioritizes_recovery_loop_attention(self):
        mod = load_control_api()
        originals = {
            "tailscale_status": mod.tailscale_status,
            "service_observation_status": mod.service_observation_status,
            "node_connection_summary": mod.node_connection_summary,
            "recovery_loop_latest": mod.recovery_loop_latest,
        }
        try:
            mod.tailscale_status = lambda: {"status": "ok"}
            mod.service_observation_status = lambda root=mod.ROOT: {
                "status": "ok",
                "observed": {"missing_count": 0, "missing_services": [], "next_action": "observe"},
            }
            mod.node_connection_summary = lambda root=mod.ROOT: {
                "status": "ok",
                "risk_count": 0,
                "tasks_stream": {"stream_action": "continue", "stream_action_reason": "none"},
                "communication_followup": {"action": "continue", "reason": "healthy"},
            }
            mod.recovery_loop_latest = lambda *, root=mod.ROOT: {"status": "needs_attention", "risk_count": 2}

            status = mod.communication_status()
        finally:
            mod.tailscale_status = originals["tailscale_status"]
            mod.service_observation_status = originals["service_observation_status"]
            mod.node_connection_summary = originals["node_connection_summary"]
            mod.recovery_loop_latest = originals["recovery_loop_latest"]

        self.assertEqual(status["status"], "needs_attention")
        self.assertEqual(status["action"], "intervene")
        self.assertEqual(status["priority_source"], "recovery_loop")

    def test_communication_status_uses_stream_recovery_next_action(self):
        mod = load_control_api()
        originals = {
            "tailscale_status": mod.tailscale_status,
            "service_observation_status": mod.service_observation_status,
            "node_connection_summary": mod.node_connection_summary,
            "recovery_loop_latest": mod.recovery_loop_latest,
        }
        try:
            mod.tailscale_status = lambda: {"status": "ok"}
            mod.service_observation_status = lambda root=mod.ROOT: {
                "status": "ok",
                "observed": {"missing_count": 0, "missing_services": [], "next_action": "observe"},
            }
            mod.node_connection_summary = lambda root=mod.ROOT: {
                "status": "ok",
                "risk_count": 0,
                "tasks_stream": {
                    "stream_action": "intervene",
                    "stream_action_reason": "pending_stuck",
                    "lag": 7,
                    "pending": 4,
                },
                "recovery_next_action": {"action": "repair", "reason": "recover_stale_commands"},
                "communication_followup": {"action": "continue", "reason": "healthy"},
            }
            mod.recovery_loop_latest = lambda *, root=mod.ROOT: {"status": "ok"}

            status = mod.communication_status()
        finally:
            mod.tailscale_status = originals["tailscale_status"]
            mod.service_observation_status = originals["service_observation_status"]
            mod.node_connection_summary = originals["node_connection_summary"]
            mod.recovery_loop_latest = originals["recovery_loop_latest"]

        tasks_stream_candidate = next(item for item in status["candidates"] if item["source"] == "tasks_stream")
        self.assertEqual(status["status"], "needs_attention")
        self.assertEqual(status["action"], "repair")
        self.assertEqual(status["priority_source"], "tasks_stream")
        self.assertEqual(status["reason"], "tasks_stream:recover_stale_commands")
        self.assertEqual(tasks_stream_candidate["action"], "repair")
        self.assertEqual(tasks_stream_candidate["reason"], "recover_stale_commands")
        self.assertEqual(tasks_stream_candidate["lag"], 7)
        self.assertEqual(tasks_stream_candidate["pending"], 4)
        self.assertEqual(tasks_stream_candidate["stream_action"], "intervene")
        self.assertEqual(tasks_stream_candidate["stream_action_reason"], "pending_stuck")

    def test_communication_status_prefers_recovery_loop_attention_over_stream_repair(self):
        mod = load_control_api()
        originals = {
            "tailscale_status": mod.tailscale_status,
            "service_observation_status": mod.service_observation_status,
            "node_connection_summary": mod.node_connection_summary,
            "recovery_loop_latest": mod.recovery_loop_latest,
        }
        try:
            mod.tailscale_status = lambda: {"status": "ok"}
            mod.service_observation_status = lambda root=mod.ROOT: {
                "status": "ok",
                "observed": {"missing_count": 0, "missing_services": [], "next_action": "observe"},
            }
            mod.node_connection_summary = lambda root=mod.ROOT: {
                "status": "ok",
                "risk_count": 0,
                "tasks_stream": {
                    "stream_action": "intervene",
                    "stream_action_reason": "pending_stuck",
                    "lag": 7,
                    "pending": 4,
                },
                "recovery_next_action": {"action": "repair", "reason": "recover_stale_commands"},
                "communication_followup": {"action": "continue", "reason": "healthy"},
            }
            mod.recovery_loop_latest = lambda *, root=mod.ROOT: {
                "status": "needs_attention",
                "risk_count": 2,
            }

            status = mod.communication_status()
        finally:
            mod.tailscale_status = originals["tailscale_status"]
            mod.service_observation_status = originals["service_observation_status"]
            mod.node_connection_summary = originals["node_connection_summary"]
            mod.recovery_loop_latest = originals["recovery_loop_latest"]

        self.assertEqual(status["status"], "needs_attention")
        self.assertEqual(status["action"], "intervene")
        self.assertEqual(status["priority_source"], "recovery_loop")
        self.assertEqual(status["reason"], "recovery_loop:needs_attention")
        tasks_stream_candidate = next(item for item in status["candidates"] if item["source"] == "tasks_stream")
        self.assertEqual(tasks_stream_candidate["action"], "repair")
        self.assertEqual(tasks_stream_candidate["reason"], "recover_stale_commands")

    def test_api_communication_status_endpoint_uses_status_payload(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}

        class DummyCommunicationStatusHandler:
            path = "/api/communication/status"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

            def write_sse(self, status, payload):
                raise AssertionError("write_sse should not be used for /api/communication/status")

        original_status = mod.communication_status
        try:
            mod.communication_status = lambda: {"status": "needs_attention", "action": "intervene"}
            mod.ControlHandler.do_GET(DummyCommunicationStatusHandler())
        finally:
            mod.communication_status = original_status

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["status"], "needs_attention")
        self.assertEqual(captured["payload"]["action"], "intervene")

    def test_communication_data_contract_report_lists_all_objects(self):
        mod = load_control_api()
        report = mod.communication_data_contract_report(root=mod.ROOT)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["kind"], "communication_data_contract_report")
        self.assertEqual(len(report["objects"]), len(mod.COMMUNICATION_DATA_CONTRACT_OBJECTS))
        self.assertEqual(report["contract_version"], mod.COMMUNICATION_DATA_CONTRACT_VERSION)
        for item in report["objects"]:
            self.assertIn("object", item)
            self.assertIn("status", item)
            self.assertIn("current_surface", item)
            self.assertIn("missing_fields_or_gap", item)
            self.assertIn("evidence", item)
            self.assertIn(item["status"], {"missing", "partial", "implemented"})

    def test_communication_data_contract_report_filters_known_object(self):
        mod = load_control_api()
        report = mod.communication_data_contract_report(object_name="node", root=mod.ROOT)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(report["objects"]), 1)
        self.assertEqual(report["objects"][0]["object"], "node")
        self.assertEqual(report["objects"][0]["status"], "partial")

    def test_communication_data_contract_report_includes_model_closure_for_closed_objects(self):
        mod = load_control_api()
        report = mod.communication_data_contract_report(root=mod.ROOT)

        model_closed = {"operator_session", "event_cursor", "reconnect_state"}
        for name in model_closed:
            item = next(item for item in report["objects"] if item["object"] == name)
            self.assertIn("model_closure", item)
            model_closure = item["model_closure"]
            self.assertIsInstance(model_closure, dict)
            self.assertIn("mysql_authority", model_closure)
            self.assertIn("redis_keys", model_closure)
            self.assertIn("owner", model_closure)
            self.assertIn("invariants", model_closure)
            self.assertIn("evidence", model_closure)
            self.assertTrue(isinstance(model_closure["redis_keys"], list))
            self.assertTrue(model_closure["redis_keys"])
            self.assertTrue(
                "status_enum" in model_closure
                or "phase_enum" in model_closure
                or "action_enum" in model_closure
            )

    def test_communication_data_contract_report_model_closure_matches_canonical_doc(self):
        mod = load_control_api()
        report = mod.communication_data_contract_report(root=mod.ROOT)
        by_object = {item["object"]: item for item in report["objects"]}

        operator_session = by_object["operator_session"]["model_closure"]
        self.assertEqual(operator_session["mysql_authority"], "a9_operator_sessions")
        self.assertEqual(
            operator_session["redis_keys"],
            ["a9:operator_events", "a9:operator:{operator_id}:{client_id}"],
        )
        self.assertEqual(
            operator_session["status_enum"],
            ["active", "idle", "stale", "revoked", "disconnected"],
        )

        event_cursor = by_object["event_cursor"]["model_closure"]
        self.assertEqual(event_cursor["mysql_authority"], "a9_event_cursors")
        self.assertEqual(event_cursor["redis_keys"], ["a9:events", "a9:tasks"])
        self.assertEqual(
            event_cursor["status_enum"],
            ["active", "gap_detected", "invalid", "stale", "reset_pending"],
        )

        reconnect_state = by_object["reconnect_state"]["model_closure"]
        self.assertEqual(reconnect_state["mysql_authority"], "a9_reconnect_states")
        self.assertEqual(
            reconnect_state["redis_keys"],
            ["a9:reconnect_events", "a9:reconnect:{node_id}", "a9:events"],
        )
        self.assertEqual(reconnect_state["phase_enum"], ["connect", "stream", "ssh", "tmux", "redis"])
        self.assertEqual(
            reconnect_state["action_enum"],
            ["continue", "reconnect", "terminate", "quarantine", "watch"],
        )

    def test_communication_data_contract_report_unknown_object_returns_missing(self):
        mod = load_control_api()
        report = mod.communication_data_contract_report(object_name="not-an-object", root=mod.ROOT)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(report["objects"]), 1)
        item = report["objects"][0]
        self.assertEqual(item["object"], "not-an-object")
        self.assertEqual(item["status"], "missing")

    def test_communication_data_contract_report_endpoint(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}

        class DummyCommunicationDataContractHandler:
            path = "/api/communication/data-contract-report"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        mod.ControlHandler.do_GET(DummyCommunicationDataContractHandler())
        payload = captured["payload"] or {}

        self.assertEqual(captured["status"], 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["kind"], "communication_data_contract_report")
        self.assertEqual(payload["contract_version"], mod.COMMUNICATION_DATA_CONTRACT_VERSION)
        self.assertIn("objects", payload)
        self.assertIsInstance(payload["objects"], list)
        self.assertGreater(len(payload["objects"]), 0)
        first = payload["objects"][0]
        for key in (
            "object",
            "status",
            "mysql_target",
            "redis_target",
            "required_fields",
            "evidence",
            "current_mapping",
            "current_surface",
        ):
            self.assertIn(key, first)

    def test_api_communication_data_contract_report_endpoint_uses_report_payload(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}

        class DummyCommunicationDataContractHandler:
            path = "/api/communication/data-contract-report?object=command"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        original_report = mod.communication_data_contract_report
        try:
            mod.communication_data_contract_report = lambda *, object_name=None, root=mod.ROOT: {
                "status": "ok",
                "kind": "communication_data_contract_report",
                "objects": [{"object": object_name, "status": "partial"}],
            }
            mod.ControlHandler.do_GET(DummyCommunicationDataContractHandler())
        finally:
            mod.communication_data_contract_report = original_report

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "communication_data_contract_report")
        self.assertEqual(captured["payload"]["objects"][0]["object"], "command")

    def test_communication_model_closure_validate_valid_operator_session(self):
        mod = load_control_api()
        payload = {
            "operator_id": "op-1",
            "client_kind": "cli",
            "client_id": "client-1",
            "auth_scope": ["operator.admin"],
            "connected_at": "2026-06-03T00:00:00Z",
            "last_seen_at": "2026-06-03T00:00:10Z",
            "last_event_id": "1-0",
            "control_permissions": ["services.start"],
            "status": "active",
        }

        result = mod.communication_model_closure_validate("operator_session", payload)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["kind"], "communication_model_closure_validate")
        self.assertEqual(result["object"], "operator_session")
        self.assertEqual(
            list(result["serialized"].keys()),
            mod.COMMUNICATION_DATA_CONTRACT_FIELDS["operator_session"],
        )
        self.assertEqual(result["serialized"]["status"], "active")
        self.assertEqual(result["missing_fields"], [])
        self.assertEqual(result["enum_violations"], [])

    def test_communication_model_closure_validate_missing_fields(self):
        mod = load_control_api()
        result = mod.communication_model_closure_validate(
            "operator_session",
            {
                "operator_id": "op-1",
                "client_kind": "cli",
                "client_id": "client-1",
                "status": "active",
            },
        )

        self.assertEqual(result["status"], "invalid_model")
        self.assertIn("auth_scope", result["missing_fields"])
        self.assertIn("connected_at", result["missing_fields"])
        self.assertIn("last_seen_at", result["missing_fields"])
        self.assertEqual(result["enum_violations"], [])

    def test_communication_model_closure_validate_invalid_enum(self):
        mod = load_control_api()
        payload = {
            "stream": "a9:events",
            "consumer": "operator:client-1",
            "last_id": "1-0",
            "oldest_id": "1-0",
            "newest_id": "2-0",
            "cursor_status": "broken",
            "updated_at": "2026-06-03T00:00:00Z",
        }

        result = mod.communication_model_closure_validate("event_cursor", payload)

        self.assertEqual(result["status"], "invalid_model")
        self.assertEqual(
            result["enum_violations"],
            [
                {
                    "field": "cursor_status",
                    "value": "broken",
                    "allowed": ["active", "gap_detected", "invalid", "stale", "reset_pending"],
                }
            ],
        )

    def test_communication_model_closure_validate_unsupported_object(self):
        mod = load_control_api()

        result = mod.communication_model_closure_validate("node", {"node_id": "n1"})

        self.assertEqual(result["status"], "unsupported_object")
        self.assertEqual(result["error_code"], "unsupported_object")
        self.assertEqual(result["object"], "node")
        self.assertEqual(result["serialized"], {})

    def test_communication_model_closure_validate_non_dict_payload(self):
        mod = load_control_api()

        result = mod.communication_model_closure_validate("operator_session", [])

        self.assertEqual(result["status"], "invalid_payload")
        self.assertEqual(result["error_code"], "invalid_payload")
        self.assertEqual(result["object"], "operator_session")
        self.assertEqual(result["serialized"], {})

    def test_communication_action_plan_routes_missing_services_to_runtime_gate(self):
        mod = load_control_api()
        plan = mod.communication_action_plan(
            {
                "status": "degraded",
                "action": "start_missing_services",
                "reason": "services:missing:1",
                "priority_source": "services",
                "layers": {
                    "services": {
                        "observed": {
                            "missing_count": 1,
                            "missing_services": ["node-worker"],
                            "next_action": "start_missing_services",
                        }
                    }
                },
            }
        )

        self.assertEqual(plan["plan_status"], "ready")
        self.assertEqual(plan["route"]["endpoint"], "/api/services/start")
        self.assertEqual(plan["route"]["command"], "services.start")
        self.assertEqual(plan["route"]["arm_group"], "runtime")
        self.assertEqual(plan["payload"]["services"], ["node-worker"])

    def test_communication_action_plan_routes_node_intervention_to_recovery_cycle(self):
        mod = load_control_api()
        plan = mod.communication_action_plan(
            {
                "status": "needs_attention",
                "action": "intervene",
                "reason": "recovery_loop:needs_attention",
                "priority_source": "recovery_loop",
            }
        )

        self.assertEqual(plan["plan_status"], "ready")
        self.assertEqual(plan["route"]["endpoint"], "/api/nodes/recovery-cycle")
        self.assertEqual(plan["route"]["command"], "nodes.recovery.cycle")
        self.assertEqual(plan["route"]["arm_group"], "remote")
        self.assertTrue(plan["payload"]["execute"])

    def test_communication_action_plan_routes_stream_repair_to_recover_stale_commands(self):
        mod = load_control_api()
        plan = mod.communication_action_plan(
            {
                "status": "needs_attention",
                "action": "repair",
                "reason": "tasks_stream:recover_stale_commands",
                "priority_source": "tasks_stream",
                "layers": {"tasks_stream": {"stream_action": "intervene", "stream_action_reason": "pending_stuck"}},
            }
        )

        self.assertEqual(plan["plan_status"], "ready")
        self.assertEqual(plan["route"]["endpoint"], "/api/communication/repair-one")
        self.assertEqual(plan["route"]["command"], "nodes.recover.stale_commands")
        self.assertEqual(plan["route"]["arm_group"], "remote")
        self.assertEqual(plan["payload"]["action"], "recover_stale_commands")

    def test_communication_repair_one_executes_stream_recovery_chain(self):
        mod = load_control_api()
        original_tailscale_status = mod.tailscale_status
        original_service_observation_status = mod.service_observation_status
        original_node_connection_summary = mod.node_connection_summary
        original_recovery_loop_latest = mod.recovery_loop_latest
        original_command_gate = mod.command_gate
        original_a9_node = mod.a9_node
        original_redis_tasks_stream_probe = mod.redis_tasks_stream_probe

        connection_summary_calls = []
        node_command_calls = []
        command_gate_calls = []
        probe_calls = []

        probe_samples = [
            {"status": "ok", "pending": 5, "stream": "a9:tasks", "group": "a9-worker", "stream_action_reason": "pending_stuck"},
            {"status": "ok", "pending": 3, "stream": "a9:tasks", "group": "a9-worker", "stream_action_reason": "none"},
        ]

        def fake_tailscale_status():
            return {"status": "ok"}

        def fake_service_observation_status(root=mod.ROOT):
            return {
                "status": "ok",
                "observed": {"missing_count": 0, "missing_services": [], "next_action": "observe"},
            }

        def fake_node_connection_summary(root=mod.ROOT):
            if len(connection_summary_calls) == 0:
                connection_summary_calls.append("pending")
                return {
                    "status": "ok",
                    "risk_count": 0,
                    "tasks_stream": {"stream_action": "intervene", "stream_action_reason": "pending_stuck", "lag": 7, "pending": 4},
                    "recovery_next_action": {"action": "repair", "reason": "recover_stale_commands"},
                    "communication_followup": {"action": "continue", "reason": "healthy"},
                }
            connection_summary_calls.append("healthy")
            return {
                "status": "ok",
                "risk_count": 0,
                "tasks_stream": {"stream_action": "continue", "stream_action_reason": "none", "lag": 0, "pending": 0},
                "recovery_next_action": {"action": "continue", "reason": "none"},
                "communication_followup": {"action": "continue", "reason": "healthy"},
            }

        def fake_recovery_loop_latest(*, root=mod.ROOT):
            return {"status": "ok"}

        def fake_node_command_claim_stale_once(node_id, count, min_idle_ms, group, stream, timeout):
            node_command_calls.append(
                {
                    "node_id": node_id,
                    "count": count,
                    "min_idle_ms": min_idle_ms,
                    "group": group,
                    "stream": stream,
                    "timeout": timeout,
                }
            )
            return {
                "status": "ok",
                "error_code": "ok",
                "action": "claim_stale_once",
                "node_id": node_id,
                "stream": stream,
                "group": group,
                "consumer": "node-a-consumer",
                "events": [
                    {"id": "1740000200-0", "fields": {"command_id": "cmd-1"}},
                    {"id": "1740000200-1", "fields": {"command_id": "cmd-2"}},
                ],
                "command_count": 2,
                "next_start_id": "0-0",
                "deleted_ids": [],
                "raw_output": {},
            }

        def fake_redis_tasks_stream_probe():
            sample = probe_samples[min(len(probe_calls), len(probe_samples) - 1)]
            probe_calls.append(sample["pending"])
            return sample

        def fake_command_gate(command, *, root=None):
            command_gate_calls.append(command)
            return {
                "status": "allowed",
                "allowed": True,
                "command": command,
                "reason": "test_gate",
            }

        class FakeNode:
            def node_command_claim_stale_once(self, node_id, count, min_idle_ms, group, stream, timeout):
                return fake_node_command_claim_stale_once(
                    node_id=node_id,
                    count=count,
                    min_idle_ms=min_idle_ms,
                    group=group,
                    stream=stream,
                    timeout=timeout,
                )

        try:
            mod.tailscale_status = fake_tailscale_status
            mod.service_observation_status = fake_service_observation_status
            mod.node_connection_summary = fake_node_connection_summary
            mod.recovery_loop_latest = fake_recovery_loop_latest
            mod.command_gate = fake_command_gate
            mod.a9_node = lambda: FakeNode()
            mod.redis_tasks_stream_probe = fake_redis_tasks_stream_probe
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                result = mod.communication_repair_one(
                    {
                        "action": "recover_stale_commands",
                        "node_id": "node/a",
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )

                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["plan"]["route"]["endpoint"], "/api/communication/repair-one")
                self.assertEqual(result["plan"]["route"]["command"], "nodes.recover.stale_commands")
                self.assertEqual(result["result"]["kind"], "recover_stale_commands")
                self.assertEqual(result["result"]["recovered_count"], 2)
                self.assertEqual(result["result"]["claimed_ids"], ["1740000200-0", "1740000200-1"])
                self.assertEqual(result["communication_after"]["status"], "ok")
                self.assertEqual(len(connection_summary_calls), 2)
                evidence_path = result["result"]["evidence_path"]
                self.assertTrue(evidence_path)
                self.assertTrue(Path(evidence_path).exists())
        finally:
            mod.tailscale_status = original_tailscale_status
            mod.service_observation_status = original_service_observation_status
            mod.node_connection_summary = original_node_connection_summary
            mod.recovery_loop_latest = original_recovery_loop_latest
            mod.command_gate = original_command_gate
            mod.a9_node = original_a9_node
            mod.redis_tasks_stream_probe = original_redis_tasks_stream_probe

        self.assertEqual(len(node_command_calls), 1)
        self.assertEqual(node_command_calls[0]["node_id"], "node-a")
        self.assertEqual(node_command_calls[0]["count"], 1)
        self.assertEqual(node_command_calls[0]["stream"], "a9:tasks")
        self.assertEqual(node_command_calls[0]["group"], "a9-worker")
        self.assertEqual(probe_calls, [5, 3])
        self.assertEqual(command_gate_calls, ["nodes.recover.stale_commands"])

    def test_communication_repair_one_dispatches_missing_service_start(self):
        mod = load_control_api()
        originals = {
            "communication_status": mod.communication_status,
            "service_start_action": mod.service_start_action,
        }
        captured = {}
        try:
            mod.communication_status = lambda root=mod.ROOT: {
                "status": "degraded",
                "action": "start_missing_services",
                "reason": "services:missing:1",
                "priority_source": "services",
                "layers": {"services": {"observed": {"missing_services": ["node-worker"]}}},
            }

            def fake_service_start_action(payload, *, root=mod.ROOT):
                captured["payload"] = payload
                return {"status": "ok", "command": "services.start"}

            mod.service_start_action = fake_service_start_action
            result = mod.communication_repair_one({"operator_scopes": ["operator.admin"]})
        finally:
            mod.communication_status = originals["communication_status"]
            mod.service_start_action = originals["service_start_action"]

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["plan"]["route"]["endpoint"], "/api/services/start")
        self.assertEqual(captured["payload"]["services"], ["node-worker"])
        self.assertEqual(captured["payload"]["operator_scopes"], ["operator.admin"])

    def test_recover_stale_commands_action_claims_pending_commands(self):
        mod = load_control_api()
        probe_samples = [
            {"status": "ok", "pending": 5, "stream": "a9:tasks", "group": "a9-worker", "stream_action_reason": "pending_stuck"},
            {"status": "ok", "pending": 3, "stream": "a9:tasks", "group": "a9-worker", "stream_action_reason": "none"},
        ]
        captured = {
            "node_calls": 0,
            "claim_call": {},
            "probe_calls": 0,
        }
        originals = {
            "a9_node": mod.a9_node,
            "redis_tasks_stream_probe": mod.redis_tasks_stream_probe,
        }

        class FakeNode:
            def node_command_claim_stale_once(self, node_id, count, min_idle_ms, group, stream, timeout):
                captured["node_calls"] += 1
                captured["claim_call"] = {
                    "node_id": node_id,
                    "count": count,
                    "min_idle_ms": min_idle_ms,
                    "group": group,
                    "stream": stream,
                    "timeout": timeout,
                }
                return {
                    "status": "ok",
                    "error_code": "ok",
                    "action": "claim_stale_once",
                    "node_id": node_id,
                    "stream": stream,
                    "group": group,
                    "consumer": "node-a-consumer",
                    "events": [
                        {"id": "1740000200-0", "fields": {"command_id": "cmd-1"}},
                        {"id": "1740000200-1", "fields": {"command_id": "cmd-2"}},
                    ],
                    "command_count": 2,
                    "next_start_id": "0-0",
                    "deleted_ids": [],
                    "raw_output": {},
                }

        def fake_probe():
            sample = probe_samples[min(captured["probe_calls"], len(probe_samples) - 1)]
            captured["probe_calls"] += 1
            return sample

        fake_node = FakeNode()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                mod.a9_node = lambda: fake_node
                mod.redis_tasks_stream_probe = fake_probe
                mod.phone_control_arm(
                    {"group": "remote", "duration": "5m", "operator_scopes": ["operator.admin"]},
                    root=root,
                )
                result = mod.recover_stale_commands(
                    {
                        "node_id": "node-a",
                        "max_claim": 2,
                        "min_idle_ms": 45000,
                        "group": "a9-worker",
                        "stream": "a9:tasks",
                        "timeout": 5,
                    },
                    root=root,
                )
                evidence_path = str(result["evidence_path"])
                self.assertFalse(evidence_path == "")
                self.assertTrue(Path(evidence_path).exists())
            finally:
                mod.a9_node = originals["a9_node"]
                mod.redis_tasks_stream_probe = originals["redis_tasks_stream_probe"]

        self.assertEqual(result["kind"], "recover_stale_commands")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["recovered_count"], 2)
        self.assertEqual(result["claimed_ids"], ["1740000200-0", "1740000200-1"])
        self.assertEqual(result["before"]["pending"], 5)
        self.assertEqual(result["after"]["pending"], 3)
        self.assertEqual(result["stream"], "a9:tasks")
        self.assertEqual(result["group"], "a9-worker")
        self.assertEqual(captured["node_calls"], 1)
        self.assertEqual(captured["claim_call"]["count"], 2)
        self.assertEqual(captured["claim_call"]["min_idle_ms"], 45000)
        self.assertEqual(captured["claim_call"]["timeout"], 5)
        self.assertEqual(captured["probe_calls"], 2)

    def test_api_communication_repair_one_endpoint_uses_payload(self):
        mod = load_control_api()
        captured = {}
        original_repair = mod.communication_repair_one
        try:
            def fake_repair(payload):
                captured["payload"] = payload
                return {"status": "ok", "kind": "communication_repair_one"}

            mod.communication_repair_one = fake_repair
            body = json.dumps({"operator_scopes": ["operator.admin"]}).encode("utf-8")

            class DummyCommunicationRepairPostHandler:
                path = "/api/communication/repair-one"
                headers = {"Content-Length": str(len(body))}
                rfile = io.BytesIO(body)

                def write_json(self, status, payload):
                    captured["status"] = status
                    captured["response"] = payload

            mod.ControlHandler.do_POST(DummyCommunicationRepairPostHandler())
        finally:
            mod.communication_repair_one = original_repair

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["response"]["kind"], "communication_repair_one")
        self.assertEqual(captured["payload"]["operator_scopes"], ["operator.admin"])

    def test_api_communication_model_closure_validate_endpoint_valid_payload(self):
        mod = load_control_api()
        captured = {}
        original_validate = mod.communication_model_closure_validate

        def fake_validate(object_name, payload):
            captured["object_name"] = object_name
            captured["payload"] = payload
            return {"status": "ok", "kind": "communication_model_closure_validate"}

        mod.communication_model_closure_validate = fake_validate
        body = json.dumps(
            {
                "object_name": "operator_session",
                "payload": {"operator_id": "op-1"},
            }
        ).encode("utf-8")

        class DummyCommunicationModelClosureValidatePostHandler:
            path = "/api/communication/model-closure-validate"
            headers = {"Content-Length": str(len(body))}
            rfile = io.BytesIO(body)

            def write_json(self, status, payload):
                captured["status"] = status
                captured["response"] = payload

        try:
            mod.ControlHandler.do_POST(DummyCommunicationModelClosureValidatePostHandler())
        finally:
            mod.communication_model_closure_validate = original_validate

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["response"]["kind"], "communication_model_closure_validate")
        self.assertEqual(captured["object_name"], "operator_session")
        self.assertEqual(captured["payload"], {"operator_id": "op-1"})

    def test_api_communication_model_closure_validate_endpoint_missing_payload(self):
        mod = load_control_api()
        captured = {}
        body = json.dumps({"object": "operator_session"}).encode("utf-8")

        class DummyCommunicationModelClosureValidateMissingPayloadPostHandler:
            path = "/api/communication/model-closure-validate"
            headers = {"Content-Length": str(len(body))}
            rfile = io.BytesIO(body)

            def write_json(self, status, payload):
                captured["status"] = status
                captured["response"] = payload

        mod.ControlHandler.do_POST(DummyCommunicationModelClosureValidateMissingPayloadPostHandler())

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["response"]["status"], "invalid_payload")
        self.assertEqual(captured["response"]["object"], "operator_session")

    def test_live_api_communication_model_closure_validate_endpoint_round_trip(self):
        mod = load_control_api()
        server = mod.ThreadingHTTPServer(("127.0.0.1", 0), mod.ControlHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        body = json.dumps(
            {
                "object_name": "operator_session",
                "payload": {
                    "operator_id": "op-1",
                    "client_kind": "cli",
                    "client_id": "client-1",
                    "auth_scope": ["operator.admin"],
                    "connected_at": "2026-06-03T00:00:00Z",
                    "last_seen_at": "2026-06-03T00:00:10Z",
                    "last_event_id": "1-0",
                    "control_permissions": ["services.start"],
                    "status": "active",
                },
            }
        ).encode("utf-8")
        try:
            thread.start()
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                conn.request(
                    "POST",
                    "/api/communication/model-closure-validate",
                    body=body,
                    headers={"Content-Type": "application/json"},
                )
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["kind"], "communication_model_closure_validate")
        self.assertEqual(payload["object"], "operator_session")
        self.assertEqual(payload["serialized"]["status"], "active")

    def test_node_recovery_cycle_plans_tmux_repair_and_writes_evidence(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@worker-a"}, root=root)
            heartbeat = mod.heartbeat_node({"node_id": "node/a", "status": "online"}, root=root)
            node_path = mod.node_path("node/a", root)
            node = mod.read_json(node_path)
            stale_at = (mod.utc_now_dt() - mod.timedelta(seconds=120)).isoformat(timespec="seconds")
            node["updated_at"] = stale_at
            node["last_heartbeat_at"] = stale_at
            node_path.write_text(json.dumps(node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(heartbeat["status"], "ok")
            mod.write_node_evidence(
                "tmux-status",
                "node/a",
                {
                    "status": "missing",
                    "target": "root@worker-a",
                    "session": "a9",
                    "tmux_action": "repair",
                    "tmux_action_reason": "tmux_session_missing",
                },
                root=root,
            )

            result = mod.node_recovery_cycle({"max_actions": 1}, root=root)
            prepared_path_exists = Path(result["steps"][0]["prepared_plan"]["evidence_path"]).exists()
            cycle_path_exists = Path(result["evidence_path"]).exists()

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["execute"])
        self.assertEqual(result["step_count"], 1)
        step = result["steps"][0]
        self.assertEqual(step["node_id"], "node-a")
        self.assertEqual(step["recovery_action"], "tmux")
        self.assertEqual(step["status"], "planned")
        self.assertEqual(step["result"]["endpoint"], "/api/nodes/tmux-ensure")
        self.assertIn("prepared_plan", step)
        self.assertTrue(prepared_path_exists)
        self.assertTrue(cycle_path_exists)

    def test_node_recovery_cycle_execute_probe_is_blocked_when_phone_disarmed(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@worker-a"}, root=root)
            node_path = mod.node_path("node/a", root)
            node = mod.read_json(node_path)
            stale_at = (mod.utc_now_dt() - mod.timedelta(seconds=120)).isoformat(timespec="seconds")
            node["updated_at"] = stale_at
            node["last_heartbeat_at"] = stale_at
            node_path.write_text(json.dumps(node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            mod.write_node_evidence(
                "probe",
                "node/a",
                {
                    "status": "failed",
                    "return_code": 255,
                    "timed_out": False,
                    "probe_action": "retry",
                    "probe_action_reason": "ssh_exec_error",
                    "checked_at": "2026-05-30T00:00:00Z",
                    "connection_summary": {
                        "connection_state": "disconnected",
                        "action": "reconnect",
                        "action_reason": "ssh_exec_error",
                        "retry_delay_ms": 1000,
                    },
                },
                root=root,
            )
            original_gate = mod.command_gate
            try:
                def fake_gate(command, *, root=mod.ROOT):
                    if command == "nodes.recovery.cycle":
                        return {"status": "allowed", "allowed": True, "command": command, "reason": "test_recovery_gate_allowed"}
                    return {"status": "blocked", "allowed": False, "command": command, "reason": "phone_control_disarmed"}

                mod.command_gate = fake_gate
                result = mod.node_recovery_cycle(
                    {"execute": True, "max_actions": 1, "operator_scopes": ["operator.admin"]},
                    root=root,
                )
                cycle_path_exists = Path(result["evidence_path"]).exists()
            finally:
                mod.command_gate = original_gate

        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["execute"])
        self.assertEqual(result["steps"][0]["recovery_action"], "probe")
        self.assertEqual(result["steps"][0]["status"], "blocked")
        self.assertEqual(result["steps"][0]["result"]["gate"]["reason"], "phone_control_disarmed")
        self.assertTrue(cycle_path_exists)

    def test_node_recovery_cycle_execute_requires_recovery_cycle_gate_before_subactions(self):
        mod = load_control_api()
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@worker-a"}, root=root)
            node_path = mod.node_path("node/a", root)
            node = mod.read_json(node_path)
            stale_at = (mod.utc_now_dt() - mod.timedelta(seconds=120)).isoformat(timespec="seconds")
            node["updated_at"] = stale_at
            node["last_heartbeat_at"] = stale_at
            node_path.write_text(json.dumps(node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            mod.write_node_evidence(
                "probe",
                "node/a",
                {
                    "status": "failed",
                    "return_code": 255,
                    "timed_out": False,
                    "probe_action": "retry",
                    "probe_action_reason": "ssh_exec_error",
                    "checked_at": "2026-05-30T00:00:00Z",
                    "connection_summary": {
                        "connection_state": "disconnected",
                        "action": "reconnect",
                        "action_reason": "ssh_exec_error",
                        "retry_delay_ms": 1000,
                    },
                },
                root=root,
            )
            original_probe = mod.probe_node
            mod.probe_node = lambda payload, *, root=mod.ROOT: calls.append(payload) or {"status": "ok"}
            try:
                result = mod.node_recovery_cycle({"execute": True, "max_actions": 1}, root=root)
                cycle_path_exists = Path(result["evidence_path"]).exists()
            finally:
                mod.probe_node = original_probe

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["step_count"], 0)
        self.assertEqual(result["gate"]["command"], "nodes.recovery.cycle")
        self.assertEqual(result["gate"]["reason"], "phone_control_disarmed")
        self.assertEqual(calls, [])
        self.assertTrue(cycle_path_exists)

    def test_node_recovery_cycle_execute_probe_when_remote_armed(self):
        mod = load_control_api()
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node(
                {
                    "node_id": "remote/a",
                    "ssh_target": "root@100.74.166.86:2200",
                    "labels": ["mobile-added"],
                },
                root=root,
            )
            node_path = mod.node_path("remote/a", root)
            node = mod.read_json(node_path)
            offline_at = (mod.utc_now_dt() - mod.timedelta(seconds=600)).isoformat(timespec="seconds")
            node["updated_at"] = offline_at
            node["last_heartbeat_at"] = offline_at
            node_path.write_text(json.dumps(node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            mod.phone_control_arm(
                {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                root=root,
            )
            original_probe = mod.probe_node
            try:
                def fake_probe(payload, *, root=mod.ROOT):
                    calls.append(payload)
                    return {"status": "ok", "probe_action": "continue", "evidence_path": "/tmp/probe.json"}

                mod.probe_node = fake_probe
                result = mod.node_recovery_cycle(
                    {"execute": True, "max_actions": 1, "operator_scopes": ["operator.admin"]},
                    root=root,
                )
            finally:
                mod.probe_node = original_probe

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["execute"])
        self.assertEqual(result["step_count"], 1)
        self.assertEqual(result["steps"][0]["recovery_action"], "probe")
        self.assertEqual(result["steps"][0]["status"], "executed")
        self.assertEqual(result["steps"][0]["result"]["audit_receipt"]["command"], "nodes.probe.execute")
        self.assertEqual(calls[0]["node_id"], "remote-a")
        self.assertEqual(calls[0]["ssh_target"], "root@100.74.166.86:2200")

    def test_node_recovery_cycle_plans_heartbeat_tmux_status_for_stale_remote_heartbeat(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node(
                {
                    "node_id": "remote/a",
                    "ssh_target": "root@100.74.166.86:2200",
                    "labels": ["mobile-added"],
                },
                root=root,
            )
            node_path = mod.node_path("remote/a", root)
            node = mod.read_json(node_path)
            stale_at = (mod.utc_now_dt() - mod.timedelta(seconds=120)).isoformat(timespec="seconds")
            node["updated_at"] = stale_at
            node["last_heartbeat_at"] = stale_at
            node_path.write_text(json.dumps(node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            mod.write_node_evidence(
                "probe",
                "remote/a",
                {
                    "status": "ok",
                    "probe_action": "continue",
                    "probe_action_reason": "probe_ok",
                    "checked_at": stale_at,
                },
                root=root,
            )
            start_at = (mod.utc_now_dt() - mod.timedelta(seconds=90)).isoformat(timespec="seconds")
            missing_at = (mod.utc_now_dt() - mod.timedelta(seconds=60)).isoformat(timespec="seconds")
            mod.write_node_evidence(
                "heartbeat-tmux-start",
                "remote/a",
                {
                    "status": "ok",
                    "heartbeat_action": "continue",
                    "heartbeat_action_reason": "heartbeat_tmux_start_ok",
                    "executed_at": start_at,
                },
                root=root,
            )

            result = mod.node_recovery_cycle({"max_actions": 1}, root=root)

        step = result["steps"][0]
        self.assertEqual(step["recovery_action"], "tmux")
        self.assertEqual(step["route"]["endpoint"], "/api/nodes/tmux-status")
        self.assertEqual(step["prepared_plan"]["session"], "a9-heartbeat")
        self.assertIn("heartbeat-tmux-plan-", step["prepared_plan"]["evidence_path"])
        self.assertEqual(step["result"]["endpoint"], "/api/nodes/tmux-status")

    def test_node_recovery_cycle_plans_heartbeat_repair_after_heartbeat_tmux_missing(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node(
                {
                    "node_id": "remote/a",
                    "ssh_target": "root@100.74.166.86:2200",
                    "labels": ["mobile-added"],
                },
                root=root,
            )
            node_path = mod.node_path("remote/a", root)
            node = mod.read_json(node_path)
            stale_at = (mod.utc_now_dt() - mod.timedelta(seconds=120)).isoformat(timespec="seconds")
            node["updated_at"] = stale_at
            node["last_heartbeat_at"] = stale_at
            node_path.write_text(json.dumps(node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            mod.write_node_evidence(
                "probe",
                "remote/a",
                {
                    "status": "ok",
                    "probe_action": "continue",
                    "probe_action_reason": "probe_ok",
                    "checked_at": stale_at,
                },
                root=root,
            )
            start_at = (mod.utc_now_dt() - mod.timedelta(seconds=90)).isoformat(timespec="seconds")
            missing_at = (mod.utc_now_dt() - mod.timedelta(seconds=60)).isoformat(timespec="seconds")
            mod.write_node_evidence(
                "heartbeat-tmux-start",
                "remote/a",
                {
                    "status": "ok",
                    "heartbeat_action": "continue",
                    "heartbeat_action_reason": "heartbeat_tmux_start_ok",
                    "executed_at": start_at,
                },
                root=root,
            )
            mod.write_node_evidence(
                "tmux-status",
                "remote/a",
                {
                    "status": "missing",
                    "session": "a9-heartbeat",
                    "tmux_action": "repair",
                    "tmux_action_reason": "tmux_session_missing",
                    "checked_at": missing_at,
                },
                root=root,
            )

            result = mod.node_recovery_cycle({"max_actions": 1}, root=root)

        step = result["steps"][0]
        self.assertEqual(step["recovery_action"], "heartbeat_repair")
        self.assertEqual(step["route"]["endpoint"], "/api/nodes/heartbeat-repair")
        self.assertEqual(step["prepared_plan"]["status"], "planned")
        self.assertEqual(step["result"]["endpoint"], "/api/nodes/heartbeat-repair")

    def test_node_recovery_cycle_marks_offline_nodes_manual_required(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/offline", "ssh_target": "root@offline"}, root=root)
            node_path = mod.node_path("node/offline", root)
            node = mod.read_json(node_path)
            offline_at = (mod.utc_now_dt() - mod.timedelta(seconds=600)).isoformat(timespec="seconds")
            node["updated_at"] = offline_at
            node["last_heartbeat_at"] = offline_at
            node_path.write_text(json.dumps(node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            result = mod.node_recovery_cycle({"max_actions": 1}, root=root)

        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(result["steps"][0]["recovery_action"], "quarantine")
        self.assertEqual(result["steps"][0]["status"], "manual_required")
        self.assertTrue(result["steps"][0]["result"]["requires_operator"])
        self.assertIn("verify_ssh_target_reachable", result["steps"][0]["result"]["steps"])

    def test_node_recovery_cycle_skips_smoke_noise_by_default(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node(
                {
                    "node_id": "local-service-smoke",
                    "ssh_target": "root@127.0.0.1",
                    "message": "service-smoke",
                },
                root=root,
            )
            mod.register_node(
                {
                    "node_id": "remote/a",
                    "ssh_target": "root@100.74.166.86:2200",
                    "labels": ["mobile-added"],
                },
                root=root,
            )
            old_at = (mod.utc_now_dt() - mod.timedelta(seconds=600)).isoformat(timespec="seconds")
            for node_id in ["local-service-smoke", "remote/a"]:
                node_path = mod.node_path(node_id, root)
                node = mod.read_json(node_path)
                node["updated_at"] = old_at
                node["last_heartbeat_at"] = old_at
                node_path.write_text(json.dumps(node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            default_cycle = mod.node_recovery_cycle({"max_actions": 3}, root=root)
            noise_cycle = mod.node_recovery_cycle({"include_noise": True, "max_actions": 3}, root=root)

        self.assertEqual([step["node_id"] for step in default_cycle["steps"]], ["remote-a"])
        self.assertEqual(default_cycle["summary"]["skipped_noise_count"], 1)
        self.assertEqual([step["node_id"] for step in noise_cycle["steps"]], ["local-service-smoke", "remote-a"])

    def test_node_recovery_cycle_skips_duplicate_targets_by_default(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for node_id, label in [("remote/old", "mobile-probed"), ("remote/new", "mobile-added")]:
                mod.register_node(
                    {
                        "node_id": node_id,
                        "ssh_target": "root@100.74.166.86:2200",
                        "labels": [label],
                    },
                    root=root,
                )
            old_at = (mod.utc_now_dt() - mod.timedelta(seconds=900)).isoformat(timespec="seconds")
            new_at = (mod.utc_now_dt() - mod.timedelta(seconds=600)).isoformat(timespec="seconds")
            for node_id, seen_at in [("remote/old", old_at), ("remote/new", new_at)]:
                node_path = mod.node_path(node_id, root)
                node = mod.read_json(node_path)
                node["updated_at"] = seen_at
                node["last_heartbeat_at"] = seen_at
                node_path.write_text(json.dumps(node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            default_cycle = mod.node_recovery_cycle({"max_actions": 3}, root=root)
            duplicate_cycle = mod.node_recovery_cycle({"include_duplicates": True, "max_actions": 3}, root=root)

        self.assertEqual([step["node_id"] for step in default_cycle["steps"]], ["remote-new"])
        self.assertEqual(default_cycle["skipped_duplicate_count"], 1)
        self.assertEqual(default_cycle["skipped_duplicates"][0]["node_id"], "remote-old")
        self.assertEqual([step["node_id"] for step in duplicate_cycle["steps"]], ["remote-old", "remote-new"])

    def test_api_nodes_recovery_cycle_post_endpoint_uses_payload(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None, "input": None}

        class DummyRecoveryCyclePostHandler:
            path = "/api/nodes/recovery-cycle"
            headers = {"Content-Length": "23"}

            def __init__(self):
                self.rfile = io.BytesIO(b'{"execute":false,"x":1}')

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        original_cycle = mod.node_recovery_cycle
        try:
            def fake_cycle(payload):
                captured["input"] = payload
                return {"status": "ok", "kind": "node_recovery_cycle"}

            mod.node_recovery_cycle = fake_cycle
            mod.ControlHandler.do_POST(DummyRecoveryCyclePostHandler())
        finally:
            mod.node_recovery_cycle = original_cycle

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "node_recovery_cycle")
        self.assertEqual(captured["input"], {"execute": False, "x": 1})

    def test_api_nodes_recovery_cycle_get_endpoint_uses_query_budget(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None, "input": None}

        class DummyRecoveryCycleGetHandler:
            path = "/api/nodes/recovery-cycle?max_actions=2&node_id=node-a&include_noise=true&include_duplicates=true"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        original_cycle = mod.node_recovery_cycle
        try:
            def fake_cycle(payload):
                captured["input"] = payload
                return {"status": "ok", "kind": "node_recovery_cycle"}

            mod.node_recovery_cycle = fake_cycle
            mod.ControlHandler.do_GET(DummyRecoveryCycleGetHandler())
        finally:
            mod.node_recovery_cycle = original_cycle

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "node_recovery_cycle")
        self.assertEqual(
            captured["input"],
            {
                "max_actions": "2",
                "node_id": "node-a",
                "include_noise": "true",
                "include_duplicates": "true",
            },
        )

    def test_heartbeat_degraded_status_propagates_to_node_status_and_api_nodes(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@worker-a"}, root=root)
            heartbeat = mod.heartbeat_node(
                {"node_id": "node/a", "status": "degraded", "message": "network jitter"},
                root=root,
            )
            status = mod.node_status(root)

            captured = {"status": None, "payload": None}

            class DummyNodesGetHandler:
                path = "/api/nodes"
                headers = {}

                def write_json(self, status_code, payload):
                    captured["status"] = status_code
                    captured["payload"] = payload

                def write_sse(self, status_code, payload):
                    raise AssertionError("write_sse should not be used for /api/nodes")

            original_node_status = mod.node_status
            mod.node_status = lambda: original_node_status(root)
            try:
                mod.ControlHandler.do_GET(DummyNodesGetHandler())
            finally:
                mod.node_status = original_node_status

        self.assertEqual(heartbeat["node"]["node_id"], "node-a")
        self.assertEqual(heartbeat["node"]["status"], "degraded")
        self.assertEqual(heartbeat["node"]["connection_state"], "degraded")
        self.assertEqual(heartbeat["node"]["connection_action"], "reconnect")
        self.assertEqual(heartbeat["node"]["connection_action_reason"], "heartbeat_reported_degraded")
        self.assertEqual(status["nodes"][0]["connection_state"], "degraded")
        self.assertEqual(status["nodes"][0]["connection_action"], "reconnect")
        self.assertEqual(status["nodes"][0]["connection_action_reason"], "heartbeat_reported_degraded")
        self.assertEqual(captured["status"], 200)
        api_node = captured["payload"]["nodes"][0]
        self.assertEqual(api_node["status"], "degraded")
        self.assertEqual(api_node["connection_state"], "degraded")
        self.assertEqual(api_node["connection_action"], "reconnect")
        self.assertEqual(api_node["connection_action_reason"], "heartbeat_reported_degraded")

    def test_heartbeat_error_and_failed_statuses_propagate_to_node_status(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@worker-a"}, root=root)
            for reported_status in ("error", "failed"):
                heartbeat = mod.heartbeat_node({"node_id": "node/a", "status": reported_status}, root=root)
                status = mod.node_status(root)
                node = status["nodes"][0]
                with self.subTest(reported_status=reported_status):
                    self.assertEqual(heartbeat["node"]["status"], reported_status)
                    self.assertEqual(node["status"], reported_status)
                    self.assertEqual(node["connection_state"], "degraded")
                    self.assertEqual(node["connection_action"], "reconnect")
                    self.assertEqual(node["connection_action_reason"], "heartbeat_reported_degraded")

    def test_heartbeat_node_entry_writes_degraded_fields_to_redis_json_and_xadd(self):
        mod = load_control_api()
        calls = []

        class FakeProc:
            def __init__(self, stdout: str = "OK\n", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            calls.append(args)
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args[:2] == ["XADD", "a9:heartbeats"]:
                return FakeProc("1740000010-0\n")
            return FakeProc()

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                mod.register_node({"node_id": "node/a", "ssh_target": "root@worker-a"}, root=root)
                result = mod.heartbeat_node({"node_id": "node/a", "status": "error"}, root=root)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["node"]["connection_state"], "degraded")
        self.assertEqual(result["redis"]["status"], "ok")
        json_set_calls = [call for call in calls if call[:2] == ["JSON.SET", "a9:node:node-a"]]
        self.assertGreaterEqual(len(json_set_calls), 2)
        json_set_call = json_set_calls[-1]
        json_payload = json.loads(json_set_call[3])
        self.assertEqual(json_payload["node_id"], "node-a")
        self.assertEqual(json_payload["status"], "error")
        self.assertEqual(json_payload["connection_state"], "degraded")
        self.assertEqual(json_payload["connection_action"], "reconnect")
        self.assertEqual(json_payload["connection_action_reason"], "heartbeat_reported_degraded")
        xadd_calls = [call for call in calls if call[:2] == ["XADD", "a9:heartbeats"]]
        self.assertGreaterEqual(len(xadd_calls), 2)
        xadd_call = xadd_calls[-1]
        self.assertIn("node_id", xadd_call)
        self.assertIn("node-a", xadd_call)
        self.assertIn("status", xadd_call)
        self.assertIn("error", xadd_call)
        self.assertIn("connection_state", xadd_call)
        self.assertIn("degraded", xadd_call)
        self.assertIn("connection_action", xadd_call)
        self.assertIn("reconnect", xadd_call)
        self.assertIn("connection_action_reason", xadd_call)
        self.assertIn("heartbeat_reported_degraded", xadd_call)

    def test_api_nodes_endpoint_preserves_reconnect_governance_fields(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node(
                {
                    "node_id": "node/a",
                    "ssh_target": "root@worker-a",
                    "reconnect_action": "reconnect",
                    "reconnect_reason": "ssh_exec_error",
                    "reconnect_attempt": 3,
                    "reconnect_backoff_seconds": 8,
                    "stream_action": "continue",
                    "stream_reason": "decode_error",
                    "reconnect_lifecycle": {"event": "reconnecting", "phase": "backoff"},
                },
                root=root,
            )

            captured = {"status": None, "payload": None}

            class DummyNodesGetHandler:
                path = "/api/nodes"
                headers = {}

                def write_json(self, status, payload):
                    captured["status"] = status
                    captured["payload"] = payload

                def write_sse(self, status, payload):
                    raise AssertionError("write_sse should not be used for /api/nodes")

            original_node_status = mod.node_status
            mod.node_status = lambda: original_node_status(root)
            try:
                mod.ControlHandler.do_GET(DummyNodesGetHandler())
            finally:
                mod.node_status = original_node_status

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["count"], 1)
        node = captured["payload"]["nodes"][0]
        self.assertEqual(node["reconnect_action"], "reconnect")
        self.assertEqual(node["reconnect_reason"], "ssh_exec_error")
        self.assertEqual(node["reconnect_attempt"], 3)
        self.assertEqual(node["reconnect_backoff_seconds"], 8)
        self.assertEqual(node["stream_action"], "continue")
        self.assertEqual(node["stream_reason"], "decode_error")
        self.assertEqual(node["reconnect_lifecycle"], {"event": "reconnecting", "phase": "backoff"})

    def test_api_nodes_status_omits_heartbeat_start_fields_without_heartbeat_start_evidence(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node(
                {
                    "node_id": "node/a",
                    "ssh_target": "root@worker-a",
                    "capabilities": {"python3": "/usr/bin/python3"},
                },
                root=root,
            )
            mod.heartbeat_node({"node_id": "node/a", "status": "online", "message": "ready"}, root=root)

            captured = {"status": None, "payload": None}

            class DummyNodesStatusGetHandler:
                path = "/api/nodes/status"
                headers = {}

                def write_json(self, status, payload):
                    captured["status"] = status
                    captured["payload"] = payload

                def write_sse(self, status, payload):
                    raise AssertionError("write_sse should not be used for /api/nodes/status")

            original_node_status = mod.node_status
            mod.node_status = lambda: original_node_status(root)
            try:
                mod.ControlHandler.do_GET(DummyNodesStatusGetHandler())
            finally:
                mod.node_status = original_node_status

        self.assertEqual(captured["status"], 200)
        node = captured["payload"]["nodes"][0]
        self.assertEqual(node["node_id"], "node-a")
        self.assertNotIn("heartbeat_start_status", node)
        self.assertNotIn("heartbeat_start_action", node)
        self.assertNotIn("heartbeat_start_action_reason", node)
        self.assertNotIn("heartbeat_start_return_code", node)
        self.assertNotIn("heartbeat_start_timed_out", node)
        self.assertNotIn("heartbeat_start_executed_at", node)
        self.assertNotIn("heartbeat_start_evidence_path", node)
        self.assertNotIn("bootstrap_execution", node)

    def test_gateway_transport_contract_get_endpoint_emits_event(self):
        mod = load_control_api()

        captured = {"status": None, "payload": None, "emit_event": None}

        class DummyTransportContractGetHandler:
            path = "/api/gateway/transport-contract?emit_event=1"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        original_gateway_transport_contract = mod.gateway_transport_contract

        def fake_gateway_transport_contract(*, emit_event: bool = False) -> dict[str, object]:
            captured["emit_event"] = emit_event
            return {"status": "ok", "kind": "gateway_transport_contract"}

        try:
            mod.gateway_transport_contract = fake_gateway_transport_contract
            mod.ControlHandler.do_GET(DummyTransportContractGetHandler())
        finally:
            mod.gateway_transport_contract = original_gateway_transport_contract

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["status"], "ok")
        self.assertEqual(captured["payload"]["kind"], "gateway_transport_contract")
        self.assertTrue(captured["emit_event"])

    def test_api_status_endpoint_reads_supervisor_status_payload(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / ".a9"
            (state_dir / "tasks" / "queue").mkdir(parents=True)
            (state_dir / "tasks" / "running").mkdir(parents=True)
            (state_dir / "tasks" / "done").mkdir(parents=True)
            (state_dir / "runs" / "run-1").mkdir(parents=True)
            (state_dir / "nodes").mkdir(parents=True)

            (state_dir / "tasks" / "queue" / "task-a.md").write_text("task-a", encoding="utf-8")
            (state_dir / "tasks" / "queue" / "task-b.md").write_text("task-b", encoding="utf-8")
            (state_dir / "tasks" / "running" / "task-c.json").write_text(
                json.dumps({"task_id": "task-c", "status": "running"}) + "\n",
                encoding="utf-8",
            )
            (state_dir / "tasks" / "done" / "task-d.json").write_text(
                json.dumps({"task_id": "task-d", "status": "pass"}) + "\n",
                encoding="utf-8",
            )
            (state_dir / "runs" / "run-1" / "summary.json").write_text(
                json.dumps(
                    {"task_id": "run-1", "status": "pass", "run_dir": str(state_dir / "runs" / "run-1")},
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "progress.json").write_text('{"progress_percent": 42}', encoding="utf-8")
            (state_dir / "daemon_heartbeat.json").write_text('{"status": "ok"}', encoding="utf-8")
            (state_dir / "nodes" / "node-a.json").write_text(
                json.dumps({"node_id": "node-a", "ssh_target": "root@worker-a", "status": "online"}) + "\n",
                encoding="utf-8",
            )

            class DummyStatusHandler:
                path = "/api/status"
                headers = {}

                def write_json(self, status_code, payload):
                    captured["status"] = status_code
                    captured["payload"] = payload

                def write_sse(self, status_code, payload):
                    raise AssertionError("write_sse should not be used for /api/status")

            old_supervisor_status = mod.supervisor_status
            original_run = mod.subprocess.run
            mod.subprocess.run = lambda *args, **kwargs: type(
                "FakeProc",
                (),
                {
                    "returncode": 0,
                    "stdout": (
                        "101 1 00:10 python3 scripts/a9_control_api.py serve --host 0.0.0.0 --port 8787\n"
                        "201 1 00:09 python3 scripts/a9_node.py command-work-loop --block-ms 5000\n"
                        "301 1 00:08 python3 scripts/a9_recovery_loop.py --controller-url http://127.0.0.1:8787\n"
                        "401 1 00:07 python3 scripts/a9_supervisor.py run-loop --auto-next --sleep-seconds 10\n"
                    ),
                },
            )()
            mod.supervisor_status = lambda: old_supervisor_status(root)
            try:
                mod.ControlHandler.do_GET(DummyStatusHandler())
            finally:
                mod.supervisor_status = old_supervisor_status
                mod.subprocess.run = original_run

        self.assertEqual(captured["status"], 200)
        status = captured["payload"]
        self.assertEqual(status["queued"], 2)
        self.assertEqual(status["running"], 1)
        self.assertEqual(status["done"], 1)
        self.assertEqual(len(status["queue"]), 2)
        self.assertTrue(status["queue"][0].endswith("task-a.md"))
        self.assertTrue(status["queue"][1].endswith("task-b.md"))
        self.assertEqual(status["running_tasks"][0]["task_id"], "task-c")
        self.assertEqual(status["latest_run"]["task_id"], "run-1")
        self.assertEqual(status["latest_run"]["status"], "pass")
        self.assertEqual(status["progress"]["progress_percent"], 42)
        self.assertEqual(status["daemon_heartbeat"]["status"], "ok")
        self.assertEqual(status["nodes"]["count"], 1)
        self.assertEqual(status["nodes"]["nodes"][0]["node_id"], "node-a")
        self.assertEqual(status["service_observation"]["status"], "ok")
        self.assertEqual(status["service_observation"]["observed"]["missing_count"], 0)
        self.assertEqual(status["service_observation"]["observed"]["next_action"], "observe")

    def test_monitor_status_projects_runtime_contract_for_monitor(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / ".a9"
            run_dir = state_dir / "runs" / "run-1"
            (state_dir / "tasks" / "queue").mkdir(parents=True)
            (state_dir / "tasks" / "running").mkdir(parents=True)
            (state_dir / "tasks" / "done").mkdir(parents=True)
            (state_dir / "tasks" / "queue" / "risky-task.md").write_text(
                """---
id: "risky-task"
phase: "implement"
checks:
allowed_paths:
task_quality_warnings:
  - "declared_check_maybe_shell_expanded:test_literal"
---
Do risky work.
""",
                encoding="utf-8",
            )
            (state_dir / "nodes").mkdir(parents=True)
            (state_dir / "runtime").mkdir(parents=True)
            (state_dir / "runtime" / "control_state.json").write_text(
                json.dumps(
                    {
                        "schema": "a9.runtime_control_state.v1",
                        "paused": True,
                        "status": "paused",
                        "reason": "operator inspection",
                        "updated_at": "2026-06-04T00:00:00+00:00",
                        "last_intervention": {"intervention_id": "monitor-pause-1", "action": "pause"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "runtime" / "worker_transport_health.json").write_text(
                json.dumps({"schema": "a9.worker_transport_health.v1", "status": "cooldown"}),
                encoding="utf-8",
            )
            intervention_audit = state_dir / "monitor" / "interventions.jsonl"
            intervention_audit.parent.mkdir(parents=True)
            intervention_audit.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "at": "2026-06-04T00:00:01+00:00",
                                "kind": "monitor_intervention_audit",
                                "action": "pause",
                                "status": "recorded",
                                "intervention_id": "monitor-pause-1",
                            }
                        ),
                        json.dumps(
                            {
                                "at": "2026-06-04T00:00:02+00:00",
                                "kind": "monitor_intervention_audit",
                                "action": "repair",
                                "status": "recorded",
                                "intervention_id": "monitor-repair-1",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            run_dir.mkdir(parents=True)
            summary = {
                "task_id": "task-1",
                "status": "needs-repair",
                "phase": "implement",
                "run_dir": str(run_dir),
                "context_pressure": {
                    "prompt_approx_tokens": 100,
                    "prompt_budget_tokens": 1000,
                    "budget_ratio": 0.1,
                    "remaining_tokens": 900,
                    "over_budget": False,
                },
                "runtime_monitor_contract": {
                    "schema": "a9.runtime_monitor_contract.v1",
                    "task": {"task_id": "task-1", "phase": "implement", "route": "execution_next"},
                    "run": {"run_id": "run-1", "status": "needs-repair", "attempt": 1, "run_dir": str(run_dir)},
                    "worker_intent": {"status": "visible", "phase_focus": "Implement", "reference_gate_status": "pass"},
                    "worker_prompt": {
                        "prompt_path": str(run_dir / "prompt.md"),
                        "raw_task_path": str(run_dir / "raw_task.md"),
                        "prompt_approx_tokens": 100,
                        "prompt_budget_tokens": 1000,
                    },
                    "command_envelope": {
                        "command_id": "task-1",
                        "target_node": "local-supervisor",
                        "expected_revision": 1,
                        "idempotency_key": "task-1:1",
                        "evidence_path": str(run_dir / "evidence.jsonl"),
                    },
                    "diff_and_checks": {
                        "changed_files": ["scripts/a9_supervisor.py"],
                        "failed_checks_count": 1,
                        "failed_checks": [{"command": "python3 -m unittest tests.test_supervisor", "return_code": 1}],
                        "diff_path": str(run_dir / "patch.diff"),
                    },
                    "monitor": {
                        "next_action": "repair",
                        "recommended_action": "repair",
                        "decision_model": "requirements_review_council_v1",
                        "score": 0.4,
                        "intervention_options": ["pause", "repair", "route_to_debate"],
                        "block": {"blocked": True, "reason": "failed_check"},
                    },
                    "evidence_refs": {
                        "runtime_monitor_contract_path": str(run_dir / "runtime_monitor_contract.json"),
                        "summary_path": str(run_dir / "summary.json"),
                        "execution_chain_path": str(run_dir / "execution_chain.json"),
                        "evidence_path": str(run_dir / "evidence.jsonl"),
                        "state_path": str(run_dir / "state.json"),
                    },
                    "guardrails": {"page_details_frozen": True, "no_nzx_business_code": True},
                },
            }
            (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False) + "\n", encoding="utf-8")

            payload = mod.monitor_status(root)

        self.assertEqual(payload["schema"], "a9.monitor_status.v1")
        self.assertEqual(payload["latest_run"]["task_id"], "task-1")
        self.assertEqual(payload["latest_run_lanes"]["latest_any"]["task_id"], "task-1")
        self.assertEqual(payload["queue"]["task_quality"]["status"], "warning")
        self.assertEqual(payload["queue"]["task_quality"]["warning_task_count"], 1)
        self.assertEqual(payload["latest_run"]["run_id"], "run-1")
        self.assertEqual(payload["next_action"], "repair")
        self.assertEqual(payload["failed_checks_count"], 1)
        self.assertEqual(payload["changed_files"], ["scripts/a9_supervisor.py"])
        self.assertEqual(payload["command_envelope"]["idempotency_key"], "task-1:1")
        self.assertTrue(payload["guardrails"]["page_details_frozen"])
        self.assertEqual(payload["context_pressure"]["remaining_tokens"], 900)
        self.assertTrue(payload["runtime_control"]["paused"])
        self.assertEqual(payload["worker_transport_health"]["status"], "cooldown")
        self.assertEqual(payload["runtime_control"]["status"], "paused")
        self.assertEqual(payload["runtime_control"]["last_intervention"]["intervention_id"], "monitor-pause-1")
        self.assertEqual(payload["recent_interventions"]["event_count"], 2)
        self.assertEqual(payload["recent_interventions"]["events"][1]["intervention_id"], "monitor-repair-1")

    def test_api_monitor_status_endpoint_returns_monitor_payload(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}

        class DummyMonitorStatusGetHandler:
            path = "/api/monitor/status"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

            def write_sse(self, status, payload):
                raise AssertionError("write_sse should not be used for /api/monitor/status")

        original_monitor_status = mod.monitor_status
        try:
            mod.monitor_status = lambda: {"status": "ok", "kind": "monitor_status", "next_action": "observe"}
            mod.ControlHandler.do_GET(DummyMonitorStatusGetHandler())
        finally:
            mod.monitor_status = original_monitor_status

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "monitor_status")
        self.assertEqual(captured["payload"]["next_action"], "observe")

    def test_monitor_control_aggregates_status_examples_and_stream_hint(self):
        mod = load_control_api()
        original_status = mod.monitor_status
        original_examples = mod.monitor_intervention_examples
        original_model_policy = mod.worker_model_policy
        original_transport_policy = mod.worker_transport_policy
        try:
            mod.monitor_status = lambda root=mod.ROOT: {
                "status": "ok",
                "kind": "monitor_status",
                "recent_interventions": {
                    "event_count": 1,
                    "events": [
                        {
                            "intervention_id": "monitor-1",
                            "redis_mirror": {"stream_id": "1740000010-0"},
                        }
                    ],
                },
            }
            mod.monitor_intervention_examples = lambda root=mod.ROOT: {
                "status": "ok",
                "kind": "monitor_intervention_examples",
                "examples": {"pause": {"action": "pause"}},
            }
            mod.worker_model_policy = lambda root=mod.ROOT: {
                "status": "ok",
                "kind": "worker_model_policy",
                "resolved": {"repair": {"model": "gpt-5.5", "source": "A9_SUPERVISOR_CRITICAL_MODEL"}},
            }
            mod.worker_transport_policy = lambda root=mod.ROOT: {
                "status": "ok",
                "kind": "worker_transport_policy",
                "resolved": {"backend": "codex_exec", "source": "worker_transport_policy.backend"},
            }
            payload = mod.monitor_control()
        finally:
            mod.monitor_status = original_status
            mod.monitor_intervention_examples = original_examples
            mod.worker_model_policy = original_model_policy
            mod.worker_transport_policy = original_transport_policy

        self.assertEqual(payload["schema"], "a9.monitor_control.v1")
        self.assertEqual(payload["monitor_status"]["kind"], "monitor_status")
        self.assertEqual(payload["worker_model_policy"]["resolved"]["repair"]["model"], "gpt-5.5")
        self.assertEqual(payload["worker_transport_policy"]["resolved"]["backend"], "codex_exec")
        self.assertEqual(payload["intervention_examples"]["examples"]["pause"]["action"], "pause")
        self.assertEqual(payload["intervention_stream"]["stream"], "a9:monitor:interventions")
        self.assertEqual(payload["intervention_stream"]["next_last_id"], "1740000010-0")
        self.assertEqual(payload["actions"]["post_endpoint"], "/api/monitor/intervention")

    def test_worker_model_policy_resolves_supervisor_phase_overrides(self):
        mod = load_control_api()
        sup = mod.supervisor()
        original_supervisor = mod.supervisor
        old_model_policy_path = sup.WORKER_MODEL_POLICY_PATH
        old_global = os.environ.pop("A9_SUPERVISOR_MODEL", None)
        old_critical = os.environ.pop("A9_SUPERVISOR_CRITICAL_MODEL", None)
        old_repair = os.environ.pop("A9_SUPERVISOR_PHASE_MODEL_REPAIR", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                sup.WORKER_MODEL_POLICY_PATH = Path(tmp) / "worker_model_policy.json"
                mod.supervisor = lambda: sup
                os.environ["A9_SUPERVISOR_CRITICAL_MODEL"] = "gpt-5.5"
                os.environ["A9_SUPERVISOR_PHASE_MODEL_REPAIR"] = "gpt-5.4"
                payload = mod.worker_model_policy()
        finally:
            sup.WORKER_MODEL_POLICY_PATH = old_model_policy_path
            mod.supervisor = original_supervisor
            if old_global is not None:
                os.environ["A9_SUPERVISOR_MODEL"] = old_global
            else:
                os.environ.pop("A9_SUPERVISOR_MODEL", None)
            if old_critical is not None:
                os.environ["A9_SUPERVISOR_CRITICAL_MODEL"] = old_critical
            else:
                os.environ.pop("A9_SUPERVISOR_CRITICAL_MODEL", None)
            if old_repair is not None:
                os.environ["A9_SUPERVISOR_PHASE_MODEL_REPAIR"] = old_repair
            else:
                os.environ.pop("A9_SUPERVISOR_PHASE_MODEL_REPAIR", None)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["schema"], "a9.worker_model_policy.v1")
        self.assertEqual(payload["configured_env"]["A9_SUPERVISOR_CRITICAL_MODEL"], "gpt-5.5")
        self.assertEqual(payload["resolved"]["test"]["model"], "gpt-5.5")
        self.assertEqual(payload["resolved"]["test"]["source"], "A9_SUPERVISOR_CRITICAL_MODEL")
        self.assertEqual(payload["resolved"]["repair"]["model"], "gpt-5.4")
        self.assertEqual(payload["resolved"]["repair"]["source"], "A9_SUPERVISOR_PHASE_MODEL_REPAIR")

    def test_worker_transport_policy_exposes_supervisor_policy(self):
        mod = load_control_api()
        sup = mod.supervisor()
        original_supervisor = mod.supervisor
        old_policy_path = sup.WORKER_TRANSPORT_POLICY_PATH
        old_override = os.environ.pop("A9_SUPERVISOR_WORKER_CMD", None)
        old_backend = os.environ.pop("A9_SUPERVISOR_WORKER_TRANSPORT_BACKEND", None)
        old_template = os.environ.pop("A9_SUPERVISOR_WORKER_CMD_TEMPLATE", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                sup.WORKER_TRANSPORT_POLICY_PATH = Path(tmp) / "worker_transport_policy.json"
                mod.supervisor = lambda: sup
                sup.write_worker_transport_policy(
                    backend="custom_command",
                    custom_command_template="echo ok > {final_path}",
                    reason="control-api-test",
                )
                payload = mod.worker_transport_policy()
        finally:
            sup.WORKER_TRANSPORT_POLICY_PATH = old_policy_path
            mod.supervisor = original_supervisor
            if old_override is None:
                os.environ.pop("A9_SUPERVISOR_WORKER_CMD", None)
            else:
                os.environ["A9_SUPERVISOR_WORKER_CMD"] = old_override
            if old_backend is None:
                os.environ.pop("A9_SUPERVISOR_WORKER_TRANSPORT_BACKEND", None)
            else:
                os.environ["A9_SUPERVISOR_WORKER_TRANSPORT_BACKEND"] = old_backend
            if old_template is None:
                os.environ.pop("A9_SUPERVISOR_WORKER_CMD_TEMPLATE", None)
            else:
                os.environ["A9_SUPERVISOR_WORKER_CMD_TEMPLATE"] = old_template

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["schema"], "a9.worker_transport_policy.v1")
        self.assertEqual(payload["policy_state"]["backend"], "custom_command")
        self.assertEqual(payload["resolved"]["backend"], "custom_command")
        self.assertEqual(payload["resolved"]["source"], "worker_transport_policy.backend")

    def test_worker_transport_presets_include_openai_compatible_template(self):
        mod = load_control_api()
        payload = mod.worker_transport_presets()
        presets = {item["name"]: item for item in payload["presets"]}
        openai_worker_path = str(mod.ROOT / "scripts" / "a9_openai_compatible_worker.py")

        self.assertEqual(payload["schema"], "a9.worker_transport_presets.v1")
        self.assertEqual(presets["codex_exec"]["backend"], "codex_exec")
        self.assertEqual(presets["openai_compatible"]["backend"], "custom_command")
        self.assertIn(openai_worker_path, presets["openai_compatible"]["custom_command_template"])
        self.assertIn("{prompt_file}", presets["openai_compatible"]["custom_command_template"])
        self.assertIn("{final_path}", presets["openai_compatible"]["custom_command_template"])
        self.assertIn("A9_LLM_WORKER_MODEL", presets["openai_compatible"]["requires"])

    def test_update_worker_transport_policy_requires_runtime_arm(self):
        mod = load_control_api()
        sup = mod.supervisor()
        original_supervisor = mod.supervisor
        original_audit = mod.enqueue_monitor_intervention_audit
        old_policy_path = sup.WORKER_TRANSPORT_POLICY_PATH
        old_override = os.environ.pop("A9_SUPERVISOR_WORKER_CMD", None)
        old_backend = os.environ.pop("A9_SUPERVISOR_WORKER_TRANSPORT_BACKEND", None)
        old_template = os.environ.pop("A9_SUPERVISOR_WORKER_CMD_TEMPLATE", None)
        audit_events = []
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "root"
                root.mkdir()
                sup.WORKER_TRANSPORT_POLICY_PATH = Path(tmp) / "worker_transport_policy.json"
                mod.supervisor = lambda: sup
                mod.enqueue_monitor_intervention_audit = lambda event, *, root: audit_events.append((event, root))

                blocked = mod.update_worker_transport_policy(
                    {
                        "backend": "custom_command",
                        "custom_command_template": "echo ok > {final_path}",
                        "reason": "test blocked",
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
                mod.phone_control_arm(
                    {"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]},
                    root=root,
                )
                applied = mod.update_worker_transport_policy(
                    {
                        "backend": "custom_command",
                        "custom_command_template": "echo ok > {final_path}",
                        "reason": "switch to test custom worker",
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
        finally:
            sup.WORKER_TRANSPORT_POLICY_PATH = old_policy_path
            mod.supervisor = original_supervisor
            mod.enqueue_monitor_intervention_audit = original_audit
            if old_override is None:
                os.environ.pop("A9_SUPERVISOR_WORKER_CMD", None)
            else:
                os.environ["A9_SUPERVISOR_WORKER_CMD"] = old_override
            if old_backend is None:
                os.environ.pop("A9_SUPERVISOR_WORKER_TRANSPORT_BACKEND", None)
            else:
                os.environ["A9_SUPERVISOR_WORKER_TRANSPORT_BACKEND"] = old_backend
            if old_template is None:
                os.environ.pop("A9_SUPERVISOR_WORKER_CMD_TEMPLATE", None)
            else:
                os.environ["A9_SUPERVISOR_WORKER_CMD_TEMPLATE"] = old_template

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["gate"]["reason"], "phone_control_disarmed")
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["after"]["backend"], "custom_command")
        self.assertEqual(applied["resolved"]["backend"], "custom_command")
        self.assertEqual([event[0]["status"] for event in audit_events], ["blocked", "applied"])

    def test_update_worker_transport_policy_returns_exact_custom_rollback_payload(self):
        mod = load_control_api()
        sup = mod.supervisor()
        original_supervisor = mod.supervisor
        original_audit = mod.enqueue_monitor_intervention_audit
        old_policy_path = sup.WORKER_TRANSPORT_POLICY_PATH
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "root"
                root.mkdir()
                sup.WORKER_TRANSPORT_POLICY_PATH = Path(tmp) / "worker_transport_policy.json"
                mod.supervisor = lambda: sup
                mod.enqueue_monitor_intervention_audit = lambda event, *, root: None
                sup.write_worker_transport_policy(
                    backend="custom_command",
                    custom_command_template="echo previous > {final_path}",
                    reason="existing custom worker",
                )
                mod.phone_control_arm(
                    {"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]},
                    root=root,
                )
                applied = mod.update_worker_transport_policy(
                    {
                        "preset": "local_envelope_smoke",
                        "reason": "temporary local smoke",
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
        finally:
            sup.WORKER_TRANSPORT_POLICY_PATH = old_policy_path
            mod.supervisor = original_supervisor
            mod.enqueue_monitor_intervention_audit = original_audit

        rollback = applied["rollback_payload"]
        self.assertEqual(rollback["backend"], "custom_command")
        self.assertEqual(rollback["custom_command_template"], "echo previous > {final_path}")
        self.assertNotIn("preset", rollback)

    def test_update_worker_transport_policy_can_apply_openai_preset(self):
        mod = load_control_api()
        sup = mod.supervisor()
        original_supervisor = mod.supervisor
        original_audit = mod.enqueue_monitor_intervention_audit
        old_policy_path = sup.WORKER_TRANSPORT_POLICY_PATH
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "root"
                root.mkdir()
                sup.WORKER_TRANSPORT_POLICY_PATH = Path(tmp) / "worker_transport_policy.json"
                mod.supervisor = lambda: sup
                mod.enqueue_monitor_intervention_audit = lambda event, *, root: None
                mod.phone_control_arm(
                    {"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]},
                    root=root,
                )
                applied = mod.update_worker_transport_policy(
                    {
                        "preset": "openai_compatible",
                        "reason": "switch to openai compatible worker preset",
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
        finally:
            sup.WORKER_TRANSPORT_POLICY_PATH = old_policy_path
            mod.supervisor = original_supervisor
            mod.enqueue_monitor_intervention_audit = original_audit

        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["preset"], "openai_compatible")
        self.assertEqual(applied["after"]["backend"], "custom_command")
        self.assertIn(str(mod.ROOT / "scripts" / "a9_openai_compatible_worker.py"), applied["after"]["custom_command_template"])

    def test_update_worker_transport_policy_materializes_openai_config_in_command(self):
        mod = load_control_api()
        sup = mod.supervisor()
        original_supervisor = mod.supervisor
        original_audit = mod.enqueue_monitor_intervention_audit
        old_policy_path = sup.WORKER_TRANSPORT_POLICY_PATH
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "root"
                root.mkdir()
                sup.WORKER_TRANSPORT_POLICY_PATH = Path(tmp) / "worker_transport_policy.json"
                mod.supervisor = lambda: sup
                mod.enqueue_monitor_intervention_audit = lambda event, *, root: None
                mod.phone_control_arm(
                    {"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]},
                    root=root,
                )
                applied = mod.update_worker_transport_policy(
                    {
                        "preset": "openai_compatible",
                        "model": "gateway-model",
                        "base_url": "http://127.0.0.1:8000/v1",
                        "api_key_env": "A9_GATEWAY_KEY",
                        "timeout_seconds": 11,
                        "reason": "switch with materialized gateway config",
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
        finally:
            sup.WORKER_TRANSPORT_POLICY_PATH = old_policy_path
            mod.supervisor = original_supervisor
            mod.enqueue_monitor_intervention_audit = original_audit

        command = applied["after"]["custom_command_template"]
        self.assertIn("--model gateway-model", command)
        self.assertIn("--base-url http://127.0.0.1:8000/v1", command)
        self.assertIn("--api-key-env A9_GATEWAY_KEY", command)
        self.assertIn("--timeout-seconds 11", command)

    def test_update_worker_transport_policy_requires_probe_pass_before_openai_switch(self):
        mod = load_control_api()
        sup = mod.supervisor()
        original_supervisor = mod.supervisor
        original_audit = mod.enqueue_monitor_intervention_audit
        old_policy_path = sup.WORKER_TRANSPORT_POLICY_PATH
        old_key = os.environ.get("A9_LLM_WORKER_API_KEY")
        old_model = os.environ.get("A9_LLM_WORKER_MODEL")
        audit_events = []
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "root"
                root.mkdir()
                sup.WORKER_TRANSPORT_POLICY_PATH = Path(tmp) / "worker_transport_policy.json"
                mod.supervisor = lambda: sup
                mod.enqueue_monitor_intervention_audit = lambda event, *, root: audit_events.append(event)
                os.environ["A9_LLM_WORKER_API_KEY"] = "test-key"
                os.environ["A9_LLM_WORKER_MODEL"] = "test-model"
                mod.phone_control_arm(
                    {"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]},
                    root=root,
                )
                with mock.patch.object(
                    mod,
                    "run_openai_compatible_worker_probe",
                    return_value={"status": "fail", "return_code": 70},
                ):
                    failed = mod.update_worker_transport_policy(
                        {
                            "preset": "openai_compatible",
                            "require_probe_pass": True,
                            "reason": "switch only after live probe",
                            "operator_scopes": ["operator.admin"],
                        },
                        root=root,
                    )
                unchanged = sup.worker_transport_policy_state()
                with mock.patch.object(
                    mod,
                    "run_openai_compatible_worker_probe",
                    return_value={"status": "pass", "return_code": 0},
                ):
                    applied = mod.update_worker_transport_policy(
                        {
                            "preset": "openai_compatible",
                            "require_probe_pass": True,
                            "reason": "switch after live probe",
                            "operator_scopes": ["operator.admin"],
                        },
                        root=root,
                    )
        finally:
            sup.WORKER_TRANSPORT_POLICY_PATH = old_policy_path
            mod.supervisor = original_supervisor
            mod.enqueue_monitor_intervention_audit = original_audit
            if old_key is None:
                os.environ.pop("A9_LLM_WORKER_API_KEY", None)
            else:
                os.environ["A9_LLM_WORKER_API_KEY"] = old_key
            if old_model is None:
                os.environ.pop("A9_LLM_WORKER_MODEL", None)
            else:
                os.environ["A9_LLM_WORKER_MODEL"] = old_model

        self.assertEqual(failed["status"], "probe_failed")
        self.assertEqual(unchanged["backend"], "codex_exec")
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["probe"]["status"], "pass")
        self.assertEqual(applied["after"]["backend"], "custom_command")
        self.assertIn("--model test-model", applied["after"]["custom_command_template"])
        self.assertEqual([event["status"] for event in audit_events], ["probe_failed", "applied"])

    def test_update_worker_transport_policy_codex_preset_clears_custom_template(self):
        mod = load_control_api()
        sup = mod.supervisor()
        original_supervisor = mod.supervisor
        original_audit = mod.enqueue_monitor_intervention_audit
        old_policy_path = sup.WORKER_TRANSPORT_POLICY_PATH
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "root"
                root.mkdir()
                sup.WORKER_TRANSPORT_POLICY_PATH = Path(tmp) / "worker_transport_policy.json"
                mod.supervisor = lambda: sup
                mod.enqueue_monitor_intervention_audit = lambda event, *, root: None
                mod.phone_control_arm(
                    {"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]},
                    root=root,
                )
                mod.update_worker_transport_policy(
                    {
                        "preset": "local_envelope_smoke",
                        "reason": "switch to local smoke worker",
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
                restored = mod.update_worker_transport_policy(
                    {
                        "preset": "codex_exec",
                        "reason": "restore codex exec worker",
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
        finally:
            sup.WORKER_TRANSPORT_POLICY_PATH = old_policy_path
            mod.supervisor = original_supervisor
            mod.enqueue_monitor_intervention_audit = original_audit

        self.assertEqual(restored["status"], "applied")
        self.assertEqual(restored["preset"], "codex_exec")
        self.assertEqual(restored["after"]["backend"], "codex_exec")
        self.assertEqual(restored["after"]["custom_command_template"], "")
        self.assertEqual(restored["resolved"]["custom_command_template"], "")

    def test_api_worker_transport_policy_post_route_calls_handler(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None, "request": None}
        original_update = mod.update_worker_transport_policy
        body = b'{"backend":"codex_exec"}'

        class DummyWorkerTransportPolicyPostHandler:
            path = "/api/worker/transport-policy"
            headers = {"Content-Length": str(len(body))}
            rfile = io.BytesIO(body)

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        def fake_update(payload):
            captured["request"] = payload
            return {"status": "applied", "kind": "worker_transport_policy_update"}

        try:
            mod.update_worker_transport_policy = fake_update
            mod.ControlHandler.do_POST(DummyWorkerTransportPolicyPostHandler())
        finally:
            mod.update_worker_transport_policy = original_update

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "worker_transport_policy_update")
        self.assertEqual(captured["request"]["backend"], "codex_exec")

    def test_api_worker_transport_presets_endpoint_returns_payload(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}
        original_presets = mod.worker_transport_presets

        class DummyWorkerTransportPresetsGetHandler:
            path = "/api/worker/transport-presets"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

            def write_sse(self, status, payload):
                raise AssertionError("write_sse should not be used for worker transport presets")

        try:
            mod.worker_transport_presets = lambda: {"status": "ok", "kind": "worker_transport_presets"}
            mod.ControlHandler.do_GET(DummyWorkerTransportPresetsGetHandler())
        finally:
            mod.worker_transport_presets = original_presets

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "worker_transport_presets")

    def test_worker_transport_check_reports_openai_compatible_config(self):
        mod = load_control_api()
        old_key = os.environ.pop("A9_LLM_WORKER_API_KEY", None)
        old_openai_key = os.environ.pop("OPENAI_API_KEY", None)
        old_model = os.environ.pop("A9_LLM_WORKER_MODEL", None)
        old_base = os.environ.pop("A9_LLM_WORKER_BASE_URL", None)
        try:
            missing = mod.worker_transport_check({"preset": "openai_compatible"})
            os.environ["A9_LLM_WORKER_API_KEY"] = "test-key"
            ready = mod.worker_transport_check(
                {
                    "preset": "openai_compatible",
                    "model": "test-model",
                    "base_url": "http://127.0.0.1:8000/v1",
                    "timeout_seconds": 7,
                }
            )
        finally:
            if old_key is not None:
                os.environ["A9_LLM_WORKER_API_KEY"] = old_key
            else:
                os.environ.pop("A9_LLM_WORKER_API_KEY", None)
            if old_openai_key is not None:
                os.environ["OPENAI_API_KEY"] = old_openai_key
            else:
                os.environ.pop("OPENAI_API_KEY", None)
            if old_model is not None:
                os.environ["A9_LLM_WORKER_MODEL"] = old_model
            else:
                os.environ.pop("A9_LLM_WORKER_MODEL", None)
            if old_base is not None:
                os.environ["A9_LLM_WORKER_BASE_URL"] = old_base
            else:
                os.environ.pop("A9_LLM_WORKER_BASE_URL", None)

        self.assertEqual(missing["status"], "not_configured")
        self.assertIn("A9_LLM_WORKER_API_KEY or OPENAI_API_KEY", missing["config"]["missing"])
        self.assertIn("A9_LLM_WORKER_MODEL or payload.model", missing["config"]["missing"])
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["config"]["model"], "test-model")
        self.assertEqual(ready["config"]["base_url"], "http://127.0.0.1:8000/v1")
        self.assertEqual(ready["config"]["timeout_seconds"], 7)

    def test_llm_worker_config_update_persists_non_secret_defaults(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocked = mod.update_llm_worker_config(
                {
                    "model": "test-model",
                    "base_url": "http://127.0.0.1:8000/v1",
                    "api_key_env": "A9_TEST_KEY",
                    "timeout_seconds": 9,
                    "reason": "configure test gateway",
                    "operator_scopes": ["operator.admin"],
                },
                root=root,
            )
            mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
            applied = mod.update_llm_worker_config(
                {
                    "model": "test-model",
                    "base_url": "http://127.0.0.1:8000/v1",
                    "api_key_env": "A9_TEST_KEY",
                    "timeout_seconds": 9,
                    "reason": "configure test gateway",
                    "operator_scopes": ["operator.admin"],
                },
                root=root,
            )
            config = mod.openai_compatible_worker_config({}, root=root)

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["after"]["model"], "test-model")
        self.assertEqual(applied["after"]["api_key_env"], "A9_TEST_KEY")
        self.assertNotIn("api_key", applied["after"])
        self.assertEqual(config["model"], "test-model")
        self.assertEqual(config["base_url"], "http://127.0.0.1:8000/v1")
        self.assertEqual(config["api_key_env"], "A9_TEST_KEY")
        self.assertEqual(config["timeout_seconds"], 9)

    def test_worker_transport_check_execute_requires_runtime_arm(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_key = os.environ.get("A9_LLM_WORKER_API_KEY")
            old_model = os.environ.get("A9_LLM_WORKER_MODEL")
            try:
                os.environ["A9_LLM_WORKER_API_KEY"] = "test-key"
                os.environ["A9_LLM_WORKER_MODEL"] = "test-model"
                blocked = mod.worker_transport_check({"preset": "openai_compatible", "execute": True, "operator_scopes": ["operator.admin"]}, root=root)
                mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
                with mock.patch.object(
                    mod,
                    "run_openai_compatible_worker_probe",
                    return_value={
                        "status": "pass",
                        "kind": "openai_compatible_worker_probe",
                        "return_code": 0,
                    },
                ) as probe:
                    armed = mod.worker_transport_check(
                        {"preset": "openai_compatible", "execute": True, "operator_scopes": ["operator.admin"]},
                        root=root,
                    )
            finally:
                if old_key is None:
                    os.environ.pop("A9_LLM_WORKER_API_KEY", None)
                else:
                    os.environ["A9_LLM_WORKER_API_KEY"] = old_key
                if old_model is None:
                    os.environ.pop("A9_LLM_WORKER_MODEL", None)
                else:
                    os.environ["A9_LLM_WORKER_MODEL"] = old_model

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["gate"]["reason"], "phone_control_disarmed")
        self.assertEqual(armed["status"], "pass")
        self.assertEqual(armed["gate"]["reason"], "phone_control_armed")
        self.assertEqual(armed["probe"]["return_code"], 0)
        probe.assert_called_once()

    def test_openai_compatible_worker_probe_timeout_returns_structured_failure(self):
        mod = load_control_api()
        with mock.patch.object(
            mod.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["worker"], timeout=1, output="started", stderr="slow"),
        ):
            result = mod.run_openai_compatible_worker_probe(
                {
                    "model": "test-model",
                    "base_url": "http://127.0.0.1:9999/v1",
                    "api_key_env": "A9_LLM_WORKER_API_KEY",
                    "timeout_seconds": 1,
                }
            )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["return_code"], -1)
        self.assertIn("timed out", result["error"])
        self.assertFalse(result["final_path_present"])

    def test_api_worker_transport_check_post_route_calls_handler(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None, "request": None}
        original_check = mod.worker_transport_check
        body = b'{"preset":"openai_compatible"}'

        class DummyWorkerTransportCheckPostHandler:
            path = "/api/worker/transport-check"
            headers = {"Content-Length": str(len(body))}
            rfile = io.BytesIO(body)

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        def fake_check(payload):
            captured["request"] = payload
            return {"status": "ready", "kind": "worker_transport_check"}

        try:
            mod.worker_transport_check = fake_check
            mod.ControlHandler.do_POST(DummyWorkerTransportCheckPostHandler())
        finally:
            mod.worker_transport_check = original_check

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "worker_transport_check")
        self.assertEqual(captured["request"]["preset"], "openai_compatible")

    def test_api_worker_transport_config_routes_call_handlers(self):
        mod = load_control_api()
        get_capture = {"status": None, "payload": None}
        post_capture = {"status": None, "payload": None, "request": None}
        original_state = mod.llm_worker_config_state
        original_update = mod.update_llm_worker_config
        body = b'{"model":"test-model"}'

        class DummyWorkerTransportConfigGetHandler:
            path = "/api/worker/transport-config"
            headers = {}

            def write_json(self, status, payload):
                get_capture["status"] = status
                get_capture["payload"] = payload

        class DummyWorkerTransportConfigPostHandler:
            path = "/api/worker/transport-config"
            headers = {"Content-Length": str(len(body))}
            rfile = io.BytesIO(body)

            def write_json(self, status, payload):
                post_capture["status"] = status
                post_capture["payload"] = payload

        def fake_update(payload):
            post_capture["request"] = payload
            return {"status": "applied", "kind": "llm_worker_config_update"}

        try:
            mod.llm_worker_config_state = lambda: {"status": "ok", "kind": "llm_worker_config"}
            mod.update_llm_worker_config = fake_update
            mod.ControlHandler.do_GET(DummyWorkerTransportConfigGetHandler())
            mod.ControlHandler.do_POST(DummyWorkerTransportConfigPostHandler())
        finally:
            mod.llm_worker_config_state = original_state
            mod.update_llm_worker_config = original_update

        self.assertEqual(get_capture["status"], 200)
        self.assertEqual(get_capture["payload"]["kind"], "llm_worker_config")
        self.assertEqual(post_capture["status"], 200)
        self.assertEqual(post_capture["payload"]["kind"], "llm_worker_config_update")
        self.assertEqual(post_capture["request"]["model"], "test-model")

    def test_api_monitor_control_endpoint_returns_payload(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}
        original_control = mod.monitor_control

        class DummyMonitorControlGetHandler:
            path = "/api/monitor/control"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

            def write_sse(self, status, payload):
                raise AssertionError("write_sse should not be used for monitor control")

        try:
            mod.monitor_control = lambda: {"status": "ok", "kind": "monitor_control"}
            mod.ControlHandler.do_GET(DummyMonitorControlGetHandler())
        finally:
            mod.monitor_control = original_control

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "monitor_control")

    def test_monitor_intervention_requires_arm_and_records_async_audit(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit_calls = []
            original_monitor_status = mod.monitor_status
            original_audit = mod.enqueue_monitor_intervention_audit
            original_supervisor = mod.supervisor
            original_publish = mod.publish_monitor_intervention_redis
            try:
                mod.monitor_status = lambda root=root: {
                    "status": "ok",
                    "kind": "monitor_status",
                    "next_action": "repair",
                    "latest_run": {"task_id": "task-1", "run_id": "run-1", "status": "needs-repair"},
                    "command_envelope": {"expected_revision": 7, "idempotency_key": "task-1:7"},
                    "evidence_refs": {"summary_path": "/tmp/run-1/summary.json"},
                    "failed_checks_count": 1,
                    "changed_files": ["scripts/a9_control_api.py"],
                }
                mod.enqueue_monitor_intervention_audit = lambda event, *, root: audit_calls.append((event, root))
                mod.publish_monitor_intervention_redis = lambda event: {
                    "status": "ok",
                    "stream": "a9:monitor:interventions",
                    "stream_id": "1-0",
                }

                class FakeSupervisor:
                    @staticmethod
                    def apply_monitor_intervention_effect(command):
                        return {
                            "status": "applied",
                            "mode": "queue_task",
                            "action": command["action"],
                            "queued_task_path": "/tmp/a9/task.md",
                        }

                mod.supervisor = lambda: FakeSupervisor

                blocked = mod.monitor_intervention(
                    {
                        "action": "repair",
                        "reason": "failed check needs deterministic repair",
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
                mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
                result = mod.monitor_intervention(
                    {
                        "action": "repair",
                        "reason": "failed check needs deterministic repair",
                        "operator_scopes": ["operator.admin"],
                        "evidence_refs": ["local:operator-note"],
                    },
                    root=root,
                )
            finally:
                mod.monitor_status = original_monitor_status
                mod.enqueue_monitor_intervention_audit = original_audit
                mod.supervisor = original_supervisor
                mod.publish_monitor_intervention_redis = original_publish

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["gate"]["reason"], "phone_control_disarmed")
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(result["schema"], "a9.monitor_intervention.v1")
        self.assertEqual(result["command"], "monitor.intervention")
        self.assertTrue(result["audit_async"])
        self.assertEqual(result["command_envelope"]["task_id"], "task-1")
        self.assertEqual(result["command_envelope"]["expected_revision"], 7)
        self.assertIn("local:operator-note", result["command_envelope"]["evidence_refs"])
        self.assertIn("/tmp/run-1/summary.json", result["command_envelope"]["evidence_refs"])
        self.assertEqual(len(audit_calls), 2)
        self.assertEqual(audit_calls[0][0]["status"], "blocked")
        self.assertEqual(audit_calls[1][0]["status"], "recorded")
        self.assertEqual(audit_calls[1][0]["execution_effect"]["mode"], "queue_task")
        self.assertEqual(audit_calls[1][0]["redis_mirror"]["stream_id"], "1-0")
        self.assertEqual(result["redis_mirror"]["status"], "ok")

    def test_publish_monitor_intervention_redis_xadds_compact_event(self):
        mod = load_control_api()
        calls = []

        class FakeProc:
            def __init__(self, stdout: str = "OK\n", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            calls.append(args)
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args[:2] == ["XADD", "a9:monitor:interventions"]:
                return FakeProc("1740000010-0\n")
            return FakeProc()

        original_redis = mod.redis_cli
        try:
            mod.redis_cli = fake_redis
            result = mod.publish_monitor_intervention_redis(
                {
                    "kind": "monitor_intervention_audit",
                    "schema": "a9.monitor_intervention.v1",
                    "intervention_id": "monitor-1",
                    "action": "pause",
                    "status": "recorded",
                    "task_id": "task-1",
                    "run_id": "run-1",
                    "actor": "mobile-operator",
                    "gate_allowed": True,
                    "execution_effect": {"mode": "runtime_state"},
                    "at": "2026-06-04T00:00:00+00:00",
                }
            )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["stream"], "a9:monitor:interventions")
        self.assertEqual(result["stream_id"], "1740000010-0")
        xadd = next(call for call in calls if call[:2] == ["XADD", "a9:monitor:interventions"])
        self.assertIn("intervention_id", xadd)
        self.assertIn("monitor-1", xadd)
        self.assertIn("effect_mode", xadd)
        self.assertIn("runtime_state", xadd)
        self.assertIn("payload_json", xadd)

    def test_publish_monitor_intervention_redis_skips_when_unavailable(self):
        mod = load_control_api()
        original_available = mod.redis_available
        try:
            mod.redis_available = lambda: False
            result = mod.publish_monitor_intervention_redis({"intervention_id": "monitor-1"})
        finally:
            mod.redis_available = original_available

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "redis_unavailable")
        self.assertEqual(result["stream"], "a9:monitor:interventions")

    def test_read_monitor_intervention_events_uses_monitor_stream(self):
        mod = load_control_api()
        calls = []

        class FakeProc:
            returncode = 0
            stdout = "1740000010-0\nintervention_id\nmonitor-1\naction\npause\n"

        original_redis = mod.redis_cli
        try:
            def fake_redis(args, *, timeout=2):
                calls.append(args)
                return FakeProc()

            mod.redis_cli = fake_redis
            payload = mod.read_monitor_intervention_events("1740000009-0", limit=2)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["kind"], "monitor_intervention_events")
        self.assertEqual(payload["stream"], "a9:monitor:interventions")
        self.assertEqual(payload["events"][0]["fields"]["intervention_id"], "monitor-1")
        self.assertEqual(calls[0][:3], ["--raw", "XRANGE", "a9:monitor:interventions"])

    def test_api_monitor_intervention_events_get_endpoint_returns_json(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}
        calls = []
        original_reader = mod.read_monitor_intervention_events

        class DummyMonitorInterventionEventsGetHandler:
            path = "/api/monitor/interventions/events?limit=3&last_id=1740000001-0"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

            def write_sse(self, status, payload):
                raise AssertionError("write_sse should not be used without format=sse")

        try:
            def fake_reader(last_id, limit=100):
                calls.append((last_id, limit))
                return {
                    "status": "ok",
                    "kind": "monitor_intervention_events",
                    "stream": "a9:monitor:interventions",
                    "events": [{"id": "1740000002-0", "fields": {"action": "pause"}}],
                    "next_last_id": "1740000002-0",
                }

            mod.read_monitor_intervention_events = fake_reader
            mod.ControlHandler.do_GET(DummyMonitorInterventionEventsGetHandler())
        finally:
            mod.read_monitor_intervention_events = original_reader

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "monitor_intervention_events")
        self.assertEqual(calls, [("1740000001-0", 3)])

    def test_api_monitor_intervention_events_sse_uses_last_event_id_header(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None, "content_type": None}
        calls = []
        original_reader = mod.read_monitor_intervention_events

        class DummyMonitorInterventionEventsSSEGetHandler:
            path = "/api/monitor/interventions/events?format=sse&limit=2"
            headers = {"Last-Event-ID": "1740000010-0"}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

            def write_sse(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload
                captured["content_type"] = "text/event-stream"

        try:
            def fake_reader(last_id, limit=100):
                calls.append((last_id, limit))
                return {
                    "status": "ok",
                    "kind": "monitor_intervention_events",
                    "stream": "a9:monitor:interventions",
                    "events": [],
                    "next_last_id": last_id,
                }

            mod.read_monitor_intervention_events = fake_reader
            mod.ControlHandler.do_GET(DummyMonitorInterventionEventsSSEGetHandler())
        finally:
            mod.read_monitor_intervention_events = original_reader

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["content_type"], "text/event-stream")
        self.assertEqual(calls, [("1740000010-0", 2)])

    def test_api_monitor_intervention_post_route_calls_handler(self):
        mod = load_control_api()
        original_monitor_intervention = mod.monitor_intervention
        post_body = json.dumps(
            {
                "action": "route_to_debate",
                "reason": "requirements conflict",
                "operator_scopes": ["operator.admin"],
            }
        ).encode("utf-8")
        captured = {"status": None, "payload": None, "called_payload": None}
        try:
            def fake_monitor_intervention(payload):
                captured["called_payload"] = payload
                return {"status": "recorded", "command": "monitor.intervention", "action": payload["action"]}

            mod.monitor_intervention = fake_monitor_intervention

            class DummyMonitorInterventionPostHandler:
                path = "/api/monitor/intervention"
                headers = {"Content-Length": str(len(post_body))}
                rfile = io.BytesIO(post_body)

                def write_json(self, status, payload):
                    captured["status"] = status
                    captured["payload"] = payload

            mod.ControlHandler.do_POST(DummyMonitorInterventionPostHandler())
        finally:
            mod.monitor_intervention = original_monitor_intervention

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["command"], "monitor.intervention")
        self.assertEqual(captured["called_payload"]["action"], "route_to_debate")

    def test_monitor_intervention_examples_use_latest_status_context(self):
        mod = load_control_api()
        original_monitor_status = mod.monitor_status
        try:
            mod.monitor_status = lambda root=mod.ROOT: {
                "status": "ok",
                "kind": "monitor_status",
                "latest_run": {"task_id": "task-1", "run_id": "run-1"},
                "evidence_refs": {"summary_path": "/tmp/run-1/summary.json"},
            }
            payload = mod.monitor_intervention_examples()
        finally:
            mod.monitor_status = original_monitor_status

        self.assertEqual(payload["schema"], "a9.monitor_intervention_examples.v1")
        self.assertEqual(payload["endpoint"], "/api/monitor/intervention")
        self.assertEqual(payload["requires"]["phone_control_command"], "monitor.intervention")
        self.assertEqual(payload["examples"]["repair"]["task_id"], "task-1")
        self.assertIn("/tmp/run-1/summary.json", payload["examples"]["repair"]["evidence_refs"])
        self.assertEqual(payload["examples"]["approve"]["flow_expected_revision"], 1)

    def test_api_monitor_intervention_examples_endpoint_returns_payload(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}
        original_examples = mod.monitor_intervention_examples

        class DummyMonitorInterventionExamplesGetHandler:
            path = "/api/monitor/intervention/examples"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

            def write_sse(self, status, payload):
                raise AssertionError("write_sse should not be used for monitor intervention examples")

        try:
            mod.monitor_intervention_examples = lambda: {
                "status": "ok",
                "kind": "monitor_intervention_examples",
                "examples": {"pause": {"action": "pause"}},
            }
            mod.ControlHandler.do_GET(DummyMonitorInterventionExamplesGetHandler())
        finally:
            mod.monitor_intervention_examples = original_examples

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "monitor_intervention_examples")
        self.assertEqual(captured["payload"]["examples"]["pause"]["action"], "pause")

    def test_monitor_intervention_cli_payload_maps_flags(self):
        mod = load_control_api()
        args = argparse.Namespace(
            action="approve",
            reason="operator approved",
            task_id="task-1",
            run_id="run-1",
            actor="cli-operator",
            evidence_ref=["summary.json", "patch.diff"],
            flow_id="flow-1",
            flow_expected_revision=3,
            flow_expected_last_seq=7,
            flow_sequence=8,
            evidence_id="checkpoint-1",
            idempotency_key="approve:flow-1:3",
        )

        payload = mod.monitor_intervention_cli_payload(args)

        self.assertEqual(payload["action"], "approve")
        self.assertEqual(payload["operator_scopes"], ["operator.admin"])
        self.assertEqual(payload["flow_id"], "flow-1")
        self.assertEqual(payload["flow_expected_revision"], 3)
        self.assertEqual(payload["evidence_refs"], ["summary.json", "patch.diff"])
        self.assertEqual(payload["idempotency_key"], "approve:flow-1:3")

    def test_monitor_intervention_cli_calls_handler_and_returns_zero_for_recorded(self):
        mod = load_control_api()
        captured = {}
        original_handler = mod.monitor_intervention
        original_arm = mod.phone_control_arm
        try:
            def fake_arm(payload):
                captured["arm"] = payload
                return {"status": "armed"}

            def fake_monitor_intervention(payload):
                captured["payload"] = payload
                return {"status": "recorded", "kind": "monitor_intervention", "action": payload["action"]}

            mod.phone_control_arm = fake_arm
            mod.monitor_intervention = fake_monitor_intervention
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = mod.main(
                    [
                        "monitor-intervention",
                        "repair",
                        "--reason",
                        "fix failed check",
                        "--task-id",
                        "task-1",
                        "--run-id",
                        "run-1",
                        "--evidence-ref",
                        "summary.json",
                        "--arm-duration",
                        "30s",
                    ]
                )
            output = json.loads(buffer.getvalue())
        finally:
            mod.monitor_intervention = original_handler
            mod.phone_control_arm = original_arm

        self.assertEqual(code, 0)
        self.assertEqual(captured["arm"]["group"], "runtime")
        self.assertEqual(captured["payload"]["action"], "repair")
        self.assertEqual(captured["payload"]["task_id"], "task-1")
        self.assertEqual(captured["payload"]["evidence_refs"], ["summary.json"])
        self.assertEqual(output["status"], "recorded")

    def test_monitor_intervention_cli_examples_prints_examples(self):
        mod = load_control_api()
        original_examples = mod.monitor_intervention_examples
        try:
            mod.monitor_intervention_examples = lambda: {
                "status": "ok",
                "kind": "monitor_intervention_examples",
                "examples": {"pause": {"action": "pause"}},
            }
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = mod.main(["monitor-intervention", "--examples"])
            output = json.loads(buffer.getvalue())
        finally:
            mod.monitor_intervention_examples = original_examples

        self.assertEqual(code, 0)
        self.assertEqual(output["kind"], "monitor_intervention_examples")
        self.assertEqual(output["examples"]["pause"]["action"], "pause")

    def test_worker_transport_check_cli_arms_and_calls_handler(self):
        mod = load_control_api()
        captured = {}
        original_arm = mod.phone_control_arm
        original_check = mod.worker_transport_check
        try:
            def fake_arm(payload):
                captured["arm"] = payload
                return {"status": "armed"}

            def fake_check(payload):
                captured["payload"] = payload
                return {"status": "pass", "kind": "worker_transport_check"}

            mod.phone_control_arm = fake_arm
            mod.worker_transport_check = fake_check
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = mod.main(
                    [
                        "worker-transport-check",
                        "--execute",
                        "--arm-duration",
                        "30s",
                        "--model",
                        "test-model",
                        "--base-url",
                        "http://127.0.0.1:8000/v1",
                    ]
                )
            output = json.loads(buffer.getvalue())
        finally:
            mod.phone_control_arm = original_arm
            mod.worker_transport_check = original_check

        self.assertEqual(code, 0)
        self.assertEqual(captured["arm"]["group"], "runtime")
        self.assertTrue(captured["payload"]["execute"])
        self.assertEqual(captured["payload"]["model"], "test-model")
        self.assertEqual(captured["payload"]["base_url"], "http://127.0.0.1:8000/v1")
        self.assertEqual(output["status"], "pass")

    def test_worker_transport_policy_cli_arms_and_calls_handler(self):
        mod = load_control_api()
        captured = {}
        original_arm = mod.phone_control_arm
        original_policy = mod.update_worker_transport_policy
        try:
            def fake_arm(payload):
                captured["arm"] = payload
                return {"status": "armed"}

            def fake_policy(payload):
                captured["payload"] = payload
                return {"status": "applied", "kind": "worker_transport_policy_update"}

            mod.phone_control_arm = fake_arm
            mod.update_worker_transport_policy = fake_policy
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = mod.main(
                    [
                        "worker-transport-policy",
                        "--preset",
                        "openai_compatible",
                        "--require-probe-pass",
                        "--reason",
                        "switch after probe",
                        "--arm-duration",
                        "30s",
                    ]
                )
            output = json.loads(buffer.getvalue())
        finally:
            mod.phone_control_arm = original_arm
            mod.update_worker_transport_policy = original_policy

        self.assertEqual(code, 0)
        self.assertEqual(captured["arm"]["group"], "runtime")
        self.assertEqual(captured["payload"]["preset"], "openai_compatible")
        self.assertTrue(captured["payload"]["require_probe_pass"])
        self.assertEqual(captured["payload"]["reason"], "switch after probe")
        self.assertEqual(output["status"], "applied")

    def test_worker_transport_config_cli_arms_and_calls_handler(self):
        mod = load_control_api()
        captured = {}
        original_arm = mod.phone_control_arm
        original_update = mod.update_llm_worker_config
        try:
            def fake_arm(payload):
                captured["arm"] = payload
                return {"status": "armed"}

            def fake_update(payload):
                captured["payload"] = payload
                return {"status": "applied", "kind": "llm_worker_config_update"}

            mod.phone_control_arm = fake_arm
            mod.update_llm_worker_config = fake_update
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = mod.main(
                    [
                        "worker-transport-config",
                        "--model",
                        "test-model",
                        "--base-url",
                        "http://127.0.0.1:8000/v1",
                        "--api-key-env",
                        "A9_TEST_KEY",
                        "--timeout-seconds",
                        "9",
                        "--reason",
                        "configure gateway",
                        "--arm-duration",
                        "30s",
                    ]
                )
            output = json.loads(buffer.getvalue())
        finally:
            mod.phone_control_arm = original_arm
            mod.update_llm_worker_config = original_update

        self.assertEqual(code, 0)
        self.assertEqual(captured["arm"]["group"], "runtime")
        self.assertEqual(captured["payload"]["model"], "test-model")
        self.assertEqual(captured["payload"]["base_url"], "http://127.0.0.1:8000/v1")
        self.assertEqual(captured["payload"]["api_key_env"], "A9_TEST_KEY")
        self.assertEqual(captured["payload"]["timeout_seconds"], 9)
        self.assertEqual(output["status"], "applied")

    def test_runtime_run_one_with_transport_cli_arms_and_calls_handler(self):
        mod = load_control_api()
        captured = {}
        original_arm = mod.phone_control_arm
        original_handler = mod.runtime_run_one_with_transport
        try:
            def fake_arm(payload):
                captured["arm"] = payload
                return {"status": "armed"}

            def fake_handler(payload):
                captured["payload"] = payload
                return {"status": "run-complete", "kind": "runtime_run_one_with_transport"}

            mod.phone_control_arm = fake_arm
            mod.runtime_run_one_with_transport = fake_handler
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = mod.main(
                    [
                        "runtime-run-one-with-transport",
                        "--preset",
                        "openai_compatible",
                        "--require-probe-pass",
                        "--model",
                        "test-model",
                        "--base-url",
                        "http://127.0.0.1:8000/v1",
                        "--api-key-env",
                        "A9_TEST_KEY",
                        "--timeout-seconds",
                        "9",
                        "--reason",
                        "temporary gateway smoke",
                        "--auto-next",
                        "--arm-duration",
                        "30s",
                    ]
                )
            output = json.loads(buffer.getvalue())
        finally:
            mod.phone_control_arm = original_arm
            mod.runtime_run_one_with_transport = original_handler

        self.assertEqual(code, 0)
        self.assertEqual(captured["arm"]["group"], "runtime")
        self.assertEqual(captured["payload"]["operator_scopes"], ["operator.admin"])
        self.assertTrue(captured["payload"]["auto_next"])
        self.assertEqual(captured["payload"]["transport"]["preset"], "openai_compatible")
        self.assertTrue(captured["payload"]["transport"]["require_probe_pass"])
        self.assertEqual(captured["payload"]["transport"]["model"], "test-model")
        self.assertEqual(captured["payload"]["transport"]["base_url"], "http://127.0.0.1:8000/v1")
        self.assertEqual(captured["payload"]["transport"]["api_key_env"], "A9_TEST_KEY")
        self.assertEqual(captured["payload"]["transport"]["timeout_seconds"], 9)
        self.assertEqual(captured["payload"]["transport"]["reason"], "temporary gateway smoke")
        self.assertEqual(output["status"], "run-complete")

    def test_gateway_reconnect_decision_get_endpoint_returns_latest_event(self):
        mod = load_control_api()

        captured = {"status": None, "payload": None}

        class DummyReconnectDecisionGetHandler:
            path = "/api/gateway/reconnect-decision"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        original_latest = mod.latest_gateway_reconnect_decision_event
        try:
            mod.latest_gateway_reconnect_decision_event = lambda: {
                "status": "ok",
                "kind": "gateway_reconnect_decision",
                "reset_on_success": True,
            }
            mod.ControlHandler.do_GET(DummyReconnectDecisionGetHandler())
        finally:
            mod.latest_gateway_reconnect_decision_event = original_latest

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "gateway_reconnect_decision")
        self.assertTrue(captured["payload"]["reset_on_success"])

    def test_gateway_health_refresh_get_endpoint_returns_refresh_payload(self):
        mod = load_control_api()

        captured = {"status": None, "payload": None}

        class DummyGatewayHealthRefreshHandler:
            path = "/api/gateway/health-refresh"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        original_refresh = mod.gateway_health_refresh
        try:
            mod.gateway_health_refresh = lambda: {"status": "ok", "kind": "gateway_health_refresh"}
            mod.ControlHandler.do_GET(DummyGatewayHealthRefreshHandler())
        finally:
            mod.gateway_health_refresh = original_refresh

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "gateway_health_refresh")

    def test_gateway_reconnect_governance_get_endpoint_returns_status(self):
        mod = load_control_api()

        captured = {"status": None, "payload": None}

        class DummyGatewayReconnectGovernanceHandler:
            path = "/api/gateway/reconnect-governance"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        original_governance = mod.gateway_reconnect_governance
        try:
            mod.gateway_reconnect_governance = lambda: {"status": "ok", "kind": "gateway_reconnect_governance"}
            mod.ControlHandler.do_GET(DummyGatewayReconnectGovernanceHandler())
        finally:
            mod.gateway_reconnect_governance = original_governance

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "gateway_reconnect_governance")
        self.assertEqual(captured["payload"]["status"], "ok")

    def test_gateway_reconnect_governance_get_endpoint_includes_schema_and_state(self):
        mod = load_control_api()

        captured = {"status": None, "payload": None}

        class DummyGatewayReconnectGovernanceHandler:
            path = "/api/gateway/reconnect-governance"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        governance_payload = {
            "kind": "gateway_reconnect_governance",
            "schema": "a9.gateway_reconnect_governance.v1",
            "status": "ok",
            "state": {
                "contract_status": "ok",
                "reconnect_event_status": "ok",
                "runtime_action": "continue",
            },
            "runtime": {
                "governance_decision": {
                    "status": "ok",
                    "action": "continue",
                    "contract_action": "continue",
                    "reconnect_action": "continue",
                    "reason": None,
                }
            },
        }

        original_governance = mod.gateway_reconnect_governance
        try:
            mod.gateway_reconnect_governance = lambda: governance_payload
            mod.ControlHandler.do_GET(DummyGatewayReconnectGovernanceHandler())
        finally:
            mod.gateway_reconnect_governance = original_governance

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["schema"], "a9.gateway_reconnect_governance.v1")
        self.assertEqual(captured["payload"]["state"]["contract_status"], "ok")
        self.assertEqual(captured["payload"]["state"]["reconnect_event_status"], "ok")
        self.assertEqual(captured["payload"]["state"]["runtime_action"], "continue")
        self.assertEqual(captured["payload"]["runtime"]["governance_decision"]["action"], "continue")

    def test_gateway_reconnect_governance_get_endpoint_contract_shape(self):
        mod = load_control_api()

        captured = {"status": None, "payload": None}

        class DummyGatewayReconnectGovernanceHandler:
            path = "/api/gateway/reconnect-governance"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        governance_payload = {
            "kind": "gateway_reconnect_governance",
            "schema": "a9.gateway_reconnect_governance.v1",
            "status": "fail",
            "state": {
                "contract_status": "fail",
                "reconnect_event_status": "missing",
                "runtime_action": "block",
            },
            "contract": {
                "kind": "gateway_transport_contract",
                "status": "fail",
                "reason": "gateway_contract_failed",
                "runtime_evidence": {"status": "fail", "action": "block", "reason": "gateway_contract_failed"},
            },
            "reconnect": {
                "latest_event": {
                    "kind": "gateway_reconnect_decision",
                    "status": "missing",
                    "reason": "no_gateway_reconnect_decision_event",
                },
            },
            "runtime": {
                "governance_decision": {
                    "status": "fail",
                    "action": "block",
                    "contract_action": "block",
                    "reconnect_action": "observe",
                    "reason": "gateway_reconnect_governance_failure",
                }
            },
        }

        original_governance = mod.gateway_reconnect_governance
        try:
            mod.gateway_reconnect_governance = lambda: governance_payload
            mod.ControlHandler.do_GET(DummyGatewayReconnectGovernanceHandler())
        finally:
            mod.gateway_reconnect_governance = original_governance

        payload = captured["payload"]
        self.assertEqual(captured["status"], 200)
        self.assertEqual(payload["kind"], "gateway_reconnect_governance")
        self.assertEqual(payload["schema"], "a9.gateway_reconnect_governance.v1")
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["state"], governance_payload["state"])
        self.assertEqual(payload["runtime"]["governance_decision"]["action"], "block")
        self.assertEqual(payload["runtime"]["governance_decision"]["status"], "fail")
        self.assertEqual(payload["runtime"]["governance_decision"]["reason"], "gateway_reconnect_governance_failure")
        self.assertIn("contract_action", payload["runtime"]["governance_decision"])
        self.assertIn("reconnect_action", payload["runtime"]["governance_decision"])

    def test_gateway_reconnect_governance_function_maps_failures_to_block(self):
        mod = load_control_api()
        calls = []

        original_contract = mod.gateway_transport_contract
        original_reconnect_event = mod.latest_gateway_reconnect_decision_event

        try:
            def fake_contract(root=None, *, emit_event: bool = False):
                calls.append(emit_event)
                return {"status": "fail", "kind": "gateway_transport_contract", "runtime_evidence": {"action": "block"}}

            mod.gateway_transport_contract = fake_contract
            mod.latest_gateway_reconnect_decision_event = lambda: {"status": "ok", "kind": "gateway_reconnect_decision", "action": "continue"}
            result = mod.gateway_reconnect_governance()
        finally:
            mod.gateway_transport_contract = original_contract
            mod.latest_gateway_reconnect_decision_event = original_reconnect_event

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["runtime"]["governance_decision"]["action"], "block")
        self.assertTrue(calls)

    def test_gateway_reconnect_diagnostic_get_endpoint_requires_success_flag(self):
        mod = load_control_api()

        captured = {"status": None, "payload": None, "success": None}

        class DummyGatewayReconnectDiagnosticHandler:
            path = "/api/gateway/reconnect-diagnostic?success=1"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        original_diagnostic = mod.gateway_reconnect_diagnostic
        try:
            def fake_diagnostic(*, success: bool = False):
                captured["success"] = success
                return {"status": "ok", "kind": "gateway_reconnect_diagnostic"}

            mod.gateway_reconnect_diagnostic = fake_diagnostic
            mod.ControlHandler.do_GET(DummyGatewayReconnectDiagnosticHandler())
        finally:
            mod.gateway_reconnect_diagnostic = original_diagnostic

        self.assertEqual(captured["status"], 200)
        self.assertTrue(captured["success"])
        self.assertEqual(captured["payload"]["kind"], "gateway_reconnect_diagnostic")

    def test_api_events_get_endpoint_returns_json_state_payload(self):
        mod = load_control_api()

        captured = {"status": None, "payload": None}
        calls = []

        class DummyEventsGetHandler:
            path = "/api/events?limit=3&last_id=1740000001-0"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

            def write_sse(self, status, payload):
                raise AssertionError("write_sse should not be used for /api/events without format=sse")

        original_read_events = mod.read_events
        try:
            def fake_read_events(last_id, limit=100):
                calls.append((last_id, limit))
                return {
                    "status": "ok",
                    "stream": "a9:events",
                    "count": 1,
                    "requested_count": 3,
                    "last_id": last_id,
                    "next_last_id": "1740000002-0",
                    "events": [{"id": "1740000002-0", "fields": {"type": "task_started"}}],
                }

            mod.read_events = fake_read_events
            mod.ControlHandler.do_GET(DummyEventsGetHandler())
        finally:
            mod.read_events = original_read_events

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["status"], "ok")
        self.assertEqual(captured["payload"]["stream"], "a9:events")
        self.assertEqual(captured["payload"]["count"], 1)
        self.assertEqual(captured["payload"]["events"][0]["fields"]["type"], "task_started")
        self.assertEqual(calls, [("1740000001-0", 3)])

    def test_api_events_get_endpoint_uses_last_event_header_for_sse_format(self):
        mod = load_control_api()

        captured = {"status": None, "payload": None, "content_type": None}
        calls = []

        class DummyEventsSSEGetHandler:
            path = "/api/events?format=sse&limit=2"
            headers = {"Last-Event-ID": "1740000010-0"}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

            def write_sse(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload
                captured["content_type"] = "text/event-stream"

        original_read_events = mod.read_events
        try:
            def fake_read_events(last_id, limit=100):
                calls.append((last_id, limit))
                return {
                    "status": "ok",
                    "stream": "a9:events",
                    "count": 0,
                    "requested_count": 2,
                    "last_id": last_id,
                    "next_last_id": last_id,
                    "events": [],
                }

            mod.read_events = fake_read_events
            mod.ControlHandler.do_GET(DummyEventsSSEGetHandler())
        finally:
            mod.read_events = original_read_events

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["content_type"], "text/event-stream")
        self.assertEqual(calls, [("1740000010-0", 2)])

    def test_node_status_aggregates_latest_tmux_action_from_evidence(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@node-a"}, root=root)
            mod.heartbeat_node({"node_id": "node/a", "status": "online"}, root=root)

            mod.write_node_evidence(
                "tmux-plan",
                "node/a",
                {"status": "planned", "transport": "tailscale+ssh+tmux"},
                root=root,
            )
            tmux_status = {
                "status": "exists",
                "target": "root@node-a",
                "session": "a9-main",
                "tmux_action": "continue",
                "tmux_action_reason": "tmux_session_exists",
                "reason": "tmux_session_exists",
            }
            evidence_path = mod.write_node_evidence("tmux-status", "node/a", tmux_status, root=root)

            status = mod.node_status(root)

        node = status["nodes"][0]
        self.assertEqual(node["tmux_action"], "continue")
        self.assertEqual(node["tmux_action_reason"], "tmux_session_exists")
        self.assertEqual(node["tmux_status"], "exists")
        self.assertEqual(node["tmux_evidence_path"], str(evidence_path))

    def test_node_status_picks_filename_latest_tmux_evidence_when_mtime_ties(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@node-a"}, root=root)
            mod.heartbeat_node({"node_id": "node/a", "status": "online"}, root=root)

            older_path = mod.write_node_evidence(
                "tmux-status",
                "node/a",
                {
                    "status": "missing",
                    "tmux_action": "repair",
                    "tmux_action_reason": "tmux_session_missing",
                    "reason": "tmux_session_missing",
                },
                root=root,
            )
            newer_path = mod.write_node_evidence(
                "tmux-ensure",
                "node/a",
                {
                    "status": "exists",
                    "tmux_action": "continue",
                    "tmux_action_reason": "tmux_ensure_ok",
                    "reason": "tmux_ensure_ok",
                },
                root=root,
            )

            tied_mtime = older_path.stat().st_mtime
            os.utime(newer_path, (tied_mtime, tied_mtime))
            os.utime(older_path, (tied_mtime, tied_mtime))

            status = mod.node_status(root)

        node = status["nodes"][0]
        self.assertEqual(node["tmux_action"], "continue")
        self.assertEqual(node["tmux_action_reason"], "tmux_ensure_ok")
        self.assertEqual(node["tmux_status"], "exists")
        self.assertEqual(node["tmux_evidence_path"], str(newer_path))

    def test_node_status_aggregates_latest_probe_evidence(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@node-a"}, root=root)
            mod.heartbeat_node({"node_id": "node/a", "status": "online"}, root=root)

            mod.write_node_evidence(
                "probe-timeout",
                "node/a",
                {
                    "status": "failed",
                    "return_code": 124,
                    "timed_out": True,
                    "probe_action": "retry",
                    "probe_action_reason": "timeout",
                    "checked_at": "2026-05-27T00:00:00Z",
                },
                root=root,
            )
            latest_evidence_path = mod.write_node_evidence(
                "probe",
                "node/a",
                {
                    "status": "ok",
                    "return_code": 0,
                    "timed_out": False,
                    "probe_action": "continue",
                    "probe_action_reason": "probe_ok",
                    "checked_at": "2026-05-28T00:00:00Z",
                    "connection_summary": {
                        "connection_state": "needs_repair",
                        "action": "repair",
                        "action_reason": "missing_required_tools",
                        "retry_delay_ms": 0,
                    },
                },
                root=root,
            )

            status = mod.node_status(root)

        node = status["nodes"][0]
        self.assertEqual(node["probe_status"], "ok")
        self.assertEqual(node["probe_action"], "continue")
        self.assertEqual(node["probe_action_reason"], "probe_ok")
        self.assertEqual(node["probe_return_code"], 0)
        self.assertFalse(node["probe_timed_out"])
        self.assertEqual(node["probe_checked_at"], "2026-05-28T00:00:00Z")
        self.assertEqual(node["probe_evidence_path"], str(latest_evidence_path))
        self.assertEqual(node["connection_state"], "needs_repair")
        self.assertEqual(node["action"], "repair")
        self.assertEqual(node["action_reason"], "missing_required_tools")
        self.assertEqual(node["retry_delay_ms"], 0)

    def test_latest_probe_evidence_for_node_includes_connection_summary_fields(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@node-a"}, root=root)

            latest_evidence_path = mod.write_node_evidence(
                "probe",
                "node/a",
                {
                    "status": "ok",
                    "return_code": 0,
                    "timed_out": False,
                    "probe_action": "continue",
                    "probe_action_reason": "probe_ok",
                    "checked_at": "2026-05-28T00:00:00Z",
                    "connection_summary": {
                        "connection_state": "needs_repair",
                        "action": "repair",
                        "action_reason": "missing_required_tools",
                        "retry_delay_ms": 0,
                    },
                },
                root=root,
            )
            latest_probe = mod.latest_probe_evidence_for_node("node/a", root=root)

        self.assertEqual(latest_probe["probe_status"], "ok")
        self.assertEqual(latest_probe["probe_action"], "continue")
        self.assertEqual(latest_probe["connection_state"], "needs_repair")
        self.assertEqual(latest_probe["action"], "repair")
        self.assertEqual(latest_probe["action_reason"], "missing_required_tools")
        self.assertEqual(latest_probe["retry_delay_ms"], 0)
        self.assertEqual(latest_probe["probe_evidence_path"], str(latest_evidence_path))

    def test_node_status_aggregates_latest_heartbeat_start_evidence(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@node-a"}, root=root)
            mod.heartbeat_node({"node_id": "node/a", "status": "online"}, root=root)

            latest_evidence_path = mod.write_node_evidence(
                "heartbeat-tmux-start",
                "node/a",
                {
                    "status": "ok",
                    "return_code": 0,
                    "timed_out": False,
                    "heartbeat_action": "continue",
                    "heartbeat_action_reason": "heartbeat_tmux_started",
                    "executed_at": "2026-05-28T00:00:00Z",
                },
                root=root,
            )

            status = mod.node_status(root)

        node = status["nodes"][0]
        self.assertEqual(node["heartbeat_start_status"], "ok")
        self.assertEqual(node["heartbeat_start_action"], "continue")
        self.assertEqual(node["heartbeat_start_action_reason"], "heartbeat_tmux_started")
        self.assertEqual(node["heartbeat_start_return_code"], 0)
        self.assertFalse(node["heartbeat_start_timed_out"])
        self.assertEqual(node["heartbeat_start_executed_at"], "2026-05-28T00:00:00Z")
        self.assertEqual(node["heartbeat_start_evidence_path"], str(latest_evidence_path))

    def test_node_status_ignores_newer_malformed_probe_evidence(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@node-a"}, root=root)
            mod.heartbeat_node({"node_id": "node/a", "status": "online"}, root=root)

            invalid_evidence_path = mod.write_node_evidence(
                "probe",
                "node/a",
                {
                    "status": "failed",
                    "return_code": 1,
                    "timed_out": True,
                    "checked_at": "2026-05-28T00:00:10Z",
                },
                root=root,
            )
            valid_evidence_path = mod.write_node_evidence(
                "probe",
                "node/a",
                {
                    "status": "ok",
                    "return_code": 0,
                    "timed_out": False,
                    "probe_action": "continue",
                    "probe_action_reason": "probe_ok",
                    "checked_at": "2026-05-28T00:00:00Z",
                },
                root=root,
            )

            base_ts = datetime(2026, 5, 28, 0, 0, 0, tzinfo=timezone.utc).timestamp()
            os.utime(str(invalid_evidence_path), (base_ts + 10.0, base_ts + 10.0))
            os.utime(str(valid_evidence_path), (base_ts, base_ts))

            status = mod.node_status(root)

        node = status["nodes"][0]
        self.assertEqual(node["probe_status"], "ok")
        self.assertEqual(node["probe_action"], "continue")
        self.assertEqual(node["probe_action_reason"], "probe_ok")
        self.assertEqual(node["probe_return_code"], 0)
        self.assertFalse(node["probe_timed_out"])
        self.assertEqual(node["probe_checked_at"], "2026-05-28T00:00:00Z")
        self.assertEqual(node["probe_evidence_path"], str(valid_evidence_path))

    def test_node_status_ignores_newer_malformed_heartbeat_start_evidence(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@node-a"}, root=root)
            mod.heartbeat_node({"node_id": "node/a", "status": "online"}, root=root)

            invalid_evidence_path = mod.write_node_evidence(
                "heartbeat-tmux-start",
                "node/a",
                {
                    "status": "failed",
                    "return_code": 1,
                    "timed_out": True,
                    "executed_at": "2026-05-28T00:00:10Z",
                },
                root=root,
            )
            valid_evidence_path = mod.write_node_evidence(
                "heartbeat-tmux-start",
                "node/a",
                {
                    "status": "ok",
                    "return_code": 0,
                    "timed_out": False,
                    "heartbeat_action": "continue",
                    "heartbeat_action_reason": "heartbeat_tmux_started",
                    "executed_at": "2026-05-28T00:00:00Z",
                },
                root=root,
            )

            base_ts = datetime(2026, 5, 28, 0, 0, 0, tzinfo=timezone.utc).timestamp()
            os.utime(str(invalid_evidence_path), (base_ts + 10.0, base_ts + 10.0))
            os.utime(str(valid_evidence_path), (base_ts, base_ts))

            status = mod.node_status(root)

        node = status["nodes"][0]
        self.assertEqual(node["heartbeat_start_status"], "ok")
        self.assertEqual(node["heartbeat_start_action"], "continue")
        self.assertEqual(node["heartbeat_start_action_reason"], "heartbeat_tmux_started")
        self.assertEqual(node["heartbeat_start_return_code"], 0)
        self.assertFalse(node["heartbeat_start_timed_out"])
        self.assertEqual(node["heartbeat_start_executed_at"], "2026-05-28T00:00:00Z")
        self.assertEqual(node["heartbeat_start_evidence_path"], str(valid_evidence_path))

    def test_node_status_without_heartbeat_start_evidence_does_not_add_fields(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.register_node({"node_id": "node/a", "ssh_target": "root@node-a"}, root=root)
            mod.heartbeat_node({"node_id": "node/a", "status": "online"}, root=root)

            status = mod.node_status(root)

        node = status["nodes"][0]
        self.assertNotIn("heartbeat_start_status", node)
        self.assertNotIn("heartbeat_start_action", node)
        self.assertNotIn("heartbeat_start_action_reason", node)
        self.assertNotIn("heartbeat_start_return_code", node)
        self.assertNotIn("heartbeat_start_timed_out", node)
        self.assertNotIn("heartbeat_start_executed_at", node)
        self.assertNotIn("heartbeat_start_evidence_path", node)

    def test_node_status_includes_tasks_stream_pending_lag_probe(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        groups_output = "\n".join(
            [
                "name",
                "a9-worker",
                "consumers",
                "2",
                "pending",
                "7",
                "last-delivered-id",
                "1740000010-0",
                "entries-read",
                "100",
                "lag",
                "3",
            ]
        )

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("11\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("22\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc(groups_output)
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("7\n1740000001-0\n1740000010-0\nworker-a\n5\nworker-b\n2\n")
            if args == ["--raw", "XINFO", "CONSUMERS", "a9:tasks", "a9-worker"]:
                return FakeProc(
                    "name\nworker-c\npending\n1\nidle\n99\n"
                    "name\nworker-a\npending\n5\nidle\n12\n"
                    "name\nworker-b\npending\n2\nidle\n35\n"
                    "name\nworker-d\npending\n0\nidle\n5\n"
                )
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["status"], "ok")
        self.assertEqual(status["tasks_stream"]["reason"], "healthy")
        self.assertEqual(status["tasks_stream"]["stream"], "a9:tasks")
        self.assertEqual(status["tasks_stream"]["group"], "a9-worker")
        self.assertEqual(status["tasks_stream"]["lag"], 3)
        self.assertEqual(status["tasks_stream"]["pending"], 7)
        self.assertEqual(status["tasks_stream"]["consumer_count"], 2)
        self.assertEqual(status["tasks_stream"]["entries_read"], 100)
        self.assertEqual(status["tasks_stream"]["consumer_probe_status"], "ok")
        self.assertEqual(status["tasks_stream"]["consumer_probe_reason"], "healthy")
        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "watch")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "pending_stuck")
        self.assertEqual(
            status["tasks_stream"]["top_consumers"],
            [
                {"name": "worker-a", "pending": 5, "idle": 12},
                {"name": "worker-b", "pending": 2, "idle": 35},
                {"name": "worker-c", "pending": 1, "idle": 99},
            ],
        )

    def test_node_status_tasks_stream_probe_sets_continue_action_when_healthy(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\na9-worker\nconsumers\n2\nentries-read\n100\nlag\n3\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("0\n1740000001-0\n1740000010-0\n\n0\n")
            if args == ["--raw", "XINFO", "CONSUMERS", "a9:tasks", "a9-worker"]:
                return FakeProc("name\nworker-a\npending\n0\nidle\n12\nname\nworker-b\npending\n0\nidle\n35\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "continue")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "none")

    def test_node_status_tasks_stream_probe_sets_watch_action_on_lag_warn(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\na9-worker\nconsumers\n1\nentries-read\n9\nlag\n100\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("0\n1740000001-0\n1740000010-0\n\n0\n")
            if args == ["--raw", "XINFO", "CONSUMERS", "a9:tasks", "a9-worker"]:
                return FakeProc("name\nworker-a\npending\n0\nidle\n12\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "watch")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "lag_warn")

    def test_node_status_tasks_stream_probe_sets_intervene_action_on_stuck_pending(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\na9-worker\nconsumers\n2\nentries-read\n20\nlag\n10\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("5\n1740000001-0\n1740000010-0\nworker-a\n5\n")
            if args == ["--raw", "XINFO", "CONSUMERS", "a9:tasks", "a9-worker"]:
                return FakeProc("name\nworker-a\npending\n5\nidle\n30000\nname\nworker-b\npending\n0\nidle\n20\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "intervene")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "pending_stuck")

    def test_tasks_stream_probe_recommends_recover_stale_commands_for_pending_stuck(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\na9-worker\nconsumers\n2\nentries-read\n100\nlag\n5\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("5\n1740000001-0\n1740000010-0\nworker-a\n5\n")
            if args == ["--raw", "XINFO", "CONSUMERS", "a9:tasks", "a9-worker"]:
                return FakeProc("name\nworker-a\npending\n5\nidle\n30000\nname\nworker-b\npending\n0\nidle\n35\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.redis_tasks_stream_probe()
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["stream_action"], "intervene")
        self.assertEqual(status["stream_action_reason"], "pending_stuck")
        self.assertEqual(status["recommended_action"], "recover_stale_commands")

    def test_node_status_tasks_stream_probe_sets_intervene_action_on_lag_critical(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\na9-worker\nconsumers\n1\nentries-read\n20\nlag\n1000\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("2\n1740000001-0\n1740000010-0\nworker-a\n2\n")
            if args == ["--raw", "XINFO", "CONSUMERS", "a9:tasks", "a9-worker"]:
                return FakeProc("name\nworker-a\npending\n2\nidle\n10\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["status"], "ok")
        self.assertEqual(status["tasks_stream"]["reason"], "healthy")
        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "intervene")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "lag_critical")

    def test_node_status_tasks_stream_probe_sets_intervene_action_on_pending_skew(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\na9-worker\nconsumers\n2\nentries-read\n20\nlag\n9\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("10\n1740000001-0\n1740000010-0\nworker-a\n9\nworker-b\n1\n")
            if args == ["--raw", "XINFO", "CONSUMERS", "a9:tasks", "a9-worker"]:
                return FakeProc("name\nworker-a\npending\n8\nidle\n29999\nname\nworker-b\npending\n2\nidle\n10\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["status"], "ok")
        self.assertEqual(status["tasks_stream"]["reason"], "healthy")
        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "intervene")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "pending_skew")

    def test_node_status_tasks_stream_probe_degrades_consumer_probe_only(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\na9-worker\nconsumers\n1\nentries-read\n9\nlag\n4\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("3\n1740000001-0\n1740000010-0\nworker-a\n3\n")
            if args == ["--raw", "XINFO", "CONSUMERS", "a9:tasks", "a9-worker"]:
                return FakeProc("ERR probe failed\n", returncode=1)
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["status"], "ok")
        self.assertEqual(status["tasks_stream"]["reason"], "healthy")
        self.assertEqual(status["tasks_stream"]["stream"], "a9:tasks")
        self.assertEqual(status["tasks_stream"]["group"], "a9-worker")
        self.assertEqual(status["tasks_stream"]["lag"], 4)
        self.assertEqual(status["tasks_stream"]["pending"], 3)
        self.assertEqual(status["tasks_stream"]["consumer_count"], 1)
        self.assertEqual(status["tasks_stream"]["entries_read"], 9)
        self.assertEqual(status["tasks_stream"]["consumer_probe_status"], "degraded")
        self.assertEqual(status["tasks_stream"]["consumer_probe_reason"], "xinfo_consumers_failed")
        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "watch")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "pending_stuck")

    def test_node_status_tasks_stream_probe_error_preserves_stream_action_fields(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\na9-worker\nconsumers\n1\nentries-read\n9\nlag\n4\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("3\n1740000001-0\n1740000010-0\nworker-a\n3\n")
            if args == ["--raw", "XINFO", "CONSUMERS", "a9:tasks", "a9-worker"]:
                raise OSError("probe timeout")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["status"], "ok")
        self.assertEqual(status["tasks_stream"]["reason"], "healthy")
        self.assertEqual(status["tasks_stream"]["lag"], 4)
        self.assertEqual(status["tasks_stream"]["pending"], 3)
        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["consumer_probe_status"], "degraded")
        self.assertEqual(status["tasks_stream"]["consumer_probe_reason"], "xinfo_consumers_probe_error")
        self.assertEqual(status["tasks_stream"]["stream_action"], "watch")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "pending_stuck")

    def test_node_status_tasks_stream_probe_degrades_on_malformed_consumers_output(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\na9-worker\nconsumers\n1\nentries-read\n9\nlag\n4\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("3\n1740000001-0\n1740000010-0\nworker-a\n3\n")
            if args == ["--raw", "XINFO", "CONSUMERS", "a9:tasks", "a9-worker"]:
                return FakeProc("name\nworker-a\npending\n3\nidle\n12\nname\nworker-b\npending\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["status"], "ok")
        self.assertEqual(status["tasks_stream"]["reason"], "healthy")
        self.assertEqual(status["tasks_stream"]["lag"], 4)
        self.assertEqual(status["tasks_stream"]["pending"], 3)
        self.assertEqual(status["tasks_stream"]["consumer_probe_status"], "degraded")
        self.assertEqual(status["tasks_stream"]["consumer_probe_reason"], "xinfo_consumers_malformed")
        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "watch")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "pending_stuck")

    def test_node_status_tasks_stream_probe_uses_highest_idle_among_all_pending_consumers_before_top_cap(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\na9-worker\nconsumers\n4\nentries-read\n20\nlag\n4\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("6\n1740000001-0\n1740000010-0\nworker-a\n2\nworker-b\n2\nworker-c\n1\nworker-d\n1\n")
            if args == ["--raw", "XINFO", "CONSUMERS", "a9:tasks", "a9-worker"]:
                return FakeProc(
                    "name\nworker-a\npending\n2\nidle\n100\n"
                    "name\nworker-b\npending\n2\nidle\n200\n"
                    "name\nworker-c\npending\n1\nidle\n1000\n"
                    "name\nworker-d\npending\n1\nidle\n30000\n"
                )
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["status"], "ok")
        self.assertEqual(status["tasks_stream"]["reason"], "healthy")
        self.assertEqual(len(status["tasks_stream"]["top_consumers"]), 3)
        self.assertEqual(
            status["tasks_stream"]["top_consumers"],
            [
                {"name": "worker-a", "pending": 2, "idle": 100},
                {"name": "worker-b", "pending": 2, "idle": 200},
                {"name": "worker-c", "pending": 1, "idle": 1000},
            ],
        )
        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "intervene")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "pending_stuck")

    def test_node_status_tasks_stream_probe_degraded_when_xpending_fails(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\na9-worker\nconsumers\n1\nentries-read\n9\nlag\n4\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("ERR no group\n", returncode=1)
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["status"], "degraded")
        self.assertEqual(status["tasks_stream"]["reason"], "xpending_failed")
        self.assertEqual(status["tasks_stream"]["lag"], 4)
        self.assertIsNone(status["tasks_stream"]["pending"])
        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "watch")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "xpending_failed")

    def test_node_status_tasks_stream_probe_degraded_when_pending_parse_invalid(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\na9-worker\nconsumers\n1\nentries-read\n9\nlag\n4\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("bad-total\n1740000001-0\n1740000010-0\nworker-a\n3\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["status"], "degraded")
        self.assertEqual(status["tasks_stream"]["reason"], "invalid_pending")
        self.assertEqual(status["tasks_stream"]["lag"], 4)
        self.assertIsNone(status["tasks_stream"]["pending"])
        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "watch")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "invalid_pending")

    def test_node_status_tasks_stream_probe_degraded_when_group_missing(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\nother-group\nlag\n1\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("0\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["status"], "degraded")
        self.assertEqual(status["tasks_stream"]["reason"], "consumer_group_missing")
        self.assertIsNone(status["tasks_stream"]["lag"])
        self.assertIsNone(status["tasks_stream"]["pending"])
        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "watch")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "consumer_group_missing")

    def test_node_status_tasks_stream_probe_degraded_when_xinfo_groups_failed(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("1\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("ERR no such key\n", returncode=1)
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("0\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status["tasks_stream"]["status"], "degraded")
        self.assertEqual(status["tasks_stream"]["reason"], "xinfo_groups_failed")
        self.assertIsNone(status["tasks_stream"]["lag"])
        self.assertIsNone(status["tasks_stream"]["pending"])
        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "intervene")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "xinfo_groups_failed")

    def test_node_status_tasks_stream_probe_unavailable_keeps_action_fields(self):
        mod = load_control_api()
        original_redis_available = mod.redis_available
        mod.redis_available = lambda: False
        try:
            status = mod.node_status(Path("/tmp/a9-test-nodes-empty"))
        finally:
            mod.redis_available = original_redis_available

        self.assertEqual(status["tasks_stream"]["status"], "unavailable")
        self.assertEqual(status["tasks_stream"]["reason"], "redis_unavailable")
        self.assertIsNone(status["tasks_stream"]["lag"])
        self.assertIsNone(status["tasks_stream"]["pending"])
        self.assertEqual(status["tasks_stream"]["thresholds_version"], "redis_streams_v1")
        self.assertEqual(status["tasks_stream"]["stream_action"], "intervene")
        self.assertEqual(status["tasks_stream"]["stream_action_reason"], "redis_unavailable")

    def test_communication_followup_intent_continue_when_all_healthy(self):
        mod = load_control_api()
        followup = mod.communication_followup_intent(
            [
                {"node_id": "node-a", "connection_state": "online", "connection_action": "continue"},
                {"node_id": "node-b", "connection_state": "online", "connection_action": "continue"},
            ],
            {"stream_action": "continue", "stream_action_reason": "none", "status": "ok"},
        )
        self.assertEqual(followup["action"], "continue")
        self.assertEqual(followup["status"], "ok")
        self.assertEqual(followup["reason"], "tasks_stream:none")
        self.assertEqual(followup["evidence"]["tasks_stream"]["action"], "continue")
        self.assertEqual(followup["intervention_decision"]["action"], "observe")
        self.assertEqual(followup["intervention_decision"]["reason"], "healthy")

    def test_communication_followup_intent_reconnect_for_degraded_node(self):
        mod = load_control_api()
        followup = mod.communication_followup_intent(
            [
                {
                    "node_id": "node-a",
                    "connection_state": "degraded",
                    "connection_action": "reconnect",
                    "connection_action_reason": "heartbeat_reported_degraded",
                }
            ],
            {"stream_action": "continue", "stream_action_reason": "none", "status": "ok"},
        )
        self.assertEqual(followup["action"], "reconnect")
        self.assertEqual(followup["status"], "degraded")
        self.assertEqual(followup["reason"], "node:heartbeat_reported_degraded")
        self.assertEqual(followup["evidence"]["nodes"][0]["node_id"], "node-a")
        self.assertEqual(followup["intervention_decision"]["action"], "repair")

    def test_communication_followup_intent_prioritizes_quarantine_and_intervene(self):
        mod = load_control_api()
        offline_first = mod.communication_followup_intent(
            [
                {
                    "node_id": "node-offline",
                    "connection_state": "offline",
                    "connection_action": "quarantine",
                    "connection_action_reason": "heartbeat_offline",
                }
            ],
            {"stream_action": "intervene", "stream_action_reason": "pending_stuck", "status": "ok"},
        )
        self.assertEqual(offline_first["action"], "quarantine")
        self.assertEqual(offline_first["reason"], "node:heartbeat_offline")
        self.assertEqual(offline_first["status"], "needs_attention")
        stream_intervene = mod.communication_followup_intent(
            [{"node_id": "node-a", "connection_state": "online", "connection_action": "continue"}],
            {"stream_action": "intervene", "stream_action_reason": "lag_critical", "status": "ok"},
        )
        self.assertEqual(stream_intervene["action"], "intervene")
        self.assertEqual(stream_intervene["reason"], "tasks_stream:lag_critical")
        self.assertEqual(stream_intervene["status"], "needs_attention")
        self.assertEqual(stream_intervene["evidence"]["tasks_stream"]["reason"], "lag_critical")
        self.assertEqual(stream_intervene["intervention_decision"]["action"], "repair")
        self.assertEqual(stream_intervene["intervention_decision"]["reason"], "stream_lag_critical")

    def _fake_redis_for_healthy_tasks_stream(self, mod, *, heartbeat_len: str):
        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc(f"{heartbeat_len}\n")
            if args == ["XLEN", "a9:events"]:
                return FakeProc("1\n")
            if args == ["--raw", "XINFO", "GROUPS", "a9:tasks"]:
                return FakeProc("name\na9-worker\nconsumers\n1\nentries-read\n9\nlag\n1\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("0\n1740000001-0\n1740000010-0\n\n0\n")
            if args == ["--raw", "XINFO", "CONSUMERS", "a9:tasks", "a9-worker"]:
                return FakeProc("name\nworker-a\npending\n0\nidle\n12\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        return original_redis

    def test_node_status_communication_followup_continue_when_nodes_and_stream_healthy(self):
        mod = load_control_api()
        original_redis = self._fake_redis_for_healthy_tasks_stream(mod, heartbeat_len="2")
        original_now = mod.utc_now_dt
        mod.utc_now_dt = lambda: datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                nodes_dir = root / ".a9" / "nodes"
                nodes_dir.mkdir(parents=True)
                for node_id in ("node-a", "node-b"):
                    (nodes_dir / f"{node_id}.json").write_text(
                        json.dumps(
                            {
                                "node_id": node_id,
                                "status": "online",
                                "last_heartbeat_at": "2026-05-26T11:59:30+00:00",
                            }
                        ),
                        encoding="utf-8",
                    )
                status = mod.node_status(root)
        finally:
            mod.utc_now_dt = original_now
            mod.redis_cli = original_redis

        followup = status["communication_followup"]
        self.assertEqual(followup["action"], "continue")
        self.assertEqual(followup["status"], "ok")
        self.assertEqual(followup["reason"], "tasks_stream:none")
        self.assertEqual(followup["evidence"]["nodes"], [])
        self.assertEqual(followup["evidence"]["tasks_stream"]["action"], "continue")

    def test_node_status_communication_followup_quarantine_for_offline_node(self):
        mod = load_control_api()
        original_redis = self._fake_redis_for_healthy_tasks_stream(mod, heartbeat_len="1")
        original_now = mod.utc_now_dt
        mod.utc_now_dt = lambda: datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                nodes_dir = root / ".a9" / "nodes"
                nodes_dir.mkdir(parents=True)
                (nodes_dir / "node-offline.json").write_text(
                    json.dumps(
                        {
                            "node_id": "node-offline",
                            "status": "online",
                            "last_heartbeat_at": "2026-05-26T11:50:00+00:00",
                        }
                    ),
                    encoding="utf-8",
                )
                status = mod.node_status(root)
        finally:
            mod.utc_now_dt = original_now
            mod.redis_cli = original_redis

        followup = status["communication_followup"]
        self.assertEqual(followup["action"], "quarantine")
        self.assertEqual(followup["status"], "needs_attention")
        self.assertEqual(followup["reason"], "node:heartbeat_offline")
        self.assertEqual(followup["evidence"]["nodes"][0]["node_id"], "node-offline")
        self.assertEqual(followup["evidence"]["nodes"][0]["action"], "quarantine")
        self.assertEqual(followup["evidence"]["nodes"][0]["recovery_plan"]["action"], "quarantine")
        self.assertTrue(followup["evidence"]["nodes"][0]["recovery_plan"]["requires_operator"])
        self.assertEqual(followup["evidence"]["tasks_stream"]["action"], "continue")

    def test_node_status_communication_followup_ignores_smoke_noise(self):
        mod = load_control_api()
        original_redis = self._fake_redis_for_healthy_tasks_stream(mod, heartbeat_len="2")
        original_now = mod.utc_now_dt
        mod.utc_now_dt = lambda: datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                nodes_dir = root / ".a9" / "nodes"
                nodes_dir.mkdir(parents=True)
                for node_id, payload in {
                    "local-service-smoke": {
                        "node_id": "local-service-smoke",
                        "status": "online",
                        "ssh_target": "root@127.0.0.1",
                        "message": "service-smoke",
                        "last_heartbeat_at": "2026-05-26T11:50:00+00:00",
                    },
                    "remote-a": {
                        "node_id": "remote-a",
                        "status": "online",
                        "ssh_target": "root@100.74.166.86:2200",
                        "labels": ["mobile-added"],
                        "last_heartbeat_at": "2026-05-26T11:50:00+00:00",
                    },
                }.items():
                    (nodes_dir / f"{node_id}.json").write_text(json.dumps(payload), encoding="utf-8")
                status = mod.node_status(root)
        finally:
            mod.utc_now_dt = original_now
            mod.redis_cli = original_redis

        followup = status["communication_followup"]
        self.assertEqual(followup["action"], "quarantine")
        self.assertEqual([node["node_id"] for node in followup["evidence"]["nodes"]], ["remote-a"])

    def test_node_status_communication_followup_dedupes_same_ssh_target(self):
        mod = load_control_api()
        original_redis = self._fake_redis_for_healthy_tasks_stream(mod, heartbeat_len="2")
        original_now = mod.utc_now_dt
        mod.utc_now_dt = lambda: datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                nodes_dir = root / ".a9" / "nodes"
                nodes_dir.mkdir(parents=True)
                for node_id, seen_at in {
                    "remote-old": "2026-05-26T11:45:00+00:00",
                    "remote-new": "2026-05-26T11:50:00+00:00",
                }.items():
                    (nodes_dir / f"{node_id}.json").write_text(
                        json.dumps(
                            {
                                "node_id": node_id,
                                "status": "online",
                                "ssh_target": "root@100.74.166.86:2200",
                                "labels": ["mobile-added"],
                                "last_heartbeat_at": seen_at,
                                "updated_at": seen_at,
                            }
                        ),
                        encoding="utf-8",
                    )
                status = mod.node_status(root)
        finally:
            mod.utc_now_dt = original_now
            mod.redis_cli = original_redis

        followup = status["communication_followup"]
        self.assertEqual(followup["action"], "quarantine")
        self.assertEqual([node["node_id"] for node in followup["evidence"]["nodes"]], ["remote-new"])

    def test_node_status_includes_recovery_plan_with_probe_priority(self):
        mod = load_control_api()
        original_now = mod.utc_now_dt
        mod.utc_now_dt = lambda: datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                mod.register_node({"node_id": "node/a", "ssh_target": "root@node-a"}, root=root)
                mod.heartbeat_node({"node_id": "node/a", "status": "degraded"}, root=root)
                mod.write_node_evidence(
                    "probe",
                    "node/a",
                    {
                        "status": "failed",
                        "probe_action": "retry",
                        "probe_action_reason": "ssh_exec_error",
                        "checked_at": "2026-05-26T11:59:50Z",
                    },
                    root=root,
                )
                status = mod.node_status(root)
        finally:
            mod.utc_now_dt = original_now

        node = status["nodes"][0]
        self.assertEqual(node["connection_action"], "reconnect")
        self.assertEqual(node["recovery_plan"]["action"], "probe")
        self.assertEqual(node["recovery_plan"]["reason"], "ssh_exec_error")
        self.assertEqual(node["recovery_plan"]["steps"], ["run_node_communication_probe", "refresh_node_status"])
        self.assertFalse(node["recovery_plan"]["requires_operator"])
        self.assertEqual(
            node["recovery_plan"]["route"],
            {
                "method": "POST",
                "endpoint": "/api/nodes/probe",
                "command": "nodes.probe.execute",
                "requires_arm": True,
            },
        )

    def test_node_status_communication_followup_keeps_multiple_reconnect_node_evidence(self):
        mod = load_control_api()
        original_redis = self._fake_redis_for_healthy_tasks_stream(mod, heartbeat_len="2")
        original_now = mod.utc_now_dt
        mod.utc_now_dt = lambda: datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                nodes_dir = root / ".a9" / "nodes"
                nodes_dir.mkdir(parents=True)
                records = [
                    {
                        "node_id": "node-degraded",
                        "status": "degraded",
                        "last_heartbeat_at": "2026-05-26T11:59:30+00:00",
                    },
                    {
                        "node_id": "node-stale",
                        "status": "online",
                        "last_heartbeat_at": "2026-05-26T11:57:00+00:00",
                    },
                ]
                for record in records:
                    (nodes_dir / f"{record['node_id']}.json").write_text(json.dumps(record), encoding="utf-8")
                status = mod.node_status(root)
        finally:
            mod.utc_now_dt = original_now
            mod.redis_cli = original_redis

        followup = status["communication_followup"]
        self.assertEqual(followup["action"], "reconnect")
        self.assertEqual(followup["status"], "degraded")
        self.assertEqual(len(followup["evidence"]["nodes"]), 2)
        self.assertEqual(
            {item["node_id"] for item in followup["evidence"]["nodes"]},
            {"node-degraded", "node-stale"},
        )

    def test_enrich_node_connection_marks_stale_and_offline(self):
        mod = load_control_api()
        original_now = mod.utc_now_dt
        mod.utc_now_dt = lambda: datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
        try:
            stale = mod.enrich_node_connection({"last_heartbeat_at": "2026-05-26T11:57:00+00:00"})
            offline = mod.enrich_node_connection({"last_heartbeat_at": "2026-05-26T11:50:00+00:00"})
        finally:
            mod.utc_now_dt = original_now

        self.assertEqual(stale["connection_state"], "stale")
        self.assertEqual(stale["connection_action"], "reconnect")
        self.assertEqual(stale["connection_action_reason"], "heartbeat_stale")
        self.assertEqual(stale["last_seen_age_seconds"], 180)
        self.assertEqual(offline["connection_state"], "offline")
        self.assertEqual(offline["connection_action"], "quarantine")
        self.assertEqual(offline["connection_action_reason"], "heartbeat_offline")

    def test_enrich_node_connection_respects_self_reported_degraded_status(self):
        mod = load_control_api()
        original_now = mod.utc_now_dt
        mod.utc_now_dt = lambda: datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
        try:
            fresh = mod.enrich_node_connection(
                {"last_heartbeat_at": "2026-05-26T11:59:50+00:00", "status": "degraded"}
            )
            stale = mod.enrich_node_connection(
                {"last_heartbeat_at": "2026-05-26T11:57:00+00:00", "status": "error"}
            )
            failed = mod.enrich_node_connection(
                {"last_heartbeat_at": "2026-05-26T11:57:00+00:00", "status": "failed"}
            )
        finally:
            mod.utc_now_dt = original_now

        self.assertEqual(fresh["connection_state"], "degraded")
        self.assertEqual(fresh["connection_action"], "reconnect")
        self.assertEqual(fresh["connection_action_reason"], "heartbeat_reported_degraded")
        self.assertEqual(stale["connection_state"], "degraded")
        self.assertEqual(stale["connection_action"], "reconnect")
        self.assertEqual(stale["connection_action_reason"], "heartbeat_reported_degraded")
        self.assertEqual(failed["connection_state"], "degraded")
        self.assertEqual(failed["connection_action"], "reconnect")
        self.assertEqual(failed["connection_action_reason"], "heartbeat_reported_degraded")

    def test_enrich_node_connection_offline_age_overrides_self_reported_degraded(self):
        mod = load_control_api()
        original_now = mod.utc_now_dt
        mod.utc_now_dt = lambda: datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
        try:
            offline = mod.enrich_node_connection(
                {"last_heartbeat_at": "2026-05-26T11:50:00+00:00", "status": "degraded"}
            )
        finally:
            mod.utc_now_dt = original_now

        self.assertEqual(offline["connection_state"], "offline")
        self.assertEqual(offline["connection_action"], "quarantine")
        self.assertEqual(offline["connection_action_reason"], "heartbeat_offline")

    def test_node_recovery_plan_requires_operator_for_quarantine(self):
        mod = load_control_api()
        plan = mod.node_recovery_plan(
            {
                "connection_state": "offline",
                "connection_action": "quarantine",
                "connection_action_reason": "heartbeat_offline",
            }
        )
        self.assertEqual(plan["action"], "quarantine")
        self.assertEqual(plan["reason"], "heartbeat_offline")
        self.assertTrue(plan["requires_operator"])
        self.assertIn("verify_ssh_target_reachable", plan["steps"])
        self.assertEqual(
            plan["route"],
            {
                "method": None,
                "endpoint": None,
                "command": None,
                "requires_arm": False,
            },
        )

    def test_node_recovery_plan_probes_offline_remote_candidate_before_manual_quarantine(self):
        mod = load_control_api()
        plan = mod.node_recovery_plan(
            {
                "connection_state": "offline",
                "connection_action": "quarantine",
                "connection_action_reason": "heartbeat_offline",
                "ssh_target": "root@100.74.166.86:2200",
                "labels": ["mobile-added"],
                "hygiene": {
                    "category": "remote_candidate",
                    "risk_scope": "operational",
                },
            }
        )
        self.assertEqual(plan["action"], "probe")
        self.assertEqual(plan["reason"], "remote_candidate_heartbeat_offline")
        self.assertFalse(plan["requires_operator"])
        self.assertEqual(
            plan["route"],
            {
                "method": "POST",
                "endpoint": "/api/nodes/probe",
                "command": "nodes.probe.execute",
                "requires_arm": True,
            },
        )

    def test_node_recovery_plan_starts_heartbeat_after_remote_probe_ok(self):
        mod = load_control_api()
        plan = mod.node_recovery_plan(
            {
                "connection_state": "connected",
                "connection_action": "continue",
                "connection_action_reason": "heartbeat_fresh",
                "probe_action": "continue",
                "probe_action_reason": "probe_ok",
                "ssh_target": "root@100.74.166.86:2200",
                "labels": ["mobile-added"],
                "hygiene": {
                    "category": "remote_candidate",
                    "risk_scope": "operational",
                },
            }
        )
        self.assertEqual(plan["action"], "heartbeat_start")
        self.assertEqual(plan["reason"], "remote_probe_ok_heartbeat_missing")
        self.assertFalse(plan["requires_operator"])
        self.assertEqual(
            plan["route"],
            {
                "method": "POST",
                "endpoint": "/api/nodes/heartbeat-tmux-start",
                "command": "nodes.heartbeat.tmux.start",
                "requires_arm": True,
            },
        )

    def test_node_recovery_plan_observes_remote_after_heartbeat_start_ok(self):
        mod = load_control_api()
        plan = mod.node_recovery_plan(
            {
                "connection_state": "connected",
                "connection_action": "continue",
                "connection_action_reason": "heartbeat_fresh",
                "probe_action": "continue",
                "heartbeat_start_action": "continue",
                "ssh_target": "root@100.74.166.86:2200",
                "labels": ["mobile-added"],
                "hygiene": {
                    "category": "remote_candidate",
                    "risk_scope": "operational",
                },
            }
        )
        self.assertEqual(plan["action"], "observe")

    def test_node_recovery_plan_starts_heartbeat_after_repair_ok(self):
        mod = load_control_api()
        plan = mod.node_recovery_plan(
            {
                "connection_state": "stale",
                "connection_action": "reconnect",
                "connection_action_reason": "heartbeat_stale",
                "probe_action": "continue",
                "heartbeat_repair_action": "continue",
                "ssh_target": "root@100.74.166.86:2200",
                "labels": ["mobile-added"],
                "hygiene": {
                    "category": "remote_candidate",
                    "risk_scope": "operational",
                },
            }
        )
        self.assertEqual(plan["action"], "heartbeat_start")
        self.assertEqual(plan["reason"], "heartbeat_repaired_start_required")
        self.assertEqual(plan["route"]["endpoint"], "/api/nodes/heartbeat-tmux-start")

    def test_node_recovery_plan_restarts_heartbeat_after_repair_even_with_old_start_evidence(self):
        mod = load_control_api()
        plan = mod.node_recovery_plan(
            {
                "connection_state": "stale",
                "connection_action": "reconnect",
                "connection_action_reason": "heartbeat_stale",
                "probe_action": "continue",
                "heartbeat_start_action": "continue",
                "heartbeat_start_executed_at": "2026-05-30T00:00:00+00:00",
                "heartbeat_repair_action": "continue",
                "heartbeat_repair_executed_at": "2026-05-30T00:01:00+00:00",
                "tmux_action": "repair",
                "tmux_session": "a9-heartbeat",
                "tmux_checked_at": "2026-05-30T00:00:30+00:00",
                "ssh_target": "root@100.74.166.86:2200",
                "labels": ["mobile-added"],
                "hygiene": {
                    "category": "remote_candidate",
                    "risk_scope": "operational",
                },
            }
        )
        self.assertEqual(plan["action"], "heartbeat_start")
        self.assertEqual(plan["reason"], "heartbeat_repaired_start_required")

    def test_node_recovery_plan_checks_tmux_when_started_heartbeat_goes_stale(self):
        mod = load_control_api()
        plan = mod.node_recovery_plan(
            {
                "connection_state": "stale",
                "connection_action": "reconnect",
                "connection_action_reason": "heartbeat_stale",
                "probe_action": "continue",
                "heartbeat_start_action": "continue",
                "ssh_target": "root@100.74.166.86:2200",
                "labels": ["mobile-added"],
                "hygiene": {
                    "category": "remote_candidate",
                    "risk_scope": "operational",
                },
            }
        )
        self.assertEqual(plan["action"], "tmux")
        self.assertEqual(plan["reason"], "remote_heartbeat_stale_check_tmux")
        self.assertTrue(plan["requires_operator"])
        self.assertEqual(plan["route"]["endpoint"], "/api/nodes/tmux-status")
        self.assertEqual(plan["route"]["session"], "a9-heartbeat")
        self.assertEqual(plan["route"]["plan_kind"], "heartbeat_tmux")

    def test_node_recovery_plan_repairs_heartbeat_when_tmux_missing_after_start(self):
        mod = load_control_api()
        plan = mod.node_recovery_plan(
            {
                "connection_state": "stale",
                "connection_action": "reconnect",
                "connection_action_reason": "heartbeat_stale",
                "probe_action": "continue",
                "heartbeat_start_action": "continue",
                "heartbeat_start_executed_at": "2026-05-30T00:00:00+00:00",
                "tmux_action": "repair",
                "tmux_session": "a9-heartbeat",
                "tmux_checked_at": "2026-05-30T00:01:00+00:00",
                "ssh_target": "root@100.74.166.86:2200",
                "labels": ["mobile-added"],
                "hygiene": {
                    "category": "remote_candidate",
                    "risk_scope": "operational",
                },
            }
        )
        self.assertEqual(plan["action"], "heartbeat_repair")
        self.assertEqual(plan["reason"], "heartbeat_tmux_missing_after_start")
        self.assertEqual(plan["route"]["endpoint"], "/api/nodes/heartbeat-repair")
        self.assertEqual(plan["route"]["command"], "nodes.remote.repair")

    def test_publish_node_heartbeat_redis_writes_json_stream_and_timeseries(self):
        mod = load_control_api()
        calls = []

        class FakeProc:
            def __init__(self, stdout: str = "OK\n", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            calls.append(args)
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args[0] == "XADD":
                return FakeProc("1740000000-0\n")
            return FakeProc()

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            result = mod.publish_node_heartbeat_redis(
                {
                    "node_id": "node-a",
                    "status": "online",
                    "connection_state": "online",
                    "connection_action": "continue",
                    "connection_action_reason": "heartbeat_fresh",
                    "last_heartbeat_at": "2026-05-26T12:00:00+00:00",
                }
            )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["json_key"], "a9:node:node-a")
        json_set_call = next(call for call in calls if call[:2] == ["JSON.SET", "a9:node:node-a"])
        json_payload = json.loads(json_set_call[3])
        self.assertEqual(json_payload["connection_action"], "continue")
        self.assertEqual(json_payload["connection_action_reason"], "heartbeat_fresh")
        xadd_call = next(call for call in calls if call[:2] == ["XADD", "a9:heartbeats"])
        self.assertIn("connection_action", xadd_call)
        self.assertIn("continue", xadd_call)
        self.assertIn("connection_action_reason", xadd_call)
        self.assertIn("heartbeat_fresh", xadd_call)
        self.assertTrue(any(call[:2] == ["TS.ADD", "a9:ts:heartbeat"] for call in calls))

    def test_enqueue_node_command_validates_and_appends_to_tasks_stream(self):
        mod = load_control_api()
        calls = []

        class FakeProc:
            def __init__(self, stdout: str = "OK\n", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            calls.append(args)
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args[:2] == ["XADD", "a9:tasks"]:
                return FakeProc("1740000000-0\n")
            return FakeProc()

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            result = mod.enqueue_node_command(
                {
                    "command_id": "cmd-001",
                    "node_id": "node-a",
                    "action": "restart",
                    "action_reason": "manual",
                    "target": "node-a",
                    "expected_revision": 12,
                    "ttl_seconds": 120,
                    "created_at": "2026-05-29T12:00:00+00:00",
                    "status": "queued",
                }
            )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["kind"], "node_command_enqueue")
        command = result["command"]
        self.assertEqual(command["stream"], "a9:tasks")
        self.assertEqual(command["stream_id"], "1740000000-0")
        self.assertEqual(command["command_id"], "cmd-001")
        self.assertEqual(command["error_code"], "none")
        xadd_call = next(call for call in calls if call[:2] == ["XADD", "a9:tasks"])
        index = xadd_call.index("command_id")
        self.assertEqual(xadd_call[index + 1], "cmd-001")
        self.assertIn("ttl_seconds", xadd_call)
        self.assertIn("120", xadd_call)
        self.assertIn("node_id", xadd_call)
        self.assertIn("node-a", xadd_call)
        stream_id_index = xadd_call.index("stream_id")
        self.assertEqual(xadd_call[stream_id_index + 1], "pending")
        error_code_index = xadd_call.index("error_code")
        self.assertEqual(xadd_call[error_code_index + 1], "none")
        hint = result["recovery_hint"]
        self.assertEqual(hint["action"], "wait")
        self.assertEqual(hint["reason"], "await_result")
        self.assertEqual(hint["next_endpoint"], "/api/node-command-results/by-command/cmd-001")
        self.assertNotEqual(hint["reason"], "command_result_found")

    def test_enqueue_node_command_returns_degraded_when_redis_unavailable(self):
        mod = load_control_api()

        def fake_redis(args, *, timeout=2):
            raise OSError("redis socket unavailable")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            result = mod.enqueue_node_command(
                {
                    "command_id": "cmd-002",
                    "node_id": "node-b",
                    "action": "rollback",
                    "action_reason": "operator",
                    "target": "node-b",
                    "expected_revision": 1,
                    "ttl_seconds": 60,
                }
            )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error_code"], "redis_unavailable")
        self.assertEqual(result["command"]["status"], "degraded")

    def test_enqueue_node_command_xadd_failure_returns_machine_readable_degrade(self):
        mod = load_control_api()
        calls = []

        class FakeProc:
            def __init__(self, stdout: str = "ERR", returncode: int = 1):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            calls.append(args)
            if args == ["PING"]:
                return FakeProc("PONG\n", 0)
            if args[:2] == ["XADD", "a9:tasks"]:
                return FakeProc("ERR", 1)
            return FakeProc()

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            result = mod.enqueue_node_command(
                {
                    "command_id": "cmd-003",
                    "node_id": "node-c",
                    "action": "scale",
                    "action_reason": "overload",
                    "target": "node-c",
                    "expected_revision": 2,
                    "ttl_seconds": 45,
                }
            )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error_code"], "xadd_failed")
        self.assertEqual(result["error"], "ERR")
        self.assertEqual(calls[0], ["PING"])
        self.assertEqual(calls[1][:2], ["XADD", "a9:tasks"])

    def test_api_nodes_command_submit_writes_to_tasks_stream(self):
        mod = load_control_api()
        calls = []

        class FakeProc:
            def __init__(self, stdout: str = "1740000100-0\n", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            calls.append(args)
            if args == ["PING"]:
                return FakeProc("PONG\n", 0)
            if args[:2] == ["XADD", "a9:tasks"]:
                return FakeProc("1740000100-0\n", 0)
            return FakeProc()

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            payload = {
                "command_id": "cmd-004",
                "node_id": "node-submit",
                "action": "restart",
                "action_reason": "operator_action",
                "target": "node-submit",
                "expected_revision": 3,
                "ttl_seconds": 30,
            }
            post_body = json.dumps(payload).encode("utf-8")
            captured = {"status": None, "payload": None}

            class DummyNodeCommandPostHandler:
                path = "/api/nodes/command-submit"
                headers = {"Content-Length": str(len(post_body))}
                rfile = io.BytesIO(post_body)

                def write_json(self, status, response_payload):
                    captured["status"] = status
                    captured["payload"] = response_payload

            mod.ControlHandler.do_POST(DummyNodeCommandPostHandler())
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["status"], "ok")
        self.assertEqual(captured["payload"]["command"]["command_id"], "cmd-004")
        self.assertEqual(captured["payload"]["command"]["status"], "queued")
        self.assertEqual(captured["payload"]["command"]["stream"], "a9:tasks")
        hint = captured["payload"]["recovery_hint"]
        self.assertEqual(hint["action"], "wait")
        self.assertEqual(hint["reason"], "await_result")
        self.assertEqual(hint["next_endpoint"], "/api/node-command-results/by-command/cmd-004")
        self.assertNotEqual(hint["reason"], "command_result_found")
        self.assertTrue(any(call[:2] == ["XADD", "a9:tasks"] for call in calls))

    def test_node_command_result_lookup_delegates_to_node_reader(self):
        mod = load_control_api()
        calls = []

        class FakeNode:
            @staticmethod
            def node_command_result_read_once(result_event_id, *, event_stream="a9:events", timeout=3):
                calls.append(
                    {
                        "result_event_id": result_event_id,
                        "event_stream": event_stream,
                        "timeout": timeout,
                    }
                )
                return {
                    "status": "ok",
                    "kind": "node_command_result",
                    "error_code": "ok",
                    "result_event_id": result_event_id,
                    "command_id": "cmd-lookup",
                    "result": {"status": "ok"},
                }

        original_a9_node = mod.a9_node
        mod.a9_node = lambda: FakeNode
        try:
            result = mod.node_command_result_lookup("1740000300-0", event_stream="a9:test-events", timeout=5)
        finally:
            mod.a9_node = original_a9_node

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["kind"], "node_command_result_lookup")
        self.assertEqual(result["error_code"], "ok")
        self.assertEqual(result["result"]["command_id"], "cmd-lookup")
        self.assertEqual(
            calls,
            [{"result_event_id": "1740000300-0", "event_stream": "a9:test-events", "timeout": 5}],
        )

    def test_node_command_result_lookup_rejects_invalid_event_id_without_reader(self):
        mod = load_control_api()
        calls = []
        original_a9_node = mod.a9_node
        mod.a9_node = lambda: calls.append("called")
        try:
            result = mod.node_command_result_lookup("bad-id")
        finally:
            mod.a9_node = original_a9_node

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error_code"], "invalid_payload")
        self.assertEqual(result["reason"], "result_event_id_must_be_redis_stream_id")
        self.assertEqual(calls, [])

    def test_api_node_command_results_endpoint_returns_lookup_payload(self):
        mod = load_control_api()
        calls = []
        captured = {"status": None, "payload": None}

        def fake_lookup(result_event_id, *, event_stream="a9:events", timeout=3, node_id=""):
            calls.append(
                {
                    "result_event_id": result_event_id,
                    "event_stream": event_stream,
                    "timeout": timeout,
                    "node_id": node_id,
                }
            )
            return {
                "status": "ok",
                "kind": "node_command_result_lookup",
                "result_event_id": result_event_id,
                "event_stream": event_stream,
                "error_code": "ok",
                "result": {"command_id": "cmd-api"},
            }

        class DummyNodeCommandResultGetHandler:
            path = "/api/node-command-results/1740000400-0?event_stream=a9:test-events&timeout=7"
            headers = {}

            def write_json(self, status, response_payload):
                captured["status"] = status
                captured["payload"] = response_payload

        original_lookup = mod.node_command_result_lookup
        mod.node_command_result_lookup = fake_lookup
        try:
            mod.ControlHandler.do_GET(DummyNodeCommandResultGetHandler())
        finally:
            mod.node_command_result_lookup = original_lookup

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["result"]["command_id"], "cmd-api")
        self.assertEqual(
            calls,
            [{"result_event_id": "1740000400-0", "event_stream": "a9:test-events", "timeout": 7, "node_id": ""}],
        )

    def test_node_command_result_by_command_lookup_finds_latest_result(self):
        mod = load_control_api()
        calls = []

        class FakeProc:
            returncode = 0
            stdout = (
                "1740000500-0\n"
                "kind\n"
                "node_command_result\n"
                "command_id\n"
                "cmd-find\n"
                "1740000400-0\n"
                "kind\n"
                "node_command_result\n"
                "command_id\n"
                "other-command\n"
            )

        def fake_redis(args, *, timeout=2):
            calls.append(args)
            return FakeProc()

        def fake_lookup(result_event_id, *, event_stream="a9:events", timeout=3):
            return {
                "status": "ok",
                "kind": "node_command_result_lookup",
                "error_code": "ok",
                "result_event_id": result_event_id,
                "event_stream": event_stream,
                "result": {"command_id": "cmd-find"},
            }

        original_redis = mod.redis_cli
        original_lookup = mod.node_command_result_lookup
        mod.redis_cli = fake_redis
        mod.node_command_result_lookup = fake_lookup
        try:
            result = mod.node_command_result_by_command_lookup("cmd-find", event_stream="a9:test-events", limit=9, timeout=4)
        finally:
            mod.redis_cli = original_redis
            mod.node_command_result_lookup = original_lookup

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["kind"], "node_command_result_by_command_lookup")
        self.assertEqual(result["requested_node_id"], "")
        self.assertEqual(result["result_event_id"], "1740000500-0")
        self.assertEqual(result["result_node_id"], "")
        self.assertEqual(result["result"]["result"]["command_id"], "cmd-find")
        self.assertEqual(calls, [["--raw", "XREVRANGE", "a9:test-events", "+", "-", "COUNT", "9"]])

    def test_node_command_result_by_command_lookup_prefers_actual_result_node_id_over_requested_node(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = "1740000500-0\nkind\nnode_command_result\ncommand_id\ncmd-find\n"

        def fake_redis(args, *, timeout=2):
            return FakeProc()

        def fake_lookup(result_event_id, *, event_stream="a9:events", timeout=3):
            return {
                "status": "ok",
                "kind": "node_command_result_lookup",
                "error_code": "ok",
                "result_event_id": result_event_id,
                "event_stream": event_stream,
                "result": {
                    "command_id": "cmd-find",
                    "node_id": "DESKTOP-92A9ATS-0",
                    "result": {"node_id": "DESKTOP-92A9ATS-0", "status": "ok"},
                },
            }

        original_redis = mod.redis_cli
        original_lookup = mod.node_command_result_lookup
        mod.redis_cli = fake_redis
        mod.node_command_result_lookup = fake_lookup
        try:
            result = mod.node_command_result_by_command_lookup(
                "cmd-find",
                event_stream="a9:test-events",
                limit=9,
                timeout=4,
                node_id="smoke-node",
            )
        finally:
            mod.redis_cli = original_redis
            mod.node_command_result_lookup = original_lookup

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["requested_node_id"], "smoke-node")
        self.assertEqual(result["result_node_id"], "DESKTOP-92A9ATS-0")
        self.assertEqual(result["result"]["result"]["node_id"], "DESKTOP-92A9ATS-0")
        self.assertEqual(result["recovery_hint"]["action"], "observe")
        self.assertIn("redis:command:cmd-find", result["recovery_hint"]["evidence_refs"])
        self.assertIn("redis:event:1740000500-0", result["recovery_hint"]["evidence_refs"])

    def test_node_command_result_by_command_lookup_noops_when_missing(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = "1740000500-0\nkind\nnode_command_result\ncommand_id\nother-command\n"

        original_redis = mod.redis_cli
        mod.redis_cli = lambda args, *, timeout=2: FakeProc()
        try:
            result = mod.node_command_result_by_command_lookup("cmd-missing", limit=2)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "noop")
        self.assertEqual(result["error_code"], "no_result")
        self.assertEqual(result["reason"], "node_command_result_not_found")
        self.assertEqual(result["scanned_count"], 1)

    def test_node_command_result_by_command_lookup_rejects_blank_command_id_without_redis(self):
        mod = load_control_api()
        calls = []
        original_redis = mod.redis_cli
        mod.redis_cli = lambda args, *, timeout=2: calls.append(args)
        try:
            result = mod.node_command_result_by_command_lookup("  ")
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error_code"], "invalid_payload")
        self.assertEqual(result["reason"], "command_id_required")
        self.assertEqual(calls, [])

    def test_api_node_command_results_by_command_endpoint_returns_lookup_payload(self):
        mod = load_control_api()
        calls = []
        captured = {"status": None, "payload": None}

        def fake_lookup(command_id, *, event_stream="a9:events", limit=100, timeout=3, result_last_id=None, node_id=""):
            calls.append(
                {
                    "command_id": command_id,
                    "event_stream": event_stream,
                    "limit": limit,
                    "timeout": timeout,
                    "result_last_id": result_last_id,
                    "node_id": node_id,
                }
            )
            return {
                "status": "ok",
                "kind": "node_command_result_by_command_lookup",
                "command_id": command_id,
                "event_stream": event_stream,
                "limit": int(limit),
                "result_event_id": "1740000600-0",
                "error_code": "ok",
                "result": {"result": {"command_id": command_id}},
            }

        class DummyNodeCommandResultByCommandGetHandler:
            path = "/api/node-command-results/by-command/cmd-api?event_stream=a9:test-events&limit=8&timeout=6&result_last_id=1740000600-0"
            headers = {"Last-Event-ID": "1740000601-0"}

            def write_json(self, status, response_payload):
                captured["status"] = status
                captured["payload"] = response_payload

        original_lookup = mod.node_command_result_by_command_lookup
        mod.node_command_result_by_command_lookup = fake_lookup
        try:
            mod.ControlHandler.do_GET(DummyNodeCommandResultByCommandGetHandler())
        finally:
            mod.node_command_result_by_command_lookup = original_lookup

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["result_event_id"], "1740000600-0")
        self.assertEqual(
            calls,
            [
                {
                    "command_id": "cmd-api",
                    "event_stream": "a9:test-events",
                    "limit": "8",
                    "timeout": "6",
                    "result_last_id": "1740000600-0",
                    "node_id": "",
                }
            ],
        )

    def test_node_command_result_watch_returns_existing_found_result(self):
        mod = load_control_api()

        def fake_lookup(command_id, *, event_stream="a9:events", limit=100, timeout=3, result_last_id=None, node_id="", root=None):
            return {
                "status": "ok",
                "kind": "node_command_result_by_command_lookup",
                "command_id": command_id,
                "result_event_id": "1740000700-0",
                "result": {"result": {"command_id": command_id, "status": "ok"}},
                "result_replay_reset": {
                    "action": "keep_cursor",
                    "reason": "no_cursor_reset_needed",
                    "next_last_id": "1740000700-0",
                },
                "error_code": "ok",
            }

        original_lookup = mod.node_command_result_by_command_lookup
        mod.node_command_result_by_command_lookup = fake_lookup
        try:
            payload = mod.node_command_result_watch("cmd-watch")
        finally:
            mod.node_command_result_by_command_lookup = original_lookup

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["kind"], "node_command_result_watch")
        self.assertEqual(payload["watch_action"], "terminate")
        self.assertEqual(payload["watch_reason"], "command_result_found")
        self.assertEqual(payload["next_last_id"], "1740000700-0")

    def test_node_command_result_watch_invalid_cursor_degrades_without_redis_scan(self):
        mod = load_control_api()
        calls = []

        def fake_replay(last_id=None, *, event_stream="a9:events", count=100, limit=None):
            calls.append(("replay", last_id, event_stream, limit))
            return {
                "status": "degraded",
                "kind": "node_command_result_replay",
                "stream": event_stream,
                "error_code": "invalid_cursor",
                "error": "invalid last_id format",
                "last_id": last_id,
                "requested_count": int(limit or count),
                "events": [],
                "next_last_id": "",
            }

        def fail_redis(*args, **kwargs):
            raise AssertionError("redis_cli should not be called for invalid cursor degrade path")

        original_replay = mod.read_node_result_replay
        original_redis = mod.redis_cli
        mod.read_node_result_replay = fake_replay
        mod.redis_cli = fail_redis
        try:
            payload = mod.node_command_result_watch("cmd-watch", result_last_id="bad-id")
        finally:
            mod.read_node_result_replay = original_replay
            mod.redis_cli = original_redis

        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["watch_action"], "terminate")
        self.assertEqual(payload["result_replay_reset"]["action"], "retry_without_cursor")
        self.assertEqual(calls, [("replay", "bad-id", "a9:events", 100)])

    def test_node_command_result_watch_cursor_gap_returns_reset_action(self):
        mod = load_control_api()

        def fake_lookup(command_id, *, event_stream="a9:events", limit=100, timeout=3, result_last_id=None, node_id="", root=None):
            return {
                "status": "degraded",
                "kind": "node_command_result_by_command_lookup",
                "command_id": command_id,
                "error_code": "cursor_gap",
                "reason": "cursor_gap: last_id outside replay window",
                "result": {},
                "result_replay": {"status": "degraded", "error_code": "cursor_gap", "next_last_id": "1740000800-0"},
                "result_replay_reset": {"action": "reset_cursor", "reason": "cursor_gap", "next_last_id": "1740000800-0"},
            }

        original_lookup = mod.node_command_result_by_command_lookup
        mod.node_command_result_by_command_lookup = fake_lookup
        try:
            payload = mod.node_command_result_watch("cmd-watch", result_last_id="1740000001-0")
        finally:
            mod.node_command_result_by_command_lookup = original_lookup

        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["watch_action"], "reconnect")
        self.assertEqual(payload["watch_reason"], "cursor_gap_reset_required")
        self.assertEqual(payload["result_replay_reset"]["action"], "reset_cursor")
        self.assertEqual(payload["next_last_id"], "1740000800-0")

    def test_api_node_command_results_watch_endpoint_prefers_query_cursor_over_last_event_id(self):
        mod = load_control_api()
        calls = []
        captured = {"status": None, "payload": None}

        def fake_watch(command_id, *, event_stream="a9:events", limit=100, timeout=3, timeout_seconds=None, result_last_id=None, node_id=""):
            calls.append(
                {
                    "command_id": command_id,
                    "event_stream": event_stream,
                    "limit": limit,
                    "timeout": timeout,
                    "timeout_seconds": timeout_seconds,
                    "result_last_id": result_last_id,
                    "node_id": node_id,
                }
            )
            return {
                "status": "noop",
                "kind": "node_command_result_watch",
                "command_id": command_id,
                "result": {},
                "result_replay": None,
                "result_replay_reset": {"action": "keep_cursor", "reason": "no_cursor_reset_needed", "next_last_id": ""},
                "watch_action": "continue",
                "watch_reason": "node_command_result_not_found_yet",
                "next_last_id": "1740000900-0",
            }

        class DummyWatchHandler:
            path = "/api/node-command-results/watch/cmd-watch?event_stream=a9:test-events&limit=7&timeout=5&timeout_seconds=9&result_last_id=1740000900-0"
            headers = {"Last-Event-ID": "1740000999-0"}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

            def write_sse(self, status, payload):
                raise AssertionError("write_sse should not be used for format=json")

        original_watch = mod.node_command_result_watch
        mod.node_command_result_watch = fake_watch
        try:
            mod.ControlHandler.do_GET(DummyWatchHandler())
        finally:
            mod.node_command_result_watch = original_watch

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "node_command_result_watch")
        self.assertEqual(calls[0]["result_last_id"], "1740000900-0")
        self.assertEqual(calls[0]["timeout_seconds"], "9")

    def test_api_node_command_results_watch_endpoint_sse_output_has_event_id_and_data(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}

        def fake_watch(command_id, *, event_stream="a9:events", limit=100, timeout=3, timeout_seconds=None, result_last_id=None, node_id=""):
            return {
                "status": "noop",
                "kind": "node_command_result_watch",
                "command_id": command_id,
                "result": {},
                "result_replay": None,
                "result_replay_reset": {"action": "keep_cursor", "reason": "no_cursor_reset_needed", "next_last_id": ""},
                "watch_action": "continue",
                "watch_reason": "node_command_result_not_found_yet",
                "next_last_id": "1740001000-0",
            }

        class DummyWatchSSEHandler:
            path = "/api/node-command-results/watch/cmd-watch?format=sse"
            headers = {"Last-Event-ID": "1740000999-0"}

            def write_json(self, status, payload):
                raise AssertionError("write_json should not be used for format=sse")

            def write_sse(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        original_watch = mod.node_command_result_watch
        mod.node_command_result_watch = fake_watch
        try:
            mod.ControlHandler.do_GET(DummyWatchSSEHandler())
        finally:
            mod.node_command_result_watch = original_watch

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["events"][0]["id"], "1740001000-0")
        self.assertEqual(captured["payload"]["events"][0]["fields"]["kind"], "node_command_result_watch")

    def test_node_command_result_lookup_missing_with_stale_heartbeat_returns_reconnect_hint(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_file = root / ".a9" / "nodes" / "node-stale.json"
            node_file.parent.mkdir(parents=True, exist_ok=True)
            stale_at = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(timespec="seconds")
            node_file.write_text(
                json.dumps(
                    {
                        "node_id": "node-stale",
                        "status": "online",
                        "last_heartbeat_at": stale_at,
                        "updated_at": stale_at,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            original_a9_node = mod.a9_node
            try:
                class FakeNode:
                    @staticmethod
                    def node_command_result_read_once(result_event_id, *, event_stream="a9:events", timeout=3):
                        return {
                            "status": "noop",
                            "kind": "node_command_result",
                            "error_code": "result_missing",
                            "reason": "result_missing",
                            "result_event_id": result_event_id,
                            "command_id": "cmd-stale",
                            "node_id": "node-stale",
                        }

                mod.a9_node = lambda: FakeNode
                result = mod.node_command_result_lookup(
                    "1740000300-0",
                    event_stream="a9:test-events",
                    timeout=3,
                    node_id="node-stale",
                    root=root,
                )
            finally:
                mod.a9_node = original_a9_node

        self.assertEqual(result["status"], "noop")
        self.assertEqual(result["recovery_hint"]["action"], "reconnect")
        self.assertIn(result["recovery_hint"]["reason"], {"heartbeat_stale", "heartbeat_reported_degraded"})
        self.assertEqual(result["recovery_hint"]["next_endpoint"], "/api/nodes/probe")

    def test_node_command_result_lookup_found_returns_observe_complete_hint(self):
        mod = load_control_api()

        class FakeNode:
            @staticmethod
            def node_command_result_read_once(result_event_id, *, event_stream="a9:events", timeout=3):
                return {
                    "status": "ok",
                    "kind": "node_command_result",
                    "error_code": "ok",
                    "result_event_id": result_event_id,
                    "command_id": "cmd-ok",
                    "node_id": "node-a",
                }

        original_a9_node = mod.a9_node
        mod.a9_node = lambda: FakeNode
        try:
            result = mod.node_command_result_lookup("1740000301-0", event_stream="a9:test-events", timeout=3)
        finally:
            mod.a9_node = original_a9_node

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["recovery_hint"]["action"], "observe")
        self.assertEqual(result["recovery_hint"]["reason"], "command_result_found")

    def test_enqueue_node_command_redis_unavailable_returns_degraded_recovery_hint(self):
        mod = load_control_api()

        def fake_redis(args, *, timeout=2):
            raise OSError("redis unavailable")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            result = mod.enqueue_node_command(
                {
                    "command_id": "cmd-redis-down",
                    "node_id": "node-r",
                    "action": "restart",
                    "action_reason": "operator",
                    "target": "node-r",
                    "expected_revision": 1,
                    "ttl_seconds": 60,
                }
            )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["recovery_hint"]["action"], "degraded")
        self.assertEqual(result["recovery_hint"]["reason"], "redis_unavailable")
        self.assertEqual(result["recovery_hint"]["next_endpoint"], "/api/nodes/status")

    def test_parse_xrange_events_accepts_raw_and_json_shapes(self):
        mod = load_control_api()
        raw = "1740000000-0\ntype\ntask_started\ntask_id\nt1\n1740000001-0\ntype\ntask_done\n"
        parsed = mod.parse_xrange_events(raw)
        self.assertEqual(parsed[0]["id"], "1740000000-0")
        self.assertEqual(parsed[0]["fields"]["type"], "task_started")
        self.assertEqual(parsed[0]["fields"]["task_id"], "t1")
        self.assertEqual(parsed[1]["fields"]["type"], "task_done")

        json_shape = json.dumps([["1740000002-0", ["type", "task_failed", "reason", "timeout"]]])
        parsed_json = mod.parse_xrange_events(json_shape)
        self.assertEqual(parsed_json[0]["id"], "1740000002-0")
        self.assertEqual(parsed_json[0]["fields"]["reason"], "timeout")

    def test_read_events_replays_after_last_id_with_degraded_fallback(self):
        mod = load_control_api()
        calls = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            calls.append(args)
            return FakeProc("1740000001-0\ntype\ntask_done\n")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            result = mod.read_events("1740000000-0", limit=5)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["events"][0]["fields"]["type"], "task_done")
        self.assertEqual(calls[0], ["--raw", "XRANGE", "a9:events", "(1740000000-0", "+", "COUNT", "5"])

        def failing_redis(args, *, timeout=2):
            return FakeProc("redis unavailable", 1)

        mod.redis_cli = failing_redis
        try:
            degraded = mod.read_events(limit=1)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(degraded["status"], "degraded")
        self.assertEqual(degraded["events"], [])

    def test_read_events_rejects_invalid_last_id_as_degraded(self):
        mod = load_control_api()
        calls = []

        def fake_redis(*args, **kwargs):
            calls.append(args)
            raise AssertionError("redis_cli must not be called for invalid cursor")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            result = mod.read_events("bad-cursor", limit=5)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["events"], [])
        self.assertIn("invalid last_id format", result["error"])
        self.assertEqual(calls, [])

    def test_read_events_marks_cursor_gap_when_stream_non_empty_but_no_replay(self):
        mod = load_control_api()
        calls = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            calls.append(args)
            if args[:3] == ["--raw", "XRANGE", "a9:events"] and args[3].startswith("("):
                return FakeProc("")
            if args == ["--raw", "XRANGE", "a9:events", "-", "+", "COUNT", "1"]:
                return FakeProc("1740000005-0\ntype\ntask_started\n")
            if args == ["--raw", "XREVRANGE", "a9:events", "+", "-", "COUNT", "1"]:
                return FakeProc("1740000010-0\ntype\ntask_done\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            result = mod.read_events("1740000004-0", limit=5)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error_code"], "cursor_gap")
        self.assertEqual(result["stream_oldest_id"], "1740000005-0")
        self.assertEqual(result["stream_newest_id"], "1740000010-0")
        self.assertEqual(result["next_last_id"], "1740000010-0")
        self.assertEqual(result["events"], [])
        self.assertEqual(calls[0], ["--raw", "XRANGE", "a9:events", "(1740000004-0", "+", "COUNT", "5"])

    def test_read_events_keeps_ok_empty_when_stream_is_empty(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args[:3] == ["--raw", "XRANGE", "a9:events"] and args[3].startswith("("):
                return FakeProc("")
            if args == ["--raw", "XRANGE", "a9:events", "-", "+", "COUNT", "1"]:
                return FakeProc("")
            if args == ["--raw", "XREVRANGE", "a9:events", "+", "-", "COUNT", "1"]:
                return FakeProc("")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            result = mod.read_events("1740000004-0", limit=5)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["events"], [])
        self.assertEqual(result["next_last_id"], "1740000004-0")

    def test_resolve_event_last_id_uses_query_then_header(self):
        mod = load_control_api()
        self.assertEqual(mod._resolve_event_last_id("1740000001-0", "1740000002-0"), "1740000001-0")
        self.assertEqual(mod._resolve_event_last_id(None, "1740000002-0"), "1740000002-0")
        self.assertIsNone(mod._resolve_event_last_id(None, "bad-cursor"))

    def test_events_to_sse_uses_stream_id_and_json_data(self):
        mod = load_control_api()
        body = mod.events_to_sse(
            {
                "events": [
                    {"id": "1740000000-0", "fields": {"type": "task_started", "task_id": "t1"}},
                ]
            }
        ).decode("utf-8")
        self.assertIn("id: 1740000000-0\n", body)
        self.assertIn('data: {"id": "1740000000-0"', body)
        self.assertTrue(body.endswith("\n\n"))

    def test_event_replay_reset_decision_resets_cursor_for_cursor_gap(self):
        mod = load_control_api()
        decision = mod.event_replay_reset_decision(
            {
                "status": "degraded",
                "error_code": "cursor_gap",
                "next_last_id": "1740000010-0",
            }
        )
        self.assertEqual(decision["action"], "reset_cursor")
        self.assertEqual(decision["reason"], "cursor_gap")
        self.assertEqual(decision["next_last_id"], "1740000010-0")

    def test_event_replay_reset_decision_retries_without_cursor_when_next_last_id_invalid(self):
        mod = load_control_api()
        decision = mod.event_replay_reset_decision(
            {
                "status": "degraded",
                "error_code": "cursor_gap",
                "next_last_id": "bad-cursor",
            }
        )
        self.assertEqual(decision["action"], "retry_without_cursor")
        self.assertEqual(decision["reason"], "cursor_gap_without_valid_next_last_id")
        self.assertEqual(decision["next_last_id"], "")

    def test_event_replay_reset_decision_keeps_cursor_when_no_gap(self):
        mod = load_control_api()
        decision = mod.event_replay_reset_decision(
            {
                "status": "ok",
                "next_last_id": "1740000008-0",
            }
        )
        self.assertEqual(decision["action"], "keep_cursor")
        self.assertEqual(decision["reason"], "no_cursor_reset_needed")
        self.assertEqual(decision["next_last_id"], "1740000008-0")

    def test_read_events_cursor_gap_response_feeds_reset_decision(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args[:3] == ["--raw", "XRANGE", "a9:events"] and args[3].startswith("("):
                return FakeProc("")
            if args == ["--raw", "XRANGE", "a9:events", "-", "+", "COUNT", "1"]:
                return FakeProc("1740000005-0\ntype\ntask_started\n")
            if args == ["--raw", "XREVRANGE", "a9:events", "+", "-", "COUNT", "1"]:
                return FakeProc("1740000010-0\ntype\ntask_done\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            response = mod.read_events("1740000004-0", limit=5)
        finally:
            mod.redis_cli = original_redis
        decision = mod.event_replay_reset_decision(response)
        self.assertEqual(decision["action"], "reset_cursor")
        self.assertEqual(decision["next_last_id"], "1740000010-0")

    def test_read_node_result_replay_rejects_invalid_last_id_without_redis(self):
        mod = load_control_api()
        calls = []

        def fake_redis(*args, **kwargs):
            calls.append(args)
            raise AssertionError("redis_cli must not be called for invalid cursor")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            result = mod.read_node_result_replay("bad-cursor", event_stream="a9:test-events", limit=5)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error_code"], "invalid_cursor")
        self.assertEqual(result["events"], [])
        self.assertEqual(calls, [])

    def test_read_node_result_replay_marks_cursor_gap_when_stream_non_empty_but_no_replay(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args[:3] == ["--raw", "XRANGE", "a9:test-events"] and args[3].startswith("("):
                return FakeProc("")
            if args == ["--raw", "XRANGE", "a9:test-events", "-", "+", "COUNT", "1"]:
                return FakeProc("1740000005-0\nkind\nnode_command_result\n")
            if args == ["--raw", "XREVRANGE", "a9:test-events", "+", "-", "COUNT", "1"]:
                return FakeProc("1740000010-0\nkind\nnode_command_result\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            result = mod.read_node_result_replay("1740000004-0", event_stream="a9:test-events", limit=5)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error_code"], "cursor_gap")
        self.assertEqual(result["next_last_id"], "1740000010-0")

    def test_result_replay_reset_decision_handles_cursor_gap_and_invalid_cursor(self):
        mod = load_control_api()
        decision_gap = mod.result_replay_reset_decision(
            {"status": "degraded", "error_code": "cursor_gap", "next_last_id": "1740000010-0"}
        )
        self.assertEqual(decision_gap["action"], "reset_cursor")
        self.assertEqual(decision_gap["next_last_id"], "1740000010-0")

        decision_invalid = mod.result_replay_reset_decision(
            {"status": "degraded", "error_code": "invalid_cursor", "next_last_id": "bad"}
        )
        self.assertEqual(decision_invalid["action"], "retry_without_cursor")
        self.assertEqual(decision_invalid["reason"], "invalid_cursor_format")

    def test_probe_node_uses_remote_probe_and_registers_result(self):
        mod = load_control_api()

        class FakeRemote:
            @staticmethod
            def ssh_base(target, *, connect_timeout=10, identity_file=""):
                return ["echo", "host=node1\nuser=root\nkernel=Linux test\npython3=/usr/bin/python3\n"]

            @staticmethod
            def remote_probe_script():
                return "ignored"

            @staticmethod
            def parse_probe(text):
                return {
                    line.split("=", 1)[0]: line.split("=", 1)[1]
                    for line in text.splitlines()
                    if "=" in line
                }

            @staticmethod
            def classify_probe_result(return_code, output):
                return {
                    "probe_action": "repair",
                    "probe_action_reason": "missing_required_tools",
                    "required_missing": ["git", "curl"],
                    "optional_missing": ["tmux", "tailscale"],
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_remote = mod.remote
            try:
                mod.remote = lambda: FakeRemote
                result = mod.probe_node({"ssh_target": "root@node1"}, root=root)
            finally:
                mod.remote = original_remote

            status = mod.node_status(root)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["probe_action"], "repair")
        self.assertEqual(result["probe_action_reason"], "missing_required_tools")
        self.assertEqual(result["supervisor_followup"]["action"], "repair")
        self.assertEqual(result["supervisor_followup"]["status"], "needs-repair")
        self.assertEqual(result["supervisor_followup"]["phase"], "repair")
        self.assertEqual(result["supervisor_followup"]["reason"], "missing_required_tools")
        self.assertEqual(result["missing_required_tools"], ["git", "curl"])
        self.assertEqual(result["missing_optional_tools"], ["tmux", "tailscale"])
        self.assertEqual(result["probe"]["python3"], "/usr/bin/python3")
        self.assertEqual(status["count"], 1)
        self.assertEqual(status["nodes"][0]["host"], "node1")
        self.assertEqual(status["nodes"][0]["capabilities"]["python3"], "/usr/bin/python3")
        self.assertEqual(status["nodes"][0]["last_probe_action"], "repair")
        self.assertEqual(status["nodes"][0]["last_probe_action_reason"], "missing_required_tools")
        self.assertEqual(status["nodes"][0]["last_probe_required_missing"], ["git", "curl"])
        self.assertEqual(status["nodes"][0]["last_probe_optional_missing"], ["tmux", "tailscale"])
        self.assertTrue(status["nodes"][0]["last_probe_checked_at"])

    def test_probe_node_nonzero_return_code_is_retry_action(self):
        mod = load_control_api()

        class FakeRemote:
            @staticmethod
            def ssh_base(target, *, connect_timeout=10, identity_file=""):
                return ["python3", "-c", "import sys; print('host=node1'); sys.exit(255)"]

            @staticmethod
            def remote_probe_script():
                return "ignored"

            @staticmethod
            def parse_probe(text):
                return {
                    line.split("=", 1)[0]: line.split("=", 1)[1]
                    for line in text.splitlines()
                    if "=" in line
                }

            @staticmethod
            def classify_probe_result(return_code, output):
                return {
                    "probe_action": "retry",
                    "probe_action_reason": "ssh_exec_error",
                    "required_missing": [],
                    "optional_missing": [],
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_remote = mod.remote
            try:
                mod.remote = lambda: FakeRemote
                result = mod.probe_node({"ssh_target": "root@node1", "reconnect_attempt": 3}, root=root)
                status = mod.node_status(root)
                listed = mod.list_node_evidence(str(result["node"]["node_id"]), root=root)
                self.assertEqual(listed["status"], "ok")
                self.assertEqual(any(item["path"] == result["evidence_path"] for item in listed["items"]), True)
            finally:
                mod.remote = original_remote

        node = status["nodes"][0]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["return_code"], 255)
        self.assertEqual(result["probe"]["host"], "node1")
        self.assertEqual(result["probe_action"], "retry")
        self.assertEqual(result["probe_action_reason"], "ssh_exec_error")
        self.assertEqual(result["supervisor_followup"]["action"], "retry")
        self.assertEqual(result["supervisor_followup"]["status"], "retryable-remote-probe")
        self.assertEqual(result["supervisor_followup"]["phase"], "repair")
        self.assertEqual(result["missing_required_tools"], [])
        self.assertEqual(node["reconnect_action"], "reconnect")
        self.assertEqual(node["reconnect_reason"], "ssh_exec_error")
        self.assertEqual(node["reconnect_attempt"], 3)
        self.assertEqual(node["reconnect_backoff_seconds"], 8)
        self.assertEqual(node["reconnect_lifecycle"]["event"], "reconnecting")

    def test_probe_node_stores_connection_summary_in_probe_evidence(self):
        mod = load_control_api()

        class FakeRemote:
            @staticmethod
            def ssh_base(target, *, connect_timeout=10, identity_file=""):
                return ["echo", "host=node1\nuser=root\npython3=/usr/bin/python3\ngit=/usr/bin/git\ncurl=/usr/bin/curl\n"]

            @staticmethod
            def remote_probe_script():
                return "ignored"

            @staticmethod
            def parse_probe(text):
                return {
                    line.split("=", 1)[0]: line.split("=", 1)[1]
                    for line in text.splitlines()
                    if "=" in line
                }

            @staticmethod
            def classify_probe_result(return_code, output):
                return {
                    "probe_action": "continue",
                    "probe_action_reason": "probe_ok",
                    "required_missing": [],
                    "optional_missing": [],
                }

            @staticmethod
            def summarize_node_connection_state(
                *,
                node_id,
                return_code,
                output,
                attempt=0,
                policy_budget_remaining=3,
            ):
                return {
                    "node_id": node_id,
                    "ssh_status": "connected",
                    "tailscale_status": "missing",
                    "tmux_status": "missing",
                    "connection_state": "degraded",
                    "action": "continue",
                    "action_reason": "optional_tools_missing",
                    "retry_delay_ms": 0,
                    "required_missing": [],
                    "optional_missing": [],
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_remote = mod.remote
            try:
                mod.remote = lambda: FakeRemote
                result = mod.probe_node({"ssh_target": "root@node1", "reconnect_attempt": 2}, root=root)
                status = mod.node_status(root)
                evidence = json.loads(mod.read_evidence_file(result["evidence_path"], root=root)["content"])
            finally:
                mod.remote = original_remote

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["probe_action"], "continue")
        self.assertEqual(status["nodes"][0]["connection_state"], "degraded")
        self.assertEqual(status["nodes"][0]["action"], "continue")
        self.assertEqual(status["nodes"][0]["action_reason"], "optional_tools_missing")
        self.assertEqual(status["nodes"][0]["retry_delay_ms"], 0)
        self.assertEqual(evidence["connection_summary"]["connection_state"], "degraded")
        self.assertEqual(evidence["connection_summary"]["action"], "continue")
        self.assertEqual(evidence["connection_summary"]["retry_delay_ms"], 0)

    def test_probe_node_timeout_is_retry_with_gateway_budget_and_reconnect_state(self):
        mod = load_control_api()

        class FakeRemote:
            @staticmethod
            def ssh_base(target, *, connect_timeout=10, identity_file=""):
                return ["ssh", "root@node1", "probe"]

            @staticmethod
            def remote_probe_script():
                return "ignored"

            @staticmethod
            def connect_error_action(error_kind):
                return "reconnect" if error_kind == "ssh_connect_timeout" else "connected"

            @staticmethod
            def capped_reconnect_backoff_seconds(attempt, *, base_seconds=1, cap_seconds=30):
                return min(cap_seconds, base_seconds * (2**attempt))

            @staticmethod
            def gateway_reconnect_decision(
                *,
                phase,
                error_class="",
                attempt=0,
                node_id="",
                origin="gateway",
                policy_budget_remaining=0,
                attempt_cap=8,
                at="",
            ):
                if policy_budget_remaining <= 0:
                    return {"action": "terminate", "delay_ms": 0}
                return {
                    "phase": phase,
                    "action": "reconnect",
                    "error_class": error_class,
                    "attempt": attempt + 1,
                    "delay_ms": 4000,
                    "policy_budget_remaining": policy_budget_remaining,
                    "node_id": node_id,
                    "origin": origin,
                    "ts": at,
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_remote = mod.remote
            original_run = mod.subprocess.run
            try:
                mod.remote = lambda: FakeRemote

                def fake_run(cmd, **kwargs):
                    raise mod.subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 0))

                mod.subprocess.run = fake_run
                result = mod.probe_node(
                    {"ssh_target": "root@node1", "node_id": "node-1", "reconnect_attempt": 2, "timeout_seconds": 1},
                    root=root,
                )
                status = mod.node_status(root)
                self.assertTrue(Path(result["evidence_path"]).exists())
                evidence_read = mod.read_evidence_file(str(result["evidence_path"]), root=root)
                self.assertEqual(evidence_read["status"], "ok")
                probe_evidence = json.loads(evidence_read["content"])
                self.assertEqual(probe_evidence["probe_action"], "retry")
                self.assertEqual(probe_evidence["reconnect_action"], "reconnect")
                self.assertTrue(probe_evidence["timed_out"])
            finally:
                mod.remote = original_remote
                mod.subprocess.run = original_run

        node = status["nodes"][0]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["return_code"], 124)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["probe_action"], "retry")
        self.assertEqual(result["probe_action_reason"], "ssh_connect_timeout")
        self.assertEqual(result["supervisor_followup"]["action"], "retry")
        self.assertEqual(result["supervisor_followup"]["status"], "retryable-remote-probe")
        self.assertEqual(result["supervisor_followup"]["phase"], "repair")
        self.assertEqual(result["supervisor_followup"]["reason"], "ssh_connect_timeout")
        self.assertEqual(result["missing_required_tools"], [])
        self.assertEqual(result["missing_optional_tools"], [])
        self.assertIn("probe timeout after 1s", result["raw"])
        self.assertEqual(node["node_id"], "node-1")
        self.assertEqual(node["ssh_target"], "root@node1")
        self.assertEqual(node["host"], "node1")
        self.assertEqual(node["reconnect_action"], "reconnect")
        self.assertEqual(node["reconnect_reason"], "ssh_connect_timeout")
        self.assertEqual(node["reconnect_attempt"], 2)
        self.assertEqual(node["reconnect_backoff_seconds"], 4)
        self.assertEqual(node["reconnect_lifecycle"]["event"], "reconnecting")


    def test_probe_node_sets_reconnect_backoff_and_terminal_action_fields(self):
        mod = load_control_api()

        class FakeRemote:
            @staticmethod
            def ssh_base(target, *, connect_timeout=10, identity_file=""):
                return ["echo", "host=node1\nuser=root\npython3=/usr/bin/python3\n"]

            @staticmethod
            def remote_probe_script():
                return "ignored"

            @staticmethod
            def parse_probe(text):
                return {
                    line.split("=", 1)[0]: line.split("=", 1)[1]
                    for line in text.splitlines()
                    if "=" in line
                }

            @staticmethod
            def classify_probe_result(return_code, output):
                return {
                    "probe_action": "repair",
                    "probe_action_reason": "auth_invalid",
                    "required_missing": [],
                    "optional_missing": [],
                }

            @staticmethod
            def connect_error_action(error_kind):
                return "terminate"

            @staticmethod
            def capped_reconnect_backoff_seconds(attempt, *, base_seconds=1, cap_seconds=30):
                return min(cap_seconds, base_seconds * (2**attempt))

            @staticmethod
            def stream_error_action(error_kind):
                return "continue" if error_kind == "decode_error" else "reconnect"

            @staticmethod
            def lifecycle_update(event, *, node_id="", at="", details=None):
                return {"event": event, "node_id": node_id, "at": at, "details": details or {}}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_remote = mod.remote
            try:
                mod.remote = lambda: FakeRemote
                result = mod.probe_node(
                    {"ssh_target": "root@node1", "reconnect_attempt": 4, "stream_reason": "decode_error"},
                    root=root,
                )
                status = mod.node_status(root)
            finally:
                mod.remote = original_remote
        node = status["nodes"][0]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(node["reconnect_action"], "terminate")
        self.assertEqual(node["reconnect_reason"], "auth_invalid")
        self.assertEqual(node["reconnect_attempt"], 4)
        self.assertEqual(node["reconnect_backoff_seconds"], 0)
        self.assertEqual(node["stream_action"], "continue")
        self.assertEqual(node["stream_reason"], "decode_error")
        self.assertEqual(node["reconnect_lifecycle"]["event"], "connected")

    def test_api_nodes_returns_persisted_last_probe_fields_after_probe_post(self):
        mod = load_control_api()

        class FakeRemote:
            @staticmethod
            def ssh_base(target, *, connect_timeout=10, identity_file=""):
                return ["echo", "host=node1\nuser=root\npython3=/usr/bin/python3\n"]

            @staticmethod
            def remote_probe_script():
                return "ignored"

            @staticmethod
            def parse_probe(text):
                return {
                    line.split("=", 1)[0]: line.split("=", 1)[1]
                    for line in text.splitlines()
                    if "=" in line
                }

            @staticmethod
            def classify_probe_result(return_code, output):
                return {
                    "probe_action": "repair",
                    "probe_action_reason": "missing_required_tools",
                    "required_missing": ["git", "curl"],
                    "optional_missing": ["tmux"],
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_remote = mod.remote
            original_probe_node = mod.probe_node
            original_node_status = mod.node_status
            original_command_gate = mod.command_gate
            try:
                mod.remote = lambda: FakeRemote
                mod.probe_node = lambda payload: original_probe_node(payload, root=root)
                mod.node_status = lambda: original_node_status(root)
                mod.command_gate = lambda command, *, root=None: {
                    "status": "allowed",
                    "allowed": True,
                    "command": command,
                    "reason": "test_gate",
                }

                post_payload = {"ssh_target": "root@node1"}
                post_body = json.dumps(post_payload).encode("utf-8")
                captured_post = {"status": None, "payload": None}

                class DummyProbePostHandler:
                    path = "/api/nodes/probe"
                    headers = {"Content-Length": str(len(post_body))}
                    rfile = io.BytesIO(post_body)

                    def write_json(self, status, payload):
                        captured_post["status"] = status
                        captured_post["payload"] = payload

                mod.ControlHandler.do_POST(DummyProbePostHandler())

                captured_get = {"status": None, "payload": None}

                class DummyNodesGetHandler:
                    path = "/api/nodes"
                    headers = {}

                    def write_json(self, status, payload):
                        captured_get["status"] = status
                        captured_get["payload"] = payload

                    def write_sse(self, status, payload):
                        raise AssertionError("write_sse should not be used for /api/nodes")

                mod.ControlHandler.do_GET(DummyNodesGetHandler())
            finally:
                mod.remote = original_remote
                mod.probe_node = original_probe_node
                mod.node_status = original_node_status
                mod.command_gate = original_command_gate

        self.assertEqual(captured_post["status"], 200)
        self.assertEqual(captured_post["payload"]["status"], "ok")
        self.assertEqual(captured_post["payload"]["audit_receipt"]["command"], "nodes.probe.execute")
        self.assertEqual(captured_post["payload"]["audit_receipt"]["endpoint"], "/api/nodes/probe")
        self.assertTrue(captured_post["payload"]["audit_receipt"]["allowed"])
        self.assertTrue(captured_post["payload"]["audit_receipt"]["evidence_path"])
        self.assertEqual(captured_get["status"], 200)
        self.assertEqual(captured_get["payload"]["count"], 1)
        node = captured_get["payload"]["nodes"][0]
        self.assertEqual(node["last_probe_action"], "repair")
        self.assertEqual(node["last_probe_action_reason"], "missing_required_tools")
        self.assertEqual(node["last_probe_required_missing"], ["git", "curl"])
        self.assertEqual(node["last_probe_optional_missing"], ["tmux"])
        self.assertTrue(node["last_probe_checked_at"])

    def test_api_nodes_persists_retry_last_probe_fields_after_probe_post(self):
        mod = load_control_api()

        class FakeRemote:
            @staticmethod
            def ssh_base(target, *, connect_timeout=10, identity_file=""):
                return ["echo", "host=node1\nuser=root\npython3=/usr/bin/python3\n"]

            @staticmethod
            def remote_probe_script():
                return "ignored"

            @staticmethod
            def parse_probe(text):
                return {
                    line.split("=", 1)[0]: line.split("=", 1)[1]
                    for line in text.splitlines()
                    if "=" in line
                }

            @staticmethod
            def classify_probe_result(return_code, output):
                return {
                    "probe_action": "retry",
                    "probe_action_reason": "ssh_exec_error",
                    "required_missing": [],
                    "optional_missing": ["tmux"],
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_remote = mod.remote
            original_probe_node = mod.probe_node
            original_node_status = mod.node_status
            original_command_gate = mod.command_gate
            try:
                mod.remote = lambda: FakeRemote
                mod.probe_node = lambda payload: original_probe_node(payload, root=root)
                mod.node_status = lambda: original_node_status(root)
                mod.command_gate = lambda command, *, root=None: {
                    "status": "allowed",
                    "allowed": True,
                    "command": command,
                    "reason": "test_gate",
                }

                post_payload = {"ssh_target": "root@node1"}
                post_body = json.dumps(post_payload).encode("utf-8")
                captured_post = {"status": None, "payload": None}

                class DummyProbePostHandler:
                    path = "/api/nodes/probe"
                    headers = {"Content-Length": str(len(post_body))}
                    rfile = io.BytesIO(post_body)

                    def write_json(self, status, payload):
                        captured_post["status"] = status
                        captured_post["payload"] = payload

                mod.ControlHandler.do_POST(DummyProbePostHandler())

                captured_get = {"status": None, "payload": None}

                class DummyNodesGetHandler:
                    path = "/api/nodes"
                    headers = {}

                    def write_json(self, status, payload):
                        captured_get["status"] = status
                        captured_get["payload"] = payload

                    def write_sse(self, status, payload):
                        raise AssertionError("write_sse should not be used for /api/nodes")

                mod.ControlHandler.do_GET(DummyNodesGetHandler())
            finally:
                mod.remote = original_remote
                mod.probe_node = original_probe_node
                mod.node_status = original_node_status
                mod.command_gate = original_command_gate

        self.assertEqual(captured_post["status"], 200)
        self.assertEqual(captured_post["payload"]["status"], "ok")
        self.assertEqual(captured_post["payload"]["audit_receipt"]["command"], "nodes.probe.execute")
        self.assertTrue(captured_post["payload"]["audit_receipt"]["allowed"])
        self.assertEqual(captured_get["status"], 200)
        self.assertEqual(captured_get["payload"]["count"], 1)
        node = captured_get["payload"]["nodes"][0]
        self.assertEqual(node["last_probe_action"], "retry")
        self.assertEqual(node["last_probe_action_reason"], "ssh_exec_error")
        self.assertEqual(node["last_probe_required_missing"], [])
        self.assertEqual(node["last_probe_optional_missing"], ["tmux"])
        self.assertTrue(node["last_probe_checked_at"])

    def test_api_nodes_probe_post_requires_remote_gate(self):
        mod = load_control_api()
        original_probe_node = mod.probe_node
        original_command_gate = mod.command_gate
        calls = []
        try:
            mod.probe_node = lambda payload: calls.append(payload) or {"status": "should-not-run"}
            mod.command_gate = lambda command, *, root=None: {
                "status": "blocked",
                "allowed": False,
                "command": command,
                "reason": "phone_control_disarmed",
            }
            post_body = json.dumps({"ssh_target": "root@node1"}).encode("utf-8")
            captured = {"status": None, "payload": None}

            class DummyProbePostHandler:
                path = "/api/nodes/probe"
                headers = {"Content-Length": str(len(post_body))}
                rfile = io.BytesIO(post_body)

                def write_json(self, status, payload):
                    captured["status"] = status
                    captured["payload"] = payload

            mod.ControlHandler.do_POST(DummyProbePostHandler())
        finally:
            mod.probe_node = original_probe_node
            mod.command_gate = original_command_gate

        self.assertEqual(captured["status"], 403)
        self.assertEqual(captured["payload"]["status"], "blocked")
        self.assertEqual(captured["payload"]["gate"]["command"], "nodes.probe.execute")
        self.assertEqual(captured["payload"]["audit_receipt"]["command"], "nodes.probe.execute")
        self.assertEqual(captured["payload"]["audit_receipt"]["endpoint"], "/api/nodes/probe")
        self.assertFalse(captured["payload"]["audit_receipt"]["allowed"])
        self.assertEqual(captured["payload"]["audit_receipt"]["result_status"], "blocked")
        self.assertTrue(captured["payload"]["audit_receipt"]["evidence_path"])
        self.assertEqual(calls, [])

    def test_api_nodes_tmux_status_post_requires_remote_gate(self):
        mod = load_control_api()
        original_tmux_status_node = mod.tmux_status_node
        original_command_gate = mod.command_gate
        calls = []
        try:
            mod.tmux_status_node = lambda payload: calls.append(payload) or {"status": "should-not-run"}
            mod.command_gate = lambda command, *, root=None: {
                "status": "blocked",
                "allowed": False,
                "command": command,
                "reason": "phone_control_disarmed",
            }
            post_body = json.dumps({"evidence_path": "/tmp/plan.json"}).encode("utf-8")
            captured = {"status": None, "payload": None}

            class DummyTmuxStatusPostHandler:
                path = "/api/nodes/tmux-status"
                headers = {"Content-Length": str(len(post_body))}
                rfile = io.BytesIO(post_body)

                def write_json(self, status, payload):
                    captured["status"] = status
                    captured["payload"] = payload

            mod.ControlHandler.do_POST(DummyTmuxStatusPostHandler())
        finally:
            mod.tmux_status_node = original_tmux_status_node
            mod.command_gate = original_command_gate

        self.assertEqual(captured["status"], 403)
        self.assertEqual(captured["payload"]["status"], "blocked")
        self.assertEqual(captured["payload"]["gate"]["command"], "nodes.tmux.status")
        self.assertEqual(captured["payload"]["audit_receipt"]["command"], "nodes.tmux.status")
        self.assertEqual(captured["payload"]["audit_receipt"]["endpoint"], "/api/nodes/tmux-status")
        self.assertFalse(captured["payload"]["audit_receipt"]["allowed"])
        self.assertEqual(calls, [])

    def test_api_nodes_command_endpoint_accepts_command_payload(self):
        mod = load_control_api()
        calls = []

        class FakeProc:
            def __init__(self, stdout: str = "1740000200-0\n", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            calls.append(args)
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args[:2] == ["XADD", "a9:tasks"]:
                return FakeProc("1740000200-0\n")
            return FakeProc()

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis
        try:
            payload = {
                "command_id": "cmd-005",
                "node_id": "node-command",
                "action": "restart",
                "action_reason": "admin",
                "target": "node-command",
                "expected_revision": 5,
                "ttl_seconds": 10,
            }
            post_body = json.dumps(payload).encode("utf-8")
            captured = {"status": None, "payload": None}

            class DummyNodeCommandPostHandler:
                path = "/api/nodes/command"
                headers = {"Content-Length": str(len(post_body))}
                rfile = io.BytesIO(post_body)

                def write_json(self, status, response_payload):
                    captured["status"] = status
                    captured["payload"] = response_payload

            mod.ControlHandler.do_POST(DummyNodeCommandPostHandler())
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["command"]["command_id"], "cmd-005")
        self.assertEqual(captured["payload"]["command"]["status"], "queued")
        self.assertEqual(captured["payload"]["command"]["stream"], "a9:tasks")
        self.assertEqual(captured["payload"]["status"], "ok")
        self.assertTrue(any(call[:2] == ["XADD", "a9:tasks"] for call in calls))

    def test_node_command_consumer_name_is_deterministic(self):
        mod = load_node()
        self.assertEqual(mod.node_command_consumer_name("worker@node-01.example"), "worker-node-01.example-consumer")
        with self.assertRaises(ValueError):
            mod.node_command_consumer_name("  ")

    def test_node_command_claim_plan_includes_claim_commands(self):
        mod = load_node()
        plan = mod.node_command_claim_plan("node-01", count=2, block_ms=5000)
        self.assertEqual(plan["status"], "ok")
        self.assertEqual(plan["node_id"], "node-01")
        self.assertEqual(plan["stream"], "a9:tasks")
        self.assertEqual(plan["group"], "a9-worker")
        self.assertEqual(plan["action"], "claim")
        self.assertEqual(plan["evidence"]["stream"], "a9:tasks")
        self.assertEqual(plan["evidence"]["group"], "a9-worker")
        self.assertEqual(plan["evidence"]["node_id"], "node-01")
        self.assertEqual(plan["evidence"]["action"], "claim")
        self.assertEqual(plan["commands"][0], ["XGROUP", "CREATE", "a9:tasks", "a9-worker", "0-0", "MKSTREAM"])
        self.assertEqual(
            plan["commands"][1],
            ["XREADGROUP", "GROUP", "a9-worker", "node-01-consumer", "COUNT", "2", "BLOCK", "5000", "STREAMS", "a9:tasks", ">"],
        )

    def test_node_command_claim_plan_invalid_payload_returns_degraded(self):
        mod = load_node()
        plan = mod.node_command_claim_plan("node-01", count=0)
        self.assertEqual(plan["status"], "degraded")
        self.assertEqual(plan["error_code"], "invalid_payload")
        self.assertEqual(plan["action"], "claim")
        self.assertEqual(plan["reason"], "count_must_be_positive")

    def test_node_command_ack_plan_includes_xack(self):
        mod = load_node()
        plan = mod.node_command_ack_plan("node-01", "1740000200-0")
        self.assertEqual(plan["status"], "ok")
        self.assertEqual(plan["action"], "ack")
        self.assertEqual(plan["evidence"]["action"], "ack")
        self.assertEqual(plan["commands"], [["XACK", "a9:tasks", "a9-worker", "1740000200-0"]])

    def test_node_command_ack_plan_invalid_payload_returns_degraded(self):
        mod = load_node()
        plan = mod.node_command_ack_plan("", "")
        self.assertEqual(plan["status"], "degraded")
        self.assertEqual(plan["error_code"], "invalid_payload")
        self.assertEqual(plan["action"], "ack")
        self.assertEqual(plan["reason"], "node_id is required")

    def test_command_claim_plan_cli_prints_deterministic_plan(self):
        mod = load_node()
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            status = mod.main(
                [
                    "--node-id",
                    "node-cli-01",
                    "command-claim-plan",
                    "--count",
                    "2",
                    "--block-ms",
                    "250",
                    "--group",
                    "workers",
                    "--stream",
                    "a9:test-tasks",
                ]
            )
        self.assertEqual(status, 0)
        payload = json.loads(captured.getvalue())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["action"], "claim")
        self.assertEqual(payload["node_id"], "node-cli-01")
        self.assertEqual(payload["stream"], "a9:test-tasks")
        self.assertEqual(payload["group"], "workers")
        self.assertEqual(
            payload["commands"][1],
            [
                "XREADGROUP",
                "GROUP",
                "workers",
                "node-cli-01-consumer",
                "COUNT",
                "2",
                "BLOCK",
                "250",
                "STREAMS",
                "a9:test-tasks",
                ">",
            ],
        )

    def test_command_ack_plan_cli_returns_degraded_payload_for_invalid_node(self):
        mod = load_node()
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            status = mod.main(["--node-id", "   ", "command-ack-plan", "1740000200-0"])
        self.assertEqual(status, 0)
        payload = json.loads(captured.getvalue())
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["action"], "ack")
        self.assertEqual(payload["reason"], "node_id is required")

    def test_command_claim_plan_cli_argparse_failure_returns_nonzero(self):
        mod = load_node()
        with self.assertRaises(SystemExit) as captured:
            mod.main(["command-claim-plan", "--count", "bad"])
        self.assertEqual(captured.exception.code, 2)

    def test_bootstrap_plan_node_is_non_executing_plan(self):
        mod = load_control_api()

        result = mod.bootstrap_plan_node(
            {
                "ssh_target": "root@node1",
                "controller_url": "http://controller:8787",
                "repo": "git@example.com:a9.git",
                "remote_dir": "~/a9-worker",
            }
        )

        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["target"], "root@node1")
        self.assertIn("ssh probe remote host", result["steps"])
        self.assertIn("install heartbeat loop script at .a9/remote-node/heartbeat.sh", result["steps"])
        self.assertIn("git@example.com:a9.git", result["repo"])
        self.assertIn("git clone", result["dry_run_script"])
        self.assertIn("CONTROLLER_URL=http://controller:8787", result["dry_run_script"])
        self.assertEqual(result["runtime_contract"]["bootstrap_mode"], "ssh_bootstrap_only")
        self.assertEqual(result["runtime_contract"]["runtime_mode"], "redis_api_runtime")
        self.assertEqual(result["runtime_contract"]["heartbeat_tmux_session"], "a9-heartbeat")

    def test_bootstrap_dry_run_node_keeps_execution_disabled(self):
        mod = load_control_api()

        result = mod.bootstrap_dry_run_node({"ssh_target": "root@node1"})

        self.assertEqual(result["status"], "dry-run")
        self.assertFalse(result["execution_enabled"])
        self.assertIn("<dry_run_script>", result["command_preview"])
        self.assertIn("git clone", result["dry_run_script"])

    def test_bootstrap_takeover_admission_waits_without_remote_execution(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_path = root / ".a9" / "nodes" / "node-a.json"
            node_path.parent.mkdir(parents=True)
            node_path.write_text(
                json.dumps(
                    {
                        "node_id": "node-a",
                        "revision": 4,
                        "ssh_target": "root@100.64.0.1",
                        "status": "registered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = mod.bootstrap_takeover_admission(
                {
                    "expected_revision": 4,
                    "reconnect_event": {
                        "status": "ok",
                        "kind": "gateway_reconnect_decision",
                        "event_id": "1779900000-0",
                        "phase": "connect",
                        "action": "terminate",
                        "error_class": "policy_budget_exhausted",
                        "node_id": "node-a",
                        "flow_revision": 4,
                    },
                },
                root=root,
            )
            record = json.loads(node_path.read_text(encoding="utf-8"))
            evidence_path_exists = Path(result["evidence_path"]).exists()

        self.assertEqual(result["status"], "needs_approval")
        self.assertFalse(result["execution_enabled"])
        self.assertTrue(result["no_actuation"])
        self.assertEqual(result["expected_revision"], 5)
        self.assertEqual(result["wait"]["approvalId"], "bootstrap-takeover:node-a:5")
        self.assertEqual(record["status"], "await_bootstrap_takeover")
        self.assertEqual(record["revision"], 5)
        self.assertEqual(record["bootstrap_takeover"]["expected_revision"], 5)
        self.assertTrue(evidence_path_exists)

    def test_bootstrap_takeover_admission_blocks_stale_revision(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_path = root / '.a9' / 'nodes' / 'node-a.json'
            node_path.parent.mkdir(parents=True)
            node_path.write_text(json.dumps({'node_id': 'node-a', 'revision': 9}) + '\n', encoding='utf-8')

            result = mod.bootstrap_takeover_admission(
                {
                    'expected_revision': 8,
                    'reconnect_event': {
                        'status': 'ok',
                        'kind': 'gateway_reconnect_decision',
                        'action': 'terminate',
                        'node_id': 'node-a',
                    },
                },
                root=root,
            )
            record = json.loads(node_path.read_text(encoding='utf-8'))

        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(result['reason'], 'expected_revision_mismatch')
        self.assertEqual(result['actual_revision'], 9)
        self.assertEqual(record['revision'], 9)

    def test_bootstrap_takeover_resume_requires_exact_expected_revision(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_path = root / '.a9' / 'nodes' / 'node-a.json'
            node_path.parent.mkdir(parents=True)
            node_path.write_text(
                json.dumps(
                    {
                        'node_id': 'node-a',
                        'revision': 4,
                        'ssh_target': 'root@100.64.0.1',
                        'status': 'registered',
                    }
                )
                + '\n',
                encoding='utf-8',
            )

            mod.bootstrap_takeover_admission(
                {
                    'expected_revision': 4,
                    'reconnect_event': {
                        'status': 'ok',
                        'kind': 'gateway_reconnect_decision',
                        'event_id': '1779900000-0',
                        'phase': 'connect',
                        'action': 'terminate',
                        'error_class': 'policy_budget_exhausted',
                        'node_id': 'node-a',
                        'flow_revision': 4,
                    },
                },
                root=root,
            )

            stale = mod.bootstrap_takeover_resume(
                {
                    'node_id': 'node-a',
                    'expected_revision': 4,
                    'operator_scopes': ['operator.admin'],
                },
                root=root,
            )
            stale_record = json.loads(node_path.read_text(encoding='utf-8'))

            resume = mod.bootstrap_takeover_resume(
                {
                    'node_id': 'node-a',
                    'expected_revision': 5,
                    'operator_scopes': ['operator.admin'],
                    'actor': 'operator.admin',
                },
                root=root,
            )
            record = json.loads(node_path.read_text(encoding='utf-8'))
            resume_evidence_path_exists = Path(resume['evidence_path']).exists()

        self.assertEqual(stale['status'], 'conflict')
        self.assertEqual(stale['reason'], 'expected_revision_mismatch')
        self.assertEqual(stale_record['revision'], 5)
        self.assertEqual(stale_record['bootstrap_takeover']['state'], 'waiting')
        self.assertEqual(resume['status'], 'approved')
        self.assertEqual(record['revision'], 6)
        self.assertEqual(record['bootstrap_takeover']['state'], 'approved')
        self.assertFalse(resume['execution_enabled'])
        self.assertTrue(resume['no_actuation'])
        self.assertEqual(record['bootstrap_takeover']['decision'], 'resume_approved')
        self.assertEqual(resume['next_revision'], 6)
        self.assertTrue(resume_evidence_path_exists)

    def test_bootstrap_takeover_reject_closes_wait_state_and_records_audit(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_path = root / '.a9' / 'nodes' / 'node-a.json'
            node_path.parent.mkdir(parents=True)
            node_path.write_text(
                json.dumps(
                    {
                        'node_id': 'node-a',
                        'revision': 4,
                        'ssh_target': 'root@100.64.0.1',
                        'status': 'registered',
                    }
                )
                + '\n',
                encoding='utf-8',
            )

            mod.bootstrap_takeover_admission(
                {
                    'expected_revision': 4,
                    'reconnect_event': {
                        'status': 'ok',
                        'kind': 'gateway_reconnect_decision',
                        'event_id': '1779900000-0',
                        'phase': 'connect',
                        'action': 'terminate',
                        'node_id': 'node-a',
                    },
                },
                root=root,
            )

            stale = mod.bootstrap_takeover_reject(
                {
                    'node_id': 'node-a',
                    'expected_revision': 4,
                    'operator_scopes': ['operator.admin'],
                },
                root=root,
            )
            stale_record = json.loads(node_path.read_text(encoding='utf-8'))
            reject = mod.bootstrap_takeover_reject(
                {
                    'node_id': 'node-a',
                    'expected_revision': 5,
                    'operator_scopes': ['operator.admin'],
                    'actor': 'operator.admin',
                    'reason': 'false_positive',
                },
                root=root,
            )
            record = json.loads(node_path.read_text(encoding='utf-8'))
            reject_evidence_path_exists = Path(reject['evidence_path']).exists()

        self.assertEqual(stale['status'], 'conflict')
        self.assertEqual(stale['reason'], 'expected_revision_mismatch')
        self.assertEqual(stale_record['revision'], 5)
        self.assertEqual(reject['status'], 'rejected')
        self.assertEqual(record['revision'], 6)
        self.assertEqual(record['status'], 'registered')
        self.assertEqual(record['bootstrap_takeover']['state'], 'rejected')
        self.assertEqual(record['bootstrap_takeover']['decision'], 'reject')
        self.assertEqual(record['bootstrap_takeover']['rejected_by'], 'operator.admin')
        self.assertTrue(reject_evidence_path_exists)

    def test_bootstrap_execute_blocked_while_takeover_waiting_without_approval(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_path = root / '.a9' / 'nodes' / 'node-a.json'
            node_path.parent.mkdir(parents=True)
            node_path.write_text(
                json.dumps(
                    {
                        'node_id': 'node-a',
                        'revision': 5,
                        'ssh_target': 'root@100.64.0.1',
                        'status': 'await_bootstrap_takeover',
                        'bootstrap_takeover': {
                            'state': 'waiting',
                            'approval_id': 'bootstrap-takeover:node-a:5',
                            'resume_token': 'bootstrap-takeover:node-a:5:resume',
                        },
                    }
                )
                + '\n',
                encoding='utf-8',
            )
            mod.phone_control_arm(
                {'group': 'remote', 'duration': '30s', 'operator_scopes': ['operator.admin']},
                root=root,
            )
            blocked = mod.bootstrap_execute_node(
                {
                    'node_id': 'node-a',
                    'ssh_target': 'root@100.64.0.1',
                    'operator_scopes': ['operator.admin'],
                },
                root=root,
            )

        self.assertEqual(blocked['status'], 'blocked')
        self.assertEqual(blocked['bootstrap_action'], 'wait_for_approval')
        self.assertEqual(blocked['bootstrap_action_reason'], 'bootstrap_takeover_not_approved')

    def test_bootstrap_execute_requires_expected_revision_for_approved_takeover(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_path = root / '.a9' / 'nodes' / 'node-a.json'
            node_path.parent.mkdir(parents=True)
            node_path.write_text(
                json.dumps(
                    {
                        'node_id': 'node-a',
                        'revision': 6,
                        'ssh_target': 'root@100.64.0.1',
                        'status': 'await_bootstrap_takeover',
                        'bootstrap_takeover': {
                            'state': 'approved',
                            'decision': 'resume_approved',
                        },
                    }
                )
                + '\n',
                encoding='utf-8',
            )
            mod.phone_control_arm(
                {'group': 'remote', 'duration': '30s', 'operator_scopes': ['operator.admin']},
                root=root,
            )
            original_run = mod.subprocess.run
            calls = []
            try:
                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    raise AssertionError('bootstrap execute should not run without expected_revision')

                mod.subprocess.run = fake_run
                result = mod.bootstrap_execute_node(
                    {
                        'node_id': 'node-a',
                        'ssh_target': 'root@100.64.0.1',
                        'operator_scopes': ['operator.admin'],
                    },
                    root=root,
                )
            finally:
                mod.subprocess.run = original_run
            record = json.loads(node_path.read_text(encoding='utf-8'))

        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(result['bootstrap_action_reason'], 'expected_revision_required')
        self.assertEqual(result['actual_revision'], 6)
        self.assertEqual(calls, [])
        self.assertEqual(record['revision'], 6)
        self.assertNotIn('bootstrap_execution', record)

    def test_bootstrap_execute_rejects_stale_approved_takeover_revision_before_ssh(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_path = root / '.a9' / 'nodes' / 'node-a.json'
            node_path.parent.mkdir(parents=True)
            node_path.write_text(
                json.dumps(
                    {
                        'node_id': 'node-a',
                        'revision': 6,
                        'ssh_target': 'root@100.64.0.1',
                        'status': 'await_bootstrap_takeover',
                        'bootstrap_takeover': {
                            'state': 'approved',
                            'decision': 'resume_approved',
                        },
                    }
                )
                + '\n',
                encoding='utf-8',
            )
            mod.phone_control_arm(
                {'group': 'remote', 'duration': '30s', 'operator_scopes': ['operator.admin']},
                root=root,
            )
            original_run = mod.subprocess.run
            calls = []
            try:
                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    raise AssertionError('bootstrap execute should not run on stale expected_revision')

                mod.subprocess.run = fake_run
                result = mod.bootstrap_execute_node(
                    {
                        'node_id': 'node-a',
                        'ssh_target': 'root@100.64.0.1',
                        'operator_scopes': ['operator.admin'],
                        'expected_revision': 5,
                    },
                    root=root,
                )
            finally:
                mod.subprocess.run = original_run
            record = json.loads(node_path.read_text(encoding='utf-8'))

        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(result['bootstrap_action_reason'], 'expected_revision_mismatch')
        self.assertEqual(result['expected_revision'], 5)
        self.assertEqual(result['actual_revision'], 6)
        self.assertEqual(calls, [])
        self.assertEqual(record['revision'], 6)
        self.assertNotIn('bootstrap_execution', record)

    def test_bootstrap_execute_runs_approved_takeover_with_matching_revision(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = 'A9 remote node prepared\n'

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_path = root / '.a9' / 'nodes' / 'node-a.json'
            node_path.parent.mkdir(parents=True)
            node_path.write_text(
                json.dumps(
                    {
                        'node_id': 'node-a',
                        'revision': 6,
                        'ssh_target': 'root@100.64.0.1',
                        'status': 'await_bootstrap_takeover',
                        'bootstrap_takeover': {
                            'state': 'approved',
                            'decision': 'resume_approved',
                        },
                    }
                )
                + '\n',
                encoding='utf-8',
            )
            mod.phone_control_arm(
                {'group': 'remote', 'duration': '30s', 'operator_scopes': ['operator.admin']},
                root=root,
            )
            original_run = mod.subprocess.run
            calls = []
            try:
                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.subprocess.run = fake_run
                result = mod.bootstrap_execute_node(
                    {
                        'node_id': 'node-a',
                        'ssh_target': 'root@100.64.0.1',
                        'operator_scopes': ['operator.admin'],
                        'expected_revision': 6,
                    },
                    root=root,
                )
            finally:
                mod.subprocess.run = original_run
            evidence_path_exists = Path(result['evidence_path']).exists()
            record = json.loads(node_path.read_text(encoding='utf-8'))

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['bootstrap_action'], 'continue')
        self.assertTrue(evidence_path_exists)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][0], 'ssh')
        self.assertEqual(record['revision'], 7)
        self.assertEqual(record['status'], 'registered')
        self.assertEqual(record['status_reason'], 'bootstrap_ok')
        self.assertEqual(record['bootstrap_execution']['action'], 'continue')
        self.assertEqual(record['bootstrap_execution']['result'], 'ok')
        self.assertEqual(record['bootstrap_execution']['return_code'], 0)
        self.assertFalse(record['bootstrap_execution']['timed_out'])
        self.assertEqual(record['bootstrap_execution']['previous_revision'], 6)
        self.assertEqual(record['bootstrap_execution']['new_revision'], 7)
        self.assertEqual(record['bootstrap_execution']['evidence_path'], result['evidence_path'])
        self.assertEqual(record['bootstrap_takeover']['state'], 'approved')
        self.assertEqual(record['bootstrap_takeover']['decision'], 'resume_approved')
        self.assertIn('recovery_hint', result)
        self.assertEqual(result['recovery_hint']['action'], 'observe')
        self.assertEqual(result['recovery_hint']['next_endpoint'], '/api/nodes/recovery-transcript')
        self.assertEqual(result['recovery_hint']['next_method'], 'GET')
        self.assertFalse(result['recovery_hint']['next_requires_arm'])

    def test_bootstrap_execute_records_node_state_on_failed_execution(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 2
            stdout = 'A9 remote bootstrap failed\n'

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_path = root / '.a9' / 'nodes' / 'node-a.json'
            node_path.parent.mkdir(parents=True)
            node_path.write_text(
                json.dumps(
                    {
                        'node_id': 'node-a',
                        'revision': 8,
                        'ssh_target': 'root@100.64.0.1',
                        'status': 'await_bootstrap_takeover',
                        'bootstrap_takeover': {
                            'state': 'approved',
                            'decision': 'resume_approved',
                        },
                    }
                )
                + '\n',
                encoding='utf-8',
            )
            mod.phone_control_arm(
                {'group': 'remote', 'duration': '30s', 'operator_scopes': ['operator.admin']},
                root=root,
            )
            original_run = mod.subprocess.run
            try:
                def fake_run(cmd, **kwargs):
                    return FakeProc()

                mod.subprocess.run = fake_run
                result = mod.bootstrap_execute_node(
                    {
                        'node_id': 'node-a',
                        'ssh_target': 'root@100.64.0.1',
                        'operator_scopes': ['operator.admin'],
                        'expected_revision': 8,
                    },
                    root=root,
                )
            finally:
                mod.subprocess.run = original_run
            record = json.loads(node_path.read_text(encoding='utf-8'))

        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['bootstrap_action'], 'repair')
        self.assertEqual(record['revision'], 9)
        self.assertEqual(record['status'], 'await_bootstrap_takeover')
        self.assertEqual(record['status_reason'], 'bootstrap_failed')
        self.assertEqual(record['bootstrap_execution']['action'], 'repair')
        self.assertEqual(record['bootstrap_execution']['result'], 'failed')
        self.assertEqual(record['bootstrap_execution']['return_code'], 2)
        self.assertFalse(record['bootstrap_execution']['timed_out'])
        self.assertEqual(record['bootstrap_execution']['previous_revision'], 8)
        self.assertEqual(record['bootstrap_execution']['new_revision'], 9)
        self.assertEqual(record['bootstrap_execution']['evidence_path'], result['evidence_path'])
        self.assertEqual(result['recovery_hint']['action'], 'repair')
        self.assertEqual(result['recovery_hint']['next_endpoint'], '/api/nodes/bootstrap-execute')
        self.assertEqual(result['recovery_hint']['next_method'], 'POST')
        self.assertTrue(result['recovery_hint']['next_requires_arm'])

    def test_bootstrap_execute_records_node_state_on_timeout_execution(self):
        mod = load_control_api()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_path = root / '.a9' / 'nodes' / 'node-a.json'
            node_path.parent.mkdir(parents=True)
            node_path.write_text(
                json.dumps(
                    {
                        'node_id': 'node-a',
                        'revision': 9,
                        'ssh_target': 'root@100.64.0.1',
                        'status': 'await_bootstrap_takeover',
                        'bootstrap_takeover': {
                            'state': 'approved',
                            'decision': 'resume_approved',
                        },
                    }
                )
                + '\n',
                encoding='utf-8',
            )
            mod.phone_control_arm(
                {'group': 'remote', 'duration': '30s', 'operator_scopes': ['operator.admin']},
                root=root,
            )
            original_run = mod.subprocess.run
            try:
                def fake_run(cmd, **kwargs):
                    raise subprocess.TimeoutExpired(cmd, timeout=0.1)

                mod.subprocess.run = fake_run
                result = mod.bootstrap_execute_node(
                    {
                        'node_id': 'node-a',
                        'ssh_target': 'root@100.64.0.1',
                        'operator_scopes': ['operator.admin'],
                        'expected_revision': 9,
                    },
                    root=root,
                )
            finally:
                mod.subprocess.run = original_run
            record = json.loads(node_path.read_text(encoding='utf-8'))

        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(result['bootstrap_action'], 'retry')
        self.assertTrue(result['timed_out'])
        self.assertEqual(record['revision'], 10)
        self.assertEqual(record['status'], 'await_bootstrap_takeover')
        self.assertEqual(record['status_reason'], 'bootstrap_timeout')
        self.assertEqual(record['bootstrap_execution']['action'], 'retry')
        self.assertEqual(record['bootstrap_execution']['result'], 'timeout')
        self.assertEqual(record['bootstrap_execution']['return_code'], 124)
        self.assertTrue(record['bootstrap_execution']['timed_out'])
        self.assertEqual(record['bootstrap_execution']['previous_revision'], 9)
        self.assertEqual(record['bootstrap_execution']['new_revision'], 10)
        self.assertEqual(record['bootstrap_execution']['evidence_path'], result['evidence_path'])
        self.assertEqual(result['recovery_hint']['action'], 'retry')
        self.assertEqual(result['recovery_hint']['next_endpoint'], '/api/nodes/bootstrap-execute')
        self.assertEqual(result['recovery_hint']['next_method'], 'POST')
        self.assertTrue(result['recovery_hint']['next_requires_arm'])

    def test_bootstrap_takeover_admission_duplicate_conflict_keeps_revision(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_path = root / ".a9" / "nodes" / "node-a.json"
            node_path.parent.mkdir(parents=True)
            node_path.write_text(json.dumps({"node_id": "node-a", "revision": 9}) + "\n", encoding="utf-8")

            result = mod.bootstrap_takeover_admission(
                {
                    "expected_revision": 8,
                    "reconnect_event": {
                        "status": "ok",
                        "kind": "gateway_reconnect_decision",
                        "action": "terminate",
                        "node_id": "node-a",
                    },
                },
                root=root,
            )
            record = json.loads(node_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["reason"], "expected_revision_mismatch")
        self.assertEqual(result["actual_revision"], 9)
        self.assertEqual(record["revision"], 9)

    def test_communication_action_plan_routes_terminal_reconnect_to_bootstrap_takeover_admission(self):
        mod = load_control_api()
        plan = mod.communication_action_plan(
            {
                "status": "needs_attention",
                "action": "await_bootstrap_takeover",
                "reason": "gateway_reconnect:policy_budget_exhausted",
                "priority_source": "gateway_reconnect",
                "layers": {
                    "gateway_reconnect": {
                        "status": "ok",
                        "kind": "gateway_reconnect_decision",
                        "action": "terminate",
                        "node_id": "node-a",
                    }
                },
            }
        )

        self.assertEqual(plan["plan_status"], "ready")
        self.assertEqual(plan["route"]["endpoint"], "/api/nodes/bootstrap-takeover-admission")
        self.assertEqual(plan["route"]["command"], "nodes.bootstrap.takeover.admit")
        self.assertFalse(plan["route"]["requires_arm"])
        self.assertEqual(plan["payload"]["reconnect_event"]["node_id"], "node-a")

    def test_bootstrap_execute_requires_arm_and_runs_script(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = "A9 remote node prepared\n"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocked = mod.bootstrap_execute_node(
                {
                    "ssh_target": "root@100.64.0.1",
                    "operator_scopes": ["operator.admin"],
                },
                root=root,
            )
            mod.phone_control_arm(
                {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                root=root,
            )
            original_run = mod.subprocess.run
            calls = []
            try:
                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.subprocess.run = fake_run
                result = mod.bootstrap_execute_node(
                    {
                        "ssh_target": "root@100.64.0.1",
                        "node_id": "remote/a",
                        "operator_scopes": ["operator.admin"],
                        "connect_timeout": 3,
                    },
                    root=root,
                )
            finally:
                mod.subprocess.run = original_run
            evidence_path_exists = Path(result["evidence_path"]).exists()

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["bootstrap_action"], "wait_for_approval")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["bootstrap_action"], "continue")
        self.assertTrue(evidence_path_exists)
        self.assertEqual(result["runtime_contract"]["bootstrap_mode"], "ssh_bootstrap_only")
        self.assertEqual(result["runtime_contract"]["runtime_mode"], "redis_api_runtime")
        self.assertEqual(calls[0][0][0], "ssh")
        self.assertIn("ConnectTimeout=3", calls[0][0])
        self.assertIn("cat > .a9/remote-node/heartbeat.sh", calls[0][0][-1])

    def test_heartbeat_repair_requires_arm_and_only_writes_heartbeat_contract(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = "A9 heartbeat repaired\n"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocked = mod.heartbeat_repair_node(
                {
                    "ssh_target": "root@100.64.0.1",
                    "operator_scopes": ["operator.admin"],
                },
                root=root,
            )
            mod.phone_control_arm(
                {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                root=root,
            )
            original_run = mod.subprocess.run
            calls = []
            try:
                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.subprocess.run = fake_run
                result = mod.heartbeat_repair_node(
                    {
                        "ssh_target": "root@100.64.0.1",
                        "node_id": "remote/a",
                        "worker_name": "remote-a",
                        "operator_scopes": ["operator.admin"],
                        "connect_timeout": 3,
                    },
                    root=root,
                )
            finally:
                mod.subprocess.run = original_run
            evidence_path_exists = Path(result["evidence_path"]).exists()

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["repair_action"], "wait_for_approval")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["repair_action"], "continue")
        self.assertTrue(evidence_path_exists)
        self.assertEqual(calls[0][0][0], "ssh")
        self.assertIn("ConnectTimeout=3", calls[0][0])
        self.assertIn('REMOTE_DIR="$HOME/a9-worker"', calls[0][0][-1])
        self.assertIn("cat > \"$REMOTE_DIR/.a9/remote-node/heartbeat.sh\"", calls[0][0][-1])
        self.assertNotIn("git pull", calls[0][0][-1])

    def test_tmux_plan_node_is_ssh_tailscale_first_and_non_executing(self):
        mod = load_control_api()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = mod.tmux_plan_node(
                {"ssh_target": "root@100.64.0.1", "session": "a9/main"},
                root=root,
            )

            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["transport"], "tailscale+ssh+tmux")
            self.assertEqual(result["transport_quality"]["quality"], "tailscale")
            self.assertEqual(result["node_id"], "root-100.64.0.1")
            self.assertEqual(result["session"], "a9-main")
            self.assertFalse(result["execution_enabled"])
            self.assertIn("ConnectTimeout=5", result["command_preview"][0])
            self.assertIn("tmux new-session", result["command_preview"][0][-1])
            evidence_path = Path(result["evidence_path"])
            self.assertTrue(evidence_path.exists())
            self.assertIn(".a9/nodes/evidence/root-100.64.0.1", str(evidence_path))
            evidence = mod.read_evidence_file(str(evidence_path), root=root)
            self.assertIn("tailscale+ssh+tmux", evidence["content"])

    def test_heartbeat_tmux_plan_node_is_non_executing_plan(self):
        mod = load_control_api()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = mod.heartbeat_tmux_plan_node(
                {"ssh_target": "root@100.64.0.1", "session": "a9/heartbeat", "remote_dir": "~/a9-worker"},
                root=root,
            )

            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["transport"], "tailscale+ssh+tmux")
            self.assertEqual(result["transport_quality"]["quality"], "tailscale")
            self.assertEqual(result["node_id"], "root-100.64.0.1")
            self.assertEqual(result["session"], "a9-heartbeat")
            self.assertFalse(result["execution_enabled"])
            self.assertIn("heartbeat loop", str(result["steps"]))
            self.assertIn("~/a9-worker/.a9/remote-node/heartbeat.sh", result["heartbeat_script"])
            self.assertNotIn("A9_HEARTBEAT_ONCE=1", result["command_preview"][0][-1])
            self.assertIn("tmux new-session", result["command_preview"][0][-1])
            self.assertIn(".a9/remote-node/heartbeat.sh", result["command_preview"][0][-1])
            evidence_path = Path(result["evidence_path"])
            self.assertTrue(evidence_path.exists())
            self.assertIn(".a9/nodes/evidence/root-100.64.0.1", str(evidence_path))
            evidence = mod.read_evidence_file(str(evidence_path), root=root)
            evidence_payload = json.loads(evidence["content"])
            self.assertEqual(evidence_payload["transport"], "tailscale+ssh+tmux")
            self.assertFalse(evidence_payload["execution_enabled"])

    def test_heartbeat_tmux_plan_node_smoke_test_uses_once_flag(self):
        mod = load_control_api()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default_plan = mod.heartbeat_tmux_plan_node(
                {"ssh_target": "root@100.64.0.1", "remote_dir": "~/a9-worker"},
                root=root,
            )
            smoke_plan = mod.heartbeat_tmux_plan_node(
                {"ssh_target": "root@100.64.0.1", "remote_dir": "~/a9-worker", "smoke_test": True},
                root=root,
            )

            self.assertNotIn("A9_HEARTBEAT_ONCE=1", default_plan["command_preview"][0][-1])
            self.assertIn("A9_HEARTBEAT_ONCE=1", smoke_plan["command_preview"][0][-1])

    def test_heartbeat_tmux_plan_node_quotes_remote_dir_and_script(self):
        mod = load_control_api()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = mod.heartbeat_tmux_plan_node(
                {
                    "ssh_target": "root@100.64.0.1",
                    "session": "a9/heartbeat",
                    "remote_dir": "/tmp/a9;bad",
                },
                root=root,
            )

            command = result["command_preview"][0][-1]
            self.assertIn("mkdir -p '/tmp/a9;bad'", command)
            self.assertIn("'/tmp/a9;bad/.a9/remote-node/heartbeat.sh'", command)
            self.assertNotIn("mkdir -p /tmp/a9;bad", command)
            self.assertIn("tmux new-session", command)
            self.assertIn("\"'\"'/tmp/a9;bad/.a9/remote-node/heartbeat.sh'\"'\"'", command)

    def test_heartbeat_tmux_plan_node_expands_default_home_path(self):
        mod = load_control_api()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = mod.heartbeat_tmux_plan_node(
                {"ssh_target": "root@100.64.0.1", "remote_dir": "~/a9-worker"},
                root=root,
            )

            command = result["command_preview"][0][-1]
            self.assertIn('"$HOME/a9-worker"', command)
            self.assertIn('"$HOME/a9-worker/.a9/remote-node/heartbeat.sh"', command)
            self.assertNotIn("'~/a9-worker'", command)

    def test_phone_control_requires_admin_and_expires_to_disarmed(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(PermissionError):
                mod.phone_control_arm({"group": "remote", "duration": "30s"}, root=root)

            armed = mod.phone_control_arm(
                {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                root=root,
            )
            self.assertEqual(armed["status"], "armed")
            self.assertIn("nodes.bootstrap.execute", armed["commands"])
            state_path = root / ".a9" / "control" / "phone_control.json"
            self.assertTrue(state_path.exists())

            disarmed = mod.phone_control_disarm({"operator_scopes": ["operator.admin"]}, root=root)
            self.assertEqual(disarmed["status"], "disarmed")
            self.assertFalse(state_path.exists())

            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "status": "armed",
                        "group": "remote",
                        "commands": ["nodes.bootstrap.execute"],
                        "armed_at": "2026-01-01T00:00:00+00:00",
                        "expires_at": "2026-01-01T00:00:01+00:00",
                    }
                ),
                encoding="utf-8",
            )
            expired = mod.phone_control_status(root=root)
            self.assertEqual(expired["status"], "disarmed")
            self.assertFalse(state_path.exists())

    def test_command_gate_follows_phone_control_arm_group(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            blocked = mod.command_gate("nodes.bootstrap.execute", root=root)
            self.assertFalse(blocked["allowed"])
            self.assertEqual(blocked["reason"], "phone_control_disarmed")

            mod.phone_control_arm(
                {"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]},
                root=root,
            )
            wrong_group = mod.command_gate("nodes.bootstrap.execute", root=root)
            self.assertFalse(wrong_group["allowed"])
            self.assertEqual(wrong_group["reason"], "command_not_in_current_arm_group")

            mod.phone_control_arm(
                {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                root=root,
            )
            allowed = mod.command_gate("nodes.bootstrap.execute", root=root)
            self.assertTrue(allowed["allowed"])
            self.assertEqual(allowed["status"], "allowed")
            allowed_probe = mod.command_gate("nodes.probe.execute", root=root)
            self.assertTrue(allowed_probe["allowed"])
            self.assertEqual(allowed_probe["status"], "allowed")
            allowed_tmux_status = mod.command_gate("nodes.tmux.status", root=root)
            self.assertTrue(allowed_tmux_status["allowed"])
            self.assertEqual(allowed_tmux_status["status"], "allowed")
            allowed_heartbeat = mod.command_gate("nodes.heartbeat.tmux.start", root=root)
            self.assertTrue(allowed_heartbeat["allowed"])
            self.assertEqual(allowed_heartbeat["status"], "allowed")

            unknown = mod.command_gate("not.real", root=root)
            self.assertFalse(unknown["allowed"])
            self.assertEqual(unknown["reason"], "unknown_command")

    def test_eval_override_requires_runtime_arm_and_writes_override(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = mod.ROOT
            original_supervisor_loader = mod.supervisor
            mod.ROOT = root
            supervisor = mod.supervisor()
            old_runs = supervisor.RUNS_DIR
            old_eval_store = supervisor.EVAL_STORE_DIR
            old_eval_runs = supervisor.EVAL_STORE_RUNS_DIR
            old_eval_overrides = supervisor.EVAL_STORE_OVERRIDES_DIR
            supervisor.RUNS_DIR = root / ".a9" / "runs"
            supervisor.EVAL_STORE_DIR = root / ".a9" / "eval_store"
            supervisor.EVAL_STORE_RUNS_DIR = supervisor.EVAL_STORE_DIR / "runs"
            supervisor.EVAL_STORE_OVERRIDES_DIR = supervisor.EVAL_STORE_DIR / "overrides"
            try:
                mod.supervisor = lambda: supervisor
                run_dir = supervisor.RUNS_DIR / "run-eval"
                run_dir.mkdir(parents=True)
                record = {
                    "schema": "a9.eval_store_record.v1",
                    "record_id": "eval-run-eval",
                    "run_id": "run-eval",
                    "task_id": "eval-task",
                    "status": "monitor-blocked",
                    "rule_monitor": {
                        "recommended_action": "block_and_rewrite_task",
                        "failed_experts": ["data_model_expert"],
                        "gates": {"hard_gate": {"status": "fail", "failed_experts": ["data_model_expert"]}},
                    },
                    "eval_contract": {"path": str(run_dir / "moe_eval_contract.json")},
                }
                record["record_hash"] = supervisor.sha256_text(
                    supervisor.stable_json({key: value for key, value in record.items() if key != "record_hash"})
                )
                (run_dir / "eval_store_record.json").write_text(json.dumps(record), encoding="utf-8")

                blocked = mod.eval_override(
                    {
                        "run_id": "run-eval",
                        "action": "continue",
                        "reason": "false positive",
                        "operator_scopes": ["operator.admin"],
                    }
                )
                mod.phone_control_arm(
                    {"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]},
                    root=root,
                )
                result = mod.eval_override(
                    {
                        "run_id": "run-eval",
                        "action": "continue",
                        "reason": "monitor false positive; state evidence is sufficient",
                        "actor": "mobile-human",
                        "evidence_refs": [".a9/runs/run-eval/state.json"],
                        "operator_scopes": ["operator.admin"],
                    }
                )
                override = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
            finally:
                mod.ROOT = old_root
                mod.supervisor = original_supervisor_loader
                supervisor.RUNS_DIR = old_runs
                supervisor.EVAL_STORE_DIR = old_eval_store
                supervisor.EVAL_STORE_RUNS_DIR = old_eval_runs
                supervisor.EVAL_STORE_OVERRIDES_DIR = old_eval_overrides

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["gate"]["reason"], "phone_control_disarmed")
        self.assertEqual(result["status"], "written")
        self.assertEqual(result["command"], "eval.override")
        self.assertEqual(result["gate"]["status"], "allowed")
        self.assertEqual(override["actor"], "mobile-human")
        self.assertEqual(override["training_label"]["human_action"], "continue")

    def test_eval_override_post_route_calls_handler(self):
        mod = load_control_api()
        original_eval_override = mod.eval_override
        post_body = json.dumps(
            {
                "run_id": "run-eval",
                "action": "continue",
                "reason": "false positive",
                "operator_scopes": ["operator.admin"],
            }
        ).encode("utf-8")
        captured = {"status": None, "payload": None, "called_payload": None}
        try:
            def fake_eval_override(payload):
                captured["called_payload"] = payload
                return {"status": "written", "command": "eval.override", "run_id": payload["run_id"]}

            mod.eval_override = fake_eval_override

            class DummyEvalOverridePostHandler:
                path = "/api/eval/override"
                headers = {"Content-Length": str(len(post_body))}
                rfile = io.BytesIO(post_body)

                def write_json(self, status, payload):
                    captured["status"] = status
                    captured["payload"] = payload

            mod.ControlHandler.do_POST(DummyEvalOverridePostHandler())
        finally:
            mod.eval_override = original_eval_override

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["command"], "eval.override")

    def test_runtime_plan_decision_approve_requires_runtime_arm_and_promotes_items(self):
        mod = load_control_api()
        calls = []

        class FakeSupervisor:
            @staticmethod
            def active_plan_id():
                return "active-plan"

            @staticmethod
            def approve_plan_decision_backlog(**kwargs):
                calls.append(kwargs)
                return {
                    "status": "approved",
                    "plan_id": kwargs["plan_id"],
                    "approved_count": 2,
                    "source_run": kwargs["source_run"],
                    "approval_path": "/tmp/decision_approval.md",
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_supervisor = mod.supervisor
            original_audit = mod.enqueue_service_control_audit
            audit_calls = []
            try:
                mod.supervisor = lambda: FakeSupervisor
                mod.enqueue_service_control_audit = lambda event, *, root: audit_calls.append((event, root))
                blocked = mod.runtime_plan_decision_approve(
                    {
                        "operator_scopes": ["operator.admin"],
                        "reason": "approve after review",
                        "source_run": "run-a",
                        "item_ids": ["candidate-1"],
                    },
                    root=root,
                )
                mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
                invalid = mod.runtime_plan_decision_approve(
                    {
                        "operator_scopes": ["operator.admin"],
                        "reason": "approve after review",
                        "actor": "mobile-human",
                        "source_run": "run-a",
                        "evidence_refs": ["/tmp/run-a/summary.json"],
                    },
                    root=root,
                )
                result = mod.runtime_plan_decision_approve(
                    {
                        "operator_scopes": ["operator.admin"],
                        "reason": "approve after review",
                        "actor": "mobile-human",
                        "source_run": "run-a",
                        "item_ids": ["candidate-1", "candidate-2"],
                        "evidence_refs": ["/tmp/run-a/summary.json"],
                    },
                    root=root,
                )
            finally:
                mod.supervisor = original_supervisor
                mod.enqueue_service_control_audit = original_audit

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["gate"]["reason"], "phone_control_disarmed")
        self.assertEqual(invalid["status"], "invalid_request")
        self.assertEqual(invalid["reason"], "item_ids_required")
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["command"], "plan.decision.approve")
        self.assertEqual(result["approved_count"], 2)
        self.assertEqual(calls[0]["plan_id"], "active-plan")
        self.assertEqual(calls[0]["source_run"], "run-a")
        self.assertEqual(calls[0]["actor"], "mobile-human")
        self.assertEqual(calls[0]["item_ids"], ["candidate-1", "candidate-2"])
        self.assertEqual(calls[0]["evidence_refs"], ["/tmp/run-a/summary.json"])
        self.assertEqual(audit_calls[-1][0]["action"], "plan_decision_approve")

    def test_runtime_plan_decision_approve_post_route_calls_handler(self):
        mod = load_control_api()
        original_handler = mod.runtime_plan_decision_approve
        captured = {}

        def fake_runtime_plan_decision_approve(payload):
            captured["payload"] = payload
            return {"status": "approved", "command": "plan.decision.approve"}

        body = json.dumps({"operator_scopes": ["operator.admin"], "reason": "approve"}).encode("utf-8")

        class DummyPlanDecisionApprovePostHandler:
            path = "/api/runtime/plan-decision-approve"
            headers = {"Content-Length": str(len(body))}
            rfile = io.BytesIO(body)

            def write_json(self, status, payload):
                captured["status"] = status
                captured["response"] = payload

        try:
            mod.runtime_plan_decision_approve = fake_runtime_plan_decision_approve
            mod.ControlHandler.do_POST(DummyPlanDecisionApprovePostHandler())
        finally:
            mod.runtime_plan_decision_approve = original_handler

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["response"]["command"], "plan.decision.approve")
        self.assertEqual(captured["payload"]["reason"], "approve")

    def test_heartbeat_tmux_start_requires_arm_and_uses_persisted_plan(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = "heartbeat tmux starting\n"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = mod.heartbeat_tmux_plan_node({"ssh_target": "root@100.64.0.1", "session": "a9/heartbeat"}, root=root)

            blocked = mod.heartbeat_tmux_start_node(
                {
                    "evidence_path": plan["evidence_path"],
                    "operator_scopes": ["operator.admin"],
                },
                root=root,
            )
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(blocked["gate"]["reason"], "phone_control_disarmed")
            self.assertEqual(blocked["heartbeat_action"], "wait_for_approval")
            self.assertEqual(blocked["heartbeat_action_reason"], "phone_control_disarmed")

            mod.phone_control_arm(
                {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                root=root,
            )
            original_run = mod.subprocess.run
            calls = []
            try:
                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.subprocess.run = fake_run
                result = mod.heartbeat_tmux_start_node(
                    {
                        "evidence_path": plan["evidence_path"],
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
            finally:
                mod.subprocess.run = original_run

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["return_code"], 0)
            self.assertEqual(result["heartbeat_action"], "continue")
            self.assertEqual(result["heartbeat_action_reason"], "heartbeat_tmux_start_ok")
            self.assertEqual(result["reason"], "heartbeat_tmux_start_ok")
            self.assertIn("heartbeat tmux starting", result["output"])
            self.assertEqual(calls[0][0][0], "ssh")
            self.assertIn("ConnectTimeout=5", calls[0][0])
            self.assertIn("tmux new-session", calls[0][0][-1])
            self.assertIn(".a9/remote-node/heartbeat.sh", calls[0][0][-1])
            self.assertTrue(Path(result["evidence_path"]).exists())

    def test_heartbeat_tmux_start_records_timeout_as_retry(self):
        mod = load_control_api()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = mod.heartbeat_tmux_plan_node({"ssh_target": "root@100.64.0.1", "session": "a9/heartbeat"}, root=root)
            mod.phone_control_arm(
                {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                root=root,
            )
            original_run = mod.subprocess.run
            try:
                def fake_run(cmd, **kwargs):
                    raise mod.subprocess.TimeoutExpired(cmd=cmd, timeout=1)

                mod.subprocess.run = fake_run
                result = mod.heartbeat_tmux_start_node(
                    {
                        "evidence_path": plan["evidence_path"],
                        "operator_scopes": ["operator.admin"],
                        "timeout_seconds": 1,
                    },
                    root=root,
                )
            finally:
                mod.subprocess.run = original_run

            self.assertEqual(result["status"], "timeout")
            self.assertEqual(result["return_code"], 124)
            self.assertTrue(result["timed_out"])
            self.assertEqual(result["heartbeat_action"], "retry")
            self.assertEqual(result["heartbeat_action_reason"], "heartbeat_tmux_start_timeout")
            self.assertEqual(result["reason"], "heartbeat_tmux_start_timeout")
            self.assertTrue(Path(result["evidence_path"]).exists())

    def test_heartbeat_tmux_start_non_zero_return_is_failed_and_repair(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 3
            stdout = "non-zero heartbeat start output"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = mod.heartbeat_tmux_plan_node(
                {"ssh_target": "root@100.64.0.1", "session": "a9/heartbeat"},
                root=root,
            )
            mod.phone_control_arm(
                {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                root=root,
            )
            original_run = mod.subprocess.run
            try:
                def fake_run(cmd, **kwargs):
                    return FakeProc()

                mod.subprocess.run = fake_run
                result = mod.heartbeat_tmux_start_node(
                    {
                        "evidence_path": plan["evidence_path"],
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
            finally:
                mod.subprocess.run = original_run

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["heartbeat_action"], "repair")
            self.assertEqual(result["heartbeat_action_reason"], "heartbeat_tmux_start_failed")
            self.assertEqual(result["reason"], "heartbeat_tmux_start_failed")
            self.assertEqual(result["return_code"], 3)
            self.assertIn("non-zero heartbeat start output", result["output"])
            self.assertTrue(Path(result["evidence_path"]).exists())

            evidence = mod.read_evidence_file(str(result["evidence_path"]), root=root)
            evidence_payload = json.loads(evidence["content"])
            self.assertEqual(evidence_payload["status"], "failed")
            self.assertEqual(evidence_payload["heartbeat_action"], "repair")
            self.assertEqual(evidence_payload["heartbeat_action_reason"], "heartbeat_tmux_start_failed")
            self.assertEqual(evidence_payload["return_code"], 3)
            self.assertEqual(evidence_payload["output"], "non-zero heartbeat start output")

    def test_heartbeat_tmux_start_with_non_heartbeat_plan_path_raises(self):
        mod = load_control_api()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = mod.tmux_plan_node({"ssh_target": "root@100.64.0.1", "session": "a9/main"}, root=root)
            mod.phone_control_arm(
                {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                root=root,
            )
            original_run = mod.subprocess.run
            calls = []
            try:
                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                class FakeProc:
                    returncode = 0
                    stdout = "should not run"

                mod.subprocess.run = fake_run
                with self.assertRaises(ValueError) as exc:
                    mod.heartbeat_tmux_start_node(
                        {
                            "evidence_path": plan["evidence_path"],
                            "operator_scopes": ["operator.admin"],
                        },
                        root=root,
                    )
            finally:
                mod.subprocess.run = original_run

            self.assertEqual(str(exc.exception), "evidence is not a heartbeat tmux plan")
            self.assertEqual(calls, [])

    def test_api_nodes_heartbeat_tmux_start_uses_wrapped_root(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = "heartbeat tmux start route ok"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = mod.heartbeat_tmux_plan_node(
                {"ssh_target": "root@100.64.0.1", "session": "a9/heartbeat"},
                root=root,
            )

            original_start_node = mod.heartbeat_tmux_start_node
            original_run = mod.subprocess.run
            try:
                mod.phone_control_arm(
                    {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                    root=root,
                )
                mod.heartbeat_tmux_start_node = lambda payload: original_start_node(payload, root=root)
                mod.subprocess.run = lambda cmd, **kwargs: FakeProc()

                post_payload = {
                    "evidence_path": plan["evidence_path"],
                    "operator_scopes": ["operator.admin"],
                }
                post_body = json.dumps(post_payload).encode("utf-8")
                captured = {"status": None, "payload": None}

                class DummyHeartbeatTmuxStartPostHandler:
                    path = "/api/nodes/heartbeat-tmux-start"
                    headers = {"Content-Length": str(len(post_body))}
                    rfile = io.BytesIO(post_body)

                    def write_json(self, status, payload):
                        captured["status"] = status
                        captured["payload"] = payload

                mod.ControlHandler.do_POST(DummyHeartbeatTmuxStartPostHandler())
            finally:
                mod.heartbeat_tmux_start_node = original_start_node
                mod.subprocess.run = original_run

            self.assertEqual(captured["status"], 200)
            self.assertEqual(captured["payload"]["status"], "ok")
            self.assertTrue(Path(captured["payload"]["evidence_path"]).exists())

    def test_api_nodes_heartbeat_tmux_start_missing_evidence_path_returns_bad_request(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = "heartbeat tmux start should not run"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_start_node = mod.heartbeat_tmux_start_node
            original_run = mod.subprocess.run
            calls = []
            try:
                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.phone_control_arm(
                    {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                    root=root,
                )
                mod.heartbeat_tmux_start_node = lambda payload: original_start_node(payload, root=root)
                mod.subprocess.run = fake_run

                post_body = json.dumps({"operator_scopes": ["operator.admin"]}).encode("utf-8")
                captured = {"status": None, "payload": None}

                class DummyHeartbeatTmuxStartPostHandler:
                    path = "/api/nodes/heartbeat-tmux-start"
                    headers = {"Content-Length": str(len(post_body))}
                    rfile = io.BytesIO(post_body)

                    def write_json(self, status, payload):
                        captured["status"] = status
                        captured["payload"] = payload

                mod.ControlHandler.do_POST(DummyHeartbeatTmuxStartPostHandler())
            finally:
                mod.heartbeat_tmux_start_node = original_start_node
                mod.subprocess.run = original_run

            self.assertEqual(captured["status"], 400)
            self.assertIn("evidence_path is required", captured["payload"]["error"])
            self.assertEqual(calls, [])

    def test_tmux_ensure_requires_arm_and_uses_persisted_plan(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = "tmux ready\n"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = mod.tmux_plan_node({"ssh_target": "root@100.64.0.1", "session": "a9/main"}, root=root)

            blocked = mod.tmux_ensure_node(
                {
                    "evidence_path": plan["evidence_path"],
                    "operator_scopes": ["operator.admin"],
                },
                root=root,
            )
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(blocked["gate"]["reason"], "phone_control_disarmed")
            self.assertEqual(blocked["tmux_action"], "wait_for_approval")
            self.assertEqual(blocked["tmux_action_reason"], "phone_control_disarmed")

            mod.phone_control_arm(
                {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                root=root,
            )
            original_run = mod.subprocess.run
            calls = []
            try:
                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.subprocess.run = fake_run
                result = mod.tmux_ensure_node(
                    {
                        "evidence_path": plan["evidence_path"],
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
            finally:
                mod.subprocess.run = original_run

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["return_code"], 0)
            self.assertEqual(result["tmux_action"], "continue")
            self.assertEqual(result["tmux_action_reason"], "tmux_ensure_ok")
            self.assertEqual(result["reason"], "tmux_ensure_ok")
            self.assertIn("tmux ready", result["output"])
            self.assertEqual(calls[0][0][0], "ssh")
            self.assertIn("ConnectTimeout=5", calls[0][0])
            self.assertIn("tmux new-session", calls[0][0][-1])
            self.assertTrue(Path(result["evidence_path"]).exists())

    def test_tmux_ensure_records_timeout_as_evidence(self):
        mod = load_control_api()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = mod.tmux_plan_node({"ssh_target": "root@100.64.0.1", "session": "a9/main"}, root=root)
            mod.phone_control_arm(
                {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                root=root,
            )
            original_run = mod.subprocess.run
            try:
                def fake_run(cmd, **kwargs):
                    raise mod.subprocess.TimeoutExpired(cmd=cmd, timeout=1)

                mod.subprocess.run = fake_run
                result = mod.tmux_ensure_node(
                    {
                        "evidence_path": plan["evidence_path"],
                        "operator_scopes": ["operator.admin"],
                        "timeout_seconds": 1,
                    },
                    root=root,
                )
            finally:
                mod.subprocess.run = original_run

            self.assertEqual(result["status"], "timeout")
            self.assertEqual(result["return_code"], 124)
            self.assertTrue(result["timed_out"])
            self.assertEqual(result["tmux_action"], "retry")
            self.assertEqual(result["tmux_action_reason"], "tmux_ensure_timeout")
            self.assertEqual(result["reason"], "tmux_ensure_timeout")
            self.assertTrue(Path(result["evidence_path"]).exists())

    def test_tmux_status_is_read_only_and_writes_evidence(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = ""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = mod.tmux_plan_node({"ssh_target": "root@100.64.0.1", "session": "a9/main"}, root=root)
            original_run = mod.subprocess.run
            calls = []
            try:
                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.subprocess.run = fake_run
                result = mod.tmux_status_node({"evidence_path": plan["evidence_path"]}, root=root)
            finally:
                mod.subprocess.run = original_run

            self.assertEqual(result["status"], "exists")
            self.assertEqual(result["tmux_action"], "continue")
            self.assertEqual(result["tmux_action_reason"], "tmux_session_exists")
            self.assertEqual(result["reason"], "tmux_session_exists")
            self.assertEqual(
                calls[0][0][-2:],
                ["root@100.64.0.1", "tmux has-session -t a9-main"],
            )
            self.assertIn("ConnectTimeout=5", calls[0][0])
            self.assertTrue(Path(result["evidence_path"]).exists())

    def test_fake_ssh_lifecycle_probe_tmux_heartbeat_updates_node_status(self):
        mod = load_control_api()

        class FakeRemote:
            @staticmethod
            def ssh_base(target, *, connect_timeout=10, identity_file=""):
                return [
                    "echo",
                    "host=100.64.0.1\nuser=root\nkernel=Linux test\npython3=/usr/bin/python3\ntmux=tmux 3.2\n",
                ]

            @staticmethod
            def remote_probe_script():
                return "ignored"

            @staticmethod
            def parse_probe(text):
                return {
                    line.split("=", 1)[0]: line.split("=", 1)[1]
                    for line in text.splitlines()
                    if "=" in line
                }

            @staticmethod
            def classify_probe_result(return_code, output):
                return {
                    "probe_action": "continue",
                    "probe_action_reason": "probe_ok",
                    "required_missing": [],
                    "optional_missing": [],
                }

        class FakeProc:
            returncode = 0
            stdout = ""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_remote = mod.remote
            original_run = mod.subprocess.run
            calls = []
            try:
                mod.remote = lambda: FakeRemote

                probe = mod.probe_node({"ssh_target": "root@100.64.0.1"}, root=root)
                tmux_plan = mod.tmux_plan_node({"ssh_target": "root@100.64.0.1", "session": "a9/main"}, root=root)
                heartbeat_plan = mod.heartbeat_tmux_plan_node(
                    {"ssh_target": "root@100.64.0.1", "session": "a9/heartbeat"},
                    root=root,
                )

                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.subprocess.run = fake_run

                tmux_status = mod.tmux_status_node({"evidence_path": tmux_plan["evidence_path"]}, root=root)
                mod.phone_control_arm(
                    {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                    root=root,
                )
                heartbeat_start = mod.heartbeat_tmux_start_node(
                    {
                        "evidence_path": heartbeat_plan["evidence_path"],
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
                self.assertTrue(Path(tmux_status["evidence_path"]).exists())
                self.assertTrue(Path(heartbeat_start["evidence_path"]).exists())
            finally:
                mod.subprocess.run = original_run
                mod.remote = original_remote

            status = mod.node_status(root)
            node = status["nodes"][0]

        self.assertEqual(probe["status"], "ok")
        self.assertEqual(probe["probe_action"], "continue")
        self.assertEqual(tmux_status["status"], "exists")
        self.assertEqual(heartbeat_start["status"], "ok")
        self.assertEqual(len(calls), 2)
        for cmd, _kwargs in calls:
            self.assertEqual(cmd[0], "ssh")
            self.assertIn("ConnectTimeout=5", cmd)

        self.assertEqual(node["last_probe_action"], "continue")
        self.assertEqual(node["tmux_action"], "continue")
        self.assertEqual(node["tmux_status"], "exists")
        self.assertTrue(node["tmux_evidence_path"])
        self.assertEqual(node["heartbeat_start_action"], "continue")
        self.assertEqual(node["heartbeat_start_status"], "ok")
        self.assertTrue(node["heartbeat_start_evidence_path"])
        self.assertEqual(node["connection_action"], "continue")

    def test_fake_ssh_lifecycle_tmux_missing_then_heartbeat_start_failed_keeps_both_evidence(self):
        mod = load_control_api()

        class FakeRemote:
            @staticmethod
            def ssh_base(target, *, connect_timeout=10, identity_file=""):
                return [
                    "echo",
                    "host=100.64.0.1\nuser=root\nkernel=Linux test\npython3=/usr/bin/python3\ntmux=tmux 3.2\n",
                ]

            @staticmethod
            def remote_probe_script():
                return "ignored"

            @staticmethod
            def parse_probe(text):
                return {
                    line.split("=", 1)[0]: line.split("=", 1)[1]
                    for line in text.splitlines()
                    if "=" in line
                }

            @staticmethod
            def classify_probe_result(return_code, output):
                return {
                    "probe_action": "continue",
                    "probe_action_reason": "probe_ok",
                    "required_missing": [],
                    "optional_missing": [],
                }

        class MissingProc:
            returncode = 1
            stdout = "can't find session"

        class HeartbeatFailProc:
            returncode = 7
            stdout = "heartbeat start failed"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_remote = mod.remote
            original_run = mod.subprocess.run
            calls = []
            try:
                mod.remote = lambda: FakeRemote
                probe = mod.probe_node({"ssh_target": "root@100.64.0.1"}, root=root)
                tmux_plan = mod.tmux_plan_node({"ssh_target": "root@100.64.0.1", "session": "a9/main"}, root=root)

                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    remote_cmd = cmd[-1]
                    if "tmux has-session -t a9-main" in remote_cmd:
                        return MissingProc()
                    if ".a9/remote-node/heartbeat.sh" in remote_cmd:
                        return HeartbeatFailProc()
                    raise AssertionError(f"unexpected command: {cmd}")

                mod.subprocess.run = fake_run
                tmux_status = mod.tmux_status_node({"evidence_path": tmux_plan["evidence_path"]}, root=root)

                heartbeat_plan = mod.heartbeat_tmux_plan_node(
                    {"ssh_target": "root@100.64.0.1", "session": "a9/heartbeat"},
                    root=root,
                )
                mod.phone_control_arm(
                    {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                    root=root,
                )
                heartbeat_start = mod.heartbeat_tmux_start_node(
                    {
                        "evidence_path": heartbeat_plan["evidence_path"],
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
            finally:
                mod.subprocess.run = original_run
                mod.remote = original_remote

            status = mod.node_status(root)
            node = status["nodes"][0]

            self.assertEqual(probe["status"], "ok")
            self.assertEqual(tmux_status["status"], "missing")
            self.assertEqual(tmux_status["tmux_action"], "repair")
            self.assertEqual(heartbeat_start["status"], "failed")
            self.assertEqual(heartbeat_start["heartbeat_action"], "repair")
            self.assertEqual(heartbeat_start["return_code"], 7)
            self.assertEqual(len(calls), 2)
            for cmd, _kwargs in calls:
                self.assertEqual(cmd[0], "ssh")
                self.assertIn("ConnectTimeout=5", cmd)

            self.assertTrue(Path(tmux_status["evidence_path"]).exists())
            self.assertTrue(Path(heartbeat_start["evidence_path"]).exists())
            self.assertEqual(node["tmux_status"], "missing")
            self.assertEqual(node["tmux_action"], "repair")
            self.assertTrue(node["tmux_evidence_path"])
            self.assertEqual(node["heartbeat_start_status"], "failed")
            self.assertEqual(node["heartbeat_start_action"], "repair")
            self.assertTrue(node["heartbeat_start_evidence_path"])
            self.assertEqual(node["last_probe_action"], "continue")
            self.assertEqual(node["connection_action"], "continue")

    def test_tmux_plan_parses_target_port_and_identity(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = mod.tmux_plan_node(
                {"ssh_target": "root@100.64.0.1:2200", "session": "a9/main", "identity_file": "/tmp/key"},
                root=root,
            )

            command = result["command_preview"][0]
            self.assertIn("-p", command)
            self.assertIn("2200", command)
            self.assertIn("-i", command)
            self.assertIn("/tmp/key", command)
            self.assertEqual(
                command[-2:],
                [
                    "root@100.64.0.1",
                    "mkdir -p ~/a9-worker && (tmux has-session -t a9-main 2>/dev/null || tmux new-session -d -s a9-main -c ~/a9-worker)",
                ],
            )

    def test_tmux_status_records_timeout_as_evidence(self):
        mod = load_control_api()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = mod.tmux_plan_node({"ssh_target": "root@100.64.0.1", "session": "a9/main"}, root=root)
            original_run = mod.subprocess.run
            try:
                def fake_run(cmd, **kwargs):
                    raise mod.subprocess.TimeoutExpired(cmd=cmd, timeout=1)

                mod.subprocess.run = fake_run
                result = mod.tmux_status_node({"evidence_path": plan["evidence_path"], "timeout_seconds": 1}, root=root)
            finally:
                mod.subprocess.run = original_run

            self.assertEqual(result["status"], "timeout")
            self.assertEqual(result["return_code"], 124)
            self.assertTrue(result["timed_out"])
            self.assertEqual(result["tmux_action"], "retry")
            self.assertEqual(result["tmux_action_reason"], "tmux_status_timeout")
            self.assertEqual(result["reason"], "tmux_status_timeout")
            self.assertTrue(Path(result["evidence_path"]).exists())

    def test_tmux_status_maps_missing_to_repair_action(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 1
            stdout = "can't find session"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = mod.tmux_plan_node({"ssh_target": "root@100.64.0.1", "session": "a9/main"}, root=root)
            original_run = mod.subprocess.run
            try:
                mod.subprocess.run = lambda cmd, **kwargs: FakeProc()
                result = mod.tmux_status_node({"evidence_path": plan["evidence_path"]}, root=root)
            finally:
                mod.subprocess.run = original_run

            self.assertEqual(result["status"], "missing")
            self.assertEqual(result["tmux_action"], "repair")
            self.assertEqual(result["tmux_action_reason"], "tmux_session_missing")
            self.assertEqual(result["reason"], "tmux_session_missing")

    def test_list_node_evidence_returns_recent_items(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = mod.tmux_plan_node({"ssh_target": "root@100.64.0.1", "session": "a9/main"}, root=root)
            all_items = mod.list_node_evidence(root=root)
            node_items = mod.list_node_evidence("root@100.64.0.1", root=root)

            self.assertEqual(all_items["status"], "ok")
            self.assertEqual(all_items["count"], 1)
            self.assertEqual(all_items["items"][0]["node_id"], "root-100.64.0.1")
            self.assertEqual(all_items["items"][0]["kind"], "tmux-plan")
            self.assertEqual(all_items["items"][0]["path"], plan["evidence_path"])
            self.assertEqual(node_items["items"][0]["session"], "a9-main")

    def test_list_node_evidence_exposes_compact_action_timeline(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = mod.write_node_evidence(
                "heartbeat-repair",
                "root@100.64.0.1",
                {
                    "status": "ok",
                    "target": "root@100.64.0.1",
                    "repair_action": "continue",
                    "repair_action_reason": "heartbeat_script_repaired",
                    "return_code": 0,
                    "timed_out": False,
                    "output": "large raw output should stay in evidence file",
                },
                root=root,
            )

            result = mod.list_node_evidence("root@100.64.0.1", root=root, limit=20)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["limit"], 20)
            self.assertEqual(result["items"][0]["kind"], "heartbeat-repair")
            self.assertEqual(result["items"][0]["action"], "continue")
            self.assertEqual(result["items"][0]["reason"], "heartbeat_script_repaired")
            self.assertEqual(result["items"][0]["return_code"], 0)
            self.assertFalse(result["items"][0]["timed_out"])
            self.assertEqual(result["items"][0]["path"], str(path))
            self.assertNotIn("output", result["items"][0])

    def test_recovery_loop_latest_reports_missing_and_compact_latest(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = mod.recovery_loop_latest(root=root)
            self.assertEqual(missing["status"], "missing")
            latest = root / ".a9" / "services" / "recovery-loop-latest.json"
            latest.parent.mkdir(parents=True)
            latest.write_text(
                json.dumps(
                        {
                            "status": "ok",
                            "checked_at": "2026-05-29T19:02:55+00:00",
                            "controller_url": "http://127.0.0.1:8787",
                            "cycle_status": "ok",
                            "step_count": 1,
                            "risk_count": 0,
                            "execute": False,
                            "communication_execute_enabled": False,
                            "communication_plan_status": "ready",
                            "communication_action": "intervene",
                            "communication_priority_source": "recovery_loop",
                            "communication_route": {"endpoint": "/api/nodes/recovery-cycle"},
                            "communication_route_execution": {
                                "status": "ok",
                                "kind": "communication_route_execution",
                                "reason": "observe_only",
                                "route": {
                                    "endpoint": "/api/nodes/recovery-cycle",
                                    "command": "nodes.recovery.cycle",
                                    "method": "POST",
                                },
                                "payload": {
                                    "communication": {
                                        "action": "intervene",
                                        "priority_source": "recovery_loop",
                                    },
                                    "max_actions": 1,
                                    "operator_scopes": ["operator.admin"],
                                    "run_id": "run-2026-06-02",
                                },
                            },
                            "communication_observation": {
                                "current_key": "recovery_loop:intervene:ready",
                                "streak": 2,
                                "recommendation": "candidate_for_repair_one",
                                "auto_execute": False,
                        },
                        "communication_repair_suggestions": {
                            "status": "ok",
                            "pending_count": 1,
                            "pending": [
                                {
                                    "suggestion_id": "recovery_loop-intervene-ready",
                                    "route": {"endpoint": "/api/nodes/recovery-cycle"},
                                    "auto_execute": False,
                                }
                            ],
                        },
                        "cycle": {
                            "summary": {"risk_count": 0},
                            "steps": [{"node_id": "node-a", "status": "planned"}],
                            "large_raw_field": "not needed by phone",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = mod.recovery_loop_latest(root=root)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["cycle_status"], "ok")
            self.assertEqual(result["step_count"], 1)
            self.assertEqual(result["communication_plan_status"], "ready")
            self.assertEqual(result["communication_action"], "intervene")
            self.assertEqual(result["communication_priority_source"], "recovery_loop")
            self.assertFalse(result["communication_execute_enabled"])
            self.assertEqual(result["communication_route_execution"]["status"], "ok")
            self.assertEqual(result["communication_route_execution"]["reason"], "observe_only")
            self.assertEqual(result["communication_route_execution"]["payload"]["communication"]["action"], "intervene")
            self.assertEqual(result["communication_route"]["endpoint"], "/api/nodes/recovery-cycle")
            self.assertEqual(result["communication_observation"]["streak"], 2)
            self.assertEqual(result["communication_observation"]["recommendation"], "candidate_for_repair_one")
            self.assertFalse(result["communication_observation"]["auto_execute"])
            self.assertEqual(result["communication_repair_suggestions"]["pending_count"], 1)
            self.assertEqual(result["communication_repair_suggestions"]["pending"][0]["suggestion_id"], "recovery_loop-intervene-ready")
            self.assertEqual(result["steps"][0]["node_id"], "node-a")
            self.assertNotIn("cycle", result)

    def test_communication_repair_suggestions_endpoint_returns_pending_queue(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            suggestions = root / ".a9" / "services" / "communication-repair-suggestions.json"
            suggestions.parent.mkdir(parents=True)
            suggestions.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "updated_at": "2026-06-01T00:01:00+00:00",
                        "mode": "observe_only",
                        "pending_count": 1,
                        "pending": [
                            {
                                "suggestion_id": "recovery_loop-intervene-ready",
                                "status": "pending",
                                "route": {"endpoint": "/api/nodes/recovery-cycle"},
                                "auto_execute": False,
                            }
                        ],
                        "last_observation": {"current_key": "recovery_loop:intervene:ready", "streak": 2},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = mod.communication_repair_suggestions(root=root)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(result["pending"][0]["suggestion_id"], "recovery_loop-intervene-ready")
        self.assertFalse(result["pending"][0]["auto_execute"])

    def test_communication_repair_suggestion_review_approves_and_audits_async(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            suggestions = root / ".a9" / "services" / "communication-repair-suggestions.json"
            suggestions.parent.mkdir(parents=True)
            suggestions.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "mode": "observe_only",
                        "pending_count": 1,
                        "pending": [
                            {
                                "suggestion_id": "recovery_loop-intervene-ready",
                                "status": "pending",
                                "route": {"endpoint": "/api/nodes/recovery-cycle", "arm_group": "remote"},
                                "auto_execute": False,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            audit_calls = []
            original_audit = mod.enqueue_communication_suggestion_audit
            try:
                mod.enqueue_communication_suggestion_audit = lambda event, *, root=mod.ROOT: audit_calls.append((event, root))
                result = mod.communication_repair_suggestion_review(
                    {
                        "suggestion_id": "recovery_loop-intervene-ready",
                        "action": "approve",
                        "reason": "operator accepted route",
                        "operator_scopes": ["operator.admin"],
                    },
                    root=root,
                )
            finally:
                mod.enqueue_communication_suggestion_audit = original_audit
            saved = json.loads(suggestions.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["audit_async"])
        self.assertEqual(result["pending_count"], 0)
        self.assertEqual(result["approved_count"], 1)
        self.assertEqual(saved["approved_count"], 1)
        self.assertEqual(saved["pending"], [])
        self.assertEqual(saved["approved"][0]["suggestion_id"], "recovery_loop-intervene-ready")
        self.assertEqual(saved["approved"][0]["status"], "approved")
        self.assertFalse(saved["approved"][0]["auto_execute"])
        self.assertEqual(audit_calls[0][0]["action"], "approve")
        self.assertFalse(audit_calls[0][0]["auto_execute"])

    def test_communication_repair_suggestion_review_requires_admin(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(PermissionError):
                mod.communication_repair_suggestion_review(
                    {"suggestion_id": "x", "action": "ignore"},
                    root=root,
                )

    def test_api_recovery_loop_latest_endpoint(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}

        class DummyRecoveryLoopLatestGetHandler:
            path = "/api/nodes/recovery-loop/latest"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        original_latest = mod.recovery_loop_latest
        try:
            mod.recovery_loop_latest = lambda: {
                "status": "ok",
                "kind": "recovery_loop_latest",
                "communication_execute_enabled": False,
                "communication_route_execution": {"status": "ok", "kind": "communication_route_execution", "reason": "observe_only"},
            }
            mod.ControlHandler.do_GET(DummyRecoveryLoopLatestGetHandler())
        finally:
            mod.recovery_loop_latest = original_latest

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "recovery_loop_latest")
        self.assertFalse(captured["payload"]["communication_execute_enabled"])
        self.assertEqual(captured["payload"]["communication_route_execution"]["kind"], "communication_route_execution")

    def test_service_control_audit_tail_missing_file(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = mod.service_control_audit_tail(root=root)

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["kind"], "service_control_audit_tail")
        self.assertEqual(result["path"], str(root / mod.SERVICE_CONTROL_AUDIT_REL_PATH))
        self.assertEqual(result["events"], [])
        self.assertEqual(result["event_count"], 0)
        self.assertEqual(result["skipped_bad_lines"], 0)

    def test_service_control_audit_tail_bounds_newest_events(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / mod.SERVICE_CONTROL_AUDIT_REL_PATH
            path.parent.mkdir(parents=True)
            events = [
                {"at": "2026-06-01T10:00:00Z", "action": "start", "command": "services.start", "status": "ok"},
                {"at": "2026-06-01T10:01:00Z", "action": "restart", "command": "services.restart", "status": "ok"},
                {"at": "2026-06-01T10:02:00Z", "action": "start", "command": "services.start", "status": "ok"},
                {"at": "2026-06-01T10:03:00Z", "action": "restart", "command": "services.restart", "status": "ok"},
                {"at": "2026-06-01T10:04:00Z", "action": "blocked", "command": "services.restart", "status": "blocked"},
            ]
            path.write_text("\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8")
            result = mod.service_control_audit_tail(limit=3, root=root)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["event_count"], 3)
        self.assertEqual(result["events"][0]["at"], "2026-06-01T10:02:00Z")
        self.assertEqual(result["events"][2]["at"], "2026-06-01T10:04:00Z")

    def test_service_control_audit_tail_skips_bad_jsonl(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / mod.SERVICE_CONTROL_AUDIT_REL_PATH
            path.parent.mkdir(parents=True)
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"at": "2026-06-01T10:00:00Z", "status": "ok", "command": "services.start"}),
                        "{bad-json-line}",
                        json.dumps({"at": "2026-06-01T10:01:00Z", "status": "blocked", "command": "services.restart"}),
                        "42",
                        json.dumps({"at": "2026-06-01T10:02:00Z", "status": "ok", "command": "services.restart"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            result = mod.service_control_audit_tail(limit=10, root=root)

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["skipped_bad_lines"], 2)
        self.assertEqual(result["event_count"], 3)
        self.assertEqual(result["events"][0]["status"], "ok")
        self.assertEqual(result["events"][2]["status"], "ok")

    def test_monitor_intervention_audit_tail_bounds_newest_events(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / mod.MONITOR_INTERVENTION_AUDIT_REL_PATH
            path.parent.mkdir(parents=True)
            events = [
                {"at": "2026-06-01T10:00:00Z", "action": "pause", "status": "recorded"},
                {"at": "2026-06-01T10:01:00Z", "action": "repair", "status": "recorded"},
                {"at": "2026-06-01T10:02:00Z", "action": "route_to_debate", "status": "recorded"},
                {"at": "2026-06-01T10:03:00Z", "action": "resume", "status": "blocked"},
            ]
            path.write_text("\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8")
            result = mod.monitor_intervention_audit_tail(limit=2, root=root)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["kind"], "monitor_intervention_audit_tail")
        self.assertEqual(result["event_count"], 2)
        self.assertEqual(result["events"][0]["action"], "route_to_debate")
        self.assertEqual(result["events"][1]["action"], "resume")

    def test_api_monitor_intervention_audit_route_passes_limit(self):
        mod = load_control_api()
        captured = {}
        original_handler = mod.monitor_intervention_audit_tail

        def fake_monitor_intervention_audit_tail(limit=20, *, root=mod.ROOT):
            captured["limit"] = limit
            captured["root"] = root
            return {
                "status": "ok",
                "kind": "monitor_intervention_audit_tail",
                "path": str(Path(root) / mod.MONITOR_INTERVENTION_AUDIT_REL_PATH),
                "events": [],
                "event_count": 0,
                "skipped_bad_lines": 0,
            }

        class DummyMonitorInterventionAuditGetHandler:
            path = "/api/monitor/interventions/audit?limit=9"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        try:
            mod.monitor_intervention_audit_tail = fake_monitor_intervention_audit_tail
            mod.ControlHandler.do_GET(DummyMonitorInterventionAuditGetHandler())
        finally:
            mod.monitor_intervention_audit_tail = original_handler

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["limit"], 9)
        self.assertEqual(captured["payload"]["kind"], "monitor_intervention_audit_tail")

    def test_api_services_control_audit_route_passes_limit(self):
        mod = load_control_api()
        captured = {}
        original_handler = mod.service_control_audit_tail

        def fake_service_control_audit_tail(limit=20, *, root=mod.ROOT):
            captured["limit"] = limit
            captured["root"] = root
            return {
                "status": "ok",
                "kind": "service_control_audit_tail",
                "path": str(Path(root) / mod.SERVICE_CONTROL_AUDIT_REL_PATH),
                "events": [],
                "event_count": 0,
                "skipped_bad_lines": 0,
            }

        class DummyServicesAuditGetHandler:
            path = "/api/services/control-audit?limit=7"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        try:
            mod.service_control_audit_tail = fake_service_control_audit_tail
            mod.ControlHandler.do_GET(DummyServicesAuditGetHandler())
        finally:
            mod.service_control_audit_tail = original_handler

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["limit"], 7)
        self.assertEqual(captured["payload"]["kind"], "service_control_audit_tail")

    def test_recovery_transcript_joins_node_gateway_stream_and_loop_evidence(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.write_node_evidence(
                "probe",
                "node-a",
                {
                    "status": "ok",
                    "target": "root@100.64.0.1",
                    "probe_action": "continue",
                    "probe_action_reason": "probe_ok",
                    "return_code": 0,
                },
                root=root,
            )
            latest = root / ".a9" / "services" / "recovery-loop-latest.json"
            latest.parent.mkdir(parents=True)
            latest.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "checked_at": "2026-05-29T19:02:55+00:00",
                        "cycle_status": "ok",
                        "step_count": 0,
                        "risk_count": 0,
                        "execute": False,
                        "cycle": {"summary": {"risk_count": 0}, "steps": []},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            original_gateway = mod.latest_gateway_reconnect_decision_event
            original_status = mod.node_status
            try:
                mod.latest_gateway_reconnect_decision_event = lambda: {
                    "status": "ok",
                    "kind": "gateway_reconnect_decision",
                    "event_id": "1-0",
                    "phase": "stream",
                    "action": "continue",
                    "error_class": "none",
                    "attempt": 0,
                    "delay_ms": 0,
                    "policy_budget_remaining": 3,
                    "flow_id": "flow-a",
                    "flow_revision": 2,
                    "node_id": "node-a",
                    "origin": "manual_resume",
                    "reset_on_success": True,
                    "ts": "2026-05-29T19:02:56+00:00",
                }
                mod.node_status = lambda root=mod.ROOT: {
                    "tasks_stream": {
                        "status": "ok",
                        "stream_action": "continue",
                        "stream_action_reason": "none",
                        "stream": "a9:tasks",
                        "group": "a9-worker",
                        "lag": 0,
                        "pending": 0,
                        "thresholds_version": "redis_streams_v1",
                    },
                    "communication_followup": {
                        "status": "ok",
                        "action": "continue",
                        "reason": "tasks_stream:none",
                        "evidence": {"tasks_stream": {"action": "continue", "reason": "none"}},
                    },
                }

                result = mod.recovery_transcript("node-a", root=root, limit=20)
            finally:
                mod.latest_gateway_reconnect_decision_event = original_gateway
                mod.node_status = original_status

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["schema"], "a9.node_recovery_transcript.v1")
            self.assertEqual(result["conclusion"], "converging")
            phases = [item["phase"] for item in result["items"]]
            self.assertIn("probe", phases)
            self.assertIn("stream-health", phases)
            self.assertIn("observe", phases)
            sources = [item["source"] for item in result["items"]]
            self.assertIn("gateway_reconnect_decision", sources)
            self.assertIn("communication_followup", sources)
            self.assertTrue(any(item["flow_id"] == "flow-a" for item in result["items"]))

    def test_recovery_transcript_marks_repairing_when_stream_intervenes(self):
        mod = load_control_api()
        original_gateway = mod.latest_gateway_reconnect_decision_event
        original_status = mod.node_status
        original_latest = mod.recovery_loop_latest
        try:
            mod.latest_gateway_reconnect_decision_event = lambda: {"status": "missing", "kind": "gateway_reconnect_decision"}
            mod.node_status = lambda root=mod.ROOT: {
                "tasks_stream": {
                    "status": "ok",
                    "stream_action": "intervene",
                    "stream_action_reason": "pending_stuck",
                },
                "communication_followup": {
                    "status": "needs_attention",
                    "action": "intervene",
                    "reason": "tasks_stream:pending_stuck",
                    "evidence": {},
                },
            }
            mod.recovery_loop_latest = lambda root=mod.ROOT: {"status": "missing"}

            result = mod.recovery_transcript(root=Path(tempfile.mkdtemp()), limit=5)
        finally:
            mod.latest_gateway_reconnect_decision_event = original_gateway
            mod.node_status = original_status
            mod.recovery_loop_latest = original_latest

        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(result["conclusion"], "bouncing")
        self.assertEqual(result["items"][-1]["action"], "intervene")
        self.assertEqual(result["intervention_decision"]["action"], "repair")

    def test_recovery_transcript_prefers_followup_embedded_intervention_decision(self):
        mod = load_control_api()
        original_gateway = mod.latest_gateway_reconnect_decision_event
        original_status = mod.node_status
        original_latest = mod.recovery_loop_latest
        try:
            mod.latest_gateway_reconnect_decision_event = lambda: {"status": "missing", "kind": "gateway_reconnect_decision"}
            mod.node_status = lambda root=mod.ROOT: {
                "tasks_stream": {
                    "status": "ok",
                    "stream_action": "continue",
                    "stream_action_reason": "none",
                },
                "communication_followup": {
                    "status": "ok",
                    "action": "continue",
                    "reason": "healthy",
                    "evidence": {},
                    "intervention_decision": {
                        "action": "watch",
                        "reason": "recovery_risk_present",
                        "evidence_refs": ["loop:risk_count"],
                    },
                },
            }
            mod.recovery_loop_latest = lambda root=mod.ROOT: {"status": "ok", "risk_count": 0, "cycle_status": "ok"}
            result = mod.recovery_transcript(root=Path(tempfile.mkdtemp()), limit=5)
        finally:
            mod.latest_gateway_reconnect_decision_event = original_gateway
            mod.node_status = original_status
            mod.recovery_loop_latest = original_latest

        self.assertEqual(result["intervention_decision"]["action"], "watch")
        self.assertEqual(result["intervention_decision"]["reason"], "recovery_risk_present")
        self.assertEqual(result["intervention_decision"]["evidence_refs"], ["loop:risk_count"])

    def test_recovery_transcript_intervention_decision_observe_when_healthy(self):
        mod = load_control_api()
        original_gateway = mod.latest_gateway_reconnect_decision_event
        original_status = mod.node_status
        original_latest = mod.recovery_loop_latest
        try:
            mod.latest_gateway_reconnect_decision_event = lambda: {"status": "missing", "kind": "gateway_reconnect_decision"}
            mod.node_status = lambda root=mod.ROOT: {
                "tasks_stream": {
                    "status": "ok",
                    "stream_action": "continue",
                    "stream_action_reason": "none",
                },
                "communication_followup": {
                    "status": "ok",
                    "action": "continue",
                    "reason": "healthy",
                    "evidence": {},
                },
            }
            mod.recovery_loop_latest = lambda root=mod.ROOT: {"status": "ok", "risk_count": 0, "cycle_status": "ok"}
            result = mod.recovery_transcript(root=Path(tempfile.mkdtemp()), limit=5)
        finally:
            mod.latest_gateway_reconnect_decision_event = original_gateway
            mod.node_status = original_status
            mod.recovery_loop_latest = original_latest

        self.assertEqual(result["intervention_decision"]["action"], "observe")
        self.assertEqual(result["intervention_decision"]["reason"], "healthy")

    def test_node_command_recovery_hint_prefers_tmux_route_for_stale_remote_heartbeat(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_id = "node-a"
            node_file = root / ".a9" / "nodes" / f"{node_id}.json"
            node_file.parent.mkdir(parents=True, exist_ok=True)
            node_file.write_text(
                json.dumps(
                    {
                        "node_id": node_id,
                        "status": "online",
                        "connection_state": "stale",
                        "connection_action": "reconnect",
                        "connection_action_reason": "heartbeat_stale",
                        "probe_action": "continue",
                        "heartbeat_start_action": "continue",
                        "tmux_action": "repair",
                        "tmux_session": "a9-heartbeat",
                        "heartbeat_start_executed_at": "2026-05-30T00:00:00+00:00",
                        "tmux_checked_at": "2026-05-30T00:01:00+00:00",
                        "updated_at": "2026-05-30T00:01:00+00:00",
                        "ssh_target": "root@100.64.0.1",
                    }
                ),
                encoding="utf-8",
            )
            hint = mod.node_command_recovery_hint(
                node_id=node_id,
                result_status="noop",
                result_error_code="no_result",
                root=root,
            )

        self.assertEqual(hint["action"], "heartbeat_repair")
        self.assertEqual(hint["reason"], "heartbeat_tmux_missing_after_start")
        self.assertEqual(hint["next_endpoint"], "/api/nodes/heartbeat-repair")
        self.assertEqual(hint["next_method"], "POST")
        self.assertEqual(hint["next_command"], "nodes.remote.repair")
        self.assertTrue(hint["next_requires_arm"])

    def test_recovery_transcript_includes_node_command_recovery_hint_and_evidence_refs(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nodes_dir = root / ".a9" / "nodes"
            nodes_dir.mkdir(parents=True)
            node_path = nodes_dir / "node-a.json"
            node_path.write_text(
                json.dumps(
                    {
                        "node_id": "node-a",
                        "status": "online",
                        "connection_state": "stale",
                        "connection_action": "reconnect",
                        "connection_action_reason": "heartbeat_stale",
                        "last_heartbeat_at": "2026-05-29T00:00:00+00:00",
                        "updated_at": "2026-05-29T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            original_gateway = mod.latest_gateway_reconnect_decision_event
            original_status = mod.node_status
            original_latest = mod.recovery_loop_latest
            try:
                mod.latest_gateway_reconnect_decision_event = lambda: {"status": "missing", "kind": "gateway_reconnect_decision"}
                mod.node_status = lambda root=mod.ROOT: {
                    "nodes": [
                        {
                            "node_id": "node-a",
                            "connection_state": "stale",
                            "connection_action": "reconnect",
                            "connection_action_reason": "heartbeat_stale",
                        }
                    ],
                    "tasks_stream": {
                        "status": "unavailable",
                        "stream_action": "intervene",
                        "stream_action_reason": "redis_unavailable",
                        "sampled_at": "2026-05-30T00:00:00+00:00",
                    },
                    "communication_followup": {
                        "status": "needs_attention",
                        "action": "reconnect",
                        "reason": "node:heartbeat_stale",
                        "evidence": {"nodes": [{"node_id": "node-a"}]},
                    },
                }
                mod.recovery_loop_latest = lambda root=mod.ROOT: {"status": "missing"}
                result = mod.recovery_transcript("node-a", root=root, limit=20)
            finally:
                mod.latest_gateway_reconnect_decision_event = original_gateway
                mod.node_status = original_status
                mod.recovery_loop_latest = original_latest

        hint_items = [item for item in result["items"] if item.get("source") == "node_command_recovery_hint"]
        self.assertTrue(hint_items)
        self.assertTrue(
            any(item.get("details", {}).get("recovery_hint", {}).get("reason") == "redis_unavailable" for item in hint_items)
        )
        self.assertTrue(
            any(
                item.get("details", {}).get("recovery_hint", {}).get("action") in {"reconnect", "probe", "wait"}
                and item.get("details", {}).get("recovery_hint", {}).get("next_endpoint")
                in {"/api/nodes/probe", "/api/node-command-results/by-command/{command_id}"}
                for item in hint_items
            )
        )
        refs = result["intervention_decision"]["evidence_refs"]
        self.assertIn("redis:ping", refs)
        self.assertIn(str(node_path), refs)

    def test_recovery_transcript_includes_node_bootstrap_execution(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence_path = root / ".a9" / "nodes" / "evidence" / "node-a" / "bootstrap-execute-node-a-1.json"
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(
                json.dumps(
                    {
                        "action": "continue",
                        "result": "ok",
                        "return_code": 0,
                        "timed_out": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / ".a9" / "nodes" / "node-a.json").write_text(
                json.dumps(
                    {
                        "node_id": "node-a",
                        "status": "registered",
                        "updated_at": "2026-06-09T00:00:00+00:00",
                        "bootstrap_execution": {
                            "action": "continue",
                            "result": "ok",
                            "return_code": 0,
                            "timed_out": False,
                            "evidence_path": str(evidence_path),
                            "previous_revision": 6,
                            "new_revision": 7,
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            original_gateway = mod.latest_gateway_reconnect_decision_event
            original_latest = mod.recovery_loop_latest
            try:
                mod.latest_gateway_reconnect_decision_event = lambda: {"status": "missing", "kind": "gateway_reconnect_decision"}
                mod.recovery_loop_latest = lambda root=mod.ROOT: {"status": "missing"}
                result = mod.recovery_transcript("node-a", root=root, limit=20)
            finally:
                mod.latest_gateway_reconnect_decision_event = original_gateway
                mod.recovery_loop_latest = original_latest

        bootstrap_items = [item for item in result["items"] if item.get("source") == "node_bootstrap_execution"]
        self.assertEqual(len(bootstrap_items), 1)
        item = bootstrap_items[0]
        self.assertEqual(item["node_id"], "node-a")
        self.assertEqual(item["action"], "continue")
        self.assertEqual(item["status"], "ok")
        self.assertEqual(item["evidence_path"], str(evidence_path))
        self.assertEqual(item["details"]["bootstrap_execution"]["previous_revision"], 6)
        self.assertEqual(item["details"]["bootstrap_execution"]["new_revision"], 7)
        self.assertEqual(item["details"]["status_reason"], "")
        self.assertEqual(item["details"]["recovery_hint"]["action"], "observe")
        self.assertEqual(item["details"]["recovery_hint"]["next_endpoint"], "/api/nodes/recovery-transcript")
        self.assertEqual(item["details"]["recovery_hint"]["next_method"], "GET")
        self.assertEqual(item["details"]["recovery_hint"]["next_requires_arm"], False)
        self.assertEqual(item["details"]["recovery_hint"]["evidence_refs"], [str(evidence_path)])

    def test_bootstrap_execute_success_commit_visible_in_node_status_and_recovery_transcript(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = "A9 remote node prepared\n"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_path = root / ".a9" / "nodes" / "node-a.json"
            node_path.parent.mkdir(parents=True)
            node_path.write_text(
                json.dumps(
                    {
                        "node_id": "node-a",
                        "revision": 6,
                        "ssh_target": "root@100.64.0.1",
                        "status": "await_bootstrap_takeover",
                        "bootstrap_takeover": {
                            "state": "approved",
                            "decision": "resume_approved",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            mod.phone_control_arm(
                {"group": "remote", "duration": "30s", "operator_scopes": ["operator.admin"]},
                root=root,
            )
            original_run = mod.subprocess.run
            original_gateway = mod.latest_gateway_reconnect_decision_event
            original_latest = mod.recovery_loop_latest
            try:
                def fake_run(cmd, **kwargs):
                    return FakeProc()

                mod.subprocess.run = fake_run
                result = mod.bootstrap_execute_node(
                    {
                        "node_id": "node-a",
                        "ssh_target": "root@100.64.0.1",
                        "operator_scopes": ["operator.admin"],
                        "expected_revision": 6,
                    },
                    root=root,
                )
                status = mod.node_status(root)
                mod.latest_gateway_reconnect_decision_event = lambda: {"status": "missing", "kind": "gateway_reconnect_decision"}
                mod.recovery_loop_latest = lambda root=mod.ROOT: {"status": "missing"}
                transcript = mod.recovery_transcript("node-a", root=root, limit=20)
            finally:
                mod.subprocess.run = original_run
                mod.latest_gateway_reconnect_decision_event = original_gateway
                mod.recovery_loop_latest = original_latest

            self.assertEqual(result["status"], "ok")
            self.assertTrue(Path(result["evidence_path"]).exists())
            node = next((item for item in status["nodes"] if item.get("node_id") == "node-a"), None)
            self.assertIsNotNone(node)
            self.assertEqual(node["revision"], 7)
            self.assertEqual(node["status"], "registered")
            self.assertEqual(node["status_reason"], "bootstrap_ok")
            self.assertEqual(node["bootstrap_execution"]["previous_revision"], 6)
            self.assertEqual(node["bootstrap_execution"]["new_revision"], 7)
            self.assertEqual(node["bootstrap_execution"]["evidence_path"], result["evidence_path"])

            bootstrap_items = [item for item in transcript["items"] if item.get("source") == "node_bootstrap_execution"]
            self.assertEqual(len(bootstrap_items), 1)
            transcript_item = bootstrap_items[0]
            self.assertEqual(transcript_item["evidence_path"], result["evidence_path"])
            self.assertEqual(transcript_item["details"]["bootstrap_execution"]["new_revision"], node["revision"])
            self.assertEqual(transcript_item["details"]["bootstrap_execution"]["evidence_path"], result["evidence_path"])
            self.assertEqual(transcript_item["details"]["recovery_hint"], result["recovery_hint"])

    def test_recovery_transcript_without_bootstrap_execution_has_no_node_bootstrap_item(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".a9" / "nodes" / "node-a.json").parent.mkdir(parents=True)
            (root / ".a9" / "nodes" / "node-a.json").write_text(
                json.dumps(
                    {
                        "node_id": "node-a",
                        "status": "registered",
                        "updated_at": "2026-06-09T00:00:00+00:00",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            original_gateway = mod.latest_gateway_reconnect_decision_event
            original_latest = mod.recovery_loop_latest
            try:
                mod.latest_gateway_reconnect_decision_event = lambda: {"status": "missing", "kind": "gateway_reconnect_decision"}
                mod.recovery_loop_latest = lambda root=mod.ROOT: {"status": "missing"}
                result = mod.recovery_transcript("node-a", root=root, limit=20)
            finally:
                mod.latest_gateway_reconnect_decision_event = original_gateway
                mod.recovery_loop_latest = original_latest

        self.assertFalse(any(item.get("source") == "node_bootstrap_execution" for item in result["items"]))

    def test_recovery_transcript_intervention_decision_quarantine_on_sequence_conflict(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence_dir = root / ".a9" / "nodes" / "evidence" / "node-a"
            evidence_dir.mkdir(parents=True)
            payload = {
                "kind": "probe",
                "action": "intervene",
                "reason": "unsafe_terminal_sequence_conflict",
                "status": "failed",
                "node_id": "node-a",
                "checked_at": "2026-05-30T00:00:00+00:00",
            }
            (evidence_dir / "probe-node-a-20260530T000000Z.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            original_gateway = mod.latest_gateway_reconnect_decision_event
            original_status = mod.node_status
            original_latest = mod.recovery_loop_latest
            try:
                mod.latest_gateway_reconnect_decision_event = lambda: {"status": "missing", "kind": "gateway_reconnect_decision"}
                mod.node_status = lambda root=mod.ROOT: {
                    "tasks_stream": {
                        "status": "ok",
                        "stream_action": "continue",
                        "stream_action_reason": "none",
                    },
                    "communication_followup": {
                        "status": "ok",
                        "action": "continue",
                        "reason": "healthy",
                        "evidence": {},
                    },
                }
                mod.recovery_loop_latest = lambda root=mod.ROOT: {"status": "missing"}
                result = mod.recovery_transcript("node-a", root=root, limit=10)
            finally:
                mod.latest_gateway_reconnect_decision_event = original_gateway
                mod.node_status = original_status
                mod.recovery_loop_latest = original_latest

        self.assertEqual(result["intervention_decision"]["action"], "quarantine")
        self.assertEqual(result["intervention_decision"]["reason"], "unsafe_terminal_or_sequence_conflict")
        self.assertTrue(result["intervention_decision"]["evidence_refs"])

    def test_api_recovery_transcript_endpoint_uses_query(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None, "input": None}

        class DummyRecoveryTranscriptGetHandler:
            path = "/api/nodes/recovery-transcript?node_id=node-a&limit=7"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        original_transcript = mod.recovery_transcript
        try:
            def fake_transcript(node_id, *, limit=20):
                captured["input"] = {"node_id": node_id, "limit": limit}
                return {"status": "ok", "kind": "node_recovery_transcript"}

            mod.recovery_transcript = fake_transcript
            mod.ControlHandler.do_GET(DummyRecoveryTranscriptGetHandler())
        finally:
            mod.recovery_transcript = original_transcript

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "node_recovery_transcript")
        self.assertEqual(captured["input"], {"node_id": "node-a", "limit": 7})

    def test_api_recovery_transcript_endpoint_exposes_node_command_hint_contract(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nodes_dir = root / ".a9" / "nodes"
            nodes_dir.mkdir(parents=True)
            node_path = nodes_dir / "node-a.json"
            node_path.write_text(
                json.dumps(
                    {
                        "node_id": "node-a",
                        "status": "online",
                        "connection_state": "stale",
                        "connection_action": "reconnect",
                        "connection_action_reason": "heartbeat_stale",
                        "last_heartbeat_at": "2026-05-29T00:00:00+00:00",
                        "updated_at": "2026-05-29T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            class DummyRecoveryTranscriptGetHandler:
                path = "/api/nodes/recovery-transcript?node_id=node-a&limit=20"
                headers = {}

                def write_json(self, status, payload):
                    captured["status"] = status
                    captured["payload"] = payload

            original_gateway = mod.latest_gateway_reconnect_decision_event
            original_status = mod.node_status
            original_latest = mod.recovery_loop_latest
            original_transcript = mod.recovery_transcript
            try:
                mod.latest_gateway_reconnect_decision_event = lambda: {"status": "missing", "kind": "gateway_reconnect_decision"}
                mod.node_status = lambda root=mod.ROOT: {
                    "nodes": [
                        {
                            "node_id": "node-a",
                            "connection_state": "stale",
                            "connection_action": "reconnect",
                            "connection_action_reason": "heartbeat_stale",
                        }
                    ],
                    "tasks_stream": {
                        "status": "unavailable",
                        "stream_action": "intervene",
                        "stream_action_reason": "redis_unavailable",
                        "sampled_at": "2026-05-30T00:00:00+00:00",
                    },
                    "communication_followup": {
                        "status": "needs_attention",
                        "action": "reconnect",
                        "reason": "node:heartbeat_stale",
                        "evidence": {"nodes": [{"node_id": "node-a"}]},
                    },
                }
                mod.recovery_loop_latest = lambda root=mod.ROOT: {"status": "missing"}

                def fake_transcript(node_id, *, limit=20):
                    return original_transcript(node_id, root=root, limit=limit)

                mod.recovery_transcript = fake_transcript
                mod.ControlHandler.do_GET(DummyRecoveryTranscriptGetHandler())
            finally:
                mod.latest_gateway_reconnect_decision_event = original_gateway
                mod.node_status = original_status
                mod.recovery_loop_latest = original_latest
                mod.recovery_transcript = original_transcript

        self.assertEqual(captured["status"], 200)
        payload = captured["payload"]
        self.assertEqual(payload["kind"], "node_recovery_transcript")
        hint_items = [item for item in payload["items"] if item.get("source") == "node_command_recovery_hint"]
        self.assertTrue(hint_items)
        refs = payload["intervention_decision"]["evidence_refs"]
        self.assertIn("redis:ping", refs)
        self.assertIn(str(node_path), refs)

    def test_api_discovery_endpoint_exposes_runtime_recovery_hint_flag(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None}

        class DummyDiscoveryGetHandler:
            path = "/api/discovery"
            headers = {}

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        mod.ControlHandler.do_GET(DummyDiscoveryGetHandler())

        self.assertEqual(captured["status"], 200)
        self.assertTrue(captured["payload"]["runtime"]["node_command_recovery_hint_contract"])

    def test_api_discovery_to_recovery_transcript_typed_contract_for_handler(self):
        mod = load_control_api()
        discovery_capture = {"status": None, "payload": None}
        transcript_capture = {"status": None, "payload": None}

        class DummyDiscoveryGetHandler:
            path = "/api/discovery"
            headers = {}

            def write_json(self, status, payload):
                discovery_capture["status"] = status
                discovery_capture["payload"] = payload

        mod.ControlHandler.do_GET(DummyDiscoveryGetHandler())
        self.assertEqual(discovery_capture["status"], 200)
        self.assertTrue(discovery_capture["payload"]["runtime"]["node_command_recovery_hint_contract"])

        transcript_endpoint = discovery_capture["payload"]["endpoints"]["node_recovery_transcript"]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nodes_dir = root / ".a9" / "nodes"
            nodes_dir.mkdir(parents=True)
            node_path = nodes_dir / "node-a.json"
            node_path.write_text(
                json.dumps(
                    {
                        "node_id": "node-a",
                        "status": "online",
                        "connection_state": "stale",
                        "connection_action": "reconnect",
                        "connection_action_reason": "heartbeat_stale",
                        "last_heartbeat_at": "2026-05-29T00:00:00+00:00",
                        "updated_at": "2026-05-29T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            class DummyTranscriptGetHandler:
                path = f"{transcript_endpoint}?node_id=node-a&limit=20"
                headers = {}

                def write_json(self, status, payload):
                    transcript_capture["status"] = status
                    transcript_capture["payload"] = payload

            original_gateway = mod.latest_gateway_reconnect_decision_event
            original_status = mod.node_status
            original_latest = mod.recovery_loop_latest
            original_transcript = mod.recovery_transcript
            try:
                mod.latest_gateway_reconnect_decision_event = lambda: {"status": "missing", "kind": "gateway_reconnect_decision"}
                mod.node_status = lambda root=mod.ROOT: {
                    "nodes": [
                        {
                            "node_id": "node-a",
                            "connection_state": "stale",
                            "connection_action": "reconnect",
                            "connection_action_reason": "heartbeat_stale",
                        }
                    ],
                    "tasks_stream": {
                        "status": "unavailable",
                        "stream_action": "intervene",
                        "stream_action_reason": "redis_unavailable",
                        "sampled_at": "2026-05-30T00:00:00+00:00",
                    },
                    "communication_followup": {
                        "status": "needs_attention",
                        "action": "reconnect",
                        "reason": "node:heartbeat_stale",
                        "evidence": {"nodes": [{"node_id": "node-a"}]},
                    },
                }
                mod.recovery_loop_latest = lambda root=mod.ROOT: {"status": "missing"}

                def fake_transcript(node_id, *, limit=20):
                    return original_transcript(node_id, root=root, limit=limit)

                mod.recovery_transcript = fake_transcript
                mod.ControlHandler.do_GET(DummyTranscriptGetHandler())
            finally:
                mod.latest_gateway_reconnect_decision_event = original_gateway
                mod.node_status = original_status
                mod.recovery_loop_latest = original_latest
                mod.recovery_transcript = original_transcript

        self.assertEqual(transcript_capture["status"], 200)
        payload = transcript_capture["payload"]
        self.assertEqual(payload["kind"], "node_recovery_transcript")

        hint_items = [item for item in payload["items"] if item.get("source") == "node_command_recovery_hint"]
        self.assertTrue(hint_items)
        self.assertTrue(
            any(
                isinstance(item.get("details"), dict)
                and isinstance(item.get("details", {}).get("recovery_hint"), dict)
                for item in hint_items
            )
        )

        refs = payload["intervention_decision"]["evidence_refs"]
        self.assertIn("redis:ping", refs)
        self.assertIn(str(node_path), refs)

    def test_api_discovery_submit_and_by_command_missing_result_exposes_routable_recovery_hint(self):
        mod = load_control_api()
        discovery_capture = {"status": None, "payload": None}
        submit_capture = {"status": None, "payload": None}
        by_command_capture = {"status": None, "payload": None}

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n", 0)
            if args[:2] == ["XADD", "a9:tasks"]:
                return FakeProc("1740000900-0\n", 0)
            if args[:3] == ["--raw", "XREVRANGE", "a9:test-events"]:
                return FakeProc("1740000999-0\nkind\nnode_command_result\ncommand_id\nother-command\n", 0)
            return FakeProc("", 0)

        class DummyDiscoveryGetHandler:
            path = "/api/discovery"
            headers = {}

            def write_json(self, status, payload):
                discovery_capture["status"] = status
                discovery_capture["payload"] = payload

        original_redis = mod.redis_cli
        original_lookup = mod.node_command_result_by_command_lookup
        mod.redis_cli = fake_redis
        try:
            mod.ControlHandler.do_GET(DummyDiscoveryGetHandler())
            self.assertEqual(discovery_capture["status"], 200)

            endpoints = discovery_capture["payload"]["endpoints"]
            self.assertEqual(endpoints["node_command_submit"], "/api/nodes/command-submit")
            self.assertEqual(endpoints["node_command_result_by_command"], "/api/node-command-results/by-command/{command_id}")
            self.assertEqual(endpoints["node_recovery_transcript"], "/api/nodes/recovery-transcript")

            payload = {
                "command_id": "cmd-lifecycle",
                "node_id": "node-lifecycle",
                "action": "probe",
                "action_reason": "typed_contract_test",
                "target": "node-lifecycle",
                "expected_revision": 1,
                "ttl_seconds": 30,
            }
            post_body = json.dumps(payload).encode("utf-8")

            class DummyCommandSubmitPostHandler:
                path = "/api/nodes/command-submit"
                headers = {"Content-Length": str(len(post_body))}
                rfile = io.BytesIO(post_body)

                def write_json(self, status, response_payload):
                    submit_capture["status"] = status
                    submit_capture["payload"] = response_payload

            mod.ControlHandler.do_POST(DummyCommandSubmitPostHandler())
            self.assertEqual(submit_capture["status"], 200)
            self.assertEqual(submit_capture["payload"]["status"], "ok")
            self.assertEqual(submit_capture["payload"]["command"]["command_id"], "cmd-lifecycle")
            self.assertIn("recovery_hint", submit_capture["payload"])
            submit_hint = submit_capture["payload"]["recovery_hint"]
            self.assertEqual(submit_hint["action"], "wait")
            self.assertEqual(submit_hint["reason"], "await_result")
            self.assertEqual(submit_hint["next_endpoint"], "/api/node-command-results/by-command/cmd-lifecycle")
            self.assertNotEqual(submit_hint["reason"], "command_result_found")

            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                nodes_dir = root / ".a9" / "nodes"
                nodes_dir.mkdir(parents=True)
                node_path = nodes_dir / "node-lifecycle.json"
                node_path.write_text(
                    json.dumps(
                        {
                            "node_id": "node-lifecycle",
                            "status": "online",
                            "connection_state": "stale",
                            "connection_action": "reconnect",
                            "connection_action_reason": "heartbeat_stale",
                            "last_heartbeat_at": "2026-05-29T00:00:00+00:00",
                            "updated_at": "2026-05-29T00:00:00+00:00",
                        }
                    ),
                    encoding="utf-8",
                )

                def lookup_with_root(
                    command_id,
                    *,
                    event_stream="a9:events",
                    limit=100,
                    timeout=3,
                    result_last_id=None,
                    node_id="",
                ):
                    return original_lookup(
                        command_id,
                        event_stream=event_stream,
                        limit=limit,
                        timeout=timeout,
                        result_last_id=result_last_id,
                        node_id=node_id,
                        root=root,
                    )

                mod.node_command_result_by_command_lookup = lookup_with_root

                class DummyByCommandGetHandler:
                    path = (
                        "/api/node-command-results/by-command/cmd-lifecycle"
                        "?event_stream=a9:test-events&limit=8&timeout=6&node_id=node-lifecycle"
                    )
                    headers = {}

                    def write_json(self, status, response_payload):
                        by_command_capture["status"] = status
                        by_command_capture["payload"] = response_payload

                mod.ControlHandler.do_GET(DummyByCommandGetHandler())

            self.assertEqual(by_command_capture["status"], 200)
            self.assertEqual(by_command_capture["payload"]["status"], "noop")
            self.assertEqual(by_command_capture["payload"]["error_code"], "no_result")
            hint = by_command_capture["payload"]["recovery_hint"]
            self.assertIsInstance(hint, dict)
            self.assertIn(hint.get("action"), {"probe", "reconnect", "wait"})
            self.assertIn(
                hint.get("next_endpoint"),
                {"/api/nodes/probe", "/api/node-command-results/by-command/{command_id}"},
            )
        finally:
            mod.redis_cli = original_redis
            mod.node_command_result_by_command_lookup = original_lookup

    def test_read_evidence_file_allows_only_a9_evidence_roots(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / ".a9" / "runs" / "run-1" / "summary.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text('{"status":"pass"}\n', encoding="utf-8")
            result = mod.read_evidence_file(str(evidence), root=root)
            self.assertEqual(result["status"], "ok")
            self.assertIn('"status":"pass"', result["content"])
            with self.assertRaises(ValueError):
                mod.read_evidence_file("/etc/passwd", root=root)

    def test_controller_discovery_exposes_registration_contract(self):
        mod = load_control_api()
        discovery = mod.controller_discovery()
        self.assertEqual(discovery["service"], "a9-controller")
        self.assertEqual(discovery["endpoints"]["communication_status"], "/api/communication/status")
        self.assertEqual(discovery["endpoints"]["monitor_control"], "/api/monitor/control")
        self.assertEqual(discovery["endpoints"]["monitor_status"], "/api/monitor/status")
        self.assertEqual(discovery["endpoints"]["monitor_intervention"], "/api/monitor/intervention")
        self.assertEqual(discovery["endpoints"]["monitor_intervention_audit"], "/api/monitor/interventions/audit")
        self.assertEqual(discovery["endpoints"]["monitor_intervention_events"], "/api/monitor/interventions/events")
        self.assertEqual(discovery["endpoints"]["monitor_intervention_examples"], "/api/monitor/intervention/examples")
        self.assertEqual(discovery["endpoints"]["worker_transport_presets"], "/api/worker/transport-presets")
        self.assertEqual(discovery["endpoints"]["worker_transport_check"], "/api/worker/transport-check")
        self.assertEqual(discovery["endpoints"]["worker_transport_config"], "/api/worker/transport-config")
        self.assertEqual(discovery["endpoints"]["worker_transport_policy_update"], "/api/worker/transport-policy")
        self.assertEqual(
            discovery["endpoints"]["communication_data_contract_report"], "/api/communication/data-contract-report"
        )
        self.assertEqual(discovery["endpoints"]["communication_action_plan"], "/api/communication/action-plan")
        self.assertEqual(discovery["endpoints"]["communication_repair_one"], "/api/communication/repair-one")
        self.assertEqual(discovery["endpoints"]["communication_repair_suggestions"], "/api/communication/repair-suggestions")
        self.assertEqual(discovery["endpoints"]["communication_repair_suggestion_review"], "/api/communication/repair-suggestions/review")
        self.assertEqual(discovery["endpoints"]["register_node"], "/api/nodes/register")
        self.assertEqual(discovery["endpoints"]["services_control_audit"], "/api/services/control-audit")
        self.assertEqual(discovery["endpoints"]["gateway_transport_contract"], "/api/gateway/transport-contract")
        self.assertEqual(discovery["endpoints"]["gateway_reconnect_decision"], "/api/gateway/reconnect-decision")
        self.assertEqual(discovery["endpoints"]["gateway_reconnect_diagnostic"], "/api/gateway/reconnect-diagnostic")
        self.assertEqual(discovery["endpoints"]["gateway_reconnect_governance"], "/api/gateway/reconnect-governance")
        self.assertEqual(discovery["endpoints"]["gateway_health_refresh"], "/api/gateway/health-refresh")
        self.assertEqual(discovery["endpoints"]["node_recovery_loop_latest"], "/api/nodes/recovery-loop/latest")
        self.assertEqual(discovery["endpoints"]["node_recovery_transcript"], "/api/nodes/recovery-transcript")
        self.assertEqual(discovery["endpoints"]["services_restart"], "/api/services/restart")
        self.assertEqual(discovery["endpoints"]["eval_override"], "/api/eval/override")
        self.assertEqual(discovery["endpoints"]["runtime_run_one_with_transport"], "/api/runtime/run-one-with-transport")
        self.assertEqual(discovery["endpoints"]["runtime_plan_backlog_next"], "/api/runtime/plan-backlog-next")
        self.assertEqual(discovery["endpoints"]["mempalace_status"], "/api/memory/mempalace/status")
        self.assertEqual(discovery["endpoints"]["mempalace_search"], "/api/memory/mempalace/search")
        self.assertEqual(discovery["endpoints"]["mempalace_wakeup"], "/api/memory/mempalace/wakeup")
        self.assertEqual(discovery["endpoints"]["mempalace_recall"], "/api/memory/mempalace/recall")
        self.assertEqual(discovery["endpoints"]["mempalace_causal_compile"], "/api/memory/mempalace/causal-compile")
        self.assertEqual(discovery["endpoints"]["mempalace_causal_commit"], "/api/memory/mempalace/causal-commit")
        self.assertEqual(discovery["endpoints"]["mempalace_causal_audit"], "/api/memory/mempalace/causal-audit")
        self.assertEqual(
            discovery["endpoints"]["mempalace_causal_repair_propose"],
            "/api/memory/mempalace/causal-repair-propose",
        )
        self.assertEqual(discovery["endpoints"]["mempalace_causal_invalidate"], "/api/memory/mempalace/causal-invalidate")
        self.assertEqual(
            discovery["endpoints"]["mempalace_causal_eval_generate_candidates"],
            "/api/memory/mempalace/causal-eval/generate-candidates",
        )
        self.assertEqual(
            discovery["endpoints"]["mempalace_causal_eval_latest_candidates"],
            "/api/memory/mempalace/causal-eval/latest-candidates",
        )
        self.assertEqual(
            discovery["endpoints"]["mempalace_causal_eval_merge_reviewed"],
            "/api/memory/mempalace/causal-eval/merge-reviewed",
        )
        self.assertEqual(discovery["endpoints"]["node_command_result"], "/api/node-command-results/{result_event_id}")
        self.assertEqual(
            discovery["endpoints"]["node_command_result_by_command"],
            "/api/node-command-results/by-command/{command_id}",
        )
        self.assertEqual(
            discovery["endpoints"]["communication_model_closure_validate"],
            "/api/communication/model-closure-validate",
        )
        self.assertFalse(discovery["runtime"]["worker_claim_ready"])
        self.assertTrue(discovery["runtime"]["gateway_transport_contract"])
        self.assertTrue(discovery["runtime"]["gateway_reconnect_governance"])
        self.assertTrue(discovery["runtime"]["node_command_recovery_hint_contract"])
        self.assertTrue(discovery["runtime"]["monitor_control_contract"])
        self.assertTrue(discovery["runtime"]["monitor_status_contract"])
        self.assertTrue(discovery["runtime"]["monitor_intervention_contract"])
        self.assertTrue(discovery["runtime"]["monitor_intervention_examples"])
        self.assertTrue(discovery["runtime"]["worker_transport_presets"])
        self.assertTrue(discovery["runtime"]["worker_transport_check"])
        self.assertTrue(discovery["runtime"]["worker_transport_config"])
        self.assertTrue(discovery["runtime"]["worker_transport_policy_update"])
        self.assertEqual(discovery["runtime"]["monitor_intervention_redis_stream"], "a9:monitor:interventions")
        self.assertEqual(discovery["events"]["max_limit"], 1000)
        self.assertIn("Last-Event-ID", discovery["events"]["sse_cursor_hint"])

    def test_controller_discovery_exposes_model_closure_validate_endpoint(self):
        mod = load_control_api()
        discovery = mod.controller_discovery()

        self.assertEqual(
            discovery["endpoints"]["communication_model_closure_validate"],
            "/api/communication/model-closure-validate",
        )

    def test_tailscale_status_reports_missing_binary(self):
        mod = load_control_api()
        original_which = mod.shutil.which
        try:
            mod.shutil.which = lambda name: None
            status = mod.tailscale_status()
        finally:
            mod.shutil.which = original_which

        self.assertEqual(status["status"], "missing")
        self.assertFalse(status["installed"])

    def test_tailscale_status_reports_needs_login(self):
        mod = load_control_api()

        class FakeProc:
            returncode = 0
            stdout = json.dumps(
                {
                    "Version": "1.0",
                    "TUN": False,
                    "BackendState": "NeedsLogin",
                    "AuthURL": "https://login.tailscale.com/a/test",
                    "Self": {"HostName": "node", "Online": False, "TailscaleIPs": None},
                    "Health": [],
                }
            )

        original_which = mod.shutil.which
        original_run = mod.subprocess.run
        try:
            mod.shutil.which = lambda name: "/usr/bin/tailscale"
            mod.subprocess.run = lambda *args, **kwargs: FakeProc()
            status = mod.tailscale_status()
        finally:
            mod.shutil.which = original_which
            mod.subprocess.run = original_run

        self.assertEqual(status["status"], "needs_login")
        self.assertEqual(status["auth_url"], "https://login.tailscale.com/a/test")

    def test_submit_task_writes_queue_file(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = mod.ROOT
            mod.ROOT = root
            supervisor = mod.supervisor()
            old_supervisor_root = supervisor.ROOT
            old_state = supervisor.STATE_DIR
            old_queue = supervisor.QUEUE_DIR
            old_running = supervisor.RUNNING_DIR
            old_done = supervisor.DONE_DIR
            old_runs = supervisor.RUNS_DIR
            old_worktrees = supervisor.WORKTREES_DIR
            old_codex_home = supervisor.WORKER_CODEX_HOME
            old_tmp = supervisor.WORKER_TMP_DIR
            old_external = supervisor.EXTERNAL_SESSIONS_DIR
            supervisor.ROOT = root
            supervisor.STATE_DIR = root / ".a9"
            supervisor.QUEUE_DIR = supervisor.STATE_DIR / "tasks" / "queue"
            supervisor.RUNNING_DIR = supervisor.STATE_DIR / "tasks" / "running"
            supervisor.DONE_DIR = supervisor.STATE_DIR / "tasks" / "done"
            supervisor.RUNS_DIR = supervisor.STATE_DIR / "runs"
            supervisor.WORKTREES_DIR = supervisor.STATE_DIR / "worktrees"
            supervisor.WORKER_CODEX_HOME = supervisor.STATE_DIR / "codex-home"
            supervisor.WORKER_TMP_DIR = supervisor.STATE_DIR / "tmp"
            supervisor.EXTERNAL_SESSIONS_DIR = supervisor.STATE_DIR / "external_sessions"
            try:
                mod.supervisor = lambda: supervisor
                result = mod.submit_task({"task_id": "mobile-task", "prompt": "strict_worker_envelope: true\nDo work."})
                self.assertEqual(result["status"], "queued")
                self.assertEqual(result["task_id"], "mobile-task")
                self.assertTrue(Path(result["queue_path"]).exists())
            finally:
                mod.ROOT = old_root
                supervisor.ROOT = old_supervisor_root
                supervisor.STATE_DIR = old_state
                supervisor.QUEUE_DIR = old_queue
                supervisor.RUNNING_DIR = old_running
                supervisor.DONE_DIR = old_done
                supervisor.RUNS_DIR = old_runs
                supervisor.WORKTREES_DIR = old_worktrees
                supervisor.WORKER_CODEX_HOME = old_codex_home
                supervisor.WORKER_TMP_DIR = old_tmp
                supervisor.EXTERNAL_SESSIONS_DIR = old_external

    def test_submit_task_run_requires_runtime_gate(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = mod.ROOT
            mod.ROOT = root
            supervisor = mod.supervisor()
            old_supervisor_root = supervisor.ROOT
            old_state = supervisor.STATE_DIR
            old_queue = supervisor.QUEUE_DIR
            old_running = supervisor.RUNNING_DIR
            old_done = supervisor.DONE_DIR
            old_runs = supervisor.RUNS_DIR
            old_worktrees = supervisor.WORKTREES_DIR
            old_codex_home = supervisor.WORKER_CODEX_HOME
            old_tmp = supervisor.WORKER_TMP_DIR
            old_external = supervisor.EXTERNAL_SESSIONS_DIR
            supervisor.ROOT = root
            supervisor.STATE_DIR = root / ".a9"
            supervisor.QUEUE_DIR = supervisor.STATE_DIR / "tasks" / "queue"
            supervisor.RUNNING_DIR = supervisor.STATE_DIR / "tasks" / "running"
            supervisor.DONE_DIR = supervisor.STATE_DIR / "tasks" / "done"
            supervisor.RUNS_DIR = supervisor.STATE_DIR / "runs"
            supervisor.WORKTREES_DIR = supervisor.STATE_DIR / "worktrees"
            supervisor.WORKER_CODEX_HOME = supervisor.STATE_DIR / "codex-home"
            supervisor.WORKER_TMP_DIR = supervisor.STATE_DIR / "tmp"
            supervisor.EXTERNAL_SESSIONS_DIR = supervisor.STATE_DIR / "external_sessions"
            try:
                mod.supervisor = lambda: supervisor
                result = mod.submit_task(
                    {
                        "task_id": "mobile-run",
                        "prompt": "strict_worker_envelope: true\nDo work.",
                        "run": True,
                        "operator_scopes": ["operator.admin"],
                    }
                )
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["gate"]["reason"], "phone_control_disarmed")
                self.assertTrue(Path(result["queue_path"]).exists())
            finally:
                mod.ROOT = old_root
                supervisor.ROOT = old_supervisor_root
                supervisor.STATE_DIR = old_state
                supervisor.QUEUE_DIR = old_queue
                supervisor.RUNNING_DIR = old_running
                supervisor.DONE_DIR = old_done
                supervisor.RUNS_DIR = old_runs
                supervisor.WORKTREES_DIR = old_worktrees
                supervisor.WORKER_CODEX_HOME = old_codex_home
                supervisor.WORKER_TMP_DIR = old_tmp
                supervisor.EXTERNAL_SESSIONS_DIR = old_external

    def test_runtime_run_one_requires_gate_and_runs_when_armed(self):
        mod = load_control_api()
        calls = []

        class FakeSupervisor:
            @staticmethod
            def run_one(auto_next: bool = False) -> int:
                calls.append(auto_next)
                return 0

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = mod.ROOT
            old_supervisor = mod.supervisor
            mod.ROOT = root
            mod.supervisor = lambda: FakeSupervisor
            try:
                blocked = mod.runtime_run_one({"operator_scopes": ["operator.admin"]})
                self.assertEqual(blocked["status"], "blocked")
                self.assertEqual(blocked["gate"]["reason"], "phone_control_disarmed")

                mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
                result = mod.runtime_run_one({"operator_scopes": ["operator.admin"], "auto_next": True})
                self.assertEqual(result["status"], "run-complete")
                self.assertEqual(result["command"], "submit.run")
                self.assertEqual(calls, [True])
            finally:
                mod.ROOT = old_root
                mod.supervisor = old_supervisor

    def test_runtime_run_one_with_transport_updates_runs_and_rolls_back(self):
        mod = load_control_api()
        calls = {"updates": [], "run_one": []}
        original_update = mod.update_worker_transport_policy
        original_supervisor = mod.supervisor
        original_latest = mod.latest_run_summary

        class FakeSupervisor:
            @staticmethod
            def run_one(auto_next: bool = False) -> int:
                calls["run_one"].append(auto_next)
                return 0

        def fake_update(payload, *, root=mod.ROOT):
            calls["updates"].append(payload)
            if len(calls["updates"]) == 1:
                return {
                    "status": "applied",
                    "rollback_payload": {
                        "backend": "custom_command",
                        "custom_command_template": "echo previous > {final_path}",
                        "reason": "rollback test",
                    },
                }
            return {"status": "applied", "after": {"backend": payload.get("backend")}}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                mod.update_worker_transport_policy = fake_update
                mod.supervisor = lambda: FakeSupervisor
                mod.latest_run_summary = lambda root=mod.ROOT: {"task_id": "latest", "status": "pass"}
                blocked = mod.runtime_run_one_with_transport(
                    {"operator_scopes": ["operator.admin"], "transport": {"preset": "local_envelope_smoke"}},
                    root=root,
                )
                mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
                result = mod.runtime_run_one_with_transport(
                    {
                        "operator_scopes": ["operator.admin"],
                        "auto_next": True,
                        "transport": {"preset": "local_envelope_smoke", "reason": "temporary smoke"},
                    },
                    root=root,
                )
            finally:
                mod.update_worker_transport_policy = original_update
                mod.supervisor = original_supervisor
                mod.latest_run_summary = original_latest

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(result["status"], "run-complete")
        self.assertEqual(calls["run_one"], [True])
        self.assertEqual(calls["updates"][0]["preset"], "local_envelope_smoke")
        self.assertEqual(calls["updates"][1]["custom_command_template"], "echo previous > {final_path}")
        self.assertEqual(result["rollback"]["status"], "applied")

    def test_api_runtime_run_one_with_transport_post_route_calls_handler(self):
        mod = load_control_api()
        captured = {"status": None, "payload": None, "request": None}
        original_handler = mod.runtime_run_one_with_transport
        body = b'{"transport":{"preset":"local_envelope_smoke"}}'

        class DummyRuntimeRunOneWithTransportPostHandler:
            path = "/api/runtime/run-one-with-transport"
            headers = {"Content-Length": str(len(body))}
            rfile = io.BytesIO(body)

            def write_json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        def fake_handler(payload):
            captured["request"] = payload
            return {"status": "run-complete", "kind": "runtime_run_one_with_transport"}

        try:
            mod.runtime_run_one_with_transport = fake_handler
            mod.ControlHandler.do_POST(DummyRuntimeRunOneWithTransportPostHandler())
        finally:
            mod.runtime_run_one_with_transport = original_handler

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "runtime_run_one_with_transport")
        self.assertEqual(captured["request"]["transport"]["preset"], "local_envelope_smoke")

    def test_service_start_action_requires_runtime_gate(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocked = mod.service_start_action({"operator_scopes": ["operator.admin"]}, root=root)
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(blocked["command"], "services.start")
            self.assertEqual(blocked["gate"]["reason"], "phone_control_disarmed")

    def test_service_start_action_without_admin_returns_blocked_payload(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocked = mod.service_start_action({}, root=root)
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(blocked["command"], "services.start")
            self.assertIn("operator.admin", blocked["blocked_reason"])
            self.assertIn("service_observation", blocked)

    def test_service_start_action_runs_helper_and_returns_start_json(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)

            class FakeProc:
                returncode = 0
                stdout = json.dumps(
                    {
                        "checked_at": "2026-06-01T00:00:00+00:00",
                        "requested": ["node-worker"],
                        "started": [
                            {
                                "kind": "node-worker",
                                "command_status": {
                                    "phase": "running",
                                    "observed_running": True,
                                    "verify_attempts_used": 1,
                                    "observed_after_ms": 15,
                                    "failure_kind": "",
                                    "recovery_action": "",
                                },
                            }
                        ],
                    }
                )

            original_observation = mod.service_observation_status
            original_run = mod.subprocess.run
            try:
                calls = []
                mod.service_observation_status = lambda *args, **kwargs: {
                    "status": "ok",
                    "observed": {
                        "missing_services": ["node-worker"],
                        "missing_count": 1,
                        "next_action": "start_missing_services",
                    },
                }

                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.subprocess.run = fake_run
                result = mod.service_start_action({"operator_scopes": ["operator.admin"]}, root=root)
            finally:
                mod.service_observation_status = original_observation
                mod.subprocess.run = original_run

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["command"], "services.start")
        self.assertEqual(result["start_result"]["started"][0]["kind"], "node-worker")
        self.assertTrue(result["start_result"]["started"][0]["command_status"]["observed_running"])
        self.assertEqual(calls[0][0][0], "python3")
        self.assertEqual(calls[0][0][2:], ["start", "--only", "node-worker"])

    def test_service_start_action_audits_blocked_gate(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit_calls = []
            original_audit = mod.enqueue_service_control_audit

            def fake_enqueue(event, *, root):
                audit_calls.append((event, root))

            try:
                mod.enqueue_service_control_audit = fake_enqueue
                result = mod.service_start_action({"operator_scopes": ["operator.admin"]}, root=root)
            finally:
                mod.enqueue_service_control_audit = original_audit

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["command"], "services.start")
        self.assertEqual(result["gate"]["reason"], "phone_control_disarmed")
        self.assertTrue(result["audit_async"])
        self.assertEqual(len(audit_calls), 1)
        event, audit_root = audit_calls[0]
        self.assertEqual(event["status"], "blocked")
        self.assertEqual(event["action"], "start")
        self.assertEqual(event["command"], "services.start")
        self.assertFalse(event["gate_allowed"])
        self.assertEqual(event["gate_reason"], "phone_control_disarmed")
        self.assertTrue(event["has_operator_scope"])
        self.assertEqual(event["operator_scope_count"], 1)
        self.assertIn("service_observation_summary", event)
        self.assertEqual(audit_root, root)

    def test_api_services_start_route_calls_handler(self):
        mod = load_control_api()
        original_handler = mod.service_start_action
        captured = {}
        try:
            def fake_service_start_action(payload):
                captured["payload"] = payload
                return {"status": "ok", "command": "services.start"}

            mod.service_start_action = fake_service_start_action
            body = json.dumps({"operator_scopes": ["operator.admin"]}).encode("utf-8")

            class DummyServicesStartPostHandler:
                path = "/api/services/start"
                headers = {"Content-Length": str(len(body))}
                rfile = io.BytesIO(body)

                def write_json(self, status, payload):
                    captured["status"] = status
                    captured["response"] = payload

            mod.ControlHandler.do_POST(DummyServicesStartPostHandler())
        finally:
            mod.service_start_action = original_handler

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["response"]["command"], "services.start")
        self.assertEqual(captured["payload"]["operator_scopes"], ["operator.admin"])

    def test_append_service_control_audit_writes_jsonl(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "status": "ok",
                "command": "services.restart",
                "target_services": ["recovery-loop"],
                "has_operator_scope": True,
            }
            mod.append_service_control_audit(payload, root=root)
            path = root / mod.SERVICE_CONTROL_AUDIT_REL_PATH
            self.assertTrue(path.parent.exists())
            line = path.read_text(encoding="utf-8").strip().splitlines()[-1]
            self.assertIn('"status":"ok"', line)
            self.assertNotIn(": ", line)
            self.assertNotIn(", ", line)
            self.assertEqual(json.loads(line), payload)

    def test_service_restart_action_requires_runtime_gate(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocked = mod.service_restart_action({"operator_scopes": ["operator.admin"]}, root=root)
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(blocked["command"], "services.restart")
            self.assertEqual(blocked["gate"]["reason"], "phone_control_disarmed")

    def test_service_restart_action_requires_explicit_services(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
            blocked = mod.service_restart_action({"operator_scopes": ["operator.admin"]}, root=root)
            self.assertEqual(blocked["status"], "invalid_request")
            self.assertEqual(blocked["command"], "services.restart")
            self.assertEqual(blocked["reason"], "no_services_requested")

    def test_service_restart_action_rejects_supervisor_by_default(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
            rejected = mod.service_restart_action(
                {"operator_scopes": ["operator.admin"], "services": ["supervisor", "recovery-loop"]},
                root=root,
            )
            self.assertEqual(rejected["status"], "invalid_request")
            self.assertEqual(rejected["command"], "services.restart")
            self.assertEqual(rejected["reason"], "supervisor_restart_not_allowed")
            self.assertEqual(rejected["target_services"], ["supervisor", "recovery-loop"])

    def test_service_restart_action_allows_supervisor_when_explicitly_enabled(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)

            class FakeProc:
                returncode = 0
                stdout = json.dumps(
                    {
                        "kind": "service_restart",
                        "requested": ["supervisor"],
                        "status": "ok",
                    }
                )

            original_observation = mod.service_observation_status
            original_run = mod.subprocess.run
            try:
                calls = []
                mod.service_observation_status = lambda *args, **kwargs: {
                    "status": "ok",
                    "observed": {"missing_services": [], "missing_count": 0},
                }

                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.subprocess.run = fake_run
                result = mod.service_restart_action(
                    {"operator_scopes": ["operator.admin"], "services": ["supervisor"], "allow_supervisor": True},
                    root=root,
                )
            finally:
                mod.service_observation_status = original_observation
                mod.subprocess.run = original_run

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["target_services"], ["supervisor"])
        self.assertEqual(calls[0][0][2:], ["restart", "--only", "supervisor"])

    def test_service_restart_action_audits_invalid_request(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
            audit_calls = []
            original_audit = mod.enqueue_service_control_audit

            def fake_enqueue(event, *, root):
                audit_calls.append((event, root))

            try:
                mod.enqueue_service_control_audit = fake_enqueue
                result = mod.service_restart_action({"operator_scopes": ["operator.admin"]}, root=root)
            finally:
                mod.enqueue_service_control_audit = original_audit

        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(result["command"], "services.restart")
        self.assertEqual(result["reason"], "no_services_requested")
        self.assertTrue(result["audit_async"])
        self.assertEqual(len(audit_calls), 1)
        event, audit_root = audit_calls[0]
        self.assertEqual(event["status"], "invalid_request")
        self.assertEqual(event["action"], "restart")
        self.assertEqual(event["command"], "services.restart")
        self.assertEqual(event["reason"], "no_services_requested")
        self.assertEqual(event["target_services"], [])
        self.assertEqual(audit_root, root)

    def test_service_restart_action_runs_helper_and_returns_restart_json(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)

            class FakeProc:
                returncode = 0
                stdout = json.dumps(
                    {
                        "checked_at": "2026-06-02T00:00:00+00:00",
                        "kind": "service_restart",
                        "requested": ["recovery-loop"],
                        "stop": {"status": "ok", "requested": ["recovery-loop"]},
                        "start": {"started": ["recovery-loop"]},
                        "status": "ok",
                    }
                )

            original_observation = mod.service_observation_status
            original_run = mod.subprocess.run
            try:
                calls = []

                def fake_observation(*args, **kwargs):
                    return {"status": "ok", "observed": {"missing_services": [], "missing_count": 0}}

                mod.service_observation_status = fake_observation

                def fake_run(cmd, **kwargs):
                    calls.append((cmd, kwargs))
                    return FakeProc()

                mod.subprocess.run = fake_run
                result = mod.service_restart_action({"operator_scopes": ["operator.admin"], "services": ["recovery-loop"]}, root=root)
            finally:
                mod.service_observation_status = original_observation
                mod.subprocess.run = original_run

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["command"], "services.restart")
        self.assertEqual(result["restart_result"]["kind"], "service_restart")
        self.assertEqual(result["restart_result"]["requested"], ["recovery-loop"])
        self.assertEqual(calls[0][0][0], "python3")
        self.assertEqual(calls[0][0][2:], ["restart", "--only", "recovery-loop"])

    def test_service_restart_action_audits_ok_result(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
            audit_calls = []
            original_audit = mod.enqueue_service_control_audit

            class FakeProc:
                returncode = 0
                stdout = json.dumps(
                    {
                        "kind": "service_restart",
                        "requested": ["recovery-loop"],
                        "status": "ok",
                    }
                )

            original_observation = mod.service_observation_status
            original_run = mod.subprocess.run
            try:
                mod.enqueue_service_control_audit = lambda event, *, root: audit_calls.append((event, root))
                mod.service_observation_status = lambda *args, **kwargs: {
                    "status": "ok",
                    "checked_at": "2026-06-02T00:00:00+00:00",
                    "observed": {"missing_count": 0},
                }
                def fake_run(cmd, **kwargs):
                    return FakeProc()
                mod.subprocess.run = fake_run
                result = mod.service_restart_action({"operator_scopes": ["operator.admin"], "services": ["recovery-loop"]}, root=root)
            finally:
                mod.service_observation_status = original_observation
                mod.subprocess.run = original_run
                mod.enqueue_service_control_audit = original_audit

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["command"], "services.restart")
        self.assertTrue(result["audit_async"])
        self.assertEqual(len(audit_calls), 1)
        event, audit_root = audit_calls[0]
        self.assertEqual(event["status"], "ok")
        self.assertEqual(event["target_services"], ["recovery-loop"])
        self.assertEqual(event["return_code"], 0)
        self.assertEqual(audit_root, root)

    def test_api_services_restart_route_calls_handler(self):
        mod = load_control_api()
        original_handler = mod.service_restart_action
        captured = {}
        try:
            def fake_service_restart_action(payload):
                captured["payload"] = payload
                return {"status": "ok", "command": "services.restart"}

            mod.service_restart_action = fake_service_restart_action
            body = json.dumps({"operator_scopes": ["operator.admin"]}).encode("utf-8")

            class DummyServicesRestartPostHandler:
                path = "/api/services/restart"
                headers = {"Content-Length": str(len(body))}
                rfile = io.BytesIO(body)

                def write_json(self, status, payload):
                    captured["status"] = status
                    captured["response"] = payload

            mod.ControlHandler.do_POST(DummyServicesRestartPostHandler())
        finally:
            mod.service_restart_action = original_handler

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["response"]["command"], "services.restart")
        self.assertEqual(captured["payload"]["operator_scopes"], ["operator.admin"])

    def test_api_runtime_plan_backlog_next_route_calls_handler(self):
        mod = load_control_api()
        original_handler = mod.runtime_plan_backlog_next
        captured = {}

        def fake_runtime_plan_backlog_next(payload):
            captured["payload"] = payload
            return {"status": "enqueued", "command": "plan.backlog.next"}

        body = json.dumps({"operator_scopes": ["operator.admin"]}).encode("utf-8")

        class DummyPlanBacklogNextPostHandler:
            path = "/api/runtime/plan-backlog-next"
            headers = {"Content-Length": str(len(body))}
            rfile = io.BytesIO(body)

            def write_json(self, status, payload):
                captured["status"] = status
                captured["response"] = payload

        try:
            mod.runtime_plan_backlog_next = fake_runtime_plan_backlog_next
            mod.ControlHandler.do_POST(DummyPlanBacklogNextPostHandler())
        finally:
            mod.runtime_plan_backlog_next = original_handler

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["response"]["command"], "plan.backlog.next")
        self.assertEqual(captured["payload"]["operator_scopes"], ["operator.admin"])

    def test_api_runtime_plan_debate_next_route_calls_handler(self):
        mod = load_control_api()
        original_handler = mod.runtime_plan_debate_next
        captured = {}

        def fake_runtime_plan_debate_next(payload):
            captured["payload"] = payload
            return {"status": "enqueued", "command": "plan.debate.next"}

        body = json.dumps({"operator_scopes": ["operator.admin"], "stage": "requirement_audit"}).encode("utf-8")

        class DummyPlanDebateNextPostHandler:
            path = "/api/runtime/plan-debate-next"
            headers = {"Content-Length": str(len(body))}
            rfile = io.BytesIO(body)

            def write_json(self, status, payload):
                captured["status"] = status
                captured["response"] = payload

        try:
            mod.runtime_plan_debate_next = fake_runtime_plan_debate_next
            mod.ControlHandler.do_POST(DummyPlanDebateNextPostHandler())
        finally:
            mod.runtime_plan_debate_next = original_handler

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["response"]["command"], "plan.debate.next")
        self.assertEqual(captured["payload"]["operator_scopes"], ["operator.admin"])
        self.assertEqual(captured["payload"]["stage"], "requirement_audit")

    def test_api_runtime_session_lane_latest_route_calls_handler(self):
        mod = load_control_api()
        original_handler = mod.runtime_session_lane_latest
        captured = {}

        def fake_runtime_session_lane_latest(payload):
            captured["payload"] = payload
            return {"status": "enqueued", "command": "session.lane.latest"}

        body = json.dumps({"operator_scopes": ["operator.admin"], "tail_turns": 1}).encode("utf-8")

        class DummySessionLaneLatestPostHandler:
            path = "/api/runtime/session-lane-latest"
            headers = {"Content-Length": str(len(body))}
            rfile = io.BytesIO(body)

            def write_json(self, status, payload):
                captured["status"] = status
                captured["response"] = payload

        try:
            mod.runtime_session_lane_latest = fake_runtime_session_lane_latest
            mod.ControlHandler.do_POST(DummySessionLaneLatestPostHandler())
        finally:
            mod.runtime_session_lane_latest = original_handler

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["response"]["command"], "session.lane.latest")
        self.assertEqual(captured["payload"]["operator_scopes"], ["operator.admin"])
        self.assertEqual(captured["payload"]["tail_turns"], 1)

    def test_runtime_plan_backlog_next_blocked_without_runtime_gate(self):
        mod = load_control_api()

        class FakeSupervisor:
            @staticmethod
            def runtime_state_from_summary(*args, **kwargs):
                return "waiting_for_review_closure", "closed_next_execution_task_missing"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_supervisor = mod.supervisor
            original_audit = mod.enqueue_service_control_audit
            audit_calls = []
            try:
                mod.supervisor = lambda: FakeSupervisor
                mod.enqueue_service_control_audit = lambda event, *, root: audit_calls.append((event, root))
                result = mod.runtime_plan_backlog_next({"operator_scopes": ["operator.admin"]}, root=root)
            finally:
                mod.supervisor = original_supervisor
                mod.enqueue_service_control_audit = original_audit

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["command"], "plan.backlog.next")
        self.assertEqual(result["gate"]["reason"], "phone_control_disarmed")
        self.assertEqual(result["runtime_state"], "waiting_for_review_closure")
        self.assertTrue(result["audit_async"])
        self.assertEqual(audit_calls[0][0]["status"], "blocked")
        self.assertEqual(audit_calls[0][1], root)

    def test_runtime_plan_backlog_next_returns_enqueued_backlog_paths(self):
        mod = load_control_api()
        calls = []

        class FakeSupervisor:
            @staticmethod
            def runtime_state_from_summary(*args, **kwargs):
                return "waiting_for_review_closure", "closed_next_execution_task_missing"

            @staticmethod
            def active_plan_id():
                return "active-plan"

            @staticmethod
            def load_plan(plan_id):
                return {"plan_id": plan_id, "execution_backlog": {}}

            @staticmethod
            def plan_execution_backlog_items(plan, *, count=0):
                return [{"task_id": "exec-001", "phase": "implement", "prompt": "do next"}]

            @staticmethod
            def enqueue_execution_backlog_items(plan, items, *, prefix="", timeout_seconds=3600, idle_timeout_seconds=300, auto_next=True):
                calls.append(
                    {
                        "plan": plan,
                        "items": items,
                        "prefix": prefix,
                        "timeout_seconds": timeout_seconds,
                        "idle_timeout_seconds": idle_timeout_seconds,
                        "auto_next": auto_next,
                    }
                )
                return [root / ".a9" / "tasks" / "queue" / "exec-001.md"]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_supervisor = mod.supervisor
            original_audit = mod.enqueue_service_control_audit
            audit_calls = []
            try:
                mod.supervisor = lambda: FakeSupervisor
                mod.enqueue_service_control_audit = lambda event, *, root: audit_calls.append((event, root))
                mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
                result = mod.runtime_plan_backlog_next(
                    {"operator_scopes": ["operator.admin"], "count": 1, "prefix": "phone", "auto_next": False},
                    root=root,
                )
            finally:
                mod.supervisor = original_supervisor
                mod.enqueue_service_control_audit = original_audit

        self.assertEqual(result["status"], "enqueued")
        self.assertEqual(result["plan_id"], "active-plan")
        self.assertEqual(result["queued_count"], 1)
        self.assertEqual(result["queued_task_paths"], [str(root / ".a9" / "tasks" / "queue" / "exec-001.md")])
        self.assertFalse(calls[0]["auto_next"])
        self.assertEqual(calls[0]["prefix"], "phone")
        self.assertEqual(result["runtime_state_reason"], "closed_next_execution_task_missing")
        self.assertTrue(result["audit_async"])
        self.assertEqual(audit_calls[0][0]["status"], "enqueued")

    def test_runtime_plan_backlog_next_no_items_returns_review_closure_diagnostics(self):
        mod = load_control_api()

        class FakeSupervisor:
            @staticmethod
            def runtime_state_from_summary(*args, **kwargs):
                return "waiting_for_review_closure", "closed_next_execution_task_missing"

            @staticmethod
            def active_plan_id():
                return "active-plan"

            @staticmethod
            def load_plan(plan_id):
                return {"plan_id": plan_id, "execution_backlog": {}}

            @staticmethod
            def plan_execution_backlog_items(plan, *, count=0):
                return []

        class FakeProvider:
            @staticmethod
            def audit_causal_memory_state(subject):
                return {
                    "schema": "a9.causal_memory_audit.v1",
                    "status": "review_required",
                    "subject": subject,
                    "conflict_count": 1,
                    "duplicate_count": 0,
                    "invalidation_candidates": [{"operation": "kg_invalidate_candidate"}],
                }

            @staticmethod
            def propose_causal_memory_repairs(audit, subject):
                return {
                    "schema": "a9.causal_memory_repair_proposal.v1",
                    "status": "review_required",
                    "proposal_count": 1,
                    "invalidation_candidates": [
                        {
                            "operation": "kg_invalidate_candidate",
                            "object": "A9 old route is stale.",
                            "requires_monitor_decision": True,
                        }
                    ],
                    "proposals": [{"id": "repair-0001", "status": "review_required"}],
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_supervisor = mod.supervisor
            original_provider = mod.mempalace_provider
            original_audit = mod.enqueue_service_control_audit
            audit_calls = []
            try:
                mod.supervisor = lambda: FakeSupervisor
                mod.mempalace_provider = lambda: FakeProvider
                mod.enqueue_service_control_audit = lambda event, *, root: audit_calls.append((event, root))
                mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
                result = mod.runtime_plan_backlog_next({"operator_scopes": ["operator.admin"], "count": 1}, root=root)
            finally:
                mod.supervisor = original_supervisor
                mod.mempalace_provider = original_provider
                mod.enqueue_service_control_audit = original_audit

        self.assertEqual(result["status"], "no_items")
        diagnostics = result["review_closure_diagnostics"]
        self.assertEqual(diagnostics["schema"], "a9.runtime_review_closure_diagnostics.v1")
        self.assertEqual(diagnostics["status"], "review_required")
        self.assertEqual(diagnostics["audit"]["conflict_count"], 1)
        self.assertEqual(diagnostics["repair_proposal"]["proposal_count"], 1)
        self.assertEqual(
            diagnostics["repair_proposal"]["invalidation_candidates"][0]["operation"],
            "kg_invalidate_candidate",
        )
        self.assertEqual(audit_calls[0][0]["review_closure_status"], "review_required")
        self.assertEqual(audit_calls[0][0]["review_closure_repair_proposals"], 1)

    def test_runtime_plan_debate_next_blocked_without_runtime_gate(self):
        mod = load_control_api()

        class FakeSupervisor:
            @staticmethod
            def runtime_state_from_summary(*args, **kwargs):
                return "waiting_for_review_closure", "closed_next_execution_task_missing"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_supervisor = mod.supervisor
            original_audit = mod.enqueue_service_control_audit
            audit_calls = []
            try:
                mod.supervisor = lambda: FakeSupervisor
                mod.enqueue_service_control_audit = lambda event, *, root: audit_calls.append((event, root))
                result = mod.runtime_plan_debate_next({"operator_scopes": ["operator.admin"]}, root=root)
            finally:
                mod.supervisor = original_supervisor
                mod.enqueue_service_control_audit = original_audit

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["command"], "plan.debate.next")
        self.assertEqual(result["gate"]["reason"], "phone_control_disarmed")
        self.assertEqual(result["runtime_state"], "waiting_for_review_closure")
        self.assertTrue(result["audit_async"])
        self.assertEqual(audit_calls[0][0]["status"], "blocked")

    def test_runtime_plan_debate_next_returns_enqueued_debate_path(self):
        mod = load_control_api()
        calls = []

        class FakeSupervisor:
            @staticmethod
            def runtime_state_from_summary(*args, **kwargs):
                return "waiting_for_review_closure", "closed_next_execution_task_missing"

            @staticmethod
            def active_plan_id():
                return "active-plan"

            @staticmethod
            def load_plan(plan_id):
                return {"plan_id": plan_id, "requirements_debate": {"status": "debating", "current_stage": "requirement_audit"}}

            @staticmethod
            def enqueue_plan_debate_task(plan, *, stage_id="", task_id="", extra="", phase="reference_scan", timeout_seconds=3600, idle_timeout_seconds=300, auto_next=False):
                calls.append(
                    {
                        "plan": plan,
                        "stage_id": stage_id,
                        "extra": extra,
                        "phase": phase,
                        "timeout_seconds": timeout_seconds,
                        "idle_timeout_seconds": idle_timeout_seconds,
                        "auto_next": auto_next,
                    }
                )
                return root / ".a9" / "tasks" / "queue" / "debate.md", {"status": "debating", "current_stage": stage_id or "requirement_audit"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_supervisor = mod.supervisor
            original_audit = mod.enqueue_service_control_audit
            audit_calls = []
            try:
                mod.supervisor = lambda: FakeSupervisor
                mod.enqueue_service_control_audit = lambda event, *, root: audit_calls.append((event, root))
                mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
                result = mod.runtime_plan_debate_next(
                    {"operator_scopes": ["operator.admin"], "stage": "requirement_audit", "extra": "tighten scope", "auto_next": False},
                    root=root,
                )
            finally:
                mod.supervisor = original_supervisor
                mod.enqueue_service_control_audit = original_audit

        self.assertEqual(result["status"], "enqueued")
        self.assertEqual(result["plan_id"], "active-plan")
        self.assertEqual(result["queued_task_path"], str(root / ".a9" / "tasks" / "queue" / "debate.md"))
        self.assertEqual(result["requirements_debate_current_stage"], "requirement_audit")
        self.assertFalse(calls[0]["auto_next"])
        self.assertEqual(calls[0]["extra"], "tighten scope")
        self.assertTrue(result["audit_async"])
        self.assertEqual(audit_calls[0][0]["status"], "enqueued")

    def test_runtime_session_refresh_trial_uses_latest_session_without_worker(self):
        mod = load_control_api()
        calls = {}

        class FakeTask:
            task_id = "mobile-session-refresh-trial-test"

        class FakeSupervisor:
            SESSION_REFRESH_PHASE = "session_refresh"

            @staticmethod
            def enqueue_task_file(task_id, prompt, **kwargs):
                calls["task_id"] = task_id
                calls["prompt"] = prompt
                calls["kwargs"] = kwargs
                path = root / ".a9" / "tasks" / "queue" / f"{task_id}.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(prompt, encoding="utf-8")
                return path

            @staticmethod
            def parse_task(path):
                calls["parse_path"] = str(path)
                return FakeTask()

            @staticmethod
            def run_session_refresh_task(task, auto_next=False):
                calls["run_task_id"] = task.task_id
                calls["auto_next"] = auto_next
                return 0

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "codex-sessions"
            session = sessions / "2026" / "05" / "26" / "trial.jsonl"
            session.parent.mkdir(parents=True)
            rows = [
                {"type": "session_meta", "payload": {"id": "trial-session"}},
                {
                    "type": "response_item",
                    "timestamp": "2026-05-26T00:00:00Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "mobile trial request"}],
                    },
                },
            ]
            session.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            old_root = mod.ROOT
            old_base = mod.CODEX_SESSIONS_DIR
            old_supervisor = mod.supervisor
            mod.ROOT = root
            mod.CODEX_SESSIONS_DIR = sessions
            mod.supervisor = lambda: FakeSupervisor
            try:
                blocked = mod.runtime_session_refresh_trial({"operator_scopes": ["operator.admin"]})
                self.assertEqual(blocked["status"], "blocked")

                mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
                result = mod.runtime_session_refresh_trial({"operator_scopes": ["operator.admin"]})
                self.assertEqual(result["status"], "run-complete")
                self.assertEqual(result["command"], "session.refresh.trial")
                self.assertEqual(result["turn"], 1)
                self.assertEqual(result["source_session_path"], str(session))
                self.assertEqual(calls["kwargs"]["phase"], "session_refresh")
                self.assertIn("auto_close_reading: false", calls["prompt"])
                self.assertIn("from_turn: 1", calls["prompt"])
                self.assertEqual(calls["auto_next"], False)
            finally:
                mod.ROOT = old_root
                mod.CODEX_SESSIONS_DIR = old_base
                mod.supervisor = old_supervisor

    def test_runtime_session_lane_latest_enqueues_without_worker(self):
        mod = load_control_api()
        calls = {}

        class FakeSupervisor:
            SESSION_REFRESH_PHASE = "session_refresh"

            @staticmethod
            def latest_codex_session_path():
                return root / "codex-sessions" / "latest.jsonl"

            @staticmethod
            def latest_session_tail_range(session_path, *, tail_turns, batch_size):
                calls["session_path"] = str(session_path)
                calls["tail_turns"] = tail_turns
                calls["batch_size"] = batch_size
                return {
                    "session_id": "latest-session",
                    "source_session_path": str(session_path),
                    "user_turn_count": 7,
                    "from_turn": 6,
                    "to_turn": 7,
                    "batch_size": batch_size,
                }

            @staticmethod
            def compact_task_ref(value):
                return str(value)

            @staticmethod
            def enqueue_task_file(task_id, prompt, **kwargs):
                calls["task_id"] = task_id
                calls["prompt"] = prompt
                calls["kwargs"] = kwargs
                path = root / ".a9" / "tasks" / "queue" / f"{task_id}.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(prompt, encoding="utf-8")
                return path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = mod.ROOT
            old_supervisor = mod.supervisor
            audit_calls = []
            original_audit = mod.enqueue_service_control_audit
            mod.ROOT = root
            mod.supervisor = lambda: FakeSupervisor
            mod.enqueue_service_control_audit = lambda event, *, root=mod.ROOT: audit_calls.append((event, root))
            try:
                blocked = mod.runtime_session_lane_latest({"operator_scopes": ["operator.admin"]}, root=root)
                self.assertEqual(blocked["status"], "blocked")

                mod.phone_control_arm({"group": "runtime", "duration": "30s", "operator_scopes": ["operator.admin"]}, root=root)
                result = mod.runtime_session_lane_latest(
                    {"operator_scopes": ["operator.admin"], "tail_turns": 2, "batch_size": 1, "task_id": "api-session-lane"},
                    root=root,
                )
            finally:
                mod.ROOT = old_root
                mod.supervisor = old_supervisor
                mod.enqueue_service_control_audit = original_audit

        self.assertEqual(result["status"], "enqueued")
        self.assertEqual(result["command"], "session.lane.latest")
        self.assertEqual(result["from_turn"], 6)
        self.assertEqual(result["to_turn"], 7)
        self.assertFalse(result["called_model"])
        self.assertFalse(result["called_worker"])
        self.assertTrue(result["auto_close_reading"])
        self.assertEqual(calls["kwargs"]["phase"], "session_refresh")
        self.assertTrue(calls["kwargs"]["auto_next"])
        self.assertIn("auto_continue: false", calls["prompt"])
        self.assertIn("auto_close_reading: true", calls["prompt"])
        self.assertEqual(audit_calls[-1][0]["status"], "enqueued")
        self.assertEqual(audit_calls[-1][0]["command"], "session.lane.latest")


if __name__ == "__main__":
    unittest.main()
