import importlib.util
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location("a9_remote_test", ROOT / "scripts" / "a9_remote.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class RemoteBootstrapTests(unittest.TestCase):
    def test_parse_probe_reads_key_values(self):
        mod = load_module()
        payload = mod.parse_probe("host=node1\npython3=/usr/bin/python3\nbad-line\n")
        self.assertEqual(payload["host"], "node1")
        self.assertEqual(payload["python3"], "/usr/bin/python3")
        self.assertNotIn("bad-line", payload)

    def test_bootstrap_script_contains_controller_repo_and_remote_dir(self):
        mod = load_module()
        args = Namespace(
            controller_url="http://controller:8787",
            repo="git@example.com:a9.git",
            remote_dir="~/a9-worker",
            worker_name="node-a",
        )
        script = mod.build_bootstrap_script(args)
        self.assertIn("CONTROLLER_URL=http://controller:8787", script)
        self.assertIn("REPO=git@example.com:a9.git", script)
        self.assertIn("REMOTE_DIR='~/a9-worker'", script)
        self.assertIn("WORKER_NAME=node-a", script)
        self.assertIn("git clone", script)

    def test_ssh_base_uses_batch_mode_and_identity(self):
        mod = load_module()
        cmd = mod.ssh_base("root@example", connect_timeout=7, identity_file="/tmp/key")
        self.assertEqual(cmd[0], "ssh")
        self.assertIn("BatchMode=yes", cmd)
        self.assertIn("ConnectTimeout=7", cmd)
        self.assertIn("/tmp/key", cmd)
        self.assertEqual(cmd[-1], "root@example")

    def test_ssh_base_parses_target_port(self):
        mod = load_module()
        cmd = mod.ssh_base("root@example:2200", connect_timeout=7, identity_file="/tmp/key")
        self.assertIn("-p", cmd)
        self.assertIn("2200", cmd)
        self.assertEqual(cmd[-1], "root@example")


if __name__ == "__main__":
    unittest.main()
