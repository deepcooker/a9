#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCOPE_GUARD_PATH = ROOT / "scripts" / "a9_scope_guard.py"


def load_scope_guard():
    spec = importlib.util.spec_from_file_location("a9_scope_guard", SCOPE_GUARD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ScopeGuardTests(unittest.TestCase):
    def test_allows_changed_files_under_allowed_prefix(self):
        mod = load_scope_guard()
        patch = """diff --git a/scripts/a9_scope_guard.py b/scripts/a9_scope_guard.py
--- a/scripts/a9_scope_guard.py
+++ b/scripts/a9_scope_guard.py
@@ -1 +1 @@
-old
+new
"""
        result = mod.validate_diff(patch, ["scripts/"])

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["changed_files"], ["scripts/a9_scope_guard.py"])

    def test_rejects_outside_allowed_paths(self):
        mod = load_scope_guard()
        patch = """diff --git a/docs/project.md b/docs/project.md
--- a/docs/project.md
+++ b/docs/project.md
@@ -1 +1 @@
-old
+new
"""
        result = mod.validate_diff(patch, ["scripts/"])

        self.assertEqual(result["status"], "fail")
        self.assertIn("outside allowed_paths", result["findings"][0]["message"])

    def test_rejects_vendor_and_sensitive_paths_by_default(self):
        mod = load_scope_guard()
        patch = """diff --git a/vendor-src/aider/LICENSE.txt b/vendor-src/aider/LICENSE.txt
--- a/vendor-src/aider/LICENSE.txt
+++ b/vendor-src/aider/LICENSE.txt
@@ -1 +1 @@
-old
+new
diff --git a/.env b/.env
--- a/.env
+++ b/.env
@@ -1 +1 @@
-old
+new
"""
        result = mod.validate_diff(patch, [])

        self.assertEqual(result["status"], "fail")
        messages = "\n".join(item["message"] for item in result["findings"])
        self.assertIn("blocked path component: vendor-src", messages)
        self.assertIn("sensitive credential/config path", messages)

    def test_cli_returns_nonzero_on_scope_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patch_path = root / "bad.patch"
            patch_path.write_text(
                """diff --git a/docs/project.md b/docs/project.md
--- a/docs/project.md
+++ b/docs/project.md
@@ -1 +1 @@
-old
+new
""",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCOPE_GUARD_PATH), str(patch_path), "--allow", "scripts/"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('"status": "fail"', result.stdout)


if __name__ == "__main__":
    unittest.main()
