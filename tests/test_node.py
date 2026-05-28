import importlib.util
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
        self.assertEqual(result["action"], "continue")
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


if __name__ == "__main__":
    unittest.main()
