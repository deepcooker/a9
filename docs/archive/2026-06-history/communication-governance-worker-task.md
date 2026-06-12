# Worker Task: Communication Governance Slice 1

Use this as the bounded task prompt for the 24-hour execution machine after the
human/operator approves the framework.

```text
You are the A9 24-hour execution worker. Follow AGENTS.md.

Goal:
Copy mature communication resilience mechanisms into A9's gateway/node layer.
Do not work on mobile UI. Do not invent from scratch before reading references.

Phase:
reference_scan -> mechanism_extract -> implement -> test -> record

References to inspect first:
- reference-projects/barter-rs/barter-integration/src/socket/backoff.rs
- reference-projects/barter-rs/barter-integration/src/socket/on_connect_err.rs
- reference-projects/barter-rs/barter-integration/src/socket/on_stream_err.rs
- reference-projects/barter-rs/barter-integration/src/socket/mod.rs
- reference-projects/barter-rs/barter-integration/src/socket/update.rs
- reference-projects/barter-rs/barter/src/engine/audit/state_replica.rs
- reference-projects/barter-rs/barter/src/engine/command.rs
- reference-projects/barter-rs/barter/src/strategy/on_disconnect.rs
- vendor-src/codex/codex-rs/core/src/compact.rs
- vendor-src/codex/codex-rs/core/src/context_manager/history.rs

Repository files likely in scope:
- crates/a9-gateway/src/main.rs
- scripts/a9_control_api.py
- scripts/a9_node.py
- tests/test_control_api.py
- tests/test_node.py
- docs/communication-governance-framework.md
- docs/copied-mechanisms.md

Implementation target:
1. Finish Rust gateway retry/backoff as a tested primitive.
2. Keep Barter-rs style: typed retry/backoff policy, capped exponential delay,
   and clear failure classification.
3. Keep Redis hot state for node heartbeats: JSON snapshot + stream event +
   TimeSeries metric where Redis is available; local file fallback otherwise.
4. Add or update focused tests only. Do not broaden into mobile UI.
5. Record what was copied, from which file, commit, and license.

Acceptance:
- cargo test for a9-gateway passes.
- Python tests for control/node heartbeat pass.
- Docs record Barter-rs source and copied mechanism.
- Output final strict envelope with changed files, tests, pass/fail, and next
  concrete slice.

Stop conditions:
- If reference files are missing, stop with repair evidence.
- If Redis assumptions are wrong, write a repair task instead of faking pass.
- If task grows toward SSE + WebSocket + UI together, stop and split.
```

Recommended next slice after this one:

```text
SSE replay slice:
Redis Streams -> /api/events SSE -> Last-Event-ID replay -> mobile/web reconnect
tests.
```
