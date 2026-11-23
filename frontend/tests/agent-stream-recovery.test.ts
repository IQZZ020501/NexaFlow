import { describe, expect, test } from "bun:test"

import { mergeAgentRunStreamEvent } from "@/components/agents/agents-page"
import { mergePublicRunEvent } from "@/components/agents/public-agent-chat"
import type { AgentRun, AgentRunStreamEvent } from "@/lib/api/agents"
import type {
  ExternalAgentRun,
  PublicAgentRunStreamEvent,
} from "@/lib/api/public-agents"
import { observeNdjsonStream } from "@/lib/api/run-stream"

type ProcessEvent = Record<string, unknown>

function harness(surface: "console" | "public") {
  const collection = surface === "console" ? "events" : "progress"
  const thought = (turn: number, reasoning: string, extra = {}) => ({
    type: surface === "console" ? "thought" : "analysis",
    id: `analysis-${turn}`,
    turn,
    reasoning,
    status: "running",
    summary: "agent.reviewing_tool_results",
    stage: "reviewing",
    tool_name: "",
    call_id: "",
    input: {},
    ...extra,
  })
  const tool = (extra = {}) => ({
    ...thought(1, ""),
    type: "tool",
    id: "tool-1",
    call_id: "call-1",
    status: "succeeded",
    summary: "agent.tool_succeeded",
    stage: "succeeded",
    tool_name: "bash",
    input: { command: "ls" },
    ...extra,
  })
  const snapshot = (events: ProcessEvent[]) => ({
    id: "run-1",
    status: "running",
    result: "",
    updated_at: "2026-11-18T00:00:00Z",
    [collection]: events,
  })
  let state = snapshot([])
  return {
    thought,
    tool,
    reset(events: ProcessEvent[]) {
      state = snapshot(events)
    },
    merge(event: unknown) {
      const runs =
        surface === "console"
          ? mergeAgentRunStreamEvent(
              [state as unknown as AgentRun],
              "run-1",
              event as AgentRunStreamEvent
            )
          : mergePublicRunEvent(
              [state as unknown as ExternalAgentRun],
              "run-1",
              event as PublicAgentRunStreamEvent,
              "run-1"
            )
      state = runs[0] as unknown as typeof state
    },
    events: () => state[collection] as ProcessEvent[],
    process(event: ProcessEvent, sequence: number) {
      return {
        type: surface === "console" ? "process" : "progress",
        event,
        sequence,
      }
    },
    run: (events: ProcessEvent[]) => ({
      type: "run",
      sequence: 0,
      run: snapshot(events),
    }),
    delta: (delta: string, live_sequence: string, extra = {}) => ({
      type: "reasoning_delta",
      turn: 2,
      delta,
      live_sequence,
      stream_epoch: "worker-1",
      ...extra,
    }),
    toolDelta: (delta: string, live_sequence: string) => ({
      type: "tool_input_delta",
      turn: 1,
      id: "tool-1",
      call_id: "call-1",
      tool_name: "bash",
      field: "command",
      delta,
      replace: false,
      stream_epoch: "worker-1",
      live_sequence,
    }),
  }
}

describe.each(["console", "public"] as const)(
  "%s stream recovery",
  (surface) => {
    test("updates history compaction in place and keeps its completed state on reconnect", () => {
      const h = harness(surface)
      const started = {
        ...h.thought(0, ""), id: "compaction-0", type: "compaction",
        summary: "agent.history_compaction_running", stage: "running",
      }
      h.merge(h.process(started, 1))
      expect(h.events()).toHaveLength(1)
      h.merge(h.process({
        ...started, status: "succeeded", stage: "succeeded",
        summary: "agent.history_compaction_succeeded",
      }, 2))
      expect(h.events()).toHaveLength(1)
      expect(h.events()[0].status).toBe("succeeded")
      h.merge(h.run([{ ...started, sequence: 1 }]))
      expect(h.events()).toHaveLength(1)
      expect(h.events()[0].status).toBe("succeeded")
    })

    test("replays completed turns and tool inputs without appending them twice", () => {
      const h = harness(surface)
      h.reset([
        h.thought(1, "X", { status: "succeeded" }),
        h.tool(),
        h.thought(2, "ABC", { status: "succeeded" }),
      ])
      h.merge(h.delta("X", "1000-0", { turn: 1 }))
      h.merge(h.toolDelta("l", "1000-1"))
      h.merge(h.toolDelta("s", "1000-2"))
      h.merge(h.delta("A", "1000-3"))
      h.merge(h.delta("B", "1000-4"))
      h.merge(h.delta("C", "1000-5"))
      expect(h.events()[0].reasoning).toBe("X")
      expect(h.events()[1].input).toEqual({ command: "ls" })
      expect(h.events()[2].reasoning).toBe("ABC")
    })

    test("appends only deltas after an active process watermark", () => {
      const h = harness(surface)
      h.reset([
        h.thought(1, ""),
        h.thought(2, "AB", {
          sequence: 7,
          stream_epoch: "worker-1",
          live_sequence: "1000-2",
        }),
      ])
      h.merge(h.delta("X", "1000-0", { turn: 1 }))
      h.merge(h.delta("A", "1000-1"))
      h.merge(h.delta("B", "1000-2"))
      h.merge(h.delta("C", "1000-3"))
      expect(h.events()[1].reasoning).toBe("ABC")
    })

    test("keeps partial tool arguments across an older preparing event", () => {
      const h = harness(surface)
      const preparing = h.tool({
        status: "running",
        stage: "preparing",
        summary: "agent.preparing_tool_call",
        input: {},
        stream_epoch: "worker-1",
        live_sequence: "1000-0",
      })
      h.reset([])
      h.merge(h.process(preparing, 7))
      h.merge(h.toolDelta("l", "1000-1"))
      h.merge(h.process(preparing, 7))
      h.merge(h.toolDelta("s", "1000-2"))
      expect(h.events()[0].input).toEqual({ command: "ls" })
    })

    test("resets a step on a newer worker version and rejects older worker deltas", () => {
      const h = harness(surface)
      h.reset([
        h.thought(2, "old", {
          sequence: 7,
          stream_epoch: "worker-1",
          live_sequence: "1000-1",
        }),
      ])
      h.merge(
        h.process(
          h.thought(2, "", {
            stream_epoch: "worker-2",
            live_sequence: "1000-2",
          }),
          8
        )
      )
      h.merge(h.delta("old", "1000-1"))
      h.merge(h.delta("new", "2000-1", { stream_epoch: "worker-2" }))
      expect(h.events()[0].reasoning).toBe("new")
    })

    test("keeps live reasoning when a reconnect snapshot is behind", () => {
      const h = harness(surface)
      const previous = h.thought(1, "X", { status: "succeeded", sequence: 3 })
      h.reset([previous])
      h.merge(
        h.process(
          h.thought(2, "", {
            stream_epoch: "worker-1",
            live_sequence: "1000-0",
          }),
          7
        )
      )
      h.merge(h.delta("AB", "1000-2"))
      h.merge(h.run([previous]))
      h.merge(h.process(h.thought(2, ""), 7))
      h.merge(h.delta("AB", "1000-2"))
      h.merge(h.delta("C", "1000-3"))
      expect(h.events().find((event) => event.turn === 2)?.reasoning).toBe(
        "ABC"
      )
    })

    test("rejects older process versions even after a completed snapshot", () => {
      const h = harness(surface)
      h.reset([h.thought(2, "ABC", { status: "succeeded", sequence: 9 })])
      h.merge(h.process(h.thought(2, ""), 7))
      expect(h.events()[0].reasoning).toBe("ABC")
      expect(h.events()[0].status).toBe("succeeded")
    })

    test("retains deltas delivered ahead of a newer durable process", () => {
      const h = harness(surface)
      h.reset([
        h.thought(2, "A", {
          sequence: 7,
          stream_epoch: "worker-1",
          live_sequence: "1000-1",
        }),
      ])
      h.merge(h.delta("BC", "1000-3"))
      h.merge(
        h.process(
          h.thought(2, "AB", {
            stream_epoch: "worker-1",
            live_sequence: "1000-2",
          }),
          8
        )
      )
      expect(h.events()[0].reasoning).toBe("ABC")
    })

    test("does not mutate finalized tool arguments while the tool is running", () => {
      const h = harness(surface)
      h.reset([
        h.tool({
          status: "running",
          stage: "running",
          summary: "agent.tool_running",
        }),
      ])
      h.merge(h.toolDelta("ls", "1000-1"))
      expect(h.events()[0].input).toEqual({ command: "ls" })
    })
  }
)

test("public answer reasoning stays authoritative during a history replay", () => {
  const h = harness("public")
  const answer = h.thought(2, "ABC", {
    type: "answer",
    id: "answer-2",
    stage: "running",
    sequence: 9,
    stream_epoch: "worker-1",
    live_sequence: "1000-3",
  })
  h.reset([answer])
  h.merge(h.process(h.thought(2, ""), 7))
  h.merge(h.delta("ABC", "1000-3"))
  expect(h.events()).toEqual([answer])
})

test("resumes both cursors after reader.read throws mid-stream", async () => {
  const requests: { cursor: number; liveCursor: string }[] = []
  const received: string[] = []
  const encoder = new TextEncoder()
  await observeNdjsonStream(
    async (cursor, liveCursor) => {
      requests.push({ cursor, liveCursor })
      if (requests.length > 1) return new Response('{"type":"complete"}\n')
      let read = false
      return new Response(
        new ReadableStream({
          pull(controller) {
            if (read) throw new TypeError("connection reset")
            read = true
            controller.enqueue(
              encoder.encode(
                '{"type":"process","sequence":7}\n' +
                  '{"type":"reasoning_delta","live_sequence":"1000-2"}\n'
              )
            )
          },
        })
      )
    },
    (event) => received.push(event.type),
    { errorLabel: "Recovery test" }
  )
  expect(requests).toEqual([
    { cursor: 0, liveCursor: "0-0" },
    { cursor: 7, liveCursor: "1000-2" },
  ])
  expect(received).toEqual(["process", "reasoning_delta", "complete"])
})

test("does not reconnect after a delivered terminal event when the body stays open", async () => {
  let requests = 0
  let cancelled = false
  await observeNdjsonStream(
    async () => {
      requests += 1
      return new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(
              new TextEncoder().encode('{"type":"complete"}\n')
            )
          },
          cancel() {
            cancelled = true
          },
        })
      )
    },
    () => {},
    { errorLabel: "Recovery test" }
  )
  expect(requests).toBe(1)
  expect(cancelled).toBe(true)
})
