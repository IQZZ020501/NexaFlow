"use client"

import * as React from "react"
import { usePathname } from "next/navigation"

const START_ANIMATION_MS = 250
const HOLD_AT_90_MS = 120
const COMPLETE_ANIMATION_MS = 180

export function TopProgress() {
  const pathname = usePathname()
  const [visible, setVisible] = React.useState(false)
  const [progress, setProgress] = React.useState(0)
  const isFirstRender = React.useRef(true)

  React.useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false
      return
    }

    let raf = 0
    let holdTimer: ReturnType<typeof setTimeout> | undefined
    let completeTimer: ReturnType<typeof setTimeout> | undefined

    setProgress(0)
    setVisible(true)

    const start = performance.now()
    const tick = (now: number) => {
      const elapsed = now - start
      const t = Math.min(elapsed / START_ANIMATION_MS, 1)
      // easeOutCubic: fast start, slow finish
      const eased = 1 - Math.pow(1 - t, 3)
      setProgress(eased * 90)
      if (t < 1) {
        raf = requestAnimationFrame(tick)
      } else {
        holdTimer = setTimeout(() => {
          setProgress(100)
          completeTimer = setTimeout(() => {
            setVisible(false)
            setProgress(0)
          }, COMPLETE_ANIMATION_MS)
        }, HOLD_AT_90_MS)
      }
    }
    raf = requestAnimationFrame(tick)

    return () => {
      cancelAnimationFrame(raf)
      if (holdTimer) clearTimeout(holdTimer)
      if (completeTimer) clearTimeout(completeTimer)
    }
  }, [pathname])

  if (!visible) {
    return null
  }

  return (
    <div
      className="fixed inset-x-0 top-0 z-[60] h-0.5 overflow-hidden"
      aria-hidden="true"
    >
      <div
        className="h-full bg-primary transition-[width] duration-150 ease-out"
        style={{ width: `${progress}%` }}
      />
    </div>
  )
}
