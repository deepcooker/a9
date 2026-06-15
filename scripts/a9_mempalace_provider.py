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
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRAWERS = ROOT / ".a9" / "mempalace" / "operator-session-drawers.jsonl"
DEFAULT_PALACE = ROOT / ".a9" / "mempalace"
DEFAULT_NATIVE_WING = "operator-codex-native"
DEFAULT_NATIVE_ROOM = "codex-message"
MEMPALACE_SOURCE = ROOT / "reference-projects" / "mempalace"
TOKEN_RE = re.compile(r"\w{2,}", re.UNICODE)
ROLE_KEYWORDS = {
    "product": ("产品", "业务", "需求", "主线", "哲学", "数据第一", "must", "should", "out of scope"),
    "architecture": ("架构", "状态", "数据", "Redis", "MySQL", "supervisor", "runtime", "gateway", "SSH", "tmux"),
    "test": ("测试", "验收", "checks", "acceptance", "验证", "回归", "质量"),
    "execution": ("执行", "worker", "allowed_paths", "execution_next", "backlog", "任务"),
    "monitor": ("监控", "monitor", "偏离", "纠偏", "漂移", "review", "closure", "证据"),
}
STALE_MARKERS = ("过期", "不再", "不是主", "旧", "stale", "deprecated", "不要再", "不维护", "已删除")
CURRENT_MARKERS = ("当前", "现在", "已完成", "必须", "核心", "主线", "decision", "accepted", "status")
CAUSAL_MARKERS = ("因为", "所以", "后来", "变成", "从", "->", "原因", "导致", "replaced", "became")


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


def is_context_injection(content: str) -> bool:
    text = (content or "").lstrip()
    return text.startswith("# AGENTS.md instructions for ") or (
        "<INSTRUCTIONS>" in text and "<environment_context>" in text
    )


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


def distance_to_similarity(distance: Any) -> float | None:
    if distance is None:
        return None
    try:
        value = float(distance)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return round(1.0 / (1.0 + math.exp(min(60.0, value))), 3)
    return round(max(0.0, 1.0 - value), 3)


def build_native_where(wing: str | None, room: str | None) -> dict[str, Any] | None:
    conditions: list[dict[str, str]] = []
    if wing:
        conditions.append({"wing": wing})
    if room:
        conditions.append({"room": room})
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def native_query_drawers(
    query: str,
    *,
    limit: int = 8,
    wing: str | None = None,
    room: str | None = None,
    palace: Path = DEFAULT_PALACE,
    max_distance: float = 0.0,
) -> dict[str, Any] | None:
    """Return MemPalace native hits with drawer IDs and raw evidence metadata.

    MemPalace MCP search intentionally returns concise drawer text. A9's
    control plane also needs stable IDs/hashes so monitor, mobile, and workers
    can hydrate exact drawers without trusting summaries.
    """
    if not (palace / "chroma.sqlite3").exists() or not MEMPALACE_SOURCE.exists():
        return None
    sys.path.insert(0, str(MEMPALACE_SOURCE))
    try:
        with suppress_native_stderr():
            from mempalace.palace import get_collection  # type: ignore

            collection = get_collection(str(palace), create=False)
            kwargs: dict[str, Any] = {
                "query_texts": [query],
                "n_results": max(1, limit),
                "include": ["documents", "metadatas", "distances"],
            }
            where = build_native_where(wing, room)
            if where:
                kwargs["where"] = where
            raw = collection.query(**kwargs)
    except Exception as exc:  # pragma: no cover - environment/index dependent
        return {
            "source": "native_mempalace",
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "results": [],
        }

    ids = (getattr(raw, "ids", None) or [[]])[0]
    docs = (getattr(raw, "documents", None) or [[]])[0]
    metas = (getattr(raw, "metadatas", None) or [[]])[0]
    distances = (getattr(raw, "distances", None) or [[]])[0]
    results: list[dict[str, Any]] = []
    for drawer_id, doc, meta, distance in zip(ids, docs, metas, distances):
        meta = meta or {}
        if max_distance > 0.0 and distance is not None and float(distance) > max_distance:
            continue
        results.append(
            {
                "drawer_id": drawer_id,
                "similarity": distance_to_similarity(distance),
                "distance": None if distance is None else round(float(distance), 4),
                "wing": meta.get("wing"),
                "room": meta.get("room"),
                "role": meta.get("role"),
                "event_kind": meta.get("event_kind"),
                "timestamp": meta.get("filed_at"),
                "source_ref": meta.get("source_ref"),
                "source_file": meta.get("source_file"),
                "source_sha256": meta.get("source_sha256"),
                "raw_line_sha256": meta.get("raw_line_sha256"),
                "content_hash": meta.get("content_hash"),
                "source_line": meta.get("source_line"),
                "content": compact(str(doc or "")),
            }
        )
    return {
        "source": "native_mempalace",
        "status": "ok",
        "palace_path": str(palace),
        "filters": {"wing": wing, "room": room},
        "results": results,
    }


def native_get_drawer(drawer_id: str, *, palace: Path = DEFAULT_PALACE) -> dict[str, Any]:
    if not drawer_id:
        return {"status": "invalid_request", "error": "drawer_id_required"}
    if not (palace / "chroma.sqlite3").exists() or not MEMPALACE_SOURCE.exists():
        return {"status": "error", "error": "native palace index unavailable"}
    sys.path.insert(0, str(MEMPALACE_SOURCE))
    try:
        with suppress_native_stderr():
            from mempalace.palace import get_collection  # type: ignore

            collection = get_collection(str(palace), create=False)
            raw = collection.get(ids=[drawer_id], include=["documents", "metadatas"])
    except Exception as exc:  # pragma: no cover - environment/index dependent
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    ids = getattr(raw, "ids", None) or []
    if not ids:
        return {"status": "not_found", "error": f"Drawer not found: {drawer_id}"}
    docs = getattr(raw, "documents", None) or []
    metas = getattr(raw, "metadatas", None) or []
    meta = metas[0] if metas else {}
    return {
        "status": "ok",
        "drawer_id": ids[0],
        "content": docs[0] if docs else "",
        "metadata": meta or {},
    }


def build_recall_packet(
    path: Path,
    *,
    query: str,
    limit: int,
    hydrate: int = 3,
    wing: str = DEFAULT_NATIVE_WING,
    room: str = DEFAULT_NATIVE_ROOM,
    palace: Path = DEFAULT_PALACE,
    native_enabled: bool = True,
) -> dict[str, Any]:
    native = (
        native_query_drawers(query, limit=limit, wing=wing, room=room, palace=palace)
        if native_enabled
        else None
    )
    fallback_hits = search_drawers(path, query, limit=limit, event_kind="message", exclude_context=True)
    native_hits = native.get("results", []) if native and native.get("status") == "ok" else []
    hydrated: list[dict[str, Any]] = []
    for hit in native_hits[: max(0, hydrate)]:
        drawer = native_get_drawer(str(hit.get("drawer_id") or ""), palace=palace)
        if drawer.get("status") == "ok":
            hydrated.append(
                {
                    "drawer_id": drawer.get("drawer_id"),
                    "content": drawer.get("content"),
                    "metadata": drawer.get("metadata"),
                }
            )
    return {
        "schema": "a9.mempalace_recall_packet.v1",
        "source": "native_mempalace+fallback_drawer_jsonl" if native_hits else "mempalace-compatible-drawer-jsonl",
        "status": "ok" if native is None or native.get("status") == "ok" else native.get("status"),
        "query": query,
        "truth_policy": "recall_not_truth",
        "official_protocol": [
            "short keyword search",
            "verbatim drawer hits",
            "drawer_id hydration",
            "KG/diary are separate continuity layers",
            "empty/conflicting recall must not be treated as truth",
        ],
        "filters": {"wing": wing, "room": room},
        "native_error": None if not native or native.get("status") == "ok" else native.get("error"),
        "search_hits": native_hits,
        "hydrated_drawers": hydrated,
        "fallback_evidence_refs": [
            {
                "source_ref": hit["source_ref"],
                "source_sha256": hit["source_sha256"],
                "content_hash": hit["content_hash"],
                "role": hit["role"],
                "event_kind": hit["event_kind"],
                "score": hit["score"],
            }
            for hit in fallback_hits
        ],
        "fallback_recall": fallback_hits,
        "next_reader_rule": "Use search_hits to select evidence, hydrated_drawers for verbatim reading, and raw source_ref/hash to audit. Do not answer from recall alone.",
    }


def evidence_ref_from_item(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "drawer_id": item.get("drawer_id") or metadata.get("drawer_id"),
        "source_ref": item.get("source_ref") or metadata.get("source_ref"),
        "source_sha256": item.get("source_sha256") or metadata.get("source_sha256"),
        "raw_line_sha256": item.get("raw_line_sha256") or metadata.get("raw_line_sha256"),
        "content_hash": item.get("content_hash") or metadata.get("content_hash"),
        "role": item.get("role") or metadata.get("role"),
        "event_kind": item.get("event_kind") or metadata.get("event_kind"),
        "timestamp": item.get("timestamp") or metadata.get("filed_at"),
    }


def recall_evidence_items(recall_packet: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for drawer in recall_packet.get("hydrated_drawers") or []:
        if not isinstance(drawer, dict):
            continue
        metadata = drawer.get("metadata") if isinstance(drawer.get("metadata"), dict) else {}
        items.append(
            {
                "drawer_id": drawer.get("drawer_id"),
                "content": str(drawer.get("content") or ""),
                "metadata": metadata,
            }
        )
    for hit in recall_packet.get("fallback_recall") or []:
        if isinstance(hit, dict):
            items.append(hit)
    for hit in recall_packet.get("search_hits") or []:
        if isinstance(hit, dict) and hit.get("content"):
            items.append(hit)
    return items


def has_any(text: str, markers: Iterable[str]) -> bool:
    lower = text.lower()
    return any(marker.lower() in lower for marker in markers)


def has_stale_signal(text: str) -> bool:
    lower = text.lower()
    for marker in STALE_MARKERS:
        marker_lower = marker.lower()
        index = lower.find(marker_lower)
        if index < 0:
            continue
        prefix = lower[max(0, index - 12):index]
        if any(negation in prefix for negation in ("没有", "无", "不要", "not ", "no ")):
            continue
        return True
    return False


def has_current_signal(text: str, *, stale_signal: bool = False) -> bool:
    strong_markers = ("当前", "现在", "已完成", "必须", "decision", "accepted", "status", "仍然", "保留")
    weak_markers = ("核心", "主线")
    if has_any(text, strong_markers):
        return True
    if stale_signal:
        return False
    return has_any(text, weak_markers)


def sentence_snippets(text: str, limit: int = 3) -> list[str]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[。！？.!?])\s+|[；;]\s*", normalized)
    snippets = [part.strip() for part in parts if part.strip()]
    if not snippets:
        snippets = [normalized]
    return [compact(part, 220) for part in snippets[:limit]]


def build_role_packets(facts: list[dict[str, Any]], stale: list[dict[str, Any]], changes: list[dict[str, Any]]) -> dict[str, Any]:
    packets: dict[str, Any] = {}
    combined = [
        ("current_fact", item) for item in facts
    ] + [
        ("stale_branch", item) for item in stale
    ] + [
        ("causal_change", item) for item in changes
    ]
    for role, keywords in ROLE_KEYWORDS.items():
        entries = []
        for kind, item in combined:
            text = str(item.get("text") or item.get("change") or "")
            if has_any(text, keywords):
                entries.append(
                    {
                        "kind": kind,
                        "text": text,
                        "evidence_ref": item.get("evidence_ref"),
                    }
                )
        packets[role] = {
            "schema": "a9.role_memory_packet.v1",
            "role": role,
            "entries": entries[:6],
            "reader_rule": "Treat as role-scoped recall candidates; verify against task contract and evidence before acting.",
        }
    return packets


def build_causal_memory_packet(
    recall_packet: dict[str, Any],
    *,
    query: str,
    max_items: int = 8,
) -> dict[str, Any]:
    """Compile recall evidence into an A9 causal-memory candidate packet.

    This follows MemPalace's protocol boundaries: search/hydration provide
    verbatim evidence, KG-style facts remain time-valid candidates with source
    drawers, diary output is role-scoped continuity, and stale facts are
    explicit invalidation candidates rather than silent overwrites.
    """
    current_facts: list[dict[str, Any]] = []
    stale_branches: list[dict[str, Any]] = []
    causal_changes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in recall_evidence_items(recall_packet):
        content = str(item.get("content") or "")
        if not content.strip():
            continue
        evidence_ref = evidence_ref_from_item(item)
        for snippet in sentence_snippets(content, limit=3):
            key = f"{evidence_ref.get('source_ref')}:{snippet}"
            if key in seen:
                continue
            seen.add(key)
            record = {
                "text": snippet,
                "evidence_ref": evidence_ref,
                "valid_from": evidence_ref.get("timestamp"),
                "source_drawer_id": evidence_ref.get("drawer_id"),
            }
            stale_signal = has_stale_signal(snippet)
            if stale_signal:
                stale_branches.append(
                    {
                        **record,
                        "status": "candidate_stale",
                        "kg_action": "invalidate_candidate",
                    }
                )
            causal_signal = has_any(snippet, CAUSAL_MARKERS)
            if causal_signal:
                causal_changes.append(
                    {
                        "change": snippet,
                        "evidence_ref": evidence_ref,
                        "valid_from": evidence_ref.get("timestamp"),
                        "kg_action": "add_change_candidate",
                    }
                )
            if has_current_signal(snippet, stale_signal=stale_signal) or (causal_signal and not stale_signal):
                current_facts.append(
                    {
                        **record,
                        "status": "candidate_current",
                        "kg_action": "add_fact_candidate",
                    }
                )
            if len(current_facts) >= max_items and len(stale_branches) >= max_items and len(causal_changes) >= max_items:
                break
        if len(current_facts) >= max_items and len(stale_branches) >= max_items and len(causal_changes) >= max_items:
            break
    current_facts = current_facts[:max_items]
    stale_branches = stale_branches[:max_items]
    causal_changes = causal_changes[:max_items]
    role_packets = build_role_packets(current_facts, stale_branches, causal_changes)
    next_task_memory = {
        "schema": "a9.next_task_memory_packet.v1",
        "query": query,
        "must_include": [
            item
            for item in current_facts[:4]
        ],
        "must_exclude_or_verify": [
            item
            for item in stale_branches[:4]
        ],
        "causal_changes_to_review": causal_changes[:4],
        "reader_rule": "Inject only bounded entries relevant to the next task; do not paste raw recall wholesale.",
    }
    return {
        "schema": "a9.causal_memory_packet.v1",
        "status": "ok",
        "query": query,
        "truth_policy": "candidate_memory_not_truth",
        "copied_protocols": [
            "MemPalace search returns verbatim evidence candidates",
            "MemPalace get_drawer hydrates exact drawer text by drawer_id",
            "MemPalace KG uses valid_from/valid_to/source_drawer_id for changing facts",
            "MemPalace diary uses role/agent scoped continuity entries",
        ],
        "kg_candidates": {
            "current_facts": current_facts,
            "stale_branches": stale_branches,
            "causal_changes": causal_changes,
        },
        "role_packets": role_packets,
        "next_task_memory": next_task_memory,
        "evidence_policy": "All compiler output is candidate memory; verify against source_ref/hash before changing plan or worker contract.",
    }


def build_causal_memory_from_query(
    path: Path,
    *,
    query: str,
    limit: int = 8,
    hydrate: int = 4,
    wing: str = DEFAULT_NATIVE_WING,
    room: str = DEFAULT_NATIVE_ROOM,
    palace: Path = DEFAULT_PALACE,
    native_enabled: bool = True,
) -> dict[str, Any]:
    recall_packet = build_recall_packet(
        path,
        query=query,
        limit=limit,
        hydrate=hydrate,
        wing=wing,
        room=room,
        palace=palace,
        native_enabled=native_enabled,
    )
    compiled = build_causal_memory_packet(recall_packet, query=query)
    return {
        **compiled,
        "recall_packet": {
            "schema": recall_packet.get("schema"),
            "source": recall_packet.get("source"),
            "filters": recall_packet.get("filters"),
            "search_hit_count": len(recall_packet.get("search_hits") or []),
            "hydrated_drawer_count": len(recall_packet.get("hydrated_drawers") or []),
            "fallback_evidence_ref_count": len(recall_packet.get("fallback_evidence_refs") or []),
        },
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def kg_operation_from_candidate(kind: str, item: dict[str, Any], *, commit_at: str) -> dict[str, Any]:
    evidence_ref = item.get("evidence_ref") if isinstance(item.get("evidence_ref"), dict) else {}
    text = str(item.get("text") or item.get("change") or "")
    predicate = {
        "current_fact": "has_current_fact",
        "stale_branch": "has_stale_branch",
        "causal_change": "has_causal_change",
    }.get(kind, "has_memory")
    return {
        "operation": "kg_add",
        "kind": kind,
        "subject": "A9",
        "predicate": predicate,
        "object": text,
        "valid_from": item.get("valid_from"),
        "valid_to": commit_at if kind == "stale_branch" else None,
        "source_file": evidence_ref.get("source_ref"),
        "source_drawer_id": evidence_ref.get("drawer_id") or item.get("source_drawer_id"),
        "adapter_name": "a9_causal_memory_compiler",
    }


def diary_operation_from_role_packet(role: str, packet: dict[str, Any], *, commit_at: str) -> dict[str, Any] | None:
    entries = packet.get("entries") if isinstance(packet.get("entries"), list) else []
    if not entries:
        return None
    compact_entries = [
        {
            "kind": entry.get("kind"),
            "text": entry.get("text"),
            "evidence_ref": entry.get("evidence_ref"),
        }
        for entry in entries[:6]
        if isinstance(entry, dict)
    ]
    content = json.dumps(
        {
            "schema": "a9.role_diary_entry.v1",
            "role": role,
            "committed_at": commit_at,
            "entries": compact_entries,
            "reader_rule": "Role-scoped continuity from approved causal memory; verify evidence before execution.",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "operation": "diary_write",
        "agent_name": role,
        "wing": "a9-causal-memory",
        "topic": "causal-memory",
        "content": content,
    }


def causal_memory_commit_plan(
    causal_packet: dict[str, Any],
    *,
    approved_by: str,
    approval_reason: str,
    commit_at: str | None = None,
) -> dict[str, Any]:
    commit_at = commit_at or utc_now_iso()
    kg = causal_packet.get("kg_candidates") if isinstance(causal_packet.get("kg_candidates"), dict) else {}
    operations: list[dict[str, Any]] = []
    for item in (kg.get("current_facts") or [])[:8]:
        if isinstance(item, dict):
            operations.append(kg_operation_from_candidate("current_fact", item, commit_at=commit_at))
    for item in (kg.get("stale_branches") or [])[:8]:
        if isinstance(item, dict):
            operations.append(kg_operation_from_candidate("stale_branch", item, commit_at=commit_at))
    for item in (kg.get("causal_changes") or [])[:8]:
        if isinstance(item, dict):
            operations.append(kg_operation_from_candidate("causal_change", item, commit_at=commit_at))
    role_packets = causal_packet.get("role_packets") if isinstance(causal_packet.get("role_packets"), dict) else {}
    for role, packet in role_packets.items():
        if isinstance(packet, dict):
            op = diary_operation_from_role_packet(str(role), packet, commit_at=commit_at)
            if op:
                operations.append(op)
    return {
        "schema": "a9.causal_memory_commit_plan.v1",
        "status": "planned",
        "truth_policy": "approved_candidate_memory_not_absolute_truth",
        "approved_by": approved_by,
        "approval_reason": approval_reason,
        "commit_at": commit_at,
        "operations": operations,
        "operation_count": len(operations),
        "copied_protocols": [
            "MemPalace KG temporal triples keep valid_from/valid_to and source_drawer_id",
            "MemPalace diary writes role/agent-scoped continuity entries",
            "Changed or stale branches are explicit ended facts rather than silent overwrites",
        ],
    }


def write_kg_operation(operation: dict[str, Any], *, palace: Path = DEFAULT_PALACE) -> dict[str, Any]:
    if not MEMPALACE_SOURCE.exists():
        return {"status": "error", "error": "reference-projects/mempalace missing", "operation": operation}
    sys.path.insert(0, str(MEMPALACE_SOURCE))
    try:
        from mempalace.knowledge_graph import KnowledgeGraph  # type: ignore

        kg = KnowledgeGraph(db_path=str(palace / "knowledge_graph.sqlite3"))
        triple_id = kg.add_triple(
            str(operation.get("subject") or "A9"),
            str(operation.get("predicate") or "has_memory"),
            str(operation.get("object") or ""),
            valid_from=operation.get("valid_from"),
            valid_to=operation.get("valid_to"),
            source_file=operation.get("source_file"),
            source_drawer_id=operation.get("source_drawer_id"),
            adapter_name=str(operation.get("adapter_name") or "a9_causal_memory_compiler"),
        )
        kg.close()
        return {"status": "ok", "operation": "kg_add", "triple_id": triple_id}
    except Exception as exc:  # pragma: no cover - environment/index dependent
        return {"status": "error", "operation": "kg_add", "error": f"{type(exc).__name__}: {exc}"}


def write_kg_invalidate_operation(operation: dict[str, Any], *, palace: Path = DEFAULT_PALACE) -> dict[str, Any]:
    if operation.get("operation") not in {"kg_invalidate", "kg_invalidate_candidate"}:
        return {"status": "invalid_request", "error": "kg_invalidate_operation_required", "operation": operation}
    if not MEMPALACE_SOURCE.exists():
        return {"status": "error", "error": "reference-projects/mempalace missing", "operation": operation}
    sys.path.insert(0, str(MEMPALACE_SOURCE))
    try:
        from mempalace.knowledge_graph import KnowledgeGraph  # type: ignore

        kg = KnowledgeGraph(db_path=str(palace / "knowledge_graph.sqlite3"))
        kg.invalidate(
            str(operation.get("subject") or "A9"),
            str(operation.get("predicate") or ""),
            str(operation.get("object") or ""),
            ended=operation.get("ended") or utc_now_iso(),
        )
        kg.close()
        return {
            "status": "ok",
            "operation": "kg_invalidate",
            "subject": operation.get("subject") or "A9",
            "predicate": operation.get("predicate"),
            "object": operation.get("object"),
            "ended": operation.get("ended"),
        }
    except Exception as exc:  # pragma: no cover - environment/index dependent
        return {"status": "error", "operation": "kg_invalidate", "error": f"{type(exc).__name__}: {exc}"}


def query_current_kg_facts(subject: str, *, palace: Path = DEFAULT_PALACE) -> list[dict[str, Any]]:
    if not MEMPALACE_SOURCE.exists():
        return []
    sys.path.insert(0, str(MEMPALACE_SOURCE))
    try:
        from mempalace.knowledge_graph import KnowledgeGraph  # type: ignore

        kg = KnowledgeGraph(db_path=str(palace / "knowledge_graph.sqlite3"))
        facts = kg.query_entity(subject, direction="outgoing")
        kg.close()
        return [fact for fact in facts if fact.get("current")]
    except Exception:
        return []


def query_kg_facts(subject: str, *, palace: Path = DEFAULT_PALACE) -> list[dict[str, Any]]:
    if not MEMPALACE_SOURCE.exists():
        return []
    sys.path.insert(0, str(MEMPALACE_SOURCE))
    try:
        from mempalace.knowledge_graph import KnowledgeGraph  # type: ignore

        kg = KnowledgeGraph(db_path=str(palace / "knowledge_graph.sqlite3"))
        facts = kg.query_entity(subject, direction="outgoing")
        kg.close()
        return facts
    except Exception:
        return []


def drift_check_commit_plan(plan: dict[str, Any], *, palace: Path = DEFAULT_PALACE) -> dict[str, Any]:
    """Check planned KG writes against current KG state before committing.

    This copies MemPalace's temporal KG contract: current facts are facts with
    ``valid_to is NULL``. A9 treats a planned current fact with the same
    subject/predicate but a different object as a drift/contradiction candidate
    that requires review before write.
    """
    operations = plan.get("operations") if isinstance(plan.get("operations"), list) else []
    planned_kg = [op for op in operations if isinstance(op, dict) and op.get("operation") == "kg_add"]
    by_subject: dict[str, list[dict[str, Any]]] = {}
    for op in planned_kg:
        by_subject.setdefault(str(op.get("subject") or "A9"), []).append(op)
    conflicts: list[dict[str, Any]] = []
    duplicate_count = 0
    checked_count = 0
    for subject, subject_ops in by_subject.items():
        existing = query_current_kg_facts(subject, palace=palace)
        for op in subject_ops:
            checked_count += 1
            predicate = str(op.get("predicate") or "")
            obj = str(op.get("object") or "")
            if op.get("valid_to"):
                continue
            matches = [
                fact for fact in existing
                if str(fact.get("predicate") or "") == predicate
            ]
            for fact in matches:
                existing_obj = str(fact.get("object") or "")
                if existing_obj == obj:
                    duplicate_count += 1
                    continue
                conflicts.append(
                    {
                        "subject": subject,
                        "predicate": predicate,
                        "planned_object": obj,
                        "existing_object": existing_obj,
                        "existing_fact": fact,
                        "planned_operation": op,
                        "action": "review_before_commit",
                    }
                )
    status = "pass" if not conflicts else "review_required"
    return {
        "schema": "a9.causal_memory_drift_check.v1",
        "status": status,
        "checked_kg_operations": checked_count,
        "duplicates": duplicate_count,
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "policy": "Do not commit conflicting current facts without explicit monitor review and stale-fact invalidation.",
    }


def audit_causal_memory_state(subject: str = "A9", *, palace: Path = DEFAULT_PALACE) -> dict[str, Any]:
    """Audit MemPalace KG state after writes without changing facts.

    This follows MemPalace's temporal KG semantics: active facts are
    ``valid_to is NULL``; obsolete facts stay queryable as history. A9 turns
    multiple active objects for the same subject/predicate into review
    candidates instead of silently invalidating them.
    """
    facts = query_kg_facts(subject, palace=palace)
    current = [fact for fact in facts if fact.get("current")]
    expired = [fact for fact in facts if not fact.get("current")]
    by_predicate: dict[str, list[dict[str, Any]]] = {}
    for fact in current:
        by_predicate.setdefault(str(fact.get("predicate") or ""), []).append(fact)

    conflicts: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    invalidation_candidates: list[dict[str, Any]] = []
    for predicate, rows in by_predicate.items():
        objects: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            objects.setdefault(str(row.get("object") or ""), []).append(row)
        for obj, obj_rows in objects.items():
            if len(obj_rows) > 1:
                duplicates.append(
                    {
                        "subject": subject,
                        "predicate": predicate,
                        "object": obj,
                        "count": len(obj_rows),
                        "facts": obj_rows,
                        "action": "dedupe_review",
                    }
                )
        if len(objects) <= 1:
            continue
        conflict = {
            "subject": subject,
            "predicate": predicate,
            "objects": sorted(objects),
            "facts": rows,
            "action": "choose_current_or_invalidate_stale",
        }
        conflicts.append(conflict)
        for obj, obj_rows in objects.items():
            invalidation_candidates.append(
                {
                    "operation": "kg_invalidate_candidate",
                    "subject": subject,
                    "predicate": predicate,
                    "object": obj,
                    "ended": utc_now_iso(),
                    "candidate_reason": "multiple current objects for one subject/predicate",
                    "matching_fact_count": len(obj_rows),
                    "requires_monitor_decision": True,
                }
            )

    status = "pass" if not conflicts and not duplicates else "review_required"
    return {
        "schema": "a9.causal_memory_audit.v1",
        "status": status,
        "subject": subject,
        "fact_count": len(facts),
        "current_fact_count": len(current),
        "expired_fact_count": len(expired),
        "conflict_count": len(conflicts),
        "duplicate_count": len(duplicates),
        "conflicts": conflicts,
        "duplicates": duplicates,
        "invalidation_candidates": invalidation_candidates,
        "stale_history_sample": expired[:8],
        "copied_protocols": [
            "MemPalace KG keeps historical facts with valid_to instead of deleting them",
            "MemPalace invalidate marks ended facts; A9 emits invalidation candidates for monitor approval",
            "MemPalace fact-checker treats stale/conflicting facts as issues, not truth",
        ],
        "policy": "Audit is side-effect free; invalidation candidates require explicit monitor approval before KG mutation.",
    }


def _fact_temporal_key(fact: dict[str, Any]) -> str:
    value = fact.get("valid_from") or fact.get("created_at") or ""
    return str(value)


def _score_stale_repair_candidate(
    fact: dict[str, Any],
    *,
    newest_key: str,
) -> dict[str, Any]:
    obj = str(fact.get("object") or "")
    reasons: list[str] = []
    score = 0
    if has_stale_signal(obj):
        score += 70
        reasons.append("object_has_stale_signal")
    if newest_key and _fact_temporal_key(fact) and _fact_temporal_key(fact) < newest_key:
        score += 35
        reasons.append("older_than_newest_current_fact")
    if has_current_signal(obj, stale_signal=has_stale_signal(obj)):
        score -= 20
        reasons.append("object_has_current_signal")
    if not reasons:
        reasons.append("ambiguous_conflict_member")
    confidence = max(0.0, min(0.95, score / 100.0))
    return {
        "score": score,
        "confidence": round(confidence, 2),
        "reasons": reasons,
        "auto_selectable": score >= 50,
    }


def propose_causal_memory_repairs(
    audit_report: dict[str, Any] | None = None,
    *,
    subject: str = "A9",
    palace: Path = DEFAULT_PALACE,
) -> dict[str, Any]:
    """Build side-effect-free stale-branch repair proposals from a KG audit.

    MemPalace's protocol says changed facts should be handled by invalidating
    the old fact and adding/querying the time-valid current fact. A9 keeps the
    selection step explicit: this function ranks stale-looking conflict members
    and emits invalidation candidates, but it never mutates the KG.
    """
    audit = audit_report if isinstance(audit_report, dict) else audit_causal_memory_state(subject, palace=palace)
    conflicts = audit.get("conflicts") if isinstance(audit.get("conflicts"), list) else []
    proposals: list[dict[str, Any]] = []
    invalidation_candidates: list[dict[str, Any]] = []
    for conflict_index, conflict in enumerate(conflicts, start=1):
        if not isinstance(conflict, dict):
            continue
        rows = [row for row in (conflict.get("facts") or []) if isinstance(row, dict)]
        if not rows:
            continue
        newest_key = max((_fact_temporal_key(row) for row in rows), default="")
        ranked: list[dict[str, Any]] = []
        for row in rows:
            score = _score_stale_repair_candidate(row, newest_key=newest_key)
            candidate = {
                "operation": "kg_invalidate_candidate",
                "subject": str(row.get("subject") or conflict.get("subject") or subject or "A9"),
                "predicate": str(row.get("predicate") or conflict.get("predicate") or ""),
                "object": str(row.get("object") or ""),
                "ended": utc_now_iso(),
                "candidate_reason": "causal_repair_policy_selected_stale_branch",
                "requires_monitor_decision": True,
                "source_fact": row,
                "repair_score": score["score"],
                "confidence": score["confidence"],
                "repair_reasons": score["reasons"],
                "auto_selectable": score["auto_selectable"],
            }
            ranked.append(candidate)
        selected = [
            candidate for candidate in sorted(
                ranked,
                key=lambda item: (-int(item.get("repair_score") or 0), str(item.get("object") or "")),
            )
            if candidate.get("auto_selectable")
        ]
        proposal_candidates = selected or ranked
        invalidation_candidates.extend(selected)
        proposals.append(
            {
                "schema": "a9.causal_memory_repair_proposal_item.v1",
                "id": f"repair-{conflict_index:04d}",
                "status": "review_required",
                "subject": conflict.get("subject") or subject,
                "predicate": conflict.get("predicate"),
                "objects": conflict.get("objects") or sorted({str(row.get("object") or "") for row in rows}),
                "recommended_action": "invalidate_selected_after_monitor_approval" if selected else "manual_review_required",
                "selected_invalidation_candidates": selected,
                "review_candidates": proposal_candidates,
                "policy_reason": (
                    "Prefer explicit stale markers and older temporal facts; "
                    "do not mutate KG until monitor approval calls causal-invalidate."
                ),
            }
        )
    status = "review_required" if proposals else "pass"
    return {
        "schema": "a9.causal_memory_repair_proposal.v1",
        "status": status,
        "subject": subject,
        "truth_policy": "side_effect_free_repair_candidates_not_truth",
        "audit_status": audit.get("status"),
        "audit_conflict_count": audit.get("conflict_count", len(conflicts)),
        "proposal_count": len(proposals),
        "proposals": proposals,
        "invalidation_candidates": invalidation_candidates,
        "copied_protocols": [
            "MemPalace recall protocol: stale/conflicting facts prefer time-valid KG over model memory",
            "MemPalace KG invalidate ends old facts with valid_to instead of deleting them",
            "MemPalace fact_checker reports stale/conflicting facts as issues anchored to KG facts",
        ],
        "policy": (
            "Repair proposal is side-effect free. Only candidates selected and approved "
            "through causal-invalidate may mutate temporal KG state."
        ),
    }


def approved_invalidation_plan(
    invalidation_candidates: list[dict[str, Any]],
    *,
    approved_by: str,
    approval_reason: str,
    ended: str | None = None,
) -> dict[str, Any]:
    ended_at = ended or utc_now_iso()
    operations: list[dict[str, Any]] = []
    for candidate in invalidation_candidates[:16]:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("operation") not in {"kg_invalidate_candidate", "kg_invalidate"}:
            continue
        subject = str(candidate.get("subject") or "A9").strip()
        predicate = str(candidate.get("predicate") or "").strip()
        obj = str(candidate.get("object") or "").strip()
        if not subject or not predicate or not obj:
            continue
        operations.append(
            {
                "operation": "kg_invalidate",
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "ended": candidate.get("ended") or ended_at,
                "source_candidate": candidate,
                "adapter_name": "a9_causal_memory_audit",
            }
        )
    return {
        "schema": "a9.causal_memory_invalidation_plan.v1",
        "status": "planned",
        "approved_by": approved_by,
        "approval_reason": approval_reason,
        "ended_at": ended_at,
        "operations": operations,
        "operation_count": len(operations),
        "copied_protocols": [
            "MemPalace KG invalidate sets valid_to instead of deleting triples",
            "MemPalace temporal facts remain queryable as history after invalidation",
            "A9 only executes invalidation candidates after explicit monitor approval",
        ],
    }


def apply_approved_invalidations(
    invalidation_candidates: list[dict[str, Any]],
    *,
    approved_by: str,
    approval_reason: str,
    dry_run: bool = True,
    palace: Path = DEFAULT_PALACE,
) -> dict[str, Any]:
    if not approved_by.strip() or not approval_reason.strip():
        return {
            "schema": "a9.causal_memory_invalidation_result.v1",
            "status": "invalid_request",
            "error": "approved_by_and_approval_reason_required",
            "results": [],
        }
    plan = approved_invalidation_plan(
        invalidation_candidates,
        approved_by=approved_by.strip(),
        approval_reason=approval_reason.strip(),
    )
    if not plan["operations"]:
        return {
            "schema": "a9.causal_memory_invalidation_result.v1",
            "status": "invalid_request",
            "error": "valid_invalidation_candidate_required",
            "plan": plan,
            "results": [],
        }
    if dry_run:
        return {
            "schema": "a9.causal_memory_invalidation_result.v1",
            "status": "dry_run",
            "plan": plan,
            "results": [],
        }
    results = [write_kg_invalidate_operation(operation, palace=palace) for operation in plan["operations"]]
    status = "ok" if all(result.get("status") == "ok" for result in results) else "partial"
    subjects = sorted({str(operation.get("subject") or "A9") for operation in plan["operations"]})
    return {
        "schema": "a9.causal_memory_invalidation_result.v1",
        "status": status,
        "plan": plan,
        "results": results,
        "post_invalidation_audit": {
            subject: audit_causal_memory_state(subject, palace=palace)
            for subject in subjects
        },
    }


def write_diary_operation(operation: dict[str, Any], *, palace: Path = DEFAULT_PALACE) -> dict[str, Any]:
    if not MEMPALACE_SOURCE.exists():
        return {"status": "error", "error": "reference-projects/mempalace missing", "operation": operation}
    if not (palace / "chroma.sqlite3").exists():
        return {"status": "error", "error": "native palace index unavailable", "operation": operation}
    sys.path.insert(0, str(MEMPALACE_SOURCE))
    try:
        with suppress_native_stderr():
            from mempalace.palace import get_collection  # type: ignore

            collection = get_collection(str(palace), create=True)
            now = utc_now_iso()
            content = str(operation.get("content") or "")
            wing = str(operation.get("wing") or "a9-causal-memory")
            role = str(operation.get("agent_name") or "unknown")
            topic = str(operation.get("topic") or "causal-memory")
            digest = hashlib.sha256(f"{role}:{topic}:{content}:{now}".encode("utf-8")).hexdigest()[:20]
            entry_id = f"a9_diary_{role}_{digest}"
            collection.add(
                ids=[entry_id],
                documents=[content],
                metadatas=[
                    {
                        "wing": wing,
                        "room": "diary",
                        "hall": "hall_diary",
                        "topic": topic,
                        "type": "diary_entry",
                        "agent": role,
                        "filed_at": now,
                        "date": now[:10],
                        "adapter_name": "a9_causal_memory_compiler",
                    }
                ],
            )
        return {"status": "ok", "operation": "diary_write", "entry_id": entry_id}
    except Exception as exc:  # pragma: no cover - environment/index dependent
        return {"status": "error", "operation": "diary_write", "error": f"{type(exc).__name__}: {exc}"}


def commit_causal_memory_packet(
    causal_packet: dict[str, Any],
    *,
    approved_by: str,
    approval_reason: str,
    dry_run: bool = True,
    palace: Path = DEFAULT_PALACE,
) -> dict[str, Any]:
    if not approved_by.strip() or not approval_reason.strip():
        return {
            "schema": "a9.causal_memory_commit_result.v1",
            "status": "invalid_request",
            "error": "approved_by_and_approval_reason_required",
            "truth_policy": "approved_candidate_memory_not_absolute_truth",
            "results": [],
        }
    plan = causal_memory_commit_plan(
        causal_packet,
        approved_by=approved_by.strip(),
        approval_reason=approval_reason.strip(),
    )
    drift_check = drift_check_commit_plan(plan, palace=palace)
    if dry_run:
        return {
            "schema": "a9.causal_memory_commit_result.v1",
            "status": "dry_run",
            "plan": plan,
            "drift_check": drift_check,
            "results": [],
        }
    if drift_check.get("status") != "pass":
        return {
            "schema": "a9.causal_memory_commit_result.v1",
            "status": "review_required",
            "plan": plan,
            "drift_check": drift_check,
            "results": [],
        }
    results: list[dict[str, Any]] = []
    for operation in plan["operations"]:
        if operation.get("operation") == "kg_add":
            results.append(write_kg_operation(operation, palace=palace))
        elif operation.get("operation") == "diary_write":
            results.append(write_diary_operation(operation, palace=palace))
        else:
            results.append({"status": "skip", "reason": "unknown_operation", "operation": operation})
    status = "ok" if all(result.get("status") == "ok" for result in results) else "partial"
    return {
        "schema": "a9.causal_memory_commit_result.v1",
        "status": status,
        "plan": plan,
        "drift_check": drift_check,
        "post_commit_audit": audit_causal_memory_state("A9", palace=palace),
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
    exclude_context: bool = False,
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
        content = str(row.get("content") or "")
        if exclude_context and is_context_injection(content):
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
            "content": compact(content),
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
    native = (
        native_search(
            query,
            limit=limit,
            wing=DEFAULT_NATIVE_WING,
            room=DEFAULT_NATIVE_ROOM,
            palace=palace,
        )
        if native_enabled
        else None
    )
    hits = search_drawers(path, query, limit=limit, event_kind="message", exclude_context=True)
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
    search.add_argument("--wing", default=DEFAULT_NATIVE_WING)
    search.add_argument("--room", default=DEFAULT_NATIVE_ROOM)

    wakeup = sub.add_parser("wakeup")
    wakeup.add_argument("--query", default="A9 MemPalace current mainline next action")
    wakeup.add_argument("--limit", type=int, default=8)

    recall = sub.add_parser("recall")
    recall.add_argument("query")
    recall.add_argument("--limit", type=int, default=8)
    recall.add_argument("--hydrate", type=int, default=3)
    recall.add_argument("--wing", default=DEFAULT_NATIVE_WING)
    recall.add_argument("--room", default=DEFAULT_NATIVE_ROOM)

    causal = sub.add_parser("causal-compile")
    causal.add_argument("query")
    causal.add_argument("--limit", type=int, default=8)
    causal.add_argument("--hydrate", type=int, default=4)
    causal.add_argument("--wing", default=DEFAULT_NATIVE_WING)
    causal.add_argument("--room", default=DEFAULT_NATIVE_ROOM)

    commit = sub.add_parser("causal-commit")
    commit.add_argument("--packet", required=True, type=Path)
    commit.add_argument("--approved-by", required=True)
    commit.add_argument("--approval-reason", required=True)
    commit.add_argument("--commit", action="store_true", help="Actually write KG/diary entries; default is dry-run")

    audit = sub.add_parser("causal-audit")
    audit.add_argument("--subject", default="A9")

    repair = sub.add_parser("causal-repair-propose")
    repair.add_argument("--subject", default="A9")
    repair.add_argument("--audit-report", type=Path)

    invalidate = sub.add_parser("causal-invalidate")
    invalidate.add_argument("--candidates", required=True, type=Path)
    invalidate.add_argument("--approved-by", required=True)
    invalidate.add_argument("--approval-reason", required=True)
    invalidate.add_argument("--commit", action="store_true", help="Actually invalidate KG triples; default is dry-run")

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
    elif args.command == "recall":
        print_json(
            build_recall_packet(
                drawers,
                query=args.query,
                limit=args.limit,
                hydrate=args.hydrate,
                wing=args.wing,
                room=args.room,
                native_enabled=native_enabled,
                palace=palace,
            )
        )
    elif args.command == "causal-compile":
        print_json(
            build_causal_memory_from_query(
                drawers,
                query=args.query,
                limit=args.limit,
                hydrate=args.hydrate,
                wing=args.wing,
                room=args.room,
                native_enabled=native_enabled,
                palace=palace,
            )
        )
    elif args.command == "causal-commit":
        packet = json.loads(args.packet.read_text(encoding="utf-8"))
        print_json(
            commit_causal_memory_packet(
                packet,
                approved_by=args.approved_by,
                approval_reason=args.approval_reason,
                dry_run=not args.commit,
                palace=palace,
            )
        )
    elif args.command == "causal-audit":
        print_json(audit_causal_memory_state(args.subject, palace=palace))
    elif args.command == "causal-repair-propose":
        audit_report = None
        if args.audit_report:
            audit_report = json.loads(args.audit_report.read_text(encoding="utf-8"))
        print_json(propose_causal_memory_repairs(audit_report, subject=args.subject, palace=palace))
    elif args.command == "causal-invalidate":
        candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
        if isinstance(candidates, dict):
            candidates = candidates.get("invalidation_candidates") or candidates.get("candidates") or []
        print_json(
            apply_approved_invalidations(
                candidates if isinstance(candidates, list) else [],
                approved_by=args.approved_by,
                approval_reason=args.approval_reason,
                dry_run=not args.commit,
                palace=palace,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
