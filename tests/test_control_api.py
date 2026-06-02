#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import os
import json
import contextlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


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
        self.assertEqual(status["latest_run"]["task_id"], "task")
        self.assertEqual(status["progress"]["progress_percent"], 1)
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
            try:
                mod.a9_node = lambda: fake_node
                mod.redis_tasks_stream_probe = fake_probe
                result = mod.recover_stale_commands(
                    {
                        "node_id": "node-a",
                        "max_claim": 2,
                        "min_idle_ms": 45000,
                        "group": "a9-worker",
                        "stream": "a9:tasks",
                        "timeout": 5,
                    },
                    root=Path(tmp),
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
        self.assertEqual(captured["called_payload"]["run_id"], "run-eval")

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
                        "communication_plan_status": "ready",
                        "communication_action": "intervene",
                        "communication_priority_source": "recovery_loop",
                        "communication_route": {"endpoint": "/api/nodes/recovery-cycle"},
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
            mod.recovery_loop_latest = lambda: {"status": "ok", "kind": "recovery_loop_latest"}
            mod.ControlHandler.do_GET(DummyRecoveryLoopLatestGetHandler())
        finally:
            mod.recovery_loop_latest = original_latest

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["kind"], "recovery_loop_latest")

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
        self.assertEqual(discovery["endpoints"]["communication_action_plan"], "/api/communication/action-plan")
        self.assertEqual(discovery["endpoints"]["communication_repair_one"], "/api/communication/repair-one")
        self.assertEqual(discovery["endpoints"]["communication_repair_suggestions"], "/api/communication/repair-suggestions")
        self.assertEqual(discovery["endpoints"]["communication_repair_suggestion_review"], "/api/communication/repair-suggestions/review")
        self.assertEqual(discovery["endpoints"]["register_node"], "/api/nodes/register")
        self.assertEqual(discovery["endpoints"]["gateway_transport_contract"], "/api/gateway/transport-contract")
        self.assertEqual(discovery["endpoints"]["gateway_reconnect_decision"], "/api/gateway/reconnect-decision")
        self.assertEqual(discovery["endpoints"]["gateway_reconnect_diagnostic"], "/api/gateway/reconnect-diagnostic")
        self.assertEqual(discovery["endpoints"]["gateway_reconnect_governance"], "/api/gateway/reconnect-governance")
        self.assertEqual(discovery["endpoints"]["gateway_health_refresh"], "/api/gateway/health-refresh")
        self.assertEqual(discovery["endpoints"]["node_recovery_loop_latest"], "/api/nodes/recovery-loop/latest")
        self.assertEqual(discovery["endpoints"]["node_recovery_transcript"], "/api/nodes/recovery-transcript")
        self.assertEqual(discovery["endpoints"]["eval_override"], "/api/eval/override")
        self.assertEqual(discovery["endpoints"]["node_command_result"], "/api/node-command-results/{result_event_id}")
        self.assertEqual(
            discovery["endpoints"]["node_command_result_by_command"],
            "/api/node-command-results/by-command/{command_id}",
        )
        self.assertFalse(discovery["runtime"]["worker_claim_ready"])
        self.assertTrue(discovery["runtime"]["gateway_transport_contract"])
        self.assertTrue(discovery["runtime"]["gateway_reconnect_governance"])
        self.assertTrue(discovery["runtime"]["node_command_recovery_hint_contract"])
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
