# A9 Vendor Source

This directory contains selected open-source source slices copied from
`reference-projects/` for A9 modification.

Rules:

- Every import must be recorded in `MANIFEST.jsonl`.
- Keep upstream license files under `vendor-src/<project>/`.
- Mark modified files and update the manifest when A9 changes copied code.
- Do not copy from non-open-source product references.
- Do not copy OpenHands `enterprise/` without separate license review.

Use:

```bash
scripts/a9_vendor.py import <project> <source-path> --purpose "<why>"
```
