#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONITOR_PATH = ROOT / "scripts" / "a9_monitor.py"


def load_monitor():
    spec = importlib.util.spec_from_file_location("a9_monitor", MONITOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MonitorTests(unittest.TestCase):
    def write_run(self, root: Path, summary: dict, events: list[dict], task_text: str | None = None) -> Path:
        run_dir = root / "run"
        run_dir.mkdir()
        event_path = run_dir / "event_summaries.jsonl"
        event_path.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in events),
            encoding="utf-8",
        )
        summary.setdefault("worker", {})["event_summaries_path"] = str(event_path)
        raw_task_path = run_dir / "raw_task.md"
        raw_task_path.write_text(
            task_text
            or (
                "Goal: protect A9 mainline and requirements.\n"
                "Why: keep worker aligned with product philosophy and business logic.\n"
                "System behavior: input trace, output council gates, state evidence, error action.\n"
                "Tradeoff: reject broad weak work, shrink scope, keep monitor/worker roles explicit.\n"
                "Hard bounds: allowed_paths are explicit; tests are declared.\n"
            ),
            encoding="utf-8",
        )
        summary["worker"]["raw_task_path"] = str(raw_task_path)
        (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return run_dir

    def test_score_flags_forbidden_session_and_service_reads(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {
                    "status": "retryable-worker-budget",
                    "worker": {
                        "budget_stopped": True,
                        "budget_reason": "worker event bytes exceeded 120000",
                        "event_bytes": 122064,
                    },
                    "worker_envelope": {"status": "fail"},
                    "checks": [],
                },
                [
                    {
                        "item_type": "command_execution",
                        "command": "python3 scripts/a9_service.py ps",
                        "exit_code": 0,
                    },
                    {
                        "item_type": "command_execution",
                        "command": "tail -n 40 docs/session-raw-summary.md",
                        "exit_code": 0,
                    },
                ],
            )

            score = mod.score_run(run_dir)

        kinds = {item["kind"] for item in score["findings"]}
        self.assertGreaterEqual(score["score"], 0.75)
        self.assertEqual(score["recommended_action"], "block_and_rewrite_task")
        self.assertIn("execution_governance_expert", {item["name"] for item in score["experts"]})
        self.assertIn("budget_stopped", kinds)
        self.assertIn("service_status", kinds)
        self.assertIn("session_docs", kinds)
        self.assertIn("worker_envelope_fail", kinds)

    def test_score_flags_undeclared_pytest_without_replacing_declared_check(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {
                    "status": "pass",
                    "worker": {"budget_stopped": False},
                    "worker_envelope": {"status": "pass"},
                    "checks": [{"command": "python3 -m unittest tests/test_control_api.py", "return_code": 0}],
                },
                [
                    {
                        "item_type": "command_execution",
                        "command": "python3 -m pytest -q tests/test_control_api.py -k retry",
                        "exit_code": 1,
                        "output_preview": "/usr/bin/python3: No module named pytest\n",
                    }
                ],
            )

            score = mod.score_run(run_dir)

        kinds = {item["kind"] for item in score["findings"]}
        self.assertEqual(score["recommended_action"], "block_and_rewrite_task")
        self.assertEqual(
            [item for item in score["experts"] if item["name"] == "test_verifiability_expert"][0]["recommended_action"],
            "monitor_review",
        )
        self.assertEqual(score["gates"]["hard_gate"]["status"], "fail")
        self.assertIn("undeclared_check", kinds)
        self.assertIn("pytest_not_declared", kinds)

    def test_unittest_file_and_module_forms_match_declared_check(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {
                    "status": "pass",
                    "worker": {"budget_stopped": False},
                    "worker_envelope": {"status": "pass"},
                    "checks": [{"command": "python3 -m unittest tests/test_remote.py", "return_code": 0}],
                },
                [
                    {
                        "item_type": "command_execution",
                        "command": "/bin/bash -lc 'python3 -m unittest tests.test_remote'",
                        "exit_code": 0,
                    }
                ],
            )

            score = mod.score_run(run_dir)

        kinds = {item["kind"] for item in score["findings"]}
        self.assertNotIn("undeclared_check", kinds)

    def test_moe_flags_architecture_and_business_scope_separately(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {"status": "pass", "worker": {}, "worker_envelope": {"status": "pass"}, "checks": []},
                [
                    {
                        "item_type": "command_execution",
                        "command": "rg -n reconnect /root/a9/reference-projects/aider",
                    },
                    {
                        "item_type": "command_execution",
                        "command": "rg -n trading_strategy docs scripts",
                    },
                ],
            )

            score = mod.score_run(run_dir)

        experts = {item["name"]: item for item in score["experts"]}
        kinds = {item["kind"] for item in score["findings"]}
        self.assertEqual(experts["tradeoff_architecture_expert"]["recommended_action"], "narrow_task")
        self.assertIn("business_scope_drift", kinds)
        self.assertIn("broad_reference_scan", kinds)

    def test_business_boundary_does_not_flag_barter_strategy_reference_path(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {"status": "pass", "worker": {}, "worker_envelope": {"status": "pass"}, "checks": []},
                [
                    {
                        "item_type": "command_execution",
                        "command": "sed -n '1,120p' reference-projects/barter-rs/barter/src/strategy/on_disconnect.rs",
                    }
                ],
            )

            score = mod.score_run(run_dir)

        kinds = {item["kind"] for item in score["findings"]}
        self.assertNotIn("business_scope_drift", kinds)

    def test_write_score_creates_monitor_score_json(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {
                    "status": "pass",
                    "phase": "record",
                    "worker": {},
                    "worker_envelope": {"status": "pass"},
                    "checks": [{"command": "python3 -m unittest tests/test_monitor.py", "return_code": 0}],
                },
                [],
            )
            payload = mod.score_run(run_dir)
            path = mod.write_score(run_dir, payload)

            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["recommended_action"], "continue")

    def test_product_mainline_and_pressure_are_first_class_gates(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {"status": "pass", "phase": "implement", "worker": {}, "worker_envelope": {"status": "pass"}, "checks": []},
                [],
                task_text=(
                    "Goal: implement a helper.\n"
                    "Why: make engineering cleaner.\n"
                    "System behavior: input trace, output json state, error action.\n"
                    "Hard bounds: allowed_paths explicit.\n"
                ),
            )

            score = mod.score_run(run_dir)

        experts = {item["name"]: item for item in score["experts"]}
        kinds = {item["kind"] for item in score["findings"]}
        self.assertIn("mainline_not_named", kinds)
        self.assertIn("no_pressure_or_rejection_frame", kinds)
        self.assertEqual(experts["product_mainline_expert"]["recommended_action"], "continue")
        self.assertEqual(experts["product_pressure_expert"]["recommended_action"], "product_rewrite")
        self.assertEqual(score["gates"]["tradeoff_gate"]["status"], "fail")
        role_review = score["role_review"]
        roles = {item["name"]: item for item in role_review["roles"]}
        self.assertEqual(role_review["schema"], "a9.role_review.v1")
        self.assertEqual(roles["product_mainline_role"]["status"], "fail")
        self.assertIn("product_mainline_role", role_review["failed_roles"])

    def test_external_learning_blocks_copy_task_without_reference_evidence(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {"status": "pass", "phase": "reference_scan", "worker": {}, "worker_envelope": {"status": "pass"}, "checks": []},
                [],
                task_text=(
                    "Goal: 抄顶级项目机制。\n"
                    "Why: A9 mainline needs external learning.\n"
                    "System behavior: input repo, output mechanism notes, state evidence, error action.\n"
                    "Tradeoff: reject weak self-invented design and shrink scope.\n"
                    "Hard bounds: allowed_paths explicit; monitor and worker roles explicit.\n"
                ),
            )

            score = mod.score_run(run_dir)

        kinds = {item["kind"] for item in score["findings"]}
        self.assertIn("no_external_or_reference_learning", kinds)
        self.assertEqual(score["recommended_action"], "block_and_rewrite_task")

    def test_data_sensitive_task_requires_data_structure_acceptance(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {
                    "status": "pass",
                    "phase": "implement",
                    "worker": {},
                    "worker_envelope": {"status": "pass"},
                    "checks": [{"command": "python3 -m unittest tests/test_control_api.py", "return_code": 0}],
                },
                [],
                task_text=(
                    "Goal: update mobile control api.\n"
                    "Why: keep A9 mainline controllable from the phone.\n"
                    "System behavior: input request, output json response, error action.\n"
                    "Tradeoff: reject broad UI polish and shrink scope.\n"
                    "Hard bounds: allowed_paths explicit; monitor and worker roles explicit.\n"
                    "Performance: keep latency and budget stable.\n"
                ),
            )

            score = mod.score_run(run_dir)

        kinds = {item["kind"] for item in score["findings"]}
        self.assertIn("data_structure_acceptance_missing", kinds)
        self.assertIn("data_model_not_explicit", kinds)
        self.assertEqual(score["gates"]["hard_gate"]["status"], "fail")

    def test_data_structure_acceptance_can_pass_when_schema_state_is_explicit(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {
                    "status": "pass",
                    "phase": "implement",
                    "worker": {},
                    "worker_envelope": {"status": "pass"},
                    "checks": [{"command": "python3 -m unittest tests/test_control_api.py  # validates event/state schema", "return_code": 0}],
                },
                [],
                task_text=(
                    "Goal: update mobile control api.\n"
                    "Why: keep A9 mainline controllable from the phone.\n"
                    "System behavior: input request, output json event/state schema, error action.\n"
                    "Data model: session table, run state, command event, and error state must match business structure.\n"
                    "Tradeoff: reject broad UI polish and shrink scope.\n"
                    "Hard bounds: allowed_paths explicit; monitor and worker roles explicit.\n"
                    "Performance: keep latency and budget stable.\n"
                ),
            )

            score = mod.score_run(run_dir)

        kinds = {item["kind"] for item in score["findings"]}
        self.assertNotIn("data_structure_acceptance_missing", kinds)
        self.assertNotIn("data_model_not_explicit", kinds)

    def test_communication_control_api_requires_explicit_event_state_schema(self):
        mod = load_monitor()
        cases = [
            {
                "name": "missing_schema_state_fails_hard_gate",
                "task_text": (
                    "Goal: implement communication gateway node-status control API task handling.\n"
                    "Why: operators need reliable remote control across reconnect and failure scenarios.\n"
                    "System behavior: input control request, output node status response, enforce bounded error action.\n"
                    "Tradeoff: keep implementation narrow and reject broad feature expansion.\n"
                    "Hard bounds: monitor/worker role boundary, allowed paths, retry budget.\n"
                    "Performance: keep gateway latency stable and preserve reconnect stability under load.\n"
                ),
                "expects_data_model_missing": True,
            },
            {
                "name": "explicit_schema_state_passes_data_model_gate",
                "task_text": (
                    "Goal: implement communication gateway node-status control API task handling.\n"
                    "Why: operators need reliable remote control across reconnect and failure scenarios.\n"
                    "System behavior: input control request, output node status response, enforce bounded error action.\n"
                    "Data model: node table stores node_id/last_seen/connection_state; heartbeat event stream records reconnect events; "
                    "tmux evidence state records session attach status; command status schema includes request_id/status/error_code/updated_at.\n"
                    "Tradeoff: keep implementation narrow and reject broad feature expansion.\n"
                    "Hard bounds: monitor/worker role boundary, allowed paths, retry budget.\n"
                    "Performance: keep gateway latency stable and preserve reconnect stability under load.\n"
                ),
                "expects_data_model_missing": False,
            },
        ]

        for case in cases:
            with self.subTest(case=case["name"]):
                with tempfile.TemporaryDirectory() as tmp:
                    run_dir = self.write_run(
                        Path(tmp),
                        {
                            "status": "pass",
                            "phase": "implement",
                            "worker": {},
                            "worker_envelope": {"status": "pass"},
                            "checks": [{"command": "python3 -m unittest tests/test_control_api.py", "return_code": 0}],
                        },
                        [],
                        task_text=case["task_text"],
                    )
                    score = mod.score_run(run_dir)

                kinds = {item["kind"] for item in score["findings"]}
                if case["expects_data_model_missing"]:
                    self.assertIn("data_model_not_explicit", kinds)
                    self.assertIn("data_model_expert", score["gates"]["hard_gate"]["failed_experts"])
                else:
                    self.assertNotIn("data_model_not_explicit", kinds)

    def test_communication_task_requires_explicit_performance_depth_bounds(self):
        mod = load_monitor()
        cases = [
            {
                "name": "missing_performance_bounds_requires_tradeoff",
                "task_text": (
                    "Goal: implement communication gateway SSH/tmux/Redis control API task orchestration.\n"
                    "Why: operators must keep remote execution governable during reconnect and failure recovery.\n"
                    "System behavior: input control request, emit event/state transition, return bounded error action.\n"
                    "Data model: request state table, gateway event stream, node heartbeat state, command status schema.\n"
                    "Tradeoff: keep scope narrow and reject broad platform feature expansion.\n"
                    "Hard bounds: monitor/worker boundary and allowed paths are explicit.\n"
                ),
                "expects_performance_missing": True,
            },
            {
                "name": "explicit_performance_bounds_passes_performance_depth_gate",
                "task_text": (
                    "Goal: implement communication gateway SSH/tmux/Redis control API task orchestration.\n"
                    "Why: operators must keep remote execution governable during reconnect and failure recovery.\n"
                    "System behavior: input control request, emit event/state transition, return bounded error action.\n"
                    "Data model: request state table, gateway event stream, node heartbeat state, command status schema.\n"
                    "Tradeoff: keep scope narrow and reject broad platform feature expansion.\n"
                    "Hard bounds: monitor/worker boundary and allowed paths are explicit.\n"
                    "Performance bounds: p95 latency <= 250ms; per-request timeout 5s; reconnect retry budget <= 3 per minute; "
                    "SSH/tmux session stability target >= 99.9%; Redis event budget <= 500 events per task.\n"
                ),
                "expects_performance_missing": False,
            },
        ]

        for case in cases:
            with self.subTest(case=case["name"]):
                with tempfile.TemporaryDirectory() as tmp:
                    run_dir = self.write_run(
                        Path(tmp),
                        {
                            "status": "pass",
                            "phase": "implement",
                            "worker": {},
                            "worker_envelope": {"status": "pass"},
                            "checks": [{"command": "python3 -m unittest tests/test_control_api.py", "return_code": 0}],
                        },
                        [],
                        task_text=case["task_text"],
                    )
                    score = mod.score_run(run_dir)

                kinds = {item["kind"] for item in score["findings"]}
                performance_expert = next(item for item in score["experts"] if item["name"] == "performance_depth_expert")
                if case["expects_performance_missing"]:
                    self.assertIn("performance_depth_not_explicit", kinds)
                    self.assertNotEqual(performance_expert["recommended_action"], "continue")
                else:
                    self.assertNotIn("performance_depth_not_explicit", kinds)

    def test_communication_task_requires_failure_taxonomy_and_recovery_mapping(self):
        mod = load_monitor()
        cases = [
            {
                "name": "missing_failure_taxonomy_triggers_exception_governance_finding",
                "task_text": (
                    "Goal: implement communication gateway SSH/tmux/Redis control API task orchestration.\n"
                    "Why: operators must keep remote execution governable during reconnect and failure recovery.\n"
                    "System behavior: input control request, emit event/state transition, return bounded error action.\n"
                    "Data model: request state table, gateway event stream, node heartbeat state, command status schema.\n"
                    "Tradeoff: keep scope narrow and reject broad platform feature expansion.\n"
                    "Hard bounds: monitor/worker boundary and allowed paths are explicit.\n"
                    "Performance bounds: p95 latency <= 250ms; per-request timeout 5s; reconnect retry budget <= 3 per minute.\n"
                ),
                "expects_missing": True,
            },
            {
                "name": "explicit_failure_taxonomy_and_mapping_passes",
                "task_text": (
                    "Goal: implement communication gateway SSH/tmux/Redis control API task orchestration.\n"
                    "Why: operators must keep remote execution governable during reconnect and failure recovery.\n"
                    "System behavior: input control request, emit event/state transition, return bounded error action.\n"
                    "Data model: request state table, gateway event stream, node heartbeat state, command status schema.\n"
                    "Tradeoff: keep scope narrow and reject broad platform feature expansion.\n"
                    "Hard bounds: monitor/worker boundary and allowed paths are explicit.\n"
                    "Performance bounds: p95 latency <= 250ms; per-request timeout 5s; reconnect retry budget <= 3 per minute.\n"
                    "Failure taxonomy -> recovery mapping: timeout->retry, auth->repair, network->retry, protocol->quarantine, rate_limit->terminate.\n"
                ),
                "expects_missing": False,
            },
        ]

        for case in cases:
            with self.subTest(case=case["name"]):
                with tempfile.TemporaryDirectory() as tmp:
                    run_dir = self.write_run(
                        Path(tmp),
                        {
                            "status": "pass",
                            "phase": "implement",
                            "worker": {},
                            "worker_envelope": {"status": "pass"},
                            "checks": [{"command": "python3 -m unittest tests/test_control_api.py", "return_code": 0}],
                        },
                        [],
                        task_text=case["task_text"],
                    )
                    score = mod.score_run(run_dir)

                kinds = {item["kind"] for item in score["findings"]}
                exception_expert = next(item for item in score["experts"] if item["name"] == "exception_governance_expert")
                if case["expects_missing"]:
                    self.assertIn("communication_failure_taxonomy_missing", kinds)
                    self.assertIn(
                        "exception_governance_expert",
                        score["gates"]["hard_gate"]["failed_experts"],
                    )
                    self.assertNotEqual(exception_expert["recommended_action"], "continue")
                else:
                    self.assertNotIn("communication_failure_taxonomy_missing", kinds)
                    self.assertNotIn(
                        "exception_governance_expert",
                        score["gates"]["hard_gate"]["failed_experts"],
                    )

    def test_context_repo_map_task_does_not_trigger_communication_failure_taxonomy_gate(self):
        mod = load_monitor()
        task_text = (
            "Goal: Make context packet repo map prefer task allowed_paths so narrow worker tasks do not receive "
            "unrelated communication governance document noise.\n"
            "Mainline: Context/token governance. Build repo map from allowed_paths and reduce prompt noise.\n"
            "Scope: scripts/a9_supervisor.py and tests/test_supervisor.py.\n"
            "Declared checks: python3 -m unittest tests/test_supervisor.py; git diff --check.\n"
        )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {
                    "status": "pass",
                    "phase": "implement",
                    "worker": {},
                    "worker_envelope": {"status": "pass"},
                    "checks": [{"command": "python3 -m unittest tests/test_supervisor.py", "return_code": 0}],
                },
                [],
                task_text=task_text,
            )
            score = mod.score_run(run_dir)

        kinds = {item["kind"] for item in score["findings"]}
        self.assertNotIn("communication_failure_taxonomy_missing", kinds)
        self.assertNotIn("exception_governance_expert", score["gates"]["hard_gate"]["failed_experts"])

    def test_worker_envelope_apply_task_does_not_trigger_communication_failure_taxonomy_gate(self):
        mod = load_monitor()
        task_text = (
            "Goal: verify strict worker envelope protocol for deterministic apply.\n"
            "Task: emit output.search_replace_blocks so A9 can apply SEARCH/REPLACE patches.\n"
            "Scope: docs/mistakes.md only; this is an apply protocol smoke, not communication gateway work.\n"
            "Hard bounds: one bounded read, strict JSON envelope, deterministic apply.\n"
        )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {
                    "status": "pass",
                    "phase": "record",
                    "worker": {},
                    "worker_envelope": {"status": "pass"},
                    "checks": [{"command": "python3 -m unittest tests/test_supervisor.py", "return_code": 0}],
                },
                [],
                task_text=task_text,
            )
            score = mod.score_run(run_dir)

        kinds = {item["kind"] for item in score["findings"]}
        self.assertNotIn("communication_failure_taxonomy_missing", kinds)
        self.assertNotIn("exception_governance_expert", score["gates"]["hard_gate"]["failed_experts"])

    def test_context_router_blocked_sections_are_monitor_visible(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {
                    "status": "pass",
                    "phase": "implement",
                    "worker": {
                        "context_router": {
                            "blocked_sections": 2,
                            "blocked_section_names": ["reference_notes", "vendor_context"],
                        }
                    },
                    "context_pressure": {
                        "context_router": {
                            "blocked_sections": [
                                {"name": "reference_notes"},
                                {"name": "vendor_context"},
                            ]
                        }
                    },
                    "worker_envelope": {"status": "pass"},
                    "checks": [{"command": "python3 -m unittest tests/test_control_api.py", "return_code": 0}],
                },
                [],
            )
            score = mod.score_run(run_dir)

        finding = next(item for item in score["findings"] if item["kind"] == "context_router_blocked_promptware")
        self.assertEqual(finding["level"], "warn")
        self.assertEqual(finding["blocked_sections"], 2)
        self.assertEqual(finding["blocked_section_names"], ["reference_notes", "vendor_context"])
        self.assertEqual(score["gates"]["hard_gate"]["status"], "pass")
        self.assertNotIn("exception_governance_expert", score["gates"]["hard_gate"]["failed_experts"])

    def test_context_router_control_task_does_not_trigger_communication_taxonomy_gate(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {
                    "status": "pass",
                    "phase": "implement",
                    "worker": {"context_router": {"blocked_sections": 1}},
                    "worker_envelope": {"status": "pass"},
                    "checks": [{"command": "python3 -m unittest tests/test_monitor.py", "return_code": 0}],
                },
                [],
                task_text=(
                    "Goal: expose context router promptware blocking in monitor/control evidence.\n"
                    "Why: context governance findings must be visible to mobile/control without raw prompt text.\n"
                    "System behavior: input summary context_router, output monitor finding and state evidence.\n"
                    "Tradeoff: warn only because router already blocked the promptware; keep scope small.\n"
                    "Hard bounds: allowed_paths are explicit; tests are declared.\n"
                ),
            )
            score = mod.score_run(run_dir)

        kinds = {item["kind"] for item in score["findings"]}
        self.assertIn("context_router_blocked_promptware", kinds)
        self.assertNotIn("communication_failure_taxonomy_missing", kinds)
        self.assertEqual(score["gates"]["hard_gate"]["status"], "pass")

    def test_score_writes_moe_eval_contract_for_second_layer_evaluator(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {
                    "status": "pass",
                    "phase": "test",
                    "task_id": "moe-contract",
                    "worker": {"event_bytes": 42},
                    "worker_envelope": {"status": "pass"},
                    "checks": [{"command": "python3 -m unittest tests/test_monitor.py", "return_code": 0}],
                },
                [
                    {
                        "item_type": "command_execution",
                        "command": "python3 -m unittest tests/test_monitor.py",
                        "status": "completed",
                        "exit_code": 0,
                        "output_preview": "OK",
                    }
                ],
            )
            score = mod.score_run(run_dir)
            contract_path = Path(score["eval_contract_path"])
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract_exists = contract_path.exists()

        self.assertTrue(contract_exists)
        self.assertEqual(contract["schema"], "a9.moe_eval_contract.v1")
        self.assertEqual(contract["layers"]["rule_monitor"]["status"], "complete")
        self.assertEqual(contract["layers"]["llm_evaluator"]["status"], "not_configured")
        self.assertEqual(contract["layers"]["rule_monitor"]["role_review"]["schema"], "a9.role_review.v1")
        self.assertEqual(score["role_review"]["schema"], "a9.role_review.v1")
        self.assertIn("data_first", " ".join(contract["criteria"]))
        self.assertIn("recommended_action", contract["output_contract"]["required_fields"])
        self.assertIn("failed_roles", contract["output_contract"]["required_fields"])
        self.assertEqual(score["layers"]["llm_evaluator"]["status"], "not_configured")


if __name__ == "__main__":
    unittest.main()
