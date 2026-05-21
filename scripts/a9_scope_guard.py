#!/usr/bin/env python3
"""Validate whether a recorded diff stayed inside the task scope."""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from dataclasses import dataclass
from pathlib import Path


BLOCKED_PARTS = {
    ".git",
    "__pycache__",
    "node_modules",
    "target",
    "vendor-src",
    "reference-projects",
}
SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
    "known_hosts",
}


@dataclass
class Finding:
    level: str
    message: str
    path: str | None = None


def normalize_diff_path(raw: str) -> str:
    raw = raw.strip()
    if raw == "/dev/null":
        return raw
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    if raw.startswith("a/") or raw.startswith("b/"):
        raw = raw[2:]
    return raw


def changed_files_from_diff(text: str) -> list[str]:
    touched: set[str] = set()
    for line in text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            for raw in parts[2:4]:
                rel = normalize_diff_path(raw)
                if rel != "/dev/null":
                    touched.add(rel)
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            rel = normalize_diff_path(line[4:])
            if rel != "/dev/null":
                touched.add(rel)
    return sorted(touched)


def is_allowed(path: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    normalized = path.strip("/")
    for pattern in patterns:
        item = pattern.strip().strip("/")
        if not item:
            continue
        if any(ch in item for ch in "*?[]"):
            if fnmatch.fnmatch(normalized, item):
                return True
            continue
        if normalized == item or normalized.startswith(item.rstrip("/") + "/"):
            return True
    return False


def validate_path(path: str, allowed_paths: list[str], findings: list[Finding]) -> None:
    candidate = Path(path)
    if candidate.is_absolute():
        findings.append(Finding("error", "absolute paths are not allowed", path))
        return
    if ".." in candidate.parts:
        findings.append(Finding("error", "path traversal is not allowed", path))
        return
    blocked = BLOCKED_PARTS.intersection(candidate.parts)
    if blocked:
        findings.append(Finding("error", f"blocked path component: {sorted(blocked)[0]}", path))
    if candidate.name in SENSITIVE_NAMES or any(part in {".ssh", ".aws", ".config"} for part in candidate.parts):
        findings.append(Finding("error", "sensitive credential/config path is not allowed", path))
    if not is_allowed(path, allowed_paths):
        findings.append(Finding("error", "changed file is outside allowed_paths", path))


def report(changed_files: list[str], allowed_paths: list[str], findings: list[Finding]) -> dict[str, object]:
    status = "fail" if any(item.level == "error" for item in findings) else "pass"
    return {
        "status": status,
        "changed_files": changed_files,
        "allowed_paths": allowed_paths,
        "findings": [item.__dict__ for item in findings],
    }


def validate_diff(text: str, allowed_paths: list[str]) -> dict[str, object]:
    findings: list[Finding] = []
    changed_files = changed_files_from_diff(text)
    for path in changed_files:
        validate_path(path, allowed_paths, findings)
    if not changed_files:
        findings.append(Finding("info", "no changed files"))
    return report(changed_files, allowed_paths, findings)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate A9 diff scope")
    parser.add_argument("patch_file", help="Unified diff file to validate, or '-' for stdin")
    parser.add_argument("--allow", action="append", default=[], help="Allowed path prefix/glob; repeatable")
    args = parser.parse_args(argv)

    text = sys.stdin.read() if args.patch_file == "-" else Path(args.patch_file).read_text(encoding="utf-8")
    result = validate_diff(text, [str(item) for item in args.allow])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
