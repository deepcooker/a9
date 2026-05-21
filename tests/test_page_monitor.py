#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MONITOR_PATH = ROOT / "scripts" / "a9_page_monitor.py"


def load_monitor():
    spec = importlib.util.spec_from_file_location("a9_page_monitor", MONITOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PageMonitorTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_monitor()
        for path in [self.mod.STATE_PATH, self.mod.SNAPSHOT_PATH, self.mod.CONTINUATION_PATH]:
            path.unlink(missing_ok=True)

    def test_check_once_writes_snapshot_and_continuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "transcript.md"
            transcript.write_text("USER: continue\nASSISTANT: working on scripts/a9_page_monitor.py\n", encoding="utf-8")
            args = Namespace(
                transcript=str(transcript),
                idle_seconds=300.0,
                tail_chars=1000,
                enqueue_on_idle=False,
                now="2026-01-01T00:00:00+00:00",
            )
            with redirect_stdout(io.StringIO()):
                code = self.mod.check_once(args)
        self.assertEqual(code, 0)
        state = json.loads(self.mod.STATE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["updated_at"], "2026-01-01T00:00:00+00:00")
        self.assertTrue(self.mod.SNAPSHOT_PATH.exists())
        self.assertIn("Recent transcript tail", self.mod.CONTINUATION_PATH.read_text(encoding="utf-8"))

    def test_idle_detection_uses_unchanged_hash_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "transcript.md"
            transcript.write_text("ASSISTANT: task complete\n", encoding="utf-8")
            content_hash = self.mod.sha256_text(transcript.read_text(encoding="utf-8"))
            self.mod.write_json(
                self.mod.STATE_PATH,
                {
                    "content_hash": content_hash,
                    "first_seen_epoch": self.mod.parse_now("2026-01-01T00:00:00+00:00")[0],
                },
            )
            args = Namespace(
                transcript=str(transcript),
                idle_seconds=30.0,
                tail_chars=1000,
                enqueue_on_idle=False,
                now="2026-01-01T00:02:00+00:00",
            )
            with redirect_stdout(io.StringIO()):
                self.mod.check_once(args)
        state = json.loads(self.mod.STATE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "stopped")
        self.assertGreaterEqual(state["unchanged_seconds"], 30)

    def test_enqueue_on_idle_hands_off_once_per_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "transcript.md"
            transcript.write_text("ASSISTANT: completed\n", encoding="utf-8")
            content_hash = self.mod.sha256_text(transcript.read_text(encoding="utf-8"))
            self.mod.write_json(
                self.mod.STATE_PATH,
                {
                    "content_hash": content_hash,
                    "first_seen_epoch": self.mod.parse_now("2026-01-01T00:00:00+00:00")[0],
                },
            )
            args = Namespace(
                transcript=str(transcript),
                idle_seconds=30.0,
                tail_chars=1000,
                enqueue_on_idle=True,
                now="2026-01-01T00:10:00+00:00",
            )
            with mock.patch.object(self.mod, "enqueue_continuation", return_value="/root/a9/.a9/tasks/queue/page-monitor-continue.md") as enqueue:
                with redirect_stdout(io.StringIO()):
                    self.mod.check_once(args)
                    self.mod.check_once(args)
        state = json.loads(self.mod.STATE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "stopped")
        self.assertEqual(state["enqueued_for_hash"], content_hash)
        enqueue.assert_called_once()


if __name__ == "__main__":
    unittest.main()
