import { init } from "pptx-preview"
import type { Viewer } from "../preview-protocol"

export async function openPresentation(
  container: HTMLElement,
  bytes: ArrayBuffer
): Promise<Viewer> {
  const content = document.createElement("div")
  content.style.width = "960px"
  content.style.margin = "auto"
  container.append(content)
  const presentation = init(content, { width: 960, mode: "slide" })
  try {
    await presentation.load(bytes)
    if (!presentation.slideCount) throw new Error("Empty presentation")
  } catch (error) {
    presentation.destroy()
    throw error
  }
  let currentPage = 0
  return {
    metadata: {
      pageCount: presentation.slideCount,
      sheets: [],
      truncated: false,
    },
    render({ page, zoom }) {
      if (page !== currentPage) {
        presentation.renderSingleSlide(page - 1)
        currentPage = page
      }
      content.style.zoom = String(
        Math.min(1, (container.clientWidth - 32) / 960) * zoom
      )
    },
    destroy() {
      presentation.destroy()
    },
  }
}
