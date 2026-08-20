import * as React from "react"
import { Label as LabelPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

/**
 * Renders a styled label while forwarding props to the underlying label primitive.
 *
 * @param className - Additional classes to apply to the label
 */
function Label({
  className,
  ...props
}: React.ComponentProps<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      data-slot="label"
      className={cn(
        "flex select-none items-center gap-2 text-sm font-medium leading-none",
        className
      )}
      {...props}
    />
  )
}

export { Label }
