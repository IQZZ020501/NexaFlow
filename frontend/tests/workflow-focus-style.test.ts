import { expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import { join } from "node:path"

const workflowCanvasSource = readFileSync(
  join(import.meta.dir, "../src/components/workflows/workflow-canvas.tsx"),
  "utf8"
)
const interactionFieldsSource = readFileSync(
  join(import.meta.dir, "../src/components/agents/interaction-config-fields.tsx"),
  "utf8"
)

function openingTag(source: string, id: string) {
  const marker = id.startsWith("id=") ? id : `id={\`${id}\`}`
  const idIndex = source.indexOf(marker)
  expect(idIndex).toBeGreaterThan(-1)
  const start = source.lastIndexOf("<", idIndex)
  const closing = source.slice(idIndex).match(/\n\s*\/?>/)
  expect(closing?.index).toBeDefined()
  const end = idIndex + (closing?.index ?? 0) + closing![0].length
  return source.slice(start, end)
}

test("workflow basic info fields use a single focus border", () => {
  const directControls = [
    openingTag(workflowCanvasSource, 'id="basic-info-name"'),
    openingTag(workflowCanvasSource, 'id="basic-info-description"'),
    openingTag(interactionFieldsSource, "${idPrefix}-input-title"),
  ]
  const textareaStyleStart = interactionFieldsSource.indexOf("const textareaClass")
  const textareaStyles = interactionFieldsSource.slice(
    textareaStyleStart,
    interactionFieldsSource.indexOf("\n    :", textareaStyleStart)
  )

  for (const control of [...directControls.slice(1), textareaStyles]) {
    expect(control).toContain("focus-visible:border-ring")
    expect(control).not.toMatch(/focus-visible:ring-[1-9]/)
  }

  expect(directControls[0]).toContain("focus-visible:border-ring")
  expect(directControls[0]).toContain("focus-visible:ring-0")
})

test("workflow binary settings use switches", () => {
  const controls = [
    openingTag(interactionFieldsSource, "${idPrefix}-tts"),
    openingTag(interactionFieldsSource, "${idPrefix}-file-upload"),
  ]

  for (const control of controls) {
    expect(control).toContain('role="switch"')
    expect(control).not.toContain('type="checkbox"')
  }
  expect(controls[0]).toContain('aria-checked={value.tts_type === "BROWSER"}')
  expect(controls[1]).toContain("aria-checked={value.file_upload}")
})
