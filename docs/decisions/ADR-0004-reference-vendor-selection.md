# ADR-0004: Reference Vendor Selection

> Status: partial_decision
> Date: 2026-06-04

## Decision

For the current runtime/monitor/communication phase, references are classified
by mechanism need, not by excitement or repository size.

| Reference | Current classification | Immediate use |
| --- | --- | --- |
| Codex | mechanism copy, vendor candidate pending manifest | event loop, compact/resume, tool execution |
| Aider | mechanism copy, vendor candidate pending manifest | deterministic edit/diff discipline |
| OpenClaw/Lobster | mechanism copy | managed flow, revision, policy, approval wait/resume |
| Barter-rs | mechanism copy, vendor candidate pending manifest | reconnect, typed stream errors, audit replica |
| planning-with-files | mechanism copy, vendor candidate pending manifest | file plan recovery and attestation |
| mem0 | API-shape copy | memory add/search/get/history |
| LangGraph | minimal contract copy | checkpoint lineage and channel history |
| Hermes | side path | trajectory/datagen/self-improvement later |
| ECC | side path for now | harness/context/skills after runtime stability |

## Source Copy Rule

No direct source copy is authorized by this ADR. Direct copy requires:

```text
source URL
commit
license
NOTICE/dependency review
copied paths
purpose
vendor manifest
tests
```

## Consequences

The next vendor task is a scan/manifest task, not a copy task.

