import * as React from "react"
import { DropdownMenu as DropdownMenuPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

/**
 * Provides the root context for a dropdown menu.
 *
 * @param props - Properties forwarded to the Radix dropdown menu root.
 */
function DropdownMenu({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Root>) {
  return <DropdownMenuPrimitive.Root data-slot="dropdown-menu" {...props} />
}

/**
 * Renders a trigger for opening the dropdown menu.
 *
 * @returns The dropdown menu trigger element.
 */
function DropdownMenuTrigger({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Trigger>) {
  return (
    <DropdownMenuPrimitive.Trigger
      data-slot="dropdown-menu-trigger"
      {...props}
    />
  )
}

/**
 * Renders dropdown menu content in a portal with bounded wheel scrolling.
 *
 * @param onWheelCapture - Optional handler invoked before the built-in wheel scrolling behavior.
 * Preventing the event skips the built-in behavior.
 * @param sideOffset - Distance between the menu content and its trigger.
 */
function DropdownMenuContent({
  className,
  onWheelCapture,
  sideOffset = 4,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Content>) {
  return (
    <DropdownMenuPrimitive.Portal>
      <DropdownMenuPrimitive.Content
        data-slot="dropdown-menu-content"
        sideOffset={sideOffset}
        className={cn(
          "z-50 min-w-56 origin-(--radix-dropdown-menu-content-transform-origin) overflow-x-hidden rounded-lg border bg-popover p-1 text-popover-foreground shadow-md",
          className
        )}
        onWheelCapture={(event) => {
          onWheelCapture?.(event)
          if (event.defaultPrevented) {
            return
          }

          const content = event.currentTarget
          const maxScrollTop = content.scrollHeight - content.clientHeight
          if (maxScrollTop <= 0) {
            return
          }

          const nextScrollTop = Math.max(
            0,
            Math.min(maxScrollTop, content.scrollTop + event.deltaY)
          )
          if (nextScrollTop === content.scrollTop) {
            return
          }

          event.preventDefault()
          event.stopPropagation()
          content.scrollTop = nextScrollTop
        }}
        {...props}
      />
    </DropdownMenuPrimitive.Portal>
  )
}

/**
 * Groups related dropdown menu items.
 */
function DropdownMenuGroup({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Group>) {
  return (
    <DropdownMenuPrimitive.Group
      data-slot="dropdown-menu-group"
      {...props}
    />
  )
}

/**
 * Renders an item within a dropdown menu with optional inset layout and visual variant styling.
 *
 * @param inset - Whether to apply inset spacing for the item.
 * @param variant - The visual style of the item.
 */
function DropdownMenuItem({
  className,
  inset,
  variant = "default",
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Item> & {
  inset?: boolean
  variant?: "default" | "destructive"
}) {
  return (
    <DropdownMenuPrimitive.Item
      data-slot="dropdown-menu-item"
      data-inset={inset}
      data-variant={variant}
      className={cn(
        "relative flex cursor-default items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-hidden select-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[inset]:pl-8 data-[variant=destructive]:text-destructive data-[variant=destructive]:focus:bg-destructive/10 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 [&_svg:not([class*='text-'])]:text-muted-foreground",
        className
      )}
      {...props}
    />
  )
}

/**
 * Renders a styled label within a dropdown menu.
 *
 * @param inset - Whether to apply inset positioning to the label.
 */
function DropdownMenuLabel({
  className,
  inset,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Label> & {
  inset?: boolean
}) {
  return (
    <DropdownMenuPrimitive.Label
      data-slot="dropdown-menu-label"
      data-inset={inset}
      className={cn("px-2 py-1.5 text-sm font-medium data-[inset]:pl-8", className)}
      {...props}
    />
  )
}

/**
 * Renders a horizontal separator within a dropdown menu.
 */
function DropdownMenuSeparator({
  className,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Separator>) {
  return (
    <DropdownMenuPrimitive.Separator
      data-slot="dropdown-menu-separator"
      className={cn("-mx-1 my-1 h-px bg-border", className)}
      {...props}
    />
  )
}

export {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
}
