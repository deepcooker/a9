# Third Party Notices

This project intentionally studies and adapts mechanisms from mature open-source
agent and memory projects.

## Mem0

- Project: `mem0ai/mem0`
- Local reference: `reference-projects/mem0`
- License: Apache-2.0
- A9 usage: API-shape and mechanism reference for memory add/search/get/history,
  scoped filters, metadata, evidence links, keyword/semantic/entity retrieval, and
  memory history.

If A9 vendors modified Mem0 source code later, the modified files must retain
Apache-2.0 notices and clearly mark local changes.

## Current Vendor Policy

See `docs/vendor-strategy.md`.

Copied source slices should be imported with:

```bash
scripts/a9_vendor.py import <project> <source-path> --purpose "<why>"
```
