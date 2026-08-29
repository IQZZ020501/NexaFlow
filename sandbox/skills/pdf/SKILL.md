---
name: pdf
description: Create paginated PDF files from Markdown content inside NexaFlow.
entrypoint: scripts/render.py
artifact-format: pdf
---

# NexaFlow PDF

Use this Skill when the requested deliverable is a new `.pdf`. The Tool accepts
Markdown content and the bundled renderer owns pagination and verification.

## Runtime contract

- The Agent supplies final content, not Python source code.
- Use headings, paragraphs, lists, and pipe tables in the Markdown input.
- `scripts/render.py` writes exactly one PDF to the platform output path.
- The renderer reopens the PDF and checks its page count and extracted text.

## Choose a tool

- Choose this Skill for PDF output and Documents for DOCX output.
- Keep the Markdown hierarchy concise enough to paginate cleanly.

## Quality and honesty

This renderer performs structural and extracted-text checks. It does not claim
pixel-level visual review or edit an uploaded PDF in place.
