"use client"

import * as React from "react"
import { LocateFixedIcon, MinusIcon, NetworkIcon, PlusIcon } from "lucide-react"
import type {
  Application,
  Container,
  Graphics,
  Text as PixiText,
} from "pixi.js"

import { Button } from "@/components/ui/button"
import { useLanguage } from "@/contexts/language-provider"
import type {
  KnowledgeLinkGraphEdge,
  KnowledgeLinkGraphNode,
} from "@/lib/api/knowledge"

type NodeDisplay = {
  container: Container
  circle: Graphics
  label: PixiText
  node: KnowledgeLinkGraphNode
  radius: number
}

type CanvasRuntime = {
  app: Application
  root: Container
  fit: () => void
  zoom: (factor: number) => void
  reheat: () => void
  redrawNodes: () => void
}

function nodeRadius(node: KnowledgeLinkGraphNode) {
  return Math.min(24, 7 + Math.sqrt(Math.max(0, node.degree)) * 2.2)
}

function readThemeColor(
  host: HTMLElement,
  className: string,
  property: "color" | "backgroundColor",
  fallbackCss: string,
  fallbackColor: number,
  context: CanvasRenderingContext2D | null
) {
  const probe = document.createElement("span")
  probe.className = className
  probe.style.position = "absolute"
  probe.style.pointerEvents = "none"
  probe.style.opacity = "0"
  host.appendChild(probe)
  const value = getComputedStyle(probe)[property] || fallbackCss
  probe.remove()
  return cssColorToPixiColor(value, fallbackColor, context)
}

export function cssColorToPixiColor(
  value: string,
  fallback: number,
  context: CanvasRenderingContext2D | null
) {
  if (!context) return fallback
  if (typeof CSS !== "undefined" && !CSS.supports("color", value)) {
    return fallback
  }
  try {
    context.clearRect(0, 0, 1, 1)
    context.fillStyle = value
    context.fillRect(0, 0, 1, 1)
    const [red = 0, green = 0, blue = 0] = context.getImageData(0, 0, 1, 1).data
    return (red << 16) | (green << 8) | blue
  } catch {
    return fallback
  }
}

function createCssColorContext() {
  try {
    const canvas = document.createElement("canvas")
    canvas.width = 1
    canvas.height = 1
    return canvas.getContext("2d", { willReadFrequently: true })
  } catch {
    return null
  }
}

function readGraphColors(host: HTMLElement) {
  const context = createCssColorContext()
  return {
    background: readThemeColor(
      host,
      "bg-background",
      "backgroundColor",
      "rgb(255, 255, 255)",
      0xffffff,
      context
    ),
    foreground: readThemeColor(
      host,
      "text-foreground",
      "color",
      "rgb(24, 24, 27)",
      0x18181b,
      context
    ),
    muted: readThemeColor(
      host,
      "text-muted-foreground",
      "color",
      "rgb(113, 113, 122)",
      0x71717a,
      context
    ),
    primary: readThemeColor(
      host,
      "text-primary",
      "color",
      "rgb(37, 99, 235)",
      0x2563eb,
      context
    ),
    destructive: readThemeColor(
      host,
      "text-destructive",
      "color",
      "rgb(220, 38, 38)",
      0xdc2626,
      context
    ),
  }
}

export function KnowledgeGraphCanvas({
  nodes,
  edges,
  selectedNodeId,
  highlightedNodeIds,
  onNodeSelect,
  onNodeOpen,
}: {
  nodes: KnowledgeLinkGraphNode[]
  edges: KnowledgeLinkGraphEdge[]
  selectedNodeId: string | null
  highlightedNodeIds: ReadonlySet<string>
  onNodeSelect: (nodeId: string) => void
  onNodeOpen: (nodeId: string) => void
}) {
  const { t } = useLanguage()
  const hostRef = React.useRef<HTMLDivElement>(null)
  const runtimeRef = React.useRef<CanvasRuntime | null>(null)
  const selectedNodeIdRef = React.useRef(selectedNodeId)
  const highlightedNodeIdsRef = React.useRef(highlightedNodeIds)
  const onNodeSelectRef = React.useRef(onNodeSelect)
  const onNodeOpenRef = React.useRef(onNodeOpen)
  const [rendererFailed, setRendererFailed] = React.useState(false)

  React.useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId
    highlightedNodeIdsRef.current = highlightedNodeIds
    runtimeRef.current?.redrawNodes()
  }, [highlightedNodeIds, selectedNodeId])

  React.useEffect(() => {
    onNodeSelectRef.current = onNodeSelect
    onNodeOpenRef.current = onNodeOpen
  }, [onNodeOpen, onNodeSelect])

  React.useEffect(() => {
    const host = hostRef.current
    if (!host || typeof Worker === "undefined" || !nodes.length) return
    let disposed = false
    let worker: Worker | null = null
    let runtime: CanvasRuntime | null = null
    let app: Application | null = null
    let themeObserver: MutationObserver | null = null

    void import("pixi.js")
      .then(
        ({
          Application: PixiApplication,
          Circle,
          Container: PixiContainer,
          Graphics: PixiGraphics,
          Point,
          Text: PixiTextClass,
        }) => {
          if (disposed) return
          setRendererFailed(false)
          let colors = readGraphColors(host)
          const pixiApp = new PixiApplication({
            resizeTo: host,
            antialias: true,
            autoDensity: true,
            resolution: Math.min(window.devicePixelRatio || 1, 2),
            backgroundAlpha: 0,
          })
          app = pixiApp
          const canvas = pixiApp.view as HTMLCanvasElement
          canvas.className = "block size-full touch-none"
          canvas.setAttribute("aria-hidden", "true")
          host.replaceChildren(canvas)

          const root = new PixiContainer()
          const edgeGraphics = new PixiGraphics()
          root.addChild(edgeGraphics)
          pixiApp.stage.addChild(root)
          pixiApp.stage.eventMode = "static"
          pixiApp.stage.hitArea = pixiApp.screen

          const displays = new Map<string, NodeDisplay>()
          const positions = new Map<string, { x: number; y: number }>()
          const nodeById = new Map(nodes.map((node) => [node.id, node]))
          let fitted = false
          let draggedNodeId: string | null = null
          let panStart: {
            x: number
            y: number
            rootX: number
            rootY: number
          } | null = null

          function redrawNode(display: NodeDisplay) {
            const selected = selectedNodeIdRef.current === display.node.id
            const highlighted = highlightedNodeIdsRef.current.has(
              display.node.id
            )
            const dimmed =
              highlightedNodeIdsRef.current.size > 0 && !highlighted
            display.container.alpha = dimmed ? 0.22 : 1
            display.circle.clear()
            if (display.node.kind === "unresolved") {
              display.circle.lineStyle(
                selected ? 3 : 1.5,
                selected ? colors.primary : colors.destructive,
                selected ? 1 : 0.72
              )
              display.circle.beginFill(colors.background, 0.9)
            } else {
              display.circle.lineStyle(
                selected ? 3 : 1,
                selected ? colors.primary : colors.background,
                selected ? 1 : 0.65
              )
              display.circle.beginFill(
                selected ? colors.primary : colors.muted,
                selected ? 1 : 0.86
              )
            }
            display.circle.drawCircle(0, 0, display.radius)
            display.circle.endFill()
            display.label.style.fill = selected
              ? colors.primary
              : colors.foreground
            display.label.style.fontWeight = selected ? "600" : "500"
          }

          function redrawNodes() {
            for (const display of displays.values()) redrawNode(display)
          }

          function drawEdges() {
            edgeGraphics.clear()
            for (const edge of edges) {
              const source = positions.get(edge.source)
              const target = positions.get(edge.target)
              const targetNode = nodeById.get(edge.target)
              if (!source || !target || !targetNode) continue
              const dx = target.x - source.x
              const dy = target.y - source.y
              const distance = Math.max(1, Math.hypot(dx, dy))
              const ux = dx / distance
              const uy = dy / distance
              const targetRadius = nodeRadius(targetNode)
              const endX = target.x - ux * (targetRadius + 4)
              const endY = target.y - uy * (targetRadius + 4)
              const width = Math.min(
                3.2,
                0.7 + Math.log2(edge.count + 1) * 0.55
              )
              edgeGraphics.lineStyle(
                width,
                colors.muted,
                edge.resolved ? 0.34 : 0.22
              )
              edgeGraphics.moveTo(source.x, source.y)
              edgeGraphics.lineTo(endX, endY)
              const arrow = 5 + width
              const leftX = endX - ux * arrow - uy * arrow * 0.65
              const leftY = endY - uy * arrow + ux * arrow * 0.65
              const rightX = endX - ux * arrow + uy * arrow * 0.65
              const rightY = endY - uy * arrow - ux * arrow * 0.65
              edgeGraphics.beginFill(colors.muted, edge.resolved ? 0.45 : 0.3)
              edgeGraphics.drawPolygon([
                endX,
                endY,
                leftX,
                leftY,
                rightX,
                rightY,
              ])
              edgeGraphics.endFill()
            }
          }

          themeObserver = new MutationObserver(() => {
            colors = readGraphColors(host)
            redrawNodes()
            drawEdges()
          })
          themeObserver.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ["class", "data-palette"],
          })

          function fit() {
            if (!positions.size) return
            const values = [...positions.values()]
            const minX = Math.min(...values.map((position) => position.x))
            const maxX = Math.max(...values.map((position) => position.x))
            const minY = Math.min(...values.map((position) => position.y))
            const maxY = Math.max(...values.map((position) => position.y))
            const width = Math.max(120, maxX - minX + 180)
            const height = Math.max(120, maxY - minY + 180)
            const scale = Math.max(
              0.08,
              Math.min(
                1.35,
                pixiApp.screen.width / width,
                pixiApp.screen.height / height
              )
            )
            root.scale.set(scale)
            root.position.set(
              pixiApp.screen.width / 2 - ((minX + maxX) / 2) * scale,
              pixiApp.screen.height / 2 - ((minY + maxY) / 2) * scale
            )
          }

          function zoom(factor: number) {
            const previous = root.scale.x || 1
            const next = Math.max(0.08, Math.min(3, previous * factor))
            const center = new Point(
              pixiApp.screen.width / 2,
              pixiApp.screen.height / 2
            )
            const local = root.toLocal(center)
            root.scale.set(next)
            root.position.set(
              center.x - local.x * next,
              center.y - local.y * next
            )
          }

          for (const node of nodes) {
            const radius = nodeRadius(node)
            const container = new PixiContainer()
            const circle = new PixiGraphics()
            const label = new PixiTextClass(node.label, {
              fill: colors.foreground,
              fontFamily:
                "Geist Variable, ui-sans-serif, system-ui, sans-serif",
              fontSize: 12,
              fontWeight: "500",
              align: "center",
            })
            label.anchor.set(0.5, 0)
            label.y = radius + 5
            label.resolution = Math.min(window.devicePixelRatio || 1, 2)
            container.addChild(circle, label)
            container.eventMode = "static"
            container.cursor = "pointer"
            container.hitArea = new Circle(0, 0, radius + 10)
            container.on("pointertap", () => onNodeSelectRef.current(node.id))
            container.on("rightclick", () => onNodeOpenRef.current(node.id))
            container.on("pointerdown", (event) => {
              event.stopPropagation()
              draggedNodeId = node.id
              onNodeSelectRef.current(node.id)
              const point = root.toLocal(event.global)
              worker?.postMessage({
                type: "pin",
                id: node.id,
                x: point.x,
                y: point.y,
              })
            })
            const display = { container, circle, label, node, radius }
            displays.set(node.id, display)
            root.addChild(container)
            redrawNode(display)
          }

          pixiApp.stage.on("pointerdown", (event) => {
            if (draggedNodeId) return
            panStart = {
              x: event.global.x,
              y: event.global.y,
              rootX: root.position.x,
              rootY: root.position.y,
            }
          })
          pixiApp.stage.on("pointermove", (event) => {
            if (draggedNodeId) {
              const point = root.toLocal(event.global)
              worker?.postMessage({
                type: "pin",
                id: draggedNodeId,
                x: point.x,
                y: point.y,
              })
              return
            }
            if (!panStart) return
            root.position.set(
              panStart.rootX + event.global.x - panStart.x,
              panStart.rootY + event.global.y - panStart.y
            )
          })
          const endPointer = () => {
            if (draggedNodeId) {
              worker?.postMessage({ type: "release", id: draggedNodeId })
            }
            draggedNodeId = null
            panStart = null
          }
          pixiApp.stage.on("pointerup", endPointer)
          pixiApp.stage.on("pointerupoutside", endPointer)

          const handleWheel = (event: WheelEvent) => {
            event.preventDefault()
            const rect = canvas.getBoundingClientRect()
            const cursor = new Point(
              event.clientX - rect.left,
              event.clientY - rect.top
            )
            const local = root.toLocal(cursor)
            const next = Math.max(
              0.08,
              Math.min(3, root.scale.x * Math.exp(-event.deltaY * 0.0015))
            )
            root.scale.set(next)
            root.position.set(
              cursor.x - local.x * next,
              cursor.y - local.y * next
            )
          }
          canvas.addEventListener("wheel", handleWheel, { passive: false })

          worker = new Worker(
            new URL("./knowledge-graph.worker.ts", import.meta.url),
            { type: "module" }
          )
          worker.onmessage = (
            event: MessageEvent<{
              type: "positions"
              positions: ArrayBuffer
            }>
          ) => {
            if (event.data.type !== "positions") return
            const values = new Float32Array(event.data.positions)
            nodes.forEach((node, index) => {
              const position = {
                x: values[index * 2] ?? 0,
                y: values[index * 2 + 1] ?? 0,
              }
              positions.set(node.id, position)
              displays
                .get(node.id)
                ?.container.position.set(position.x, position.y)
            })
            drawEdges()
            if (!fitted && positions.size === nodes.length) {
              fitted = true
              fit()
            }
          }
          worker.postMessage({
            type: "initialize",
            nodes: nodes.map((node) => ({
              id: node.id,
              radius: nodeRadius(node),
            })),
            edges: edges.map((edge) => ({
              source: edge.source,
              target: edge.target,
              weight: edge.count,
            })),
          })

          runtime = {
            app: pixiApp,
            root,
            fit,
            zoom,
            reheat: () => worker?.postMessage({ type: "reheat" }),
            redrawNodes,
          }
          runtimeRef.current = runtime
        }
      )
      .catch((error: unknown) => {
        themeObserver?.disconnect()
        app?.destroy(true, {
          children: true,
          texture: true,
          baseTexture: true,
        })
        app = null
        host.replaceChildren()
        if (!disposed) {
          if (process.env.NODE_ENV !== "test") {
            console.error(
              "[knowledge-graph-canvas] Failed to initialize graph canvas",
              error
            )
          }
          setRendererFailed(true)
        }
      })

    return () => {
      disposed = true
      worker?.postMessage({ type: "stop" })
      worker?.terminate()
      themeObserver?.disconnect()
      runtimeRef.current = null
      app?.destroy(true, {
        children: true,
        texture: true,
        baseTexture: true,
      })
      app = null
      host.replaceChildren()
    }
  }, [edges, nodes])

  return (
    <div
      className="relative h-[calc(100vh-15rem)] min-h-[36rem] w-full overflow-hidden bg-muted/15 max-sm:h-[62svh] max-sm:min-h-[22rem]"
      data-testid="knowledge-graph-canvas"
    >
      <div ref={hostRef} className="absolute inset-0" />
      <div className="pointer-events-none absolute top-3 left-3 z-10 rounded-md border bg-background/85 px-3 py-2 text-xs text-muted-foreground shadow-xs backdrop-blur">
        {t("拖动节点重新布局 · 拖动画布平移 · 滚轮缩放")}
      </div>
      <div
        className="absolute right-3 bottom-3 z-10 flex items-center gap-1 rounded-md border bg-background/90 p-1 shadow-sm backdrop-blur"
        aria-label={t("知识关联画布控制")}
      >
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={t("缩小")}
          onClick={() => runtimeRef.current?.zoom(0.8)}
        >
          <MinusIcon />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={t("放大")}
          onClick={() => runtimeRef.current?.zoom(1.25)}
        >
          <PlusIcon />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={t("适合画布")}
          onClick={() => runtimeRef.current?.fit()}
        >
          <LocateFixedIcon />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={t("重新计算布局")}
          onClick={() => runtimeRef.current?.reheat()}
        >
          <NetworkIcon />
        </Button>
      </div>
      {rendererFailed ? (
        <p className="absolute inset-x-4 top-16 text-center text-sm text-destructive">
          {t("图谱画布初始化失败")}
        </p>
      ) : null}
      <div className="sr-only" aria-label={t("知识关联画布")}>
        {nodes.map((node) => (
          <button
            key={node.id}
            type="button"
            aria-label={t("选择节点 {name}", { name: node.filename })}
            onClick={() => onNodeSelect(node.id)}
          >
            {node.filename}
          </button>
        ))}
      </div>
    </div>
  )
}
