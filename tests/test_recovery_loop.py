#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    def test_read_json_url_ignores_environment_proxy_for_local_controller(self):
        mod = load_module()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

            def log_message(self, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        previous = {key: os.environ.get(key) for key in ("HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy")}
        try:
            os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"
            os.environ["http_proxy"] = "http://127.0.0.1:9"
            os.environ["NO_PROXY"] = ""
            os.environ["no_proxy"] = ""
            thread.start()
            payload = mod.read_json_url(f"http://127.0.0.1:{server.server_port}/health", timeout=2)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual(payload, {"status": "ok"})

    def test_recovery_cycle_once_reads_planning_endpoint_and_writes_latest(self):
        mod = load_module()
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            original_state = mod.STATE_DIR
            original_latest = mod.LATEST_PATH
            original_observation = mod.COMMUNICATION_OBSERVATION_PATH
            original_suggestions = mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH
            original_read = mod.read_json_url
            mod.STATE_DIR = Path(tmp) / "services"
            mod.LATEST_PATH = mod.STATE_DIR / "recovery-loop-latest.json"
            mod.COMMUNICATION_OBSERVATION_PATH = mod.STATE_DIR / "communication-observation.json"
            mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH = mod.STATE_DIR / "communication-repair-suggestions.json"
            try:
                def fake_read(url, *, timeout=10):
                    calls.append((url, timeout))
                    if url.endswith("/api/communication/action-plan"):
                        return {
                            "status": "ok",
                            "plan_status": "ready",
                            "communication": {"action": "intervene", "priority_source": "recovery_loop"},
                            "route": {"endpoint": "/api/nodes/recovery-cycle", "arm_group": "remote"},
                        }
                    return {
                        "status": "needs_attention",
                        "step_count": 2,
                        "execute": False,
                        "summary": {"risk_count": 2},
                    }

                mod.read_json_url = fake_read
                result = mod.recovery_cycle_once("http://controller:8787/", timeout=7, max_actions=2)
                latest = json.loads(mod.LATEST_PATH.read_text(encoding="utf-8"))
                observation = json.loads(mod.COMMUNICATION_OBSERVATION_PATH.read_text(encoding="utf-8"))
                suggestions = json.loads(mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH.read_text(encoding="utf-8"))
            finally:
                mod.STATE_DIR = original_state
                mod.LATEST_PATH = original_latest
                mod.COMMUNICATION_OBSERVATION_PATH = original_observation
                mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH = original_suggestions
                mod.read_json_url = original_read

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["cycle_status"], "needs_attention")
        self.assertEqual(result["communication_plan_status"], "ready")
        self.assertEqual(result["communication_action"], "intervene")
        self.assertEqual(result["communication_priority_source"], "recovery_loop")
        self.assertEqual(result["communication_route"]["endpoint"], "/api/nodes/recovery-cycle")
        self.assertEqual(result["step_count"], 2)
        self.assertEqual(result["risk_count"], 2)
        self.assertFalse(result["execute"])
        self.assertEqual(
            calls,
            [
                ("http://controller:8787/api/communication/action-plan", 7),
                ("http://controller:8787/api/nodes/recovery-cycle?max_actions=2", 7),
            ],
        )
        self.assertEqual(latest["cycle_status"], "needs_attention")
        self.assertEqual(latest["communication_plan_status"], "ready")
        self.assertEqual(observation["current_key"], "recovery_loop:intervene:ready")
        self.assertEqual(observation["streak"], 1)
        self.assertEqual(observation["recommendation"], "operator_review")
        self.assertFalse(observation["auto_execute"])
        self.assertEqual(suggestions["pending_count"], 0)
        self.assertEqual(suggestions["last_observation"]["recommendation"], "operator_review")

    def test_recovery_cycle_once_does_not_post_repair_one_without_execute_flag(self):
        mod = load_module()
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            original_state = mod.STATE_DIR
            original_latest = mod.LATEST_PATH
            original_observation = mod.COMMUNICATION_OBSERVATION_PATH
            original_suggestions = mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH
            original_read = mod.read_json_url
            original_post = mod.post_json_url
            mod.STATE_DIR = Path(tmp) / "services"
            mod.LATEST_PATH = mod.STATE_DIR / "recovery-loop-latest.json"
            mod.COMMUNICATION_OBSERVATION_PATH = mod.STATE_DIR / "communication-observation.json"
            mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH = mod.STATE_DIR / "communication-repair-suggestions.json"
            try:
                def fake_read(url, *, timeout=10):
                    calls.append(("read", url, timeout))
                    if url.endswith("/api/communication/action-plan"):
                        return {
                            "status": "ok",
                            "plan_status": "ready",
                            "communication": {"action": "intervene", "priority_source": "tasks_stream"},
                            "route": {
                                "method": "POST",
                                "endpoint": "/api/communication/repair-one",
                            },
                            "payload": {"action": "recover_stale_commands", "stream": "tasks_stream"},
                        }
                    return {
                        "status": "needs_attention",
                        "step_count": 1,
                        "summary": {"risk_count": 0},
                    }

                def fake_post(url, payload, *, timeout=10):
                    calls.append(("post", url, timeout, payload))
                    return {"status": "unexpected"}

                mod.read_json_url = fake_read
                mod.post_json_url = fake_post
                result = mod.recovery_cycle_once("http://controller:8787/")
            finally:
                mod.STATE_DIR = original_state
                mod.LATEST_PATH = original_latest
                mod.COMMUNICATION_OBSERVATION_PATH = original_observation
                mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH = original_suggestions
                mod.read_json_url = original_read
                mod.post_json_url = original_post

        self.assertEqual(result["communication_route"]["endpoint"], "/api/communication/repair-one")
        self.assertEqual(result["communication_route_execution"]["reason"], "observe_only")
        self.assertEqual(
            [entry[0] for entry in calls if entry[0] == "post"],
            [],
        )
        self.assertEqual(
            calls[:2],
            [
                ("read", "http://controller:8787/api/communication/action-plan", 10),
                ("read", "http://controller:8787/api/nodes/recovery-cycle?max_actions=3", 10),
            ],
        )

    def test_recovery_cycle_once_posts_repair_one_when_execute_flag_enabled(self):
        mod = load_module()
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            original_state = mod.STATE_DIR
            original_latest = mod.LATEST_PATH
            original_observation = mod.COMMUNICATION_OBSERVATION_PATH
            original_suggestions = mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH
            original_read = mod.read_json_url
            original_post = mod.post_json_url
            mod.STATE_DIR = Path(tmp) / "services"
            mod.LATEST_PATH = mod.STATE_DIR / "recovery-loop-latest.json"
            mod.COMMUNICATION_OBSERVATION_PATH = mod.STATE_DIR / "communication-observation.json"
            mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH = mod.STATE_DIR / "communication-repair-suggestions.json"
            try:
                def fake_read(url, *, timeout=10):
                    if url.endswith("/api/communication/action-plan"):
                        return {
                            "status": "ok",
                            "plan_status": "ready",
                            "communication": {"action": "repair", "priority_source": "tasks_stream"},
                            "route": {
                                "method": "POST",
                                "endpoint": "/api/communication/repair-one",
                            },
                            "payload": {"action": "recover_stale_commands", "stream": "tasks_stream", "group": "workers"},
                        }
                    return {"status": "needs_attention", "step_count": 1, "summary": {"risk_count": 0}}

                def fake_post(url, payload, *, timeout=10):
                    calls.append(("post", url, timeout, payload))
                    return {"status": "ok", "kind": "communication_repair_one", "result": {"recovered": 1}}

                mod.read_json_url = fake_read
                mod.post_json_url = fake_post
                result = mod.recovery_cycle_once("http://controller:8787/", execute_communication_repair=True)
            finally:
                mod.STATE_DIR = original_state
                mod.LATEST_PATH = original_latest
                mod.COMMUNICATION_OBSERVATION_PATH = original_observation
                mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH = original_suggestions
                mod.read_json_url = original_read
                mod.post_json_url = original_post

        self.assertEqual(result["communication_route"]["endpoint"], "/api/communication/repair-one")
        self.assertEqual(result["communication_route_execution"]["status"], "ok")
        self.assertEqual(result["communication_route_execution"]["endpoint"], "/api/communication/repair-one")
        self.assertEqual(result["communication_route_execution"]["payload"]["group"], "workers")
        self.assertEqual(result["communication_route_execution"]["result"], {"status": "ok", "kind": "communication_repair_one", "result": {"recovered": 1}})
        self.assertEqual(calls, [("post", "http://controller:8787/api/communication/repair-one", 10, {"action": "recover_stale_commands", "stream": "tasks_stream", "group": "workers"})])

    def test_recovery_cycle_once_records_manual_required_when_route_unsupported(self):
        mod = load_module()
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            original_state = mod.STATE_DIR
            original_latest = mod.LATEST_PATH
            original_observation = mod.COMMUNICATION_OBSERVATION_PATH
            original_suggestions = mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH
            original_read = mod.read_json_url
            original_post = mod.post_json_url
            mod.STATE_DIR = Path(tmp) / "services"
            mod.LATEST_PATH = mod.STATE_DIR / "recovery-loop-latest.json"
            mod.COMMUNICATION_OBSERVATION_PATH = mod.STATE_DIR / "communication-observation.json"
            mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH = mod.STATE_DIR / "communication-repair-suggestions.json"
            try:
                def fake_read(url, *, timeout=10):
                    if url.endswith("/api/communication/action-plan"):
                        return {
                            "status": "ok",
                            "plan_status": "ready",
                            "communication": {"action": "repair", "priority_source": "tasks_stream"},
                            "route": {"method": "POST", "endpoint": "/api/communication/unsupported", "payload": {}},
                        }
                    return {"status": "needs_attention", "step_count": 1, "summary": {"risk_count": 0}}

                def fake_post(url, payload, *, timeout=10):
                    calls.append(("post", url, timeout, payload))
                    return {"status": "unexpected"}

                mod.read_json_url = fake_read
                mod.post_json_url = fake_post
                result = mod.recovery_cycle_once("http://controller:8787/", execute_communication_repair=True)
            finally:
                mod.STATE_DIR = original_state
                mod.LATEST_PATH = original_latest
                mod.COMMUNICATION_OBSERVATION_PATH = original_observation
                mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH = original_suggestions
                mod.read_json_url = original_read
                mod.post_json_url = original_post

        self.assertEqual(result["communication_route_execution"]["status"], "manual_required")
        self.assertEqual(result["communication_route_execution"]["reason"], "unsupported_route")
        self.assertEqual(calls, [])

    def test_communication_observation_updates_streak_without_executing(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "communication-observation.json"
            first = mod.communication_observation_update(
                {
                    "checked_at": "2026-06-01T00:00:00+00:00",
                    "communication_action": "intervene",
                    "communication_priority_source": "recovery_loop",
                    "communication_plan_status": "ready",
                    "communication_route": {"endpoint": "/api/nodes/recovery-cycle"},
                },
                path=path,
            )
            second = mod.communication_observation_update(
                {
                    "checked_at": "2026-06-01T00:01:00+00:00",
                    "communication_action": "intervene",
                    "communication_priority_source": "recovery_loop",
                    "communication_plan_status": "ready",
                    "communication_route": {"endpoint": "/api/nodes/recovery-cycle"},
                },
                path=path,
            )

        self.assertEqual(first["streak"], 1)
        self.assertEqual(second["streak"], 2)
        self.assertEqual(second["first_seen_at"], "2026-06-01T00:00:00+00:00")
        self.assertEqual(second["recommendation"], "candidate_for_repair_one")
        self.assertFalse(second["auto_execute"])

    def test_communication_repair_suggestions_writes_pending_candidate_without_execution(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "communication-repair-suggestions.json"
            queue = mod.communication_repair_suggestions_update(
                {
                    "current_key": "recovery_loop:intervene:ready",
                    "action": "intervene",
                    "priority_source": "recovery_loop",
                    "plan_status": "ready",
                    "streak": 2,
                    "first_seen_at": "2026-06-01T00:00:00+00:00",
                    "last_seen_at": "2026-06-01T00:01:00+00:00",
                    "recommendation": "candidate_for_repair_one",
                    "route": {"endpoint": "/api/nodes/recovery-cycle", "arm_group": "remote"},
                },
                {"cycle_status": "needs_attention", "risk_count": 1},
                path=path,
            )
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(queue["pending_count"], 1)
        self.assertEqual(saved["pending"][0]["suggestion_id"], "recovery_loop-intervene-ready")
        self.assertEqual(saved["pending"][0]["route"]["endpoint"], "/api/nodes/recovery-cycle")
        self.assertEqual(saved["pending"][0]["operator_action"], "review_then_arm_and_repair_one")
        self.assertFalse(saved["pending"][0]["auto_execute"])

    def test_recovery_cycle_once_classifies_controller_unavailable_for_observation(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            original_state = mod.STATE_DIR
            original_latest = mod.LATEST_PATH
            original_observation = mod.COMMUNICATION_OBSERVATION_PATH
            original_suggestions = mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH
            original_read = mod.read_json_url
            mod.STATE_DIR = Path(tmp) / "services"
            mod.LATEST_PATH = mod.STATE_DIR / "recovery-loop-latest.json"
            mod.COMMUNICATION_OBSERVATION_PATH = mod.STATE_DIR / "communication-observation.json"
            mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH = mod.STATE_DIR / "communication-repair-suggestions.json"
            try:
                def fake_read(_url, *, timeout=10):
                    raise OSError("controller down")

                mod.read_json_url = fake_read
                result = mod.recovery_cycle_once("http://controller:8787/", timeout=7, max_actions=2)
                observation = json.loads(mod.COMMUNICATION_OBSERVATION_PATH.read_text(encoding="utf-8"))
            finally:
                mod.STATE_DIR = original_state
                mod.LATEST_PATH = original_latest
                mod.COMMUNICATION_OBSERVATION_PATH = original_observation
                mod.COMMUNICATION_REPAIR_SUGGESTIONS_PATH = original_suggestions
                mod.read_json_url = original_read

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["communication_plan_status"], "unavailable")
        self.assertEqual(result["communication_action"], "intervene")
        self.assertEqual(result["communication_priority_source"], "controller")
        self.assertEqual(observation["current_key"], "controller:intervene:unavailable")
        self.assertEqual(observation["recommendation"], "operator_review")

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
