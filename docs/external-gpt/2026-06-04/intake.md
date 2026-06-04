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

## Accepted Priority Order

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

This priority is now the default route unless a newer human decision overrides
it.

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

First bounded worker task should be:

```yaml
task_id: execution_next_0001_architecture_packet
route: execution_next
goal: convert the external GPT review and A9 aggregation draft into ADRs and
  a first execution task list
scope:
  - create docs/architecture/a9-agentos-financial-foundation.md
  - create docs/decisions/ADR-0001-a9-highest-form.md
  - create docs/decisions/ADR-0002-reference-vendor-selection.md
  - create docs/decisions/ADR-0003-nzx-is-first-business-app.md
  - create docs/decisions/ADR-0004-ai-not-in-trading-hot-path.md
  - create docs/decisions/ADR-0005-redis-not-trading-ledger.md
  - create docs/decisions/ADR-0006-compute-layer-roadmap.md
out_of_scope:
  - no production trading code
  - no broker API
  - no smart contract deployment
  - no mobile UI implementation
  - no source vendor copy
acceptance:
  - A9 vs NZX layer boundary is explicit
  - direct-copy vs mechanism-copy table exists
  - current code keep/rewrite/archive table exists
  - first five execution_next tasks are listed
  - every direct-copy candidate is marked pending license/vendor manifest
```

## Guardrail For 24h Worker

The worker must not start P2/P3/P4 implementation from this review alone. It
must first produce the P0 decision packet, then wait for monitor/human review or
an explicit next task contract.

