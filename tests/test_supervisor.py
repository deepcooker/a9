#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR_PATH = ROOT / "scripts" / "a9_supervisor.py"


def load_supervisor():
    spec = importlib.util.spec_from_file_location("a9_supervisor", SUPERVISOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SupervisorTests(unittest.TestCase):
    def test_parse_task_frontmatter(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            task_path = Path(tmp) / "sample.md"
            task_path.write_text(
                """---
id: "sample"
phase: "compare"
timeout_seconds: 12
idle_timeout_seconds: 3
max_attempts: 4
checks:
  - "python --version"
allowed_paths:
  - "scripts/"
  - "tests/*.py"
---
Do the work.
""",
                encoding="utf-8",
            )
            task = mod.parse_task(task_path)
        self.assertEqual(task.task_id, "sample")
        self.assertEqual(task.phase, "compare")
        self.assertEqual(task.timeout_seconds, 12)
        self.assertEqual(task.idle_timeout_seconds, 3)
        self.assertEqual(task.max_attempts, 4)
        self.assertEqual(task.checks, ["python --version"])
        self.assertEqual(task.allowed_paths, ["scripts/", "tests/*.py"])
        self.assertEqual(task.prompt, "Do the work.")

    def test_aider_style_compression_preserves_recent_tail_and_references(self):
        mod = load_supervisor()
        messages = []
        for index in range(18):
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"# Step {index}\n"
                        f"- touched scripts/module_{index}.py\n"
                        f"- def function_{index} changed\n"
                        f"- status pass\n"
                    )
                    * 6,
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": f"Assistant detail {index}\n- tests/test_{index}.py passed\n" * 6,
                }
            )
        messages.append({"role": "user", "content": "RECENT_SENTINEL keep this exact tail detail"})

        compressed = mod.compress_messages_aider_style(messages, 700)
        rendered = mod.render_messages(compressed)

        self.assertLessEqual(mod.approx_token_count(rendered), 700)
        self.assertIn("RECENT_SENTINEL keep this exact tail detail", rendered)
        self.assertIn("scripts/module_0.py", rendered)
        self.assertIn("tests/test_0.py", rendered)
        self.assertLess(len(rendered), len(mod.render_messages(messages)))

    def test_context_compression_removes_noise_and_dedupes(self):
        mod = load_supervisor()
        messages = [
            {
                "role": "user",
                "content": "\n".join(
                    [
                        "mysql: [Warning] Using a password on the command line interface can be insecure.",
                        "....",
                        "Ran 4 tests in 1.234s",
                        "OK",
                        "- status pass",
                        "- status pass",
                        "- touched scripts/noise_filter.py",
                        "- touched scripts/noise_filter.py",
                        "RECENT_NOISE_SENTINEL keep this",
                    ]
                ),
            }
        ]

        rendered = mod.render_messages(mod.compress_messages_aider_style(messages, 120))

        self.assertNotIn("mysql: [Warning]", rendered)
        self.assertNotIn("Ran 4 tests", rendered)
        self.assertNotIn("\nOK", rendered)
        self.assertEqual(rendered.count("- status pass"), 1)
        self.assertEqual(rendered.count("scripts/noise_filter.py"), 1)
        self.assertIn("RECENT_NOISE_SENTINEL keep this", rendered)

    def test_repo_map_is_ranked_bounded_and_excludes_vendor_noise(self):
        mod = load_supervisor()
        repo_map, meta = mod.build_repo_map("change a9_supervisor context repo map tests", 450)

        self.assertLessEqual(mod.approx_token_count(repo_map), 450)
        self.assertIn("scripts/a9_supervisor.py", repo_map)
        self.assertIn("tests/test_supervisor.py", repo_map)
        self.assertNotIn("vendor-src/", repo_map)
        self.assertGreater(meta["included_files"], 0)
        self.assertEqual(meta["strategy"], "aider_ranked_symbol_repo_map")

    def test_codex_style_event_summary_preserves_tool_meta_signal(self):
        mod = load_supervisor()
        event = {
            "type": "item.completed",
            "item": {
                "id": "mcp-1",
                "type": "mcp_tool_call",
                "server": "search service",
                "tool": "web_run",
                "status": "completed",
                "duration_ms": 42,
                "result": {"_meta": {"raw_messages": [{"ref_id": "turn0search0"}]}},
            },
        }

        summary = mod.summarize_thread_event(event)

        self.assertEqual(summary["event_type"], "item.completed")
        self.assertEqual(summary["item_type"], "mcp_tool_call")
        self.assertEqual(summary["tool"], "web_run")
        self.assertTrue(summary["has_meta"])

    def test_compact_guard_summary_indexes_full_guard_evidence(self):
        mod = load_supervisor()
        summary = {
            "patch_guard": {
                "status": "pass",
                "return_code": 0,
                "kind": "unified_diff",
                "touched_files": ["scripts/a9_supervisor.py"],
                "findings": [{"level": "info"}],
                "output_path": "/tmp/patch_guard.json",
                "large_raw_field": "not copied",
            },
            "scope_guard": {
                "status": "fail",
                "return_code": 1,
                "changed_files": ["secret.env"],
                "allowed_paths": ["scripts/"],
                "findings": [{"level": "error"}, {"level": "error"}],
                "output_path": "/tmp/scope_guard.json",
            },
        }

        guards = mod.compact_guard_summary(summary)

        self.assertEqual(guards["patch_guard"]["status"], "pass")
        self.assertEqual(guards["patch_guard"]["findings_count"], 1)
        self.assertEqual(guards["patch_guard"]["touched_files"], ["scripts/a9_supervisor.py"])
        self.assertEqual(guards["scope_guard"]["status"], "fail")
        self.assertEqual(guards["scope_guard"]["findings_count"], 2)
        self.assertEqual(guards["scope_guard"]["changed_files"], ["secret.env"])
        self.assertNotIn("large_raw_field", guards["patch_guard"])

    def test_redis_session_payload_keeps_state_by_reference(self):
        mod = load_supervisor()
        task = mod.Task(path=Path("task.md"), task_id="redis-payload", prompt="demo")
        summary = {
            "status": "pass",
            "finished_at": "2026-05-21T00:00:00+00:00",
            "run_dir": "/tmp/a9-run",
            "evidence_path": "/tmp/a9-run/evidence.jsonl",
            "deep_marks_path": "/tmp/a9-run/deep_marks.jsonl",
            "patch_guard": {"status": "pass", "findings": []},
            "scope_guard": {"status": "pass", "findings": []},
        }
        state = {
            "checkpoint_id": "checkpoint-1",
            "deep_mark_count": 20000,
            "channels": {
                "deep_marks": [f"mark-{index}" for index in range(20000)],
                "checks": ["check-1"],
            },
        }

        payload = mod.redis_session_payload(task, summary, state, evidence_count=12)

        self.assertNotIn("state", payload)
        self.assertEqual(payload["state_path"], "/tmp/a9-run/state.json")
        self.assertEqual(payload["channel_counts"]["deep_marks"], 20000)
        self.assertEqual(payload["deep_mark_count"], 20000)
        self.assertLess(len(mod.json_compact(payload)), 2000)

    def test_compact_context_pressure_indexes_token_budget_metadata(self):
        mod = load_supervisor()
        summary = {
            "worker": {
                "prompt_approx_tokens": 900,
                "prompt_budget_tokens": 1000,
                "prompt_section_budgets": {"repo_map": 250},
                "previous_context_path": "/tmp/context.md",
                "previous_context_compression": {
                    "strategy": "aider_tail_preserving_summary",
                    "original_tokens": 1200,
                    "compressed_tokens": 300,
                },
                "repo_map": {
                    "strategy": "aider_ranked_symbol_repo_map",
                    "approx_tokens": 220,
                    "budget_tokens": 250,
                },
                "prompt": "must not be copied",
            }
        }

        pressure = mod.compact_context_pressure(summary)

        self.assertEqual(pressure["prompt_approx_tokens"], 900)
        self.assertEqual(pressure["prompt_budget_tokens"], 1000)
        self.assertEqual(pressure["budget_ratio"], 0.9)
        self.assertEqual(pressure["remaining_tokens"], 100)
        self.assertFalse(pressure["over_budget"])
        self.assertEqual(pressure["repo_map"]["approx_tokens"], 220)
        self.assertNotIn("prompt", pressure)

    def test_supervisor_fake_worker_end_to_end(self):
        env = os.environ.copy()
        env["A9_SUPERVISOR_WORKER_CMD"] = (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "import json\n"
            "print(json.dumps({'type':'fake.start'}))\n"
            "print(json.dumps({'type':'thread.started','thread_id':'fake-thread'}))\n"
            "print(json.dumps({'type':'item.completed','item':{'id':'cmd-1','type':'command_execution','command':'echo ok','status':'completed','exit_code':0,'aggregated_output':'ok'}}))\n"
            "Path('worker-output.txt').write_text('done\\n')\n"
            "Path('{run_dir}/final.md').write_text('ok\\n')\n"
            "print(json.dumps({'type':'fake.done'}))\n"
            "PY"
        )
        task_id = "selftest-supervisor"
        queue_path = ROOT / ".a9" / "tasks" / "queue" / f"{task_id}.md"
        done_path = ROOT / ".a9" / "tasks" / "done" / f"{task_id}.json"
        queue_dir = ROOT / ".a9" / "tasks" / "queue"

        with tempfile.TemporaryDirectory() as held_tmp:
            held_dir = Path(held_tmp)
            subprocess.run([str(SUPERVISOR_PATH), "init"], cwd=ROOT, check=True)
            held_paths = []
            for path in queue_dir.glob("*.md"):
                held_path = held_dir / path.name
                shutil.move(str(path), str(held_path))
                held_paths.append((held_path, path))
            try:
                if done_path.exists():
                    done_path.unlink()
                subprocess.run(
                    [
                        str(SUPERVISOR_PATH),
                        "enqueue",
                        task_id,
                        "fake task",
                        "--check",
                        "test -f worker-output.txt",
                        "--allow-path",
                        "worker-output.txt",
                        "--timeout-seconds",
                        "60",
                        "--idle-timeout-seconds",
                        "20",
                        "--max-attempts",
                        "1",
                    ],
                    cwd=ROOT,
                    check=True,
                )
                subprocess.run([str(SUPERVISOR_PATH), "run-one"], cwd=ROOT, check=True, env=env)
                data = json.loads(done_path.read_text(encoding="utf-8"))
            finally:
                queue_path.unlink(missing_ok=True)
                for path in queue_dir.glob("auto-*-selftest-supervisor-*.md"):
                    path.unlink()
                for held_path, original_path in held_paths:
                    if held_path.exists() and not original_path.exists():
                        shutil.move(str(held_path), str(original_path))
        self.assertEqual(data["status"], "pass")
        self.assertEqual(data["phase"], "implement")
        self.assertGreater(data["diff"]["diff_bytes"], 0)
        self.assertEqual(data["patch_guard"]["status"], "pass")
        self.assertEqual(data["guard_summary"]["patch_guard"]["status"], "pass")
        self.assertIn("findings_count", data["guard_summary"]["patch_guard"])
        self.assertEqual(
            data["context_pressure"]["prompt_budget_tokens"],
            data["worker"]["prompt_budget_tokens"],
        )
        self.assertTrue(Path(data["patch_guard"]["output_path"]).exists())
        self.assertEqual(data["scope_guard"]["status"], "pass")
        self.assertEqual(data["guard_summary"]["scope_guard"]["status"], "pass")
        self.assertEqual(data["scope_guard"]["allowed_paths"], ["worker-output.txt"])
        self.assertTrue(Path(data["scope_guard"]["output_path"]).exists())
        self.assertIn("persistence", data)
        evidence_path = Path(data["evidence_path"])
        state_path = Path(data["state_path"])
        deep_marks_path = Path(data["deep_marks_path"])
        event_summaries_path = Path(data["worker"]["event_summaries_path"])
        self.assertTrue(evidence_path.exists())
        self.assertTrue(state_path.exists())
        self.assertTrue(deep_marks_path.exists())
        self.assertTrue(event_summaries_path.exists())

        evidence = [
            json.loads(line)
            for line in evidence_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        kinds = {item["kind"] for item in evidence}
        self.assertIn("prompt", kinds)
        self.assertIn("events", kinds)
        self.assertIn("event_summary", kinds)
        self.assertIn("patch", kinds)
        self.assertIn("patch_guard", kinds)
        self.assertIn("scope_guard", kinds)
        self.assertIn("check_log", kinds)
        self.assertIn("context", kinds)
        self.assertTrue(all(item["sha256"] for item in evidence))

        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["session_id"], task_id)
        self.assertEqual(state["status"], "pass")
        self.assertIn("parent_checkpoint_id", state)
        self.assertIn("repo_map", state)
        self.assertTrue(state["channels"]["event_summaries"])
        self.assertEqual(len(state["channels"]["patches"]), 2)
        self.assertEqual(len(state["channels"]["guards"]), 2)
        self.assertTrue(state["channels"]["checks"])
        self.assertTrue(state["channels"]["deep_marks"])
        self.assertGreater(state["deep_mark_count"], 0)
        self.assertEqual(len(state["evidence_ids"]), len(evidence))

        deep_marks = [
            json.loads(line)
            for line in deep_marks_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(all(item["session_id"] == task_id for item in deep_marks))
        mark_kinds = {item["kind"] for item in deep_marks}
        self.assertIn("check_result", mark_kinds)
        self.assertIn("changed_file", mark_kinds)
        self.assertIn("patch_guard_result", mark_kinds)
        self.assertIn("scope_guard_result", mark_kinds)

        event_summaries = [
            json.loads(line)
            for line in event_summaries_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(any(item.get("event_type") == "thread.started" for item in event_summaries))
        self.assertTrue(any(item.get("item_type") == "command_execution" for item in event_summaries))

        for backend in ("mysql", "redis"):
            status = data["persistence"][backend]
            if status["enabled"]:
                self.assertEqual(status["status"], "ok", status)

        for path in (ROOT / ".a9" / "tasks" / "queue").glob("auto-*-selftest-supervisor-*.md"):
            path.unlink()

    def test_previous_task_checkpoint_id_reads_done_state(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.QUEUE_DIR / "lineage-test.md",
            task_id="lineage-test",
            prompt="lineage",
        )
        run_dir = mod.RUNS_DIR / "lineage-test-run"
        run_dir.mkdir(parents=True, exist_ok=True)
        state_path = run_dir / "state.json"
        state_path.write_text(
            json.dumps({"checkpoint_id": "lineage-test:checkpoint:1"}),
            encoding="utf-8",
        )
        done_path = mod.DONE_DIR / "lineage-test.json"
        done_path.write_text(json.dumps({"state_path": str(state_path)}), encoding="utf-8")

        self.assertEqual(
            mod.previous_task_checkpoint_id(task),
            "lineage-test:checkpoint:1",
        )

    def test_failed_patch_guard_status_requires_repair(self):
        mod = load_supervisor()
        worker = {"timed_out": False, "idle_timed_out": False, "return_code": 0}
        diff = {"diff_bytes": 120}
        checks = [{"return_code": 0}]
        patch_guard = {
            "status": "fail",
            "findings": [{"level": "error", "message": "blocked path component: vendor-src"}],
        }

        self.assertEqual(mod.decide_status(worker, diff, checks, patch_guard), "needs-repair")

    def test_failed_scope_guard_status_requires_repair(self):
        mod = load_supervisor()
        worker = {"timed_out": False, "idle_timed_out": False, "return_code": 0}
        diff = {"diff_bytes": 120}
        checks = [{"return_code": 0}]
        patch_guard = {"status": "pass"}
        scope_guard = {
            "status": "fail",
            "findings": [{"level": "error", "message": "changed file is outside allowed_paths"}],
        }

        self.assertEqual(
            mod.decide_status(worker, diff, checks, patch_guard, scope_guard),
            "needs-repair",
        )

    def test_validate_captured_diff_records_patch_guard_json(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            run_dir = Path(tmp) / "run"
            root.mkdir()
            run_dir.mkdir()
            diff_path = run_dir / "patch.diff"
            diff_path.write_text(
                """diff --git a/demo.txt b/demo.txt
new file mode 100644
index 0000000..3e75765
--- /dev/null
+++ b/demo.txt
@@ -0,0 +1 @@
+hello
""",
                encoding="utf-8",
            )
            result = mod.validate_captured_diff(
                {"diff_path": str(diff_path), "diff_bytes": diff_path.stat().st_size},
                root,
                run_dir,
            )
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["return_code"], 0)
            self.assertTrue(Path(result["output_path"]).exists())

    def test_validate_scope_records_scope_guard_json(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            diff_path = run_dir / "patch.diff"
            diff_path.write_text(
                """diff --git a/scripts/demo.py b/scripts/demo.py
new file mode 100644
index 0000000..3e75765
--- /dev/null
+++ b/scripts/demo.py
@@ -0,0 +1 @@
+hello
""",
                encoding="utf-8",
            )
            task = mod.Task(
                path=Path("demo.md"),
                task_id="demo",
                prompt="demo",
                allowed_paths=["scripts/"],
            )
            result = mod.validate_scope(
                {"diff_path": str(diff_path), "diff_bytes": diff_path.stat().st_size},
                task,
                run_dir,
            )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["return_code"], 0)
            self.assertEqual(result["changed_files"], ["scripts/demo.py"])
            self.assertTrue(Path(result["output_path"]).exists())

    def test_schedule_next_task_creates_copy_pipeline_followup_with_progress(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "auto-source.md",
            task_id="auto-source",
            prompt="copy the next mature mechanism",
            phase="reference_scan",
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "auto-source-run"),
            "context_path": str(mod.RUNS_DIR / "auto-source-run" / "context.md"),
        }

        next_path = mod.schedule_next_task(task, summary)
        self.assertIsNotNone(next_path)
        assert next_path is not None
        text = next_path.read_text(encoding="utf-8")
        self.assertIn('phase: "mechanism_extract"', text)
        self.assertIn("Continue A9 24-hour automation", text)
        self.assertIn("Copy pipeline phases", text)
        self.assertIn("vendor_import", text)
        self.assertIn("python3 -m unittest", text)

        progress = mod.service_progress(summary, next_path)
        self.assertEqual(progress["stage"], "auto-loop-mvp")
        self.assertTrue(progress["capabilities"]["auto_next_scheduler"])
        self.assertTrue(progress["capabilities"]["copy_pipeline_templates"])
        self.assertTrue(progress["auto_next_scheduled"])
        self.assertTrue(progress["capabilities"]["production_daemon_packaging"])
        self.assertTrue(progress["capabilities"]["patch_guard_evidence"])
        self.assertTrue(progress["capabilities"]["scope_guard_evidence"])
        self.assertEqual(progress["progress_percent"], 100.0)
        self.assertTrue(mod.PROGRESS_PATH.exists())

        next_path.unlink(missing_ok=True)

    def test_copy_pipeline_phase_order(self):
        mod = load_supervisor()

        self.assertEqual(mod.next_phase_for("pass", "reference_scan"), "mechanism_extract")
        self.assertEqual(mod.next_phase_for("pass", "mechanism_extract"), "vendor_import")
        self.assertEqual(mod.next_phase_for("pass", "vendor_import"), "implement")
        self.assertEqual(mod.next_phase_for("pass", "record"), "reference_scan")
        self.assertEqual(mod.next_phase_for("needs-repair", "implement"), "repair")
        self.assertEqual(mod.next_phase_for("needs-followup", "test"), "test")

    def test_worktree_branch_name_is_scoped_to_worktree_root(self):
        mod = load_supervisor()
        task_id = "branch-scope"
        branch_scope = mod.hashlib.sha256(str(mod.WORKTREES_DIR.resolve()).encode("utf-8")).hexdigest()[:10]
        expected_branch = f"a9-supervisor/{task_id}-1-{branch_scope}"

        self.assertIn(branch_scope, expected_branch)


if __name__ == "__main__":
    unittest.main()
