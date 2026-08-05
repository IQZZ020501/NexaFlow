import { describe, expect, test } from "bun:test"

import {
  DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
  knowledgeUploadPath,
  knowledgeUploadSegmentPath,
  parseKnowledgeUploadRouteState,
} from "../lib/knowledge-upload-route"

const KNOWLEDGE_BASE_ID = "5fa2f018-636f-47c5-9955-62f341058747"
const DOCUMENT_IDS = [
  "6ea0e340-2099-4192-a670-c93c854383e2",
  "1cb109d4-7f8c-4906-850e-09cd0f9c323e",
]

describe("knowledge upload routes", () => {
  test("round-trips the segment documents and parse settings", () => {
    const parseSettings = {
      segmentMode: "advanced" as const,
      chunkSize: 900,
      chunkOverlap: 90,
      splitSeparator: "。",
      cleaningRules: ["trim_lines", "collapse_spaces"],
    }
    const path = knowledgeUploadSegmentPath(
      KNOWLEDGE_BASE_ID,
      DOCUMENT_IDS,
      parseSettings,
    )
    const url = new URL(path, "http://localhost")

    expect(url.pathname).toBe(
      `/app/knowledge/${KNOWLEDGE_BASE_ID}/upload/segment`,
    )
    expect(parseKnowledgeUploadRouteState(Object.fromEntries(url.searchParams))).toEqual({
      documentIds: DOCUMENT_IDS,
      parseSettings,
    })
  })

  test("rejects invalid route state and falls back to safe defaults", () => {
    expect(
      parseKnowledgeUploadRouteState({
        documents: `${DOCUMENT_IDS[0]},not-a-document,${DOCUMENT_IDS[0]}`,
        mode: "unknown",
        chunk_size: "50",
        chunk_overlap: "5000",
        separator: "invalid",
        cleaning: "trim_lines,invalid",
      }),
    ).toEqual({
      documentIds: [DOCUMENT_IDS[0]],
      parseSettings: DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
    })
    expect(knowledgeUploadPath(KNOWLEDGE_BASE_ID)).toBe(
      `/app/knowledge/${KNOWLEDGE_BASE_ID}/upload`,
    )
  })
})
