#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
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
            "context_pressure": {"budget_ratio": 0.25},
        }

        compact = mod.compact_summary(summary)

        self.assertEqual(compact["task_id"], "task-1")
        self.assertEqual(compact["worker_envelope"]["status"], "pass")
        self.assertEqual(compact["policy_attestation"]["attestation_hash"], "abc")
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
        self.assertEqual(stale["last_seen_age_seconds"], 180)
        self.assertEqual(offline["connection_state"], "offline")

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
                    "last_heartbeat_at": "2026-05-26T12:00:00+00:00",
                }
            )
        finally:
            mod.redis_cli = original_redis

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["json_key"], "a9:node:node-a")
        self.assertTrue(any(call[:2] == ["JSON.SET", "a9:node:node-a"] for call in calls))
        self.assertTrue(any(call[:2] == ["XADD", "a9:heartbeats"] for call in calls))
        self.assertTrue(any(call[:2] == ["TS.ADD", "a9:ts:heartbeat"] for call in calls))

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
        self.assertEqual(result["probe"]["python3"], "/usr/bin/python3")
        self.assertEqual(status["count"], 1)
        self.assertEqual(status["nodes"][0]["host"], "node1")
        self.assertEqual(status["nodes"][0]["capabilities"]["python3"], "/usr/bin/python3")

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
            self.assertTrue(Path(result["evidence_path"]).exists())

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
        self.assertFalse(discovery["runtime"]["worker_claim_ready"])

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
