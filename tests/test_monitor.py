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


if __name__ == "__main__":
    unittest.main()
