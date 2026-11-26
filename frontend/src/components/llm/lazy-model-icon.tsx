"use client"

import * as React from "react"
import type ModelIcon from "@lobehub/icons/es/features/ModelIcon"
import dynamic from "next/dynamic"

export type LazyModelIconProps = React.ComponentProps<typeof ModelIcon>

const DynamicModelIcon = dynamic(
  () => import("@lobehub/icons/es/features/ModelIcon"),
  { ssr: false }
)

/**
 * Dynamically loaded wrapper around `@lobehub/icons` `ModelIcon` so model-icon
 * sprite/SVG chunks stay out of initial page bundles.
 */
export function LazyModelIcon(props: LazyModelIconProps) {
  return <DynamicModelIcon {...props} />
}
