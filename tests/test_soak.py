#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import types
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOAK_PATH = ROOT / "scripts" / "a9_soak.py"


def load_soak():
    spec = importlib.util.spec_from_file_location("a9_soak", SOAK_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SoakTests(unittest.TestCase):
    def test_seed_prompt_is_copy_pipeline_not_domain_business_logic(self):
        mod = load_soak()
        prompt = mod.seed_prompt()

        self.assertIn("copy-pipeline", prompt)
        self.assertIn("reference_scan", prompt)
        self.assertIn("vendor_import", prompt)
        self.assertIn("not domain business logic", prompt)

    def test_fake_worker_command_writes_required_outputs(self):
        mod = load_soak()
        command = mod.fake_worker_cmd()

        self.assertIn("soak-output.txt", command)
        self.assertIn("{run_dir}/final.md", command)
        self.assertIn("turn.completed", command)

    def test_write_report_writes_latest_pointer(self):
        mod = load_soak()
        with tempfile.TemporaryDirectory() as tmp:
            original_soak_dir = mod.SOAK_DIR
            original_reports_dir = mod.REPORTS_DIR
            mod.SOAK_DIR = Path(tmp) / "soak"
            mod.REPORTS_DIR = mod.SOAK_DIR / "reports"
            try:
                path = mod.write_report({"return_code": 0, "progress": {"progress_percent": 100.0}})
                latest = mod.SOAK_DIR / "latest.json"
                self.assertTrue(path.exists())
                self.assertTrue(latest.exists())
                self.assertEqual(json.loads(latest.read_text(encoding="utf-8"))["return_code"], 0)
            finally:
                mod.SOAK_DIR = original_soak_dir
                mod.REPORTS_DIR = original_reports_dir

    def test_refresh_heartbeat_after_cleanup_updates_queue_count(self):
        mod = load_soak()
        with tempfile.TemporaryDirectory() as tmp:
            original_state_dir = mod.STATE_DIR
            original_queue_dir = mod.QUEUE_DIR
            original_heartbeat_path = mod.HEARTBEAT_PATH
            mod.STATE_DIR = Path(tmp)
            mod.QUEUE_DIR = mod.STATE_DIR / "tasks" / "queue"
            mod.HEARTBEAT_PATH = mod.STATE_DIR / "daemon_heartbeat.json"
            mod.QUEUE_DIR.mkdir(parents=True)
            mod.HEARTBEAT_PATH.write_text(
                json.dumps({"state": "sleeping", "queued_tasks": 9}),
                encoding="utf-8",
            )
            try:
                heartbeat = mod.refresh_heartbeat_after_cleanup()
                self.assertEqual(heartbeat["queued_tasks"], 0)
                self.assertEqual(json.loads(mod.HEARTBEAT_PATH.read_text(encoding="utf-8"))["queued_tasks"], 0)
            finally:
                mod.STATE_DIR = original_state_dir
                mod.QUEUE_DIR = original_queue_dir
                mod.HEARTBEAT_PATH = original_heartbeat_path

    def test_communication_snapshot_reads_control_api_node_status(self):
        mod = load_soak()
        with tempfile.TemporaryDirectory() as tmp:
            control_api_path = Path(tmp) / "a9_control_api.py"
            control_api_path.write_text(
                "\n".join(
                    [
                        "def node_status(root=None):",
                        "    return {",
                        "        'count': 2,",
                        "        'redis': {'status': 'ok'},",
                        "        'tasks_stream': {'thresholds_version': 'redis_streams_v1', 'stream_action': 'continue'}",
                        "    }",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            original_control_api_path = mod.CONTROL_API_PATH
            mod.CONTROL_API_PATH = control_api_path
            try:
                snapshot = mod.communication_snapshot()
                self.assertEqual(snapshot["status"], "ok")
                self.assertEqual(snapshot["nodes_count"], 2)
                self.assertEqual(snapshot["redis"]["status"], "ok")
                self.assertEqual(snapshot["tasks_stream"]["thresholds_version"], "redis_streams_v1")
            finally:
                mod.CONTROL_API_PATH = original_control_api_path

    def test_communication_snapshot_degrades_when_control_api_is_unavailable(self):
        mod = load_soak()
        with tempfile.TemporaryDirectory() as tmp:
            original_control_api_path = mod.CONTROL_API_PATH
            mod.CONTROL_API_PATH = Path(tmp) / "missing_a9_control_api.py"
            try:
                snapshot = mod.communication_snapshot()
                self.assertEqual(snapshot["status"], "unavailable")
                self.assertIn("reason", snapshot)
            finally:
                mod.CONTROL_API_PATH = original_control_api_path

    def test_cleanup_next_tasks_removes_only_matching_auto_tasks(self):
        mod = load_soak()
        with tempfile.TemporaryDirectory() as tmp:
            original_queue_dir = mod.QUEUE_DIR
            mod.QUEUE_DIR = Path(tmp)
            try:
                keep = mod.QUEUE_DIR / "auto-implement-other-20260101T000000Z.md"
                remove = mod.QUEUE_DIR / "auto-mechanism_extract-soak-20260101T000000Z.md"
                keep.write_text("keep", encoding="utf-8")
                remove.write_text("remove", encoding="utf-8")

                cleaned = mod.cleanup_next_tasks("soak")

                self.assertEqual(cleaned, [str(remove)])
                self.assertFalse(remove.exists())
                self.assertTrue(keep.exists())
            finally:
                mod.QUEUE_DIR = original_queue_dir

    def test_latest_run_summaries_include_guard_evidence(self):
        mod = load_soak()
        with tempfile.TemporaryDirectory() as tmp:
            original_runs_dir = mod.RUNS_DIR
            mod.RUNS_DIR = Path(tmp)
            run_dir = mod.RUNS_DIR / "run-a"
            run_dir.mkdir()
            (run_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "task_id": "guarded-task",
                        "status": "pass",
                        "phase": "test",
                        "run_dir": str(run_dir),
                        "patch_guard": {
                            "status": "pass",
                            "kind": "unified_diff",
                            "touched_files": ["scripts/a9_patch_guard.py"],
                            "findings": [],
                            "output_path": str(run_dir / "patch_guard.json"),
                        },
                        "scope_guard": {
                            "status": "pass",
                            "changed_files": ["scripts/a9_scope_guard.py"],
                            "findings": [],
                            "output_path": str(run_dir / "scope_guard.json"),
                        },
                        "checks": [{"command": "python3 -m unittest", "return_code": 0}],
                    }
                ),
                encoding="utf-8",
            )
            try:
                summaries = mod.latest_run_summaries(1)

                self.assertEqual(summaries[0]["guards"]["patch_guard"]["status"], "pass")
                self.assertEqual(summaries[0]["guards"]["patch_guard"]["findings_count"], 0)
                self.assertEqual(
                    summaries[0]["guards"]["patch_guard"]["touched_files"],
                    ["scripts/a9_patch_guard.py"],
                )
                self.assertEqual(summaries[0]["guards"]["scope_guard"]["status"], "pass")
                self.assertEqual(
                    summaries[0]["guards"]["scope_guard"]["touched_files"],
                    ["scripts/a9_scope_guard.py"],
                )
            finally:
                mod.RUNS_DIR = original_runs_dir

    def test_run_soak_latest_report_keeps_tasks_stream_action_fields_after_cleanup(self):
        mod = load_soak()
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / ".a9"
            queue_dir = state_dir / "tasks" / "queue"
            queue_dir.mkdir(parents=True)
            soak_dir = state_dir / "soak"
            reports_dir = soak_dir / "reports"

            task_id = "soak"
            auto_next = queue_dir / "auto-mechanism_extract-soak-20260101T000000Z.md"
            unrelated = queue_dir / "auto-mechanism_extract-other-20260101T000000Z.md"
            auto_next.write_text("auto", encoding="utf-8")
            unrelated.write_text("keep", encoding="utf-8")

            progress_path = state_dir / "progress.json"
            heartbeat_path = state_dir / "daemon_heartbeat.json"
            progress_path.write_text(
                json.dumps(
                    {
                        "next_task_path": str(auto_next),
                        "auto_next_scheduled": True,
                        "queued_tasks": 2,
                    }
                ),
                encoding="utf-8",
            )
            heartbeat_path.write_text(
                json.dumps({"queued_tasks": 2, "running_tasks": 0}),
                encoding="utf-8",
            )

            original_state_dir = mod.STATE_DIR
            original_soak_dir = mod.SOAK_DIR
            original_reports_dir = mod.REPORTS_DIR
            original_progress_path = mod.PROGRESS_PATH
            original_heartbeat_path = mod.HEARTBEAT_PATH
            original_queue_dir = mod.QUEUE_DIR
            original_enqueue_seed = mod.enqueue_seed
            original_run_cmd = mod.run_cmd
            original_latest_run_summaries = mod.latest_run_summaries
            original_communication_snapshot = mod.communication_snapshot
            try:
                mod.STATE_DIR = state_dir
                mod.SOAK_DIR = soak_dir
                mod.REPORTS_DIR = reports_dir
                mod.PROGRESS_PATH = progress_path
                mod.HEARTBEAT_PATH = heartbeat_path
                mod.QUEUE_DIR = queue_dir
                mod.enqueue_seed = lambda *_args, **_kwargs: queue_dir / f"{task_id}.md"
                mod.run_cmd = lambda *_args, **_kwargs: types.SimpleNamespace(returncode=0, stdout="run ok\n")
                mod.latest_run_summaries = lambda _limit: []
                mod.communication_snapshot = lambda: {
                    "status": "ok",
                    "tasks_stream": {
                        "stream_action": "continue",
                        "stream_action_reason": "healthy",
                    },
                }

                rc = mod.run_soak(
                    types.SimpleNamespace(
                        task_id=task_id,
                        phase="test",
                        fake_worker=True,
                        sleep_seconds=0.0,
                        tasks=1,
                        keep_next=False,
                    )
                )

                latest = json.loads((soak_dir / "latest.json").read_text(encoding="utf-8"))
                self.assertEqual(rc, 0)
                self.assertEqual(latest["communication"]["tasks_stream"]["stream_action"], "continue")
                self.assertEqual(latest["communication"]["tasks_stream"]["stream_action_reason"], "healthy")
                self.assertFalse(auto_next.exists())
                self.assertTrue(unrelated.exists())
            finally:
                mod.STATE_DIR = original_state_dir
                mod.SOAK_DIR = original_soak_dir
                mod.REPORTS_DIR = original_reports_dir
                mod.PROGRESS_PATH = original_progress_path
                mod.HEARTBEAT_PATH = original_heartbeat_path
                mod.QUEUE_DIR = original_queue_dir
                mod.enqueue_seed = original_enqueue_seed
                mod.run_cmd = original_run_cmd
                mod.latest_run_summaries = original_latest_run_summaries
                mod.communication_snapshot = original_communication_snapshot

    def test_run_soak_latest_report_keeps_tasks_stream_degraded_action_fields(self):
        mod = load_soak()
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / ".a9"
            queue_dir = state_dir / "tasks" / "queue"
            queue_dir.mkdir(parents=True)
            soak_dir = state_dir / "soak"
            reports_dir = soak_dir / "reports"
            task_id = "soak"

            original_state_dir = mod.STATE_DIR
            original_soak_dir = mod.SOAK_DIR
            original_reports_dir = mod.REPORTS_DIR
            original_progress_path = mod.PROGRESS_PATH
            original_heartbeat_path = mod.HEARTBEAT_PATH
            original_queue_dir = mod.QUEUE_DIR
            original_enqueue_seed = mod.enqueue_seed
            original_run_cmd = mod.run_cmd
            original_latest_run_summaries = mod.latest_run_summaries
            original_communication_snapshot = mod.communication_snapshot
            try:
                mod.STATE_DIR = state_dir
                mod.SOAK_DIR = soak_dir
                mod.REPORTS_DIR = reports_dir
                mod.PROGRESS_PATH = state_dir / "progress.json"
                mod.HEARTBEAT_PATH = state_dir / "daemon_heartbeat.json"
                mod.QUEUE_DIR = queue_dir
                mod.enqueue_seed = lambda *_args, **_kwargs: queue_dir / f"{task_id}.md"
                mod.run_cmd = lambda *_args, **_kwargs: types.SimpleNamespace(returncode=0, stdout="run ok\n")
                mod.latest_run_summaries = lambda _limit: []
                mod.communication_snapshot = lambda: {
                    "status": "ok",
                    "tasks_stream": {
                        "status": "degraded",
                        "reason": "consumer_group_missing",
                        "thresholds_version": "redis_streams_v1",
                        "stream_action": "watch",
                        "stream_action_reason": "consumer_group_missing",
                    },
                }

                rc = mod.run_soak(
                    types.SimpleNamespace(
                        task_id=task_id,
                        phase="test",
                        fake_worker=True,
                        sleep_seconds=0.0,
                        tasks=1,
                        keep_next=False,
                    )
                )

                latest = json.loads((soak_dir / "latest.json").read_text(encoding="utf-8"))
                stream = latest["communication"]["tasks_stream"]
                self.assertEqual(rc, 0)
                self.assertEqual(stream["thresholds_version"], "redis_streams_v1")
                self.assertEqual(stream["stream_action"], "watch")
                self.assertEqual(stream["stream_action_reason"], "consumer_group_missing")
            finally:
                mod.STATE_DIR = original_state_dir
                mod.SOAK_DIR = original_soak_dir
                mod.REPORTS_DIR = original_reports_dir
                mod.PROGRESS_PATH = original_progress_path
                mod.HEARTBEAT_PATH = original_heartbeat_path
                mod.QUEUE_DIR = original_queue_dir
                mod.enqueue_seed = original_enqueue_seed
                mod.run_cmd = original_run_cmd
                mod.latest_run_summaries = original_latest_run_summaries
                mod.communication_snapshot = original_communication_snapshot


if __name__ == "__main__":
    unittest.main()
