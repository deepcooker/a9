import importlib.util
import io
import contextlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location("a9_node_test", ROOT / "scripts" / "a9_node.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class NodeHelperTests(unittest.TestCase):
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
        self.assertEqual(calls[2], ["XADD", "a9:events", "*", "kind", "node_command_result", "action", "work_once", "node_id", "node-01", "claimed_id", "1740000200-0", "command_id", "cmd-status-01", "command_action", "status", "result_status", "ok", "error_code", "ok", "result", '{"status":"ok","command_id":"cmd-status-01","command_action":"status","node_id":"node-01","result":"status_ok"}'])
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


if __name__ == "__main__":
    unittest.main()
