type ClosestCapableTarget = {
  closest: (selector: string) => unknown
}

/**
 * Determines whether a value provides a callable `closest` method.
 *
 * @param target - The value to inspect
 * @returns `true` if the value can be used as a closest-capable target, `false` otherwise
 */
function hasClosest(target: unknown): target is ClosestCapableTarget {
  return (
    target !== null &&
    typeof target === "object" &&
    "closest" in target &&
    typeof (target as { closest: unknown }).closest === "function"
  )
}

/**
 * Determines whether an event originated within dropdown-menu content.
 *
 * @param event - The event-like object whose target and composed path are checked
 * @returns `true` if the event target or a composed-path item is within dropdown-menu content, `false` otherwise
 */
export function isEventFromDropdownMenu(event: {
  target: unknown
  composedPath?: () => unknown[]
}) {
  const isDropdownMenuTarget = (target: unknown) =>
    hasClosest(target) &&
    Boolean(target.closest("[data-slot='dropdown-menu-content']"))

  if (isDropdownMenuTarget(event.target)) {
    return true
  }

  return event.composedPath?.().some(isDropdownMenuTarget) ?? false
}
