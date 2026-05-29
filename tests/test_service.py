#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = ROOT / "scripts" / "a9_service.py"
SUPERVISOR_PATH = ROOT / "scripts" / "a9_supervisor.py"
UNIT_PATH = ROOT / "infra" / "systemd" / "a9-supervisor.service"
NODE_WORKER_UNIT_PATH = ROOT / "infra" / "systemd" / "a9-node-worker.service"


def load_service():
    spec = importlib.util.spec_from_file_location("a9_service", SERVICE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_supervisor():
    spec = importlib.util.spec_from_file_location("a9_supervisor", SUPERVISOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ServiceTests(unittest.TestCase):
    def test_systemd_unit_runs_auto_next_loop(self):
        unit = UNIT_PATH.read_text(encoding="utf-8")
        self.assertIn("ExecStart=/root/a9/scripts/a9_supervisor.py run-loop --auto-next", unit)
        self.assertIn("Restart=always", unit)
        self.assertIn("ExecStartPre=/root/a9/scripts/a9_middleware.py status", unit)

    def test_node_worker_systemd_unit_runs_command_loop(self):
        unit = NODE_WORKER_UNIT_PATH.read_text(encoding="utf-8")
        self.assertIn("ExecStart=/root/a9/scripts/a9_node.py command-work-loop", unit)
        self.assertIn("--block-ms 5000 --timeout 10", unit)
        self.assertIn("Restart=always", unit)
        self.assertIn("After=network-online.target docker.service a9-control-api.service", unit)

    def test_service_unit_command_prints_unit(self):
        result = subprocess.run(
            [str(SERVICE_PATH), "unit"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("[Unit]", result.stdout)
        self.assertIn("a9_supervisor.py run-loop --auto-next", result.stdout)
        self.assertIn("a9_node.py command-work-loop", result.stdout)

    def test_parse_process_table_finds_supervisor_node_worker_and_worker(self):
        mod = load_service()
        processes = mod.parse_process_table(
            """123 1 00:01:02 python3 scripts/a9_supervisor.py run-loop --auto-next
321 1 00:00:30 python3 scripts/a9_node.py command-work-loop --block-ms 5000
456 123 00:00:20 node /usr/local/bin/codex exec --json -C /tmp/work prompt
789 1 00:00:01 rg 'a9_supervisor.py run-loop|codex exec --json'
"""
        )

        self.assertEqual([item["kind"] for item in processes], ["supervisor", "node-worker", "worker"])
        self.assertEqual(processes[0]["pid"], 123)
        self.assertEqual(processes[2]["ppid"], 123)

    def test_service_ps_command_returns_json(self):
        result = subprocess.run(
            [str(SERVICE_PATH), "ps"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertIn("processes", payload)

    def test_service_stop_dry_run_returns_json(self):
        result = subprocess.run(
            [str(SERVICE_PATH), "stop", "--dry-run"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["target"], "supervisor")

    def test_service_readiness_returns_run_mode_json(self):
        result = subprocess.run(
            [str(SERVICE_PATH), "readiness"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertIn(result.returncode, (0, 1), result.stdout)
        payload = json.loads(result.stdout)
        self.assertIn(payload["mode"], {"not_ready", "bounded_ready", "daemon_ready"})
        self.assertIn("blockers", payload)
        self.assertIn("warnings", payload)
        self.assertIn("recommendation", payload)
        self.assertIn("git", payload)

    def test_daemon_heartbeat_is_json(self):
        mod = load_supervisor()
        payload = mod.write_daemon_heartbeat("test", detail="service-test")
        self.assertEqual(payload["state"], "test")
        heartbeat = json.loads(mod.DAEMON_HEARTBEAT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(heartbeat["detail"], "service-test")

    def test_service_progress_includes_compact_guard_status(self):
        mod = load_supervisor()
        progress = mod.service_progress(
            {
                "task_id": "guard-progress-test",
                "status": "pass",
                "run_dir": "/tmp/a9-run",
                "worker": {
                    "prompt_approx_tokens": 900,
                    "prompt_budget_tokens": 1000,
                    "prompt_section_budgets": {"repo_map": 250},
                    "previous_context_path": "/tmp/context.md",
                    "previous_context_compression": {"compressed_tokens": 300},
                    "repo_map": {"approx_tokens": 220, "budget_tokens": 250},
                },
                "patch_guard": {
                    "status": "pass",
                    "return_code": 0,
                    "kind": "unified_diff",
                    "touched_files": ["scripts/a9_supervisor.py"],
                    "findings": [],
                    "output_path": "/tmp/patch_guard.json",
                },
                "scope_guard": {
                    "status": "pass",
                    "return_code": 0,
                    "changed_files": ["scripts/a9_supervisor.py"],
                    "allowed_paths": ["scripts/"],
                    "findings": [],
                    "output_path": "/tmp/scope_guard.json",
                },
            }
        )

        self.assertEqual(progress["latest_guards"]["patch_guard"]["status"], "pass")
        self.assertEqual(progress["latest_guards"]["scope_guard"]["changed_files"], ["scripts/a9_supervisor.py"])
        self.assertEqual(progress["latest_context_pressure"]["budget_ratio"], 0.9)
        self.assertEqual(progress["latest_context_pressure"]["remaining_tokens"], 100)
        self.assertEqual(progress["capability_groups"]["runtime"]["percent"], 100.0)
        self.assertEqual(progress["capability_groups"]["context"]["percent"], 100.0)
        self.assertEqual(progress["capability_groups"]["automation"]["percent"], 100.0)
        self.assertEqual(progress["capability_groups"]["governance"]["percent"], 100.0)
        self.assertTrue(
            progress["capability_groups"]["governance"]["capabilities"]["rollback_aware_repair_prompt"]
        )
        self.assertTrue(
            progress["capability_groups"]["governance"]["capabilities"]["worker_event_budget_gate"]
        )


if __name__ == "__main__":
    unittest.main()
