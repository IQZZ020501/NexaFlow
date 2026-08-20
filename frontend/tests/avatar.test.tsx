/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"

import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from "@/components/ui/avatar"
import { cleanup, render, screen } from "./helpers/dom"

const originalImage = window.Image

afterEach(() => {
  cleanup()
  Object.defineProperty(window, "Image", {
    value: originalImage,
    configurable: true,
  })
})

function stubLoadedImage() {
  class FakeImage {
    complete = true
    naturalWidth = 100
    naturalHeight = 100
    src = ""
    referrerPolicy = ""
    crossOrigin: string | null = null
    addEventListener() {}
    removeEventListener() {}
  }
  Object.defineProperty(window, "Image", {
    value: FakeImage,
    configurable: true,
  })
}

describe("Avatar", () => {
  test("renders the image once it loads and merges custom classes", () => {
    stubLoadedImage()
    const { container } = render(
      <Avatar className="size-12">
        <AvatarImage
          src="https://example.com/avatar.png"
          alt="Profile"
          className="rounded"
        />
        <AvatarFallback>PF</AvatarFallback>
      </Avatar>
    )

    const image = container.querySelector(
      '[data-slot="avatar-image"]'
    ) as HTMLImageElement
    expect(image).toBeTruthy()
    expect(image.getAttribute("src")).toBe("https://example.com/avatar.png")
    expect(image.getAttribute("alt")).toBe("Profile")
    expect(image.className).toContain("aspect-square size-full")
    expect(image.className).toContain("rounded")
    expect(screen.queryByText("PF")).toBeNull()

    const root = container.querySelector('[data-slot="avatar"]')
    expect(root?.className).toContain(
      "relative flex shrink-0 overflow-hidden rounded-full"
    )
    // tailwind-merge keeps the custom size over the default size-8.
    expect(root?.className).toContain("size-12")
    expect(root?.className).not.toContain("size-8")
  })

  test("shows name-derived initials as the fallback while the image loads", () => {
    const { container } = render(
      <Avatar>
        <AvatarImage src="https://example.com/avatar.png" alt="Ada Lovelace" />
        <AvatarFallback className="text-base">AL</AvatarFallback>
      </Avatar>
    )

    const fallback = screen.getByText("AL")
    expect(fallback).toBeTruthy()
    expect(fallback.className).toContain(
      "flex size-full items-center justify-center rounded-full bg-muted"
    )
    expect(fallback.className).toContain("font-medium")
    // tailwind-merge keeps the custom font size over the default.
    expect(fallback.className).toContain("text-base")
    expect(
      container.querySelector('[data-slot="avatar-image"]')
    ).toBeNull()
  })

  test("renders the fallback without an image source", () => {
    render(
      <Avatar>
        <AvatarFallback>JD</AvatarFallback>
      </Avatar>
    )

    expect(screen.getByText("JD")).toBeTruthy()
    expect(screen.queryByRole("img")).toBeNull()
  })
})
