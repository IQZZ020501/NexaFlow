/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { screen } from "@testing-library/react"

import { DocumentDetailPage } from "@/components/knowledge/document-detail-page"
import {
  cleanup,
  jsonResponse,
  makeSession,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  resetFetch,
  withFetch,
} from "./helpers/dom"

const timestamp = "2026-09-28T00:00:00Z"

mockUseSession(makeSession())
mockNextNavigation({ params: { id: "kb-1", docId: "doc-1" } })

afterEach(() => {
  cleanup()
  resetFetch()
})

describe("document detail page", () => {
  test("renders the canonical document content as Markdown", async () => {
    withFetch((url) => {
      if (url.endsWith("/knowledge-bases")) {
        return jsonResponse([
          {
            id: "kb-1",
            workspace_id: "ws-1",
            name: "Product docs",
            description: "",
            status: "active",
            embedding_model_id: null,
            reranker_model_id: null,
            created_by_user_id: "u-1",
            created_at: timestamp,
            updated_at: timestamp,
            permission: "edit",
            document_count: 1,
            char_count: 32,
          },
        ])
      }
      if (url.endsWith("/documents")) {
        return jsonResponse([
          {
            id: "doc-1",
            workspace_id: "ws-1",
            knowledge_base_id: "kb-1",
            filename: "guide.docx",
            content_type:
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes: 1024,
            attachment_id: "attachment-1",
            meta: {
              normalized_content_type: "text/markdown",
            },
            status: "parsed",
            is_active: true,
            chunk_count: 1,
            last_error: null,
            created_by_user_id: "u-1",
            created_at: timestamp,
            updated_at: timestamp,
          },
        ])
      }
      if (url.includes("/chunks?")) {
        return jsonResponse([
          {
            id: "chunk-1",
            workspace_id: "ws-1",
            knowledge_base_id: "kb-1",
            document_id: "doc-1",
            parent_id: null,
            parent_title: null,
            parent_index: null,
            chunk_index: 0,
            start_offset: null,
            end_offset: null,
            content: "raw chunk fallback",
            kind: "document",
            question: null,
            source: null,
            row_number: null,
            char_count: 18,
            token_count: 3,
            vector_id: null,
            status: "preview",
            images: [],
            created_at: timestamp,
            updated_at: timestamp,
          },
        ])
      }
      if (url.endsWith("/tasks")) {
        return jsonResponse([])
      }
      if (url.endsWith("/content")) {
        return new Response("# Canonical title\n\nRead the **bold** value.", {
          status: 200,
          headers: { "Content-Type": "text/markdown; charset=utf-8" },
        })
      }
      throw new Error(`Unhandled fetch: ${url}`)
    })

    renderPage(<DocumentDetailPage />)

    expect(
      await screen.findByRole("heading", { name: "Canonical title" })
    ).toBeTruthy()
    expect(screen.getByText("bold").tagName).toBe("STRONG")
    expect(screen.queryByText("raw chunk fallback")).toBeNull()
  })
})
