#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import importlib.util
import sys
from unittest import mock
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
        self.assertEqual(result["drift_check"]["status"], "pass")
        self.assertTrue(any(op["operation"] == "kg_add" and op["predicate"] == "has_current_fact" for op in operations))
        self.assertTrue(any(op["operation"] == "kg_add" and op["valid_to"] for op in operations))
        self.assertTrue(any(op["operation"] == "diary_write" and op["agent_name"] == "monitor" for op in operations))

    def test_causal_commit_blocks_conflicting_current_facts_before_write(self):
        mod = load_provider()
        packet = {
            "schema": "a9.causal_memory_packet.v1",
            "kg_candidates": {
                "current_facts": [
                    {
                        "text": "A9 current mainline is supervisor runtime.",
                        "valid_from": "2026-01-01T00:00:00Z",
                        "evidence_ref": {"drawer_id": "d1", "source_ref": "session.jsonl:10"},
                    }
                ],
                "stale_branches": [],
                "causal_changes": [],
            },
            "role_packets": {},
        }
        existing = [
            {
                "subject": "A9",
                "predicate": "has_current_fact",
                "object": "A9 current mainline is page monitor.",
                "valid_to": None,
                "current": True,
            }
        ]
        with mock.patch.object(mod, "query_current_kg_facts", return_value=existing), mock.patch.object(
            mod, "write_kg_operation"
        ) as write_kg:
            result = mod.commit_causal_memory_packet(
                packet,
                approved_by="codex-monitor",
                approval_reason="reviewed but conflicting",
                dry_run=False,
            )

        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["drift_check"]["status"], "review_required")
        self.assertEqual(result["drift_check"]["conflict_count"], 1)
        write_kg.assert_not_called()

    def test_causal_audit_reports_current_conflicts_and_invalidation_candidates(self):
        mod = load_provider()
        facts = [
            {
                "subject": "A9",
                "predicate": "has_current_fact",
                "object": "A9 current mainline is supervisor runtime.",
                "valid_to": None,
                "current": True,
            },
            {
                "subject": "A9",
                "predicate": "has_current_fact",
                "object": "A9 current mainline is page monitor.",
                "valid_to": None,
                "current": True,
            },
            {
                "subject": "A9",
                "predicate": "has_stale_branch",
                "object": "page monitor",
                "valid_to": "2026-01-01T00:00:00Z",
                "current": False,
            },
        ]
        with mock.patch.object(mod, "query_kg_facts", return_value=facts):
            result = mod.audit_causal_memory_state("A9")

        self.assertEqual(result["schema"], "a9.causal_memory_audit.v1")
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["conflict_count"], 1)
        self.assertEqual(result["expired_fact_count"], 1)
        self.assertEqual(result["invalidation_candidates"][0]["operation"], "kg_invalidate_candidate")
        self.assertTrue(result["invalidation_candidates"][0]["requires_monitor_decision"])

    def test_causal_repair_proposal_selects_stale_branch_without_mutation(self):
        mod = load_provider()
        audit_report = {
            "schema": "a9.causal_memory_audit.v1",
            "status": "review_required",
            "subject": "A9",
            "conflict_count": 1,
            "conflicts": [
                {
                    "subject": "A9",
                    "predicate": "has_current_fact",
                    "objects": [
                        "A9 current mainline is supervisor runtime.",
                        "A9 old page monitor route is stale.",
                    ],
                    "facts": [
                        {
                            "subject": "A9",
                            "predicate": "has_current_fact",
                            "object": "A9 current mainline is supervisor runtime.",
                            "valid_from": "2026-06-02T00:00:00Z",
                            "current": True,
                        },
                        {
                            "subject": "A9",
                            "predicate": "has_current_fact",
                            "object": "A9 old page monitor route is stale.",
                            "valid_from": "2026-05-01T00:00:00Z",
                            "current": True,
                        },
                    ],
                }
            ],
        }

        result = mod.propose_causal_memory_repairs(audit_report, subject="A9")

        self.assertEqual(result["schema"], "a9.causal_memory_repair_proposal.v1")
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["truth_policy"], "side_effect_free_repair_candidates_not_truth")
        self.assertEqual(result["proposal_count"], 1)
        self.assertEqual(len(result["invalidation_candidates"]), 1)
        candidate = result["invalidation_candidates"][0]
        self.assertEqual(candidate["operation"], "kg_invalidate_candidate")
        self.assertEqual(candidate["object"], "A9 old page monitor route is stale.")
        self.assertTrue(candidate["requires_monitor_decision"])
        self.assertTrue(candidate["auto_selectable"])
        self.assertIn("object_has_stale_signal", candidate["repair_reasons"])
        self.assertIn("older_than_newest_current_fact", candidate["repair_reasons"])

    def test_causal_commit_success_includes_post_commit_audit(self):
        mod = load_provider()
        packet = {
            "schema": "a9.causal_memory_packet.v1",
            "kg_candidates": {
                "current_facts": [
                    {
                        "text": "A9 current mainline is supervisor runtime.",
                        "valid_from": "2026-01-01T00:00:00Z",
                        "evidence_ref": {"drawer_id": "d1", "source_ref": "session.jsonl:10"},
                    }
                ],
                "stale_branches": [],
                "causal_changes": [],
            },
            "role_packets": {},
        }
        with mock.patch.object(mod, "query_current_kg_facts", return_value=[]), mock.patch.object(
            mod, "write_kg_operation", return_value={"status": "ok", "operation": "kg_add", "triple_id": "t1"}
        ), mock.patch.object(
            mod, "audit_causal_memory_state",
            return_value={"schema": "a9.causal_memory_audit.v1", "status": "pass"},
        ) as audit:
            result = mod.commit_causal_memory_packet(
                packet,
                approved_by="codex-monitor",
                approval_reason="approved current fact",
                dry_run=False,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["post_commit_audit"]["status"], "pass")
        audit.assert_called_once()

    def test_approved_invalidation_dry_run_requires_approval_and_plans_operations(self):
        mod = load_provider()
        candidates = [
            {
                "operation": "kg_invalidate_candidate",
                "subject": "A9",
                "predicate": "has_current_fact",
                "object": "A9 current mainline is page monitor.",
                "ended": "2026-06-01T00:00:00Z",
            }
        ]

        invalid = mod.apply_approved_invalidations(candidates, approved_by="", approval_reason="", dry_run=True)
        self.assertEqual(invalid["status"], "invalid_request")

        result = mod.apply_approved_invalidations(
            candidates,
            approved_by="codex-monitor",
            approval_reason="current fact superseded",
            dry_run=True,
        )

        self.assertEqual(result["schema"], "a9.causal_memory_invalidation_result.v1")
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["plan"]["operation_count"], 1)
        self.assertEqual(result["plan"]["operations"][0]["operation"], "kg_invalidate")

    def test_approved_invalidation_commit_calls_mempalace_invalidate_and_audits(self):
        mod = load_provider()
        candidates = [
            {
                "operation": "kg_invalidate_candidate",
                "subject": "A9",
                "predicate": "has_current_fact",
                "object": "A9 current mainline is page monitor.",
            }
        ]
        with mock.patch.object(
            mod,
            "write_kg_invalidate_operation",
            return_value={"status": "ok", "operation": "kg_invalidate"},
        ) as write_invalidate, mock.patch.object(
            mod,
            "audit_causal_memory_state",
            return_value={"schema": "a9.causal_memory_audit.v1", "status": "pass"},
        ) as audit:
            result = mod.apply_approved_invalidations(
                candidates,
                approved_by="codex-monitor",
                approval_reason="monitor selected stale branch",
                dry_run=False,
            )

        self.assertEqual(result["status"], "ok")
        write_invalidate.assert_called_once()
        audit.assert_called_once_with("A9", palace=mod.DEFAULT_PALACE)
        self.assertEqual(result["post_invalidation_audit"]["A9"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
