#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROVIDER = ROOT / "scripts" / "a9_mempalace_provider.py"


def load_provider():
    spec = importlib.util.spec_from_file_location("a9_mempalace_provider_test", PROVIDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
        {
            "schema": "a9.mempalace.drawer.v1",
            "drawer_id": "d4",
            "session_id": "s1",
            "role": "user",
            "event_kind": "message",
            "timestamp": "2026-01-01T00:00:03Z",
            "source_ref": "session.jsonl:13",
            "source_sha256": "sourcehash",
            "content_hash": "hash4",
            "content": "# AGENTS.md instructions for /root/a9\n<INSTRUCTIONS>recall truth</INSTRUCTIONS>\n<environment_context>x</environment_context>",
        },
        {
            "schema": "a9.mempalace.drawer.v1",
            "drawer_id": "d5",
            "session_id": "s1",
            "role": "assistant",
            "event_kind": "message",
            "timestamp": "2026-01-01T00:00:04Z",
            "source_ref": "session.jsonl:14",
            "source_sha256": "sourcehash",
            "content_hash": "hash5",
            "content": "旧页面监控路线已过期，因为当前主线变成 supervisor runtime -> MemPalace recall protocol。",
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
            self.assertEqual(payload["fallback_drawers"]["drawer_count"], 5)
            self.assertEqual(payload["fallback_drawers"]["roles"]["user"], 2)

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
            self.assertNotIn("AGENTS.md instructions", payload["recall"][0]["content"])

    def test_recall_packet_separates_search_hydration_and_fallback_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            drawers = Path(tmp) / "drawers.jsonl"
            write_drawers(drawers)
            result = subprocess.run(
                [
                    str(PROVIDER),
                    "--drawers",
                    str(drawers),
                    "--native-mode",
                    "fallback",
                    "recall",
                    "session governance",
                    "--limit",
                    "2",
                    "--hydrate",
                    "1",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema"], "a9.mempalace_recall_packet.v1")
            self.assertEqual(payload["truth_policy"], "recall_not_truth")
            self.assertIn("drawer_id hydration", payload["official_protocol"])
            self.assertEqual(payload["search_hits"], [])
            self.assertEqual(payload["hydrated_drawers"], [])
            self.assertEqual(payload["fallback_evidence_refs"][0]["source_ref"], "session.jsonl:10")
            self.assertEqual(payload["fallback_recall"][0]["drawer_id"], "d1")

    def test_causal_compile_outputs_candidates_and_role_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            drawers = Path(tmp) / "drawers.jsonl"
            write_drawers(drawers)
            result = subprocess.run(
                [
                    str(PROVIDER),
                    "--drawers",
                    str(drawers),
                    "--native-mode",
                    "fallback",
                    "causal-compile",
                    "当前 主线 过期 因为 supervisor",
                    "--limit",
                    "4",
                    "--hydrate",
                    "0",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema"], "a9.causal_memory_packet.v1")
            self.assertEqual(payload["truth_policy"], "candidate_memory_not_truth")
            self.assertTrue(payload["kg_candidates"]["current_facts"])
            self.assertTrue(payload["kg_candidates"]["stale_branches"])
            self.assertTrue(payload["kg_candidates"]["causal_changes"])
            self.assertEqual(payload["kg_candidates"]["stale_branches"][0]["kg_action"], "invalidate_candidate")
            self.assertIn("monitor", payload["role_packets"])
            self.assertIn("must_include", payload["next_task_memory"])
            self.assertGreaterEqual(payload["recall_packet"]["fallback_evidence_ref_count"], 1)

    def test_causal_commit_dry_run_requires_approval_and_plans_kg_diary(self):
        mod = load_provider()
        packet = {
            "schema": "a9.causal_memory_packet.v1",
            "kg_candidates": {
                "current_facts": [
                    {
                        "text": "A9 current mainline is supervisor runtime.",
                        "valid_from": "2026-01-01T00:00:00Z",
                        "source_drawer_id": "d1",
                        "evidence_ref": {"drawer_id": "d1", "source_ref": "session.jsonl:10"},
                    }
                ],
                "stale_branches": [
                    {
                        "text": "Page monitoring is stale.",
                        "valid_from": "2026-01-01T00:00:00Z",
                        "source_drawer_id": "d2",
                        "evidence_ref": {"drawer_id": "d2", "source_ref": "session.jsonl:11"},
                    }
                ],
                "causal_changes": [
                    {
                        "change": "page monitor -> supervisor runtime because control is stronger",
                        "valid_from": "2026-01-01T00:00:00Z",
                        "evidence_ref": {"drawer_id": "d3", "source_ref": "session.jsonl:12"},
                    }
                ],
            },
            "role_packets": {
                "monitor": {
                    "entries": [
                        {
                            "kind": "causal_change",
                            "text": "page monitor -> supervisor runtime",
                            "evidence_ref": {"drawer_id": "d3"},
                        }
                    ]
                }
            },
        }

        invalid = mod.commit_causal_memory_packet(packet, approved_by="", approval_reason="", dry_run=True)
        self.assertEqual(invalid["status"], "invalid_request")

        result = mod.commit_causal_memory_packet(
            packet,
            approved_by="codex-monitor",
            approval_reason="bounded dry run",
            dry_run=True,
        )

        self.assertEqual(result["schema"], "a9.causal_memory_commit_result.v1")
        self.assertEqual(result["status"], "dry_run")
        operations = result["plan"]["operations"]
        self.assertEqual(result["plan"]["approved_by"], "codex-monitor")
        self.assertTrue(any(op["operation"] == "kg_add" and op["predicate"] == "has_current_fact" for op in operations))
        self.assertTrue(any(op["operation"] == "kg_add" and op["valid_to"] for op in operations))
        self.assertTrue(any(op["operation"] == "diary_write" and op["agent_name"] == "monitor" for op in operations))


if __name__ == "__main__":
    unittest.main()
