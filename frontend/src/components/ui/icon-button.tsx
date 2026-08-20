import * as React from "react"
import { Button } from "@/components/ui/button"

type IconButtonProps = Omit<
  React.ComponentProps<typeof Button>,
  "children" | "size" | "title" | "type" | "variant"
> & {
  label: string
  children: React.ReactNode
}

/**
 * Renders an icon button with an accessible label.
 *
 * @param label - The accessible text and tooltip for the button
 * @param children - The icon or content displayed in the button
 */
export function IconButton({
  label,
  children,
  ...props
}: IconButtonProps) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      title={label}
      {...props}
    >
      {children}
      <span className="sr-only">{label}</span>
    </Button>
  )
}
