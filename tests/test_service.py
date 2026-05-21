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


if __name__ == "__main__":
    unittest.main()
