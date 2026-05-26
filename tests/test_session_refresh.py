#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SESSION_REFRESH = ROOT / "scripts" / "a9_session_refresh.py"


def write_fake_session(path: Path) -> None:
    rows = [
        {"timestamp": "2026-01-01T00:00:00Z", "type": "session_meta", "payload": {"id": "fake-session"}},
        {
            "timestamp": "2026-01-01T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "<environment_context>skip</environment_context>"}],
            },
        },
        {
            "timestamp": "2026-01-01T00:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "first task"}],
            },
        },
        {
            "timestamp": "2026-01-01T00:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "first answer"}],
            },
        },
        {
            "timestamp": "2026-01-01T00:00:04Z",
            "type": "response_item",
            "payload": {"type": "function_call", "name": "exec_command", "arguments": "{\"cmd\":\"true\"}"},
        },
        {
            "timestamp": "2026-01-01T00:00:05Z",
            "type": "response_item",
            "payload": {"type": "function_call_output", "output": "ok"},
        },
        {
            "timestamp": "2026-01-01T00:00:06Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "second task"}],
            },
        },
        {
            "timestamp": "2026-01-01T00:00:07Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "second answer"}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class SessionRefreshTests(unittest.TestCase):
    def test_index_skips_environment_context_and_records_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session.jsonl"
            write_fake_session(session)
            result = subprocess.run(
                [str(SESSION_REFRESH), "index", str(session), "--batch-size", "1"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["session_id"], "fake-session")
            self.assertEqual(payload["user_turn_count"], 2)
            self.assertEqual(payload["turns"][0]["turn"], 1)
            self.assertEqual(payload["turns"][0]["line"], 3)
            self.assertEqual(payload["batches"][0]["approx_lines"], "3-3")

    def test_extract_turn_range_includes_assistant_and_tool_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session.jsonl"
            write_fake_session(session)
            result = subprocess.run(
                [str(SESSION_REFRESH), "extract", str(session), "--from-turn", "1", "--to-turn", "1"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["from_turn"], 1)
            self.assertEqual(payload["to_turn"], 1)
            self.assertEqual(payload["turns"][0]["user_text"], "first task")
            self.assertEqual(payload["turns"][0]["assistant_messages"], ["first answer"])
            self.assertEqual(payload["turns"][0]["tool_calls"][0]["name"], "exec_command")
            self.assertEqual(payload["turns"][0]["tool_output_count"], 1)

    def test_refresh_writes_index_and_extract_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session.jsonl"
            out_dir = Path(tmp) / "out"
            write_fake_session(session)
            result = subprocess.run(
                [
                    str(SESSION_REFRESH),
                    "refresh",
                    str(session),
                    "--from-turn",
                    "2",
                    "--to-turn",
                    "2",
                    "--out-dir",
                    str(out_dir),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(Path(payload["index_path"]).exists())
            self.assertTrue(Path(payload["extract_path"]).exists())
            extracted = json.loads(Path(payload["extract_path"]).read_text(encoding="utf-8"))
            self.assertEqual(extracted["turns"][0]["user_text"], "second task")


if __name__ == "__main__":
    unittest.main()
