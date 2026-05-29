#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECOVERY_LOOP_PATH = ROOT / "scripts" / "a9_recovery_loop.py"


def load_module():
    spec = importlib.util.spec_from_file_location("a9_recovery_loop", RECOVERY_LOOP_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RecoveryLoopTests(unittest.TestCase):
    def test_recovery_cycle_once_reads_planning_endpoint_and_writes_latest(self):
        mod = load_module()
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            original_state = mod.STATE_DIR
            original_latest = mod.LATEST_PATH
            original_read = mod.read_json_url
            mod.STATE_DIR = Path(tmp) / "services"
            mod.LATEST_PATH = mod.STATE_DIR / "recovery-loop-latest.json"
            try:
                def fake_read(url, *, timeout=10):
                    calls.append((url, timeout))
                    return {
                        "status": "needs_attention",
                        "step_count": 2,
                        "execute": False,
                        "summary": {"risk_count": 2},
                    }

                mod.read_json_url = fake_read
                result = mod.recovery_cycle_once("http://controller:8787/", timeout=7, max_actions=2)
                latest = json.loads(mod.LATEST_PATH.read_text(encoding="utf-8"))
            finally:
                mod.STATE_DIR = original_state
                mod.LATEST_PATH = original_latest
                mod.read_json_url = original_read

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["cycle_status"], "needs_attention")
        self.assertEqual(result["step_count"], 2)
        self.assertEqual(result["risk_count"], 2)
        self.assertFalse(result["execute"])
        self.assertEqual(calls, [("http://controller:8787/api/nodes/recovery-cycle?max_actions=2", 7)])
        self.assertEqual(latest["cycle_status"], "needs_attention")

    def test_recovery_loop_runs_bounded_iterations_without_execute(self):
        mod = load_module()
        calls = []
        emitted = []
        original_once = mod.recovery_cycle_once
        original_sleep = mod.time.sleep
        try:
            mod.recovery_cycle_once = lambda controller_url, **kwargs: calls.append((controller_url, kwargs)) or {
                "status": "ok",
                "cycle_status": "ok",
            }
            mod.time.sleep = lambda seconds: emitted.append({"sleep": seconds})
            summary = mod.recovery_loop(
                "http://controller:8787",
                interval_seconds=1,
                timeout=5,
                max_actions=3,
                max_iterations=2,
                emit=emitted.append,
            )
        finally:
            mod.recovery_cycle_once = original_once
            mod.time.sleep = original_sleep

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["iterations"], 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]["max_actions"], 3)
        self.assertEqual(emitted[0]["cycle_status"], "ok")
        self.assertEqual(emitted[1], {"sleep": 1.0})


if __name__ == "__main__":
    unittest.main()
