# A9 Stage Handoff - 2026-06-01

## Current Stage

This stage is closed enough to summarize before the next implementation slice.

Scope completed:

- Communication status has one canonical read model:
  `GET /api/communication/status`.
- Communication action planning is deterministic:
  `GET /api/communication/action-plan`.
- Bounded repair exists:
  `POST /api/communication/repair-one`.
- Recovery loop observes communication plan every cycle and writes
  `.a9/services/communication-observation.json`.
- Stable action streaks are observe-only. They do not auto-execute.
- Candidate repairs are written into
  `.a9/services/communication-repair-suggestions.json`.
- Suggestion review supports `approve`, `ignore`, and `resolve`.
- Review/audit is an async sidecar. It must not block the hot communication
  status/read/repair path.
- Mobile control can see communication status, action plan, recovery loop,
  observation streak, repair suggestions, and review controls.
- Main services are running: `control-api`, `recovery-loop`, `node-worker`,
  and `supervisor`.

Current live state when this handoff was written:

- `communication.status = ok`
- `communication.action = continue`
- `communication.reason = tailscale:ok`
- `communication_observation.current_key = tailscale:continue:noop`
- `communication_observation.recommendation = continue_observation`
- `communication_observation.auto_execute = false`
- `communication_repair_suggestions.pending_count = 0`

## Verified Checks

Latest verified checks:

```bash
python3 -m py_compile scripts/a9_control_api.py
python3 -m unittest tests.test_control_api tests.test_recovery_loop
```

Result: 209 tests passed.

Mobile project checks:

```bash
npx tsc --noEmit
npm run smoke:mobile
```

Result: passed.

Latest relevant main commit:

```text
b54a15b Add async communication suggestion review
```

## Boundaries

Do not continue by adding more gates before the next summary cycle.

Active rules:

- Data first, performance second.
- Business/data/architecture shape comes before hard gates.
- Gates should observe first and block only destructive, unsafe, license,
  scope, or fact-source corrupting behavior.
- Review/audit/evaluation must be async sidecar by default.
- Mobile is the control plane entry, not the canonical runtime state.
- Communication governance belongs in the runtime/control API/recovery loop
  layer, not in UI polish.
- External Codex/operator session and A9 runtime session remain separate.

## Observed Problems

Problems observed during this stage:

- Worker/main monitor can drift into UI details when the mainline is runtime
  governance.
- Fixed numeric context gates are too easy to overfit. They should record
  context pressure and only block at hard failure boundaries.
- Mobile smoke caught a real UI stability issue: recovery card controls should
  render stable placeholders even when observation data has not arrived.
- Review/audit must not sit on the hot path. This was corrected with async
  sidecar audit.
- The current summary state is already large enough that the next meaningful
  task should not be another feature slice. It should be session governance
  consolidation.

## Next Required Task

Next round must be session incremental close reading and causal consolidation.

Goal:

```text
external Codex/operator session
-> bounded incremental extraction
-> close-reading with turn/line anchors
-> causal change log
-> idea iteration detail
-> observed problem analysis
-> noise removal
-> updated current summary
```

This is not a normal feature task and not a project-copy task.

Required inputs:

- Raw session:
  `/root/.codex/sessions/2026/05/21/rollout-2026-05-21T11-20-49-019e488c-d5f9-7501-835a-bf6e8ff6d8a2.jsonl`
- Existing close reading:
  `docs/session-raw-close-reading.md`
- Existing rolling summary:
  `docs/session-raw-summary.md`
- Causal memory:
  `docs/session-causal-memory.md`
- This handoff:
  `docs/stage-handoff-2026-06-01.md`
- Mistakes:
  `docs/mistakes.md`

Expected outputs:

- Update `docs/session-raw-close-reading.md` with the next bounded turn range
  and approximate line anchors.
- Update `docs/session-raw-summary.md` with the latest distilled state.
- Update `docs/session-causal-memory.md` with:
  - what changed
  - why it changed
  - which idea expired or was downgraded
  - what is now active
  - what worker must not do next
- Update `docs/mistakes.md` only for real observed failure modes.
- Remove or demote noise from current docs only when it clearly conflicts with
  the active mainline.

## Suggested Supervisor Task

Use the deterministic session mini-flow first. Do not ask an AI worker to read
the whole session.

```bash
python3 scripts/a9_supervisor.py enqueue refresh-next \
  $'source_session_path: /root/.codex/sessions/2026/05/21/rollout-2026-05-21T11-20-49-019e488c-d5f9-7501-835a-bf6e8ff6d8a2.jsonl\nfrom_turn: <next_turn>\nto_turn: <next_turn>\nbatch_size: 1\nauto_continue: true\nauto_close_reading: true\nclose_reading_doc: docs/session-raw-close-reading.md\nsummary_doc: docs/session-raw-summary.md' \
  --phase session_refresh --timeout-seconds 120 --idle-timeout-seconds 120 --max-attempts 1

python3 scripts/a9_supervisor.py run-loop --auto-next --max-tasks 4 --keep-going-on-error
```

After the mini-flow writes bounded evidence, the monitor must do the causal
统筹 step. The deterministic flow can extract and index; it cannot decide which
ideas became obsolete.

## Summary For Next Monitor

The project is not stuck. The current communication/control slice is usable and
verified. The correct next move is to refresh the operator-session memory before
starting another implementation run, because the main risk is now idea drift,
not missing code.

