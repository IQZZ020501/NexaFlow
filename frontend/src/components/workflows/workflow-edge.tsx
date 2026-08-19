"use client"

import * as React from "react"
import {
  BaseEdge,
  getBezierPath,
  type Edge,
  type EdgeProps,
} from "@xyflow/react"
import { XIcon } from "lucide-react"

type WorkflowEdgeData = Record<string, unknown> & {
  deleteLabel: string
  readOnly: boolean
  onDelete: (id: string) => void
}

type InteractiveWorkflowEdge = Edge<WorkflowEdgeData, "workflow">

/**
 * Renders an interactive workflow edge with selection styling and an optional delete control.
 *
 * @param data - Controls read-only behavior and handles delete requests.
 * @returns The rendered workflow edge.
 */
export function WorkflowEdgeCard({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerStart,
  markerEnd,
  selected,
  style,
  data,
}: EdgeProps<InteractiveWorkflowEdge>) {
  const [hovered, setHovered] = React.useState(false)
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  })
  const showDelete = !data?.readOnly && (hovered || selected)

  return (
    <g
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <BaseEdge
        id={id}
        path={path}
        markerStart={markerStart}
        markerEnd={markerEnd}
        interactionWidth={28}
        style={{
          ...style,
          strokeWidth: selected ? 2.5 : 1.6,
        }}
      />
      {showDelete ? (
        <foreignObject
          x={labelX - 13}
          y={labelY - 13}
          width={26}
          height={26}
          className="overflow-visible"
        >
          <button
            type="button"
            className="nodrag nopan flex size-6 items-center justify-center rounded-full border bg-background text-muted-foreground shadow-md transition-[color,background-color,transform] hover:scale-110 hover:bg-destructive hover:text-destructive-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={data?.deleteLabel}
            title={data?.deleteLabel}
            onClick={(event) => {
              event.stopPropagation()
              data?.onDelete(id)
            }}
          >
            <XIcon className="size-3.5" />
          </button>
        </foreignObject>
      ) : null}
    </g>
  )
}
