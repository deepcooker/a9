# A9 Reference And Copy Policy

A9 copies mature open-source mechanisms first, then adapts them locally with
tests and evidence.

## Copy Rules

1. Verify license before copying source.
2. Record project, commit, path, license, destination and purpose.
3. Preserve required notices.
4. Prefer mechanism copy before source copy.
5. Do not copy non-open-source product references.

## Use-Through Rule

Reference projects are not architecture decisions by themselves. A9 must not
adopt a mechanism just because its README, demo or public reputation looks
strong.

Correct order:

```text
download locally
-> run or inspect enough to understand the real behavior
-> use it against an A9-shaped task
-> identify duplicate/overlapping mechanisms
-> write the failure modes and tradeoffs
-> build a small local spike/eval
-> decide whether to join A9, stay as reference, or be rejected
```

This is intentionally slower up front. Architecture quality matters more than
early feature velocity. A mechanism that has not been locally tried, compared
and evaluated is only a candidate, not part of the A9 architecture.
One day spent using the right reference deeply can save hundreds or thousands
of later correction loops.

Selection standards:

- Keep the best mechanism per layer; do not merge duplicate ideas just because
  multiple projects implement them.
- Prefer projects that have runnable behavior, tests, clear boundaries and
  recoverable failure modes.
- If a copied mechanism only works after A9-specific patches, the patch and the
  reason must be recorded.
- A reference can be downgraded or removed after local trial.
- Passing a small spike does not make it production; it only allows bounded
  integration behind tests/evidence.

## Rust And Gateway Baseline

A9 is not a Python-only automation script. Python remains useful for model,
business and personalization logic, but the stable control/runtime skeleton
must be selected and tested around Rust-first gateway and interaction behavior.

Required use-through baselines:

- Codex is the primary interaction/runtime reference. A9 must deeply test its
  CLI loop, tool protocol, context/compact/resume behavior, apply discipline,
  sandbox/approval model and long-running goal/session handling before claiming
  equivalent interaction quality.
- Barter-rs is the trading-grade gateway reference. A9 must deeply test its
  reconnect/backoff/error-action/stream handling patterns before designing
  private-node, worker-transport or market-facing gateway behavior.
- OpenClaw/Lobster remains the managed-flow/tool-envelope reference, but it
  does not replace Codex for interaction quality or Barter-rs for low-latency
  gateway reliability.

The intended architecture is layered, not either/or:

```text
Rust gateway/control hot path
-> Redis/MySQL state and evidence plane
-> Codex-like interaction/runtime
-> Python model/business logic where it has leverage
-> mobile/control and higher product surfaces
```

Any communication/runtime choice must be evaluated for latency, reconnect,
idempotency, observability, recoverability and bounded context behavior. UI
convenience is not allowed to define the runtime architecture.

## Priority References

- MemPalace: verbatim-first raw storage, per-message drawer, palace hierarchy,
  semantic + hybrid retrieval, wakeup/bootstrap packs, temporal KG,
  precompact/save hooks, provider/backend abstraction and rebuildable indexes.
- Codex: loop, tools, sandbox, approval, context and compaction.
- OpenClaw/Lobster: managed flow, approval/wait/resume, policy attestation,
  plugin/extension shape, memory governance and tool envelope.
- Barter-rs: reconnect, backoff, error action and trading-grade gateway
  reliability.
- Aider: repo map, token budgeting, diff/edit discipline and architect/editor
  split.
- Headroom: context-efficiency control plane, CCR, live-zone compression,
  content routing, cache-stability observability, Codex/OpenClaw wrapping and
  proxy metrics.
- LangGraph: checkpoint, parent lineage and channel history.
- mem0: memory add/search/get/history semantics.
- OpenHands, Continue, Cline, Roo, SWE-agent, opencode, aichat: terminal UX,
  provider abstraction, tool boundary and execution harness.

Claude Code and Antigravity are product references only unless an open-source
repo/license is verified.

## Active Copied Mechanisms

Keep this section small. New direct source copies must update
`vendor-src/MANIFEST.jsonl`.

MemPalace is the default mechanism reference for A9 session/memory/context
governance, but recall must not be treated as truth. Any recalled item entering
worker, monitor or operator context must keep source path, line/message id,
hash, role and timestamp.

Current local integration uses `reference-projects/mempalace` as the mechanism
source and `scripts/a9_mempalace_provider.py` as an A9 facade. Native MemPalace
collection access is enabled only when its Python dependencies are present;
otherwise A9 uses the source-preserving drawer JSONL fallback.

## Current Decision Matrix

This is the bounded evidence matrix for A9 session/memory governance and 24h
execution quality. It exists to prevent local invention from replacing
reference-first copying.

| Reference | Local evidence | Mechanism to copy | A9 status | Current gap / next cut |
| --- | --- | --- | --- | --- |
| Codex | `reference-projects/codex/codex-rs/code-mode/src/service.rs`, `reference-projects/codex/codex-rs/apply-patch/src/parser.rs` | Session registry, resume-to-pending, sandbox/approval config, deterministic patch grammar and context matching. | A9 has supervisor queue, worktrees, strict envelope, deterministic apply and patch/scope/git governance. | Worker prompts still allow broad command habits. Next cut: task packets must include exact read-command discipline, not just allowed_paths. |
| MemPalace | `reference-projects/mempalace/README.md`, `reference-projects/mempalace/CHANGELOG.md`, `reference-projects/mempalace/examples/cursor/README.md` | Verbatim drawers, source metadata, hybrid retrieval, wakeup packs, preCompact/sessionStart hooks, temporal KG and idempotent resumable mining. | A9 uses MemPalace-first drawer/evidence/index, native recall where available, fallback drawer JSONL, causal candidate compiler and review-only eval candidates. | Recall is still not final truth. Next cut: compile drawer evidence into time-valid facts, stale invalidations and role packets with explicit evidence refs before worker execution. |
| planning-with-files | `reference-projects/planning-with-files/templates/task_plan.md`, `reference-projects/planning-with-files/templates/loop.md`, `reference-projects/planning-with-files/README.md`, `reference-projects/planning-with-files/MIGRATION.md` | Filesystem working memory, progress/findings/task plan loop, hooks re-read before work, attestation and parallel plan isolation. | A9 has active plan, progress/findings/mistakes/change_request and managed backlog. | A9 must not add more planning docs. Next cut: make plan/backlog items stricter as contracts: exact files, exact commands, validated checks, and no broad aliases. |
| OpenClaw/Lobster | `reference-projects/openclaw/src/node-host/invoke.ts`, `reference-projects/openclaw/src/node-host/invoke-system-run-plan.ts`, `reference-projects/openclaw/src/context-engine/types.ts`, `reference-projects/openclaw/packages/sdk/src/types.ts` | Approval hash/reload safety, flow IDs, plugin command envelope, context engine overflow authority and approval events. | A9 has Redis managed-flow revision checks, approval/wait/resume, policy attestation and runtime monitor contract. | Quality-blocked tasks must update plan state and monitor/mobile must see them. This is now implemented for task-quality blocks; next cut is command-level task generation. |
| Aider | `reference-projects/aider/aider/repomap.py`, `reference-projects/aider/aider/coders/architect_prompts.py`, `reference-projects/aider/aider/coders/udiff_prompts.py` | Repo map instead of full repo reads, architect/editor split, explicit edit format and git-friendly diff discipline. | A9 has repo map, bounded context, deterministic apply and git governance. | Worker still broad-searches (`scripts`, `tests`) after task generation. Next cut: generated backlog must include exact rg/sed commands or anchors, not just a file list. |
| Headroom | `reference-projects/headroom/README.md`, `reference-projects/headroom/docs/content/docs/ccr.mdx`, `reference-projects/headroom/headroom/ccr/*`, `reference-projects/headroom/headroom/transforms/content_router.py`, `reference-projects/headroom/crates/headroom-core/src/ccr/mod.rs`, `reference-projects/headroom/crates/headroom-core/src/transforms/live_zone.rs`, `reference-projects/headroom/headroom/providers/codex/*`, `reference-projects/headroom/headroom/providers/openclaw/*` | Compress-Cache-Retrieve with source hash, retrieval tool injection, workspace-scoped context tracker, content-type router, live-zone byte-range surgery, cache volatility observation, proxy health/stats/metrics, Codex/OpenClaw wrapper config hygiene. | Source build passed in A9-isolated venv/toolchain; Python CCR/router/proxy/wrapper tests mostly pass; proxy smoke passed. Extra A9-shaped tests now cover cache stability, byte-faithful forwarding, system-prompt immutability, Codex WS lifecycle/timing, memory project isolation, learn analyzer/writer, compression failure action and streaming resilience. Real A9 replay showed good savings on a run prompt and summary, but zero savings and high latency on a 594 KB node-worker JSONL tail. This is still a use-through candidate, not a final architecture decision. | Primary strength appears to be context-gateway accident prevention and observability, not only token compression. It is not yet proven as a universal big-log reducer. Continue using it against real A9 worker/session logs before deciding what to copy. Do not put ML/ONNX Rust deps on A9 hot path yet. |

Headroom use-through correction:

- A9's earlier Headroom trial was too close to "call `compress()` and judge".
  That is not Headroom's strongest opening.
- The better opening is persistent gateway usage: `headroom proxy` or
  `headroom wrap codex/claude` with the `agent-90` profile, proxy metrics,
  CCR, cache-zone protection, retrieval hashes and provider-specific wrapper
  hygiene.
- A broader local matrix passed `2629` tests and failed `14`. The failures
  split into environment/setup classes: optional memory bridge tests defaulted
  to `sentence-transformers`, observability tests need OTEL/Langfuse extras,
  two Codex wrap tests assume Python 3.11 `tomllib`, one persistent wrapper
  test collided with A9's own port `8787`, and a direct env-path failure did
  not reproduce in isolation.
- Do not install Headroom's default `local` embedder casually. Its own config
  marks it as `sentence-transformers` / torch-heavy. A9 should use the official
  `onnx` embedder path for local memory trials unless a task explicitly asks
  for the heavy backend.
- A real ONNX memory-bridge smoke imported a small A9 memory file into
  Headroom LocalBackend with `embedder_backend="onnx"`, producing `4` memories.
  Cold init/import took about `21s`, but scoped semantic search returned in
  about `0.05s` and found the A9 mainline plus "data before performance/gates".
- Headroom's memory backend supports `user_id` and `session_id` scoping. A9
  should never query a global memory heap by default; operator session, worker
  session, project, role and run evidence must stay scoped and then be merged
  by an explicit context pack.
- The ONNX path emits an `onnxruntime` GPU discovery warning in this WSL
  environment because `/sys/class/drm/card0/device/vendor` is missing. It is
  not fatal for CPU execution, but deployment logs should suppress or classify
  it so monitors do not treat it as memory failure.
- Current Headroom conclusion: it is a serious context gateway/memory
  candidate, but A9 still needs its own event folding and causal-memory
  compiler. Raw A9 JSONL logs should be folded into meaningful events before
  Headroom-style compression/retrieval; otherwise token savings can be zero.

Latest commercial-readiness read:

- The commercial-grade reference point from the operator is roughly
  `200万-500万 token` and about `10MB/10兆` scale context processing. This is a
  sizing lens, not a hard gate. Do not misread it as `10min` throughput or as a
  fixed prompt-pack token budget.
- The intended A9/A3B scenario is: A9 can receive a large context/data payload
  from A9's own smaller model or upstream worker, hold that scale without
  losing evidence, then split it into high-quality batches, filter noise, fold
  repeated events, preserve source refs and feed refined context to A3B. The
  target is not merely shrinking one prompt; it is controlled large-context
  intake and staged cognition handoff.
- A9 should not choose Headroom as the raw large-context ingestion engine. Its
  local ONNX path is useful for pure embedding on small warmed batches, but full
  `save_memory` + SQLite/vector indexing is far slower in the current default
  path.
- Measured on A9 operator session slices: pure ONNX embedding reached about
  `236万`, `133万` and `81万` estimated-token rough throughput extrapolations
  in short synthetic slices. These are only probes, not proof that Headroom can
  handle the operator's large-context target end to end.
- Measured full local memory path: clean 30-message operator sample took about
  `6.8s` init and `57.3s` save/index, while each scoped recall query returned
  in about `0.05s`. The quality was good only after A9 filtered out tool-output
  noise and AGENTS/context injection. Without that filter, retrieval returned
  curl/help/tool-output noise.
- Therefore Headroom's A9 role is: context gateway, cache/live-zone protection,
  scoped recall, memory budget, CCR/retrieve tool protocol and observability.
  It optimizes the selected recall/context slice that enters a worker prompt,
  not the raw evidence lake. The final prompt budget must be task-dependent,
  not a fixed 200-500 token rule.
- A9 must keep the high-throughput layer itself: stream parse raw session and
  worker JSONL, fold repeated events, drop tool-output noise, deduplicate
  context injection, classify role/session/project/run, then asynchronously
  index only high-value memory packets into MemPalace/Headroom-style storage.
  Worker hot path should consume a bounded, task-shaped recall pack plus
  explicit evidence refs.

Decision:

- The earlier high-quality debate came from durable context plus human
  correction plus repeated requirements shaping; it was not enough as a
  production mechanism.
- A9 should keep the debate quality by turning it into reference-backed plan,
  evidence and memory contracts.
- The next code cut is not another gate. It is task-contract shaping:
  backlog-generation output must be narrow enough that the worker does not need
  broad discovery commands.

## Trial Queue

This queue is deliberately small and should be updated only when a reference
has been used locally, not when it is merely mentioned.

| Reference | Local state | Trial target | Current decision |
| --- | --- | --- | --- |
| MemPalace | Downloaded, native/fallback recall tested against real operator session, recall-quality eval added. | Commercial-grade memory: recall quality, causal compiler, role packets, wrongbook loop. | Adopted for memory layer, still not truth authority. Next: role packet eval and contradiction repair. |
| Codex | Downloaded, selected Rust service/apply-patch paths inspected. | Interaction loop, tool boundary, sandbox/approval, session resume, compact and long-running goal behavior. | Core interaction/runtime reference; needs deeper use-through before A9 claims Codex-like quality. |
| OpenClaw/Lobster | Downloaded, selected flow/context/tool envelope paths inspected. | Runtime managed flow, approval/resume, tool/plugin envelope, context overflow authority. | Candidate runtime/gateway reference; not fully adopted until local flow spike passes. |
| Barter-rs | Downloaded, README/license present, not yet gateway use-through tested in A9. | Rust gateway reconnect, backoff, stream error action, audit state and low-latency transport discipline. | Primary gateway reliability candidate; must run local communication/gateway spike before inclusion. |
| Aider | Downloaded, repo map and architect/editor prompts inspected. | Repo map, bounded edit discipline, architect/editor split. | Partially adopted; next proof is reducing worker broad reads through exact read commands. |
| planning-with-files | Downloaded, templates and hook flow inspected. | File-backed task memory and resume. | Mechanism reference only; A9 will not import its role model or add extra doc sprawl. |
| Hermes | Downloaded, not yet use-through tested. | Sidecar self-improvement, routines, wrongbook/eval feedback loop. | Candidate; must run a local spike before inclusion. |
| ECC | Downloaded, not yet use-through tested. | Multi-agent/tool ecosystem shape and cross-IDE agent conventions. | Candidate; must be compared against A9 role model before inclusion. |
| Headroom | Downloaded and source-run in A9 isolated environment. `headroom._core` build/import passed with Rust 1.95.0 under `.a9/rustup`; CCR tests passed `88/88`; content-router/decision/policy/cache-aligner/Codex/OpenClaw wrapper subset passed `225/227` with the two failures caused by Python 3.10 missing stdlib `tomllib`; proxy smoke passed `/livez`, `/readyz`, `/stats`, `/metrics`; proxy/cache/Codex-WS/memory/learn A9-shaped subset passed `226/226`; byte-faithful/system-prompt/failure-action/streaming/scalability/safety subset passed `134/134`; broader matrix passed `2629` and failed `14` mostly from optional/heavy deps, OTEL/Langfuse extras, Python 3.10 compatibility and A9 port `8787` collision; real A9 replay: run prompt `5688 -> 1649` tokens, run summary `1044 -> 491`, node-worker log tail `171653 -> 171653`; ONNX LocalBackend memory bridge smoke passed with `4` stored memories and `0.05s` scoped search; Rust `headroom-core` full test hit Ubuntu 22.04 glibc vs ONNX Runtime `__isoc23_*` link incompatibility. | Compression, token savings, Codex/Claude/OpenAI proxy behavior, model-aware context reduction, local memory bridge, scoped semantic retrieval and observability. | Not decided yet, but stronger than a plain compression library. Current hypothesis: Headroom's strongest value is context-gateway governance: keep unmutated bytes byte-faithful, protect system/cache hot zones, compress only safe live zones, preserve original evidence behind retrieval hashes, scope memory by workspace/session, surface metrics, and learn repeat failure patterns. Weakness seen so far: raw repetitive A9 JSONL logs need pre-aggregation/event folding before Headroom-style compression. Next use-through must replay real A9 worker/session payloads through proxy-shaped boundaries and ONNX memory before A9 copies or replaces any existing context path. |
| MiroFish | Downloaded, not yet use-through tested. | Multi-agent prediction/simulation ideas and parallel-world evaluation flow. | Candidate; must prove it improves A9 debate/review quality before inclusion. |
| Superpowers | Downloaded, not yet use-through tested. | Spec-first workflow, design confirmation, subagent execution discipline and agentic skills. | Candidate requirements/plan reference; must be run against an A9-shaped requirement before inclusion. |
| gstack | Downloaded, not yet use-through tested. | Skillized roles, plan reviews, QA/benchmark/retro discipline. | Candidate role-review reference; only mechanisms that improve A9's own method roles should be copied. |
