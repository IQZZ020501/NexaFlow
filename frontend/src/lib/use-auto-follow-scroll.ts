"use client"

import * as React from "react"

export function isNearScrollBottom(
  element: Pick<HTMLElement, "clientHeight" | "scrollHeight" | "scrollTop">
) {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= 64
}

function scrollHost(element: HTMLElement, pageFallback: boolean) {
  if (!pageFallback) return element
  if (element.getClientRects().length === 0) return null
  return element.scrollHeight > element.clientHeight
    ? element
    : (element.ownerDocument.scrollingElement ?? element)
}

/** Follow new output until the reader scrolls up; resume at the bottom. */
export function useAutoFollowScroll({
  content,
  resetKey,
  enabled = true,
  pageFallback = false,
}: {
  content: unknown
  resetKey: string
  enabled?: boolean
  pageFallback?: boolean
}) {
  const scrollRef = React.useRef<HTMLDivElement>(null)
  const shouldFollowRef = React.useRef(true)
  const lastScrollTopRef = React.useRef(0)
  const resetKeyRef = React.useRef(resetKey)

  const followOutput = React.useCallback(() => {
    shouldFollowRef.current = true
    const container = scrollRef.current
    const host = container && scrollHost(container, pageFallback)
    if (host) {
      host.scrollTop = host.scrollHeight
      lastScrollTopRef.current = host.scrollTop
    }
  }, [pageFallback])

  React.useLayoutEffect(() => {
    if (resetKeyRef.current !== resetKey) {
      shouldFollowRef.current = true
      resetKeyRef.current = resetKey
    }
    const container = scrollRef.current
    const view = container?.ownerDocument.defaultView
    if (!enabled || !container || !view) return

    const onScroll = (event: Event) => {
      const host = scrollHost(container, pageFallback)
      if (!host || (host === container && event.target !== container)) return
      shouldFollowRef.current =
        host.scrollTop >= lastScrollTopRef.current && isNearScrollBottom(host)
      lastScrollTopRef.current = host.scrollTop
    }
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY < 0) shouldFollowRef.current = false
    }
    let touchY: number | undefined
    const onTouchStart = (event: TouchEvent) => {
      touchY = event.touches[0]?.clientY
    }
    const onTouchMove = (event: TouchEvent) => {
      const nextY = event.touches[0]?.clientY
      if (nextY !== undefined && touchY !== undefined && nextY > touchY) {
        shouldFollowRef.current = false
      }
      touchY = nextY
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (["ArrowUp", "PageUp", "Home"].includes(event.key)) {
        shouldFollowRef.current = false
      }
    }
    const followContent = () => {
      if (!shouldFollowRef.current) return
      const host = scrollHost(container, pageFallback)
      if (host) {
        host.scrollTop = host.scrollHeight
        lastScrollTopRef.current = host.scrollTop
      }
    }
    container.addEventListener("scroll", onScroll, { passive: true })
    container.addEventListener("wheel", onWheel, { passive: true })
    container.addEventListener("touchstart", onTouchStart, { passive: true })
    container.addEventListener("touchmove", onTouchMove, { passive: true })
    container.addEventListener("keydown", onKeyDown)
    if (pageFallback)
      view.addEventListener("scroll", onScroll, { passive: true })
    followContent()
    const frame = requestAnimationFrame(followContent)
    const observer = new ResizeObserver(followContent)
    observer.observe(container)
    for (const child of container.children) observer.observe(child)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
      container.removeEventListener("scroll", onScroll)
      container.removeEventListener("wheel", onWheel)
      container.removeEventListener("touchstart", onTouchStart)
      container.removeEventListener("touchmove", onTouchMove)
      container.removeEventListener("keydown", onKeyDown)
      if (pageFallback) view.removeEventListener("scroll", onScroll)
    }
  }, [content, resetKey, enabled, pageFallback])

  return { scrollRef, followOutput }
}
