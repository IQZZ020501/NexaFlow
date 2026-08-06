import { describe, expect, test } from "bun:test"

import { resolveSelectedDocumentId } from "../components/knowledge/knowledge-upload-flow"

describe("knowledge upload preview selection", () => {
  test("keeps an available selection and falls back after removal", () => {
    const documents = [{ id: "second" }, { id: "third" }]

    expect(resolveSelectedDocumentId(documents, "third")).toBe("third")
    expect(resolveSelectedDocumentId(documents, "first")).toBe("second")
    expect(resolveSelectedDocumentId([], "first")).toBeNull()
  })
})
