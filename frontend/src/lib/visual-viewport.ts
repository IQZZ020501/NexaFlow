import * as React from "react"

export type VisualViewportMetrics = {
  height: number
  offsetTop: number
}

export function readVisualViewportMetrics(): VisualViewportMetrics | null {
  const viewport = window.visualViewport
  if (!viewport) return null
  const height = Math.round(viewport.height)
  const offsetTop = Math.round(viewport.offsetTop)
  if (!Number.isFinite(height) || height <= 0) return null
  return {
    height,
    offsetTop: Number.isFinite(offsetTop) && offsetTop > 0 ? offsetTop : 0,
  }
}

/**
 * Pins a full-screen chat shell to the visual viewport.
 *
 * iOS Safari keeps the layout viewport tall when the keyboard opens and
 * instead shifts `visualViewport.offsetTop`. Sizing the shell by height
 * alone leaves the focused composer in the unscrolled document, so the
 * visible area becomes a blank page above the keyboard.
 */
export function visualViewportShellStyle(
  metrics: VisualViewportMetrics | null
):
  | {
      position: "fixed"
      top: number
      left: number
      right: number
      width: "100%"
      height: number
      maxHeight: number
    }
  | undefined {
  if (!metrics) return undefined
  return {
    position: "fixed",
    top: metrics.offsetTop,
    left: 0,
    right: 0,
    width: "100%",
    height: metrics.height,
    maxHeight: metrics.height,
  }
}

export function useVisualViewportShellStyle() {
  const [metrics, setMetrics] = React.useState<VisualViewportMetrics | null>(
    readVisualViewportMetrics
  )

  React.useEffect(() => {
    const viewport = window.visualViewport
    if (!viewport) return

    const html = document.documentElement
    const body = document.body
    const previousHtmlOverflow = html.style.overflow
    const previousBodyOverflow = body.style.overflow
    html.style.overflow = "hidden"
    body.style.overflow = "hidden"

    const sync = () => {
      const next = readVisualViewportMetrics()
      setMetrics((current) =>
        current &&
        next &&
        current.height === next.height &&
        current.offsetTop === next.offsetTop
          ? current
          : next
      )
    }
    sync()
    viewport.addEventListener("resize", sync)
    viewport.addEventListener("scroll", sync)
    return () => {
      html.style.overflow = previousHtmlOverflow
      body.style.overflow = previousBodyOverflow
      viewport.removeEventListener("resize", sync)
      viewport.removeEventListener("scroll", sync)
    }
  }, [])

  return visualViewportShellStyle(metrics)
}
