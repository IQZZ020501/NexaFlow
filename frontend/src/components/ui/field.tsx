import * as React from "react"

import { cn } from "@/lib/utils"
import { Label } from "@/components/ui/label"

/**
 * Groups related field components in a vertically spaced layout.
 *
 * @param className - Additional CSS classes to apply to the group
 */
function FieldGroup({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="field-group"
      className={cn("flex flex-col gap-4", className)}
      {...props}
    />
  )
}

/**
 * Renders a field container with vertical layout and spacing.
 *
 * @param className - Additional classes to apply to the container
 */
function Field({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="field"
      className={cn("flex flex-col gap-2", className)}
      {...props}
    />
  )
}

/**
 * Renders a styled label for a field.
 *
 * @returns A label element with field-specific styling.
 */
function FieldLabel({
  className,
  ...props
}: React.ComponentProps<typeof Label>) {
  return (
    <Label
      data-slot="field-label"
      className={cn("text-sm", className)}
      {...props}
    />
  )
}

/**
 * Renders descriptive text associated with a form field.
 *
 * @param className - Additional CSS classes to apply to the description
 * @returns The field description paragraph element
 */
function FieldDescription({
  className,
  ...props
}: React.ComponentProps<"p">) {
  return (
    <p
      data-slot="field-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

export { Field, FieldDescription, FieldGroup, FieldLabel }
