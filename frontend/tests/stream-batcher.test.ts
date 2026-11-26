import { describe, expect, test } from "bun:test"

import { createStreamEventBatcher } from "@/lib/stream-batcher"

type TestEvent =
  | { type: "delta"; delta: string }
  | { type: "reasoning"; delta: string }
  | { type: "complete" }

describe("createStreamEventBatcher", () => {
  test("batches delta and reasoning chunks and flushes before structural events", () => {
    const batches: TestEvent[][] = []
    const batcher = createStreamEventBatcher<TestEvent>(
      (event) => event.type === "delta" || event.type === "reasoning",
      (events) => batches.push(events)
    )

    batcher.push({ type: "reasoning", delta: "step 1 " })
    batcher.push({ type: "delta", delta: "hel" })
    batcher.push({ type: "delta", delta: "lo" })
    expect(batches.length).toBe(0)

    batcher.push({ type: "complete" })
    expect(batches).toEqual([
      [
        { type: "reasoning", delta: "step 1 " },
        { type: "delta", delta: "hel" },
        { type: "delta", delta: "lo" },
      ],
      [{ type: "complete" }],
    ])
  })

  test("cancel drops queued events without flushing", () => {
    const batches: TestEvent[][] = []
    const batcher = createStreamEventBatcher<TestEvent>(
      (event) => event.type === "delta",
      (events) => batches.push(events)
    )

    batcher.push({ type: "delta", delta: "abandoned" })
    batcher.cancel()
    batcher.flushNow()
    expect(batches).toEqual([])
  })
})
