/// <reference lib="webworker" />

import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force"

type LayoutNode = SimulationNodeDatum & {
  id: string
  radius: number
}

type LayoutEdge = SimulationLinkDatum<LayoutNode> & {
  source: string | LayoutNode
  target: string | LayoutNode
  weight: number
}

type InitializeMessage = {
  type: "initialize"
  nodes: Array<{ id: string; radius: number }>
  edges: Array<{ source: string; target: string; weight: number }>
}

type PinMessage = {
  type: "pin"
  id: string
  x: number
  y: number
}

type ReleaseMessage = {
  type: "release"
  id: string
}

type ReheatMessage = { type: "reheat" }
type StopMessage = { type: "stop" }
type WorkerMessage =
  InitializeMessage | PinMessage | ReleaseMessage | ReheatMessage | StopMessage

let simulation: Simulation<LayoutNode, LayoutEdge> | null = null
let nodes: LayoutNode[] = []
let lastFrameAt = 0

function emitPositions(force = false) {
  const now = performance.now()
  if (!force && now - lastFrameAt < 32) return
  lastFrameAt = now
  const positions = new Float32Array(nodes.length * 2)
  for (let index = 0; index < nodes.length; index += 1) {
    positions[index * 2] = nodes[index].x ?? 0
    positions[index * 2 + 1] = nodes[index].y ?? 0
  }
  self.postMessage(
    { type: "positions", positions: positions.buffer },
    { transfer: [positions.buffer] }
  )
}

function initialize(message: InitializeMessage) {
  simulation?.stop()
  nodes = message.nodes.map((node, index) => {
    const radius = index === 0 ? 0 : 48 * Math.sqrt(index)
    const angle = index * Math.PI * (3 - Math.sqrt(5))
    return {
      ...node,
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
    }
  })
  const edges: LayoutEdge[] = message.edges.map((edge) => ({ ...edge }))
  simulation = forceSimulation<LayoutNode>(nodes)
    .force(
      "links",
      forceLink<LayoutNode, LayoutEdge>(edges)
        .id((node) => node.id)
        .distance((edge) => Math.max(76, 132 - Math.log2(edge.weight + 1) * 12))
        .strength((edge) => Math.min(0.75, 0.22 + edge.weight * 0.08))
    )
    .force(
      "charge",
      forceManyBody<LayoutNode>()
        .strength((node) => -150 - node.radius * 7)
        .distanceMax(900)
    )
    .force("x", forceX<LayoutNode>(0).strength(0.035))
    .force("y", forceY<LayoutNode>(0).strength(0.035))
    .force(
      "collision",
      forceCollide<LayoutNode>()
        .radius((node) => node.radius + 20)
        .strength(0.85)
        .iterations(2)
    )
    .alpha(1)
    .alphaDecay(0.025)
    .velocityDecay(0.34)
    .on("tick", () => emitPositions())
    .on("end", () => emitPositions(true))
}

self.onmessage = (event: MessageEvent<WorkerMessage>) => {
  const message = event.data
  if (message.type === "initialize") {
    initialize(message)
    return
  }
  if (message.type === "stop") {
    simulation?.stop()
    simulation = null
    return
  }
  if (message.type === "reheat") {
    simulation?.alphaTarget(0.18).restart()
    setTimeout(() => simulation?.alphaTarget(0), 180)
    return
  }
  const node = nodes.find((item) => item.id === message.id)
  if (!node || !simulation) return
  if (message.type === "pin") {
    node.fx = message.x
    node.fy = message.y
    simulation.alphaTarget(0.24).restart()
    return
  }
  node.fx = null
  node.fy = null
  simulation.alphaTarget(0.12).restart()
  setTimeout(() => simulation?.alphaTarget(0), 160)
}

export {}
