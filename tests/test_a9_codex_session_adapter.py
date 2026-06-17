import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "a9_codex_session_adapter.py"


def load_adapter():
    spec = importlib.util.spec_from_file_location("a9_codex_session_adapter", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def message_row(role: str, text: str) -> dict:
    want_type = "output_text" if role == "assistant" else "input_text"
    return {
        "type": "response_item",
        "timestamp": "2026-06-17T00:00:00Z",
        "payload": {
            "type": "message",
            "role": role,
            "content": [{"type": want_type, "text": text}],
        },
    }


class IncrementalIngestTest(unittest.TestCase):
    def test_incremental_ingest_appends_only_new_rows(self):
        adapter = load_adapter()
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            session = tmp_path / "session.jsonl"
            drawers = tmp_path / "drawers.jsonl"
            cursor = tmp_path / "cursor.json"

            append_jsonl(session, {"type": "session_meta", "payload": {"id": "sess-1"}})
            append_jsonl(session, message_row("user", "first"))

            first = adapter.incremental_ingest(session, out_path=drawers, cursor_path=cursor)
            self.assertEqual(first["rows_read"], 2)
            self.assertEqual(first["drawers_found"], 1)
            self.assertEqual(first["drawers_written"], 1)
            self.assertEqual(len(drawers.read_text(encoding="utf-8").splitlines()), 1)

            append_jsonl(session, message_row("assistant", "second"))
            second = adapter.incremental_ingest(session, out_path=drawers, cursor_path=cursor)

            self.assertEqual(second["previous_byte_offset"], first["byte_offset"])
            self.assertEqual(second["rows_read"], 1)
            self.assertEqual(second["drawers_found"], 1)
            self.assertEqual(second["drawers_written"], 1)
            lines = [json.loads(line) for line in drawers.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([line["content"] for line in lines], ["first", "second"])
            self.assertEqual(json.loads(cursor.read_text(encoding="utf-8"))["ordinal"], 2)

    def test_incremental_ingest_dry_run_does_not_write(self):
        adapter = load_adapter()
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            session = tmp_path / "session.jsonl"
            drawers = tmp_path / "drawers.jsonl"
            cursor = tmp_path / "cursor.json"

            append_jsonl(session, {"type": "session_meta", "payload": {"id": "sess-1"}})
            append_jsonl(session, message_row("user", "first"))

            result = adapter.incremental_ingest(
                session,
                out_path=drawers,
                cursor_path=cursor,
                dry_run=True,
            )

            self.assertEqual(result["status"], "dry-run")
            self.assertEqual(result["drawers_found"], 1)
            self.assertEqual(result["drawers_written"], 0)
            self.assertFalse(drawers.exists())
            self.assertFalse(cursor.exists())

    def test_init_cursor_from_existing_drawers(self):
        adapter = load_adapter()
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            session = tmp_path / "session.jsonl"
            drawers = tmp_path / "drawers.jsonl"
            cursor = tmp_path / "cursor.json"

            append_jsonl(session, {"type": "session_meta", "payload": {"id": "sess-1"}})
            append_jsonl(session, message_row("user", "first"))
            adapter.incremental_ingest(session, out_path=drawers, cursor_path=cursor)

            cursor.unlink()
            result = adapter.init_incremental_cursor_from_drawers(
                session,
                drawers_path=drawers,
                cursor_path=cursor,
            )

            self.assertEqual(result["line_no"], 2)
            self.assertEqual(result["ordinal"], 1)
            self.assertTrue(result["byte_offset"] > 0)
            self.assertEqual(json.loads(cursor.read_text(encoding="utf-8"))["line_no"], 2)


if __name__ == "__main__":
    unittest.main()
