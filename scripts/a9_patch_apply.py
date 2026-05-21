#!/usr/bin/env python3
"""Apply A9 SEARCH/REPLACE edits with Aider-style strictness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import a9_patch_guard


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
        resolved = a9_patch_guard.validate_rel_path(root, block.path, findings)
        if resolved is None:
            continue

        current = ""
        creating_file = not resolved.exists() and block.search == ""
        if resolved.exists():
            if not resolved.is_file():
                findings.append(a9_patch_guard.Finding("error", "target path is not a file", block.path))
                continue
            current = resolved.read_text(encoding="utf-8")
        elif not creating_file:
            findings.append(a9_patch_guard.Finding("error", "target file does not exist", block.path))
            continue

        if block.search == "" and not creating_file:
            findings.append(a9_patch_guard.Finding("error", "empty SEARCH is only allowed for new files", block.path))
            continue

        if creating_file:
            new_content = block.replace
            matches = 0
        else:
            matches = current.count(block.search)
            if matches != 1:
                findings.append(
                    a9_patch_guard.Finding(
                        "error",
                        f"SEARCH content must match exactly once; found {matches}",
                        block.path,
                    )
                )
                continue
            new_content = current.replace(block.search, block.replace, 1)

        if new_content == current and not creating_file:
            findings.append(a9_patch_guard.Finding("warning", "replacement is identical to search", block.path))

        if not dry_run:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(new_content, encoding="utf-8")
        applied.append(
            {
                "index": index,
                "path": block.path,
                "line": block.line,
                "mode": "create" if creating_file else "replace",
                "search_bytes": len(block.search.encode("utf-8")),
                "replace_bytes": len(block.replace.encode("utf-8")),
                "matches": matches,
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
    return {
        "status": status,
        "kind": kind,
        "dry_run": dry_run,
        "applied_count": len(applied),
        "applied": applied,
        "touched_files": sorted({item["path"] for item in applied}),
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
