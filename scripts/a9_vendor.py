#!/usr/bin/env python3
"""Copy open-source reference code into A9's vendor area with provenance."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / "reference-projects"
VENDOR_DIR = ROOT / "vendor-src"
MANIFEST = VENDOR_DIR / "MANIFEST.jsonl"

LICENSES = {
    "codex": "Apache-2.0",
    "aider": "Apache-2.0",
    "mem0": "Apache-2.0",
    "langgraph": "MIT",
    "openhands": "MIT (enterprise/ is separately licensed)",
    "continue": "Apache-2.0",
    "swe-agent": "MIT",
    "cline": "Apache-2.0",
    "roo-code": "Apache-2.0",
    "gemini-cli": "Apache-2.0",
    "opencode": "MIT",
    "aichat": "MIT OR Apache-2.0",
}

LICENSE_FILES = {
    "codex": ["LICENSE"],
    "aider": ["LICENSE.txt"],
    "mem0": ["LICENSE"],
    "langgraph": ["LICENSE"],
    "openhands": ["LICENSE"],
    "continue": ["LICENSE"],
    "swe-agent": ["LICENSE"],
    "cline": ["LICENSE"],
    "roo-code": ["LICENSE"],
    "gemini-cli": ["LICENSE"],
    "opencode": ["LICENSE"],
    "aichat": ["LICENSE-APACHE", "LICENSE-MIT"],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)


def git_commit(path: Path) -> str:
    result = run(["git", "rev-parse", "HEAD"], cwd=path)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def validate_source(project: str, rel_path: str) -> Path:
    if project not in LICENSES:
        raise SystemExit(f"Unknown project or license not reviewed: {project}")
    if project == "openhands" and (rel_path == "enterprise" or rel_path.startswith("enterprise/")):
        raise SystemExit("Refusing OpenHands enterprise/ copy; license is separate.")
    source = (REFERENCE_DIR / project / rel_path).resolve()
    project_root = (REFERENCE_DIR / project).resolve()
    if not source.exists():
        raise SystemExit(f"Source does not exist: {source}")
    if project_root not in source.parents and source != project_root:
        raise SystemExit(f"Source escapes project root: {source}")
    return source


def copy_tree_or_file(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        ignore = shutil.ignore_patterns(".git", "__pycache__", "node_modules", "target", "dist", "build")
        shutil.copytree(source, dest, ignore=ignore)
    else:
        shutil.copy2(source, dest)


def append_manifest(record: dict[str, Any]) -> None:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def copy_license_files(project: str) -> list[str]:
    copied: list[str] = []
    project_root = REFERENCE_DIR / project
    dest_root = VENDOR_DIR / project
    for rel in LICENSE_FILES.get(project, []):
        source = project_root / rel
        if not source.exists():
            continue
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        copied.append(str(dest.relative_to(ROOT)))
    return copied


def import_source(args: argparse.Namespace) -> int:
    source = validate_source(args.project, args.source)
    project_root = REFERENCE_DIR / args.project
    dest = VENDOR_DIR / args.project / args.source
    copy_tree_or_file(source, dest)
    copied_license_files = copy_license_files(args.project)
    record = {
        "imported_at": utc_now(),
        "project": args.project,
        "license": LICENSES[args.project],
        "source_commit": git_commit(project_root),
        "source_path": str(source.relative_to(project_root)),
        "dest_path": str(dest.relative_to(ROOT)),
        "mode": args.mode,
        "purpose": args.purpose,
        "modified_by_a9": False,
        "license_files": copied_license_files,
    }
    append_manifest(record)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def list_projects(_: argparse.Namespace) -> int:
    for project, license_name in sorted(LICENSES.items()):
        exists = (REFERENCE_DIR / project).exists()
        print(f"{project}\t{license_name}\t{'present' if exists else 'missing'}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="A9 vendor importer")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")

    imp = sub.add_parser("import")
    imp.add_argument("project")
    imp.add_argument("source")
    imp.add_argument("--mode", choices=["source-slice", "module-fork"], default="source-slice")
    imp.add_argument("--purpose", required=True)

    args = parser.parse_args(argv)
    if args.command == "list":
        return list_projects(args)
    if args.command == "import":
        return import_source(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
