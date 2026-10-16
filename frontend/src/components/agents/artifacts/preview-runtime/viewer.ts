import {
  validateOfficeArchive,
  type PreviewCommand,
  type PreviewPosition,
  type Viewer,
} from "../preview-protocol"

const channel = document.getElementById("viewer")!.dataset.channel!
const container = document.getElementById("preview")!
const assetBase = new URL("./", import.meta.url).href
let viewer: Viewer | undefined
let opened = false
let rendering = false
let pending = false
let position: PreviewPosition = { page: 1, sheet: 0, zoom: 1 }

function notify(type: string, value: object = {}) {
  parent.postMessage({ channel, type, ...value }, "*")
}

async function render() {
  if (!viewer) return
  pending = true
  if (rendering) return
  rendering = true
  try {
    while (pending) {
      pending = false
      await viewer.render(position)
    }
    notify("rendered", { metadata: viewer.metadata })
  } catch {
    notify("failed")
  } finally {
    rendering = false
  }
}

window.addEventListener(
  "message",
  async (event: MessageEvent<PreviewCommand>) => {
    if (event.source !== parent || event.data?.channel !== channel) return
    const command = event.data
    if (command.type === "open" && !opened) {
      opened = true
      try {
        if (
          !(command.bytes instanceof ArrayBuffer) ||
          command.bytes.byteLength > 5 * 1024 * 1024
        )
          throw new Error("Invalid file")
        if (command.format !== "pdf") validateOfficeArchive(command.bytes)
        switch (command.format) {
          case "pdf":
            viewer = await (
              await import("./pdf")
            ).openPdf(container, command.bytes, assetBase)
            break
          case "docx":
            viewer = await (
              await import("./word")
            ).openWord(container, command.bytes)
            break
          case "xlsx":
            viewer = await (
              await import("./spreadsheet")
            ).openSpreadsheet(container, command.bytes, command.emptyLabel)
            break
          case "pptx":
            viewer = await (
              await import("./presentation")
            ).openPresentation(container, command.bytes)
            break
          default:
            throw new Error("Unsupported file")
        }
        await render()
      } catch {
        notify("failed")
      }
    } else if (command.type === "position" && viewer) {
      const next = command.position
      if (
        !next ||
        !Number.isInteger(next.page) ||
        !Number.isInteger(next.sheet) ||
        !Number.isFinite(next.zoom)
      )
        return
      position = {
        page: Math.max(1, Math.min(viewer.metadata.pageCount || 1, next.page)),
        sheet: Math.max(
          0,
          Math.min(viewer.metadata.sheets.length - 1, next.sheet)
        ),
        zoom: Math.max(0.5, Math.min(2, next.zoom)),
      }
      await render()
    }
  }
)
// Disable document links, including links created by Office renderers.
document.addEventListener(
  "click",
  (event) => {
    if (event.target instanceof Element && event.target.closest("a"))
      event.preventDefault()
  },
  true
)
window.addEventListener("resize", () => void render())
window.addEventListener("pagehide", () => viewer?.destroy())
notify("ready")
