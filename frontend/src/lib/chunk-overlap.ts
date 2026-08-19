const MAX_OVERLAP_CHARS = 2000
const MIN_HIGHLIGHTED_OVERLAP_CHARS = 8

/**
 * Finds the longest overlap between the end of previous content and the beginning of current content.
 *
 * @param previousContent - The preceding content
 * @param currentContent - The content that follows it
 * @returns The matching overlap length, or `0` if no qualifying overlap exists
 */
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
