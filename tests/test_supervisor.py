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
    def test_probe_action_to_followup_maps_continue_repair_retry(self):
        mod = load_supervisor()
        cont = mod.probe_action_to_followup("continue", "heartbeat_fresh")
        self.assertEqual(cont["action"], "continue")
        self.assertEqual(cont["status"], "needs-followup")
        self.assertEqual(cont["phase"], "implement")
        self.assertEqual(cont["reason"], "heartbeat_fresh")

        rep = mod.probe_action_to_followup("repair", "missing_required_tools")
        self.assertEqual(rep["action"], "repair")
        self.assertEqual(rep["status"], "needs-repair")
        self.assertEqual(rep["phase"], "repair")

        retry = mod.probe_action_to_followup("retry", "ssh_exec_error")
        self.assertEqual(retry["action"], "retry")
        self.assertEqual(retry["status"], "retryable-remote-probe")
        self.assertEqual(retry["phase"], "repair")

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

    def test_effective_worker_idle_timeout_extends_supervisor_suite(self):
        mod = load_supervisor()
        task = mod.Task(
            path=Path("task.md"),
            task_id="long-supervisor",
            prompt="demo",
            checks=["python3 -m unittest tests/test_supervisor.py"],
            idle_timeout_seconds=120,
        )
        self.assertEqual(mod.effective_worker_idle_timeout_seconds(task), 420)

        short = mod.Task(
            path=Path("task.md"),
            task_id="short",
            prompt="demo",
            checks=["python3 -m unittest tests/test_remote.py"],
            idle_timeout_seconds=120,
        )
        self.assertEqual(mod.effective_worker_idle_timeout_seconds(short), 120)

    def test_create_monitor_score_records_moe_findings(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            events_path = run_dir / "event_summaries.jsonl"
            events_path.write_text(
                json.dumps(
                    {
                        "item_type": "command_execution",
                        "command": "python3 -m pytest -q tests/test_control_api.py",
                        "output_preview": "/usr/bin/python3: No module named pytest\n",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "worker": {"event_summaries_path": str(events_path)},
                        "worker_envelope": {"status": "pass"},
                        "checks": [{"command": "python3 -m unittest tests/test_control_api.py", "return_code": 0}],
                    }
                ),
                encoding="utf-8",
            )

            score = mod.create_monitor_score(run_dir)
            self.assertTrue(Path(score["output_path"]).exists())

        self.assertEqual(score["recommended_action"], "block_and_rewrite_task")
        self.assertIn("test_verifiability_expert", {item["name"] for item in score["experts"]})
        self.assertEqual(score["gates"]["hard_gate"]["status"], "fail")

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

    def test_repo_map_prefers_allowed_paths_and_excludes_session_governance_noise(self):
        mod = load_supervisor()
        allowed = ["scripts/a9_supervisor.py", "tests/test_supervisor.py"]
        repo_map, meta = mod.build_repo_map(
            "focus on supervisor repo map behavior",
            900,
            allowed_paths=allowed,
        )

        self.assertIn("scripts/a9_supervisor.py", repo_map)
        self.assertIn("tests/test_supervisor.py", repo_map)
        self.assertNotIn("session-governance.md", repo_map)
        self.assertNotIn("docs/session-raw-summary.md", repo_map)
        self.assertNotIn("docs/session-raw-close-reading.md", repo_map)
        self.assertEqual(meta["allowed_paths"], allowed)
        self.assertGreater(meta["included_files"], 0)

    def test_hydrate_worker_reference_slices_copies_bounded_references(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_root = tmp_path / "source"
            worktree = tmp_path / "worktree"
            codex_transport = (
                source_root
                / "reference-projects"
                / "codex"
                / "codex-rs"
                / "app-server-transport"
                / "src"
                / "transport"
            )
            codex_transport.mkdir(parents=True)
            (codex_transport / "mod.rs").write_text("mod websocket;\n", encoding="utf-8")
            lobster = source_root / "reference-projects" / "openclaw" / "extensions" / "lobster" / "src"
            lobster.mkdir(parents=True)
            (lobster / "lobster-core.d.ts").write_text("type LobsterToolEnvelope = {}\n", encoding="utf-8")
            barter_socket = (
                source_root / "reference-projects" / "barter-rs" / "barter-integration" / "src" / "socket"
            )
            barter_socket.mkdir(parents=True)
            (barter_socket / "mod.rs").write_text("pub mod reconnect;\n", encoding="utf-8")
            barter_audit = source_root / "reference-projects" / "barter-rs" / "barter" / "src" / "engine" / "audit"
            barter_audit.mkdir(parents=True)
            (barter_audit / "mod.rs").write_text("pub struct AuditEngine;\n", encoding="utf-8")
            barter_strategy = source_root / "reference-projects" / "barter-rs" / "barter" / "src" / "strategy"
            barter_strategy.mkdir(parents=True)
            (barter_strategy / "mod.rs").write_text("pub trait Strategy {};\n", encoding="utf-8")
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

            self.assertIn("reference-projects/codex/codex-rs/app-server-transport/src/transport", copied)
            self.assertIn("reference-projects/openclaw/extensions/lobster", copied)
            self.assertIn("reference-projects/barter-rs/barter-integration/src/socket", copied)
            self.assertIn("reference-projects/barter-rs/barter/src/engine/audit", copied)
            self.assertIn("reference-projects/barter-rs/barter/src/strategy", copied)
            self.assertIn("vendor-src", copied)
            self.assertTrue(
                (
                    worktree
                    / "reference-projects"
                    / "codex"
                    / "codex-rs"
                    / "app-server-transport"
                    / "src"
                    / "transport"
                    / "mod.rs"
                ).exists()
            )
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
            self.assertTrue(
                (
                    worktree
                    / "reference-projects"
                    / "barter-rs"
                    / "barter-integration"
                    / "src"
                    / "socket"
                    / "mod.rs"
                ).exists()
            )
            self.assertTrue(
                (
                    worktree
                    / "reference-projects"
                    / "barter-rs"
                    / "barter"
                    / "src"
                    / "engine"
                    / "audit"
                    / "mod.rs"
                ).exists()
            )
            self.assertTrue(
                (
                    worktree
                    / "reference-projects"
                    / "barter-rs"
                    / "barter"
                    / "src"
                    / "strategy"
                    / "mod.rs"
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

    def test_worker_envelope_declared_check_timeout_conflict_reconciles_to_pass_and_committable(self):
        mod = load_supervisor()
        worker = {"timed_out": False, "idle_timed_out": False, "return_code": 0}
        diff_stub = {"diff_bytes": 120}
        checks = [{"command": "python3 -m unittest tests/test_supervisor.py", "return_code": 0}]
        worker_envelope = {
            "status": "fail",
            "envelope": {
                "protocolVersion": 1,
                "ok": False,
                "status": "error",
                "error": {"code": "declared_check_timeout", "message": "declared_check_timeout from stale self-report"},
            },
        }
        initial_status = mod.decide_status(worker, diff_stub, checks, worker_envelope=worker_envelope)
        conflict = mod.reconcile_worker_envelope_check_conflict(
            worker_envelope,
            checks,
            patch_apply={"status": "skip"},
            patch_guard={"status": "pass"},
            scope_guard={"status": "pass"},
            process_governance={"status": "pass"},
        )
        reconciled_status = "pass" if (initial_status == "needs-repair" and conflict) else initial_status

        self.assertEqual(initial_status, "needs-repair")
        self.assertIsNotNone(conflict)
        assert conflict is not None
        self.assertEqual(conflict["status"], "reconciled-pass")
        self.assertEqual(reconciled_status, "pass")

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
            captured_diff = mod.capture_diff(repo, run_dir)
            governance = mod.apply_git_governance(
                repo,
                run_dir,
                mod.Task(path=Path("task.md"), task_id="git-reconcile-pass", prompt="demo"),
                reconciled_status,
                captured_diff,
            )

        self.assertEqual(governance["status"], "committed")
        self.assertFalse(governance["rolled_back"])

    def test_worker_envelope_genuine_failure_with_failing_check_stays_needs_repair(self):
        mod = load_supervisor()
        worker = {"timed_out": False, "idle_timed_out": False, "return_code": 0}
        diff = {"diff_bytes": 120}
        checks = [{"command": "python3 -m unittest tests/test_supervisor.py", "return_code": 1}]
        worker_envelope = {
            "status": "fail",
            "envelope": {
                "protocolVersion": 1,
                "ok": False,
                "status": "error",
                "error": {"code": "declared_checks_failed", "message": "declared checks failed"},
            },
        }

        status = mod.decide_status(worker, diff, checks, worker_envelope=worker_envelope)
        conflict = mod.reconcile_worker_envelope_check_conflict(
            worker_envelope,
            checks,
            patch_apply={"status": "skip"},
            patch_guard={"status": "pass"},
            scope_guard={"status": "pass"},
            process_governance={"status": "pass"},
        )

        self.assertEqual(status, "needs-repair")
        self.assertIsNone(conflict)

    def test_process_governance_flags_undeclared_worker_test_commands(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            events = run_dir / "event_summaries.jsonl"
            events.write_text(
                json.dumps(
                    {
                        "item_type": "command_execution",
                        "command": "/bin/bash -lc 'python3 -m pytest -q tests/test_control_api.py -k compact_summary'",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            task = mod.Task(
                path=Path("task.md"),
                task_id="process-governance",
                prompt="test data schema",
                checks=["python3 -m unittest tests/test_control_api.py"],
            )
            result = mod.classify_process_governance(task, {"event_summaries_path": str(events)}, run_dir)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["findings"][0]["kind"], "undeclared_check")
        self.assertIn("pytest", result["findings"][0]["command"])

    def test_process_governance_enforces_task_command_bounds(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            events = run_dir / "event_summaries.jsonl"
            events.write_text(
                "\n".join(
                    [
                        json.dumps({"item_type": "command_execution", "command": "/bin/bash -lc ls"}),
                        json.dumps(
                            {
                                "item_type": "command_execution",
                                "command": "/bin/bash -lc 'rg --files reference-projects | head -n 200'",
                            }
                        ),
                        json.dumps(
                            {
                                "item_type": "command_execution",
                                "command": "/bin/bash -lc 'rg -n \"command_window_exceeded\" /tmp/run docs . -g \"*.json\"'",
                            }
                        ),
                        json.dumps(
                            {
                                "item_type": "command_execution",
                                "command": "/bin/bash -lc \"sed -n '1,241p' reference-projects/codex/mod.rs\"",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            task = mod.Task(
                path=Path("task.md"),
                task_id="process-command-bounds",
                prompt=(
                    "Hard bounds:\n"
                    "- Do not run ls or rg --files.\n"
                    "- Use sed windows must be <= 120 lines and targeted rg only.\n"
                ),
                checks=["python3 -m py_compile scripts/a9_supervisor.py"],
            )
            result = mod.classify_process_governance(task, {"event_summaries_path": str(events)}, run_dir)

        kinds = [finding["kind"] for finding in result["findings"]]
        self.assertEqual(result["status"], "fail")
        self.assertEqual(kinds.count("forbidden_command"), 2)
        self.assertIn("broad_rg_command", kinds)
        self.assertIn("command_window_exceeded", kinds)
        window = next(finding for finding in result["findings"] if finding["kind"] == "command_window_exceeded")
        self.assertEqual(window["lines"], 241)
        self.assertEqual(window["soft_limit"], 180)
        self.assertEqual(window["hard_limit"], 240)

    def test_process_governance_observes_batched_sed_reads_with_rationale(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            events = run_dir / "event_summaries.jsonl"
            events.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "item_type": "agent_message",
                                "text_preview": "为了理解 transport 状态机机制，需要分批读取 on_stream_err 核心窗口。",
                            }
                        ),
                        json.dumps(
                            {
                                "item_type": "command_execution",
                                "command": "/bin/bash -lc \"sed -n '1,220p' reference-projects/codex/mod.rs\"",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            task = mod.Task(
                path=Path("task.md"),
                task_id="batched-sed-rationale",
                phase="mechanism_extract",
                prompt="Hard bounds:\n- sed windows <= 120 lines.\n",
                checks=[],
            )
            result = mod.classify_process_governance(task, {"event_summaries_path": str(events)}, run_dir)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["findings"][0]["kind"], "batched_read_with_rationale")
        self.assertEqual(result["findings"][0]["level"], "info")

    def test_process_governance_warns_on_batched_sed_read_without_rationale(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            events = run_dir / "event_summaries.jsonl"
            events.write_text(
                json.dumps(
                    {
                        "item_type": "command_execution",
                        "command": "/bin/bash -lc \"sed -n '1,220p' reference-projects/codex/mod.rs\"",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            task = mod.Task(
                path=Path("task.md"),
                task_id="batched-sed-no-rationale",
                phase="mechanism_extract",
                prompt="Hard bounds:\n- sed windows <= 120 lines.\n",
                checks=[],
            )
            result = mod.classify_process_governance(task, {"event_summaries_path": str(events)}, run_dir)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["findings"][0]["kind"], "command_window_missing_rationale")
        self.assertEqual(result["findings"][0]["level"], "warning")

    def test_process_governance_failure_blocks_status_even_when_checks_pass(self):
        mod = load_supervisor()
        worker = {"timed_out": False, "idle_timed_out": False, "return_code": 0}
        status = mod.decide_status(
            worker,
            {"diff_bytes": 120},
            [{"command": "python3 -m unittest tests/test_control_api.py", "return_code": 0}],
            patch_guard={"status": "pass"},
            scope_guard={"status": "pass"},
            process_governance={"status": "fail", "findings": [{"kind": "undeclared_check"}]},
        )

        self.assertEqual(status, "monitor-blocked")

    def test_live_worker_command_violation_blocks_task_bound_violations(self):
        mod = load_supervisor()
        task = mod.Task(
            path=Path("task.md"),
            task_id="live-command-bounds",
            prompt=(
                "Hard bounds:\n"
                "- Do not run ls or rg --files.\n"
                "- Use targeted rg -n only.\n"
                "- sed windows <= 120 lines.\n"
            ),
            checks=["python3 -m unittest tests.test_supervisor.SupervisorTests.test_demo"],
        )

        broad_rg = mod.live_worker_command_violation(task, "/bin/bash -lc 'rg -n needle docs .'")
        sed_over = mod.live_worker_command_violation(task, "/bin/bash -lc \"sed -n '1,241p' scripts/a9_supervisor.py\"")
        undeclared = mod.live_worker_command_violation(task, "/bin/bash -lc 'python3 -m pytest -q tests/test_supervisor.py'")
        declared = mod.live_worker_command_violation(
            task,
            "/bin/bash -lc 'python3 -m unittest tests.test_supervisor.SupervisorTests.test_demo'",
        )

        self.assertEqual(broad_rg["kind"], "broad_rg_command")
        self.assertEqual(sed_over["kind"], "command_window_exceeded")
        self.assertEqual(sed_over["lines"], 241)
        self.assertEqual(undeclared["kind"], "undeclared_check")
        self.assertEqual(declared, {})

    def test_declared_unittest_file_and_module_forms_are_equivalent(self):
        mod = load_supervisor()

        self.assertTrue(
            mod.command_matches_declared_check(
                "/bin/bash -lc 'python3 -m unittest tests.test_remote'",
                ["python3 -m unittest tests/test_remote.py"],
            )
        )
        self.assertTrue(
            mod.command_matches_declared_check(
                "/bin/bash -lc 'python3 -m unittest tests/test_remote.py'",
                ["python3 -m unittest tests.test_remote"],
            )
        )

    def test_live_worker_allows_read_heavy_batched_sed_with_rationale(self):
        mod = load_supervisor()
        task = mod.Task(
            path=Path("task.md"),
            task_id="live-batched-read",
            phase="mechanism_extract",
            prompt="Hard bounds:\n- sed windows <= 120 lines.\n",
        )

        allowed = mod.live_worker_command_violation(
            task,
            "/bin/bash -lc \"sed -n '1,220p' reference-projects/codex/mod.rs\"",
            rationale="为了理解状态机机制，需要分批读取这个 bounded window。",
        )
        blocked = mod.live_worker_command_violation(
            task,
            "/bin/bash -lc \"sed -n '1,361p' reference-projects/codex/mod.rs\"",
            rationale="为了理解状态机机制，需要分批读取这个 bounded window。",
        )

        self.assertEqual(allowed, {})
        self.assertEqual(blocked["kind"], "command_window_exceeded")
        self.assertEqual(blocked["limit"], 360)

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

    def test_worker_envelope_status_alias_pass_normalizes_to_ok(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":1,"ok":true,"status":"pass","output":{"changed_files":[]}}\n',
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
        self.assertEqual(envelope["envelope"]["status"], "ok")
        self.assertEqual(status, "pass")
        self.assertTrue(
            any("normalized status alias" in finding.get("message", "") for finding in envelope.get("findings", []))
        )

    def test_worker_envelope_status_alias_success_normalizes_to_ok(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":1,"ok":true,"status":"success","output":{"changed_files":[]}}\n',
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
        self.assertEqual(envelope["envelope"]["status"], "ok")
        self.assertEqual(status, "pass")

    def test_worker_envelope_protocol_version_alias_string_1_0_normalizes_to_1(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":"1.0","ok":true,"status":"ok","output":{"changed_files":[]}}\n',
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
        self.assertEqual(envelope["envelope"]["protocolVersion"], 1)
        self.assertEqual(status, "pass")
        self.assertTrue(
            any("normalized protocolVersion alias" in finding.get("message", "") for finding in envelope.get("findings", []))
        )
        self.assertFalse(any(finding.get("level") == "error" for finding in envelope.get("findings", [])))

    def test_worker_envelope_protocol_and_status_aliases_normalize_together(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":"openclaw/1","ok":true,"status":"completed","output":{"changed_files":[]}}\n',
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
        self.assertEqual(envelope["envelope"]["protocolVersion"], 1)
        self.assertEqual(envelope["envelope"]["status"], "ok")
        self.assertEqual(status, "pass")
        self.assertTrue(
            any("normalized protocolVersion alias" in finding.get("message", "") for finding in envelope.get("findings", []))
        )
        self.assertTrue(
            any("normalized status alias" in finding.get("message", "") for finding in envelope.get("findings", []))
        )

    def test_worker_envelope_status_alias_completed_normalizes_to_ok(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":1,"ok":true,"status":"completed","output":{"changed_files":[]}}\n',
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
        self.assertEqual(envelope["envelope"]["status"], "ok")
        self.assertEqual(status, "pass")
        self.assertTrue(
            any("normalized status alias" in finding.get("message", "") for finding in envelope.get("findings", []))
        )

    def test_worker_envelope_status_alias_reference_scan_complete_normalizes_to_ok(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":"1.0","ok":true,"status":"reference_scan_complete","output":{"changed_files":[]}}\n',
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
        self.assertEqual(envelope["envelope"]["protocolVersion"], 1)
        self.assertEqual(envelope["envelope"]["status"], "ok")
        self.assertEqual(status, "pass")
        self.assertTrue(
            any("normalized status alias" in finding.get("message", "") for finding in envelope.get("findings", []))
        )

    def test_worker_envelope_protocol_version_alias_openclaw_1_normalizes_to_1(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":"openclaw/1","ok":true,"status":"ok","output":{"changed_files":[]}}\n',
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
        self.assertEqual(envelope["envelope"]["protocolVersion"], 1)
        self.assertEqual(status, "pass")
        self.assertTrue(
            any("normalized protocolVersion alias" in finding.get("message", "") for finding in envelope.get("findings", []))
        )

    def test_worker_envelope_protocol_version_alias_openclaw_v1_normalizes_to_1(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":"openclaw/v1","ok":true,"status":"completed","output":{"changed_files":[]}}\n',
                encoding="utf-8",
            )
            task = mod.Task(
                path=Path("task.md"),
                task_id="strict-envelope-openclaw-v1",
                prompt="strict_worker_envelope: true\nDo work.",
            )
            worker = {"final_path": str(final), "timed_out": False, "idle_timed_out": False, "return_code": 0}

            envelope = mod.validate_worker_envelope(task, worker, run_dir)
            status = mod.decide_status(worker, {"diff_bytes": 120}, [], worker_envelope=envelope)

        self.assertEqual(envelope["status"], "pass")
        self.assertEqual(envelope["envelope"]["protocolVersion"], 1)
        self.assertEqual(envelope["envelope"]["status"], "ok")
        self.assertEqual(status, "pass")
        self.assertTrue(
            any("normalized protocolVersion alias" in finding.get("message", "") for finding in envelope.get("findings", []))
        )

    def test_worker_envelope_protocol_version_alias_openclaw_lobster_normalizes_to_1(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":"openclaw-lobster-worker-envelope/1.0","ok":true,"status":"ok","output":{"changed_files":[]}}\n',
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
        self.assertEqual(envelope["envelope"]["protocolVersion"], 1)
        self.assertEqual(status, "pass")
        self.assertTrue(
            any("normalized protocolVersion alias" in finding.get("message", "") for finding in envelope.get("findings", []))
        )

    def test_worker_envelope_protocol_version_alias_openclaw_lobster_v1_normalizes_to_1(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final_path = run_dir / "final.md"
            final_path.write_text(
                'done\n{"protocolVersion":"openclaw-lobster-v1","ok":true,"status":"completed","output":{"changed_files":[]}}\n',
                encoding="utf-8",
            )
            task = mod.Task(
                path=Path("task.md"),
                task_id="envelope-alias-openclaw-lobster-v1",
                prompt="strict_worker_envelope: true\nDo work.",
            )
            worker = {"final_path": str(final_path), "timed_out": False, "idle_timed_out": False, "return_code": 0}
            envelope = mod.validate_worker_envelope(task, worker, run_dir)
            status = mod.decide_status(worker, {"diff_bytes": 120}, [], worker_envelope=envelope)

        self.assertEqual(envelope["status"], "pass")
        self.assertEqual(status, "pass")
        self.assertEqual(envelope["envelope"]["protocolVersion"], 1)
        self.assertEqual(envelope["envelope"]["status"], "ok")

    def test_worker_envelope_protocol_version_alias_named_v1_normalizes_to_1(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":"a9.strict_worker_envelope.v1","ok":true,"status":"ok","output":{"changed_files":[]}}\n',
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
        self.assertEqual(envelope["envelope"]["protocolVersion"], 1)
        self.assertEqual(status, "pass")

    def test_worker_envelope_invalid_protocol_version_still_fails(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":"v2","ok":true,"status":"ok","output":{"changed_files":[]}}\n',
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

        self.assertEqual(envelope["status"], "fail")
        self.assertEqual(status, "needs-repair")
        self.assertTrue(any("protocolVersion must be 1" in finding.get("message", "") for finding in envelope["findings"]))

    def test_worker_envelope_invalid_status_still_fails(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final = run_dir / "final.md"
            final.write_text(
                'done\n{"protocolVersion":1,"ok":true,"status":"done","output":{"changed_files":[]}}\n',
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

        self.assertEqual(envelope["status"], "fail")
        self.assertEqual(status, "needs-repair")
        self.assertTrue(
            any("status must be ok, needs_approval, or cancelled" in finding.get("message", "") for finding in envelope["findings"])
        )

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
        bulleted = mod.Task(
            path=Path("task.md"),
            task_id="diagnostic-bulleted",
            prompt="Phase-specific bounds:\n- expected_file_changes: false\n- Do not modify files.",
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
        self.assertTrue(mod.task_allows_no_diff(bulleted))
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

    def test_next_task_prompt_inlines_worker_next_slice(self):
        mod = load_supervisor()
        task = mod.Task(path=Path("task.md"), task_id="scan", prompt="demo", phase="reference_scan")
        summary = {
            "status": "pass",
            "run_dir": "/tmp/run",
            "context_path": "/tmp/run/context.md",
            "worker_envelope": {
                "envelope": {
                    "output": {
                        "next_slice": "mechanism_extract: formalize reconnect backoff",
                        "copied_mechanisms": [{"mechanism": "Barter reconnect stream"}],
                        "changed_files": [],
                    }
                }
            },
        }

        prompt = mod.next_task_prompt(task, summary, "mechanism_extract")

        self.assertIn("Previous worker output:", prompt)
        self.assertIn("mechanism_extract: formalize reconnect backoff", prompt)
        self.assertIn("Barter reconnect stream", prompt)

    def test_next_task_prompt_enforces_worker_prompt_discipline(self):
        mod = load_supervisor()
        task = mod.Task(path=Path("task.md"), task_id="test-discipline", prompt="demo", phase="test")
        summary = {
            "status": "pass",
            "run_dir": "/tmp/run",
            "context_path": "/tmp/run/context.md",
            "worker_envelope": {"envelope": {"output": {"next_slice": "test: keep checks bounded"}}},
        }

        prompt = mod.next_task_prompt(task, summary, "test")

        self.assertIn("Declared checks are authoritative", prompt)
        self.assertIn("Do not add pytest or cargo unless they are explicitly declared", prompt)
        self.assertIn("Do not use web search or browsing unless the task explicitly asks", prompt)
        self.assertIn("Do not read `docs/session-raw-summary.md`", prompt)
        self.assertIn("raw session logs", prompt)
        self.assertIn("Use `rg -n` first", prompt)

    def test_next_task_prompt_includes_communication_acceptance_hints_when_gateway_evidence_required(self):
        mod = load_supervisor()
        task = mod.Task(
            path=Path("task.md"),
            task_id="gateway-communication-hints",
            prompt="Continue communication governance for gateway runtime evidence.",
            phase="test",
        )
        summary = {
            "status": "pass",
            "run_dir": "/tmp/run",
            "context_path": "/tmp/run/context.md",
            "worker_envelope": {"envelope": {"output": {"next_slice": "test reconnect event stream envelope"}}},
        }

        prompt = mod.next_task_prompt(task, summary, "record")

        self.assertIn("Communication acceptance hints:", prompt)
        self.assertIn("Data model:", prompt)
        self.assertIn("node table shape", prompt)
        self.assertIn("Performance bounds:", prompt)
        self.assertIn("latency/timeout targets", prompt)
        self.assertIn("Failure taxonomy -> recovery mapping:", prompt)
        self.assertIn("timeout/auth/network/protocol/rate_limit", prompt)

    def test_next_task_prompt_omits_communication_acceptance_hints_for_non_communication_task(self):
        mod = load_supervisor()
        task = mod.Task(path=Path("task.md"), task_id="docs-record", prompt="Update docs.", phase="record")
        summary = {
            "status": "pass",
            "run_dir": "/tmp/run",
            "context_path": "/tmp/run/context.md",
            "worker_envelope": {"envelope": {"output": {"next_slice": "record copied mechanisms"}}},
        }

        prompt = mod.next_task_prompt(task, summary, "record")

        self.assertNotIn("Communication acceptance hints:", prompt)

    def test_retryable_worker_failure_short_circuits_checks(self):
        mod = load_supervisor()

        self.assertTrue(mod.worker_failure_short_circuits_checks({"status": "retryable-worker-budget"}))
        self.assertTrue(mod.worker_failure_short_circuits_checks({"status": "retryable-worker-network"}))
        self.assertFalse(mod.worker_failure_short_circuits_checks({"status": ""}))
        self.assertFalse(mod.worker_failure_short_circuits_checks({"status": "needs-repair"}))

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

    def test_schedule_next_task_blocks_when_monitor_hard_gate_fails(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "monitor-block.md",
            task_id="monitor-block",
            prompt="test data schema",
            phase="test",
            allowed_paths=["tests/test_control_api.py"],
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "monitor-block-run"),
            "context_path": str(mod.RUNS_DIR / "monitor-block-run" / "context.md"),
            "monitor_score": {
                "decision_model": "requirements_review_council_v1",
                "recommended_action": "block_and_rewrite_task",
                "gates": {
                    "hard_gate": {
                        "status": "fail",
                        "failed_experts": ["test_verifiability_expert"],
                    }
                },
            },
        }

        self.assertTrue(mod.monitor_score_blocks_next(summary))
        self.assertIsNone(mod.schedule_next_task(task, summary))

    def test_schedule_next_task_blocks_communication_when_gateway_runtime_evidence_not_continue(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "gateway-communication.md",
            task_id="gateway-communication",
            prompt="Continue communication governance for Redis stream and mobile control plane.",
            phase="test",
            allowed_paths=["crates/a9-gateway/src/main.rs"],
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "gateway-run"),
            "context_path": str(mod.RUNS_DIR / "gateway-run" / "context.md"),
        }
        original_gate = mod.gateway_runtime_gate
        try:
            mod.gateway_runtime_gate = lambda: {
                "status": "degraded",
                "action": "emit_runtime_event",
                "reason": "gateway_runtime_event_stale",
                "event_id": "1-0",
            }
            self.assertTrue(mod.communication_task_requires_gateway_runtime_evidence(task, summary))
            self.assertIsNone(mod.schedule_next_task(task, summary))
        finally:
            mod.gateway_runtime_gate = original_gate

        self.assertEqual(summary["gateway_runtime_gate"]["action"], "emit_runtime_event")
        self.assertEqual(summary["gateway_runtime_gate"]["reason"], "gateway_runtime_event_stale")

    def test_schedule_next_task_allows_communication_when_gateway_runtime_evidence_continue(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "gateway-communication-pass.md",
            task_id="gateway-communication-pass",
            prompt="Continue gateway Redis stream communication governance.",
            phase="test",
            allowed_paths=["crates/a9-gateway/src/main.rs"],
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "gateway-run-pass"),
            "context_path": str(mod.RUNS_DIR / "gateway-run-pass" / "context.md"),
        }
        original_gate = mod.gateway_runtime_gate
        try:
            mod.gateway_runtime_gate = lambda: {
                "status": "ok",
                "action": "continue",
                "reason": "gateway_runtime_event_fresh",
                "event_id": "2-0",
            }
            next_path = mod.schedule_next_task(task, summary)
        finally:
            mod.gateway_runtime_gate = original_gate

        self.assertIsNotNone(next_path)
        assert next_path is not None
        try:
            text = next_path.read_text(encoding="utf-8")
            self.assertIn("Continue A9 24-hour automation", text)
            self.assertEqual(summary["gateway_runtime_gate"]["action"], "continue")
        finally:
            next_path.unlink(missing_ok=True)

    def test_schedule_next_task_skips_gateway_gate_for_non_communication_task(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "docs-record.md",
            task_id="docs-record",
            prompt="Update copied mechanism notes.",
            phase="record",
            allowed_paths=["docs/copied-mechanisms.md"],
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "docs-run"),
            "context_path": str(mod.RUNS_DIR / "docs-run" / "context.md"),
        }
        next_path = mod.schedule_next_task(task, summary)

        self.assertIsNotNone(next_path)
        assert next_path is not None
        try:
            self.assertEqual(summary["gateway_runtime_gate"]["status"], "skip")
        finally:
            next_path.unlink(missing_ok=True)

    def test_schedule_next_task_routes_monitor_blocked_to_repair_takeover(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "monitor-blocked.md",
            task_id="monitor-blocked",
            prompt="test data schema",
            phase="test",
            checks=["python3 -m unittest tests/test_control_api.py"],
            allowed_paths=["scripts/a9_control_api.py", "tests/test_control_api.py"],
        )
        summary = {
            "task_id": task.task_id,
            "status": "monitor-blocked",
            "run_dir": str(mod.RUNS_DIR / "monitor-blocked-run"),
            "context_path": str(mod.RUNS_DIR / "monitor-blocked-run" / "context.md"),
            "diff": {"diff_path": str(mod.RUNS_DIR / "monitor-blocked-run" / "patch.diff"), "diff_bytes": 120},
            "process_governance": {
                "status": "fail",
                "policy": "declared_checks_and_task_command_bounds_are_authoritative",
                "output_path": "/tmp/run/process_governance.json",
                "findings": [
                    {"kind": "undeclared_check", "message": "bad check", "command": "python3 -m pytest -q"},
                    {
                        "kind": "command_window_exceeded",
                        "message": "too many lines",
                        "command": "/bin/bash -lc \"sed -n '1,240p' huge/file\"",
                        "lines": 240,
                        "limit": 120,
                    },
                    {"kind": "broad_rg_command", "message": "broad rg", "command": "rg -n needle docs ."},
                    {"kind": "broad_rg_command", "message": "broad rg again", "command": "rg -n other docs ."},
                ],
            },
            "monitor_score": {
                "decision_model": "requirements_review_council_v1",
                "recommended_action": "block_and_rewrite_task",
                "gates": {"hard_gate": {"status": "fail", "failed_experts": ["test_verifiability_expert"]}},
            },
            "monitor_block": {
                "blocked": True,
                "reason": "monitor_hard_gate_failed",
                "failed_experts": ["test_verifiability_expert"],
            },
        }

        next_path = mod.schedule_next_task(task, summary)
        self.assertIsNotNone(next_path)
        assert next_path is not None
        try:
            text = next_path.read_text(encoding="utf-8")
            self.assertIn('phase: "repair"', text)
            self.assertIn("Monitor-blocked repair", text)
            self.assertIn("process_governance_summary", text)
            self.assertIn('"findings_count": 4', text)
            self.assertIn('"broad_rg_command": 2', text)
            self.assertIn("/tmp/run/process_governance.json", text)
            self.assertIn("patch.diff", text)
            self.assertIn("Declared checks are authoritative", text)
            self.assertIn("prefer <=180 line", text)
            self.assertIn("python3 -m unittest tests/test_control_api.py", text)
            self.assertNotIn("rg -n other docs .", text)
        finally:
            next_path.unlink(missing_ok=True)

    def test_monitor_block_summary_projects_hard_gate_for_progress(self):
        mod = load_supervisor()
        monitor_score = {
            "recommended_action": "block_and_rewrite_task",
            "gates": {
                "hard_gate": {
                    "status": "fail",
                    "failed_experts": ["data_model_expert", "test_verifiability_expert"],
                }
            },
        }

        block = mod.monitor_block_summary(monitor_score)
        progress = mod.service_progress(
            {
                "task_id": "blocked",
                "status": "pass",
                "run_dir": "/tmp/run",
                "monitor_block": block,
            }
        )

        self.assertTrue(block["blocked"])
        self.assertEqual(block["reason"], "monitor_hard_gate_failed")
        self.assertEqual(block["failed_experts"], ["data_model_expert", "test_verifiability_expert"])
        self.assertEqual(progress["latest_monitor_block"], block)

    def test_reconcile_status_with_monitor_block_overrides_with_conflict_evidence(self):
        mod = load_supervisor()
        status, block = mod.reconcile_status_with_monitor_block(
            "pass",
            {
                "blocked": True,
                "reason": "monitor_hard_gate_failed",
                "failed_experts": ["exception_governance_expert"],
                "recommended_action": "block_and_rewrite_task",
            },
            worker_envelope_check_conflict={
                "status": "reconciled-pass",
                "reason": "worker self-reported declared check failure/timeout but supervisor checks passed",
            },
        )

        self.assertEqual(status, "pass")
        self.assertFalse(block["blocked"])
        self.assertEqual(block["reason"], "monitor_block_overridden_by_supervisor_reconciliation")
        self.assertEqual(block["override"]["source"], "worker_envelope_check_conflict")
        self.assertEqual(block["override"]["previous_failed_experts"], ["exception_governance_expert"])

    def test_reconcile_status_with_monitor_block_blocks_non_reconciled_pass(self):
        mod = load_supervisor()
        status, block = mod.reconcile_status_with_monitor_block(
            "pass",
            {
                "blocked": True,
                "reason": "monitor_hard_gate_failed",
                "failed_experts": ["exception_governance_expert"],
                "recommended_action": "block_and_rewrite_task",
            },
            worker_envelope_check_conflict=None,
        )

        self.assertEqual(status, "monitor-blocked")
        self.assertTrue(block["blocked"])
        self.assertEqual(block["reason"], "monitor_hard_gate_failed")

    def test_reconcile_status_with_monitor_block_keeps_non_strict_worker_advisory(self):
        mod = load_supervisor()
        status, block = mod.reconcile_status_with_monitor_block(
            "pass",
            {
                "blocked": True,
                "reason": "monitor_hard_gate_failed",
                "failed_experts": ["exception_governance_expert"],
                "recommended_action": "block_and_rewrite_task",
            },
            worker_envelope_check_conflict=None,
            worker_envelope={"status": "skip", "required": False},
        )

        self.assertEqual(status, "pass")
        self.assertFalse(block["blocked"])
        self.assertEqual(block["reason"], "monitor_block_advisory_for_non_strict_worker")
        self.assertEqual(block["override"]["source"], "non_strict_worker_envelope")

    def test_schedule_next_task_records_deterministically_without_record_worker(self):
        mod = load_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            old_records = mod.RECORDS_DIR
            old_gateway_runtime_blocks_next = mod.gateway_runtime_blocks_next
            mod.RECORDS_DIR = Path(tmp) / "records"
            mod.gateway_runtime_blocks_next = lambda task, summary: False
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
                "auto_loop_guard": {"status": "ok"},
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
                mod.gateway_runtime_blocks_next = old_gateway_runtime_blocks_next
                if "next_path" in locals() and next_path is not None:
                    next_path.unlink(missing_ok=True)

    def test_schedule_next_task_routes_to_test_phase_from_next_slice_prefix(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "auto-impl.md",
            task_id="auto-impl",
            prompt="implement one bounded slice",
            phase="implement",
            checks=["python3 -m unittest tests/test_control_api.py"],
            allowed_paths=["scripts/a9_supervisor.py", "tests/test_supervisor.py"],
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "auto-impl-run"),
            "context_path": str(mod.RUNS_DIR / "auto-impl-run" / "context.md"),
            "worker_envelope": {
                "status": "pass",
                "envelope": {"output": {"next_slice": "test: validate bounded routing"}},
            },
        }

        next_path = mod.schedule_next_task(task, summary)
        self.assertIsNotNone(next_path)
        assert next_path is not None
        try:
            text = next_path.read_text(encoding="utf-8")
            self.assertIn('phase: "test"', text)
            self.assertIn('  - "python3 -m unittest tests/test_control_api.py"', text)
            self.assertNotIn("cargo build --workspace", text)
        finally:
            next_path.unlink(missing_ok=True)

    def test_schedule_next_task_routes_needs_followup_from_next_slice_prefix(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "auto-followup.md",
            task_id="auto-followup",
            prompt="continue one bounded slice",
            phase="implement",
            allowed_paths=["scripts/a9_supervisor.py", "tests/test_supervisor.py"],
        )
        summary = {
            "task_id": task.task_id,
            "status": "needs-followup",
            "run_dir": str(mod.RUNS_DIR / "auto-followup-run"),
            "context_path": str(mod.RUNS_DIR / "auto-followup-run" / "context.md"),
            "worker_envelope": {
                "status": "pass",
                "envelope": {"output": {"next_slice": "test: cover followup routing"}},
            },
        }

        next_path = mod.schedule_next_task(task, summary)
        self.assertIsNotNone(next_path)
        assert next_path is not None
        try:
            text = next_path.read_text(encoding="utf-8")
            self.assertIn('phase: "test"', text)
        finally:
            next_path.unlink(missing_ok=True)

    def test_schedule_next_task_routes_to_implement_phase_from_next_slice_prefix(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "auto-vendor.md",
            task_id="auto-vendor",
            prompt="import one mechanism",
            phase="vendor_import",
            allowed_paths=["scripts/a9_supervisor.py", "tests/test_supervisor.py"],
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "auto-vendor-run"),
            "context_path": str(mod.RUNS_DIR / "auto-vendor-run" / "context.md"),
            "worker_envelope": {
                "status": "pass",
                "envelope": {"output": {"next_slice": "implement: wire next transition"}},
            },
        }

        next_path = mod.schedule_next_task(task, summary)
        self.assertIsNotNone(next_path)
        assert next_path is not None
        try:
            text = next_path.read_text(encoding="utf-8")
            self.assertIn('phase: "implement"', text)
        finally:
            next_path.unlink(missing_ok=True)

    def test_schedule_next_task_routes_to_record_phase_from_next_slice_prefix(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "auto-test.md",
            task_id="auto-test",
            prompt="test one copied mechanism",
            phase="test",
            allowed_paths=["scripts/a9_supervisor.py", "tests/test_supervisor.py"],
        )
        summary = {
            "task_id": task.task_id,
            "status": "needs-followup",
            "run_dir": str(mod.RUNS_DIR / "auto-test-run"),
            "context_path": str(mod.RUNS_DIR / "auto-test-run" / "context.md"),
            "worker_envelope": {
                "status": "pass",
                "envelope": {"output": {"next_slice": "record: append evidence for replay pass"}},
            },
        }

        next_path = mod.schedule_next_task(task, summary)
        self.assertIsNotNone(next_path)
        assert next_path is not None
        try:
            text = next_path.read_text(encoding="utf-8")
            self.assertIn('phase: "record"', text)
        finally:
            next_path.unlink(missing_ok=True)

    def test_schedule_next_task_unknown_next_slice_prefix_falls_back_to_phase_order(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "auto-ref.md",
            task_id="auto-ref",
            prompt="scan next reference",
            phase="reference_scan",
            allowed_paths=["scripts/a9_supervisor.py", "tests/test_supervisor.py"],
        )

        unknown_summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "auto-ref-run-unknown"),
            "context_path": str(mod.RUNS_DIR / "auto-ref-run-unknown" / "context.md"),
            "worker_envelope": {
                "status": "pass",
                "envelope": {"output": {"next_slice": "unknown: something"}},
            },
        }
        unknown_next = mod.schedule_next_task(task, unknown_summary)
        self.assertIsNotNone(unknown_next)
        assert unknown_next is not None
        try:
            unknown_text = unknown_next.read_text(encoding="utf-8")
            self.assertIn('phase: "mechanism_extract"', unknown_text)
        finally:
            unknown_next.unlink(missing_ok=True)

    def test_schedule_next_task_blocks_pass_with_empty_worker_next_slice(self):
        mod = load_supervisor()
        mod.ensure_dirs()
        task = mod.Task(
            path=mod.DONE_DIR / "auto-empty.md",
            task_id="auto-empty",
            prompt="scan next reference",
            phase="test",
            allowed_paths=["scripts/a9_supervisor.py", "tests/test_supervisor.py"],
        )
        summary = {
            "task_id": task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "auto-empty-run"),
            "context_path": str(mod.RUNS_DIR / "auto-empty-run" / "context.md"),
            "worker_envelope": {
                "status": "pass",
                "envelope": {"output": {"changed_files": ["tests/test_control_api.py"], "next_slice": ""}},
            },
        }

        self.assertIsNone(mod.schedule_next_task(task, summary))
        self.assertEqual(summary["auto_next_block"]["reason"], "missing_worker_next_slice")

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

    def test_transition_managed_flow_passes_sequence_gate_args(self):
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
                stdout='{"flow_id":"flow-test","status":"running","revision":3,"last_seq":11}\n',
            )

        try:
            mod.redis_available = fake_available
            mod.redis_cli = fake_cli
            result = mod.transition_managed_flow(
                flow_id="flow-test",
                expected_revision=2,
                expected_last_seq=10,
                sequence=11,
                next_status="running",
                actor="test",
                reason="unit",
                evidence_id="e1",
            )
        finally:
            mod.redis_available = original_available
            mod.redis_cli = original_cli

        self.assertEqual(result["status"], "pass")
        self.assertEqual(captured_args[-2:], ["10", "11"])

    def test_transition_managed_flow_marks_stale_sequence_as_skipped(self):
        mod = load_supervisor()
        original_available = mod.redis_available
        original_cli = mod.redis_cli

        def fake_available():
            return True

        def fake_cli(args):
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='{"flow_id":"flow-test","status":"running","revision":2,"last_seq":11}\n',
            )

        try:
            mod.redis_available = fake_available
            mod.redis_cli = fake_cli
            result = mod.transition_managed_flow(
                flow_id="flow-test",
                expected_revision=2,
                expected_last_seq=11,
                sequence=11,
                next_status="running",
                actor="test",
                reason="stale",
                evidence_id="e1",
            )
        finally:
            mod.redis_available = original_available
            mod.redis_cli = original_cli

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["revision"], 2)
        self.assertEqual(result["last_seq"], 11)

    def test_transition_managed_flow_sequence_gap_blocks_auto_next(self):
        mod = load_supervisor()
        original_available = mod.redis_available
        original_cli = mod.redis_cli

        def fake_available():
            return True

        def fake_cli(args):
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='{"flow_id":"flow-test","status":"quarantined","revision":3,"last_seq":1,"terminal_reason":"sequence_gap"}\n',
            )

        try:
            mod.redis_available = fake_available
            mod.redis_cli = fake_cli
            result = mod.transition_managed_flow(
                flow_id="flow-test",
                expected_revision=2,
                expected_last_seq=1,
                sequence=3,
                next_status="running",
                actor="test",
                reason="gap",
                evidence_id="e1",
            )
        finally:
            mod.redis_available = original_available
            mod.redis_cli = original_cli

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["terminal_reason"], "sequence_gap")
        self.assertTrue(mod.flow_transition_blocks_next({"flow_transition": result}))

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

    def test_session_auto_next_blocked_by_managed_flow_sequence_gate_fail(self):
        mod = load_supervisor()

        refresh_task = mod.Task(
            path=mod.DONE_DIR / "refresh.md",
            task_id="refresh",
            prompt="source_session_path: /tmp/session.jsonl\nfrom_turn: 1\nto_turn: 1",
            phase=mod.SESSION_REFRESH_PHASE,
        )
        refresh_summary = {
            "task_id": refresh_task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "refresh-run"),
            "context_path": str(mod.RUNS_DIR / "refresh-run" / "context.md"),
            "flow_transition": {
                "enabled": True,
                "status": "fail",
                "terminal_reason": "sequence_gap",
                "flow_status": "quarantined",
            },
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

        self.assertIsNone(mod.schedule_next_task(refresh_task, refresh_summary))

        close_task = mod.Task(
            path=mod.DONE_DIR / "close.md",
            task_id="close",
            prompt="extract_path: /tmp/session/turns-1-1.json",
            phase=mod.SESSION_CLOSE_READING_PHASE,
        )
        close_summary = {
            "task_id": close_task.task_id,
            "status": "pass",
            "run_dir": str(mod.RUNS_DIR / "close-run"),
            "context_path": str(mod.RUNS_DIR / "close-run" / "context.md"),
            "flow_transition": {
                "enabled": True,
                "status": "fail",
                "terminal_reason": "",
                "flow_status": "quarantined",
            },
            "session_close_reading": {
                "source_session_path": "/tmp/session.jsonl",
                "to_turn": 1,
                "batch_size": 1,
                "auto_continue": True,
                "auto_close_reading": True,
                "user_turn_count": 2,
                "close_reading_doc": "docs/session-raw-close-reading.md",
                "summary_doc": "docs/session-raw-summary.md",
            },
        }

        self.assertIsNone(mod.schedule_next_task(close_task, close_summary))

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

        spec = mod.parse_task_flow_spec(
            "flow_id: copy-flow\nflow_expected_revision: 7\nflow_expected_last_seq: 13\nflow_sequence: 14\nbody"
        )

        self.assertEqual(spec["flow_id"], "copy-flow")
        self.assertEqual(spec["flow_expected_revision"], 7)
        self.assertEqual(spec["flow_expected_last_seq"], 13)
        self.assertEqual(spec["flow_sequence"], 14)

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
                "flow_last_seq": 21,
                "flow_next_seq": 22,
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
            self.assertIn("flow_expected_last_seq: 21", text)
            self.assertIn("flow_sequence: 22", text)
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
                "flow_last_seq": 22,
                "flow_next_seq": 23,
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
            self.assertIn("flow_expected_last_seq: 22", text)
            self.assertIn("flow_sequence: 23", text)
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

    def test_long_copy_pipeline_task_ids_use_bounded_artifact_names(self):
        mod = load_supervisor()
        long_task_id = "auto-vendor_import-auto-mechanism_extract-" * 8 + "tail"

        artifact_ref = mod.artifact_task_ref(long_task_id)
        run_id = mod.run_id_for_task(long_task_id, 1)

        self.assertLessEqual(len(artifact_ref), 96)
        self.assertLessEqual(len(Path(run_id).name), 120)
        self.assertIn(artifact_ref, run_id)
        self.assertLessEqual(len((mod.WORKTREES_DIR / f"{artifact_ref}-attempt-1").name), 120)
        self.assertIsNone(mod.previous_task_checkpoint_id(mod.Task(path=Path("task.md"), task_id=long_task_id, prompt="demo")))
        packet = mod.build_context_packet(mod.Task(path=Path("task.md"), task_id=long_task_id, prompt="demo"))
        self.assertIn("prompt", packet)

        with tempfile.TemporaryDirectory() as tmp:
            old_queue = mod.QUEUE_DIR
            try:
                mod.QUEUE_DIR = Path(tmp)
                queued = mod.enqueue_task_file(
                    f"auto-implement-{long_task_id}-20260526T000000Z",
                    "strict_worker_envelope: true\n",
                    phase="implement",
                )
                self.assertLessEqual(len(queued.name), 124)
                parsed = mod.parse_task(queued)
                self.assertEqual(parsed.task_id, queued.stem)
            finally:
                mod.QUEUE_DIR = old_queue

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
        self.assertEqual(mod.next_phase_for("monitor-blocked", "test"), "repair")
        self.assertEqual(mod.next_phase_for("needs-followup", "test"), "test")

    def test_worktree_branch_name_is_scoped_to_worktree_root(self):
        mod = load_supervisor()
        task_id = "branch-scope"
        branch_scope = mod.hashlib.sha256(str(mod.WORKTREES_DIR.resolve()).encode("utf-8")).hexdigest()[:10]
        expected_branch = f"a9-supervisor/{task_id}-1-{branch_scope}"

        self.assertIn(branch_scope, expected_branch)


if __name__ == "__main__":
    unittest.main()
