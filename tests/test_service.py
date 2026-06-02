#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import argparse
import json
import subprocess
import tempfile
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = ROOT / "scripts" / "a9_service.py"
SUPERVISOR_PATH = ROOT / "scripts" / "a9_supervisor.py"
UNIT_PATH = ROOT / "infra" / "systemd" / "a9-supervisor.service"
NODE_WORKER_UNIT_PATH = ROOT / "infra" / "systemd" / "a9-node-worker.service"
RECOVERY_LOOP_UNIT_PATH = ROOT / "infra" / "systemd" / "a9-recovery-loop.service"
STACK_PATH = ROOT / "scripts" / "a9_stack.sh"


def load_service():
    spec = importlib.util.spec_from_file_location("a9_service", SERVICE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_supervisor():
    spec = importlib.util.spec_from_file_location("a9_supervisor", SUPERVISOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ServiceTests(unittest.TestCase):
    def test_systemd_unit_runs_auto_next_loop(self):
        unit = UNIT_PATH.read_text(encoding="utf-8")
        self.assertIn("ExecStart=/root/a9/scripts/a9_supervisor.py run-loop --auto-next", unit)
        self.assertIn("Restart=always", unit)
        self.assertIn("ExecStartPre=/root/a9/scripts/a9_middleware.py status", unit)

    def test_local_stack_runs_supervisor_loop(self):
        stack = STACK_PATH.read_text(encoding="utf-8")
        self.assertIn("start_supervisor_loop", stack)
        self.assertIn("A9_IDLE_GOAL_CONTINUATION=0", stack)
        self.assertIn("scripts/a9_supervisor.py run-loop --auto-next --sleep-seconds 10 --keep-going-on-error", stack)
        self.assertIn("supervisor-loop.log", stack)
        self.assertIn("status_one supervisor-loop 0", stack)

    def test_node_worker_systemd_unit_runs_command_loop(self):
        unit = NODE_WORKER_UNIT_PATH.read_text(encoding="utf-8")
        self.assertIn("ExecStart=/root/a9/scripts/a9_node.py command-work-loop", unit)
        self.assertIn("--block-ms 5000 --timeout 10", unit)
        self.assertIn("Restart=always", unit)
        self.assertIn("After=network-online.target docker.service a9-control-api.service", unit)

    def test_recovery_loop_systemd_unit_runs_planning_loop(self):
        unit = RECOVERY_LOOP_UNIT_PATH.read_text(encoding="utf-8")
        self.assertIn("ExecStart=/root/a9/scripts/a9_recovery_loop.py", unit)
        self.assertIn("--interval-seconds 60", unit)
        self.assertIn("--max-actions 3", unit)
        self.assertIn("Restart=always", unit)
        self.assertIn("After=network-online.target a9-control-api.service", unit)

    def test_service_unit_command_prints_unit(self):
        result = subprocess.run(
            [str(SERVICE_PATH), "unit"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("[Unit]", result.stdout)
        self.assertIn("a9_supervisor.py run-loop --auto-next", result.stdout)
        self.assertIn("a9_node.py command-work-loop", result.stdout)
        self.assertIn("a9_recovery_loop.py", result.stdout)

    def test_parse_process_table_finds_supervisor_node_worker_and_worker(self):
        mod = load_service()
        processes = mod.parse_process_table(
            """123 1 00:01:02 python3 scripts/a9_supervisor.py run-loop --auto-next
321 1 00:00:30 python3 scripts/a9_node.py command-work-loop --block-ms 5000
654 1 00:00:10 python3 scripts/a9_recovery_loop.py --interval-seconds 60
456 123 00:00:20 node /usr/local/bin/codex exec --json -C /tmp/work prompt
789 1 00:00:01 rg 'a9_supervisor.py run-loop|codex exec --json'
"""
        )

        self.assertEqual([item["kind"] for item in processes], ["supervisor", "node-worker", "recovery-loop", "worker"])
        self.assertEqual(processes[0]["pid"], 123)
        self.assertEqual(processes[3]["ppid"], 123)

    def test_service_ps_command_returns_json(self):
        result = subprocess.run(
            [str(SERVICE_PATH), "ps"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertIn("processes", payload)

    def test_service_start_dry_run_returns_detached_commands(self):
        result = subprocess.run(
            [str(SERVICE_PATH), "start", "--dry-run", "--only", "control-api", "recovery-loop"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["requested"], ["control-api", "recovery-loop"])
        self.assertEqual(payload["started"][0]["kind"], "control-api")
        self.assertEqual(payload["started"][0]["command"][:2], ["setsid", "-f"])
        self.assertIn("a9_control_api.py serve", " ".join(payload["started"][0]["command"]))
        self.assertIn("a9_recovery_loop.py", " ".join(payload["started"][1]["command"]))
        self.assertIn("start_contract", payload)
        self.assertEqual(
            payload["start_contract"]["failure_taxonomy"],
            ["timeout", "auth", "network", "protocol", "rate_limit"],
        )
        self.assertIn(payload["started"][0]["command_status"]["phase"], {"planned", "already_running"})

    def test_start_cmd_sets_running_status_after_verify(self):
        mod = load_service()
        args = argparse.Namespace(command="start", all=False, only=["control-api"], dry_run=False)
        running = [{"kind": "control-api", "pid": 123, "ppid": 1, "etime": "00:00:01", "cmd": "x"}, {"kind": "control-api", "pid": 777, "ppid": 1, "etime": "00:00:02", "cmd": "x"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(mod, "STATE_DIR", Path(tmpdir) / ".a9"):
                with mock.patch.object(mod, "SERVICE_PID_DIR", Path(tmpdir) / ".a9" / "services"):
                    with mock.patch.object(mod, "running_processes", side_effect=[[], running, running]):
                        with mock.patch.object(mod.subprocess, "Popen") as popen:
                            popen.return_value.pid = 999
                            with mock.patch.object(mod.time, "sleep"):
                                with mock.patch("builtins.print") as printer:
                                    rc = mod.start_cmd(args)
                payload = json.loads(printer.call_args.args[0])
                self.assertEqual(payload["started"][0]["command_status"]["phase"], "running")
                self.assertTrue(payload["started"][0]["command_status"]["observed_running"])
                self.assertEqual(payload["started"][0]["observed_process_count"], 2)
                self.assertEqual(payload["started"][0]["pid"], 777)
                pidfile = Path(tmpdir) / ".a9" / "services" / "control-api.pid"
                self.assertEqual(pidfile.read_text(encoding="utf-8"), "777\n")
        self.assertEqual(rc, 0)

    def test_start_cmd_timeout_maps_to_retry_action(self):
        mod = load_service()
        args = argparse.Namespace(command="start", all=False, only=["control-api"], dry_run=False)
        no_process = []
        with mock.patch.object(mod, "running_processes", side_effect=[no_process] + [no_process] * mod.START_VERIFY_ATTEMPTS):
            with mock.patch.object(mod.subprocess, "Popen") as popen:
                popen.return_value.pid = 999
                with mock.patch.object(mod.time, "sleep"):
                    with mock.patch("builtins.print") as printer:
                        rc = mod.start_cmd(args)
        self.assertEqual(rc, 0)
        self.assertTrue(printer.called)
        payload = json.loads(printer.call_args.args[0])
        self.assertEqual(payload["started"][0]["command_status"]["phase"], "start_timeout")
        self.assertEqual(payload["started"][0]["command_status"]["failure_kind"], "timeout")
        self.assertEqual(payload["started"][0]["command_status"]["recovery_action"], "retry")

    def test_start_cmd_refreshes_stale_pidfile_for_already_running(self):
        mod = load_service()
        args = argparse.Namespace(command="start", all=False, only=["recovery-loop"], dry_run=False)
        running = [{"kind": "recovery-loop", "pid": 2222, "ppid": 1, "etime": "00:00:30", "cmd": "x"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(mod, "STATE_DIR", Path(tmpdir) / ".a9"):
                with mock.patch.object(mod, "SERVICE_PID_DIR", Path(tmpdir) / ".a9" / "services"):
                    pid_path = Path(tmpdir) / ".a9" / "services" / "recovery-loop.pid"
                    pid_path.parent.mkdir(parents=True, exist_ok=True)
                    pid_path.write_text("9999\n", encoding="utf-8")
                    with mock.patch.object(mod, "running_processes", return_value=running):
                        with mock.patch.object(mod.subprocess, "Popen") as popen:
                            with mock.patch("builtins.print") as printer:
                                rc = mod.start_cmd(args)
                    payload = json.loads(printer.call_args.args[0])
                    self.assertEqual(payload["started"][0]["status"], "already_running")
                    self.assertEqual(payload["started"][0]["pid"], 2222)
                    self.assertEqual(payload["started"][0]["observed_process_count"], 1)
                    self.assertEqual(pid_path.read_text(encoding="utf-8"), "2222\n")
                    popen.assert_not_called()
        self.assertEqual(rc, 0)

    def test_observed_pid_for_kind_prefers_stable_primary(self):
        mod = load_service()
        processes = [
            {"kind": "control-api", "pid": 200, "ppid": 1, "etime": "00:00:01", "cmd": "a"},
            {"kind": "control-api", "pid": 500, "ppid": 2, "etime": "00:00:02", "cmd": "b"},
            {"kind": "control-api", "pid": 500, "ppid": 3, "etime": "00:00:03", "cmd": "c"},
            {"kind": "recovery-loop", "pid": 900, "ppid": 1, "etime": "00:00:01", "cmd": "x"},
        ]
        first = mod.observed_pid_for_kind("control-api", processes)
        second = mod.observed_pid_for_kind("control-api", processes)
        self.assertEqual(first, (500, 3))
        self.assertEqual(second, (500, 3))

    def test_service_stop_dry_run_returns_json(self):
        result = subprocess.run(
            [str(SERVICE_PATH), "stop", "--dry-run"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["target"], "supervisor")

    def test_service_readiness_returns_run_mode_json(self):
        result = subprocess.run(
            [str(SERVICE_PATH), "readiness"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertIn(result.returncode, (0, 1), result.stdout)
        payload = json.loads(result.stdout)
        self.assertIn(payload["mode"], {"not_ready", "bounded_ready", "daemon_ready"})
        self.assertIn("blockers", payload)
        self.assertIn("warnings", payload)
        self.assertIn("recommendation", payload)
        self.assertIn("git", payload)

    def test_daemon_heartbeat_is_json(self):
        mod = load_supervisor()
        payload = mod.write_daemon_heartbeat("test", detail="service-test")
        self.assertEqual(payload["state"], "test")
        heartbeat = json.loads(mod.DAEMON_HEARTBEAT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(heartbeat["detail"], "service-test")

    def test_service_progress_includes_compact_guard_status(self):
        mod = load_supervisor()
        progress = mod.service_progress(
            {
                "task_id": "guard-progress-test",
                "status": "pass",
                "run_dir": "/tmp/a9-run",
                "worker": {
                    "prompt_approx_tokens": 900,
                    "prompt_budget_tokens": 1000,
                    "prompt_section_budgets": {"repo_map": 250},
                    "previous_context_path": "/tmp/context.md",
                    "previous_context_compression": {"compressed_tokens": 300},
                    "repo_map": {"approx_tokens": 220, "budget_tokens": 250},
                },
                "patch_guard": {
                    "status": "pass",
                    "return_code": 0,
                    "kind": "unified_diff",
                    "touched_files": ["scripts/a9_supervisor.py"],
                    "findings": [],
                    "output_path": "/tmp/patch_guard.json",
                },
                "scope_guard": {
                    "status": "pass",
                    "return_code": 0,
                    "changed_files": ["scripts/a9_supervisor.py"],
                    "allowed_paths": ["scripts/"],
                    "findings": [],
                    "output_path": "/tmp/scope_guard.json",
                },
            }
        )

        self.assertEqual(progress["latest_guards"]["patch_guard"]["status"], "pass")
        self.assertEqual(progress["latest_guards"]["scope_guard"]["changed_files"], ["scripts/a9_supervisor.py"])
        self.assertEqual(progress["latest_context_pressure"]["budget_ratio"], 0.9)
        self.assertEqual(progress["latest_context_pressure"]["remaining_tokens"], 100)
        self.assertEqual(progress["capability_groups"]["runtime"]["percent"], 100.0)
        self.assertEqual(progress["capability_groups"]["context"]["percent"], 100.0)
        self.assertEqual(progress["capability_groups"]["automation"]["percent"], 100.0)
        self.assertEqual(progress["capability_groups"]["governance"]["percent"], 100.0)
        self.assertTrue(
            progress["capability_groups"]["governance"]["capabilities"]["rollback_aware_repair_prompt"]
        )
        self.assertTrue(
            progress["capability_groups"]["governance"]["capabilities"]["worker_event_budget_gate"]
        )


if __name__ == "__main__":
    unittest.main()
