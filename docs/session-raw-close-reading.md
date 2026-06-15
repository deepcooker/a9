# A9 Raw Session 精读索引

This file is the active pointer for external Codex/operator session close
reading. It is intentionally small.

Raw source session:

`/root/.codex/sessions/2026/05/21/rollout-2026-05-21T11-20-49-019e488c-d5f9-7501-835a-bf6e8ff6d8a2.jsonl`

## Current Use

- Default worker context must not read the full archive.
- `session_refresh` and `session_close_reading` may append new bounded
  deterministic extracts here.
- When this file grows past a small active window, fold the causal fact into
  `docs/session-causal-memory.md` and delete process noise.
- For product or causal-memory recovery, read `docs/session-raw-summary.md` and
  `docs/session-causal-memory.md` first.

## Historical Coverage

The archived full reading contains:

- manual close reading from early turns through turn 577-era architecture
  aggregation work
- auto close reading entries through turns 693-696
- line references into the raw JSONL session

## Active Appends

New auto close-reading entries may appear below this section.
