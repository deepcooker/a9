from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path
from unittest import mock

from scripts import a9_runtime_archive as mod


class RuntimeArchiveTests(unittest.TestCase):
    def test_run_candidates_keep_newest_and_plan_archive_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            archive = root / "archive"
            runs.mkdir()
            for index, name in enumerate(["old", "middle", "new"]):
                path = runs / name
                path.mkdir()
                timestamp = 1000 + index
                os.utime(path, (timestamp, timestamp))
            with mock.patch.object(mod, "RUNS_DIR", runs), mock.patch.object(mod, "ARCHIVE_DIR", archive):
                candidates = mod.run_candidates(keep_runs=1)

        self.assertEqual([candidate.path.name for candidate in candidates], ["old", "middle"])
        self.assertEqual(candidates[0].action, "move")
        self.assertIn("runs/19700101/old", str(candidates[0].archive_path))

    def test_worktree_candidates_protect_running_task_and_use_git_remove_for_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worktrees = root / "worktrees"
            tasks = root / "tasks"
            worktrees.mkdir()
            (tasks / "running").mkdir(parents=True)
            protected = worktrees / "active-task-attempt-1"
            registered = worktrees / "old-task-attempt-1"
            plain = worktrees / "plain-task-attempt-1"
            for index, path in enumerate([protected, registered, plain]):
                path.mkdir()
                os.utime(path, (1000 + index, 1000 + index))
            (tasks / "running" / "active-task.md").write_text("active", encoding="utf-8")
            with mock.patch.object(mod, "WORKTREES_DIR", worktrees), mock.patch.object(mod, "TASKS_DIR", tasks), mock.patch.object(
                mod, "git_worktree_paths", return_value={registered.resolve()}
            ):
                candidates = mod.worktree_candidates(keep_worktrees=0)

        by_name = {candidate.path.name: candidate for candidate in candidates}
        self.assertNotIn("active-task-attempt-1", by_name)
        self.assertEqual(by_name["old-task-attempt-1"].action, "git_worktree_remove")
        self.assertEqual(by_name["plain-task-attempt-1"].action, "move")

    def test_task_candidates_never_consider_queue_or_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks"
            for subdir in ["queue", "running", "done", "blocked", "interrupted"]:
                (tasks / subdir).mkdir(parents=True)
                (tasks / subdir / f"{subdir}.md").write_text(subdir, encoding="utf-8")
            with mock.patch.object(mod, "TASKS_DIR", tasks), mock.patch.object(mod, "ARCHIVE_DIR", root / "archive"):
                candidates = mod.task_candidates(keep_done_files=0)

        paths = [str(candidate.path) for candidate in candidates]
        self.assertFalse(any("/queue/" in path or "/running/" in path for path in paths))
        self.assertEqual({candidate.kind for candidate in candidates}, {"task_done", "task_blocked", "task_interrupted"})


if __name__ == "__main__":
    unittest.main()
