# Memory Graph And Wiki Reference Scan

This document exists to avoid over-promoting `planning-with-files`.

`planning-with-files` is useful for task working memory and interruption
recovery. It is not enough for A9's long-term causal memory, requirements
method, or institutional knowledge layer.

## References Scanned

### GBrain

Local evidence:

- `reference-projects/gbrain`
- local commit: `eefe8b5`
- license: MIT
- `reference-projects/gbrain/README.md`
- `reference-projects/gbrain/docs/GBRAIN_RECOMMENDED_SCHEMA.md`
- `reference-projects/gbrain/docs/GBRAIN_SKILLPACK.md`

Mechanisms worth copying:

- Brain layer answers with synthesis, citations, and explicit gap analysis.
- Every claim should point back to a source page.
- Self-wiring knowledge graph extracts entity refs and typed edges on every
  page write, without requiring an LLM call for every edge.
- Hybrid retrieval combines vector, keyword, rank fusion, source boosts,
  reranking, and graph signals.
- Schema packs define what page types exist, how they link, and what facts are
  extractable.
- Human/agent review promotes schema candidates rather than silently changing
  the world model.
- Daily/cron dream cycle enriches, deduplicates, fixes citations, finds
  contradictions, and prepares future work.
- Per-user/team scope prevents memory leakage.
- Durable job queue supports crash-safe two-phase persistence and audit.
- Skills are markdown and routed by a resolver.

A9 interpretation:

- A9 needs a brain layer above plan files.
- Memory answers must include citations and "what we do not know yet".
- Causal memory should become claim/source/evidence/status records, not only
  prose summaries.
- The requirements guide maps naturally to schema packs: task, requirement,
  decision, risk, data object, state event, exception, test, run, mistake.
- Nightly sidecars should dedupe, find contradiction/drift, and propose memory
  commits.

### Microsoft GraphRAG

Local evidence:

- `reference-projects/graphrag`
- local commit: `6d02c23`
- license: MIT
- `reference-projects/graphrag/README.md`
- `reference-projects/graphrag/RAI_TRANSPARENCY.md`

Mechanisms worth copying:

- Pipeline transforms unstructured text into structured graph data.
- Graph memory helps LLMs reason about private narrative data.
- Prompt tuning and responsible-use documentation are explicit parts of the
  system.
- Indexing can be expensive; start small and understand costs.

A9 interpretation:

- A9 should not blindly graph everything.
- Graph indexing belongs to batch/sidecar lanes, not the hot worker path.
- Graph build cost must be observable.
- Graph output is a derived view over raw evidence, not the canonical truth.

### Graphify

Local evidence:

- `reference-projects/graphify`
- local commit: `4b17f19`
- license: MIT
- `reference-projects/graphify/README.md`

Mechanisms worth copying:

- Project files become `graph.html`, `GRAPH_REPORT.md`, and `graph.json`.
- The graph covers code, docs, PDFs, images, video/audio, SQL, and MCP config.
- Query-first guidance tells agents to ask the graph before grepping broad raw
  files.
- Extracted relationships carry confidence tags such as extracted, inferred,
  and ambiguous.
- Reports include key concepts, surprising connections, suggested questions,
  and rationale nodes.

A9 interpretation:

- A9 can use graphify-style outputs for repo/reference orientation.
- The best first use is reference/project map generation, not runtime memory.
- Confidence tags are important: extracted facts and inferred links must not be
  treated the same.
- `GRAPH_REPORT.md` is useful as an index, but `graph.json` plus source files
  remain the evidence base.

### LLM-Wiki

Local evidence:

- `reference-projects/llm-wiki`
- local commit: `7e9bd0a`
- license: MIT
- `reference-projects/llm-wiki/README.md`
- `reference-projects/llm-wiki/AGENTS.md`

Mechanisms worth copying:

- LLM-compiled knowledge bases for agents.
- Parallel multi-agent research, collector catalogs, source ingestion, wiki
  compilation, truth-seeking audits, querying, and artifact generation.
- Obsidian-compatible wiki output.
- Codex plugin entry via `@wiki`.
- Runtime packaging keeps behavior logic shared and wrapper-specific metadata
  thin.
- Topic archive lifecycle keeps old topics preserved but out of normal context.
- Lint repair resolves fuzzy raw source refs, stale indexes, and coverage gaps.
- Portable hub resolution avoids machine-specific path breakage.
- Query resume can answer where work left off.

A9 interpretation:

- A9 needs wiki-style durable topic spaces for long-running research and
  reference digestion.
- `session close-reading`, `reference scan`, and `run review` can each compile
  into wiki topics.
- Archives are important: old product branches should be preserved but not
  injected by default.
- Lint/repair over wiki memory is a better long-term control than hoping every
  prompt remembers every doctrine.

## A9 Layering

The references support this separation:

```text
requirements method
  -> task shaping / plan directory
  -> worker execution
  -> run evidence
  -> wiki/brain compilation
  -> graph/search retrieval
  -> sidecar audit / contradiction / drift report
  -> next task shaping
```

`planning-with-files` belongs mostly to task shaping and current execution.

GBrain / GraphRAG / Graphify / LLM-Wiki belong mostly to durable memory,
reference digestion, graph retrieval, contradiction detection, and later
training/eval data.

## Recovery Requirement

After interruption, compaction, session switch, or worker resume, the agent must
first restate the current task before acting.

The restatement must include:

- current goal
- current plan id or evidence source
- current phase
- what changed since the last action
- next intended action
- why that action serves the goal
- what is explicitly out of scope

If it cannot answer these, it must read the plan/progress/causal memory before
editing files or dispatching worker tasks.

This is stricter than `planning-with-files`' 5-question reboot test because A9
also needs causal change and business-mainline alignment.

## Provisional Decision

Do not replace the requirements-analysis method with any memory tool.

Use:

- requirements guide as method
- plan files as current-task working memory
- wiki/brain as durable compiled knowledge
- graph as retrieval/index over evidence
- raw sessions/runs/git/tests as canonical fact source

Next implementation should still be a minimal `.a9/plans/<plan-id>/` lane, but
the design should reserve fields for later wiki/graph compilation:

- `evidence_refs`
- `memory_commit_refs`
- `wiki_topic`
- `graph_index_refs`
- `recovery_restatement`
- `known_gaps`
- `contradictions`
