import importlib.util
import io
import contextlib
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location("a9_node_test", ROOT / "scripts" / "a9_node.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def load_control_api_module():
    spec = importlib.util.spec_from_file_location("a9_control_api_test", ROOT / "scripts" / "a9_control_api.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class NodeHelperTests(unittest.TestCase):
    def test_http_json_ignores_environment_proxy_for_local_controller(self):
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
            payload = mod.http_json("GET", f"http://127.0.0.1:{server.server_port}/health", timeout=2)
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

    def test_default_node_id_is_non_empty(self):
        mod = load_module()
        self.assertTrue(mod.default_node_id())

    def test_node_payload_contains_capability_keys(self):
        mod = load_module()
        payload = mod.node_payload("node-1", ssh_target="root@node-1")
        self.assertEqual(payload["node_id"], "node-1")
        self.assertEqual(payload["ssh_target"], "root@node-1")
        for key in ("git", "python3", "docker", "redis_cli", "systemctl", "codex"):
            self.assertIn(key, payload["capabilities"])

    def test_classify_connection_state_online(self):
        mod = load_module()
        result = mod.classify_node_connection_state(
            heartbeat_age_seconds=3,
            heartbeat_status="online",
        )
        self.assertEqual(result["state"], "online")
        self.assertEqual(result["action"], "continue")
        self.assertEqual(result["reason"], "heartbeat_fresh")
        self.assertEqual(result["evidence"]["reconnect_action"], "none")

    def test_classify_connection_state_stale(self):
        mod = load_module()
        result = mod.classify_node_connection_state(
            heartbeat_age_seconds=45,
            heartbeat_status="online",
            stale_after_seconds=30,
            offline_after_seconds=90,
        )
        self.assertEqual(result["state"], "stale")
        self.assertEqual(result["action"], "observe")
        self.assertEqual(result["reason"], "heartbeat_stale")

    def test_classify_connection_state_offline(self):
        mod = load_module()
        result = mod.classify_node_connection_state(
            heartbeat_age_seconds=200,
            heartbeat_status="online",
            stale_after_seconds=30,
            offline_after_seconds=90,
        )
        self.assertEqual(result["state"], "offline")
        self.assertEqual(result["action"], "escalate")
        self.assertEqual(result["reason"], "heartbeat_timeout")

    def test_classify_connection_state_offline_overrides_degraded_report(self):
        mod = load_module()
        result = mod.classify_node_connection_state(
            heartbeat_age_seconds=200,
            heartbeat_status="degraded",
            stale_after_seconds=30,
            offline_after_seconds=90,
        )
        self.assertEqual(result["state"], "offline")
        self.assertEqual(result["action"], "escalate")
        self.assertEqual(result["reason"], "heartbeat_timeout")

    def test_classify_connection_state_reconnecting_from_decision(self):
        mod = load_module()
        result = mod.classify_node_connection_state(
            heartbeat_age_seconds=12,
            heartbeat_status="online",
            reconnect_decision={"phase": "connect", "action": "reconnect", "error_class": "timeout"},
        )
        self.assertEqual(result["state"], "reconnecting")
        self.assertEqual(result["action"], "retry")
        self.assertEqual(result["reason"], "reconnect_requested")
        self.assertEqual(result["evidence"]["reconnect_phase"], "connect")

    def test_classify_connection_state_degraded_from_stream_continue(self):
        mod = load_module()
        result = mod.classify_node_connection_state(
            heartbeat_age_seconds=5,
            heartbeat_status="online",
            reconnect_decision={"phase": "stream", "action": "continue", "error_class": "decode_error"},
        )
        self.assertEqual(result["state"], "degraded")
        self.assertEqual(result["action"], "observe")
        self.assertEqual(result["reason"], "stream_error_continue")

    def test_classify_connection_state_degraded_from_terminated_reconnect(self):
        mod = load_module()
        result = mod.classify_node_connection_state(
            heartbeat_age_seconds=8,
            heartbeat_status="online",
            reconnect_decision={"phase": "connect", "action": "terminate", "policy_budget_remaining": 0},
        )
        self.assertEqual(result["state"], "degraded")
        self.assertEqual(result["action"], "quarantine")
        self.assertEqual(result["reason"], "reconnect_terminated")

    def test_parse_xreadgroup_output_supports_json_and_raw(self):
        mod = load_module()
        json_payload = json.dumps(
            [
                ["1740000200-0", ["command_id", "cmd-001", "action", "restart"]],
                ["1740000201-0", {"command_id": "cmd-002", "action": "reboot"}],
            ]
        )
        self.assertEqual(
            mod.parse_xreadgroup_output(json_payload),
            [
                {"id": "1740000200-0", "fields": {"command_id": "cmd-001", "action": "restart"}},
                {"id": "1740000201-0", "fields": {"command_id": "cmd-002", "action": "reboot"}},
            ],
        )
        self.assertEqual(
            mod.parse_xreadgroup_output(
                "\n".join(
                    [
                        "1740000202-0",
                        "command_id",
                        "cmd-003",
                        "action",
                        "status",
                        "1740000203-0",
                        "command_id",
                        "cmd-004",
                    ]
                )
            ),
            [
                {
                    "id": "1740000202-0",
                    "fields": {"command_id": "cmd-003", "action": "status"},
                },
                {"id": "1740000203-0", "fields": {"command_id": "cmd-004"}},
            ],
        )

    def test_parse_xautoclaim_output_supports_json_and_raw(self):
        mod = load_module()
        json_payload = json.dumps(
            [
                "1740000209-0",
                [["1740000200-0", ["command_id", "cmd-001", "action", "status"]]],
                ["1740000199-0"],
            ]
        )
        self.assertEqual(
            mod.parse_xautoclaim_output(json_payload),
            {
                "next_start_id": "1740000209-0",
                "events": [{"id": "1740000200-0", "fields": {"command_id": "cmd-001", "action": "status"}}],
                "deleted_ids": ["1740000199-0"],
            },
        )
        self.assertEqual(
            mod.parse_xautoclaim_output(
                "\n".join(
                    [
                        "1740000210-0",
                        "1740000201-0",
                        "command_id",
                        "cmd-002",
                        "action",
                        "status",
                    ]
                )
            ),
            {
                "next_start_id": "1740000210-0",
                "events": [{"id": "1740000201-0", "fields": {"command_id": "cmd-002", "action": "status"}}],
                "deleted_ids": [],
            },
        )

    def test_parse_node_command_result_event_parses_dict_with_json_result(self):
        mod = load_module()
        parsed = mod.parse_node_command_result_event(
            "1740000300-0",
            {
                "kind": "node_command_result",
                "node_id": "node-01",
                "claimed_id": "1740000200-0",
                "command_id": "cmd-status-01",
                "command_action": "status",
                "result_status": "ok",
                "error_code": "ok",
                "event_stream": "a9:events",
                "result": json.dumps(
                    {
                        "status": "ok",
                        "command_id": "cmd-status-01",
                        "command_action": "status",
                        "node_id": "node-01",
                    }
                ),
            },
        )
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["action"], "parse_result_event")
        self.assertEqual(parsed["event_id"], "1740000300-0")
        self.assertEqual(parsed["event_stream"], "a9:events")
        self.assertEqual(parsed["kind"], "node_command_result")
        self.assertEqual(parsed["node_id"], "node-01")
        self.assertEqual(parsed["command_id"], "cmd-status-01")
        self.assertEqual(parsed["error_code"], "ok")
        self.assertEqual(parsed["result"]["status"], "ok")

    def test_parse_node_command_result_event_defaults_error_code_to_ok(self):
        mod = load_module()
        parsed = mod.parse_node_command_result_event(
            "1740000300-0",
            {"kind": "node_command_result", "result": "{}"},
        )
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["error_code"], "ok")

    def test_parse_node_command_result_event_parses_list_fields(self):
        mod = load_module()
        parsed = mod.parse_node_command_result_event(
            "1740000301-0",
            [
                "kind",
                "node_command_result",
                "node_id",
                "node-01",
                "claimed_id",
                "1740000201-0",
                "command_id",
                "cmd-unsupported",
                "command_action",
                "reboot",
                "result_status",
                "unsupported",
                "error_code",
                "unsupported_command",
                "event_stream",
                "a9:events",
                "result",
                json.dumps({"status": "unsupported"}),
            ],
        )
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["action"], "parse_result_event")
        self.assertEqual(parsed["command_action"], "reboot")
        self.assertEqual(parsed["result_status"], "unsupported")
        self.assertEqual(parsed["error_code"], "unsupported_command")
        self.assertEqual(parsed["result"]["status"], "unsupported")

    def test_parse_node_command_result_event_degraded_on_invalid_result_json(self):
        mod = load_module()
        parsed = mod.parse_node_command_result_event("1740000302-0", {"kind": "node_command_result", "result": "{invalid-json"})
        self.assertEqual(parsed["status"], "degraded")
        self.assertEqual(parsed["action"], "parse_result_event")
        self.assertEqual(parsed["reason"], "result_json_decode_error")

    def test_node_command_claim_once_returns_noop_when_empty(self):
        mod = load_module()
        calls: list[list[str]] = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            calls.append(args)
            if args[:2] == ["XGROUP", "CREATE"]:
                return FakeProc("OK")
            if args[:2] == ["--raw", "XREADGROUP"]:
                return FakeProc("(nil)")
            raise AssertionError(f"unexpected args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            result = mod.node_command_claim_once(
                "node-01",
                count=2,
                block_ms=100,
                group="a9-worker",
                stream="a9:tasks",
                ack=False,
                timeout=3,
            )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "noop")
        self.assertEqual(result["command_count"], 0)
        self.assertEqual(result["events"], [])
        self.assertEqual(calls[0], ["XGROUP", "CREATE", "a9:tasks", "a9-worker", "0-0", "MKSTREAM"])
        self.assertEqual(calls[1][:2], ["--raw", "XREADGROUP"])

    def test_node_command_claim_once_returns_ok_with_events_and_no_ack(self):
        mod = load_module()
        calls: list[list[str]] = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            calls.append(args)
            if args[:2] == ["XGROUP", "CREATE"]:
                return FakeProc("OK")
            if args[:2] == ["--raw", "XREADGROUP"]:
                return FakeProc(
                    "\n".join(
                        [
                            "1740000200-0",
                            "command_id",
                            "cmd-001",
                            "action",
                            "restart",
                            "1740000201-0",
                            "command_id",
                            "cmd-002",
                            "action",
                            "reboot",
                        ]
                    )
                )
            raise AssertionError(f"unexpected args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            result = mod.node_command_claim_once(
                "node-01",
                count=2,
                block_ms=100,
                group="a9-worker",
                stream="a9:tasks",
                ack=False,
                timeout=3,
            )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["command_count"], 2)
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(result["events"][0]["id"], "1740000200-0")
        self.assertEqual(result["events"][1]["fields"]["action"], "reboot")
        self.assertEqual(result["acked_ids"], [])
        self.assertNotIn(["XACK", "a9:tasks", "a9-worker", "1740000200-0", "1740000201-0"], calls)

    def test_node_command_claim_once_ack_true_calls_xack(self):
        mod = load_module()
        calls: list[list[str]] = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            calls.append(args)
            if args[:2] == ["XGROUP", "CREATE"]:
                return FakeProc("OK")
            if args[:2] == ["--raw", "XREADGROUP"]:
                return FakeProc(
                    "\n".join(
                        [
                            "1740000200-0",
                            "command_id",
                            "cmd-001",
                            "1740000201-0",
                            "command_id",
                            "cmd-002",
                        ]
                    )
                )
            if args[:1] == ["XACK"]:
                return FakeProc("2")
            raise AssertionError(f"unexpected args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            result = mod.node_command_claim_once(
                "node-01",
                count=2,
                block_ms=100,
                group="a9-worker",
                stream="a9:tasks",
                ack=True,
                timeout=3,
            )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["command_count"], 2)
        self.assertEqual(result["acked_ids"], ["1740000200-0", "1740000201-0"])
        self.assertEqual(calls[2], ["XACK", "a9:tasks", "a9-worker", "1740000200-0", "1740000201-0"])

    def test_node_command_claim_once_degraded_on_redis_unavailable(self):
        mod = load_module()

        original_redis = mod.redis_cli
        mod.redis_cli = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("redis unavailable"))
        try:
            result = mod.node_command_claim_once("node-01", timeout=3)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error_code"], "redis_unavailable")

    def test_node_command_claim_stale_once_uses_xautoclaim(self):
        mod = load_module()
        calls: list[list[str]] = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            calls.append(args)
            if args[:2] == ["XGROUP", "CREATE"]:
                return FakeProc("BUSYGROUP Consumer Group name already exists", 1)
            if args[:2] == ["--raw", "XAUTOCLAIM"]:
                return FakeProc(
                    "\n".join(
                        [
                            "1740000209-0",
                            "1740000200-0",
                            "command_id",
                            "cmd-stale-01",
                            "action",
                            "status",
                        ]
                    )
                )
            raise AssertionError(f"unexpected args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            result = mod.node_command_claim_stale_once(
                "node-01",
                count=1,
                min_idle_ms=2500,
                group="a9-worker",
                stream="a9:tasks",
                timeout=3,
            )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "claim_stale_once")
        self.assertEqual(result["command_count"], 1)
        self.assertEqual(result["events"][0]["id"], "1740000200-0")
        self.assertEqual(result["events"][0]["fields"]["command_id"], "cmd-stale-01")
        self.assertEqual(result["next_start_id"], "1740000209-0")
        self.assertEqual(
            calls[1],
            [
                "--raw",
                "XAUTOCLAIM",
                "a9:tasks",
                "a9-worker",
                "node-01-consumer",
                "2500",
                "0-0",
                "COUNT",
                "1",
            ],
        )

    def test_command_claim_once_cli_prints_payload(self):
        mod = load_module()
        captured = io.StringIO()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            if args[:2] == ["XGROUP", "CREATE"]:
                return FakeProc("OK")
            if args[:2] == ["--raw", "XREADGROUP"]:
                return FakeProc("(nil)")
            if args[:1] == ["XACK"]:
                return FakeProc("0")
            return FakeProc()

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            with contextlib.redirect_stdout(captured):
                status = mod.main(
                    [
                        "--node-id",
                        "node-cli-01",
                        "command-claim-once",
                        "--count",
                        "1",
                        "--block-ms",
                        "200",
                        "--group",
                        "workers",
                        "--stream",
                        "a9:test-tasks",
                        "--ack",
                    ]
                )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status, 0)
        payload = json.loads(captured.getvalue())
        self.assertEqual(payload["status"], "noop")
        self.assertEqual(payload["stream"], "a9:test-tasks")
        self.assertEqual(payload["group"], "workers")
        self.assertEqual(payload["node_id"], "node-cli-01")

    def test_node_command_ack_once_returns_ok_when_xack_acknowledges(self):
        mod = load_module()
        calls: list[list[str]] = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            calls.append(args)
            if args[:1] == ["XACK"]:
                return FakeProc("1")
            raise AssertionError(f"unexpected args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            result = mod.node_command_ack_once(
                "node-01",
                "1740000200-0",
                group="a9-worker",
                stream="a9:tasks",
                timeout=3,
            )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["error_code"], "ok")
        self.assertEqual(result["action"], "ack_once")
        self.assertEqual(result["acked_count"], 1)
        self.assertEqual(result["acked_ids"], ["1740000200-0"])
        self.assertEqual(calls, [["XACK", "a9:tasks", "a9-worker", "1740000200-0"]])

    def test_node_command_ack_once_returns_noop_when_not_pending(self):
        mod = load_module()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        original_redis = mod.redis_cli
        mod.redis_cli = lambda args, *, timeout=2: FakeProc("0")
        try:
            result = mod.node_command_ack_once("node-01", "1740000200-0")
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "noop")
        self.assertEqual(result["error_code"], "not_pending_or_already_acked")
        self.assertEqual(result["acked_count"], 0)
        self.assertEqual(result["reason"], "not_pending_or_already_acked")

    def test_node_command_ack_once_rejects_invalid_stream_id_without_redis(self):
        mod = load_module()
        calls: list[list[str]] = []

        original_redis = mod.redis_cli
        mod.redis_cli = lambda args, *, timeout=2: calls.append(args)
        try:
            result = mod.node_command_ack_once("node-01", "bad-id")
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error_code"], "invalid_payload")
        self.assertEqual(result["reason"], "command_stream_id_must_be_redis_stream_id")
        self.assertEqual(calls, [])

    def test_node_command_ack_once_degraded_on_redis_unavailable(self):
        mod = load_module()

        original_redis = mod.redis_cli
        mod.redis_cli = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("redis unavailable"))
        try:
            result = mod.node_command_ack_once("node-01", "1740000200-0")
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error_code"], "redis_unavailable")
        self.assertIn("redis unavailable", result["reason"])

    def test_command_ack_once_cli_prints_payload(self):
        mod = load_module()
        captured = io.StringIO()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        original_redis = mod.redis_cli
        mod.redis_cli = lambda args, *, timeout=2: FakeProc("1")
        try:
            with contextlib.redirect_stdout(captured):
                status = mod.main(
                    [
                        "--node-id",
                        "node-cli-01",
                        "command-ack-once",
                        "1740000200-0",
                        "--group",
                        "workers",
                        "--stream",
                        "a9:test-tasks",
                    ]
                )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status, 0)
        payload = json.loads(captured.getvalue())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["action"], "ack_once")
        self.assertEqual(payload["stream"], "a9:test-tasks")
        self.assertEqual(payload["group"], "workers")
        self.assertEqual(payload["node_id"], "node-cli-01")
        self.assertEqual(payload["command_stream_id"], "1740000200-0")

    def test_node_command_result_read_once_rejects_invalid_event_id(self):
        mod = load_module()
        calls: list[list[str]] = []
        original_redis = mod.redis_cli
        mod.redis_cli = lambda args, *, timeout=2: calls.append(args)
        try:
            result = mod.node_command_result_read_once("bad-event-id")
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error_code"], "invalid_payload")
        self.assertEqual(result["action"], "result_read_once")
        self.assertEqual(result["reason"], "result_event_id_must_be_redis_stream_id")
        self.assertEqual(calls, [])

    def test_node_command_result_read_once_returns_noop_when_event_missing(self):
        mod = load_module()
        calls: list[list[str]] = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            calls.append(args)
            if args[:5] == ["--raw", "XRANGE", "a9:events", "1740000300-0", "1740000300-0"]:
                return FakeProc("(nil)")
            raise AssertionError(f"unexpected args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            result = mod.node_command_result_read_once("1740000300-0")
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "noop")
        self.assertEqual(result["error_code"], "no_events")
        self.assertEqual(result["action"], "result_read_once")
        self.assertEqual(result["event_id"], "1740000300-0")
        self.assertEqual(result["event_stream"], "a9:events")
        self.assertEqual(calls, [["--raw", "XRANGE", "a9:events", "1740000300-0", "1740000300-0"]])

    def test_node_command_result_read_once_reads_and_parses_event(self):
        mod = load_module()
        calls: list[list[str]] = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            calls.append(args)
            if args[:5] == ["--raw", "XRANGE", "a9:events", "1740000300-0", "1740000300-0"]:
                return FakeProc(
                    "\n".join(
                        [
                            "1740000300-0",
                            "kind",
                            "node_command_result",
                            "node_id",
                            "node-01",
                            "claimed_id",
                            "1740000200-0",
                            "command_id",
                            "cmd-status-01",
                            "command_action",
                            "status",
                            "result_status",
                            "ok",
                            "error_code",
                            "ok",
                            "event_stream",
                            "a9:events",
                            "result",
                            json.dumps({"status": "ok", "command_id": "cmd-status-01"}),
                        ]
                    )
                )
            raise AssertionError(f"unexpected args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            result = mod.node_command_result_read_once("1740000300-0")
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["error_code"], "ok")
        self.assertEqual(result["action"], "result_read_once")
        self.assertEqual(result["command_id"], "cmd-status-01")
        self.assertEqual(result["result_status"], "ok")
        self.assertEqual(result["raw_fields"]["kind"], "node_command_result")
        self.assertEqual(result["event_stream"], "a9:events")
        self.assertEqual(result["event_id"], "1740000300-0")
        self.assertEqual(result["result"]["command_id"], "cmd-status-01")
        self.assertEqual(calls, [["--raw", "XRANGE", "a9:events", "1740000300-0", "1740000300-0"]])

    def test_node_command_result_read_once_degraded_on_redis_unavailable(self):
        mod = load_module()
        original_redis = mod.redis_cli
        mod.redis_cli = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("redis unavailable"))
        try:
            result = mod.node_command_result_read_once("1740000300-0")
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error_code"], "redis_unavailable")
        self.assertIn("redis unavailable", result["reason"])

    def test_node_command_work_once_supported_status_executes_and_acks(self):
        mod = load_module()
        calls: list[list[str]] = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            calls.append(args)
            if args[:2] == ["XGROUP", "CREATE"]:
                return FakeProc("OK")
            if args[:2] == ["--raw", "XREADGROUP"]:
                return FakeProc(
                    "\n".join(
                        [
                            "1740000200-0",
                            "command_id",
                            "cmd-status-01",
                            "action",
                            "status",
                        ]
                    )
                )
            if args[:1] == ["XADD"]:
                return FakeProc("1740000300-0")
            if args[:1] == ["XACK"]:
                return FakeProc("1")
            raise AssertionError(f"unexpected args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            result = mod.node_command_work_once("node-01", stream="a9:tasks", event_stream="a9:events", block_ms=100, timeout=3)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["error_code"], "ok")
        self.assertEqual(result["claimed_id"], "1740000200-0")
        self.assertEqual(result["command_id"], "cmd-status-01")
        self.assertEqual(result["command_action"], "status")
        self.assertEqual(result["result_event_id"], "1740000300-0")
        self.assertEqual(result["acked_ids"], ["1740000200-0"])
        self.assertEqual(calls[0], ["XGROUP", "CREATE", "a9:tasks", "a9-worker", "0-0", "MKSTREAM"])
        self.assertEqual(calls[1], ["--raw", "XREADGROUP", "GROUP", "a9-worker", "node-01-consumer", "COUNT", "1", "BLOCK", "100", "STREAMS", "a9:tasks", ">"])
        self.assertEqual(
            calls[2],
            [
                "XADD",
                "a9:events",
                "*",
                "kind",
                "node_command_result",
                "action",
                "work_once",
                "node_id",
                "node-01",
                "claimed_id",
                "1740000200-0",
                "command_id",
                "cmd-status-01",
                "command_action",
                "status",
                "result_status",
                "ok",
                "error_code",
                "ok",
                "event_stream",
                "a9:events",
                "result",
                '{"status":"ok","command_id":"cmd-status-01","command_action":"status","node_id":"node-01","result":"status_ok"}',
            ],
        )
        self.assertEqual(calls[3], ["XACK", "a9:tasks", "a9-worker", "1740000200-0"])

    def test_node_command_work_once_unsupported_action_writes_result_and_acks(self):
        mod = load_module()
        calls: list[list[str]] = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            calls.append(args)
            if args[:2] == ["XGROUP", "CREATE"]:
                return FakeProc("OK")
            if args[:2] == ["--raw", "XREADGROUP"]:
                return FakeProc(
                    "\n".join(
                        [
                            "1740000200-0",
                            "command_id",
                            "cmd-unsupported",
                            "action",
                            "reboot",
                        ]
                    )
                )
            if args[:1] == ["XADD"]:
                return FakeProc("1740000300-1")
            if args[:1] == ["XACK"]:
                return FakeProc("1")
            raise AssertionError(f"unexpected args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            result = mod.node_command_work_once("node-01", stream="a9:tasks", event_stream="a9:events", block_ms=100, timeout=3)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["error_code"], "unsupported_command")
        self.assertEqual(result["command_action"], "reboot")
        self.assertEqual(result["command_id"], "cmd-unsupported")
        self.assertEqual(result["acked_ids"], ["1740000200-0"])
        self.assertEqual(result["result_event_id"], "1740000300-1")
        self.assertEqual(result["raw_output"]["xadd"], "1740000300-1")
        self.assertEqual(calls[2][0], "XADD")
        self.assertEqual(calls[3], ["XACK", "a9:tasks", "a9-worker", "1740000200-0"])

    def test_node_command_work_once_noop_when_no_events(self):
        mod = load_module()
        calls: list[list[str]] = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            calls.append(args)
            if args[:2] == ["XGROUP", "CREATE"]:
                return FakeProc("OK")
            if args[:2] == ["--raw", "XREADGROUP"]:
                return FakeProc("(nil)")
            raise AssertionError(f"unexpected args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            result = mod.node_command_work_once("node-01", block_ms=100, timeout=3)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "noop")
        self.assertEqual(result["error_code"], "no_events")
        self.assertEqual(result["command_id"], "")
        self.assertEqual(result["result_event_id"], "")
        self.assertEqual(len(calls), 2)

    def test_node_command_work_once_recovers_pending_when_no_new_events(self):
        mod = load_module()
        calls: list[list[str]] = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            calls.append(args)
            if args[:2] == ["XGROUP", "CREATE"]:
                return FakeProc("BUSYGROUP Consumer Group name already exists", 1)
            if args[:2] == ["--raw", "XREADGROUP"]:
                return FakeProc("(nil)")
            if args[:2] == ["--raw", "XAUTOCLAIM"]:
                return FakeProc(
                    "\n".join(
                        [
                            "1740000209-0",
                            "1740000200-0",
                            "command_id",
                            "cmd-stale-status",
                            "action",
                            "status",
                        ]
                    )
                )
            if args[:1] == ["XADD"]:
                return FakeProc("1740000300-2")
            if args[:1] == ["XACK"]:
                return FakeProc("1")
            raise AssertionError(f"unexpected args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            result = mod.node_command_work_once(
                "node-01",
                stream="a9:tasks",
                event_stream="a9:events",
                block_ms=100,
                timeout=3,
                recover_pending=True,
                min_idle_ms=2500,
            )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["error_code"], "ok")
        self.assertEqual(result["claim_source"], "pending")
        self.assertTrue(result["recovered_pending"])
        self.assertEqual(result["command_id"], "cmd-stale-status")
        self.assertEqual(result["acked_ids"], ["1740000200-0"])
        self.assertEqual(calls[2][:2], ["XGROUP", "CREATE"])
        self.assertEqual(calls[3][:2], ["--raw", "XAUTOCLAIM"])
        self.assertEqual(calls[-1], ["XACK", "a9:tasks", "a9-worker", "1740000200-0"])

    def test_node_command_work_once_degraded_on_xadd_failure(self):
        mod = load_module()
        calls: list[list[str]] = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            calls.append(args)
            if args[:2] == ["XGROUP", "CREATE"]:
                return FakeProc("OK")
            if args[:2] == ["--raw", "XREADGROUP"]:
                return FakeProc(
                    "\n".join(
                        [
                            "1740000200-0",
                            "command_id",
                            "cmd-status-01",
                            "action",
                            "status",
                        ]
                    )
                )
            if args[:1] == ["XADD"]:
                return FakeProc("ERR command", 1)
            if args[:1] == ["XACK"]:
                return FakeProc("1")
            raise AssertionError(f"unexpected args: {args}")

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            result = mod.node_command_work_once("node-01", block_ms=100, timeout=3)
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error_code"], "xadd_failed")
        self.assertEqual(result["acked_ids"], [])
        self.assertEqual(result["result_event_id"], "")
        self.assertEqual(calls[-1][0], "XADD")
        self.assertEqual(calls[-1][1], "a9:events")

    def test_node_command_lifecycle_submit_worker_result_by_command_lookup(self):
        node_mod = load_module()
        control_mod = load_control_api_module()
        enqueue_calls: list[list[str]] = []
        work_calls: list[list[str]] = []
        by_command_calls: list[list[str]] = []

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        original_control_redis = control_mod.redis_cli
        try:
            def fake_control_redis_enqueue(args, *, timeout=2):
                enqueue_calls.append(args)
                if args == ["PING"]:
                    return FakeProc("PONG")
                if args[:2] == ["XADD", "a9:tasks"]:
                    return FakeProc("1740000200-0")
                raise AssertionError(f"unexpected enqueue args: {args}")

            control_mod.redis_cli = fake_control_redis_enqueue
            enqueue_result = control_mod.enqueue_node_command(
                {
                    "command_id": "cmd-lifecycle-01",
                    "node_id": "node-01",
                    "action": "status",
                    "action_reason": "operator_action",
                    "target": "node-01",
                    "expected_revision": 4,
                    "ttl_seconds": 60,
                    "created_at": "2026-06-01T00:00:00+00:00",
                }
            )
        finally:
            control_mod.redis_cli = original_control_redis

        self.assertEqual(enqueue_result["status"], "ok")
        enqueue_xadd = next(call for call in enqueue_calls if call[:2] == ["XADD", "a9:tasks"])
        command_fields = dict(zip(enqueue_xadd[3::2], enqueue_xadd[4::2]))
        self.assertEqual(command_fields["command_id"], "cmd-lifecycle-01")
        self.assertEqual(command_fields["node_id"], "node-01")
        self.assertEqual(command_fields["action"], "status")

        original_node_redis = node_mod.redis_cli
        try:
            def fake_node_redis_work(args, *, timeout=2):
                work_calls.append(args)
                if args[:2] == ["XGROUP", "CREATE"]:
                    return FakeProc("OK")
                if args[:2] == ["--raw", "XREADGROUP"]:
                    return FakeProc(
                        "\n".join(
                            [
                                "1740000200-0",
                                "command_id",
                                "cmd-lifecycle-01",
                                "node_id",
                                "node-01",
                                "action",
                                "status",
                            ]
                        )
                    )
                if args[:2] == ["XADD", "a9:events"]:
                    return FakeProc("1740000300-0")
                if args[:1] == ["XACK"]:
                    return FakeProc("1")
                raise AssertionError(f"unexpected work args: {args}")

            node_mod.redis_cli = fake_node_redis_work
            work_result = node_mod.node_command_work_once(
                "node-01",
                stream="a9:tasks",
                event_stream="a9:events",
                block_ms=100,
                timeout=3,
            )
        finally:
            node_mod.redis_cli = original_node_redis

        self.assertEqual(work_result["status"], "ok")
        self.assertEqual(work_result["command_id"], "cmd-lifecycle-01")
        self.assertEqual(work_result["result_event_id"], "1740000300-0")
        self.assertEqual(work_result["acked_ids"], ["1740000200-0"])
        self.assertEqual(work_calls[-1], ["XACK", "a9:tasks", "a9-worker", "1740000200-0"])

        worker_xadd = next(call for call in work_calls if call[:2] == ["XADD", "a9:events"])
        worker_fields = dict(zip(worker_xadd[3::2], worker_xadd[4::2]))
        self.assertEqual(worker_fields["kind"], "node_command_result")
        self.assertEqual(worker_fields["command_id"], "cmd-lifecycle-01")
        self.assertEqual(worker_fields["node_id"], "node-01")
        self.assertEqual(worker_fields["error_code"], "ok")
        self.assertEqual(json.loads(worker_fields["result"])["status"], "ok")

        original_control_redis = control_mod.redis_cli
        original_control_node_loader = control_mod.a9_node
        original_node_redis = node_mod.redis_cli
        try:
            def fake_control_redis_lookup(args, *, timeout=2):
                by_command_calls.append(args)
                if args[:2] == ["--raw", "XREVRANGE"]:
                    return FakeProc(
                        "\n".join(
                            [
                                "1740000300-0",
                                "kind",
                                "node_command_result",
                                "command_id",
                                "cmd-lifecycle-01",
                            ]
                        )
                    )
                raise AssertionError(f"unexpected lookup args: {args}")

            def fake_node_redis_read(args, *, timeout=2):
                if args[:3] == ["--raw", "XRANGE", "a9:events"]:
                    return FakeProc(
                        "\n".join(
                            [
                                "1740000300-0",
                                "kind",
                                "node_command_result",
                                "action",
                                "work_once",
                                "node_id",
                                "node-01",
                                "claimed_id",
                                "1740000200-0",
                                "command_id",
                                "cmd-lifecycle-01",
                                "command_action",
                                "status",
                                "result_status",
                                "ok",
                                "error_code",
                                "ok",
                                "event_stream",
                                "a9:events",
                                "result",
                                worker_fields["result"],
                            ]
                        )
                    )
                raise AssertionError(f"unexpected read args: {args}")

            control_mod.redis_cli = fake_control_redis_lookup
            control_mod.a9_node = lambda: node_mod
            node_mod.redis_cli = fake_node_redis_read
            by_command_result = control_mod.node_command_result_by_command_lookup(
                "cmd-lifecycle-01",
                event_stream="a9:events",
                limit=5,
                timeout=3,
            )
        finally:
            control_mod.redis_cli = original_control_redis
            control_mod.a9_node = original_control_node_loader
            node_mod.redis_cli = original_node_redis

        self.assertEqual(by_command_result["status"], "ok")
        self.assertEqual(by_command_result["result_event_id"], "1740000300-0")
        self.assertEqual(by_command_result["result"]["result"]["status"], "ok")
        self.assertEqual(
            by_command_result["result"]["result"]["result"]["command_id"],
            "cmd-lifecycle-01",
        )
        self.assertEqual(
            by_command_calls,
            [["--raw", "XREVRANGE", "a9:events", "+", "-", "COUNT", "5"]],
        )

    def test_command_work_once_cli_prints_payload(self):
        mod = load_module()
        captured = io.StringIO()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            if args[:2] == ["XGROUP", "CREATE"]:
                return FakeProc("OK")
            if args[:2] == ["--raw", "XREADGROUP"]:
                return FakeProc("(nil)")
            if args[:1] == ["XADD"]:
                return FakeProc("1740000300-0")
            if args[:1] == ["XACK"]:
                return FakeProc("1")
            return FakeProc()

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            with contextlib.redirect_stdout(captured):
                status = mod.main(
                    [
                        "--node-id",
                        "node-cli-02",
                        "command-work-once",
                        "--group",
                        "workers",
                        "--stream",
                        "a9:test-tasks",
                        "--event-stream",
                        "a9:test-events",
                        "--block-ms",
                        "200",
                    ]
                )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status, 0)
        payload = json.loads(captured.getvalue())
        self.assertEqual(payload["status"], "noop")
        self.assertEqual(payload["action"], "work_once")
        self.assertEqual(payload["stream"], "a9:test-tasks")
        self.assertEqual(payload["event_stream"], "a9:test-events")
        self.assertEqual(payload["node_id"], "node-cli-02")
        self.assertEqual(payload["error_code"], "no_events")

    def test_node_command_work_loop_runs_bounded_iterations(self):
        mod = load_module()
        calls = []
        results = [
            {"status": "noop", "error_code": "no_events"},
            {"status": "ok", "error_code": "ok", "command_id": "cmd-1"},
        ]

        def fake_work_once(node_id, **kwargs):
            calls.append({"node_id": node_id, **kwargs})
            return results[len(calls) - 1]

        emitted = []
        original_work_once = mod.node_command_work_once
        original_sleep = mod.time.sleep
        mod.node_command_work_once = fake_work_once
        mod.time.sleep = lambda seconds: emitted.append({"sleep": seconds})
        try:
            summary = mod.node_command_work_loop(
                "node-loop",
                stream="a9:test-tasks",
                event_stream="a9:test-events",
                block_ms=25,
                timeout=2,
                sleep_seconds=0.5,
                max_iterations=2,
                emit=emitted.append,
            )
        finally:
            mod.node_command_work_once = original_work_once
            mod.time.sleep = original_sleep

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["iterations"], 2)
        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["noop"], 1)
        self.assertEqual(summary["degraded"], 0)
        self.assertEqual(summary["timeout"], 2)
        self.assertEqual(summary["last_result"]["command_id"], "cmd-1")
        self.assertEqual(calls[0]["stream"], "a9:test-tasks")
        self.assertEqual(calls[0]["event_stream"], "a9:test-events")
        self.assertTrue(calls[0]["recover_pending"])
        self.assertEqual(calls[0]["min_idle_ms"], 30000)
        self.assertEqual(emitted[0]["status"], "noop")
        self.assertEqual(emitted[1], {"sleep": 0.5})
        self.assertEqual(emitted[2]["status"], "ok")

    def test_command_work_loop_cli_prints_json_lines(self):
        mod = load_module()
        captured = io.StringIO()

        def fake_work_once(node_id, **kwargs):
            return {"status": "noop", "error_code": "no_events", "node_id": node_id}

        original_work_once = mod.node_command_work_once
        original_sleep = mod.time.sleep
        mod.node_command_work_once = fake_work_once
        mod.time.sleep = lambda seconds: None
        try:
            with contextlib.redirect_stdout(captured):
                status = mod.main(
                    [
                        "--node-id",
                        "node-cli-loop",
                        "command-work-loop",
                        "--max-iterations",
                        "1",
                        "--sleep-seconds",
                        "0",
                    ]
                )
        finally:
            mod.node_command_work_once = original_work_once
            mod.time.sleep = original_sleep

        self.assertEqual(status, 0)
        lines = [json.loads(line) for line in captured.getvalue().splitlines()]
        self.assertEqual(lines[0]["status"], "noop")
        self.assertEqual(lines[1]["action"], "work_loop")
        self.assertEqual(lines[1]["node_id"], "node-cli-loop")
        self.assertEqual(lines[1]["iterations"], 1)
        self.assertEqual(lines[1]["timeout"], 3)
        self.assertTrue(lines[1]["recover_pending"])
        self.assertEqual(lines[1]["min_idle_ms"], 30000)

    def test_node_command_work_loop_timeout_covers_block_ms(self):
        mod = load_module()
        calls = []
        original_work_once = mod.node_command_work_once
        original_sleep = mod.time.sleep
        mod.node_command_work_once = lambda node_id, **kwargs: calls.append(kwargs) or {"status": "noop", "error_code": "no_events"}
        mod.time.sleep = lambda seconds: None
        try:
            summary = mod.node_command_work_loop("node-loop", block_ms=5000, timeout=3, max_iterations=1)
        finally:
            mod.node_command_work_once = original_work_once
            mod.time.sleep = original_sleep

        self.assertEqual(calls[0]["timeout"], 7)
        self.assertTrue(calls[0]["recover_pending"])
        self.assertEqual(summary["timeout"], 7)

    def test_node_command_work_loop_can_disable_pending_recovery(self):
        mod = load_module()
        calls = []
        original_work_once = mod.node_command_work_once
        original_sleep = mod.time.sleep
        mod.node_command_work_once = lambda node_id, **kwargs: calls.append(kwargs) or {"status": "noop", "error_code": "no_events"}
        mod.time.sleep = lambda seconds: None
        try:
            summary = mod.node_command_work_loop(
                "node-loop",
                max_iterations=1,
                recover_pending=False,
                min_idle_ms=50,
            )
        finally:
            mod.node_command_work_once = original_work_once
            mod.time.sleep = original_sleep

        self.assertFalse(calls[0]["recover_pending"])
        self.assertEqual(calls[0]["min_idle_ms"], 50)
        self.assertFalse(summary["recover_pending"])
        self.assertEqual(summary["min_idle_ms"], 50)

    def test_node_command_result_read_once_cli_prints_payload(self):
        mod = load_module()
        captured = io.StringIO()

        class FakeProc:
            def __init__(self, stdout: str = "", returncode: int = 0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_redis_cli(args, *, timeout=2):
            if args[:5] == ["--raw", "XRANGE", "a9:test-events", "1740000300-0", "1740000300-0"]:
                return FakeProc(
                    "\n".join(
                        [
                            "1740000300-0",
                            "kind",
                            "node_command_result",
                            "node_id",
                            "node-cli-02",
                            "claimed_id",
                            "1740000200-0",
                            "command_id",
                            "cmd-status-01",
                            "command_action",
                            "status",
                            "result_status",
                            "ok",
                            "error_code",
                            "ok",
                            "event_stream",
                            "a9:test-events",
                            "result",
                            json.dumps({"status": "ok", "command_id": "cmd-status-01"}),
                        ]
                    )
                )
            return FakeProc()

        original_redis = mod.redis_cli
        mod.redis_cli = fake_redis_cli
        try:
            with contextlib.redirect_stdout(captured):
                status = mod.main(
                    [
                        "--node-id",
                        "node-cli-02",
                        "command-result-read-once",
                        "1740000300-0",
                        "--event-stream",
                        "a9:test-events",
                    ]
                )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(status, 0)
        payload = json.loads(captured.getvalue())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["action"], "result_read_once")
        self.assertEqual(payload["event_id"], "1740000300-0")
        self.assertEqual(payload["event_stream"], "a9:test-events")
        self.assertEqual(payload["command_id"], "cmd-status-01")
        self.assertEqual(payload["result_status"], "ok")
        self.assertEqual(payload["result"]["command_id"], "cmd-status-01")


if __name__ == "__main__":
    unittest.main()
