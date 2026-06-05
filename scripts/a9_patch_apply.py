#!/usr/bin/env python3
"""Apply A9 SEARCH/REPLACE edits with Aider-style strictness."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any

import a9_patch_guard


def is_blocked_candidate(path: Path) -> bool:
    return bool(a9_patch_guard.BLOCKED_PARTS.intersection(path.parts))


def basename_candidates(root: Path, name: str) -> list[str]:
    matches: list[str] = []
    for path in root.rglob(name):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if is_blocked_candidate(rel):
            continue
        matches.append(str(rel))
    return sorted(matches)


def similar_lines(search: str, content: str, *, context: int = 3) -> str:
    search_lines = [line for line in search.splitlines() if line.strip()]
    content_lines = content.splitlines()
    if not search_lines or not content_lines:
        return ""
    matches = difflib.get_close_matches(search_lines[0], content_lines, n=1, cutoff=0.55)
    if not matches:
        return ""
    index = content_lines.index(matches[0])
    start = max(0, index - context)
    end = min(len(content_lines), index + len(search_lines) + context)
    return "\n".join(content_lines[start:end])


def repair_hint_for_block(block: a9_patch_guard.SearchReplaceBlock, content: str, message: str) -> str:
    parts = [
        f"## SearchReplaceNoExactMatch: {message} in {block.path}",
        "<<<<<<< SEARCH",
        block.search,
        "=======",
        block.replace,
        ">>>>>>> REPLACE",
        "",
    ]
    hint = similar_lines(block.search, content)
    if hint:
        parts.extend(
            [
                f"Did you mean to match these actual lines from {block.path}?",
                "```",
                hint,
                "```",
                "",
            ]
        )
    if block.replace and block.replace in content:
        parts.extend(
            [
                f"The REPLACE lines already exist in {block.path}.",
                "Check whether the previous edit was already applied.",
                "",
            ]
        )
    parts.append(
        "The SEARCH section must exactly match existing text, including whitespace and comments. "
        "Reply only with fixed SEARCH/REPLACE blocks for the failed edits."
    )
    return "\n".join(parts)


def repair_hint_for_path(block: a9_patch_guard.SearchReplaceBlock, message: str, candidates: list[str]) -> str:
    parts = [
        f"## SearchReplacePathError: {message} for {block.path}",
        "<<<<<<< SEARCH",
        block.search,
        "=======",
        block.replace,
        ">>>>>>> REPLACE",
        "",
    ]
    if candidates:
        parts.extend(["Candidate files:", *[f"- {item}" for item in candidates], ""])
    parts.append("Use the full repository-relative path in the next SEARCH/REPLACE block.")
    return "\n".join(parts)


def block_summary(item: dict[str, Any]) -> str:
    path = item.get("effective_path") or item.get("path")
    return f"- block {item.get('index')}: {path} ({item.get('mode')})"


def build_repair_hint(successful: list[dict[str, Any]], failed: list[dict[str, Any]]) -> str:
    hints = [item["repair_hint"] for item in failed if item.get("repair_hint")]
    if successful and failed:
        prefix = [
            "# Partial SEARCH/REPLACE result",
            f"- applied_blocks: {len(successful)}",
            f"- failed_blocks: {len(failed)}",
            "",
            "Successful blocks:",
            *[block_summary(item) for item in successful],
            "",
            "In a retained worktree, Do not resend successful blocks.",
            "In A9 supervisor repair, failed runs may be rolled back by git governance; check target content and this metadata before resending blocks.",
            "If a repeated SEARCH no longer matches but REPLACE already exists, treat that block as already applied.",
            "",
            "Failed blocks to fix:",
        ]
        return "\n".join(prefix + hints)
    return "\n\n".join(hints)


def split_keepends(text: str) -> list[str]:
    if text and not text.endswith("\n"):
        text += "\n"
    return text.splitlines(keepends=True)


def replace_exact(current: str, search: str, replace: str) -> tuple[str, dict[str, Any]] | None:
    matches = current.count(search)
    if matches != 1:
        return None
    return current.replace(search, replace, 1), {
        "matches": matches,
        "match_strategy": "exact",
        "fuzz_level": 0,
    }


def match_leading_whitespace(whole_lines: list[str], part_lines: list[str]) -> str | None:
    if len(whole_lines) != len(part_lines):
        return None
    if not all(whole_lines[index].lstrip() == part_lines[index].lstrip() for index in range(len(part_lines))):
        return None
    offsets = {
        whole_lines[index][: len(whole_lines[index]) - len(part_lines[index])]
        for index in range(len(part_lines))
        if whole_lines[index].strip()
    }
    if len(offsets) != 1:
        return None
    return offsets.pop()


def replace_leading_whitespace(current: str, search: str, replace: str) -> tuple[str, dict[str, Any]] | None:
    whole_lines = split_keepends(current)
    search_lines = split_keepends(search)
    replace_lines = split_keepends(replace)
    if not search_lines:
        return None
    matches: list[tuple[int, str]] = []
    for index in range(len(whole_lines) - len(search_lines) + 1):
        add_leading = match_leading_whitespace(whole_lines[index : index + len(search_lines)], search_lines)
        if add_leading is not None:
            matches.append((index, add_leading))
    if len(matches) != 1:
        return None
    index, add_leading = matches[0]
    adjusted_replace = [add_leading + line if line.strip() else line for line in replace_lines]
    new_lines = whole_lines[:index] + adjusted_replace + whole_lines[index + len(search_lines) :]
    return "".join(new_lines), {
        "matches": len(matches),
        "match_strategy": "leading_whitespace",
        "fuzz_level": 1,
    }


def replace_with_strategy(current: str, search: str, replace: str) -> tuple[str, dict[str, Any]] | None:
    direct = replace_exact(current, search, replace) or replace_leading_whitespace(current, search, replace)
    if direct:
        return direct
    if "\\\\" not in search:
        return None
    normalized_search = search.replace("\\\\", "\\")
    normalized_replace = replace.replace("\\\\", "\\")
    normalized = replace_exact(current, normalized_search, normalized_replace) or replace_leading_whitespace(
        current,
        normalized_search,
        normalized_replace,
    )
    if not normalized:
        return None
    new_content, meta = normalized
    meta = {
        **meta,
        "match_strategy": f"{meta.get('match_strategy', 'unknown')}+windows_backslash_unescape",
        "normalization": "windows_backslash_unescape",
        "fuzz_level": max(int(meta.get("fuzz_level") or 0), 1),
    }
    return new_content, meta


def normalize_wrapped_text(text: str, path: str, section: str) -> tuple[str, list[str]]:
    normalizations: list[str] = []
    if not text:
        return text, normalizations
    lines = text.splitlines()
    if lines and lines[0].strip() == path:
        lines = lines[1:]
        normalizations.append(f"{section}:filename_line")
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip().startswith("```"):
        lines = lines[1:-1]
        normalizations.append(f"{section}:fence")
    normalized = "\n".join(lines)
    if normalized and text.endswith("\n"):
        normalized += "\n"
    return normalized, normalizations


def resolve_apply_path(
    root: Path,
    raw_path: str,
    findings: list[a9_patch_guard.Finding],
    *,
    allow_basename: bool,
) -> tuple[Path | None, str, list[str], list[str]]:
    resolved = a9_patch_guard.validate_rel_path(root, raw_path, findings)
    normalizations: list[str] = []
    candidates: list[str] = []
    if resolved is None:
        return None, raw_path, normalizations, candidates
    if resolved.exists() or not allow_basename or "/" in raw_path or "\\" in raw_path:
        return resolved, raw_path, normalizations, candidates
    candidates = basename_candidates(root, Path(raw_path).name)
    if len(candidates) == 1:
        effective_path = candidates[0]
        normalizations.append("path:basename_unique")
        resolved = a9_patch_guard.validate_rel_path(root, effective_path, findings)
        return resolved, effective_path, normalizations, candidates
    return resolved, raw_path, normalizations, candidates


def apply_search_replace(text: str, root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    findings: list[a9_patch_guard.Finding] = []
    blocks, parse_findings = a9_patch_guard.parse_search_replace(text)
    findings.extend(parse_findings)
    applied: list[dict[str, Any]] = []

    if not blocks:
        if not findings:
            findings.append(a9_patch_guard.Finding("error", "no SEARCH/REPLACE blocks found"))
        return report("search_replace_apply", "fail", applied, findings, dry_run=dry_run)

    for index, block in enumerate(blocks, start=1):
        search_probe, _ = normalize_wrapped_text(block.search, block.path, "search")
        resolved, effective_path, path_resolution_normalizations, path_candidates = resolve_apply_path(
            root,
            block.path,
            findings,
            allow_basename=search_probe != "",
        )
        if resolved is None:
            continue
        search, search_normalizations = normalize_wrapped_text(block.search, effective_path, "search")
        replace, replace_normalizations = normalize_wrapped_text(block.replace, effective_path, "replace")
        normalizations = (
            (block.path_normalizations or [])
            + path_resolution_normalizations
            + search_normalizations
            + replace_normalizations
        )

        current = ""
        creating_file = not resolved.exists() and search == ""
        if resolved.exists():
            if not resolved.is_file():
                findings.append(a9_patch_guard.Finding("error", "target path is not a file", block.path))
                continue
            current = resolved.read_text(encoding="utf-8")
        elif not creating_file:
            if path_candidates:
                message = f"ambiguous basename; found {len(path_candidates)} candidates"
            else:
                message = "target file does not exist"
            findings.append(
                a9_patch_guard.Finding(
                    "error",
                    message,
                    block.path,
                )
            )
            applied.append(
                {
                    "index": index,
                    "path": block.path,
                    "effective_path": effective_path,
                    "line": block.line,
                    "mode": "failed",
                    "search_bytes": len(search.encode("utf-8")),
                    "replace_bytes": len(replace.encode("utf-8")),
                    "matches": 0,
                    "match_strategy": "none",
                    "fuzz_level": None,
                    "normalizations": normalizations,
                    "path_candidates": path_candidates,
                    "repair_hint": repair_hint_for_path(block, message, path_candidates),
                }
            )
            continue

        if search == "" and not creating_file:
            findings.append(a9_patch_guard.Finding("error", "empty SEARCH is only allowed for new files", block.path))
            continue

        if creating_file:
            new_content = replace
            match_meta = {"matches": 0, "match_strategy": "new_file", "fuzz_level": 0}
        else:
            replacement = replace_with_strategy(current, search, replace)
            if replacement is None:
                exact_matches = current.count(search)
                replace_matches = current.count(replace) if replace else 0
                if replace_matches == 1:
                    findings.append(
                        a9_patch_guard.Finding(
                            "warning",
                            "SEARCH missing but REPLACE already exists exactly once; treating block as already applied",
                            block.path,
                        )
                    )
                    if normalizations:
                        findings.append(
                            a9_patch_guard.Finding(
                                "warning",
                                "normalized wrapped SEARCH/REPLACE content: " + ", ".join(normalizations),
                                block.path,
                            )
                        )
                    applied.append(
                        {
                            "index": index,
                            "path": block.path,
                            "effective_path": effective_path,
                            "line": block.line,
                            "mode": "already_applied",
                            "search_bytes": len(search.encode("utf-8")),
                            "replace_bytes": len(replace.encode("utf-8")),
                            "matches": exact_matches,
                            "replace_matches": replace_matches,
                            "match_strategy": "already_applied",
                            "fuzz_level": 0,
                            "normalizations": normalizations,
                        }
                    )
                    continue
                if replace_matches > 1:
                    message = (
                        f"SEARCH content must match exactly once; found {exact_matches}; "
                        f"REPLACE appears {replace_matches} times"
                    )
                else:
                    message = f"SEARCH content must match exactly once; found {exact_matches}"
                findings.append(
                    a9_patch_guard.Finding(
                        "error",
                        message,
                        block.path,
                    )
                )
                applied.append(
                    {
                        "index": index,
                        "path": block.path,
                        "effective_path": effective_path,
                        "line": block.line,
                        "mode": "failed",
                        "search_bytes": len(search.encode("utf-8")),
                        "replace_bytes": len(replace.encode("utf-8")),
                        "matches": exact_matches,
                        "replace_matches": replace_matches,
                        "match_strategy": "none",
                        "fuzz_level": None,
                        "normalizations": normalizations,
                        "repair_hint": repair_hint_for_block(block, current, message),
                    }
                )
                continue
            new_content, match_meta = replacement

        if new_content == current and not creating_file:
            findings.append(a9_patch_guard.Finding("warning", "replacement is identical to search", block.path))
        if match_meta["fuzz_level"] > 0:
            findings.append(
                a9_patch_guard.Finding(
                    "warning",
                    f"applied with controlled fuzz: {match_meta['match_strategy']}",
                    block.path,
                )
            )
        if normalizations:
            findings.append(
                a9_patch_guard.Finding(
                    "warning",
                    "normalized wrapped SEARCH/REPLACE content: " + ", ".join(normalizations),
                    block.path,
                )
            )

        if not dry_run:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(new_content, encoding="utf-8")
        applied.append(
            {
                "index": index,
                "path": block.path,
                "effective_path": effective_path,
                "line": block.line,
                "mode": "create" if creating_file else "replace",
                "search_bytes": len(search.encode("utf-8")),
                "replace_bytes": len(replace.encode("utf-8")),
                "normalizations": normalizations,
                **match_meta,
            }
        )

    status = "fail" if any(item.level == "error" for item in findings) else "pass"
    return report("search_replace_apply", status, applied, findings, dry_run=dry_run)


def report(
    kind: str,
    status: str,
    applied: list[dict[str, Any]],
    findings: list[a9_patch_guard.Finding],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    applied_success = [item for item in applied if item.get("mode") != "failed"]
    written = [item for item in applied_success if item.get("mode") in {"create", "replace"}]
    already_applied = [item for item in applied_success if item.get("mode") == "already_applied"]
    failed = [item for item in applied if item.get("mode") == "failed"]
    return {
        "status": status,
        "kind": kind,
        "dry_run": dry_run,
        "applied_count": len(written),
        "already_applied_count": len(already_applied),
        "success_count": len(applied_success),
        "failed_count": len(failed),
        "partial_success": bool(applied_success and failed),
        "applied": applied,
        "successful_blocks": applied_success,
        "failed_blocks": failed,
        "touched_files": sorted({item.get("effective_path") or item["path"] for item in written}),
        "referenced_files": sorted({item.get("effective_path") or item["path"] for item in applied_success}),
        "repair_hint": build_repair_hint(applied_success, failed),
        "findings": [item.__dict__ for item in findings],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Apply A9 SEARCH/REPLACE patch blocks")
    parser.add_argument("patch_file", help="Patch file to apply, or '-' for stdin")
    parser.add_argument("--root", default=str(a9_patch_guard.ROOT), help="Repository root")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without writing files")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    result = apply_search_replace(a9_patch_guard.read_patch(args.patch_file), root, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
