import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "a9_runtime_thread_view.py"


def load_module():
    spec = importlib.util.spec_from_file_location("a9_runtime_thread_view", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


class RuntimeThreadViewTests(unittest.TestCase):
    def make_summary_fixture(
        self,
        tmp: str,
        *,
        run_id: str = "run-1",
        status: str = "ok",
    ) -> Path:
        run_dir = Path(tmp) / run_id
        run_dir.mkdir()
        events = run_dir / "event_summaries.jsonl"
        write_jsonl(
            events,
            [
                {"event_type": "thread.started", "thread_id": "thread-abc"},
                {"event_type": "turn.started"},
                {
                    "event_type": "item.completed",
                    "item_id": "item_1",
                    "item_type": "command_execution",
                    "status": "completed",
                    "command": "python3 -m unittest tests.test_runtime_thread_view",
                    "exit_code": 0,
                },
                {"event_type": "turn.completed"},
            ],
        )
        summary = run_dir / "summary.json"
        summary.write_text(
            json.dumps(
                {
                    "task_id": "task-1",
                    "phase": "execution_next",
                    "status": status,
                    "started_at": "2026-06-22T00:00:00+00:00",
                    "finished_at": "2026-06-22T00:01:00+00:00",
                    "task_path": str(Path(tmp) / ".a9" / "tasks" / "queue" / "task-1.md"),
                    "worktree": str(Path(tmp) / ".a9" / "worktrees" / "task-1"),
                    "worker": {"event_summaries_path": str(events)},
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return summary

    def test_project_summary_builds_codex_like_turn_view(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            summary = self.make_summary_fixture(tmp)
            events = summary.parent / "event_summaries.jsonl"

            projected = mod.project_summary(summary)

            self.assertEqual(projected["thread_id"], "thread-abc")
            self.assertEqual(projected["task_id"], "task-1")
            self.assertEqual(projected["thread_status"], "completed")
            self.assertEqual(projected["turns"][0]["item_count"], 1)
            self.assertEqual(projected["turns"][0]["items"][0]["item_type"], "command_execution")
            self.assertEqual(projected["evidence"]["summary_path"], str(summary))
            self.assertEqual(projected["evidence"]["event_summaries_path"], str(events))
            self.assertEqual(projected["evidence"]["task_path"], str(Path(tmp) / ".a9" / "tasks" / "queue" / "task-1.md"))

    def test_build_projection_adds_runtime_schema_arrays(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            summary = self.make_summary_fixture(tmp)

            projected = mod.build_projection([summary], root=Path(tmp))

            self.assertEqual(projected["schema"], "a9.runtime_projection.v1")
            self.assertEqual(projected["counts"]["threads"], 1)
            self.assertEqual(projected["counts"]["turns"], 1)
            self.assertEqual(projected["counts"]["items"], 1)
            self.assertEqual(projected["active_runs"][0]["thread_id"], "thread-abc")
            self.assertFalse(projected["active_runs"][0]["is_active"])
            self.assertEqual(projected["worker_tasks"][0]["task_id"], "task-1")
            self.assertEqual(projected["turns"][0]["item_ids"], ["item_1"])
            self.assertEqual(projected["items"][0]["run_id"], "run-1")
            self.assertEqual(projected["operator_commands"], [])
            self.assertEqual(projected["active_run_deliveries"], [])
            self.assertEqual(projected["profile_role_lanes"], [])
            self.assertEqual(projected["handoffs"], [])

    def test_build_projection_indexes_memory_cursor_and_local_host(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = self.make_summary_fixture(tmp)
            mempalace = root / ".a9" / "mempalace"
            mempalace.mkdir(parents=True)
            (mempalace / "operator-session-ingest-cursor.json").write_text(
                json.dumps(
                    {
                        "session_id": "session-1",
                        "ordinal": 7,
                        "byte_offset": 99,
                        "source_session_path": "/tmp/session.jsonl",
                        "drawers_path": ".a9/mempalace/operator-session-drawers.jsonl",
                        "updated_at": "2026-06-22T00:02:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            services = root / ".a9" / "services"
            services.mkdir(parents=True)
            (services / "control-api.pid").write_text("123\n", encoding="utf-8")
            runtime = root / ".a9" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "operator_commands.jsonl").write_text(
                json.dumps(
                    {
                        "operator_command_id": "operator-command-1",
                        "at": "2026-06-22T00:03:00+00:00",
                        "actor": "mobile-operator",
                        "command": "monitor.intervention",
                        "action": "repair",
                        "status": "recorded",
                        "run_id": "run-1",
                        "task_id": "task-1",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (runtime / "active_run_delivery_queue.jsonl").write_text(
                json.dumps(
                    {
                        "delivery_id": "delivery-1",
                        "created_at": "2026-06-22T00:04:00+00:00",
                        "expires_at": "2026-06-22T00:34:00+00:00",
                        "status": "queued",
                        "command": "active_run.steer",
                        "action": "steer",
                        "operator_command_id": "operator-command-2",
                        "target": {"run_id": "run-1", "thread_id": "thread-abc"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (runtime / "active_run_delivery_results.jsonl").write_text(
                json.dumps(
                    {
                        "delivery_id": "delivery-1",
                        "operator_command_id": "operator-command-2",
                        "recorded_at": "2026-06-22T00:05:00+00:00",
                        "status": "rejected",
                        "reason": "active_run_transport_unavailable",
                        "transport": "codex_active_run",
                        "command": "active_run.steer",
                        "action": "steer",
                        "target": {"run_id": "run-1", "thread_id": "thread-abc"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            projected = mod.build_projection([summary], root=root)

            self.assertEqual(projected["counts"]["memory_packets"], 1)
            self.assertEqual(projected["memory_packets"][0]["session_id"], "session-1")
            self.assertEqual(projected["counts"]["remote_hosts"], 1)
            self.assertEqual(projected["remote_hosts"][0]["pid_files"], ["control-api.pid"])
            self.assertEqual(projected["counts"]["operator_commands"], 1)
            self.assertEqual(projected["operator_commands"][0]["command"], "monitor.intervention")
            self.assertEqual(projected["counts"]["active_run_deliveries"], 1)
            self.assertEqual(projected["active_run_deliveries"][0]["delivery_id"], "delivery-1")
            self.assertEqual(projected["counts"]["active_run_delivery_results"], 1)
            self.assertEqual(projected["active_run_delivery_results"][0]["reason"], "active_run_transport_unavailable")

    def test_build_projection_indexes_active_run_relay_state(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = self.make_summary_fixture(tmp)
            relays = root / ".a9" / "runtime" / "active_run_relays"
            relays.mkdir(parents=True)
            (relays / "relay-1.json").write_text(
                json.dumps(
                    {
                        "relay_id": "relay-1",
                        "run_id": "relay-run-1",
                        "task_id": "relay-task-1",
                        "status": "running",
                        "thread_id": "codex-thread-1",
                        "current_turn_id": "codex-turn-1",
                        "transport": "codex_app_server_jsonrpc",
                        "endpoint": "ws://127.0.0.1:8791",
                        "pid": 123,
                        "started_at": "2026-06-22T00:10:00+00:00",
                        "updated_at": "2026-06-22T00:11:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            projected = mod.build_projection([summary], root=root)
            active = [row for row in projected["active_runs"] if row.get("is_active")]

            self.assertEqual(projected["counts"]["active_runs"], 2)
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["run_id"], "relay-run-1")
            self.assertEqual(active[0]["thread_id"], "codex-thread-1")
            self.assertEqual(active[0]["current_turn_id"], "codex-turn-1")
            self.assertEqual(active[0]["relay"]["relay_id"], "relay-1")
            self.assertEqual(active[0]["evidence"]["relay_state_path"], str(relays / "relay-1.json"))

    def test_failed_event_overrides_summary_status(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run-2"
            run_dir.mkdir()
            events = run_dir / "event_summaries.jsonl"
            write_jsonl(
                events,
                [
                    {"event_type": "thread.started", "thread_id": "thread-failed"},
                    {"event_type": "turn.started"},
                    {"event_type": "error", "message": "limit"},
                    {"event_type": "turn.failed", "message": "limit"},
                ],
            )
            summary = run_dir / "summary.json"
            summary.write_text(
                json.dumps({"task_id": "task-2", "status": "retryable-worker-failed"}),
                encoding="utf-8",
            )

            projected = mod.project_summary(summary)

            self.assertEqual(projected["thread_status"], "failed")
            self.assertEqual(projected["turns"][0]["error"], "limit")


if __name__ == "__main__":
    unittest.main()
