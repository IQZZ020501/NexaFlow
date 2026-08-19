type ClosestCapableTarget = {
  closest: (selector: string) => unknown
}

function hasClosest(target: unknown): target is ClosestCapableTarget {
  return (
    target !== null &&
    typeof target === "object" &&
    "closest" in target &&
    typeof (target as { closest: unknown }).closest === "function"
  )
}

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
