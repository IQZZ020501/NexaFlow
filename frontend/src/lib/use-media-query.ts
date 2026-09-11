"use client"

import * as React from "react"

/**
 * Matches phones and everything narrower than Tailwind's `md` breakpoint.
 *
 * List surfaces render a card layout below `md` and their table layout at `md`
 * and above. Both representations carry the same copy, so rendering them
 * together would duplicate content for assistive technology and for DOM
 * queries; components select one with {@link useMediaQuery} instead.
 */
export const PHONE_LIST_QUERY = "(max-width: 767.98px)"

/**
 * Matches phones and everything narrower than Tailwind's `sm` breakpoint,
 * where the header navigation is replaced by the bottom tab bar.
 */
export const PHONE_NAV_QUERY = "(max-width: 639.98px)"

/**
 * Reports whether a CSS media query currently matches, and re-renders when it
 * changes.
 *
 * The server snapshot is `false`, so the wide representation is rendered
 * during server rendering and the client swaps to the compact one immediately
 * after hydration.
 *
 * @param query - A CSS media query string, for example `"(max-width: 767.98px)"`
 * @returns `true` while the query matches the current viewport
 */
export function useMediaQuery(query: string) {
  const subscribe = React.useCallback(
    (onStoreChange: () => void) => {
      const mediaQueryList = window.matchMedia(query)
      mediaQueryList.addEventListener("change", onStoreChange)
      return () => mediaQueryList.removeEventListener("change", onStoreChange)
    },
    [query]
  )

  return React.useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false
  )
}
