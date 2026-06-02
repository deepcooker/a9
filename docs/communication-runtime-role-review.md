# A9 Communication Runtime Role Review

Date: 2026-06-02

## Status

`partial_decision`.

This is round 2 review for communication runtime. It uses:

- `docs/communication-runtime-decision-packet.md`
- `.a9/runs/communication-runtime-model-validation-20260602-20260602T141549Z-a1`
- `.a9/runs/communication-runtime-model-validation-narrow-20260602-20260602T151204Z-a1`
- `.a9/runs/communication-runtime-model-validation-narrow2-20260602-20260602T151510Z-a1`

The broad worker run produced useful model-gap evidence but over-read. The two
narrow retries proved the new read-scope governance works: worker expansion was
stopped early instead of consuming another large token budget.

## Evidence Quality

Useful evidence from the broad run:

- Missing or not-yet-modeled entities:
  `operator_session`, `ssh_identity`, `tmux_session`, `repair_action`.
- Partial entities:
  `node`, `command`, `command_result`, `event_cursor`, `heartbeat`,
  `reconnect_state`.
- Existing strengths:
  Redis Streams command/result flow, cursor/replay/gap behavior,
  gateway reconnect classification, Barter-style typed reconnect actions, and
  async audit surfaces.

Rejected or corrected evidence:

- The claim that `reference-projects/codex/codex-rs/core/src/tasks/mod.rs` is
  missing is false in the current repository snapshot.
- The broad run read outside its intended scope; its output is evidence, not a
  clean pass.
- The two narrow runs were correctly `monitor-blocked`; they should be treated
  as worker-discipline observations, not communication-model failures.

## Product / Mainline

Decision: pass with constraints.

The product problem is stable control of the 24h execution machine across
phone/web/CLI and multiple nodes. The product object is controllable runtime
state, not SSH itself and not mobile UI polish.

Mainline constraints:

- Data model first.
- Transport/state/replay before UI polish.
- Operator authority must remain above worker auto-continuation.
- Any reconnect/repair automation must leave evidence and audit.

Product rejects starting with a broad Rust rewrite or more mobile features.

## Business

Decision: pass with constraints.

The business requirement is continuity:

- know which node is alive;
- know which session/command is active;
- recover after disconnect;
- replay missed output;
- audit remote mutation;
- make the operator technically unaware of SSH/tmux/Redis details.

The key business entities are:

- operator session;
- node;
- ssh identity;
- tmux session;
- command;
- command result;
- cursor;
- heartbeat;
- reconnect state;
- repair action;
- audit event.

These must become the shared language before implementation expands.

## Architecture

Decision: needs one model-closure slice before feature implementation.

Current architecture is partly aligned:

- Redis Streams already fit hot event delivery and replay.
- Rust gateway already has reconnect decisions and retry evidence.
- Python control/node layer already exposes command/result/recovery routes.
- MySQL is declared as canonical but not yet represented as a communication
  schema.

Architecture gaps:

- no canonical communication schema document;
- no single v1 mapping from business object to Redis/MySQL/local evidence;
- no dedicated tmux session lifecycle object;
- no ssh identity object;
- no operator session object;
- repair actions are payload-shaped but not entity-shaped;
- expected revision exists conceptually but is not uniform across node/command
  communication states.

Architecture decision:

The first approved implementation candidate is not a feature. It is a
model-closure artifact:

```text
implement: communication-runtime data contract v1
```

It should define object fields, stream keys, Redis snapshot keys, MySQL target
tables, state transitions, and minimal validation evidence. It may add a
non-blocking validator/report only if the data contract is clear and bounded.

## Test / Data

Decision: partial pass.

Test/data approves a doc-first contract slice because current fixtures can drift
from the real data model. The next slice must specify testable invariants before
changing runtime behavior.

Required acceptance for the next slice:

- data contract file exists;
- each object has required fields, owner, source-of-truth, hot cache, event key,
  and evidence path;
- each state transition has normal path and exception path;
- current code mapping is explicit: `missing`, `partial`, or `implemented`;
- no broad reference or docs scan;
- no runtime behavior change unless explicitly scoped as validation/reporting.

## Runtime Governance

Decision: pass for monitor behavior, fail for worker discipline.

What worked:

- explicit allowed-read-scope governance stopped narrow retries quickly;
- no large token burn repeated after the broad run;
- monitor could distinguish useful evidence from bad run quality.

What failed:

- worker ignored "do not read other paths" and searched context docs;
- worker treated injected method/context docs as read targets;
- first repair run tried to inspect a run evidence path outside the task's
  allowed read scope.

Governance decision:

Keep read-scope enforcement for tasks that explicitly say "inspect/read only
allowed_paths." Do not make `allowed_paths` a global read gate for normal
implementation tasks.

## Final Decision

Communication runtime is not ready for feature implementation.

It is ready for one decided model-closure slice:

```text
decision_status: decided
phase: implement
task: create communication runtime data contract v1
allowed_paths:
  - docs/communication-runtime-data-contract-v1.md
  - docs/communication-runtime-role-review.md
  - docs/communication-runtime-decision-packet.md
checks:
  - no runtime code changes
  - document includes object model, stream/key model, state transitions,
    exception transitions, current-code conformance, first next implementation
    candidate
```

Next implementation after that contract, if accepted:

```text
implement: non-blocking communication data-contract report endpoint or CLI
```

Do not start SSH/tmux feature coding before the v1 contract exists.
