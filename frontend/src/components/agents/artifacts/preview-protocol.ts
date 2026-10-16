import type { PreviewFormat } from "@/lib/agent-artifacts"

export type OfficePreviewFormat = Exclude<PreviewFormat, "html">
export type PreviewPosition = { page: number; sheet: number; zoom: number }
export type PreviewMetadata = {
  pageCount: number
  sheets: string[]
  truncated: boolean
}
export type Viewer = {
  metadata: PreviewMetadata
  render(position: PreviewPosition): Promise<void> | void
  destroy(): void
}

export type PreviewCommand =
  | {
      type: "open"
      channel: string
      format: OfficePreviewFormat
      bytes: ArrayBuffer
      emptyLabel: string
    }
  | { type: "position"; channel: string; position: PreviewPosition }

/** The viewer receives bytes, never a bearer URL or host credentials. */
export function filePreviewDocument(origin: string, channel: string) {
  const assetBase = `${new URL(origin).origin}/file-preview/`
  const policy = [
    "default-src 'none'",
    `script-src ${assetBase} blob: 'wasm-unsafe-eval'`,
    "style-src 'unsafe-inline'",
    "img-src data: blob:",
    `font-src ${assetBase} data: blob:`,
    `connect-src ${assetBase} blob:`,
    `worker-src ${assetBase} blob:`,
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
  ].join("; ")
  if (!/^[a-zA-Z0-9-]+$/.test(channel))
    throw new Error("Invalid preview channel")
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${policy}"><meta name="referrer" content="no-referrer"><meta name="viewport" content="width=device-width, initial-scale=1"><style>html,body{margin:0;min-height:100%;background:#f3f4f6;color:#171717;font-family:system-ui,sans-serif}*{box-sizing:border-box}#preview{padding:16px;min-height:100vh;overflow:auto}canvas{display:block;margin:auto;background:white}table{border-collapse:collapse;background:white}td,th{border:1px solid #ddd;padding:6px 10px;max-width:400px;white-space:pre-wrap;overflow-wrap:anywhere}th{background:#f5f5f5;font-weight:500;position:sticky;top:0}a{pointer-events:none}img{max-width:100%}.docx-wrapper{padding:0!important;background:transparent!important}.docx-wrapper>section.docx{margin:0 auto 16px!important}</style></head><body><main id="preview"></main><script id="viewer" data-channel="${channel}" type="module" crossorigin="anonymous" src="${assetBase}viewer.js"></script></body></html>`
}

/** Bound Office ZIP expansion before handing it to document libraries. */
export function validateOfficeArchive(bytes: ArrayBuffer) {
  const view = new DataView(bytes)
  let end = bytes.byteLength - 22
  const minimum = Math.max(0, end - 65535)
  for (; end >= minimum; end--) {
    if (
      view.getUint32(end, true) === 0x06054b50 &&
      end + 22 + view.getUint16(end + 20, true) === bytes.byteLength
    )
      break
  }
  if (end < minimum) throw new Error("Invalid Office archive")
  const count = view.getUint16(end + 10, true)
  const directorySize = view.getUint32(end + 12, true)
  let offset = view.getUint32(end + 16, true)
  const directoryEnd = offset + directorySize
  if (
    view.getUint32(end + 4, true) !== 0 ||
    view.getUint16(end + 8, true) !== count ||
    count === 0 ||
    count > 2500 ||
    directoryEnd !== end
  )
    throw new Error("Unsupported Office archive")
  let expanded = 0
  for (let entry = 0; entry < count; entry++) {
    if (
      offset + 46 > directoryEnd ||
      view.getUint32(offset, true) !== 0x02014b50
    )
      throw new Error("Invalid Office entry")
    const size = view.getUint32(offset + 24, true)
    const compressed = view.getUint32(offset + 20, true)
    const method = view.getUint16(offset + 10, true)
    expanded += size
    if (
      view.getUint16(offset + 8, true) & 1 ||
      ![0, 8].includes(method) ||
      size > 16 * 1024 * 1024 ||
      expanded > 64 * 1024 * 1024 ||
      compressed > bytes.byteLength
    )
      throw new Error("Office archive exceeds preview limits")
    offset +=
      46 +
      view.getUint16(offset + 28, true) +
      view.getUint16(offset + 30, true) +
      view.getUint16(offset + 32, true)
  }
  if (offset !== directoryEnd) throw new Error("Invalid Office directory")
}
