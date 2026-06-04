# ADR-0003: Communication Foundation

> Status: accepted
> Date: 2026-06-04

## Decision

A9 communication starts with typed commands and replayable events:

```text
REST typed command plane
SSE event tail first
Redis Streams hot event bus
Python supervisor/model logic
Rust gateway/bus hot path
SSH/tmux fallback for repair and takeover
```

WebSocket can be added later where true bidirectional terminal/chat is required.

## Command Envelope

Every command must include:

```text
command_id
target_node
expected_revision
ttl
created_by
policy_attestation
idempotency_key
evidence_path
```

## Node State

```text
online -> stale -> offline -> degraded -> reconnecting -> online
```

## Consequences

- UI state is never canonical.
- Redis is hot event/control infrastructure, not trading ledger.
- Replay gaps, stale heartbeat, retry, timeout, disconnect, and repair must
  write bounded evidence.

