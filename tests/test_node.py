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


if __name__ == "__main__":
    unittest.main()
