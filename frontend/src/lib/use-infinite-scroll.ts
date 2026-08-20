"use client"

import * as React from "react"

export const CARD_BATCH_SIZE = 50

/**
 * Creates a callback ref that loads more content when its element approaches the viewport.
 *
 * @param loadMore - Callback invoked when the observed element intersects the viewport.
 * @returns A callback ref for the element used as the infinite-scroll sentinel.
 */
export function useInfiniteScroll(loadMore: () => void) {
  const loadMoreRef = React.useRef(loadMore)
  React.useLayoutEffect(() => {
    loadMoreRef.current = loadMore
  }, [loadMore])

  return React.useCallback((node: HTMLDivElement | null) => {
    if (!node) {
      return undefined
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          loadMoreRef.current()
        }
      },
      { rootMargin: "200px 0px" },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
}
