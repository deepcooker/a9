#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL_API_PATH = ROOT / "scripts" / "a9_control_api.py"


def load_control_api():
    spec = importlib.util.spec_from_file_location("a9_control_api", CONTROL_API_PATH)
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

    def test_supervisor_status_reads_existing_a9_state(self):
        mod = load_control_api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".a9" / "tasks" / "queue").mkdir(parents=True)
            (root / ".a9" / "tasks" / "running").mkdir(parents=True)
            (root / ".a9" / "tasks" / "done").mkdir(parents=True)
            (root / ".a9" / "runs" / "run-1").mkdir(parents=True)
            (root / ".a9" / "tasks" / "queue" / "task.md").write_text("demo", encoding="utf-8")
            (root / ".a9" / "progress.json").write_text('{"progress_percent": 1}', encoding="utf-8")
            (root / ".a9" / "runs" / "run-1" / "summary.json").write_text(
                json.dumps({"task_id": "task", "status": "pass", "run_dir": str(root / ".a9" / "runs" / "run-1")}),
                encoding="utf-8",
            )

            status = mod.supervisor_status(root)

        self.assertEqual(status["queued"], 1)
        self.assertEqual(status["latest_run"]["task_id"], "task")
        self.assertEqual(status["progress"]["progress_percent"], 1)
        self.assertEqual(status["nodes"]["count"], 0)
        self.assertEqual(status["gateway"]["status"], "missing")

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

    def test_node_status_communication_followup_continue_when_nodes_and_stream_healthy(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("2\n")
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
        original_now = mod.utc_now_dt
        mod.redis_cli = fake_redis
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
                return FakeProc("name\na9-worker\nconsumers\n1\nentries-read\n9\nlag\n1\n")
            if args == ["--raw", "XPENDING", "a9:tasks", "a9-worker"]:
                return FakeProc("0\n1740000001-0\n1740000010-0\n\n0\n")
            if args == ["--raw", "XINFO", "CONSUMERS", "a9:tasks", "a9-worker"]:
                return FakeProc("name\nworker-a\npending\n0\nidle\n12\n")
            raise AssertionError(f"unexpected redis args: {args}")

        original_redis = mod.redis_cli
        original_now = mod.utc_now_dt
        mod.redis_cli = fake_redis
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
        self.assertEqual(followup["evidence"]["tasks_stream"]["action"], "continue")

    def test_node_status_communication_followup_keeps_multiple_reconnect_node_evidence(self):
        mod = load_control_api()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis(args, *, timeout=2):
            if args == ["PING"]:
                return FakeProc("PONG\n")
            if args == ["XLEN", "a9:heartbeats"]:
                return FakeProc("2\n")
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
        original_now = mod.utc_now_dt
        mod.redis_cli = fake_redis
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
            try:
                mod.remote = lambda: FakeRemote
                mod.probe_node = lambda payload: original_probe_node(payload, root=root)
                mod.node_status = lambda: original_node_status(root)

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

        self.assertEqual(captured_post["status"], 200)
        self.assertEqual(captured_post["payload"]["status"], "ok")
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
            try:
                mod.remote = lambda: FakeRemote
                mod.probe_node = lambda payload: original_probe_node(payload, root=root)
                mod.node_status = lambda: original_node_status(root)

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

        self.assertEqual(captured_post["status"], 200)
        self.assertEqual(captured_post["payload"]["status"], "ok")
        self.assertEqual(captured_get["status"], 200)
        self.assertEqual(captured_get["payload"]["count"], 1)
        node = captured_get["payload"]["nodes"][0]
        self.assertEqual(node["last_probe_action"], "retry")
        self.assertEqual(node["last_probe_action_reason"], "ssh_exec_error")
        self.assertEqual(node["last_probe_required_missing"], [])
        self.assertEqual(node["last_probe_optional_missing"], ["tmux"])
        self.assertTrue(node["last_probe_checked_at"])

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
        self.assertIn("git@example.com:a9.git", result["repo"])
        self.assertIn("git clone", result["dry_run_script"])
        self.assertIn("CONTROLLER_URL=http://controller:8787", result["dry_run_script"])

    def test_bootstrap_dry_run_node_keeps_execution_disabled(self):
        mod = load_control_api()

        result = mod.bootstrap_dry_run_node({"ssh_target": "root@node1"})

        self.assertEqual(result["status"], "dry-run")
        self.assertFalse(result["execution_enabled"])
        self.assertIn("<dry_run_script>", result["command_preview"])
        self.assertIn("git clone", result["dry_run_script"])

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

            unknown = mod.command_gate("not.real", root=root)
            self.assertFalse(unknown["allowed"])
            self.assertEqual(unknown["reason"], "unknown_command")

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
        self.assertEqual(discovery["endpoints"]["register_node"], "/api/nodes/register")
        self.assertEqual(discovery["endpoints"]["gateway_transport_contract"], "/api/gateway/transport-contract")
        self.assertEqual(discovery["endpoints"]["gateway_reconnect_decision"], "/api/gateway/reconnect-decision")
        self.assertEqual(discovery["endpoints"]["gateway_reconnect_diagnostic"], "/api/gateway/reconnect-diagnostic")
        self.assertEqual(discovery["endpoints"]["gateway_health_refresh"], "/api/gateway/health-refresh")
        self.assertFalse(discovery["runtime"]["worker_claim_ready"])
        self.assertTrue(discovery["runtime"]["gateway_transport_contract"])
        self.assertEqual(discovery["events"]["max_limit"], 1000)
        self.assertIn("Last-Event-ID", discovery["events"]["sse_cursor_hint"])

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


if __name__ == "__main__":
    unittest.main()
