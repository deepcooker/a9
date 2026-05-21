# A9 Copy Pipeline

This is the default 24-hour automation loop. It is domain-neutral; quant work is
future business logic, not the current service milestone.

Phases:

1. `reference_scan`: inspect mature local reference projects and choose one
   concrete mechanism.
2. `mechanism_extract`: document the moving parts, contracts, failure modes,
   context behavior, and cost controls.
3. `vendor_import`: copy licensed source slices into `vendor-src/` and record
   source, commit, purpose, and license obligations.
4. `implement`: adapt the mechanism into A9 with bounded code or docs changes.
5. `test`: add or strengthen automated verification.
6. `record`: update docs, evidence, progress, and next task state.
7. `repair`: fix failed checks or missing evidence before returning to the
   current phase.

The supervisor schedules these phases through `run-loop --auto-next`. A worker
must not stop at analysis when code, tests, or durable records are needed.

Use `scripts/a9_soak.py run --tasks N --fake-worker` for bounded unattended
verification of the loop without spending model tokens. The report is written to
`.a9/soak/latest.json` and a timestamped file under `.a9/soak/reports/`.
The fake worker is the default; pass `--real-worker` only for deliberate live
worker testing.

Soak reports include a compact `latest_runs[].guards` view copied from the
recorded run summaries. This view is only an index: the canonical evidence
remains each run's `summary.json`, `patch_guard.json`, `scope_guard.json`,
`evidence.jsonl`, checks, and raw event files.
