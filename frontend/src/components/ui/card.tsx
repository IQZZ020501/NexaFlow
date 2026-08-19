import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Renders a styled container for grouping related content.
 *
 * @param className - Additional CSS classes to apply to the card
 */
function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card"
      className={cn(
        "flex flex-col gap-6 rounded-lg border bg-card py-6 text-card-foreground shadow-sm",
        className
      )}
      {...props}
    />
  )
}

/**
 * Renders the header section of a card.
 *
 * @param className - Additional CSS classes to apply to the header
 */
function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn("flex flex-col gap-1.5 px-6", className)}
      {...props}
    />
  )
}

/**
 * Renders a styled title section for a card.
 *
 * @param className - Additional classes to apply to the title
 * @param props - Additional properties for the title element
 */
function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-title"
      className={cn("text-base font-medium leading-none", className)}
      {...props}
    />
  )
}

/**
 * Renders descriptive text within a card.
 *
 * @param className - Additional classes to apply to the description
 * @param props - Standard properties for the underlying `div` element
 */
function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

/**
 * Renders the main content section of a card.
 *
 * @param className - Additional CSS classes for the content section
 * @returns The card content section
 */
function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-content"
      className={cn("px-6", className)}
      {...props}
    />
  )
}

/**
 * Renders the footer section of a card.
 *
 * @param className - Additional CSS classes to apply to the footer
 */
function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn("flex items-center px-6", className)}
      {...props}
    />
  )
}

export {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
}
