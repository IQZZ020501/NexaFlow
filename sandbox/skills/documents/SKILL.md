---
name: documents
description: Create DOCX files from structured Markdown when a Word document is requested.
entrypoint: scripts/render.py
artifact-format: docx
---

# NexaFlow documents

Use this Skill for a Word-compatible `.docx` deliverable. The Tool accepts
Markdown content and an optional `style`; the bundled renderer owns DOCX
construction and structural verification.

## Runtime contract

- The Agent supplies final content, not Python source code.
- Use headings, paragraphs, lists, and pipe tables in the Markdown input.
- Omit `style` (or use `report`) for the existing report layout.
- Use `style: formal_legal` only for a formal legal-document layout. Its first
  H1 is a centered black title; later headings are restrained black section
  labels; body paragraphs use 12pt formal CJK serif/fangsong-like text, 1.4
  line spacing, and a two-character first-line indent. Headings and list lines
  stay in the unified body style with direct formatting instead of becoming
  Word Heading/List styles, and this mode has no page-number footer.
- In `formal_legal`, prefix each signature or date line with `> ` to right-align
  it. Put `---` on its own line to start the following instructions or
  attachment section on a new page.
- The renderer uses `Noto Sans CJK SC` for report documents and `Noto Serif CJK
  SC` for formal documents in Linux; macOS uses `PingFang SC` and `STFangsong`.
  `NEXAFLOW_CJK_FONT` overrides either choice.
- `formal_legal` rejects the specific contradictory combination
  “仲裁费用…由被申请人承担” plus “劳动仲裁不收费”. This is a narrow issue guard,
  not general legal-content validation.
- `scripts/render.py` writes exactly one DOCX to the platform output path.
- Pipe tables use fixed page-width geometry and wrap long cell text instead of
  expanding beyond the document margins.
- The renderer reopens the DOCX and rejects empty or structurally invalid output.

## Recommended flow

1. Choose this Skill when the requested result is DOCX.
2. Produce concise Markdown with a clear heading hierarchy; select
   `formal_legal` and its explicit markers only when that layout is requested.
3. Call the Skill Tool once with the final filename and content.

## Boundary

This Skill creates a new local DOCX from Markdown. It does not publish to Google
Drive, reuse an uploaded DOCX template, or preserve an uploaded Word binary's
OOXML, styles, or layout.
