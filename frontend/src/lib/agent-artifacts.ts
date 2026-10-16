export type ArtifactEvent = {
  tool_name?: string
  status?: string
  output?: unknown
}

export type PreviewFormat = "html" | "pdf" | "docx" | "xlsx" | "pptx"

export type PreviewArtifact = {
  filename: string
  downloadUrl: string
  format: PreviewFormat
}

export const MAX_PREVIEW_BYTES = 5 * 1024 * 1024

export const PREVIEW_MIME_TYPES: Record<PreviewFormat, string> = {
  html: "text/html",
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

const ARTIFACT_PATH = /^\/api\/v1\/artifacts\/[A-Za-z0-9._~-]+$/
const FILE_TOOLS = new Set([
  "create_artifact",
  "documents_skill",
  "pdf_skill",
  "spreadsheets_skill",
  "pptx_skill",
])

/** Only successful, platform-generated files can become previews. */
export function previewArtifactsForEvents(events: readonly ArtifactEvent[]) {
  const artifacts = new Map<string, PreviewArtifact>()
  for (const event of events) {
    if (
      event.status !== "succeeded" ||
      !event.output ||
      typeof event.output !== "object"
    )
      continue
    const output = event.output as Record<string, unknown>
    const files = FILE_TOOLS.has(event.tool_name ?? "")
      ? [output]
      : (event.tool_name === "bash" ||
            event.tool_name === "run_skill_script") &&
          Array.isArray(output.artifacts)
        ? output.artifacts
        : []
    for (const file of files) {
      if (!file || typeof file !== "object") continue
      const { filename, download_url: downloadUrl } = file
      if (
        typeof filename !== "string" ||
        !/\.(html?|pdf|docx|xlsx|pptx)$/i.test(filename) ||
        typeof downloadUrl !== "string" ||
        !ARTIFACT_PATH.test(downloadUrl)
      ) {
        continue
      }
      // Match download-link behavior: the latest rewrite of a filename wins.
      const extension = filename.split(".").pop()!.toLowerCase()
      artifacts.set(filename, {
        filename,
        downloadUrl,
        format: extension === "htm" ? "html" : (extension as PreviewFormat),
      })
    }
  }
  const urls = new Set<string>()
  return [...artifacts.values()].filter(({ downloadUrl }) => {
    if (urls.has(downloadUrl)) return false
    urls.add(downloadUrl)
    return true
  })
}

/** The policy precedes all untrusted markup, including full HTML documents. */
export function htmlPreviewDocument(html: string) {
  const policy = [
    "default-src 'none'",
    "script-src 'unsafe-inline'",
    "style-src 'unsafe-inline'",
    "img-src data: blob:",
    "font-src data:",
    "media-src data: blob:",
    "connect-src 'none'",
    "frame-src 'none'",
    "object-src 'none'",
    "worker-src 'none'",
    "base-uri about:",
    "form-action 'none'",
  ].join("; ")
  // Do not parse or mount this markup in the host document. The iframe must
  // keep sandbox="allow-scripts" without allow-same-origin on every surface.
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${policy}"><meta name="referrer" content="no-referrer"><base href="about:srcdoc"><meta name="viewport" content="width=device-width, initial-scale=1"></head>${html}</html>`
}
