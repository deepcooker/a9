#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = ROOT / "scripts" / "a9_mempalace_eval.py"
FIXTURE = ROOT / "tests" / "fixtures" / "mempalace_causal_eval.jsonl"


def load_eval():
    spec = importlib.util.spec_from_file_location("a9_mempalace_eval_test", EVAL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MempalaceEvalTests(unittest.TestCase):
    def test_eval_fixture_scores_current_stale_and_causal_labels(self):
        mod = load_eval()
        result = mod.run_eval(FIXTURE)

        self.assertEqual(result["schema"], "a9.mempalace_causal_eval.v1")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["sample_count"], 12)
        self.assertEqual(result["micro"]["precision"], 1.0)
        self.assertEqual(result["micro"]["recall"], 1.0)
        self.assertEqual(result["wrongbook_candidates"], [])
        self.assertGreaterEqual(result["compiler"]["current_facts"], 8)
        self.assertGreaterEqual(result["compiler"]["stale_branches"], 4)
        self.assertGreaterEqual(result["compiler"]["causal_changes"], 3)

    def test_generate_candidates_keeps_source_refs_and_requires_review(self):
        mod = load_eval()
        rows = [
            {
                "schema": "a9.mempalace.drawer.v1",
                "drawer_id": "d1",
                "role": "assistant",
                "event_kind": "message",
                "timestamp": "2026-06-16T00:00:00Z",
                "source_ref": "session.jsonl:10",
                "source_sha256": "sourcehash",
                "content_hash": "hash1",
                "content": "因为页面监控旧路线已过期，所以当前主线变成 supervisor runtime。",
            },
            {
                "schema": "a9.mempalace.drawer.v1",
                "drawer_id": "d2",
                "role": "tool",
                "event_kind": "tool_output",
                "timestamp": "2026-06-16T00:00:01Z",
                "source_ref": "session.jsonl:11",
                "source_sha256": "sourcehash",
                "content_hash": "hash2",
                "content": "当前 主线 过期",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            drawers = Path(tmp) / "drawers.jsonl"
            drawers.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            result = mod.generate_eval_candidates(drawers, limit=5)

        self.assertEqual(result["schema"], "a9.mempalace_causal_eval_candidates.v1")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["candidate_count"], 1)
        candidate = result["candidates"][0]
        self.assertTrue(candidate["review_required"])
        self.assertEqual(candidate["source_ref"], "session.jsonl:10")
        self.assertEqual(candidate["source_sha256"], "sourcehash")
        self.assertTrue(candidate["suggested_expected"]["stale"])
        self.assertTrue(candidate["suggested_expected"]["causal"])
        self.assertIn("fixture_line", candidate)


if __name__ == "__main__":
    unittest.main()
