"use client"

import * as React from "react"

export const CARD_BATCH_SIZE = 50

export function useInfiniteScroll(loadMore: () => void) {
  const loadMoreRef = React.useRef(loadMore)

  React.useEffect(() => {
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
