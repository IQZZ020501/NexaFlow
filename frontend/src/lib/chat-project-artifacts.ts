import { artifactContentUrl, type ArtifactEvent } from "@/lib/agent-artifacts"

/** Only saved artifacts from successful file tools can be shared explicitly. */
export function projectArtifactOptions(events: readonly ArtifactEvent[]) {
  const files = new Map<string, { id: string; filename: string }>()
  for (const event of events) {
    if (
      event.status !== "succeeded" ||
      !event.output ||
      typeof event.output !== "object"
    )
      continue
    const output = event.output as Record<string, unknown>
    const candidates =
      ["bash", "run_skill_script"].includes(event.tool_name ?? "") &&
      Array.isArray(output.artifacts)
        ? output.artifacts
        : [
              "create_artifact",
              "documents_skill",
              "pdf_skill",
              "spreadsheets_skill",
              "pptx_skill",
              "generate_image",
            ].includes(event.tool_name ?? "")
          ? [output]
          : []
    for (const file of candidates) {
      if (
        file &&
        typeof file === "object" &&
        artifactContentUrl(file) &&
        typeof file.filename === "string" &&
        typeof file.artifact_id === "string"
      ) {
        files.set(file.relative_path ?? file.filename, {
          id: file.artifact_id,
          filename: file.filename,
        })
      }
    }
  }
  return [...files.values()]
}
