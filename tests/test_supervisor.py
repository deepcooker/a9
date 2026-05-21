#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
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
timeout_seconds: 12
idle_timeout_seconds: 3
max_attempts: 4
checks:
  - "python --version"
---
Do the work.
""",
                encoding="utf-8",
            )
            task = mod.parse_task(task_path)
        self.assertEqual(task.task_id, "sample")
        self.assertEqual(task.timeout_seconds, 12)
        self.assertEqual(task.idle_timeout_seconds, 3)
        self.assertEqual(task.max_attempts, 4)
        self.assertEqual(task.checks, ["python --version"])
        self.assertEqual(task.prompt, "Do the work.")

    def test_supervisor_fake_worker_end_to_end(self):
        env = os.environ.copy()
        env["A9_SUPERVISOR_WORKER_CMD"] = (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "import json\n"
            "print(json.dumps({'type':'fake.start'}))\n"
            "Path('worker-output.txt').write_text('done\\n')\n"
            "Path('{run_dir}/final.md').write_text('ok\\n')\n"
            "print(json.dumps({'type':'fake.done'}))\n"
            "PY"
        )
        task_id = "selftest-supervisor"
        queue_path = ROOT / ".a9" / "tasks" / "queue" / f"{task_id}.md"
        done_path = ROOT / ".a9" / "tasks" / "done" / f"{task_id}.json"
        if queue_path.exists():
            queue_path.unlink()
        if done_path.exists():
            done_path.unlink()

        subprocess.run([str(SUPERVISOR_PATH), "init"], cwd=ROOT, check=True)
        subprocess.run(
            [
                str(SUPERVISOR_PATH),
                "enqueue",
                task_id,
                "fake task",
                "--check",
                "test -f worker-output.txt",
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
        self.assertEqual(data["status"], "pass")
        self.assertGreater(data["diff"]["diff_bytes"], 0)
        evidence_path = Path(data["evidence_path"])
        state_path = Path(data["state_path"])
        deep_marks_path = Path(data["deep_marks_path"])
        self.assertTrue(evidence_path.exists())
        self.assertTrue(state_path.exists())
        self.assertTrue(deep_marks_path.exists())

        evidence = [
            json.loads(line)
            for line in evidence_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        kinds = {item["kind"] for item in evidence}
        self.assertIn("prompt", kinds)
        self.assertIn("events", kinds)
        self.assertIn("patch", kinds)
        self.assertIn("check_log", kinds)
        self.assertIn("context", kinds)
        self.assertTrue(all(item["sha256"] for item in evidence))

        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["session_id"], task_id)
        self.assertEqual(state["status"], "pass")
        self.assertTrue(state["channels"]["checks"])
        self.assertTrue(state["channels"]["deep_marks"])
        self.assertGreater(state["deep_mark_count"], 0)
        self.assertEqual(len(state["evidence_ids"]), len(evidence))

        deep_marks = [
            json.loads(line)
            for line in deep_marks_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        mark_kinds = {item["kind"] for item in deep_marks}
        self.assertIn("check_result", mark_kinds)
        self.assertIn("changed_file", mark_kinds)


if __name__ == "__main__":
    unittest.main()
