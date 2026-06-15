#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "scripts" / "a9_codex_session_adapter.py"


def write_fake_session(path: Path) -> None:
    rows = [
        {"timestamp": "2026-01-01T00:00:00Z", "type": "session_meta", "payload": {"id": "fake-session"}},
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "developer instruction"}],
            },
        },
        {
            "timestamp": "2026-01-01T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "first task"}],
            },
        },
        {
            "timestamp": "2026-01-01T00:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "first answer"}],
            },
        },
        {
            "timestamp": "2026-01-01T00:00:03Z",
            "type": "response_item",
            "payload": {"type": "function_call", "name": "exec_command", "arguments": "{\"cmd\":\"true\"}"},
        },
        {
            "timestamp": "2026-01-01T00:00:04Z",
            "type": "response_item",
            "payload": {"type": "function_call_output", "output": "ok"},
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class CodexSessionAdapterTests(unittest.TestCase):
    def test_convert_emits_traceable_drawers(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session.jsonl"
            write_fake_session(session)
            result = subprocess.run(
                [str(ADAPTER), "convert", str(session), "--pretty"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["session_id"], "fake-session")
            self.assertEqual(payload["drawer_count"], 5)
            first = payload["records"][0]
            self.assertEqual(first["schema"], "a9.mempalace.drawer.v1")
            self.assertEqual(first["role"], "developer")
            self.assertEqual(first["event_kind"], "message")
            self.assertEqual(first["source_line"], 2)
            self.assertEqual(first["content"], "developer instruction")
            self.assertIn("content_hash", first)
            self.assertIn("raw_line_sha256", first)
            self.assertEqual(payload["records"][1]["role"], "user")
            self.assertEqual(payload["records"][3]["event_kind"], "tool_call")
            self.assertEqual(payload["records"][3]["metadata"]["tool_name"], "exec_command")
            self.assertEqual(payload["records"][4]["event_kind"], "tool_output")

    def test_convert_can_write_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session.jsonl"
            out = Path(tmp) / "drawers.jsonl"
            write_fake_session(session)
            result = subprocess.run(
                [str(ADAPTER), "convert", str(session), "--out", str(out)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["drawer_count"], 5)
            records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 5)
            self.assertTrue(records[0]["source_ref"].endswith(":2"))


if __name__ == "__main__":
    unittest.main()
