---
name: pptx
description: Create new widescreen PPTX decks from structured audience-facing slide content, with model-declared visual themes, entrance animations, and page transitions.
entrypoint: scripts/render.py
artifact-format: pptx
---

# NexaFlow PPTX

Use this Skill for a new PowerPoint-compatible `.pptx` deliverable. The Tool
accepts structured slide content; the bundled renderer owns layout, styling,
animation, speaker notes, and structural verification.

## Runtime contract

- The Agent supplies final audience-facing content, not Python source code.
- The Agent creates a coherent visual identity through `presentation.theme`:
  palette, body and heading fonts, typography scale, panel treatment, cover
  accent, and title alignment. A slide may use `style` for a deliberate local
  variation. The renderer owns safe 16:9 geometry and rejects low contrast,
  unreadable sizes, overflow, and clipping. Built-in templates remain fallback
  defaults when the Agent omits a theme. For teaching or training decks, turn
  the lesson into a short visual narrative (normally 8–12 content slides):
  show the motivating problem, the worked example, the reasoning or process,
  practice, and the takeaway. Do not paste a lesson plan line-by-line.
- Supported layouts: `section` (transition), `bullets` (one claim with
  supporting points), `two_column` (direct comparison), `icons` (2-4 parallel
  concepts on panels), `table` (compact structured data), `hero` (bold
  full-slide statement), `stats` (2-4 key metrics), `steps` (2-5 step
  process), and `quote` (centered quotation with optional attribution).
  Vary adjacent layouts so slide silhouettes do not repeat. Do not use more
  than two consecutive `bullets` slides; use `steps` for procedures, `hero`
  or `two_column` for a worked example, and `table` only when rows add real
  comparison value.
- For arithmetic or other symbolic examples, keep the central expression in
  the slide copy; the renderer will surface simple multiplication expressions
  in a dedicated, editable visual region. Do not repeat the same expression in
  several unrelated bullets.
- Prefer a subject-appropriate `theme`; use a built-in template only as a
  fallback. Keep per-slide variations coherent with the deck-level identity.
- Chinese text defaults to the installed Song-style `Noto Serif CJK SC` on
  Linux and `Songti SC` on macOS; `NEXAFLOW_CJK_FONT` can override it.
- Put externally sourced claims in each slide's speaker notes under a
  `[Sources]` block.
- Keep the cover minimal, use takeaway-style slide titles, and keep body copy
  at readable sizes; slide titles use a 35pt baseline. Four-item icon and
  three/four-item stats slides automatically use a wider 2x2 grid, and text
  fits down only to each layout's readable size floor before being rejected.
  For math,
  science, or process content, put the central expression, sequence, or
  comparison in a dedicated visual region instead of burying it in bullets.
- Every slide gets a click-triggered fade entrance (title first, then content)
  and a medium fade page transition. Content beyond the readable layout floor
  is still rejected rather than clipped or made illegibly small.

## Recommended flow

1. Establish the audience, purpose, and central takeaway before calling the
   Tool.
2. Give each slide one narrative job and a takeaway-style title.
3. Define one coherent theme for the audience and subject before choosing
   slide-level variations.
4. For a lesson or training deck, outline 8–12 content slides and remove
   repeated “analysis / objective / method” inventory slides unless they
   change the audience's decision or understanding.
5. Map content to the layout that fits it best: `steps` for ordered actions,
   `hero`/`two_column` for a worked example, `icons` for a small set of
   parallel ideas, and `bullets` only for concise support.
6. Keep the cover simple, keep one primary visual idea per slide, and prefer a
   few useful points over dense text.
7. Call the Tool once with the final filename and structured presentation.

## Boundary

This Skill creates a new local PPTX with native shapes, tables, built-in
icons, entrance animations, and transitions. It does not fetch external
images, edit an uploaded deck losslessly, or publish to Google Slides.
Structural checks verify slide count, canvas bounds, animation targets, and
speaker notes. Text-fit and text-box-overlap checks run before delivery;
raster-level review still belongs to the deployment/CI QA job when a
LibreOffice renderer is available.
