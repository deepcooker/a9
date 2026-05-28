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
        self.assertIn(".a9/remote-node/heartbeat.sh", script)
        self.assertIn("chmod +x .a9/remote-node/heartbeat.sh", script)
        self.assertIn("api/nodes/heartbeat", script)
        self.assertIn("A9_HEARTBEAT_ONCE", script)

    def test_heartbeat_loop_script_contains_heartbeat_payload_fields(self):
        mod = load_module()
        args = Namespace(
            controller_url="http://controller:8787",
            worker_name="node-a",
            repo="git@example.com:a9.git",
            remote_dir="~/a9-worker",
        )
        heartbeat_script = mod.heartbeat_loop_script(args)
        self.assertIn("#!/bin/sh", heartbeat_script)
        self.assertIn("CONTROLLER_URL=http://controller:8787", heartbeat_script)
        self.assertIn("WORKER_NAME=node-a", heartbeat_script)
        self.assertIn("/api/nodes/heartbeat", heartbeat_script)
        self.assertIn("A9_HEARTBEAT_ONCE", heartbeat_script)
        self.assertIn('"node_id"', heartbeat_script)
        self.assertIn('"current_task"', heartbeat_script)
        self.assertIn('"message"', heartbeat_script)
        self.assertIn('"load"', heartbeat_script)

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

    def test_remote_probe_script_lists_required_before_optional_tools(self):
        mod = load_module()
        script = mod.remote_probe_script()
        self.assertLess(script.index("git"), script.index("tmux"))
        self.assertLess(script.index("python3"), script.index("tmux"))
        self.assertLess(script.index("curl"), script.index("tailscale"))

    def test_classify_probe_result_repairs_when_required_tools_missing(self):
        mod = load_module()
        result = mod.classify_probe_result(
            0,
            {
                "git": "",
                "python3": "/usr/bin/python3",
                "curl": "",
                "tmux": "",
                "tailscale": "/usr/bin/tailscale",
            },
        )
        self.assertEqual(result["probe_action"], "repair")
        self.assertEqual(result["probe_action_reason"], "missing_required_tools")
        self.assertEqual(result["required_missing"], ["git", "curl"])
        self.assertEqual(result["optional_missing"], ["tmux"])

    def test_classify_probe_result_optional_missing_is_continue(self):
        mod = load_module()
        result = mod.classify_probe_result(
            0,
            {
                "git": "/usr/bin/git",
                "python3": "/usr/bin/python3",
                "curl": "/usr/bin/curl",
                "tmux": "",
                "tailscale": "",
            },
        )
        self.assertEqual(result["probe_action"], "continue")
        self.assertEqual(result["probe_action_reason"], "optional_tools_missing")
        self.assertEqual(result["required_missing"], [])
        self.assertEqual(result["optional_missing"], ["tmux", "tailscale"])

    def test_classify_probe_result_nonzero_return_code_is_retry_and_preserves_parse(self):
        mod = load_module()
        parsed = mod.parse_probe("git=\npython3=/usr/bin/python3\ncurl=/usr/bin/curl\ntmux=\n")
        result = mod.classify_probe_result(255, parsed)
        self.assertEqual(parsed["python3"], "/usr/bin/python3")
        self.assertEqual(result["probe_action"], "retry")
        self.assertEqual(result["probe_action_reason"], "ssh_exec_error")
        self.assertEqual(result["required_missing"], ["git"])
        self.assertEqual(result["optional_missing"], ["tmux", "tailscale"])

    def test_reconnect_governance_helpers_cover_backoff_connect_stream_and_lifecycle(self):
        mod = load_module()
        self.assertEqual(mod.capped_reconnect_backoff_seconds(0), 1)
        self.assertEqual(mod.capped_reconnect_backoff_seconds(3), 8)
        self.assertEqual(mod.capped_reconnect_backoff_seconds(10), 30)
        self.assertEqual(mod.connect_error_action("ssh_exec_error"), "reconnect")
        self.assertEqual(mod.connect_error_action("auth_invalid"), "terminate")
        self.assertEqual(mod.stream_error_action("decode_error"), "continue")
        self.assertEqual(mod.stream_error_action("broken_pipe"), "reconnect")
        event = mod.lifecycle_update("reconnecting", node_id="node-1", at="2026-05-27T00:00:00+00:00", details={"k": "v"})
        self.assertEqual(event["event"], "reconnecting")
        self.assertEqual(event["node_id"], "node-1")
        self.assertEqual(event["details"]["k"], "v")

    def test_gateway_reconnect_decision_connect_retry(self):
        mod = load_module()
        decision = mod.gateway_reconnect_decision(
            phase="connect",
            error_class="ssh_exec_error",
            attempt=0,
            policy_budget_remaining=3,
            node_id="node-1",
            origin="probe",
            at="2026-05-28T00:00:00+00:00",
        )
        self.assertEqual(decision["kind"], "error")
        self.assertEqual(decision["action"], "reconnect")
        self.assertEqual(decision["attempt"], 1)
        self.assertEqual(decision["delay_ms"], 1000)
        self.assertEqual(decision["phase"], "connect")

    def test_gateway_reconnect_decision_connect_terminate(self):
        mod = load_module()
        decision = mod.gateway_reconnect_decision(
            phase="connect",
            error_class="auth_invalid",
            attempt=2,
            policy_budget_remaining=3,
        )
        self.assertEqual(decision["action"], "terminate")
        self.assertEqual(decision["attempt"], 2)
        self.assertEqual(decision["delay_ms"], 0)

    def test_gateway_reconnect_decision_stream_continue(self):
        mod = load_module()
        decision = mod.gateway_reconnect_decision(
            phase="stream",
            error_class="decode_error",
            attempt=3,
            policy_budget_remaining=3,
        )
        self.assertEqual(decision["action"], "continue")
        self.assertEqual(decision["attempt"], 3)
        self.assertEqual(decision["delay_ms"], 0)

    def test_gateway_reconnect_decision_stream_reconnect(self):
        mod = load_module()
        decision = mod.gateway_reconnect_decision(
            phase="stream",
            error_class="broken_pipe",
            attempt=2,
            policy_budget_remaining=3,
        )
        self.assertEqual(decision["action"], "reconnect")
        self.assertEqual(decision["attempt"], 3)
        self.assertEqual(decision["delay_ms"], 4000)

    def test_gateway_reconnect_decision_attempt_cap_terminates(self):
        mod = load_module()
        decision = mod.gateway_reconnect_decision(
            phase="connect",
            error_class="ssh_exec_error",
            attempt=3,
            attempt_cap=3,
            policy_budget_remaining=3,
        )
        self.assertEqual(decision["action"], "terminate")
        self.assertEqual(decision["attempt"], 3)
        self.assertEqual(decision["delay_ms"], 0)

    def test_gateway_reconnect_decision_success_resets_baseline(self):
        mod = load_module()
        decision = mod.gateway_reconnect_decision(
            phase="success",
            error_class="",
            attempt=5,
            policy_budget_remaining=3,
            node_id="node-1",
            origin="stream",
        )
        self.assertEqual(decision["kind"], "lifecycle")
        self.assertEqual(decision["action"], "connected")
        self.assertEqual(decision["attempt"], 0)
        self.assertEqual(decision["delay_ms"], 0)
        self.assertEqual(decision["node_id"], "node-1")


if __name__ == "__main__":
    unittest.main()
