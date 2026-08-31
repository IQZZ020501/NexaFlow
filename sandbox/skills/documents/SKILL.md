---
name: documents
description: Create DOCX files from structured Markdown when a Word document is requested.
entrypoint: scripts/render.py
artifact-format: docx
---

# NexaFlow documents

Use this Skill for a Word-compatible `.docx` deliverable. The Tool accepts
Markdown content; the bundled renderer owns DOCX construction and structural
verification.

## Runtime contract

- The Agent supplies final content, not Python source code.
- Use headings, paragraphs, lists, and pipe tables in the Markdown input.
- The renderer uses a platform CJK family (`Noto Sans CJK SC` in the Linux
  image, `PingFang SC` on macOS) with `NEXAFLOW_CJK_FONT` as an override; it
  does not force the unavailable `Microsoft YaHei` family.
- `scripts/render.py` writes exactly one DOCX to the platform output path.
- Pipe tables use fixed page-width geometry and wrap long cell text instead of
  expanding beyond the document margins.
- The renderer reopens the DOCX and rejects empty or structurally invalid output.

## Recommended flow

1. Choose this Skill when the requested result is DOCX.
2. Produce concise Markdown with a clear heading hierarchy.
3. Call the Skill Tool once with the final filename and content.

## Boundary

This Skill creates a local DOCX handoff. It does not publish to Google Drive or
perform lossless editing of an uploaded Word binary.
