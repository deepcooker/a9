#!/usr/bin/env python3
"""A9 MemPalace provider facade.

This is the first runtime-facing MemPalace lane. It consumes the
MemPalace-compatible drawer JSONL produced by ``a9_codex_session_adapter.py``
and exposes status/search/wakeup without making the supervisor depend on a
global MemPalace install. Native MemPalace can be enabled later when its
dependencies are available; this fallback keeps A9 usable today.
"""

from __future__ import annotations

import argparse
import contextlib
import heapq
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRAWERS = ROOT / ".a9" / "mempalace" / "operator-session-drawers.jsonl"
DEFAULT_PALACE = ROOT / ".a9" / "mempalace"
MEMPALACE_SOURCE = ROOT / "reference-projects" / "mempalace"
TOKEN_RE = re.compile(r"\w{2,}", re.UNICODE)


@contextlib.contextmanager
def suppress_native_stderr() -> Iterable[None]:
    """Suppress C-extension stderr noise during native Chroma/ONNX calls.

    onnxruntime can emit GPU discovery warnings directly to file descriptor 2,
    bypassing Python logging and ``contextlib.redirect_stderr``. A9 provider
    commands must remain machine-readable JSON, so native recall calls are
    isolated from that noise.
    """
    saved = os.dup(2)
    try:
        with open(os.devnull, "w", encoding="utf-8") as sink:
            os.dup2(sink.fileno(), 2)
            yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


def read_drawers(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no}: invalid drawer JSONL: {exc}") from exc


def compact(text: str, limit: int = 420) -> str:
    value = re.sub(r"\s+", " ", text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def native_status(palace: Path = DEFAULT_PALACE) -> dict[str, Any]:
    status: dict[str, Any] = {
        "source_path": str(MEMPALACE_SOURCE),
        "source_exists": MEMPALACE_SOURCE.exists(),
        "palace_path": str(palace),
        "palace_chroma_exists": (palace / "chroma.sqlite3").exists(),
        "python_import": False,
        "native_collection_ready": False,
        "drawer_count": None,
        "version": None,
        "error": None,
    }
    if not MEMPALACE_SOURCE.exists():
        status["error"] = "reference-projects/mempalace missing"
        return status
    sys.path.insert(0, str(MEMPALACE_SOURCE))
    try:
        import mempalace  # type: ignore

        status["python_import"] = True
        status["version"] = getattr(mempalace, "__version__", None)
    except Exception as exc:  # pragma: no cover - environment dependent
        status["error"] = f"{type(exc).__name__}: {exc}"
        return status
    try:
        with suppress_native_stderr():
            from mempalace.palace import get_collection  # type: ignore

            if status["palace_chroma_exists"]:
                collection = get_collection(str(palace), create=False)
                status["drawer_count"] = collection.count()
                status["native_collection_ready"] = True
    except Exception as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def native_search(
    query: str,
    *,
    limit: int = 8,
    wing: str | None = None,
    room: str | None = None,
    palace: Path = DEFAULT_PALACE,
) -> dict[str, Any] | None:
    """Search the native MemPalace index when it has been mined.

    The fallback drawer JSONL remains the line-level evidence ledger. Native
    search is the scalable recall path; fallback search is the deterministic
    recovery path when Chroma/native dependencies are unavailable.
    """
    if not (palace / "chroma.sqlite3").exists():
        return None
    if not MEMPALACE_SOURCE.exists():
        return None
    sys.path.insert(0, str(MEMPALACE_SOURCE))
    try:
        with suppress_native_stderr():
            from mempalace.searcher import search_memories  # type: ignore

            payload = search_memories(
                query,
                str(palace),
                wing=wing,
                room=room,
                n_results=limit,
            )
    except Exception as exc:  # pragma: no cover - environment/index dependent
        return {
            "source": "native_mempalace",
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "results": [],
        }
    if payload.get("error"):
        return {
            "source": "native_mempalace",
            "status": "error",
            "error": payload.get("error"),
            "results": [],
        }
    results: list[dict[str, Any]] = []
    for row in payload.get("results") or []:
        results.append(
            {
                "score": row.get("similarity"),
                "similarity": row.get("similarity"),
                "distance": row.get("distance"),
                "effective_distance": row.get("effective_distance"),
                "bm25_score": row.get("bm25_score"),
                "matched_via": row.get("matched_via"),
                "wing": row.get("wing"),
                "room": row.get("room"),
                "source_file": row.get("source_file"),
                "created_at": row.get("created_at"),
                "content": compact(str(row.get("text") or "")),
            }
        )
    return {
        "source": "native_mempalace",
        "status": "ok",
        "palace_path": str(palace),
        "filters": payload.get("filters") or {"wing": wing, "room": room},
        "total_before_filter": payload.get("total_before_filter"),
        "results": results,
    }


def drawer_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "drawers_path": str(path),
            "exists": False,
            "drawer_count": 0,
            "roles": {},
            "event_kinds": {},
        }
    roles: Counter[str] = Counter()
    events: Counter[str] = Counter()
    sessions: Counter[str] = Counter()
    source_sha256 = ""
    count = 0
    for row in read_drawers(path):
        count += 1
        roles[str(row.get("role") or "unknown")] += 1
        events[str(row.get("event_kind") or "unknown")] += 1
        sessions[str(row.get("session_id") or "unknown")] += 1
        source_sha256 = str(row.get("source_sha256") or source_sha256)
    return {
        "drawers_path": str(path),
        "exists": True,
        "drawer_count": count,
        "source_sha256": source_sha256,
        "roles": dict(roles.most_common()),
        "event_kinds": dict(events.most_common()),
        "sessions": dict(sessions.most_common(5)),
    }


def score_drawer(query: str, query_terms: set[str], row: dict[str, Any]) -> float:
    content = str(row.get("content") or "")
    lower = content.lower()
    tokens = set(tokenize(content))
    overlap = len(query_terms & tokens)
    if not overlap and query.lower() not in lower:
        return 0.0
    score = float(overlap * 3)
    if query.lower() in lower:
        score += 8.0
    role = row.get("role")
    event_kind = row.get("event_kind")
    if role == "user":
        score += 1.5
    if role == "assistant":
        score += 1.0
    if event_kind == "tool_call":
        score += 0.8
    if event_kind == "tool_output":
        score += 0.4
    return score


def search_drawers(
    path: Path,
    query: str,
    *,
    limit: int = 8,
    role: str | None = None,
    event_kind: str | None = None,
) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"drawer JSONL not found: {path}")
    query_terms = set(tokenize(query))
    if not query_terms:
        raise SystemExit("query must contain at least one token")
    heap: list[tuple[float, int, dict[str, Any]]] = []
    scanned = 0
    for row in read_drawers(path):
        scanned += 1
        if role and row.get("role") != role:
            continue
        if event_kind and row.get("event_kind") != event_kind:
            continue
        score = score_drawer(query, query_terms, row)
        if score <= 0:
            continue
        item = {
            "score": round(score, 3),
            "role": row.get("role"),
            "event_kind": row.get("event_kind"),
            "timestamp": row.get("timestamp"),
            "source_ref": row.get("source_ref"),
            "source_sha256": row.get("source_sha256"),
            "content_hash": row.get("content_hash"),
            "drawer_id": row.get("drawer_id"),
            "content": compact(str(row.get("content") or "")),
        }
        entry = (score, scanned, item)
        if len(heap) < limit:
            heapq.heappush(heap, entry)
        elif entry > heap[0]:
            heapq.heapreplace(heap, entry)
    return [item for _, _, item in sorted(heap, reverse=True)]


def build_wakeup(
    path: Path,
    *,
    query: str,
    limit: int,
    native_enabled: bool = True,
    palace: Path = DEFAULT_PALACE,
) -> dict[str, Any]:
    native = native_search(query, limit=limit, wing="operator-codex", palace=palace) if native_enabled else None
    hits = search_drawers(path, query, limit=limit, event_kind="message")
    native_hits = native.get("results", []) if native and native.get("status") == "ok" else []
    return {
        "schema": "a9.wakeup_pack.v1",
        "source": "native_mempalace+fallback_drawer_jsonl" if native_hits else "mempalace-compatible-drawer-jsonl",
        "truth_policy": "recall_not_truth",
        "query": query,
        "required_read_order": ["AGENTS.md", "docs/project.md", "docs/method.md", "docs/session.md"],
        "must_not_do": [
            "Do not treat recall as truth.",
            "Do not inject full raw recall into execution workers.",
            "Do not replace raw JSONL or evidence hashes with summaries.",
        ],
        "native_recall": native_hits,
        "evidence_refs": [
            {
                "source_ref": hit["source_ref"],
                "source_sha256": hit["source_sha256"],
                "content_hash": hit["content_hash"],
                "role": hit["role"],
                "event_kind": hit["event_kind"],
                "score": hit["score"],
            }
            for hit in hits
        ],
        "recall": hits,
    }


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="A9 MemPalace provider facade")
    parser.add_argument("--drawers", default=str(DEFAULT_DRAWERS), help="MemPalace-compatible drawer JSONL")
    parser.add_argument("--palace", default=str(DEFAULT_PALACE), help="Native MemPalace palace directory")
    parser.add_argument(
        "--native-mode",
        choices=["auto", "native", "fallback"],
        default="auto",
        help="Search native MemPalace first, force native, or force fallback drawer JSONL",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")

    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--role")
    search.add_argument("--event-kind")
    search.add_argument("--wing", default="operator-codex")
    search.add_argument("--room")

    wakeup = sub.add_parser("wakeup")
    wakeup.add_argument("--query", default="A9 MemPalace current mainline next action")
    wakeup.add_argument("--limit", type=int, default=8)

    args = parser.parse_args()
    drawers = Path(args.drawers)
    palace = Path(args.palace)
    native_enabled = args.native_mode != "fallback" and drawers == DEFAULT_DRAWERS

    if args.command == "status":
        print_json(
            {
                "schema": "a9.mempalace_provider_status.v1",
                "native_mempalace": native_status(palace if native_enabled else Path("/nonexistent-a9-mempalace-disabled")),
                "fallback_drawers": drawer_status(drawers),
            }
        )
    elif args.command == "search":
        use_native = args.native_mode in {"auto", "native"} and drawers == DEFAULT_DRAWERS
        native = (
            native_search(
                args.query,
                limit=args.limit,
                wing=args.wing,
                room=args.room,
                palace=palace,
            )
            if use_native
            else None
        )
        if native and native.get("status") == "ok":
            print_json(
                {
                    "schema": "a9.mempalace_search.v1",
                    "query": args.query,
                    "truth_policy": "recall_not_truth",
                    **native,
                }
            )
            return 0
        if args.native_mode == "native":
            print_json(
                {
                    "schema": "a9.mempalace_search.v1",
                    "query": args.query,
                    "truth_policy": "recall_not_truth",
                    "source": "native_mempalace",
                    "status": "error",
                    "error": (native or {}).get("error") or "native palace index unavailable",
                    "results": [],
                }
            )
            return 0
        print_json(
            {
                "schema": "a9.mempalace_search.v1",
                "query": args.query,
                "truth_policy": "recall_not_truth",
                "source": "mempalace-compatible-drawer-jsonl",
                "native_fallback_reason": None if not native else native.get("error"),
                "results": search_drawers(
                    drawers,
                    args.query,
                    limit=args.limit,
                    role=args.role,
                    event_kind=args.event_kind,
                ),
            }
        )
    elif args.command == "wakeup":
        print_json(
            build_wakeup(
                drawers,
                query=args.query,
                limit=args.limit,
                native_enabled=native_enabled,
                palace=palace,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
