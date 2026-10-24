"use client"

import * as React from "react"
import { useLanguage } from "@/contexts/language-provider"

/** Shared split-pane sizing for console and public conversations. */
export function ArtifactPreviewPane({
  id,
  label,
  onClose,
  children,
}: {
  id: string
  label: string
  onClose: () => void
  children: React.ReactNode
}) {
  const { t } = useLanguage()
  const panelRef = React.useRef<HTMLElement>(null)
  const [preferredWidth, setPreferredWidth] = React.useState(60)
  const [containerWidth, setContainerWidth] = React.useState(0)
  const [activePointer, setActivePointer] = React.useState<number | null>(null)
  // Keep each pane at least 320px wide when space permits; adapt on small layouts.
  const minimum = containerWidth
    ? Math.min((320 / containerWidth) * 100, 40)
    : 20
  const maximum = 100 - minimum
  const width = Math.max(minimum, Math.min(maximum, preferredWidth))

  React.useEffect(() => {
    const container = panelRef.current?.parentElement
    if (!container) return
    const measure = () =>
      setContainerWidth(container.getBoundingClientRect().width)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(container)
    return () => observer.disconnect()
  }, [])

  function resize(event: React.PointerEvent<HTMLDivElement>) {
    if (event.pointerId !== activePointer) return
    const bounds = panelRef.current?.parentElement?.getBoundingClientRect()
    if (!bounds?.width) return
    const min = Math.min((320 / bounds.width) * 100, 40)
    setPreferredWidth(
      Math.max(
        min,
        Math.min(
          100 - min,
          ((bounds.right - event.clientX) / bounds.width) * 100
        )
      )
    )
  }

  function endResize(event: React.PointerEvent<HTMLDivElement>) {
    if (event.pointerId !== activePointer) return
    setActivePointer(null)
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId)
  }

  return (
    <>
      <div
        role="separator"
        aria-label={t("调整文件预览宽度")}
        aria-orientation="vertical"
        aria-controls={id}
        aria-valuemin={Math.round(minimum)}
        aria-valuemax={Math.round(maximum)}
        aria-valuenow={Math.round(width)}
        tabIndex={0}
        data-resizing={activePointer !== null}
        className="group relative z-20 hidden w-0 shrink-0 cursor-col-resize touch-none outline-none select-none before:absolute before:inset-y-0 before:-left-1.5 before:w-3 hover:before:bg-primary/10 focus-visible:before:bg-ring/20 data-[resizing=true]:before:bg-primary/10 md:block"
        onPointerDown={(event) => {
          if (event.button !== 0 || activePointer !== null) return
          event.preventDefault()
          event.currentTarget.focus({ preventScroll: true })
          event.currentTarget.setPointerCapture(event.pointerId)
          setActivePointer(event.pointerId)
        }}
        onPointerMove={resize}
        onPointerUp={endResize}
        onPointerCancel={endResize}
        onLostPointerCapture={endResize}
        onKeyDown={(event) => {
          const next = {
            ArrowLeft: width + 5,
            ArrowRight: width - 5,
            Home: minimum,
            End: maximum,
          }[event.key]
          if (next !== undefined) {
            event.preventDefault()
            setPreferredWidth(Math.max(minimum, Math.min(maximum, next)))
          } else if (event.key === "Escape") {
            event.preventDefault()
            onClose()
          }
        }}
      >
        <span className="pointer-events-none absolute top-1/2 left-0 h-8 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-muted-foreground opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 group-data-[resizing=true]:opacity-100" />
      </div>
      <aside
        ref={panelRef}
        id={id}
        aria-label={label}
        style={
          { "--artifact-preview-width": `${width}%` } as React.CSSProperties
        }
        className="pb-safe flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden border-l bg-background md:w-[var(--artifact-preview-width)] md:flex-none"
        onKeyDown={(event) => {
          if (event.key === "Escape" && !event.defaultPrevented) {
            event.preventDefault()
            onClose()
          }
        }}
      >
        {children}
      </aside>
      {activePointer !== null ? (
        // Keep the cursor and pointer stream in the host while crossing an iframe.
        <div
          aria-hidden="true"
          className="fixed inset-0 z-50 cursor-col-resize select-none"
        />
      ) : null}
    </>
  )
}
