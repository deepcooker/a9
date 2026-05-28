#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_APPLY_PATH = ROOT / "scripts" / "a9_patch_apply.py"


def load_patch_apply():
    sys.path.insert(0, str(PATCH_APPLY_PATH.parent))
    spec = importlib.util.spec_from_file_location("a9_patch_apply", PATCH_APPLY_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PatchApplyTests(unittest.TestCase):
    def test_applies_exact_unique_search_replace(self):
        mod = load_patch_apply()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "scripts" / "demo.py"
            target.parent.mkdir()
            target.write_text("alpha\nbeta\n", encoding="utf-8")

            result = mod.apply_search_replace(
                """scripts/demo.py
<<<<<<< SEARCH
alpha
=======
gamma
>>>>>>> REPLACE
""",
                root,
            )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["applied_count"], 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "gamma\nbeta\n")

    def test_rejects_ambiguous_match_without_writing(self):
        mod = load_patch_apply()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.py"
            target.write_text("same\nsame\n", encoding="utf-8")

            result = mod.apply_search_replace(
                """demo.py
<<<<<<< SEARCH
same
=======
other
>>>>>>> REPLACE
""",
                root,
            )

            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["applied_count"], 0)
            self.assertEqual(result["failed_count"], 1)
            self.assertIn("SearchReplaceNoExactMatch", result["repair_hint"])
            self.assertIn("Did you mean", result["repair_hint"])
            self.assertEqual(target.read_text(encoding="utf-8"), "same\nsame\n")

    def test_empty_search_creates_new_file_only(self):
        mod = load_patch_apply()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = mod.apply_search_replace(
                """docs/new.md
<<<<<<< SEARCH
=======
# New
>>>>>>> REPLACE
""",
                root,
            )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["applied"][0]["mode"], "create")
            self.assertEqual((root / "docs" / "new.md").read_text(encoding="utf-8"), "# New\n")

    def test_partial_success_reports_successful_and_failed_blocks(self):
        mod = load_patch_apply()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.py"
            target.write_text("alpha\nsame\nsame\n", encoding="utf-8")

            result = mod.apply_search_replace(
                """demo.py
<<<<<<< SEARCH
alpha
=======
gamma
>>>>>>> REPLACE
demo.py
<<<<<<< SEARCH
same
=======
other
>>>>>>> REPLACE
""",
                root,
            )

            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["applied_count"], 1)
            self.assertEqual(result["failed_count"], 1)
            self.assertTrue(result["partial_success"])
            self.assertEqual(result["successful_blocks"][0]["index"], 1)
            self.assertEqual(result["failed_blocks"][0]["index"], 2)
            self.assertIn("Do not resend successful blocks", result["repair_hint"])
            self.assertIn("block 1: demo.py", result["repair_hint"])
            self.assertEqual(target.read_text(encoding="utf-8"), "gamma\nsame\nsame\n")

    def test_leading_whitespace_fuzz_is_controlled_and_recorded(self):
        mod = load_patch_apply()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.py"
            target.write_text("def run():\n    alpha\n    beta\n", encoding="utf-8")

            result = mod.apply_search_replace(
                """demo.py
<<<<<<< SEARCH
alpha
beta
=======
gamma
delta
>>>>>>> REPLACE
""",
                root,
            )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["applied"][0]["match_strategy"], "leading_whitespace")
            self.assertEqual(result["applied"][0]["fuzz_level"], 1)
            self.assertIn("controlled fuzz", result["findings"][0]["message"])
            self.assertEqual(target.read_text(encoding="utf-8"), "def run():\n    gamma\n    delta\n")

    def test_leading_whitespace_fuzz_rejects_ambiguous_matches(self):
        mod = load_patch_apply()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.py"
            target.write_text("    alpha\nalpha\n", encoding="utf-8")

            result = mod.apply_search_replace(
                """demo.py
<<<<<<< SEARCH
alpha
=======
gamma
>>>>>>> REPLACE
""",
                root,
            )

            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["applied_count"], 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "    alpha\nalpha\n")

    def test_already_applied_replace_is_success_without_writing(self):
        mod = load_patch_apply()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.py"
            target.write_text("gamma\n", encoding="utf-8")

            result = mod.apply_search_replace(
                """demo.py
<<<<<<< SEARCH
alpha
=======
gamma
>>>>>>> REPLACE
""",
                root,
            )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["applied_count"], 0)
            self.assertEqual(result["already_applied_count"], 1)
            self.assertEqual(result["success_count"], 1)
            self.assertEqual(result["successful_blocks"][0]["mode"], "already_applied")
            self.assertEqual(result["successful_blocks"][0]["replace_matches"], 1)
            self.assertEqual(result["touched_files"], [])
            self.assertEqual(result["referenced_files"], ["demo.py"])
            self.assertIn("already applied", result["findings"][0]["message"])
            self.assertEqual(target.read_text(encoding="utf-8"), "gamma\n")

    def test_already_applied_ambiguous_replace_still_fails(self):
        mod = load_patch_apply()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.py"
            target.write_text("gamma\ngamma\n", encoding="utf-8")

            result = mod.apply_search_replace(
                """demo.py
<<<<<<< SEARCH
alpha
=======
gamma
>>>>>>> REPLACE
""",
                root,
            )

            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["applied_count"], 0)
            self.assertEqual(result["already_applied_count"], 0)
            self.assertEqual(result["failed_count"], 1)
            self.assertIn("REPLACE appears 2 times", result["failed_blocks"][0]["repair_hint"])
            self.assertEqual(target.read_text(encoding="utf-8"), "gamma\ngamma\n")

    def test_normalizes_filename_and_fence_wrapping(self):
        mod = load_patch_apply()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.py"
            target.write_text("alpha\n", encoding="utf-8")

            result = mod.apply_search_replace(
                """demo.py
<<<<<<< SEARCH
demo.py
```python
alpha
```
=======
```python
gamma
```
>>>>>>> REPLACE
""",
                root,
            )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(
                result["applied"][0]["normalizations"],
                ["search:filename_line", "search:fence", "replace:fence"],
            )
            self.assertIn("normalized wrapped", result["findings"][0]["message"])
            self.assertEqual(target.read_text(encoding="utf-8"), "gamma\n")

    def test_records_path_normalizations_from_guard_parser(self):
        mod = load_patch_apply()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.py"
            target.write_text("alpha\n", encoding="utf-8")

            result = mod.apply_search_replace(
                """# `demo.py`:
<<<<<<< SEARCH
alpha
=======
gamma
>>>>>>> REPLACE
""",
                root,
            )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(
                result["applied"][0]["normalizations"],
                ["path:trailing_colon", "path:leading_hash", "path:inline_markup"],
            )
            self.assertEqual(target.read_text(encoding="utf-8"), "gamma\n")

    def test_applies_embedded_inline_path_heading(self):
        mod = load_patch_apply()
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
            result = mod.apply_search_replace(patch, root)

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["applied"][0]["effective_path"], "docs/mistakes.md")
            self.assertIn("path:embedded_inline_path", result["applied"][0]["normalizations"])
            self.assertEqual(target.read_text(encoding="utf-8"), "gamma\n")

    def test_unique_basename_path_resolves_to_repository_file(self):
        mod = load_patch_apply()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "scripts" / "demo.py"
            target.parent.mkdir()
            target.write_text("alpha\n", encoding="utf-8")

            result = mod.apply_search_replace(
                """demo.py
<<<<<<< SEARCH
alpha
=======
gamma
>>>>>>> REPLACE
""",
                root,
            )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["applied"][0]["effective_path"], "scripts/demo.py")
            self.assertIn("path:basename_unique", result["applied"][0]["normalizations"])
            self.assertEqual(result["touched_files"], ["scripts/demo.py"])
            self.assertEqual(target.read_text(encoding="utf-8"), "gamma\n")

    def test_ambiguous_basename_path_fails_with_candidates(self):
        mod = load_patch_apply()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ("scripts/demo.py", "tests/demo.py"):
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("alpha\n", encoding="utf-8")

            result = mod.apply_search_replace(
                """demo.py
<<<<<<< SEARCH
alpha
=======
gamma
>>>>>>> REPLACE
""",
                root,
            )

            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["applied_count"], 0)
            self.assertEqual(result["failed_blocks"][0]["path_candidates"], ["scripts/demo.py", "tests/demo.py"])
            self.assertIn("Candidate files", result["repair_hint"])
            self.assertEqual((root / "scripts" / "demo.py").read_text(encoding="utf-8"), "alpha\n")
            self.assertEqual((root / "tests" / "demo.py").read_text(encoding="utf-8"), "alpha\n")

    def test_dry_run_does_not_write(self):
        mod = load_patch_apply()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.py"
            target.write_text("old\n", encoding="utf-8")

            result = mod.apply_search_replace(
                """demo.py
<<<<<<< SEARCH
old
=======
new
>>>>>>> REPLACE
""",
                root,
                dry_run=True,
            )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")

    def test_cli_returns_nonzero_on_failed_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patch = root / "bad.patch"
            patch.write_text(
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
                [sys.executable, str(PATCH_APPLY_PATH), str(patch), "--root", str(root)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('"status": "fail"', result.stdout)


if __name__ == "__main__":
    unittest.main()
