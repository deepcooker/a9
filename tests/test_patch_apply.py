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
