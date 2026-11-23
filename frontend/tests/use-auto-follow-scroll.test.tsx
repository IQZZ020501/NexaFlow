/* @jsxImportSource react */
import { afterEach, beforeEach, expect, test } from "bun:test"
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"

import { useAutoFollowScroll } from "@/lib/use-auto-follow-scroll"

const originalObserver = globalThis.ResizeObserver

class ResizeObserverStub {
  static instances: ResizeObserverStub[] = []
  disconnected = false
  constructor(private callback: ResizeObserverCallback) {
    ResizeObserverStub.instances.push(this)
  }
  observe() {}
  unobserve() {}
  disconnect() {
    this.disconnected = true
  }
  emit() {
    this.callback([], this as unknown as ResizeObserver)
  }
}

beforeEach(() => {
  ResizeObserverStub.instances = []
  globalThis.ResizeObserver =
    ResizeObserverStub as unknown as typeof ResizeObserver
})
afterEach(() => {
  cleanup()
  globalThis.ResizeObserver = originalObserver
})

function Harness({
  content = "first",
  resetKey = "conversation-1",
  enabled = true,
  pageFallback = false,
}) {
  const { scrollRef, followOutput } = useAutoFollowScroll({
    content,
    resetKey,
    enabled,
    pageFallback,
  })
  return (
    <>
      <div ref={scrollRef} data-testid="output" tabIndex={0}>
        <div>{content}</div>
      </div>
      <button onClick={followOutput}>Follow output</button>
    </>
  )
}

function metrics(element: HTMLElement) {
  let height = 1000
  let top = 800
  Object.defineProperties(element, {
    scrollHeight: { configurable: true, get: () => height },
    clientHeight: { configurable: true, value: 200 },
    scrollTop: {
      configurable: true,
      get: () => top,
      set: (value: number) => {
        top = Math.max(0, Math.min(value, height - 200))
      },
    },
  })
  return {
    grow: () => {
      height += 100
    },
    top: () => top,
  }
}

test("small upward scrollbar movement pauses following even inside the bottom threshold", () => {
  const view = render(<Harness />)
  const host = screen.getByTestId("output")
  const scroll = metrics(host)
  fireEvent.scroll(host)
  host.scrollTop -= 10
  fireEvent.scroll(host)
  scroll.grow()
  view.rerender(<Harness content="second" />)
  expect(scroll.top()).toBe(790)
  host.scrollTop = host.scrollHeight - host.clientHeight
  fireEvent.scroll(host)
  scroll.grow()
  view.rerender(<Harness content="third" />)
  expect(scroll.top()).toBe(1000)
})

test.each(["wheel", "touch", "keyboard"])(
  "%s input pauses before output, animation frames, or resize callbacks can move the viewport",
  async (input) => {
    const view = render(<Harness />)
    const host = screen.getByTestId("output")
    const scroll = metrics(host)
    fireEvent.scroll(host)
    if (input === "wheel") fireEvent.wheel(host, { deltaY: -20 })
    if (input === "keyboard") fireEvent.keyDown(host, { key: "PageUp" })
    if (input === "touch") {
      fireEvent.touchStart(host, { touches: [{ clientY: 100 }] })
      fireEvent.touchMove(host, { touches: [{ clientY: 140 }] })
    }
    scroll.grow()
    view.rerender(<Harness content="second" />)
    await act(async () => {
      ResizeObserverStub.instances.at(-1)!.emit()
      await new Promise((resolve) => setTimeout(resolve, 30))
    })
    expect(scroll.top()).toBe(800)
    fireEvent.click(screen.getByRole("button", { name: "Follow output" }))
    expect(scroll.top()).toBe(900)
    scroll.grow()
    act(() => ResizeObserverStub.instances.at(-1)!.emit())
    expect(scroll.top()).toBe(1000)
  }
)

test("switching conversations resumes following without carrying the previous reading position", () => {
  const view = render(<Harness />)
  const host = screen.getByTestId("output")
  const scroll = metrics(host)
  fireEvent.scroll(host)
  host.scrollTop = 100
  fireEvent.scroll(host)
  scroll.grow()
  view.rerender(
    <Harness content="new conversation" resetKey="conversation-2" />
  )
  expect(scroll.top()).toBe(900)
})

test("page scrolling pauses and resumes when the page is the output scroll host", () => {
  const view = render(<Harness pageFallback />)
  const host = screen.getByTestId("output")
  Object.defineProperty(host, "getClientRects", {
    configurable: true,
    value: () => [{}],
  })
  const documentHost = document.scrollingElement as HTMLElement
  const descriptors = ["scrollHeight", "clientHeight", "scrollTop"].map(
    (key) => [key, Object.getOwnPropertyDescriptor(documentHost, key)] as const
  )
  const scroll = metrics(documentHost)
  try {
    view.rerender(<Harness pageFallback content="second" />)
    expect(scroll.top()).toBe(800)
    documentHost.scrollTop = 100
    fireEvent.scroll(window)
    scroll.grow()
    view.rerender(<Harness pageFallback content="third" />)
    expect(scroll.top()).toBe(100)
    documentHost.scrollTop = 900
    fireEvent.scroll(window)
    scroll.grow()
    view.rerender(<Harness pageFallback content="fourth" />)
    expect(scroll.top()).toBe(1000)
  } finally {
    for (const [key, descriptor] of descriptors) {
      if (descriptor) Object.defineProperty(documentHost, key, descriptor)
      else delete (documentHost as unknown as Record<string, unknown>)[key]
    }
  }
})

test("closed output panes stay still and release their observers", () => {
  const view = render(<Harness enabled={false} />)
  const host = screen.getByTestId("output")
  const scroll = metrics(host)
  scroll.grow()
  view.rerender(<Harness enabled={false} content="second" />)
  expect(scroll.top()).toBe(800)
  view.rerender(<Harness content="second" />)
  expect(scroll.top()).toBe(900)
  view.unmount()
  expect(
    ResizeObserverStub.instances.every((observer) => observer.disconnected)
  ).toBe(true)
})
