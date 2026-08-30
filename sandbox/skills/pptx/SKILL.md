---
name: pptx
description: Create new widescreen PPTX decks from structured audience-facing slide content.
entrypoint: scripts/render.py
artifact-format: pptx
---

# NexaFlow PPTX

Use this Skill for a new PowerPoint-compatible `.pptx` deliverable. The Tool
accepts structured slide content; the bundled renderer owns layout, styling,
speaker notes, and structural verification.

## Runtime contract

- The Agent supplies final audience-facing content, not Python source code.
- The renderer creates a minimal title slide plus section, bullets,
  two-column, icon, and table slides in 16:9 format.
- Choose one of the built-in templates or provide a contrasting brand palette.
- Put externally sourced claims in each slide's speaker notes under a
  `[Sources]` block.
- Keep the cover minimal, use takeaway-style slide titles, and keep body copy
  at readable sizes; the renderer rejects overlong slide titles.
- Overlong content is rejected instead of being silently shrunk below readable
  type sizes.

## Recommended flow

1. Establish the audience, purpose, and central takeaway before calling the
   Tool.
2. Give each slide one narrative job and use a takeaway-style title.
3. Keep the cover simple, vary adjacent layouts, and prefer a few useful points
   over dense text.
4. Call the Tool once with the final filename and structured presentation.

## Boundary

This Skill creates a new local PPTX with native shapes, tables, and built-in
icons. It does not fetch external images, edit an uploaded deck losslessly, or
publish to Google Slides. Structural checks do not claim pixel-level visual QA.
