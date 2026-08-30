/* @jsxImportSource react */
import { expect, test } from "bun:test"

import { BuiltinToolIcon } from "../src/components/tools/builtin-tool-icon"

test("uses the matching file icon for each built-in file Skill", () => {
  const icons = {
    documents_skill: "/skill-icons/docx.png",
    pdf_skill: "/skill-icons/pdf.png",
    pptx_skill: "/skill-icons/pptx.png",
    spreadsheets_skill: "/skill-icons/excel.png",
  }

  for (const [functionName, src] of Object.entries(icons)) {
    const icon = BuiltinToolIcon({ functionName })
    expect(icon.type).toBe("img")
    expect(icon.props.src).toBe(src)
  }
})
