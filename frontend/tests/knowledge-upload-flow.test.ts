import { describe, expect, test } from "bun:test"

import {
  appendKnowledgeUploadFiles,
  resolveSelectedDocumentId,
  SUPPORTED_FILE_TYPES,
} from "../components/knowledge/knowledge-upload-flow"
import { MAX_KNOWLEDGE_UPLOAD_DOCUMENTS } from "../lib/knowledge-upload-route"

describe("knowledge upload preview selection", () => {
  test("accepts the supported document formats", () => {
    expect(SUPPORTED_FILE_TYPES).toEqual([
      ".docx",
      ".md",
      ".markdown",
      ".pdf",
      ".txt",
      ".pptx",
      ".xlsx",
      ".xls",
      ".html",
      ".csv",
      ".json",
      ".xml",
      ".ipynb",
      ".epub",
      ".zip",
      ".png",
      ".jpg",
      ".jpeg",
      ".webp",
    ])
  })

  test("keeps an available selection and falls back after removal", () => {
    const documents = [{ id: "second" }, { id: "third" }]

    expect(resolveSelectedDocumentId(documents, "third")).toBe("third")
    expect(resolveSelectedDocumentId(documents, "first")).toBe("second")
    expect(resolveSelectedDocumentId([], "first")).toBeNull()
  })

  test("appends newly selected files without dropping the existing queue", () => {
    const file = (name: string) => new File([name], name)
    const existingFiles = [
      file("one.txt"),
      file("two.txt"),
      file("three.txt"),
      file("four.txt"),
    ]
    const nextFile = file("five.txt")

    expect(
      appendKnowledgeUploadFiles(existingFiles, [nextFile]).map(
        (item) => item.name,
      ),
    ).toEqual(["one.txt", "two.txt", "three.txt", "four.txt", "five.txt"])
  })

  test("keeps the combined queue within the upload limit", () => {
    const file = (index: number) => new File([String(index)], `${index}.txt`)
    const existingFiles = Array.from(
      { length: MAX_KNOWLEDGE_UPLOAD_DOCUMENTS - 1 },
      (_, index) => file(index),
    )

    expect(appendKnowledgeUploadFiles(existingFiles, [file(30), file(31)])).toHaveLength(
      MAX_KNOWLEDGE_UPLOAD_DOCUMENTS,
    )
  })
})
