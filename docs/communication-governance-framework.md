# A9 Communication Governance Framework

## Decision

Communication governance is part of the A9 runtime foundation, not a UI feature.

Current priority:

```text
control API / supervisor / Redis flow
+ SSH / Tailscale / tmux private node access
+ reconnect and command lifecycle evidence
+ monitor intervention and recovery
```

## Active Contract

- Model communication as data and state first: node, ssh identity, tmux session,
  command, command result, reconnect state, repair action.
- Use Redis Streams/JSON/Functions for hot control state and revisioned flow.
- Keep MySQL/canonical persistence as the long-term source-of-record target.
- Borrow reconnect/backoff/error-action ideas from Barter-rs, but do not treat
  Barter-rs as the A9 control plane.
- Keep mobile/control as an entry into this runtime, not the runtime itself.

## Next Slice

Before adding more UI or product features, make sure each communication task has:

- object/data contract
- state transitions
- exception flow
- evidence keys
- bounded tests
- monitor visibility
