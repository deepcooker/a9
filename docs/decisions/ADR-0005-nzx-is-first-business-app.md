# ADR-0005: NZX Is First Business App

> Status: accepted
> Date: 2026-06-04

## Decision

NZX RWA Orderbook Appchain is A9's first heavy business application. It is not
the A9 foundation itself.

## Boundary

A9 foundation:

```text
runtime
monitor
communication
private network
model/compute control
evidence/session governance
trading infrastructure control plane
```

NZX application:

```text
NZX assets
custody/SPV/trust structure
wNZX token
Rust CLOB
market making
broker adapter
appchain settlement
proof-of-reserve
audit/reporting
```

## Consequences

- Current first engineering work does not implement NZX trading code.
- NZX requirements must later go through the same requirements/data/performance
  closure before execution.

