import * as React from "react"

import { isEventFromDropdownMenu } from "@/lib/dom"
import { cn } from "@/lib/utils"

/**
 * Grid layout shared by every resource listing (knowledge, apps, models, tools).
 */
export const resourceCardGridClass =
  "grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"

const SHELL_CLASS =
  "group flex h-full min-w-0 flex-col rounded-xl border bg-card p-3 shadow-xs transition-colors"

const INTERACTIVE_CLASS =
  "cursor-pointer outline-none hover:border-primary/50 hover:bg-muted/30 focus-visible:ring-2 focus-visible:ring-ring"

const SELECTED_CLASS = "border-primary/50 bg-primary/[0.035]"

const TONE_CLASS = {
  blue: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  violet: "bg-violet-500/10 text-violet-700 dark:text-violet-400",
  sky: "bg-sky-500/10 text-sky-700 dark:text-sky-400",
  muted: "bg-muted/70 text-muted-foreground",
} as const

/**
 * Builds the shared card shell used by every resource listing.
 *
 * Use it directly when the card cannot be rendered by `ResourceCard` (for
 * example a native `<button>`); otherwise prefer `ResourceCard`.
 *
 * @param options - Interaction state and extra classes for the card
 * @returns The card class list
 */
export function resourceCardClass(options?: {
  interactive?: boolean
  selected?: boolean
  className?: string
}) {
  return cn(
    SHELL_CLASS,
    options?.interactive && INTERACTIVE_CLASS,
    options?.selected && SELECTED_CLASS,
    options?.className
  )
}

type ResourceCardProps = Omit<React.ComponentProps<"div">, "onSelect"> & {
  /** Element to render; `article` keeps non-activatable cards semantically opaque. */
  as?: "div" | "article"
  /** Enables the hover/focus affordances and Enter/Space activation. */
  interactive?: boolean
  /** Highlights the card while it is part of a bulk selection. */
  selected?: boolean
  /** Sets `aria-pressed`; pass a value only while bulk selection is active. */
  pressed?: boolean
  /** Runs on click or Enter/Space; only used when `interactive`. */
  onActivate?: () => void
}

/**
 * Renders one resource card, including its click and keyboard activation.
 *
 * Clicks originating inside a dropdown menu are ignored so opening a card menu
 * never opens or selects the card itself.
 *
 * @param as - Element to render
 * @param interactive - Whether the card can be activated
 * @param selected - Whether the card is currently selected
 * @param pressed - Value for `aria-pressed`
 * @param onActivate - Activation handler
 * @param className - Additional CSS classes
 */
export function ResourceCard({
  as = "div",
  interactive = false,
  selected = false,
  pressed,
  onActivate,
  className,
  onClick,
  onKeyDown,
  children,
  ...props
}: ResourceCardProps) {
  const activatable = interactive && Boolean(onActivate)
  const Component = as as React.ElementType

  function handleClick(event: React.MouseEvent<HTMLDivElement>) {
    onClick?.(event)
    if (!activatable || event.defaultPrevented) return
    if (isEventFromDropdownMenu(event)) return
    onActivate?.()
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    onKeyDown?.(event)
    if (!activatable || event.defaultPrevented) return
    if (event.target !== event.currentTarget) return
    if (event.key !== "Enter" && event.key !== " ") return
    event.preventDefault()
    onActivate?.()
  }

  return (
    <Component
      data-slot="resource-card"
      role={activatable ? "button" : undefined}
      tabIndex={activatable ? 0 : undefined}
      aria-pressed={activatable ? pressed : undefined}
      className={resourceCardClass({
        interactive: activatable,
        selected,
        className,
      })}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      {...props}
    >
      {children}
    </Component>
  )
}

/**
 * Renders the tinted icon tile shown at the start of a resource card.
 *
 * @param tone - Accent used by the tile
 * @param className - Additional CSS classes
 */
export function ResourceCardIcon({
  tone = "muted",
  className,
  children,
}: {
  tone?: keyof typeof TONE_CLASS
  className?: string
  children: React.ReactNode
}) {
  return (
    <span
      className={cn(
        "flex size-9 shrink-0 items-center justify-center rounded-lg",
        TONE_CLASS[tone],
        className
      )}
    >
      {children}
    </span>
  )
}

/**
 * Renders the header row: identity on the start side, actions on the end side.
 *
 * @param className - Additional CSS classes
 */
export function ResourceCardHeader({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("flex items-start justify-between gap-3", className)}
      {...props}
    />
  )
}

/**
 * Renders the header row's action cluster (edit button, card menu, checkbox).
 *
 * @param className - Additional CSS classes
 */
export function ResourceCardActions({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("flex shrink-0 items-center gap-1", className)}
      {...props}
    />
  )
}

/**
 * Renders one muted metadata line, such as creator and update time.
 *
 * @param className - Additional CSS classes
 */
export function ResourceCardMeta({
  className,
  ...props
}: React.ComponentProps<"p">) {
  return (
    <p
      className={cn("mt-1 truncate text-xs text-muted-foreground", className)}
      {...props}
    />
  )
}

/**
 * Renders a resource card name.
 *
 * @param as - Heading level; pick the level matching the page outline
 * @param className - Additional CSS classes
 */
export function ResourceCardTitle({
  as: tag = "h2",
  className,
  ...props
}: React.ComponentProps<"h2"> & { as?: "h2" | "h3" }) {
  const Component = tag as React.ElementType

  return (
    <Component
      className={cn("truncate text-sm font-semibold", className)}
      {...props}
    />
  )
}

/**
 * Renders the bottom row: key figures on the start side, actions on the end side.
 *
 * @param className - Additional CSS classes
 */
export function ResourceCardFooter({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "mt-auto flex items-end justify-between gap-3 pt-3",
        className
      )}
      {...props}
    />
  )
}

/**
 * Renders the `dl` holding a card's figures; pair it with `Spec` entries.
 *
 * @param className - Additional CSS classes
 */
export function ResourceCardSpecs({
  className,
  ...props
}: React.ComponentProps<"dl">) {
  return (
    <dl
      className={cn(
        "grid min-w-0 flex-1 grid-cols-2 content-end gap-x-3 gap-y-2 text-sm",
        className
      )}
      {...props}
    />
  )
}
