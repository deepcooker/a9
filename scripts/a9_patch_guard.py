#!/usr/bin/env python3
"""Validate bounded patch/diff edits before execution.

This is an A9-native mechanism adaptation inspired by Aider's edit discipline:
small structured edits, exact existing-code matches, and bounded context instead
of trusting free-form "I changed it" claims.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BLOCKED_PARTS = {
    ".git",
    ".aider.tags.cache.v3",
    ".aider.tags.cache.v4",
    "__pycache__",
    "node_modules",
    "target",
    "vendor-src",
    "reference-projects",
}


@dataclass
class Finding:
    level: str
    message: str
    path: str | None = None


@dataclass
class SearchReplaceBlock:
    path: str
    search: str
    replace: str
    line: int


def read_patch(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def normalize_diff_path(raw: str) -> str:
    raw = raw.strip()
    if raw == "/dev/null":
        return raw
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    if raw.startswith("a/") or raw.startswith("b/"):
        raw = raw[2:]
    return raw


def validate_rel_path(root: Path, raw_path: str, findings: list[Finding]) -> Path | None:
    if raw_path == "/dev/null":
        return None

    rel = normalize_diff_path(raw_path)
    candidate = Path(rel)
    if candidate.is_absolute():
        findings.append(Finding("error", "absolute paths are not allowed", rel))
        return None
    if ".." in candidate.parts:
        findings.append(Finding("error", "path traversal is not allowed", rel))
        return None
    blocked = BLOCKED_PARTS.intersection(candidate.parts)
    if blocked:
        findings.append(Finding("error", f"blocked path component: {sorted(blocked)[0]}", rel))
        return None

    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        findings.append(Finding("error", "path escapes repository root", rel))
        return None
    return resolved


def parse_search_replace(text: str) -> tuple[list[SearchReplaceBlock], list[Finding]]:
    lines = text.splitlines(keepends=True)
    blocks: list[SearchReplaceBlock] = []
    findings: list[Finding] = []
    last_nonempty: tuple[int, str] | None = None
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()
        if stripped != "<<<<<<< SEARCH":
            if stripped:
                last_nonempty = (index + 1, stripped)
            index += 1
            continue

        if not last_nonempty:
            findings.append(Finding("error", f"SEARCH block at line {index + 1} has no preceding file path"))
            index += 1
            continue
        path_line, path = last_nonempty
        search_start = index + 1
        sep = None
        end = None
        for cursor in range(search_start, len(lines)):
            marker = lines[cursor].strip()
            if marker == "=======" and sep is None:
                sep = cursor
                continue
            if marker == ">>>>>>> REPLACE":
                end = cursor
                break
        if sep is None or end is None or sep > end:
            findings.append(
                Finding(
                    "error",
                    f"unterminated SEARCH/REPLACE block starting at line {index + 1}",
                    path,
                )
            )
            break

        search = "".join(lines[search_start:sep])
        replace = "".join(lines[sep + 1 : end])
        blocks.append(SearchReplaceBlock(path=path, search=search, replace=replace, line=path_line))
        index = end + 1
        last_nonempty = None

    return blocks, findings


def validate_search_replace(text: str, root: Path) -> dict[str, object]:
    findings: list[Finding] = []
    blocks, parse_findings = parse_search_replace(text)
    findings.extend(parse_findings)
    if not blocks:
        if not findings:
            findings.append(Finding("error", "no SEARCH/REPLACE blocks found"))
        return report("search_replace", 0, [], findings)

    touched: list[str] = []
    for block in blocks:
        resolved = validate_rel_path(root, block.path, findings)
        touched.append(block.path)
        if resolved is None:
            continue
        if not resolved.exists():
            findings.append(Finding("error", "target file does not exist", block.path))
            continue
        if not resolved.is_file():
            findings.append(Finding("error", "target path is not a file", block.path))
            continue
        if not block.search:
            findings.append(Finding("error", "SEARCH content must not be empty", block.path))
            continue
        current = resolved.read_text(encoding="utf-8")
        matches = current.count(block.search)
        if matches != 1:
            findings.append(
                Finding(
                    "error",
                    f"SEARCH content must match exactly once; found {matches}",
                    block.path,
                )
            )
        if block.search == block.replace:
            findings.append(Finding("warning", "replacement is identical to search", block.path))

    return report("search_replace", len(blocks), sorted(set(touched)), findings)


def validate_unified_diff(text: str, root: Path) -> dict[str, object]:
    findings: list[Finding] = []
    touched: set[str] = set()
    hunk_count = 0
    change_count = 0

    for line in text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                for raw in parts[2:4]:
                    rel = normalize_diff_path(raw)
                    if rel != "/dev/null":
                        touched.add(rel)
                        validate_rel_path(root, rel, findings)
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            rel = normalize_diff_path(line[4:])
            if rel != "/dev/null":
                touched.add(rel)
                validate_rel_path(root, rel, findings)
            continue
        if line.startswith("@@ "):
            hunk_count += 1
            continue
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            change_count += 1

    if not touched:
        findings.append(Finding("error", "unified diff has no file paths"))
    if hunk_count == 0:
        findings.append(Finding("error", "unified diff has no hunks"))
    if change_count == 0:
        findings.append(Finding("error", "unified diff has no changed lines"))

    return report("unified_diff", hunk_count, sorted(touched), findings)


def report(kind: str, block_count: int, touched: list[str], findings: list[Finding]) -> dict[str, object]:
    status = "fail" if any(item.level == "error" for item in findings) else "pass"
    return {
        "status": status,
        "kind": kind,
        "block_count": block_count,
        "touched_files": touched,
        "findings": [item.__dict__ for item in findings],
    }


def detect_format(text: str) -> str:
    if "<<<<<<< SEARCH" in text and ">>>>>>> REPLACE" in text:
        return "search_replace"
    return "unified_diff"


def validate(text: str, root: Path, patch_format: str) -> dict[str, object]:
    kind = detect_format(text) if patch_format == "auto" else patch_format
    if kind == "search_replace":
        return validate_search_replace(text, root)
    if kind == "unified_diff":
        return validate_unified_diff(text, root)
    raise AssertionError(kind)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate A9 patch/diff discipline")
    parser.add_argument("patch_file", help="Patch file to validate, or '-' for stdin")
    parser.add_argument("--root", default=str(ROOT), help="Repository root for path and match checks")
    parser.add_argument("--format", choices=["auto", "search_replace", "unified_diff"], default="auto")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    result = validate(read_patch(args.patch_file), root, args.format)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
