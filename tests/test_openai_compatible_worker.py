#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "scripts" / "a9_openai_compatible_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("a9_openai_compatible_worker", WORKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class OpenAICompatibleWorkerTests(unittest.TestCase):
    def test_extract_declared_checks_from_a9_prompt(self):
        mod = load_worker()
        prompt = "# Header\n\n# Task Declared Checks\n\n- python3 -m unittest tests.test_x\n- none\n\n# Current Task\n\nDo it."
        self.assertEqual(mod.extract_declared_checks(prompt), ["python3 -m unittest tests.test_x"])

    def test_main_writes_model_strict_envelope(self):
        mod = load_worker()
        with tempfile.TemporaryDirectory() as tmp:
            prompt_path = Path(tmp) / "prompt.md"
            final_path = Path(tmp) / "final.md"
            prompt_path.write_text(
                "# Task Declared Checks\n\n- python3 -c 'print(\"ok\")'\n\n# Current Task\n\nReturn envelope.",
                encoding="utf-8",
            )
            envelope = {
                "protocolVersion": 1,
                "ok": True,
                "status": "ok",
                "output": {
                    "changed_files": [],
                    "search_replace_blocks": [],
                    "worker_commands_run": [],
                    "supervisor_declared_checks": ["python3 -c 'print(\"ok\")'"],
                    "copied_mechanisms": [],
                    "files_validated": [],
                    "repo_metadata_evidence": [],
                    "next_slice": "next",
                },
            }
            response = {
                "choices": [
                    {
                        "message": {
                            "content": "ignored prefix\n" + json.dumps(envelope) + "\nignored suffix",
                        }
                    }
                ]
            }
            old_argv = sys.argv
            old_key = os.environ.get("A9_LLM_WORKER_API_KEY")
            old_model = os.environ.get("A9_LLM_WORKER_MODEL")
            try:
                os.environ["A9_LLM_WORKER_API_KEY"] = "test-key"
                os.environ["A9_LLM_WORKER_MODEL"] = "test-model"
                sys.argv = [
                    "a9_openai_compatible_worker.py",
                    "--prompt-file",
                    str(prompt_path),
                    "--final-path",
                    str(final_path),
                    "--task-id",
                    "llm-worker-test",
                    "--phase",
                    "record",
                    "--base-url",
                    "http://127.0.0.1:9999/v1",
                ]
                with mock.patch.object(mod.urllib.request, "urlopen", return_value=FakeResponse(response)) as urlopen:
                    with redirect_stdout(io.StringIO()):
                        code = mod.main()
            finally:
                sys.argv = old_argv
                if old_key is None:
                    os.environ.pop("A9_LLM_WORKER_API_KEY", None)
                else:
                    os.environ["A9_LLM_WORKER_API_KEY"] = old_key
                if old_model is None:
                    os.environ.pop("A9_LLM_WORKER_MODEL", None)
                else:
                    os.environ["A9_LLM_WORKER_MODEL"] = old_model

            written = json.loads(final_path.read_text(encoding="utf-8"))
            request = urlopen.call_args.args[0]
            request_payload = json.loads(request.data.decode("utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(written["status"], "ok")
        self.assertEqual(written["output"]["supervisor_declared_checks"], ["python3 -c 'print(\"ok\")'"])
        self.assertEqual(request_payload["model"], "test-model")
        self.assertEqual(request.full_url, "http://127.0.0.1:9999/v1/chat/completions")

    def test_main_missing_api_key_writes_error_envelope(self):
        mod = load_worker()
        with tempfile.TemporaryDirectory() as tmp:
            prompt_path = Path(tmp) / "prompt.md"
            final_path = Path(tmp) / "final.md"
            prompt_path.write_text("# Task Declared Checks\n\n- none\n", encoding="utf-8")
            old_argv = sys.argv
            old_key = os.environ.pop("A9_LLM_WORKER_API_KEY", None)
            old_openai_key = os.environ.pop("OPENAI_API_KEY", None)
            old_model = os.environ.get("A9_LLM_WORKER_MODEL")
            try:
                os.environ["A9_LLM_WORKER_MODEL"] = "test-model"
                sys.argv = [
                    "a9_openai_compatible_worker.py",
                    "--prompt-file",
                    str(prompt_path),
                    "--final-path",
                    str(final_path),
                    "--task-id",
                    "missing-key-test",
                    "--phase",
                    "record",
                ]
                with redirect_stdout(io.StringIO()):
                    code = mod.main()
            finally:
                sys.argv = old_argv
                if old_key is not None:
                    os.environ["A9_LLM_WORKER_API_KEY"] = old_key
                if old_openai_key is not None:
                    os.environ["OPENAI_API_KEY"] = old_openai_key
                if old_model is None:
                    os.environ.pop("A9_LLM_WORKER_MODEL", None)
                else:
                    os.environ["A9_LLM_WORKER_MODEL"] = old_model

            written = json.loads(final_path.read_text(encoding="utf-8"))

        self.assertEqual(code, 70)
        self.assertFalse(written["ok"])
        self.assertIn("missing API key", written["error"]["message"])


if __name__ == "__main__":
    unittest.main()
