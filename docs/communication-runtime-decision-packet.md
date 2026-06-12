# A9 Communication Runtime Decision Packet Index

Full decision packet archive:

`docs/archive/2026-06-noise-reduction/communication-runtime-decision-packet-full-20260613.md`

## Active Decision

Communication runtime work must proceed through data/state/exception contracts
before implementation.

Approved focus:

- operator session
- event cursor
- reconnect state
- command lifecycle
- monitor-visible evidence

Out of scope from this packet:

- mobile UI polish
- trading implementation
- broad runtime rewrite
- unbounded reference scans

## Next Execution Rule

Any next communication slice must name the object contract, state transition,
exception behavior, evidence path and tests it will touch.

