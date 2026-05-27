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
    def write_run(self, root: Path, summary: dict, events: list[dict]) -> Path:
        run_dir = root / "run"
        run_dir.mkdir()
        event_path = run_dir / "event_summaries.jsonl"
        event_path.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in events),
            encoding="utf-8",
        )
        summary.setdefault("worker", {})["event_summaries_path"] = str(event_path)
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
        self.assertIn("governance", {item["name"] for item in score["experts"]})
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
        self.assertEqual(score["recommended_action"], "monitor_review")
        self.assertEqual(
            [item for item in score["experts"] if item["name"] == "testing"][0]["recommended_action"],
            "monitor_review",
        )
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
        self.assertEqual(experts["architecture"]["recommended_action"], "narrow_task")
        self.assertIn("business_scope_drift", kinds)
        self.assertIn("broad_reference_scan", kinds)

    def test_write_score_creates_monitor_score_json(self):
        mod = load_monitor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.write_run(
                Path(tmp),
                {"status": "pass", "worker": {}, "worker_envelope": {"status": "pass"}, "checks": []},
                [],
            )
            payload = mod.score_run(run_dir)
            path = mod.write_score(run_dir, payload)

            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["recommended_action"], "continue")


if __name__ == "__main__":
    unittest.main()
