import * as React from "react"
import { Button } from "@/components/ui/button"

export function IconButton({
  label,
  children,
  onClick,
}: {
  label: string
  children: React.ReactNode
  onClick: (event: React.MouseEvent<HTMLButtonElement>) => void
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      title={label}
      onClick={onClick}
    >
      {children}
      <span className="sr-only">{label}</span>
    </Button>
  )
}
