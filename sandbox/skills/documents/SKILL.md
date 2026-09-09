---
name: documents
description: Create DOCX files from structured Markdown when a Word document is requested.
entrypoint: scripts/render.py
artifact-format: docx
---

# NexaFlow documents

Use this Skill for a Word-compatible `.docx` deliverable. The Tool accepts
Markdown content, an optional `style`, and an optional base64-encoded reference
DOCX; the bundled renderer owns DOCX construction and layout verification.

## Runtime contract

- The Agent supplies final content, not Python source code.
- Use headings, paragraphs, lists, and pipe tables in the Markdown input.
- Omit `style` to let the renderer recognize an obvious legal-document title;
  use `report` to force the existing report layout or `formal_legal` to force a
  formal legal-document layout.
- Use `style: formal_legal` only for a formal legal-document layout. Its first
  H1 is a centered black title; later headings are restrained black section
  labels; body paragraphs use 12pt formal CJK serif/fangsong-like text, 1.4
  line spacing, and a two-character first-line indent. Headings and list lines
  stay in the unified body style with direct formatting instead of becoming
  Word Heading/List styles, and this mode has no page-number footer.
- In `formal_legal`, prefix each signature or date line with `> ` to right-align
  it. Put `---` on its own line to start the following instructions or
  attachment section on a new page.
- Set `reference_docx_base64` to a base64-encoded DOCX when a reference
  template is available. The renderer preserves its section page geometry,
  headers, footers, styles, and direct paragraph/run formatting, then replaces
  only the body content with the supplied Markdown. The reference is the
  formatting authority and takes precedence over the generic legal defaults.
- The renderer uses `Noto Serif CJK SC` for report and formal documents in
  Linux; macOS uses `Songti SC` for report and formal documents.
  `NEXAFLOW_CJK_FONT` overrides either choice.
- The renderer rejects contradictory arbitration-fee statements, including a
  request that the respondent bear arbitration fees together with a statement
  that labor arbitration is free. This is a narrow consistency guard, not legal
  advice or a substitute for review by a qualified professional.
- `scripts/render.py` writes exactly one DOCX to the platform output path.
- Pipe tables use fixed page-width geometry and wrap long cell text instead of
  expanding beyond the document margins.
- The renderer reopens the DOCX and rejects empty or structurally invalid output,
  including title, list-style, signature alignment, and explicit page-break
  drift in formal legal documents.

## Recommended flow

1. Choose this Skill when the requested result is DOCX.
2. Produce concise Markdown with a clear heading hierarchy; omit `style` for
   automatic legal-title recognition or select `formal_legal` explicitly, and
   use the `> ` and `---` markers where applicable.
3. Call the Skill Tool once with the final filename and content.

## Boundary

This Skill creates a new local DOCX from Markdown. A supplied reference DOCX is
used only as a formatting template; its body text is replaced and arbitrary
Word features that `python-docx` cannot represent are not guaranteed. It does
not publish to Google Drive or edit the reference file in place.
