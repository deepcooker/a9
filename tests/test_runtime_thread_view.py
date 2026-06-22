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
    def test_project_summary_builds_codex_like_turn_view(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run-1"
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
                        "status": "ok",
                        "started_at": "2026-06-22T00:00:00+00:00",
                        "ended_at": "2026-06-22T00:01:00+00:00",
                        "worker": {"event_summaries_path": str(events)},
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            projected = mod.project_summary(summary)

            self.assertEqual(projected["thread_id"], "thread-abc")
            self.assertEqual(projected["task_id"], "task-1")
            self.assertEqual(projected["thread_status"], "completed")
            self.assertEqual(projected["turns"][0]["item_count"], 1)
            self.assertEqual(projected["turns"][0]["items"][0]["item_type"], "command_execution")
            self.assertEqual(projected["evidence"]["summary_path"], str(summary))
            self.assertEqual(projected["evidence"]["event_summaries_path"], str(events))

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
