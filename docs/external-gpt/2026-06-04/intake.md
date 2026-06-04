# GPT Review Intake: A9 AgentOS Financial Foundation

> Date: 2026-06-04
> Source files:
>
> - `docs/external-gpt/2026-06-04/A9_AgentOS_金融交易环境重构决策包.md`
> - `docs/external-gpt/2026-06-04/A9_AgentOS_金融交易环境全景图.svg`
> - `docs/external-gpt/2026-06-04/gpt.md`

## Status

Accepted as a strong external review input. It is not yet a final ADR set and
does not authorize immediate large code migration.

The review correctly strengthens the current direction:

```text
A9 = private AgentOS financial trading foundation
NZX RWA Orderbook Appchain = first heavy business application
24h worker/mobile/control/compute/network/session governance = foundation layers
```

## What It Clarified

1. A9 and NZX must be separated by layer.
   A9 is the foundation/control plane/runtime; NZX is the first application on
   top of it.
2. The next step is not NZX implementation, K8s, or mobile UI polishing.
   The next step is decision closure: ADRs, vendor baseline, code boundary, and
   execution task contracts.
3. Reference projects need stronger classification:
   direct vendor candidate, mechanism copy, sidecar reference, or forbidden
   mainline.
4. Current Python/Rust MVP pieces are valuable evidence, but several are
   legacy/prototype candidates after the architecture settles.
5. Agent/AI remains side path. It must not enter trading matching, settlement
   finality, or authority-of-record paths.

## Accepted Decisions

- A9 is a financial AgentOS foundation, not a single worker, app, VPN, exchange,
  or quant strategy.
- NZX RWA is the first business application, not the whole A9 product.
- AI/Agent must not enter trading hot path.
- Redis/Valkey/Dragonfly are hot mirror/cache/control bus, not trading ledger.
- Rust CLOB is the trading authority candidate.
- Barter-rs is a strong reference for market data, reconnect, broker/exchange
  adapters, market making, hedging, and failure governance; it is not the CLOB
  matching kernel.
- Compute RWA/tokenomics remains a long-term candidate and must not be treated
  as compute scheduler design.
- Direct source copy requires source URL, commit, license, NOTICE/dependency
  review, copied paths, purpose, and a vendor manifest.

## Accepted Priority Order With Current Correction

The GPT package gives a useful high-level order, but the current human decision
narrows the first engineering focus:

```text
P0 Requirements/ADR closure for 24h worker + monitor + communication foundation
P1 24h worker + monitor reliability path
P2 Communication foundation and private node/base connectivity
P3 A9 core contracts that support P1/P2
P4 Reference/vendor baseline needed by P1/P2
P5 Mobile/control product packet, page details frozen for now
P6 Compute Stage A
P7 NZX Technical MVP
```

The original GPT order is retained as architectural background:

```text
P0 Architecture Decision Packet
P1 Reference Baseline Scan + Vendor Manifest
P2 A9 Core Contract
P3 Gateway / Bus refactor
P4 AgentOS Runtime
P5 Mobile / Remote Control Packet
P6 Compute Stage A
P7 NZX Technical MVP
```

The corrected priority above is now the default route unless a newer human
decision overrides it.

## Needs Human/Monitor Review Before Implementation

- Whether `Codex`, `Aider`, `barter-rs`, `planning-with-files`, and `aichat`
  should become direct-vendor slices or only mechanism-copy references.
- Whether current `crates/a9-gateway` should be renamed to `a9-bus` or
  `a9-redis-control-prototype`.
- Whether to migrate Python scripts into `scripts/legacy/` now or after the
  first ADR set.
- Whether `OpenClaw/Lobster` can be direct vendor after license and module
  boundary review.
- Whether LangGraph/mem0 should be sidecar dependencies or reimplemented as
  minimal contracts.

## Next Execution Candidate

First bounded worker task should be narrowed to:

```yaml
task_id: execution_next_0001_runtime_monitor_foundation_packet
route: execution_next
goal: convert the external GPT review, A9 aggregation draft, and current
  human correction into a decision packet for 24h worker, monitor, and
  communication foundation
scope:
  - create docs/architecture/a9-agentos-financial-foundation.md
  - create docs/architecture/a9-runtime-monitor-foundation.md
  - create docs/decisions/ADR-0001-a9-highest-form.md
  - create docs/decisions/ADR-0002-runtime-monitor-priority.md
  - create docs/decisions/ADR-0003-communication-foundation.md
  - create docs/decisions/ADR-0004-reference-vendor-selection.md
  - create docs/decisions/ADR-0005-nzx-is-first-business-app.md
out_of_scope:
  - no production trading code
  - no broker API
  - no smart contract deployment
  - no mobile UI implementation
  - no source vendor copy
  - no broad workspace crate migration
acceptance:
  - A9 vs NZX layer boundary is explicit
  - 24h worker + monitor guarantees are explicit
  - monitor visibility and intervention model is explicit
  - communication foundation boundary is explicit
  - direct-copy vs mechanism-copy table exists for runtime/communication needs
  - current code keep/rewrite/archive table exists
  - first five execution_next tasks are listed
  - every direct-copy candidate is marked pending license/vendor manifest
```

## Guardrail For 24h Worker

The worker must not start mobile UI changes, NZX implementation, compute RWA,
or broad crate migration from this review alone. It must first produce the
runtime/monitor/communication decision packet, then wait for monitor/human
review or an explicit next task contract.
