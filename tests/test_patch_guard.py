#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_GUARD_PATH = ROOT / "scripts" / "a9_patch_guard.py"


def load_patch_guard():
    spec = importlib.util.spec_from_file_location("a9_patch_guard", PATCH_GUARD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PatchGuardTests(unittest.TestCase):
    def test_search_replace_requires_exact_unique_match(self):
        mod = load_patch_guard()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "scripts" / "demo.py"
            target.parent.mkdir()
            target.write_text("alpha\nbeta\n", encoding="utf-8")

            patch = """scripts/demo.py
<<<<<<< SEARCH
alpha
=======
gamma
>>>>>>> REPLACE
"""
            result = mod.validate(patch, root, "auto")

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["kind"], "search_replace")
        self.assertEqual(result["touched_files"], ["scripts/demo.py"])

    def test_search_replace_accepts_path_before_markdown_fence(self):
        mod = load_patch_guard()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "scripts" / "demo.py"
            target.parent.mkdir()
            target.write_text("alpha\nbeta\n", encoding="utf-8")

            patch = """scripts/demo.py
```python
<<<<<<< SEARCH
alpha
=======
gamma
>>>>>>> REPLACE
```
"""
            result = mod.validate(patch, root, "auto")

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["kind"], "search_replace")
        self.assertEqual(result["touched_files"], ["scripts/demo.py"])

    def test_search_replace_normalizes_wrapped_path_lines(self):
        mod = load_patch_guard()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "scripts" / "demo.py"
            target.parent.mkdir()
            target.write_text("alpha\n", encoding="utf-8")

            patch = """# `scripts/demo.py`:
<<<<<<< SEARCH
alpha
=======
gamma
>>>>>>> REPLACE
```python scripts/demo.py
<<<<<<< SEARCH
alpha
=======
gamma
>>>>>>> REPLACE
"""
            blocks, findings = mod.parse_search_replace(patch)
            result = mod.validate(patch, root, "auto")

        self.assertEqual([block.path for block in blocks], ["scripts/demo.py", "scripts/demo.py"])
        self.assertEqual(blocks[0].path_normalizations, ["path:trailing_colon", "path:leading_hash", "path:inline_markup"])
        self.assertEqual(blocks[1].path_normalizations, ["path:fence_language_prefix"])
        self.assertEqual(findings, [])
        self.assertEqual(result["status"], "pass")

    def test_search_replace_extracts_embedded_inline_path(self):
        mod = load_patch_guard()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "docs" / "mistakes.md"
            target.parent.mkdir()
            target.write_text("alpha\n", encoding="utf-8")

            patch = (
                "SEARCH/REPLACE block for `docs/mistakes.md`:\n"
                "<<<<<<< SEARCH\n"
                "alpha\n"
                "=======\n"
                "gamma\n"
                ">>>>>>> REPLACE\n"
            )
            blocks, findings = mod.parse_search_replace(patch)
            result = mod.validate(patch, root, "auto")

        self.assertEqual(blocks[0].path, "docs/mistakes.md")
        self.assertEqual(blocks[0].path_normalizations, ["path:trailing_colon", "path:embedded_inline_path"])
        self.assertEqual(findings, [])
        self.assertEqual(result["status"], "pass")

    def test_search_replace_rejects_ambiguous_match(self):
        mod = load_patch_guard()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.py"
            target.write_text("same\nsame\n", encoding="utf-8")

            patch = """demo.py
<<<<<<< SEARCH
same
=======
other
>>>>>>> REPLACE
"""
            result = mod.validate(patch, root, "auto")

        self.assertEqual(result["status"], "fail")
        self.assertIn("found 2", result["findings"][0]["message"])

    def test_rejects_vendor_and_traversal_paths(self):
        mod = load_patch_guard()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patch = """diff --git a/vendor-src/aider/aider/history.py b/vendor-src/aider/aider/history.py
--- a/vendor-src/aider/aider/history.py
+++ b/vendor-src/aider/aider/history.py
@@ -1 +1 @@
-old
+new
diff --git a/../escape.py b/../escape.py
--- a/../escape.py
+++ b/../escape.py
@@ -1 +1 @@
-old
+new
"""
            result = mod.validate(patch, root, "unified_diff")

        self.assertEqual(result["status"], "fail")
        messages = "\n".join(item["message"] for item in result["findings"])
        self.assertIn("blocked path component: vendor-src", messages)
        self.assertIn("path traversal is not allowed", messages)

    def test_cli_returns_nonzero_on_failed_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patch_path = root / "bad.patch"
            patch_path.write_text(
                """missing.py
<<<<<<< SEARCH
nope
=======
ok
>>>>>>> REPLACE
""",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(PATCH_GUARD_PATH), str(patch_path), "--root", str(root)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('"status": "fail"', result.stdout)

    def test_malformed_search_replace_returns_json_failure(self):
        mod = load_patch_guard()
        result = mod.validate("<<<<<<< SEARCH\nold\n", Path.cwd(), "search_replace")

        self.assertEqual(result["status"], "fail")
        self.assertIn("no preceding file path", result["findings"][0]["message"])


if __name__ == "__main__":
    unittest.main()
