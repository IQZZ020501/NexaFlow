import * as React from "react"
import { Badge } from "@/components/ui/badge"
import { findChunkOverlapLength } from "@/lib/chunk-overlap"
import { MarkdownContent } from "@/components/knowledge/markdown-content"
import type { KnowledgeDocumentChunk } from "@/lib/api/knowledge"

const CHUNK_OVERLAP_HIGHLIGHT_NAME = "knowledge-chunk-overlap"
const CHUNK_OVERLAP_HIGHLIGHT_STYLE = `::highlight(${CHUNK_OVERLAP_HIGHLIGHT_NAME}) {
  background-color: var(--chunk-overlap-highlight);
  color: inherit;
}`

function createLeadingTextRange(root: HTMLElement, charCount: number) {
  const walker = window.document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const firstNode = walker.nextNode() as Text | null
  if (!firstNode) {
    return null
  }

  const range = new Range()
  range.setStart(firstNode, 0)
  let currentNode: Text | null = firstNode
  let remainingChars = charCount

  while (currentNode) {
    if (remainingChars <= currentNode.length) {
      range.setEnd(currentNode, remainingChars)
      return range
    }
    remainingChars -= currentNode.length
    const nextNode: Text | null = walker.nextNode() as Text | null
    if (!nextNode) {
      range.setEnd(currentNode, currentNode.length)
      return range
    }
    currentNode = nextNode
  }

  return null
}

export function ChunkPreviewList({
  chunks,
  fileName,
}: {
  chunks: KnowledgeDocumentChunk[]
  fileName: string
}) {
  const previewRef = React.useRef<HTMLDivElement>(null)
  const overlapLengths = React.useMemo(
    () =>
      chunks.map((chunk, index) =>
        index === 0
          ? 0
          : findChunkOverlapLength(chunks[index - 1].content, chunk.content),
      ),
    [chunks]
  )

  React.useEffect(() => {
    const previewRoot = previewRef.current
    if (!previewRoot || typeof Highlight === "undefined" || !CSS.highlights) {
      return
    }

    const ranges = overlapLengths.flatMap((overlapLength, index) => {
      if (!overlapLength) {
        return []
      }
      const chunkContent = previewRoot.querySelector<HTMLElement>(
        `[data-overlap-chunk="${index}"]`,
      )
      const range = chunkContent
        ? createLeadingTextRange(chunkContent, overlapLength)
        : null
      return range ? [range] : []
    })

    if (!ranges.length) {
      CSS.highlights.delete(CHUNK_OVERLAP_HIGHLIGHT_NAME)
      return
    }

    const highlight = new Highlight(...ranges)
    CSS.highlights.set(CHUNK_OVERLAP_HIGHLIGHT_NAME, highlight)
    return () => {
      if (CSS.highlights.get(CHUNK_OVERLAP_HIGHLIGHT_NAME) === highlight) {
        CSS.highlights.delete(CHUNK_OVERLAP_HIGHLIGHT_NAME)
      }
    }
  }, [overlapLengths])

  return (
    <>
      <style>{CHUNK_OVERLAP_HIGHLIGHT_STYLE}</style>
      <div ref={previewRef} className="space-y-3">
        {chunks.map((chunk, index) => {
          const overlapLength = overlapLengths[index] ?? 0
          return (
            <article
              key={chunk.id}
              className="overflow-hidden rounded-lg border bg-background"
            >
              <div className="flex items-center justify-between gap-3 border-b bg-muted/20 px-4 py-2">
                <h3 className="truncate text-sm font-semibold text-foreground" title={fileName}>
                  {fileName}
                </h3>
                <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                  {overlapLength ? (
                    <Badge variant="secondary">重叠 {overlapLength} 字符</Badge>
                  ) : null}
                  <span className="text-xs text-muted-foreground">
                    {chunk.char_count} 字符 / {chunk.token_count} tokens
                  </span>
                </div>
              </div>
              <div data-overlap-chunk={index}>
                <MarkdownContent
                  content={chunk.content}
                  className="px-4 py-3 text-[15px] leading-7"
                />
              </div>
            </article>
          )
        })}
      </div>
    </>
  )
}
