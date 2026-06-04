# ADR-0001: A9 Highest Form

> Status: accepted
> Date: 2026-06-04

## Decision

A9 is a private AgentOS financial trading foundation:

```text
financial trading infrastructure control plane
+ 24h agent execution system
+ private compute/model scheduling layer
+ high-performance trading runtime environment
+ ResearchOps / training data loop
```

NZX RWA Orderbook Appchain is the first heavy business application on top of A9,
not A9 itself.

## Context

The project drifted across worker automation, mobile UI, communication, private
networking, compute, and NZX business design. The clarified layer boundary is
required so implementation does not jump from a foundation concern into a
business app or UI detail.

## Consequences

- Runtime/monitor/communication foundations are the current first engineering
  path.
- NZX design remains important but out of the immediate execution scope.
- Mobile is a control plane entrance, not the state authority.
- AI/Agent remains side path for development, research, monitoring, review, and
  training data, not trading hot path.

