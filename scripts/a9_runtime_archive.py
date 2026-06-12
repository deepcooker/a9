#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".a9"
RUNS_DIR = STATE_DIR / "runs"
WORKTREES_DIR = STATE_DIR / "worktrees"
TASKS_DIR = STATE_DIR / "tasks"
ARCHIVE_DIR = STATE_DIR / "archive"


@dataclass(frozen=True)
class ArchiveCandidate:
    kind: str
    path: Path
    archive_path: Path | None
    reason: str
    action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": str(self.path),
            "archive_path": str(self.archive_path) if self.archive_path else "",
            "reason": self.reason,
            "action": self.action,
        }


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def list_child_dirs(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted((item for item in path.iterdir() if item.is_dir()), key=lambda item: (path_mtime(item), item.name), reverse=True)


def list_task_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: (path_mtime(item), str(item)), reverse=True)


def archive_bucket(kind: str, path: Path) -> Path:
    date = datetime.fromtimestamp(path_mtime(path), timezone.utc).strftime("%Y%m%d")
    return ARCHIVE_DIR / kind / date / path.name


def git_worktree_paths() -> set[Path]:
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return set()
    paths: set[Path] = set()
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            raw = line.removeprefix("worktree ").strip()
            if raw:
                paths.add(Path(raw).resolve())
    return paths


def protected_task_ids() -> set[str]:
    protected: set[str] = set()
    for subdir in ("queue", "running"):
        directory = TASKS_DIR / subdir
        if not directory.exists():
            continue
        for item in directory.iterdir():
            if item.is_file():
                protected.add(item.stem)
    return protected


def worktree_task_id(path: Path) -> str:
    name = path.name
    return re.sub(r"-attempt-\d+$", "", name)


def run_task_id(path: Path) -> str:
    name = path.name
    match = re.match(r"(.+)-\d{8}T\d{6}Z-a\d+$", name)
    return match.group(1) if match else name


def run_candidates(*, keep_runs: int) -> list[ArchiveCandidate]:
    runs = list_child_dirs(RUNS_DIR)
    stale_runs = list(reversed(runs[keep_runs:]))
    candidates: list[ArchiveCandidate] = []
    for run in stale_runs:
        candidates.append(
            ArchiveCandidate(
                kind="run",
                path=run,
                archive_path=archive_bucket("runs", run),
                reason=f"older_than_newest_{keep_runs}_runs task_id={run_task_id(run)}",
                action="move",
            )
        )
    return candidates


def task_candidates(*, keep_done_files: int) -> list[ArchiveCandidate]:
    candidates: list[ArchiveCandidate] = []
    for subdir in ("done", "blocked", "interrupted"):
        files = list_task_files(TASKS_DIR / subdir)
        stale_files = list(reversed(files[keep_done_files:]))
        for item in stale_files:
            candidates.append(
                ArchiveCandidate(
                    kind=f"task_{subdir}",
                    path=item,
                    archive_path=archive_bucket(f"tasks/{subdir}", item),
                    reason=f"older_than_newest_{keep_done_files}_{subdir}_task_files",
                    action="move",
                )
            )
    return candidates


def worktree_candidates(*, keep_worktrees: int) -> list[ArchiveCandidate]:
    worktrees = list_child_dirs(WORKTREES_DIR)
    stale_worktrees = list(reversed(worktrees[keep_worktrees:]))
    git_paths = git_worktree_paths()
    protected_ids = protected_task_ids()
    candidates: list[ArchiveCandidate] = []
    for worktree in stale_worktrees:
        task_id = worktree_task_id(worktree)
        if task_id in protected_ids:
            continue
        resolved = worktree.resolve()
        action = "git_worktree_remove" if resolved in git_paths else "move"
        archive_path = None if action == "git_worktree_remove" else archive_bucket("worktrees", worktree)
        candidates.append(
            ArchiveCandidate(
                kind="worktree",
                path=worktree,
                archive_path=archive_path,
                reason=f"older_than_newest_{keep_worktrees}_worktrees task_id={task_id}",
                action=action,
            )
        )
    return candidates


def apply_candidate(candidate: ArchiveCandidate) -> None:
    if candidate.action == "move":
        if candidate.archive_path is None:
            raise ValueError(f"archive_path required for move: {candidate.path}")
        candidate.archive_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(candidate.path), str(candidate.archive_path))
        return
    if candidate.action == "git_worktree_remove":
        subprocess.run(["git", "worktree", "remove", "--force", str(candidate.path)], cwd=ROOT, check=True)
        return
    raise ValueError(f"unsupported action: {candidate.action}")


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    candidates: list[ArchiveCandidate] = []
    if args.include_runs:
        candidates.extend(run_candidates(keep_runs=args.keep_runs))
    if args.include_tasks:
        candidates.extend(task_candidates(keep_done_files=args.keep_task_files))
    if args.include_worktrees:
        candidates.extend(worktree_candidates(keep_worktrees=args.keep_worktrees))
    limit = int(args.limit or 0)
    selected = candidates[:limit] if limit > 0 else candidates
    return {
        "schema": "a9.runtime_archive_plan.v1",
        "created_at": utc_stamp(),
        "dry_run": not args.apply,
        "root": str(ROOT),
        "keep_runs": args.keep_runs,
        "keep_worktrees": args.keep_worktrees,
        "keep_task_files": args.keep_task_files,
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "candidates": [candidate.to_dict() for candidate in selected],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or apply safe A9 runtime archive cleanup.")
    parser.add_argument("--apply", action="store_true", help="Apply selected cleanup actions. Default is dry-run.")
    parser.add_argument("--keep-runs", type=int, default=50)
    parser.add_argument("--keep-worktrees", type=int, default=20)
    parser.add_argument("--keep-task-files", type=int, default=100)
    parser.add_argument("--limit", type=int, default=0, help="Limit selected candidates; 0 means all.")
    parser.add_argument("--include-runs", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-worktrees", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-tasks", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--json", action="store_true", help="Print full JSON plan.")
    args = parser.parse_args()

    plan = build_plan(args)
    if args.apply:
        for item in plan["candidates"]:
            apply_candidate(
                ArchiveCandidate(
                    kind=item["kind"],
                    path=Path(item["path"]),
                    archive_path=Path(item["archive_path"]) if item.get("archive_path") else None,
                    reason=item["reason"],
                    action=item["action"],
                )
            )
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        mode = "apply" if args.apply else "dry-run"
        print(f"runtime archive {mode}: candidates={plan['candidate_count']} selected={plan['selected_count']}")
        by_action: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for item in plan["candidates"]:
            by_action[item["action"]] = by_action.get(item["action"], 0) + 1
            by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
        print("by_action:", " ".join(f"{key}={value}" for key, value in sorted(by_action.items())) or "none")
        print("by_kind:", " ".join(f"{key}={value}" for key, value in sorted(by_kind.items())) or "none")
        for item in plan["candidates"][:20]:
            print(f"{item['action']} {item['kind']} {item['path']} -> {item['archive_path']} ({item['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
