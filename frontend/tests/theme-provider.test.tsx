/* @jsxImportSource react */
import { afterEach, describe, expect, spyOn, test } from "bun:test"
import { act } from "@testing-library/react"

import { ThemeProvider, useTheme } from "@/contexts/theme-provider"
import { cleanup, fireEvent, render, screen } from "./helpers/dom"

/** Consumer child exposing the theme and appearance state with their controls. */
function Probe() {
  const {
    theme,
    setTheme,
    palette,
    setPalette,
    font,
    setFont,
    radius,
    setRadius,
    density,
    setDensity,
    sidebar,
    setSidebar,
    layout,
    setLayout,
    contentWidth,
    setContentWidth,
  } = useTheme()
  return (
    <div>
      <output data-testid="theme-value">{theme}</output>
      <output data-testid="palette-value">{palette}</output>
      <output data-testid="font-value">{font}</output>
      <output data-testid="radius-value">{radius}</output>
      <output data-testid="density-value">{density}</output>
      <output data-testid="sidebar-value">{sidebar}</output>
      <output data-testid="layout-value">{layout}</output>
      <output data-testid="content-width-value">{contentWidth}</output>
      <button onClick={() => setTheme("light")}>set-light</button>
      <button onClick={() => setTheme("dark")}>set-dark</button>
      <button onClick={() => setTheme("system")}>set-system</button>
      <button onClick={() => setPalette("ocean")}>set-ocean</button>
      <button onClick={() => setPalette("amber")}>set-amber</button>
      <button onClick={() => setFont("serif")}>set-serif</button>
      <button onClick={() => setRadius("0.3")}>set-radius</button>
      <button onClick={() => setDensity("large")}>set-large</button>
      <button onClick={() => setSidebar("floating")}>set-floating</button>
      <button onClick={() => setLayout("full")}>set-full</button>
      <button onClick={() => setContentWidth("centered")}>set-centered</button>
    </div>
  )
}

type MediaQueryListMock = MediaQueryList & {
  dispatchChange(matches: boolean): void
  listenerCount(): number
}

/** Installs a controllable matchMedia stub so the system color scheme is deterministic. */
function installMatchMedia(initialMatches: boolean): MediaQueryListMock {
  const listeners = new Set<EventListener>()
  const state: { matches: boolean } = { matches: initialMatches }
  const base: MediaQueryList = {
    media: "(prefers-color-scheme: dark)",
    get matches() {
      return state.matches
    },
    onchange: null,
    addEventListener: (
      type: string,
      callback: EventListenerOrEventListenerObject | null
    ) => {
      if (type === "change" && typeof callback === "function") {
        listeners.add(callback as EventListener)
      }
    },
    removeEventListener: (
      type: string,
      callback: EventListenerOrEventListenerObject | null
    ) => {
      if (type === "change") {
        listeners.delete(callback as EventListener)
      }
    },
    dispatchEvent: () => true,
    addListener: () => undefined,
    removeListener: () => undefined,
  }
  const mock = Object.assign(base, {
    dispatchChange(next: boolean) {
      state.matches = next
      const event = { matches: next, media: base.media } as MediaQueryListEvent
      for (const listener of [...listeners]) {
        listener(event)
      }
    },
    listenerCount: () => listeners.size,
  })
  window.matchMedia = () => mock
  return mock
}

/** Queues requestAnimationFrame callbacks instead of firing them. */
function stubRequestAnimationFrame() {
  const queue: FrameRequestCallback[] = []
  window.requestAnimationFrame = (callback: FrameRequestCallback) => {
    queue.push(callback)
    return queue.length
  }
  return {
    flush() {
      while (queue.length > 0) {
        const callback = queue.shift()
        callback?.(0)
      }
    },
    size: () => queue.length,
  }
}

function transitionStyleCount() {
  return [...document.head.querySelectorAll("style")].filter((style) =>
    style.textContent?.includes("transition:none")
  ).length
}

function dispatchKeyDown(init: KeyboardEventInit) {
  act(() => {
    window.dispatchEvent(new KeyboardEvent("keydown", init))
  })
}

function dispatchStorage(
  key: string | null,
  newValue: string | null,
  storageArea: Storage | null
) {
  act(() => {
    window.dispatchEvent(
      new StorageEvent("storage", { key, newValue, storageArea })
    )
  })
}

const originalMatchMedia = window.matchMedia
const originalRequestAnimationFrame = window.requestAnimationFrame
const detachedNodes: HTMLElement[] = []

afterEach(() => {
  cleanup()
  window.matchMedia = originalMatchMedia
  window.requestAnimationFrame = originalRequestAnimationFrame
  localStorage.clear()
  const root = document.documentElement
  root.classList.remove("light", "dark")
  root.removeAttribute("data-palette")
  root.removeAttribute("data-font")
  root.removeAttribute("data-radius")
  root.removeAttribute("data-density")
  root.removeAttribute("data-sidebar")
  root.removeAttribute("data-layout")
  root.removeAttribute("data-content-width")
  root.removeAttribute("style")
  for (const style of [...document.head.querySelectorAll("style")]) {
    if (style.textContent?.includes("transition:none")) {
      style.remove()
    }
  }
  while (detachedNodes.length > 0) {
    detachedNodes.pop()?.remove()
  }
})

describe("ThemeProvider", () => {
  test("applies the dark default theme to the document root", () => {
    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    expect(screen.getByTestId("theme-value").textContent).toBe("dark")
    const root = document.documentElement
    expect(root.classList.contains("dark")).toBe(true)
    expect(root.classList.contains("light")).toBe(false)
    expect(root.style.colorScheme).toBe("dark")
    expect(root.style.backgroundColor).toBe("var(--background)")
  })

  test("applies the light default theme to the document root", () => {
    render(
      <ThemeProvider defaultTheme="light">
        <Probe />
      </ThemeProvider>
    )

    expect(screen.getByTestId("theme-value").textContent).toBe("light")
    expect(document.documentElement.classList.contains("light")).toBe(true)
    expect(document.documentElement.style.colorScheme).toBe("light")
  })

  test("resolves the system theme to dark when the OS prefers dark", () => {
    installMatchMedia(true)

    render(
      <ThemeProvider defaultTheme="system">
        <Probe />
      </ThemeProvider>
    )

    expect(screen.getByTestId("theme-value").textContent).toBe("system")
    const root = document.documentElement
    expect(root.classList.contains("dark")).toBe(true)
    expect(root.style.colorScheme).toBe("dark")
  })

  test("resolves the system theme to light when the OS prefers light", () => {
    installMatchMedia(false)

    render(
      <ThemeProvider defaultTheme="system">
        <Probe />
      </ThemeProvider>
    )

    expect(document.documentElement.classList.contains("light")).toBe(true)
  })

  test("reads a stored theme from local storage", () => {
    localStorage.setItem("theme", "light")

    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    expect(screen.getByTestId("theme-value").textContent).toBe("light")
  })

  test("falls back to the default theme when the stored value is invalid", () => {
    localStorage.setItem("theme", "neon")

    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    expect(screen.getByTestId("theme-value").textContent).toBe("dark")
  })

  test("uses the default theme when nothing is stored", () => {
    render(
      <ThemeProvider defaultTheme="light">
        <Probe />
      </ThemeProvider>
    )

    expect(screen.getByTestId("theme-value").textContent).toBe("light")
  })

  test("falls back to the default theme when storage access throws", () => {
    const ownDesc = Object.getOwnPropertyDescriptor(window, "localStorage")
    Object.defineProperty(window, "localStorage", {
      value: undefined,
      configurable: true,
    })
    try {
      render(
        <ThemeProvider defaultTheme="dark">
          <Probe />
        </ThemeProvider>
      )
      expect(screen.getByTestId("theme-value").textContent).toBe("dark")
    } finally {
      if (ownDesc) {
        Object.defineProperty(window, "localStorage", ownDesc)
      } else {
        delete (window as { localStorage?: unknown }).localStorage
      }
    }
  })

  test("setTheme persists the choice and updates the document", () => {
    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    fireEvent.click(screen.getByRole("button", { name: "set-light" }))
    expect(localStorage.getItem("theme")).toBe("light")
    expect(screen.getByTestId("theme-value").textContent).toBe("light")
    const root = document.documentElement
    expect(root.classList.contains("light")).toBe(true)
    expect(root.classList.contains("dark")).toBe(false)
    expect(root.style.colorScheme).toBe("light")

    fireEvent.click(screen.getByRole("button", { name: "set-dark" }))
    expect(localStorage.getItem("theme")).toBe("dark")
    expect(screen.getByTestId("theme-value").textContent).toBe("dark")
    expect(root.classList.contains("dark")).toBe(true)
    expect(root.style.colorScheme).toBe("dark")

    fireEvent.click(screen.getByRole("button", { name: "set-system" }))
    expect(localStorage.getItem("theme")).toBe("system")
    expect(screen.getByTestId("theme-value").textContent).toBe("system")
  })

  test("uses a custom storage key for persistence and storage events", () => {
    render(
      <ThemeProvider defaultTheme="dark" storageKey="appearance">
        <Probe />
      </ThemeProvider>
    )

    fireEvent.click(screen.getByRole("button", { name: "set-light" }))
    expect(localStorage.getItem("appearance")).toBe("light")
    expect(localStorage.getItem("theme")).toBeNull()

    dispatchStorage("appearance", "system", localStorage)
    expect(screen.getByTestId("theme-value").textContent).toBe("system")

    // Events for a different key are ignored.
    dispatchStorage("theme", "dark", localStorage)
    expect(screen.getByTestId("theme-value").textContent).toBe("system")
  })

  test("temporarily disables transitions on theme change by default", () => {
    const raf = stubRequestAnimationFrame()

    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    expect(transitionStyleCount()).toBe(1)
    expect(raf.size()).toBe(1)

    raf.flush()

    expect(raf.size()).toBe(0)
    expect(transitionStyleCount()).toBe(0)
  })

  test("skips the transition override when disableTransitionOnChange is false", () => {
    render(
      <ThemeProvider defaultTheme="dark" disableTransitionOnChange={false}>
        <Probe />
      </ThemeProvider>
    )

    expect(transitionStyleCount()).toBe(0)
    expect(document.documentElement.classList.contains("dark")).toBe(true)
  })

  test("re-applies the system theme when the color scheme preference changes", () => {
    const mediaQuery = installMatchMedia(false)

    render(
      <ThemeProvider defaultTheme="system">
        <Probe />
      </ThemeProvider>
    )

    expect(document.documentElement.classList.contains("light")).toBe(true)
    expect(mediaQuery.listenerCount()).toBe(1)

    mediaQuery.dispatchChange(true)
    expect(document.documentElement.classList.contains("dark")).toBe(true)
    expect(document.documentElement.style.colorScheme).toBe("dark")

    mediaQuery.dispatchChange(false)
    expect(document.documentElement.classList.contains("light")).toBe(true)
  })

  test("does not register a media query listener for a fixed theme", () => {
    const mediaQuery = installMatchMedia(true)

    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    expect(mediaQuery.listenerCount()).toBe(0)
  })

  test("removes the media query listener on unmount", () => {
    const mediaQuery = installMatchMedia(false)
    const { unmount } = render(
      <ThemeProvider defaultTheme="system">
        <Probe />
      </ThemeProvider>
    )

    expect(mediaQuery.listenerCount()).toBe(1)
    unmount()
    expect(mediaQuery.listenerCount()).toBe(0)
  })

  test("toggles dark to light with the d key and persists the change", () => {
    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    dispatchKeyDown({ key: "d" })
    expect(screen.getByTestId("theme-value").textContent).toBe("light")
    expect(localStorage.getItem("theme")).toBe("light")

    dispatchKeyDown({ key: "d" })
    expect(screen.getByTestId("theme-value").textContent).toBe("dark")
    expect(localStorage.getItem("theme")).toBe("dark")
  })

  test("handles the uppercase D shortcut", () => {
    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    dispatchKeyDown({ key: "D" })
    expect(screen.getByTestId("theme-value").textContent).toBe("light")
  })

  test("ignores keys other than d", () => {
    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    dispatchKeyDown({ key: "x" })
    expect(screen.getByTestId("theme-value").textContent).toBe("dark")
  })

  test("toggles system to the opposite of the OS preference and back", () => {
    installMatchMedia(true)

    render(
      <ThemeProvider defaultTheme="system">
        <Probe />
      </ThemeProvider>
    )

    // System resolves to dark, so the shortcut moves to light.
    dispatchKeyDown({ key: "d" })
    expect(screen.getByTestId("theme-value").textContent).toBe("light")
    expect(localStorage.getItem("theme")).toBe("light")

    dispatchKeyDown({ key: "d" })
    expect(screen.getByTestId("theme-value").textContent).toBe("dark")

    dispatchKeyDown({ key: "d" })
    expect(screen.getByTestId("theme-value").textContent).toBe("light")
  })

  test("skips the shortcut when the OS prefers light and the theme is system", () => {
    installMatchMedia(false)

    render(
      <ThemeProvider defaultTheme="system">
        <Probe />
      </ThemeProvider>
    )

    dispatchKeyDown({ key: "d" })
    expect(screen.getByTestId("theme-value").textContent).toBe("dark")
  })

  test("skips the shortcut when a modifier key is held", () => {
    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    dispatchKeyDown({ key: "d", metaKey: true })
    dispatchKeyDown({ key: "d", ctrlKey: true })
    dispatchKeyDown({ key: "d", altKey: true })

    expect(screen.getByTestId("theme-value").textContent).toBe("dark")
    expect(localStorage.getItem("theme")).toBeNull()
  })

  test("skips the shortcut on repeated keydown events", () => {
    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    dispatchKeyDown({ key: "d", repeat: true })
    expect(screen.getByTestId("theme-value").textContent).toBe("dark")
  })

  test("skips the shortcut when the target is an editable field", () => {
    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    const input = document.createElement("input")
    document.body.appendChild(input)
    detachedNodes.push(input)
    act(() => {
      input.dispatchEvent(
        new KeyboardEvent("keydown", { key: "d", bubbles: true })
      )
    })

    const textarea = document.createElement("textarea")
    document.body.appendChild(textarea)
    detachedNodes.push(textarea)
    act(() => {
      textarea.dispatchEvent(
        new KeyboardEvent("keydown", { key: "d", bubbles: true })
      )
    })

    const editable = document.createElement("div")
    editable.contentEditable = "true"
    document.body.appendChild(editable)
    detachedNodes.push(editable)
    act(() => {
      editable.dispatchEvent(
        new KeyboardEvent("keydown", { key: "d", bubbles: true })
      )
    })

    expect(screen.getByTestId("theme-value").textContent).toBe("dark")
    expect(localStorage.getItem("theme")).toBeNull()
  })

  test("still toggles when the target is a non-editable element", () => {
    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    const button = document.createElement("button")
    document.body.appendChild(button)
    detachedNodes.push(button)
    act(() => {
      button.dispatchEvent(
        new KeyboardEvent("keydown", { key: "d", bubbles: true })
      )
    })

    expect(screen.getByTestId("theme-value").textContent).toBe("light")
  })

  test("syncs a valid theme from a storage event", () => {
    render(
      <ThemeProvider defaultTheme="light">
        <Probe />
      </ThemeProvider>
    )

    dispatchStorage("theme", "dark", localStorage)
    expect(screen.getByTestId("theme-value").textContent).toBe("dark")
    expect(document.documentElement.classList.contains("dark")).toBe(true)
  })

  test("syncs the system theme from a storage event and resolves it", () => {
    installMatchMedia(true)

    render(
      <ThemeProvider defaultTheme="light">
        <Probe />
      </ThemeProvider>
    )

    dispatchStorage("theme", "system", localStorage)
    expect(screen.getByTestId("theme-value").textContent).toBe("system")
    expect(document.documentElement.classList.contains("dark")).toBe(true)
  })

  test("falls back to the default theme on an invalid storage event value", () => {
    render(
      <ThemeProvider defaultTheme="light">
        <Probe />
      </ThemeProvider>
    )

    dispatchStorage("theme", "neon", localStorage)
    expect(screen.getByTestId("theme-value").textContent).toBe("light")

    dispatchStorage("theme", null, localStorage)
    expect(screen.getByTestId("theme-value").textContent).toBe("light")
  })

  test("ignores storage events for other storage areas", () => {
    render(
      <ThemeProvider defaultTheme="light">
        <Probe />
      </ThemeProvider>
    )

    dispatchStorage("theme", "dark", null)
    expect(screen.getByTestId("theme-value").textContent).toBe("light")
  })

  test("removes the keydown and storage listeners on unmount", () => {
    const addEventListener = spyOn(window, "addEventListener")
    const removeEventListener = spyOn(window, "removeEventListener")
    try {
      const { unmount } = render(
        <ThemeProvider defaultTheme="dark">
          <Probe />
        </ThemeProvider>
      )
      const keydownListener = addEventListener.mock.calls.find(
        ([type]) => type === "keydown"
      )?.[1]
      const storageListener = addEventListener.mock.calls.find(
        ([type]) => type === "storage"
      )?.[1]
      expect(keydownListener).toBeTruthy()
      expect(storageListener).toBeTruthy()

      unmount()

      expect(removeEventListener).toHaveBeenCalledWith(
        "keydown",
        keydownListener
      )
      expect(removeEventListener).toHaveBeenCalledWith(
        "storage",
        storageListener
      )
    } finally {
      addEventListener.mockRestore()
      removeEventListener.mockRestore()
    }
  })

  test("throws when useTheme is used outside a provider", () => {
    expect(() => render(<Probe />)).toThrow(
      "useTheme must be used within a ThemeProvider"
    )
  })
})

describe("ThemeProvider palettes", () => {
  test("applies the default palette to the document root", () => {
    render(
      <ThemeProvider defaultTheme="light">
        <Probe />
      </ThemeProvider>
    )

    expect(screen.getByTestId("palette-value").textContent).toBe("neutral")
    expect(document.documentElement.dataset.palette).toBe("neutral")
  })

  test("reads a stored palette from local storage", () => {
    localStorage.setItem("palette", "violet")

    render(
      <ThemeProvider defaultTheme="light">
        <Probe />
      </ThemeProvider>
    )

    expect(screen.getByTestId("palette-value").textContent).toBe("violet")
    expect(document.documentElement.dataset.palette).toBe("violet")
  })

  test("falls back to the default palette when the stored value is unsupported", () => {
    localStorage.setItem("palette", "neon")

    render(
      <ThemeProvider defaultTheme="light" defaultPalette="forest">
        <Probe />
      </ThemeProvider>
    )

    expect(screen.getByTestId("palette-value").textContent).toBe("forest")
    expect(document.documentElement.dataset.palette).toBe("forest")
  })

  test("setPalette persists the choice without changing the color scheme", () => {
    render(
      <ThemeProvider defaultTheme="dark">
        <Probe />
      </ThemeProvider>
    )

    fireEvent.click(screen.getByRole("button", { name: "set-ocean" }))
    expect(localStorage.getItem("palette")).toBe("ocean")
    expect(document.documentElement.dataset.palette).toBe("ocean")
    expect(document.documentElement.classList.contains("dark")).toBe(true)

    fireEvent.click(screen.getByRole("button", { name: "set-light" }))
    expect(document.documentElement.dataset.palette).toBe("ocean")
    expect(document.documentElement.classList.contains("light")).toBe(true)
  })

  test("keeps the palette and the theme in separate storage keys", () => {
    render(
      <ThemeProvider defaultTheme="light" paletteStorageKey="skin">
        <Probe />
      </ThemeProvider>
    )

    fireEvent.click(screen.getByRole("button", { name: "set-amber" }))
    expect(localStorage.getItem("skin")).toBe("amber")
    expect(localStorage.getItem("palette")).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "set-dark" }))
    expect(localStorage.getItem("theme")).toBe("dark")
    expect(localStorage.getItem("skin")).toBe("amber")
  })

  test("syncs a palette from its storage event and ignores other keys", () => {
    render(
      <ThemeProvider defaultTheme="light">
        <Probe />
      </ThemeProvider>
    )

    dispatchStorage("palette", "amber", localStorage)
    expect(screen.getByTestId("palette-value").textContent).toBe("amber")
    expect(document.documentElement.dataset.palette).toBe("amber")

    dispatchStorage("theme", "dark", localStorage)
    expect(document.documentElement.dataset.palette).toBe("amber")

    dispatchStorage("palette", "neon", localStorage)
    expect(document.documentElement.dataset.palette).toBe("neutral")
  })
})

describe("ThemeProvider appearance axes", () => {
  test("applies and persists font, radius, density, sidebar, layout, and width", () => {
    render(
      <ThemeProvider defaultTheme="light">
        <Probe />
      </ThemeProvider>
    )

    fireEvent.click(screen.getByRole("button", { name: "set-serif" }))
    fireEvent.click(screen.getByRole("button", { name: "set-radius" }))
    fireEvent.click(screen.getByRole("button", { name: "set-large" }))
    fireEvent.click(screen.getByRole("button", { name: "set-floating" }))
    fireEvent.click(screen.getByRole("button", { name: "set-full" }))
    fireEvent.click(screen.getByRole("button", { name: "set-centered" }))

    const root = document.documentElement
    expect(screen.getByTestId("font-value").textContent).toBe("serif")
    expect(screen.getByTestId("radius-value").textContent).toBe("0.3")
    expect(screen.getByTestId("density-value").textContent).toBe("large")
    expect(screen.getByTestId("sidebar-value").textContent).toBe("floating")
    expect(screen.getByTestId("layout-value").textContent).toBe("full")
    expect(screen.getByTestId("content-width-value").textContent).toBe("centered")
    expect(root.dataset.font).toBe("serif")
    expect(root.dataset.radius).toBe("0.3")
    expect(root.dataset.density).toBe("large")
    expect(root.dataset.sidebar).toBe("floating")
    expect(root.dataset.layout).toBe("full")
    expect(root.dataset.contentWidth).toBe("centered")
    expect(localStorage.getItem("font")).toBe("serif")
    expect(localStorage.getItem("radius")).toBe("0.3")
    expect(localStorage.getItem("density")).toBe("large")
    expect(localStorage.getItem("sidebar")).toBe("floating")
    expect(localStorage.getItem("layout")).toBe("full")
    expect(localStorage.getItem("content-width")).toBe("centered")
  })

  test("reads stored appearance axes and rejects unsupported values", () => {
    localStorage.setItem("font", "serif")
    localStorage.setItem("radius", "0.5")
    localStorage.setItem("density", "compact")
    localStorage.setItem("sidebar", "sidebar")
    localStorage.setItem("layout", "compact")
    localStorage.setItem("content-width", "centered")

    render(
      <ThemeProvider defaultTheme="light">
        <Probe />
      </ThemeProvider>
    )

    expect(screen.getByTestId("font-value").textContent).toBe("serif")
    expect(screen.getByTestId("radius-value").textContent).toBe("0.5")
    expect(screen.getByTestId("density-value").textContent).toBe("compact")
    expect(screen.getByTestId("sidebar-value").textContent).toBe("sidebar")
    expect(screen.getByTestId("layout-value").textContent).toBe("compact")
    expect(screen.getByTestId("content-width-value").textContent).toBe("centered")

    localStorage.setItem("font", "comic")
    dispatchStorage("font", "comic", localStorage)
    expect(screen.getByTestId("font-value").textContent).toBe("auto")
    expect(document.documentElement.dataset.font).toBe("auto")
  })
})
