# A9 Patch / Diff Discipline

## Position

A9 should not accept a worker's free-form claim that code was changed. Patch
execution must be bounded, checkable, and backed by evidence.

This document is a mechanism adaptation, not copied source. The local reference
files are Apache-2.0 under `docs/vendor-strategy.md`:

- `vendor-src/aider/aider/history.py`
- `vendor-src/aider/aider/repomap.py`

## Aider Mechanisms Extracted

- Keep edits small enough that the old text can be matched exactly.
- Treat recent high-fidelity context as more valuable than broad old context.
- Use repo maps and symbols to choose context instead of dumping full
  repositories.
- Maintain a token budget separately for chat/history and repository context.
- Fail closed when an edit target is ambiguous, missing, or outside the allowed
  workspace.

## A9 Rules

1. A worker patch must be represented as structured edit text, preferably
   Aider-style `SEARCH/REPLACE` blocks or a unified diff.
2. A `SEARCH` block must match the current target file exactly once before any
   edit is applied.
3. Patch paths must be repository-relative. Absolute paths and `..` traversal
   are invalid.
4. Reference and vendor areas are read-only for ordinary implementation patches:
   `vendor-src/` and `reference-projects/` are blocked unless a task explicitly
   enters the vendor import flow.
5. Patch validation result must be recorded as evidence before execution.
6. A failed patch validation is a repair event, not a reason to continue adding
   features.

## Prototype

`scripts/a9_patch_guard.py` validates:

- Aider-style blocks:

```text
path/to/file.py
<<<<<<< SEARCH
old exact text
=======
new text
>>>>>>> REPLACE
```

  It also accepts the documented Aider variant where the path line is followed
  by an opening markdown code fence before `<<<<<<< SEARCH`.

- Unified diffs with basic file path, hunk, and changed-line sanity checks.

Example:

```bash
python3 scripts/a9_patch_guard.py proposed.patch --root .
```

The command prints JSON with `status`, touched files, and findings. Exit code is
zero only when validation passes.

## Supervisor Integration

`scripts/a9_supervisor.py` now runs the patch guard against the captured
`patch.diff` before classifying a completed run. The guard result is written to
`patch_guard.json`, recorded as `patch_guard` evidence, added to the checkpoint
`patches` channel, and marked in deep context as `patch_guard_result`.

A non-empty worker diff must pass this guard before the run can be considered
`pass`. If patch validation fails, the supervisor classifies the run as
`needs-repair` even when the worker process and declared checks returned zero.
Empty diffs are recorded with a skipped guard result and still use the existing
`needs-followup` path.

## SEARCH/REPLACE Apply Engine

`scripts/a9_patch_apply.py` is the first A9-native apply engine copied from
Aider's edit-block discipline:

- only `SEARCH/REPLACE` blocks are accepted;
- each `SEARCH` must match exactly once before writing;
- ambiguous or missing matches fail without modifying the target file;
- empty `SEARCH` is allowed only when creating a new file;
- `--dry-run` reports the planned edits without writing files.

This is intentionally stricter than a free-form model answer. The model may
propose text, but A9 applies only deterministic, auditable edits.
