import { renderAsync } from "docx-preview"
import type { Viewer } from "../preview-protocol"

export async function openWord(
  container: HTMLElement,
  bytes: ArrayBuffer
): Promise<Viewer> {
  const content = document.createElement("div")
  content.style.width = "max-content"
  container.append(content)
  await renderAsync(bytes, content, undefined, {
    inWrapper: true,
    breakPages: true,
    ignoreLastRenderedPageBreak: false,
    renderAltChunks: false,
    useBase64URL: true,
  })
  const width = Math.max(content.scrollWidth, 1)
  return {
    metadata: { pageCount: 0, sheets: [], truncated: false },
    render({ zoom }) {
      content.style.zoom = String(
        Math.min(1, (container.clientWidth - 32) / width) * zoom
      )
    },
    destroy() {
      content.remove()
    },
  }
}
