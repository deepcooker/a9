#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
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
        self.assertEqual(result["sample_count"], 5)
        self.assertEqual(result["micro"]["precision"], 1.0)
        self.assertEqual(result["micro"]["recall"], 1.0)
        self.assertEqual(result["wrongbook_candidates"], [])
        self.assertGreaterEqual(result["compiler"]["current_facts"], 3)
        self.assertGreaterEqual(result["compiler"]["stale_branches"], 1)
        self.assertGreaterEqual(result["compiler"]["causal_changes"], 1)


if __name__ == "__main__":
    unittest.main()
