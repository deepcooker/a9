# A9 错题本索引

This file is the active wrongbook pointer and small hot lane.

Full historical wrongbook was archived to:

`docs/archive/evidence/mistakes-full-20260613.md`

## Current Use

- Do not read the full archive by default.
- New real failure modes may be appended here as small active entries.
- Periodically fold active entries into the archive and keep this file short.
- Tests and patch/apply examples may still reference `docs/mistakes.md`; keep
  this path alive.

## Hot Lessons

- Do not trust worker self-evaluation over deterministic checks, diff, guard,
  tests and monitor evidence.
- Do not use fixed line/token counts as early hard gates; observe first, then
  optimize by architecture.
- Do not let ordinary workers read raw session or large evidence logs unless the
  task is explicitly bounded.
- Do not mix A9 runtime work with A3B training or financial strategy work.
- Keep business/data shape first, performance second, engineering gates after
  the shape is stable.

## Active Entries

New entries after 2026-06-13 should go below.

