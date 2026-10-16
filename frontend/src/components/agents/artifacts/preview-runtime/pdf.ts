import {
  getDocument,
  GlobalWorkerOptions,
  type PDFDocumentProxy,
} from "pdfjs-dist"
import type { Viewer } from "../preview-protocol"

export async function openPdf(
  container: HTMLElement,
  bytes: ArrayBuffer,
  assetBase: string
): Promise<Viewer> {
  const workerResponse = await fetch(`${assetBase}pdf.worker.js`, {
    credentials: "omit",
  })
  if (!workerResponse.ok) throw new Error("PDF worker unavailable")
  const workerUrl = URL.createObjectURL(
    new Blob([await workerResponse.text()], { type: "text/javascript" })
  )
  const worker = new Worker(workerUrl)
  GlobalWorkerOptions.workerPort = worker
  function releaseWorker() {
    worker.terminate()
    URL.revokeObjectURL(workerUrl)
    GlobalWorkerOptions.workerPort = null
  }
  const loading = getDocument({
    data: new Uint8Array(bytes),
    enableXfa: false,
    cMapUrl: `${assetBase}cmaps/`,
    cMapPacked: true,
    standardFontDataUrl: `${assetBase}standard_fonts/`,
    wasmUrl: `${assetBase}wasm/`,
    maxImageSize: 16 * 1024 * 1024,
    canvasMaxAreaInBytes: 32 * 1024 * 1024,
  })
  let document: PDFDocumentProxy
  try {
    document = await loading.promise
  } catch (error) {
    await loading.destroy()
    releaseWorker()
    throw error
  }
  const canvas = window.document.createElement("canvas")
  canvas.setAttribute("aria-hidden", "true")
  const text = window.document.createElement("div")
  text.style.cssText =
    "position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)"
  container.append(canvas, text)
  return {
    metadata: { pageCount: document.numPages, sheets: [], truncated: false },
    async render({ page, zoom }) {
      const current = await document.getPage(page)
      const base = current.getViewport({ scale: 1 })
      const scale =
        Math.min(2, Math.max(0.1, (container.clientWidth - 32) / base.width)) *
        zoom
      const viewport = current.getViewport({ scale })
      const ratio = Math.min(
        window.devicePixelRatio || 1,
        2,
        4096 / Math.max(viewport.width, viewport.height)
      )
      canvas.width = Math.ceil(viewport.width * ratio)
      canvas.height = Math.ceil(viewport.height * ratio)
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`
      await current.render({
        canvas,
        viewport,
        transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
      }).promise
      const content = await current.getTextContent()
      text.textContent = content.items
        .map((item) => ("str" in item ? item.str : ""))
        .join(" ")
      current.cleanup()
    },
    destroy() {
      void loading.destroy().finally(releaseWorker)
    },
  }
}
