# Login page design QA

- Source visual truth: `/Users/yang/personal/NexaFlow/frontend/public/NexaFlow-log.png`
- Desktop implementation: `/Users/yang/.codex/visualizations/2026/09/23/01a0cd8e-4c84-7910-9974-e8e99cc4f76c/nexaflow-login-desktop.png`
- Mobile implementation: `/Users/yang/.codex/visualizations/2026/09/23/01a0cd8e-4c84-7910-9974-e8e99cc4f76c/nexaflow-login-mobile.png`
- Combined comparison: `/Users/yang/.codex/visualizations/2026/09/23/01a0cd8e-4c84-7910-9974-e8e99cc4f76c/nexaflow-login-comparison.png`
- State: unauthenticated, Simplified Chinese, light theme

## Capture normalization

- Source asset: 1536 × 1024 pixels.
- Desktop: 1440 × 1024 CSS pixels, 1440 × 1024 captured pixels, device pixel ratio 1.
- Mobile: 390 × 844 CSS pixels, 390 × 844 captured pixels, device pixel ratio 1.
- The source asset is not a full-page mock. The comparison therefore evaluates asset fidelity, crop, prominence, and its relationship to the existing login controls rather than expecting the page chrome to match the source image.

## Full-view comparison

- Desktop preserves the supplied artwork without distortion and crops only its outer whitespace. The mark, wordmark, vertical rule, and slogan remain visible at native-quality scale in a dedicated brand region.
- Mobile uses the same source asset with a tighter whitespace crop so the brand remains legible without pushing the login action below the viewport.
- The form keeps the existing Geist typography, neutral theme tokens, labels, recovery link, submit action, and enterprise-login region. The removed card treatment creates a clearer two-region hierarchy without introducing a competing visual language.
- The 1440 × 1024 and 390 × 844 captures have no horizontal or vertical overflow.

## Required fidelity surfaces

- Fonts and typography: existing Geist hierarchy is retained; the 24 px semibold page heading and 14 px supporting copy remain readable at both breakpoints.
- Spacing and layout rhythm: desktop uses a stable split layout with a centered 384 px form column; mobile keeps 24 px page gutters and preserves touch-target sizing.
- Colors and visual tokens: existing background, foreground, muted, border, input, ring, and primary tokens are used. No new palette was introduced.
- Image quality and asset fidelity: both layouts render the supplied PNG through `next/image`; there are no placeholders, CSS drawings, recreated marks, or stretched geometry.
- Copy and content: all existing localized login copy and behavior are preserved. The literal `SLOGAN TEXT` remains because it is embedded in the supplied source asset.

## Focused-region comparison

A separate focused crop was not needed: the combined board keeps the complete artwork and all form controls readable at the captured density. Targeted DOM tests additionally cover the image source, labels, recovery link, submit behavior, and enterprise-provider controls.

## Findings

- No actionable P0, P1, or P2 findings remain.
- P3 follow-up: confirm whether the embedded `SLOGAN TEXT` is final brand copy before release; changing it requires a revised source asset rather than a UI overlay.

## Comparison history

1. The first 390 × 844 render preserved the full image but made the actual mark and wordmark too small relative to the form (P2).
2. The mobile artwork was enlarged to 135% inside an overflow crop, with balanced negative vertical margins. The second capture shows a legible brand block while all login controls remain visible within the 844 px viewport.
3. The final desktop recapture confirmed that the mobile adjustment did not change the desktop brand crop or form proportions.

## Interaction and runtime checks

- Browser-rendered `/login` inspected at desktop and mobile viewports.
- The password-recovery link navigated to `/forgot-password` and browser back returned to `/login`.
- Browser console warnings/errors: none during the final desktop capture.
- Automated login and enterprise-provider behavior remains covered by the targeted DOM suites.

final result: passed
