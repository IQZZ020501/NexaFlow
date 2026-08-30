/* eslint-disable @next/next/no-img-element -- tiny local Skill icons do not need image optimization */
import type { ComponentType } from "react"
import { WrenchIcon } from "lucide-react"

import { cn } from "@/lib/utils"

type IconComponent = ComponentType<{ className?: string }>

const BUILTIN_TOOL_ICON_PATHS: Record<string, string> = {
  documents_skill: "/skill-icons/docx.png",
  pdf_skill: "/skill-icons/pdf.png",
  pptx_skill: "/skill-icons/pptx.png",
  spreadsheets_skill: "/skill-icons/excel.png",
}

type BuiltinToolIconProps = {
  functionName?: string | null
  className?: string
  fallback?: IconComponent
}

/** Renders the product file icon for built-in file Skills and a tool fallback otherwise. */
export function BuiltinToolIcon({
  functionName,
  className,
  fallback: Fallback = WrenchIcon,
}: BuiltinToolIconProps) {
  const src = functionName ? BUILTIN_TOOL_ICON_PATHS[functionName] : undefined
  if (!src) return <Fallback className={className} />

  return (
    <img
      src={src}
      alt=""
      aria-hidden="true"
      width={24}
      height={24}
      className={cn("object-contain", className)}
      decoding="async"
    />
  )
}
