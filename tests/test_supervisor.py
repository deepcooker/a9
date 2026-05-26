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

    def test_default_worker_uses_stable_codex_model_and_can_be_overridden(self):
        mod = load_supervisor()
        task = mod.Task(path=Path("task.md"), task_id="model-test", prompt="demo")
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final_path = run_dir / "final.md"
            old_model = os.environ.pop("A9_SUPERVISOR_MODEL", None)
            old_override = os.environ.pop("A9_SUPERVISOR_WORKER_CMD", None)
            try:
                cmd = mod.build_worker_cmd(task, Path("/tmp/worktree"), run_dir, final_path, "prompt")
                self.assertEqual(cmd[0], "env")
                self.assertIn(f"CODEX_HOME={mod.WORKER_CODEX_HOME}", cmd)
                self.assertIn(f"HOME={mod.WORKER_CODEX_HOME}", cmd)
                self.assertIn(f"TMPDIR={mod.WORKER_TMP_DIR}", cmd)
                self.assertIn("--ephemeral", cmd)
                self.assertIn("--model", cmd)
                self.assertEqual(cmd[cmd.index("--model") + 1], "gpt-5.3-codex")

                os.environ["A9_SUPERVISOR_MODEL"] = "gpt-5.5"
                cmd = mod.build_worker_cmd(task, Path("/tmp/worktree"), run_dir, final_path, "prompt")
                self.assertEqual(cmd[cmd.index("--model") + 1], "gpt-5.5")
            finally:
                if old_model is not None:
                    os.environ["A9_SUPERVISOR_MODEL"] = old_model
                else:
                    os.environ.pop("A9_SUPERVISOR_MODEL", None)
                if old_override is not None:
                    os.environ["A9_SUPERVISOR_WORKER_CMD"] = old_override
                else:
                    os.environ.pop("A9_SUPERVISOR_WORKER_CMD", None)

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

    def test_hydrate_worker_reference_slices_copies_bounded_references(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_root = tmp_path / "source"
            worktree = tmp_path / "worktree"
            lobster = source_root / "reference-projects" / "openclaw" / "extensions" / "lobster" / "src"
            lobster.mkdir(parents=True)
            (lobster / "lobster-core.d.ts").write_text("type LobsterToolEnvelope = {}\n", encoding="utf-8")
            vendor = source_root / "vendor-src"
            vendor.mkdir()
            (vendor / "manifest.json").write_text("{}\n", encoding="utf-8")
            worktree.mkdir()

            original_root = mod.ROOT
            try:
                mod.ROOT = source_root
                copied = mod.hydrate_worker_reference_slices(worktree)
            finally:
                mod.ROOT = original_root

            self.assertIn("reference-projects/openclaw/extensions/lobster", copied)
            self.assertIn("vendor-src", copied)
            self.assertTrue(
                (
                    worktree
                    / "reference-projects"
                    / "openclaw"
                    / "extensions"
                    / "lobster"
                    / "src"
                    / "lobster-core.d.ts"
                ).exists()
            )
            self.assertFalse((worktree / "reference-projects" / "openclaw" / ".git").exists())

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

    def test_turn_completed_summary_and_aggregate_token_usage(self):
        mod = load_supervisor()
        summary = mod.summarize_thread_event(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 60,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 7,
                },
            }
        )

        self.assertEqual(summary["input_tokens"], 100)
        self.assertEqual(summary["cached_input_tokens"], 60)
        self.assertEqual(summary["output_tokens"], 20)
        self.assertEqual(summary["reasoning_output_tokens"], 7)
        totals = mod.aggregate_token_usage([summary, {"usage": {"input_tokens": 10, "output_tokens": 2}}])
        self.assertEqual(totals["input_tokens"], 110)
        self.assertEqual(totals["cached_input_tokens"], 60)
        self.assertEqual(totals["uncached_input_tokens"], 50)
        self.assertEqual(totals["output_tokens"], 22)
        self.assertEqual(totals["reasoning_output_tokens"], 7)
        self.assertEqual(totals["total_tokens"], 139)

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
            "worker": {"actual_token_usage": {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 10}},
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
        self.assertEqual(payload["actual_token_usage"]["cached_input_tokens"], 80)
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
        self.assertEqual(data["policy_attestation"]["status"], "pass")
        self.assertTrue(Path(data["policy_attestation"]["output_path"]).exists())
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
        self.assertIn("patch_apply", kinds)
        self.assertIn("patch", kinds)
        self.assertIn("patch_guard", kinds)
        self.assertIn("scope_guard", kinds)
        self.assertIn("policy_attestation", kinds)
        self.assertIn("check_log", kinds)
        self.assertIn("context", kinds)
        self.assertTrue(all(item["sha256"] for item in evidence))

        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["session_id"], task_id)
        self.assertEqual(state["status"], "pass")
        self.assertIn("parent_checkpoint_id", state)
        self.assertIn("repo_map", state)
        self.assertTrue(state["channels"]["event_summaries"])
        self.assertEqual(len(state["channels"]["patches"]), 3)
        self.assertEqual(len(state["channels"]["guards"]), 2)
        self.assertTrue(state["channels"]["policy_attestations"])
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

    def test_supervisor_applies_worker_search_replace_final_message(self):
        env = os.environ.copy()
        env["A9_SUPERVISOR_WORKER_CMD"] = (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "import json\n"
            "print(json.dumps({'type':'fake.start'}))\n"
            "Path('{run_dir}/final.md').write_text('README.md\\n<<<<<<< SEARCH\\n# a9\\n=======\\n# a9 deterministic apply\\n>>>>>>> REPLACE\\n')\n"
            "print(json.dumps({'type':'fake.done'}))\n"
            "PY"
        )
        task_id = "selftest-search-replace-apply"
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
                        "fake search replace task",
                        "--check",
                        "grep -q 'deterministic apply' README.md",
                        "--allow-path",
                        "README.md",
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
                for path in queue_dir.glob("auto-*-selftest-search-replace-apply-*.md"):
                    path.unlink()
                for held_path, original_path in held_paths:
                    if held_path.exists() and not original_path.exists():
                        shutil.move(str(held_path), str(original_path))

        self.assertEqual(data["status"], "pass")
        self.assertEqual(data["patch_apply"]["status"], "pass")
        self.assertEqual(data["patch_apply"]["applied_count"], 1)
        self.assertEqual(data["patch_guard"]["status"], "pass")
        evidence = [
            json.loads(line)
            for line in Path(data["evidence_path"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertIn("patch_apply", {item["kind"] for item in evidence})

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

    def test_worker_envelope_required_missing_requires_repair(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text("plain final answer\n", encoding="utf-8")
            task = mod.Task(
                path=Path("task.md"),
                task_id="strict-envelope",
                prompt="strict_worker_envelope: true\nDo work.",
            )
            worker = {"final_path": str(final), "timed_out": False, "idle_timed_out": False, "return_code": 0}

            envelope = mod.validate_worker_envelope(task, worker, run_dir)
            status = mod.decide_status(worker, {"diff_bytes": 120}, [], worker_envelope=envelope)

        self.assertEqual(envelope["status"], "fail")
        self.assertEqual(status, "needs-repair")

    def test_worker_envelope_ok_passes_when_required(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":1,"ok":true,"status":"ok","output":[]}\n',
                encoding="utf-8",
            )
            task = mod.Task(
                path=Path("task.md"),
                task_id="strict-envelope",
                prompt="strict_worker_envelope: true\nDo work.",
            )
            worker = {"final_path": str(final), "timed_out": False, "idle_timed_out": False, "return_code": 0}

            envelope = mod.validate_worker_envelope(task, worker, run_dir)
            status = mod.decide_status(worker, {"diff_bytes": 120}, [], worker_envelope=envelope)

        self.assertEqual(envelope["status"], "pass")
        self.assertEqual(status, "pass")

    def test_worker_envelope_ok_allows_object_output(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":1,"ok":true,"status":"ok","output":{"changed_files":[]}}\n',
                encoding="utf-8",
            )
            task = mod.Task(
                path=Path("task.md"),
                task_id="strict-envelope",
                prompt="strict_worker_envelope: true\nDo work.",
            )
            worker = {"final_path": str(final), "timed_out": False, "idle_timed_out": False, "return_code": 0}

            envelope = mod.validate_worker_envelope(task, worker, run_dir)

        self.assertEqual(envelope["status"], "pass")

    def test_no_diff_diagnostic_task_can_pass(self):
        mod = load_supervisor()
        worker = {"timed_out": False, "idle_timed_out": False, "budget_stopped": False, "return_code": 0}
        envelope = {"status": "pass"}

        status = mod.decide_status(
            worker,
            {"diff_bytes": 0},
            [{"command": "true", "return_code": 0}],
            worker_envelope=envelope,
            allow_no_diff=True,
        )

        self.assertEqual(status, "pass")

    def test_no_diff_still_needs_followup_by_default(self):
        mod = load_supervisor()
        worker = {"timed_out": False, "idle_timed_out": False, "budget_stopped": False, "return_code": 0}

        status = mod.decide_status(worker, {"diff_bytes": 0}, [{"command": "true", "return_code": 0}])

        self.assertEqual(status, "needs-followup")

    def test_task_allows_no_diff_from_explicit_field_and_smoke_text(self):
        mod = load_supervisor()
        explicit = mod.Task(
            path=Path("task.md"),
            task_id="diagnostic",
            prompt="strict_worker_envelope: true\nexpected_file_changes: false\nTask: inspect only.",
        )
        textual = mod.Task(
            path=Path("task.md"),
            task_id="smoke",
            prompt="Task: smoke. Do not modify files. Return JSON only.",
        )
        implementation = mod.Task(
            path=Path("task.md"),
            task_id="implementation",
            prompt="Task: implement the next feature.",
        )

        self.assertTrue(mod.task_allows_no_diff(explicit))
        self.assertTrue(mod.task_allows_no_diff(textual))
        self.assertFalse(mod.task_allows_no_diff(implementation))

    def test_worker_envelope_needs_approval_becomes_status(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                json.dumps(
                    {
                        "protocolVersion": 1,
                        "ok": True,
                        "status": "needs_approval",
                        "output": [],
                        "requiresApproval": {
                            "type": "approval_request",
                            "prompt": "Approve next step?",
                            "approvalId": "approval-1",
                        },
                    }
                ),
                encoding="utf-8",
            )
            task = mod.Task(
                path=Path("task.md"),
                task_id="strict-envelope",
                prompt="strict_worker_envelope: true\nDo work.",
            )
            worker = {"final_path": str(final), "timed_out": False, "idle_timed_out": False, "return_code": 0}

            envelope = mod.validate_worker_envelope(task, worker, run_dir)
            status = mod.decide_status(worker, {"diff_bytes": 120}, [], worker_envelope=envelope)

        self.assertEqual(envelope["status"], "needs-approval")
        self.assertEqual(status, "needs-approval")

    def test_policy_attestation_hashes_policy_workspace_and_findings(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            task = mod.Task(
                path=Path("task.md"),
                task_id="policy-test",
                prompt="strict_worker_envelope: true\nflow_id: flow-1",
                phase="implement",
                checks=["python3 -m unittest tests/test_supervisor.py"],
                allowed_paths=["scripts/"],
            )
            summary = {
                "status": "needs-repair",
                "diff": {"diff_path": str(run_dir / "patch.diff"), "diff_bytes": 12},
                "worker_envelope": {"status": "fail", "required": True, "findings": [{"message": "bad envelope"}]},
                "patch_apply": {"status": "skip", "applied_count": 0, "failed_count": 0, "findings": []},
                "patch_guard": {"status": "pass", "touched_files": ["scripts/a9_supervisor.py"], "findings": []},
                "scope_guard": {
                    "status": "fail",
                    "changed_files": ["secret.env"],
                    "allowed_paths": ["scripts/"],
                    "findings": [{"message": "outside scope"}],
                },
                "checks": [{"command": "false", "return_code": 1, "output_path": str(run_dir / "check.log")}],
                "git_governance": {"status": "rolled-back", "commit": "", "rolled_back": True, "findings": []},
            }

            attestation = mod.create_policy_attestation(task, run_dir, summary)
            payload = json.loads(Path(attestation["output_path"]).read_text(encoding="utf-8"))

        self.assertEqual(attestation["status"], "fail")
        self.assertEqual(payload["policy"]["hash"], attestation["policy_hash"])
        self.assertEqual(payload["workspace"]["hash"], attestation["workspace_hash"])
        self.assertEqual(payload["findingsHash"], attestation["findings_hash"])
        recomputed = mod.sha256_text(
            mod.stable_json(
                {
                    "ok": payload["ok"],
                    "policyHash": payload["policy"]["hash"],
                    "workspaceHash": payload["workspace"]["hash"],
                    "findingsHash": payload["findingsHash"],
                }
            )
        )
        self.assertEqual(payload["attestationHash"], recomputed)
        self.assertGreaterEqual(attestation["findings_count"], 3)

    def test_worker_budget_stop_is_retryable(self):
        mod = load_supervisor()
        worker = {
            "timed_out": False,
            "idle_timed_out": False,
            "budget_stopped": True,
            "return_code": -9,
        }
        diff = {"diff_bytes": 0}

        self.assertEqual(mod.decide_status(worker, diff, []), "retryable-worker-budget")

    def test_worker_network_error_is_classified_separately(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            event_summaries = Path(tmp) / "event_summaries.jsonl"
            event_summaries.write_text(
                json.dumps(
                    {
                        "item_type": "command_execution",
                        "output_preview": "Connection reset by peer\nReconnecting...",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            worker = {
                "timed_out": False,
                "idle_timed_out": False,
                "budget_stopped": False,
                "return_code": 1,
                "event_summaries_path": str(event_summaries),
            }

            failure = mod.classify_worker_failure(worker)
            status = mod.decide_status(worker, {"diff_bytes": 0}, [])

        self.assertEqual(failure["status"], "retryable-worker-network")
        self.assertEqual(status, "retryable-worker-network")

    def test_nonfatal_worker_stderr_does_not_override_success(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            stderr = Path(tmp) / "stderr.log"
            stderr.write_text("failed to connect to websocket: IO error: tls handshake eof\n", encoding="utf-8")
            worker = {
                "timed_out": False,
                "idle_timed_out": False,
                "budget_stopped": False,
                "return_code": 0,
                "stderr_path": str(stderr),
            }

            failure = mod.classify_worker_failure(worker)

        self.assertEqual(failure["status"], "")

    def test_worker_startup_error_is_classified_separately(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            stderr = Path(tmp) / "stderr.log"
            stderr.write_text("app-server initialization failed: permission denied\n", encoding="utf-8")
            worker = {
                "timed_out": False,
                "idle_timed_out": False,
                "budget_stopped": False,
                "return_code": 1,
                "stderr_path": str(stderr),
            }

            failure = mod.classify_worker_failure(worker)

        self.assertEqual(failure["status"], "retryable-worker-startup")

    def test_worker_broken_pipe_is_classified_separately(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / "final.md"
            final.write_text("tool failed with Broken pipe\n", encoding="utf-8")
            worker = {
                "timed_out": False,
                "idle_timed_out": False,
                "budget_stopped": False,
                "return_code": 1,
                "final_path": str(final),
            }

            failure = mod.classify_worker_failure(worker)

        self.assertEqual(failure["status"], "retryable-worker-broken-pipe")

    def test_blocked_worker_command_detects_nested_supervisor_and_codex(self):
        mod = load_supervisor()

        self.assertEqual(mod.blocked_worker_command("python3 scripts/a9_supervisor.py run-loop"), "a9_supervisor.py run-loop")
        self.assertEqual(mod.blocked_worker_command("codex exec --json prompt"), "codex exec")
        self.assertEqual(mod.blocked_worker_command("python3 -m unittest tests/test_service.py"), "")

    def test_repair_next_task_includes_patch_apply_hint(self):
        mod = load_supervisor()
        task = mod.Task(path=Path("task.md"), task_id="repair-hint", prompt="demo", phase="implement")
        summary = {
            "status": "needs-repair",
            "run_dir": "/tmp/run",
            "context_path": "/tmp/context.md",
            "git_governance": {
                "status": "rolled-back",
                "rolled_back": True,
            },
            "patch_apply": {
                "status": "fail",
                "partial_success": True,
                "applied_count": 1,
                "already_applied_count": 1,
                "success_count": 2,
                "failed_count": 1,
                "successful_blocks": [
                    {
                        "index": 1,
                        "path": "demo.py",
                        "mode": "already_applied",
                        "match_strategy": "already_applied",
                        "replace_matches": 1,
                    },
                    {
                        "index": 2,
                        "path": "other.py",
                        "mode": "replace",
                        "match_strategy": "exact",
                    },
                ],
                "failed_blocks": [
                    {
                        "index": 3,
                        "path": "bad.py",
                        "mode": "failed",
                        "match_strategy": "none",
                        "replace_matches": 0,
                    }
                ],
                "repair_hint": "# Partial SEARCH/REPLACE result\nDo not resend successful blocks\n## SearchReplaceNoExactMatch\n<<<<<<< SEARCH\nbad\n=======\nfixed\n>>>>>>> REPLACE",
            },
        }

        prompt = mod.next_task_prompt(task, summary, "repair")

        self.assertIn("Patch apply repair metadata", prompt)
        self.assertIn("already_applied_count: 1", prompt)
        self.assertIn("git_governance_status: rolled-back", prompt)
        self.assertIn("git_rolled_back: True", prompt)
        self.assertIn("inspect current file content before deciding whether to resend", prompt)
        self.assertIn("block 1: demo.py mode=already_applied", prompt)
        self.assertIn("block 2: other.py mode=replace", prompt)
        self.assertIn("block 3: bad.py mode=failed", prompt)
        self.assertIn("Partial SEARCH/REPLACE result", prompt)
        self.assertIn("Do not resend successful blocks", prompt)
        self.assertIn("SearchReplaceNoExactMatch", prompt)
        self.assertIn("<<<<<<< SEARCH", prompt)

    def test_repair_next_task_keeps_successful_blocks_when_not_rolled_back(self):
        mod = load_supervisor()
        task = mod.Task(path=Path("task.md"), task_id="repair-hint-retained", prompt="demo", phase="implement")
        summary = {
            "status": "needs-repair",
            "run_dir": "/tmp/run",
            "context_path": "/tmp/context.md",
            "git_governance": {
                "status": "operator-intervention",
                "rolled_back": False,
            },
            "patch_apply": {
                "status": "fail",
                "partial_success": True,
                "successful_blocks": [
                    {
                        "index": 1,
                        "path": "demo.py",
                        "mode": "replace",
                        "match_strategy": "exact",
                    }
                ],
                "failed_blocks": [],
                "repair_hint": "fix failed block",
            },
        }

        prompt = mod.next_task_prompt(task, summary, "repair")

        self.assertIn("git_rolled_back: False", prompt)
        self.assertIn("Successful blocks already handled; do not resend", prompt)
        self.assertIn("block 1: demo.py mode=replace", prompt)

    def test_git_governance_commits_passed_worker_diff(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            run_dir = Path(tmp) / "run"
            repo.mkdir()
            run_dir.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (repo / "demo.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True, stdout=subprocess.PIPE)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.email=test@example.invalid",
                    "-c",
                    "user.name=Test",
                    "commit",
                    "-m",
                    "base",
                ],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
            )
            (repo / "demo.txt").write_text("base\nchanged\n", encoding="utf-8")
            diff = mod.capture_diff(repo, run_dir)

            result = mod.apply_git_governance(
                repo,
                run_dir,
                mod.Task(path=Path("task.md"), task_id="git-pass", prompt="demo"),
                "pass",
                diff,
            )

            self.assertEqual(result["status"], "committed")
            self.assertTrue(result["commit"])
            self.assertTrue(Path(result["output_path"]).exists())
            self.assertEqual(subprocess.run(["git", "status", "--short"], cwd=repo, text=True, stdout=subprocess.PIPE).stdout, "")

    def test_git_governance_rolls_back_failed_worker_diff(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            run_dir = Path(tmp) / "run"
            repo.mkdir()
            run_dir.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (repo / "demo.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True, stdout=subprocess.PIPE)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.email=test@example.invalid",
                    "-c",
                    "user.name=Test",
                    "commit",
                    "-m",
                    "base",
                ],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
            )
            (repo / "demo.txt").write_text("bad\n", encoding="utf-8")
            (repo / "scratch.txt").write_text("remove me\n", encoding="utf-8")
            diff = mod.capture_diff(repo, run_dir)

            result = mod.apply_git_governance(
                repo,
                run_dir,
                mod.Task(path=Path("task.md"), task_id="git-fail", prompt="demo"),
                "needs-repair",
                diff,
            )

            self.assertEqual(result["status"], "rolled-back")
            self.assertTrue(result["rolled_back"])
            self.assertEqual((repo / "demo.txt").read_text(encoding="utf-8"), "base\n")
            self.assertFalse((repo / "scratch.txt").exists())
            self.assertEqual(subprocess.run(["git", "status", "--short"], cwd=repo, text=True, stdout=subprocess.PIPE).stdout, "")

    def test_reset_existing_worktree_returns_to_current_base(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (repo / "demo.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True, stdout=subprocess.PIPE)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.email=test@example.invalid",
                    "-c",
                    "user.name=Test",
                    "commit",
                    "-m",
                    "base",
                ],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
            )
            base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
            (repo / "demo.txt").write_text("committed worker snapshot\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True, stdout=subprocess.PIPE)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.email=test@example.invalid",
                    "-c",
                    "user.name=Test",
                    "commit",
                    "-m",
                    "worker snapshot",
                ],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
            )
            (repo / "scratch.txt").write_text("stale\n", encoding="utf-8")
            old_git_head = mod.git_head
            try:
                mod.git_head = lambda: base
                mod.reset_existing_worktree(repo)
            finally:
                mod.git_head = old_git_head

            self.assertEqual((repo / "demo.txt").read_text(encoding="utf-8"), "base\n")
            self.assertFalse((repo / "scratch.txt").exists())
            self.assertEqual(subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, stdout=subprocess.PIPE).stdout.strip(), base)

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
            allowed_paths=["scripts/a9_control_api.py", "tests/test_control_api.py"],
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
        self.assertIn("strict_worker_envelope", text)
        self.assertIn('protocolVersion":1', text)
        self.assertIn('  - "scripts/a9_control_api.py"', text)
        self.assertIn('max_attempts: 1', text)

        progress = mod.service_progress(summary, next_path)
        self.assertEqual(progress["stage"], "auto-loop-mvp")
        self.assertTrue(progress["capabilities"]["auto_next_scheduler"])
        self.assertTrue(progress["capabilities"]["copy_pipeline_templates"])
        self.assertTrue(progress["auto_next_scheduled"])
        self.assertTrue(progress["capabilities"]["production_daemon_packaging"])
        self.assertTrue(progress["capabilities"]["patch_guard_evidence"])
        self.assertTrue(progress["capabilities"]["scope_guard_evidence"])
        self.assertTrue(progress["capabilities"]["deterministic_search_replace_apply"])
        self.assertTrue(progress["capabilities"]["already_applied_detection"])
        self.assertTrue(progress["capabilities"]["rollback_aware_repair_prompt"])
        self.assertTrue(progress["capabilities"]["worker_event_budget_gate"])
        self.assertTrue(progress["capabilities"]["auto_loop_failure_circuit_breaker"])
        self.assertEqual(progress["capability_groups"]["governance"]["percent"], 100.0)
        self.assertEqual(progress["progress_percent"], 100.0)
        self.assertTrue(mod.PROGRESS_PATH.exists())

        next_path.unlink(missing_ok=True)

    def test_schedule_next_task_records_deterministically_without_record_worker(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            old_records = mod.RECORDS_DIR
            mod.RECORDS_DIR = Path(tmp) / "records"
            task = mod.Task(
                path=mod.DONE_DIR / "auto-test.md",
                task_id="auto-test",
                prompt="test the copied mechanism",
                phase="test",
                allowed_paths=["scripts/a9_control_api.py", "tests/test_control_api.py"],
            )
            summary = {
                "task_id": task.task_id,
                "status": "pass",
                "run_dir": "/tmp/run",
                "context_path": "/tmp/run/context.md",
                "evidence_path": "/tmp/run/evidence.jsonl",
                "worker_envelope": {
                    "status": "pass",
                    "envelope": {
                        "protocolVersion": 1,
                        "ok": True,
                        "status": "ok",
                        "output": {
                            "changed_files": ["scripts/a9_control_api.py"],
                            "copied_mechanisms": [{"mechanism": "redis stream replay"}],
                            "tests": [{"command": "python3 -m unittest tests/test_control_api.py", "result": "pass"}],
                            "next_slice": "continue communication governance",
                        },
                    },
                },
                "patch_apply": {"status": "skip"},
                "patch_guard": {"status": "pass"},
                "scope_guard": {"status": "pass"},
                "git_governance": {"status": "committed", "commit": "abc123", "rolled_back": False},
                "checks": [{"command": "python3 -m unittest tests/test_control_api.py", "return_code": 0}],
            }
            try:
                next_path = mod.schedule_next_task(task, summary)
                self.assertIsNotNone(next_path)
                assert next_path is not None
                text = next_path.read_text(encoding="utf-8")
                self.assertIn('phase: "reference_scan"', text)
                self.assertIn('  - "python3 -m py_compile scripts/a9_supervisor.py"', text)
                self.assertIn("Continue A9 24-hour automation", text)
                self.assertIn("expected_file_changes: false", text)
                self.assertIn("Do not `cat` full context", text)
                self.assertIn("deterministic_record_path", summary)
                record_path = Path(summary["deterministic_record_path"])
                self.assertIn(f"- record_path: {record_path}", text)
                record = json.loads(record_path.read_text(encoding="utf-8"))
                self.assertEqual(record["mode"], "deterministic_supervisor_record")
                self.assertEqual(record["task_id"], "auto-test")
                self.assertEqual(record["worker_output"]["next_slice"], "continue communication governance")
                self.assertEqual(record["git"]["commit"], "abc123")
            finally:
                mod.RECORDS_DIR = old_records
                if "next_path" in locals() and next_path is not None:
                    next_path.unlink(missing_ok=True)

    def test_auto_loop_guard_trips_after_consecutive_failures_and_resets_on_pass(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            old_path = mod.AUTO_LOOP_GUARD_PATH
            old_limit = os.environ.get("A9_AUTO_LOOP_FAILURE_LIMIT")
            mod.AUTO_LOOP_GUARD_PATH = Path(tmp) / "auto_loop_guard.json"
            os.environ["A9_AUTO_LOOP_FAILURE_LIMIT"] = "2"
            try:
                first = mod.update_auto_loop_guard(
                    {
                        "task_id": "task-1",
                        "run_dir": "/tmp/run-1",
                        "status": "retryable-worker-budget",
                        "worker_failure": {"status": "retryable-worker-budget"},
                    }
                )
                self.assertEqual(first["status"], "watching")
                self.assertFalse(mod.auto_loop_guard_blocks_next({"auto_loop_guard": first}))

                second = mod.update_auto_loop_guard(
                    {
                        "task_id": "task-2",
                        "run_dir": "/tmp/run-2",
                        "status": "needs-repair",
                    }
                )
                self.assertEqual(second["status"], "tripped")
                self.assertTrue(mod.auto_loop_guard_blocks_next({"auto_loop_guard": second}))

                reset = mod.update_auto_loop_guard(
                    {
                        "task_id": "task-3",
                        "run_dir": "/tmp/run-3",
                        "status": "pass",
                    }
                )
                self.assertEqual(reset["status"], "ok")
                self.assertEqual(reset["consecutive_failures"], 0)
            finally:
                mod.AUTO_LOOP_GUARD_PATH = old_path
                if old_limit is None:
                    os.environ.pop("A9_AUTO_LOOP_FAILURE_LIMIT", None)
                else:
                    os.environ["A9_AUTO_LOOP_FAILURE_LIMIT"] = old_limit

    def test_schedule_next_task_blocks_when_auto_loop_guard_tripped(self):
        mod = load_supervisor()
        task = mod.Task(
            path=mod.DONE_DIR / "auto-source.md",
            task_id="auto-source",
            prompt="copy the next mature mechanism",
            phase="reference_scan",
        )
        summary = {
            "task_id": task.task_id,
            "status": "needs-repair",
            "run_dir": str(mod.RUNS_DIR / "auto-source-run"),
            "context_path": str(mod.RUNS_DIR / "auto-source-run" / "context.md"),
            "auto_loop_guard": {
                "status": "tripped",
                "consecutive_failures": 2,
                "failure_limit": 2,
                "latest_failure": "needs-repair",
            },
        }

        self.assertIsNone(mod.schedule_next_task(task, summary))

    def test_session_refresh_prompt_parser_accepts_key_value_spec(self):
        mod = load_supervisor()

        spec = mod.parse_session_refresh_spec(
            """
source_session_path: /tmp/session.jsonl
from_turn: 3
to_turn: 7
batch_size: 4
flow_id: flow-test
flow_expected_revision: 2
"""
        )

        self.assertEqual(spec["source_session_path"], "/tmp/session.jsonl")
        self.assertEqual(spec["from_turn"], 3)
        self.assertEqual(spec["to_turn"], 7)
        self.assertEqual(spec["batch_size"], 4)
        self.assertTrue(spec["auto_continue"])
        self.assertTrue(spec["auto_close_reading"])
        self.assertEqual(spec["flow_id"], "flow-test")
        self.assertEqual(spec["flow_expected_revision"], 2)

    def test_session_refresh_prompt_parser_accepts_none_flow_revision(self):
        mod = load_supervisor()

        spec = mod.parse_session_refresh_spec(
            """
source_session_path: /tmp/session.jsonl
from_turn: 122
to_turn: 131
flow_expected_revision: None
"""
        )

        self.assertIsNone(spec["flow_expected_revision"])

    def test_transition_managed_flow_skips_without_flow_id(self):
        mod = load_supervisor()

        result = mod.transition_managed_flow(
            flow_id="",
            expected_revision=0,
            next_status="running",
            actor="test",
            reason="unit",
            evidence_id="e1",
        )

        self.assertEqual(result["status"], "skipped")

    def test_transition_managed_flow_parses_redis_function_result(self):
        mod = load_supervisor()
        original_available = mod.redis_available
        original_cli = mod.redis_cli

        def fake_available():
            return True

        def fake_cli(args):
            self.assertEqual(args[0], "FCALL")
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='{"flow_id":"flow-test","status":"refreshed","revision":3}\n',
            )

        try:
            mod.redis_available = fake_available
            mod.redis_cli = fake_cli
            result = mod.transition_managed_flow(
                flow_id="flow-test",
                expected_revision=2,
                next_status="refreshed",
                actor="test",
                reason="unit",
                evidence_id="e1",
            )
        finally:
            mod.redis_available = original_available
            mod.redis_cli = original_cli

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["revision"], 3)

    def test_set_managed_flow_wait_uses_worker_approval_envelope(self):
        mod = load_supervisor()
        original_available = mod.redis_available
        original_cli = mod.redis_cli
        captured_args = []

        def fake_available():
            return True

        def fake_cli(args):
            captured_args.extend(args)
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='{"flow_id":"flow-test","status":"waiting","revision":4}\n',
            )

        worker_envelope = {
            "status": "needs-approval",
            "envelope": {
                "protocolVersion": 1,
                "ok": True,
                "status": "needs_approval",
                "requiresApproval": {
                    "type": "approval_request",
                    "prompt": "Approve next step?",
                    "approvalId": "approval-1",
                },
            },
        }
        try:
            mod.redis_available = fake_available
            mod.redis_cli = fake_cli
            result = mod.set_managed_flow_wait(
                flow_id="flow-test",
                expected_revision=3,
                worker_envelope=worker_envelope,
                policy_attestation={"attestation_hash": "abcdef1234567890"},
                actor="test",
                evidence_id="e1",
            )
        finally:
            mod.redis_available = original_available
            mod.redis_cli = original_cli

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["revision"], 4)
        self.assertIn("set_waiting_flow", captured_args)
        self.assertIn("approval-1", captured_args)
        self.assertIn("Approve next step?", captured_args)
        self.assertIn("worker_needs_approval:policy:abcdef123456", captured_args)

    def test_failed_flow_transition_blocks_auto_next(self):
        mod = load_supervisor()
        task = mod.Task(
            path=mod.DONE_DIR / "refresh.md",
            task_id="refresh",
            prompt="source_session_path: /tmp/session.jsonl\nfrom_turn: 1\nto_turn: 1",
            phase=mod.SESSION_REFRESH_PHASE,
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "refresh-run"),
            "context_path": str(mod.RUNS_DIR / "refresh-run" / "context.md"),
            "flow_transition": {"enabled": True, "status": "fail", "reason": "revision_mismatch"},
            "session_refresh": {
                "source_session_path": "/tmp/session.jsonl",
                "from_turn": 1,
                "to_turn": 1,
                "batch_size": 1,
                "auto_continue": True,
                "auto_close_reading": True,
                "user_turn_count": 2,
                "extract_path": "/tmp/session/turns-1-1.json",
            },
        }

        self.assertIsNone(mod.schedule_next_task(task, summary))

    def test_copy_pipeline_next_prompt_carries_managed_flow_revision(self):
        mod = load_supervisor()
        task = mod.Task(
            path=mod.DONE_DIR / "copy.md",
            task_id="copy",
            prompt="flow_id: copy-flow\nflow_expected_revision: 0\ncopy next mechanism",
            phase="reference_scan",
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "copy-run"),
            "context_path": str(mod.RUNS_DIR / "copy-run" / "context.md"),
            "flow_transition": {
                "enabled": True,
                "status": "pass",
                "flow_id": "copy-flow",
                "revision": 1,
            },
        }

        next_path = mod.schedule_next_task(task, summary)
        self.assertIsNotNone(next_path)
        assert next_path is not None
        try:
            text = next_path.read_text(encoding="utf-8")
            self.assertIn('phase: "mechanism_extract"', text)
            self.assertIn("- flow_id: copy-flow", text)
            self.assertIn("- flow_expected_revision: 1", text)
        finally:
            next_path.unlink(missing_ok=True)

    def test_task_flow_spec_parser_reads_managed_flow_fields(self):
        mod = load_supervisor()

        spec = mod.parse_task_flow_spec("flow_id: copy-flow\nflow_expected_revision: 7\nbody")

        self.assertEqual(spec["flow_id"], "copy-flow")
        self.assertEqual(spec["flow_expected_revision"], 7)

    def test_session_refresh_phase_does_not_schedule_copy_pipeline_followup(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "refresh.md",
            task_id="refresh",
            prompt="source_session_path: /tmp/session.jsonl\nfrom_turn: 1\nto_turn: 1",
            phase=mod.SESSION_REFRESH_PHASE,
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "refresh-run"),
            "context_path": str(mod.RUNS_DIR / "refresh-run" / "context.md"),
            "session_refresh": {
                "source_session_path": "/tmp/session.jsonl",
                "from_turn": 1,
                "to_turn": 1,
                "batch_size": 10,
                "auto_continue": False,
                "user_turn_count": 20,
            },
        }

        self.assertIsNone(mod.schedule_next_task(task, summary))

    def test_session_refresh_auto_next_schedules_close_reading_first(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "refresh.md",
            task_id="refresh",
            prompt="source_session_path: /tmp/session.jsonl\nfrom_turn: 1\nto_turn: 5",
            phase=mod.SESSION_REFRESH_PHASE,
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "refresh-run"),
            "context_path": str(mod.RUNS_DIR / "refresh-run" / "context.md"),
            "session_refresh": {
                "source_session_path": "/tmp/session.jsonl",
                "from_turn": 1,
                "to_turn": 5,
                "batch_size": 5,
                "auto_continue": True,
                "auto_close_reading": True,
                "user_turn_count": 12,
                "extract_path": "/tmp/session/turns-1-5.json",
                "close_reading_doc": "docs/session-raw-close-reading.md",
                "summary_doc": "docs/session-raw-summary.md",
                "flow_id": "flow-test",
                "flow_revision": 3,
            },
        }

        next_path = mod.schedule_next_task(task, summary)
        self.assertIsNotNone(next_path)
        assert next_path is not None
        try:
            text = next_path.read_text(encoding="utf-8")
            self.assertIn('phase: "session_close_reading"', text)
            self.assertIn("extract_path: /tmp/session/turns-1-5.json", text)
            self.assertIn("to_turn: 5", text)
            self.assertIn("user_turn_count: 12", text)
            self.assertIn("auto_continue: true", text)
            self.assertIn("flow_id: flow-test", text)
            self.assertIn("flow_expected_revision: 3", text)
            self.assertNotIn("Copy pipeline phases", text)
        finally:
            next_path.unlink(missing_ok=True)

    def test_session_close_reading_auto_next_schedules_next_bounded_refresh(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "close.md",
            task_id="close",
            prompt="extract_path: /tmp/session/turns-1-5.json",
            phase=mod.SESSION_CLOSE_READING_PHASE,
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "close-run"),
            "context_path": str(mod.RUNS_DIR / "close-run" / "context.md"),
            "session_close_reading": {
                "source_session_path": "/tmp/session.jsonl",
                "to_turn": 5,
                "batch_size": 5,
                "auto_continue": True,
                "auto_close_reading": True,
                "user_turn_count": 12,
                "close_reading_doc": "docs/session-raw-close-reading.md",
                "summary_doc": "docs/session-raw-summary.md",
                "flow_id": "flow-test",
                "flow_revision": 4,
            },
        }

        next_path = mod.schedule_next_task(task, summary)
        self.assertIsNotNone(next_path)
        assert next_path is not None
        try:
            text = next_path.read_text(encoding="utf-8")
            self.assertIn('phase: "session_refresh"', text)
            self.assertIn("from_turn: 6", text)
            self.assertIn("to_turn: 10", text)
            self.assertIn("auto_close_reading: true", text)
            self.assertIn("flow_id: flow-test", text)
            self.assertIn("flow_expected_revision: 4", text)
            self.assertNotIn("Copy pipeline phases", text)
        finally:
            next_path.unlink(missing_ok=True)

    def test_managed_session_flow_task_ids_are_bounded(self):
        mod = load_supervisor()
        long_parent = "auto-session-close-reading-" * 8 + "parent"

        compact = mod.compact_task_ref(long_parent)

        self.assertLessEqual(len(compact), 48)
        self.assertIn("-", compact)

        task = mod.Task(
            path=mod.DONE_DIR / "close.md",
            task_id=long_parent,
            prompt="extract_path: /tmp/session/turns-1-5.json",
            phase=mod.SESSION_CLOSE_READING_PHASE,
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "close-run"),
            "context_path": str(mod.RUNS_DIR / "close-run" / "context.md"),
            "session_close_reading": {
                "source_session_path": "/tmp/session.jsonl",
                "to_turn": 5,
                "batch_size": 5,
                "auto_continue": True,
                "auto_close_reading": True,
                "user_turn_count": 12,
                "close_reading_doc": "docs/session-raw-close-reading.md",
                "summary_doc": "docs/session-raw-summary.md",
            },
        }

        next_path = mod.schedule_next_task(task, summary)
        self.assertIsNotNone(next_path)
        assert next_path is not None
        try:
            self.assertLess(len(next_path.name), 140)
        finally:
            next_path.unlink(missing_ok=True)

    def test_session_refresh_route_runs_without_codex_worker(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task_id = "session-refresh-route-test"
        with tempfile.TemporaryDirectory() as tmp:
            session_path = Path(tmp) / "session.jsonl"
            rows = [
                {"type": "session_meta", "payload": {"id": "session-refresh-test"}},
                {
                    "type": "response_item",
                    "timestamp": "2026-05-22T00:00:00Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "first request"}],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-22T00:00:01Z",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "first answer"}],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-22T00:00:02Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "second request"}],
                    },
                },
            ]
            session_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            task_path = mod.QUEUE_DIR / f"{task_id}.md"
            task_path.write_text(
                f"""---
id: "{task_id}"
phase: "{mod.SESSION_REFRESH_PHASE}"
timeout_seconds: 60
idle_timeout_seconds: 60
max_attempts: 1
checks:
allowed_paths:
---
source_session_path: {session_path}
from_turn: 1
to_turn: 2
batch_size: 1
auto_continue: false
auto_close_reading: false
""",
                encoding="utf-8",
            )
            task = mod.parse_task(task_path)

            try:
                code = mod.run_session_refresh_task(task, auto_next=True)
                self.assertEqual(code, 0)
                summary_path = mod.DONE_DIR / f"{task_id}.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                refresh = summary["session_refresh"]
                self.assertEqual(summary["status"], "pass")
                self.assertFalse(refresh["called_model"])
                self.assertFalse(refresh["called_worker"])
                self.assertTrue(Path(refresh["index_path"]).exists())
                self.assertTrue(Path(refresh["extract_path"]).exists())
                self.assertEqual(refresh["user_turn_count"], 2)
                self.assertFalse((mod.QUEUE_DIR / f"auto-mechanism_extract-{task_id}.md").exists())
                self.assertEqual(len(list(mod.QUEUE_DIR.glob(f"auto-session-close-reading-{task_id}*.md"))), 0)
            finally:
                (mod.DONE_DIR / f"{task_id}.json").unlink(missing_ok=True)
                (mod.DONE_DIR / f"{task_id}.md").unlink(missing_ok=True)
                task_path.unlink(missing_ok=True)
                shutil.rmtree(mod.EXTERNAL_SESSIONS_DIR / "session-refresh-test", ignore_errors=True)

    def test_session_close_reading_route_appends_bounded_docs_without_worker(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task_id = "session-close-reading-route-test"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            extract_path = tmp_path / "turns-1-2.json"
            close_doc = tmp_path / "close.md"
            summary_doc = tmp_path / "summary.md"
            extract_path.write_text(
                json.dumps(
                    {
                        "kind": "external_codex_session_extract",
                        "session_id": "external-test",
                        "source_session_path": "/tmp/session.jsonl",
                        "from_turn": 1,
                        "to_turn": 2,
                        "approx_lines": "10-30",
                        "turns": [
                            {
                                "turn": 1,
                                "user_line": 10,
                                "user_text": "first task",
                                "assistant_messages": ["first answer"],
                                "tool_calls": [{"name": "exec_command"}],
                                "tool_output_count": 1,
                            },
                            {
                                "turn": 2,
                                "user_line": 30,
                                "user_text": "second task",
                                "assistant_messages": [],
                                "tool_calls": [],
                                "tool_output_count": 0,
                            },
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            task_path = mod.QUEUE_DIR / f"{task_id}.md"
            task_path.write_text(
                f"""---
id: "{task_id}"
phase: "{mod.SESSION_CLOSE_READING_PHASE}"
timeout_seconds: 60
idle_timeout_seconds: 60
max_attempts: 1
checks:
allowed_paths:
---
extract_path: {extract_path}
close_reading_doc: {close_doc}
summary_doc: {summary_doc}
source_session_path: /tmp/session.jsonl
to_turn: 2
user_turn_count: 2
batch_size: 1
auto_continue: false
""",
                encoding="utf-8",
            )
            task = mod.parse_task(task_path)

            try:
                code = mod.run_session_close_reading_task(task, auto_next=True)
                self.assertEqual(code, 0)
                summary = json.loads((mod.DONE_DIR / f"{task_id}.json").read_text(encoding="utf-8"))
                reading = summary["session_close_reading"]
                self.assertEqual(summary["status"], "pass")
                self.assertFalse(reading["called_model"])
                self.assertFalse(reading["called_worker"])
                self.assertTrue(reading["close_reading_appended"])
                self.assertTrue(reading["summary_appended"])
                self.assertIn("## Auto Close Reading: Turn 1-2", close_doc.read_text(encoding="utf-8"))
                self.assertIn("turn 1-2: external session extract", summary_doc.read_text(encoding="utf-8"))
                self.assertEqual(len(list(mod.QUEUE_DIR.glob(f"auto-compare-{task_id}*.md"))), 0)
            finally:
                (mod.DONE_DIR / f"{task_id}.json").unlink(missing_ok=True)
                (mod.DONE_DIR / f"{task_id}.md").unlink(missing_ok=True)
                task_path.unlink(missing_ok=True)

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
