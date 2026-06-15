#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROVIDER = ROOT / "scripts" / "a9_mempalace_provider.py"


def write_drawers(path: Path) -> None:
    rows = [
        {
            "schema": "a9.mempalace.drawer.v1",
            "drawer_id": "d1",
            "session_id": "s1",
            "role": "user",
            "event_kind": "message",
            "timestamp": "2026-01-01T00:00:00Z",
            "source_ref": "session.jsonl:10",
            "source_sha256": "sourcehash",
            "content_hash": "hash1",
            "content": "MemPalace first current mainline is session governance.",
        },
        {
            "schema": "a9.mempalace.drawer.v1",
            "drawer_id": "d2",
            "session_id": "s1",
            "role": "assistant",
            "event_kind": "message",
            "timestamp": "2026-01-01T00:00:01Z",
            "source_ref": "session.jsonl:11",
            "source_sha256": "sourcehash",
            "content_hash": "hash2",
            "content": "Worker should not treat recall as truth.",
        },
        {
            "schema": "a9.mempalace.drawer.v1",
            "drawer_id": "d3",
            "session_id": "s1",
            "role": "tool",
            "event_kind": "tool_output",
            "timestamp": "2026-01-01T00:00:02Z",
            "source_ref": "session.jsonl:12",
            "source_sha256": "sourcehash",
            "content_hash": "hash3",
            "content": "recall truth recall truth recall truth",
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class MempalaceProviderTests(unittest.TestCase):
    def test_status_reports_fallback_drawers(self):
        with tempfile.TemporaryDirectory() as tmp:
            drawers = Path(tmp) / "drawers.jsonl"
            write_drawers(drawers)
            result = subprocess.run(
                [str(PROVIDER), "--drawers", str(drawers), "status"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["fallback_drawers"]["drawer_count"], 3)
            self.assertEqual(payload["fallback_drawers"]["roles"]["user"], 1)

    def test_search_returns_source_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            drawers = Path(tmp) / "drawers.jsonl"
            write_drawers(drawers)
            result = subprocess.run(
                [str(PROVIDER), "--drawers", str(drawers), "search", "session governance", "--limit", "1"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["truth_policy"], "recall_not_truth")
            self.assertEqual(payload["results"][0]["source_ref"], "session.jsonl:10")
            self.assertEqual(payload["results"][0]["content_hash"], "hash1")

    def test_wakeup_keeps_recall_not_truth_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            drawers = Path(tmp) / "drawers.jsonl"
            write_drawers(drawers)
            result = subprocess.run(
                [str(PROVIDER), "--drawers", str(drawers), "wakeup", "--query", "recall truth"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema"], "a9.wakeup_pack.v1")
            self.assertEqual(payload["truth_policy"], "recall_not_truth")
            self.assertTrue(payload["evidence_refs"])
            self.assertEqual(payload["recall"][0]["event_kind"], "message")


if __name__ == "__main__":
    unittest.main()
