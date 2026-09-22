---
name: pptx
description: Create new widescreen PPTX decks with the offline open-kimi-ppt PPTD renderer, named design systems, free-form editable elements, animations, and transitions.
entrypoint: scripts/render.py
artifact-format: pptx
---

# NexaFlow PPTX

Use this fixed Skill for a new PowerPoint-compatible `.pptx` deliverable. New
decks use the open-kimi-ppt PPTD composition model and its offline WASM
exporter. Existing layout-based payloads remain supported by the compatibility
renderer.

## Runtime contract

- Supply final audience-facing content, not Python, JavaScript, setup commands,
  or raw PPTD files. The fixed renderer creates the project internally.
- For a new deck, choose one `scenario` and one `design_system`, then compose
  every slide with `elements` on the 960x540 canvas. Include the cover as the
  first slide. Elements remain editable PowerPoint text, shapes, lines, or
  images.
- The available scenarios are analysis/decision, business plan, management
  report, academic research, education/training, technical engineering, and
  brand/creative. Structure the story for that job rather than copying a source
  document page-by-page.
- Thirty named visual systems cover consulting, finance, work, promotion, and
  academic contexts. Select one coherent system for the whole deck; override
  its palette or fonts only when a supplied brand requires it. The renderer
  supplies stable `$background`, `$surface`, `$primary`, `$accent`, `$text`,
  `$muted`, `$rule`, and `$white` color tokens plus `$title`, `$body`, and
  `$label` text styles.
- Use `background` plus layered `elements` to create deliberate visual
  hierarchy. Prefer one takeaway per slide, strong contrast, restrained copy,
  and varied compositions. Do not repeat the same grid on every page.
- Optional images arrive only through bounded `presentation.media` base64
  entries and are referenced as `media/<filename>`. Remote URLs, host paths,
  SVG, video, and network fetching are rejected.
- Speaker notes belong in each slide's `notes`; put traceable external sources
  under a `[Sources]` block.

## Animation

PPTD animations target an `elementId` on the same page. Supported effects are:

- entrance: `appear`, `fade-in`, `fly-in`, `zoom-in`, `wipe-in`, `float-in`,
  `peek-in`, `rise-in`;
- emphasis: `pulse`, `grow-shrink`, `spin`, `teeter`, `fill-color`,
  `transparency`, `color-pulse`;
- exit: `disappear`, `fade-out`, `fly-out`, `zoom-out`, `wipe-out`,
  `float-out`;
- path: `motion-path`.

Use `onClick` to begin a click group, `withPrevious` for simultaneous motion,
and `afterPrevious` for a sequence. Keep most pages to one to three groups and
prefer fade, fly, or zoom unless motion carries meaning. `fill-color` and
`color-pulse` require `color`; `transparency` requires `amount`; `motion-path`
requires a path beginning at `M 0 0`.

## Recommended flow

1. Establish audience, purpose, and the one decision or understanding the deck
   should create.
2. Choose the scenario and a design system that fits that audience.
3. Outline a short narrative with a minimal cover, progression, evidence or
   worked examples, and a clear close.
4. Compose each 960x540 page with a different but related silhouette. Use
   shapes and lines as information structure, not decoration.
5. Add animations only where they reveal sequence, comparison, causality, or
   emphasis.
6. Put citations in notes, include any local image bytes in `media`, and call
   the Tool once with the final filename and presentation.

## Compatibility and boundary

Legacy slides using `layout` (`section`, `bullets`, `two_column`, `icons`,
`table`, `hero`, `stats`, `steps`, or `quote`) continue to render through the
previous deterministic renderer. A deck cannot mix legacy layout slides and
PPTD element slides.

The Skill runs offline in OpenSandbox, produces one PPTX of at most 5 MiB, and
does not edit existing decks or publish to external services. Structural checks
verify slide count, page transitions, animation timing, media containment, and
the output ZIP. Browser-based editor and raster QA assets are intentionally not
part of the production execution image.
