# A9 Agent Runtime Observations

## 2026-06-02: auto-next recovered, then entered a local repair loop

Context:
- The 24h worker previously stalled when `pass` plus `next_slice` did not produce `next_task_path`.
- Several repair/test slices fixed real issues around `schedule_next_task`, runtime pre-gate false positives, and `monitor_blocked_repair_checks`.
- The auto loop recovered: queue -> running -> done -> next task was observed across multiple cycles.

Useful behavior observed:
- Worker found concrete causes from run evidence instead of only guessing.
- Worker added focused tests and usually repaired failing tests before final output.
- `next_slice` routing correctly moved failed focused tests into repair phases.
- Supervisor kept raw run evidence, summaries, process governance, patches, and commits.

Quality problems observed:
- Worker repeatedly ran undeclared checks. Current policy records this as warning, which is acceptable for observation-first governance, but it creates noisy repair prompts.
- Worker started expanding one local boundary (`monitor_blocked_repair_checks` test-runner promotion) into many small edge-case slices.
- A monitor-inserted correction task hung on a simple `ls -la` tool call and had to be terminated.
- After that termination, A9 returned to the queued auto-generated test instead of prioritizing the operator correction outcome.

Monitor decision:
- Do not keep expanding test-runner boundary cases unless they block the main runtime.
- Treat this as evidence that A9 needs an explicit operator correction / priority override lane.
- Next high-value direction should return to the main runtime line: reference-first session governance or multi-machine SSH/Tailscale/tmux/Redis communication governance.

Next recommended slice:
- `reference_scan`: inspect local Codex and Aider session/context mechanisms first, then compare with OpenHands/Continue event-stream adapters.
- Goal: design a small, testable operator correction lane so monitor interventions are durable and do not get buried behind auto-generated local repair loops.
