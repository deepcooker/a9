# A9 Vendor And Modification Strategy

## Position

A9's core method is to copy mature open-source mechanisms, then modify them for
our own 24-hour private agent service.

Open-source projects are not only references. If the license allows it, A9 may
copy source files or modules into an A9-controlled vendor area and modify them.

## Rules

1. Verify the license before copying code.
2. Record source project, source commit, source path, destination path, license,
   and purpose.
3. Preserve license notices and attribution required by the upstream license.
4. Mark modified files as modified by A9.
5. Keep copied code isolated until it has tests and clear ownership.
6. Do not copy code from non-open-source product references.
7. Treat mixed-license directories separately.

## Current Reference Policy

| Project | License | Copy policy |
| --- | --- | --- |
| Codex CLI | Apache-2.0 | Copy/adapt allowed with notice. Primary source for session, context, compaction, sandbox, event loop. |
| Aider | Apache-2.0 | Copy/adapt allowed with notice. Good for repo map, token budget mechanics, and SEARCH/REPLACE edit discipline. Aider is not the "Lobster/OpenClaw" reference. |
| OpenClaw / Lobster | MIT for `reference-projects/openclaw`; Apache-2.0 for the local `mem0/openclaw` plugin slice. | Copy/adapt allowed with the matching notice. Primary source for A9 24-hour runtime/gateway, managed flows, approval/resume, extension/plugin shape, policy attestation, skills, memory-core, memory-wiki, agent-friendly CLI JSON, and per-agent isolation. Historical reassessment is archived at `docs/archive/active-indexes/2026-06-15/reference-selection-reassessment.md`. |
| mem0 | Apache-2.0 | Copy/adapt allowed with notice. Good for memory API shape, extraction, hybrid retrieval, entity boost, history. |
| LangGraph | MIT | Copy/adapt allowed with notice. Good for checkpoint/channel lineage and state graph patterns. |
| OpenHands | MIT plus segmented enterprise license | Copy OSS areas only; avoid `enterprise/` unless separately reviewed. |
| Continue | Apache-2.0 | Copy/adapt allowed with notice. Good for IDE/session/edit outcome ideas. |
| SWE-agent | MIT | Copy/adapt allowed with notice. Good for issue-to-patch harness and eval loops. |
| Cline | Apache-2.0 | Copy/adapt allowed with notice. Good for tool UX, plan/act, approval patterns. |
| Roo Code | Apache-2.0 | Copy/adapt allowed with notice. Good for modes and tool orchestration. |
| Gemini CLI | Apache-2.0 | Copy/adapt allowed with notice. Good for terminal agent UX and providers. |
| opencode | MIT | Copy/adapt allowed with notice. Good for terminal agent and provider abstraction. |
| aichat | MIT OR Apache-2.0 | Copy/adapt allowed with notice. Good for Rust CLI/provider patterns. |
| Claude Code | Product reference only | Do not copy source unless an open-source repo/license is verified. |
| Antigravity | Product reference only | Do not copy source unless an open-source repo/license is verified. |

## Vendor Layout

Copied source goes under:

```text
vendor-src/<project>/<relative-source-path>
```

Each import creates or updates:

```text
vendor-src/MANIFEST.jsonl
```

The manifest is the audit trail for copied code.

## Copy Modes

- `mechanism`: only copy ideas into A9-native code.
- `source-slice`: copy selected files into `vendor-src/` for modification.
- `module-fork`: copy a coherent module/subpackage into `vendor-src/`.
- `dependency`: use package manager dependency and adapt with wrapper code.

Default mode is `mechanism`. Use `source-slice` when we need exact behavior and
the upstream license allows modification.
