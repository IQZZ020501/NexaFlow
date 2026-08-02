const MAX_OVERLAP_CHARS = 2000
const MIN_HIGHLIGHTED_OVERLAP_CHARS = 8

export function findChunkOverlapLength(
  previousContent: string,
  currentContent: string,
): number {
  const maxLength = Math.min(
    previousContent.length,
    currentContent.length,
    MAX_OVERLAP_CHARS,
  )

  for (
    let length = maxLength;
    length >= MIN_HIGHLIGHTED_OVERLAP_CHARS;
    length -= 1
  ) {
    if (previousContent.endsWith(currentContent.slice(0, length))) {
      return length
    }
  }

  return 0
}
