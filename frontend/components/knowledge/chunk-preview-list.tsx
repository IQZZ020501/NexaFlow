import * as React from "react"
import { Badge } from "@/components/ui/badge"
import { useLanguage } from "@/contexts/language-provider"
import { findChunkOverlapLength } from "@/lib/chunk-overlap"
import { MarkdownContent } from "@/components/knowledge/markdown-content"
import { loadKnowledgeAsset } from "@/lib/api/knowledge"
import type {
  KnowledgeAsset,
  KnowledgeDocumentChunk,
} from "@/lib/api/knowledge"

const CHUNK_OVERLAP_HIGHLIGHT_NAME = "knowledge-chunk-overlap"
const CHUNK_OVERLAP_HIGHLIGHT_STYLE = `::highlight(${CHUNK_OVERLAP_HIGHLIGHT_NAME}) {
  background-color: var(--chunk-overlap-highlight);
  color: inherit;
}`

function AssetImage({
  token,
  workspaceId,
  knowledgeBaseId,
  documentId,
  asset,
}: {
  token: string
  workspaceId: string
  knowledgeBaseId: string
  documentId: string
  asset: KnowledgeAsset
}) {
  const { t } = useLanguage()
  const [objectUrl, setObjectUrl] = React.useState<string | null>(null)
  const [failed, setFailed] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    let createdUrl: string | null = null
    loadKnowledgeAsset(
      token,
      workspaceId,
      knowledgeBaseId,
      documentId,
      asset.id,
    )
      .then((blob) => {
        if (cancelled) {
          return
        }
        createdUrl = URL.createObjectURL(blob)
        setObjectUrl(createdUrl)
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true)
        }
      })
    return () => {
      cancelled = true
      if (createdUrl) {
        URL.revokeObjectURL(createdUrl)
      }
    }
  }, [asset.id, documentId, knowledgeBaseId, token, workspaceId])

  if (failed) {
    return (
      <span className="text-xs text-muted-foreground">
        {t("图片加载失败")}
      </span>
    )
  }
  if (!objectUrl) {
    return <div className="h-24 w-32 animate-pulse rounded bg-muted" />
  }
  return (
    <img
      src={objectUrl}
      alt={asset.alt_text || asset.filename}
      className="max-h-64 max-w-full rounded border object-contain"
    />
  )
}

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
  token,
  workspaceId,
  knowledgeBaseId,
}: {
  chunks: KnowledgeDocumentChunk[]
  fileName: string
  token: string
  workspaceId: string
  knowledgeBaseId: string
}) {
  const { t } = useLanguage()
  const previewRef = React.useRef<HTMLDivElement>(null)
  const overlapLengths = React.useMemo(
    () =>
      chunks.map((chunk, index) => {
        const previousChunk = chunks[index - 1]
        return !previousChunk || previousChunk.parent_id !== chunk.parent_id
          ? 0
          : findChunkOverlapLength(previousChunk.content, chunk.content)
      }),
    [chunks]
  )
  const parentGroups = React.useMemo(() => {
    const groups: {
      id: string
      title: string | null
      index: number | null
      chunks: { chunk: KnowledgeDocumentChunk; index: number }[]
    }[] = []
    const groupsById = new Map<string, (typeof groups)[number]>()
    for (const [index, chunk] of chunks.entries()) {
      const id = chunk.parent_id ?? `flat:${chunk.id}`
      const group = groupsById.get(id)
      if (group) {
        group.chunks.push({ chunk, index })
      } else {
        const nextGroup = {
          id,
          title: chunk.parent_title,
          index: chunk.parent_index,
          chunks: [{ chunk, index }],
        }
        groups.push(nextGroup)
        groupsById.set(id, nextGroup)
      }
    }
    return groups
  }, [chunks])
  const hasParentChunks = chunks.some((chunk) => chunk.parent_id)

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
        `[data-overlap-chunk="${index}"]`
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

  function renderChunk(
    chunk: KnowledgeDocumentChunk,
    index: number,
    title: string
  ) {
    const overlapLength = overlapLengths[index] ?? 0
    return (
      <article
        key={chunk.id}
        className="overflow-hidden rounded-lg border bg-background"
      >
        <div className="flex items-center justify-between gap-3 border-b bg-muted/20 px-4 py-2">
          <h3
            className="truncate text-sm font-semibold text-foreground"
            title={title}
          >
            {title}
          </h3>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            {overlapLength ? (
              <Badge variant="secondary">
                {t("重叠 {value} 字符", { value: overlapLength })}
              </Badge>
            ) : null}
            <span className="text-xs text-muted-foreground">
              {t("{chars} 字符 / {tokens} tokens", {
                chars: chunk.char_count,
                tokens: chunk.token_count,
              })}
            </span>
          </div>
        </div>
        <div data-overlap-chunk={index}>
          <MarkdownContent
            content={chunk.content}
            className="px-4 py-3 text-[15px] leading-7"
          />
          {chunk.images.length ? (
            <div className="flex flex-wrap gap-3 border-t px-4 py-3">
              {chunk.images.map((asset) => (
                <AssetImage
                  key={asset.id}
                  token={token}
                  workspaceId={workspaceId}
                  knowledgeBaseId={knowledgeBaseId}
                  documentId={chunk.document_id}
                  asset={asset}
                />
              ))}
            </div>
          ) : null}
        </div>
      </article>
    )
  }

  return (
    <>
      <style>{CHUNK_OVERLAP_HIGHLIGHT_STYLE}</style>
      <div ref={previewRef} className="space-y-3">
        {hasParentChunks
          ? parentGroups.map((group) => (
              <section key={group.id} className="space-y-2">
                <div className="px-1">
                  <h3 className="text-sm font-semibold text-foreground">
                    {group.title ||
                      t("章节 {value}", { value: (group.index ?? 0) + 1 })}
                  </h3>
                  <p
                    className="truncate text-xs text-muted-foreground"
                    title={fileName}
                  >
                    {fileName}
                  </p>
                </div>
                <div className="space-y-3">
                  {group.chunks.map(({ chunk, index }) =>
                    renderChunk(
                      chunk,
                      index,
                      t("片段 {value}", { value: chunk.chunk_index + 1 })
                    )
                  )}
                </div>
              </section>
            ))
          : chunks.map((chunk, index) => renderChunk(chunk, index, fileName))}
      </div>
    </>
  )
}
