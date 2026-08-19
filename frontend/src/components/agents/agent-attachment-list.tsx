import { PaperclipIcon, XIcon } from "lucide-react"
import type { TFunction } from "@/i18n"

/**
 * Renders attached files with localized remove controls.
 *
 * @param files - The files to display
 * @param onRemove - Called with the index of the file selected for removal
 * @returns The attachment list, or `null` when `files` is empty
 */
export function AgentAttachmentList({
  files,
  onRemove,
  t,
}: {
  files: File[]
  onRemove: (index: number) => void
  t: TFunction
}) {
  if (!files.length) return null

  return (
    <ul className="flex max-h-24 flex-wrap gap-1.5 overflow-y-auto px-3 pb-1 pr-24">
      {files.map((file, index) => (
        <li
          key={`${file.name}-${file.size}-${file.lastModified}-${index}`}
          title={file.name}
          className="flex max-w-48 items-center gap-1 rounded-md bg-muted py-1 pr-1 pl-2 text-xs text-muted-foreground"
        >
          <PaperclipIcon className="size-3" />
          <span className="truncate">{file.name}</span>
          <button
            type="button"
            className="rounded-sm p-0.5 hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={t("移除 {value}", { value: file.name })}
            onClick={() => onRemove(index)}
          >
            <XIcon className="size-3" />
          </button>
        </li>
      ))}
    </ul>
  )
}
