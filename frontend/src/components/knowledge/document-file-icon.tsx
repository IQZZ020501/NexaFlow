import FileExcelOutlined from "@ant-design/icons/es/icons/FileExcelOutlined"
import FileImageOutlined from "@ant-design/icons/es/icons/FileImageOutlined"
import FileMarkdownOutlined from "@ant-design/icons/es/icons/FileMarkdownOutlined"
import FilePdfOutlined from "@ant-design/icons/es/icons/FilePdfOutlined"
import FilePptOutlined from "@ant-design/icons/es/icons/FilePptOutlined"
import FileTextOutlined from "@ant-design/icons/es/icons/FileTextOutlined"
import FileUnknownOutlined from "@ant-design/icons/es/icons/FileUnknownOutlined"
import FileWordOutlined from "@ant-design/icons/es/icons/FileWordOutlined"
import FileZipOutlined from "@ant-design/icons/es/icons/FileZipOutlined"
import type { AntdIconProps } from "@ant-design/icons/es/components/AntdIconLight"
import type { ForwardRefExoticComponent, RefAttributes } from "react"

type DocumentFileIcon = ForwardRefExoticComponent<
  Omit<AntdIconProps, "ref"> & RefAttributes<HTMLSpanElement>
>

const DOCUMENT_FILE_ICONS: Record<string, DocumentFileIcon> = {
  ".pdf": FilePdfOutlined,
  ".docx": FileWordOutlined,
  ".txt": FileTextOutlined,
  ".md": FileMarkdownOutlined,
  ".markdown": FileMarkdownOutlined,
  ".pptx": FilePptOutlined,
  ".xlsx": FileExcelOutlined,
  ".xls": FileExcelOutlined,
  ".csv": FileExcelOutlined,
  ".html": FileTextOutlined,
  ".xml": FileTextOutlined,
  ".json": FileTextOutlined,
  ".ipynb": FileTextOutlined,
  ".epub": FileTextOutlined,
  ".zip": FileZipOutlined,
  ".png": FileImageOutlined,
  ".jpg": FileImageOutlined,
  ".jpeg": FileImageOutlined,
  ".webp": FileImageOutlined,
}

const DOCUMENT_FILE_ICON_COLORS: Record<string, string> = {
  ".pdf": "!text-red-600 dark:!text-red-400",
  ".docx": "!text-blue-600 dark:!text-blue-400",
  ".pptx": "!text-orange-600 dark:!text-orange-400",
  ".xlsx": "!text-emerald-600 dark:!text-emerald-400",
  ".xls": "!text-emerald-600 dark:!text-emerald-400",
  ".csv": "!text-emerald-600 dark:!text-emerald-400",
  ".md": "!text-sky-600 dark:!text-sky-400",
  ".markdown": "!text-sky-600 dark:!text-sky-400",
  ".zip": "!text-amber-600 dark:!text-amber-400",
  ".png": "!text-violet-600 dark:!text-violet-400",
  ".jpg": "!text-violet-600 dark:!text-violet-400",
  ".jpeg": "!text-violet-600 dark:!text-violet-400",
  ".webp": "!text-violet-600 dark:!text-violet-400",
}

/**
 * Extracts the lowercase extension from a filename.
 *
 * @param filename - The filename to inspect
 * @returns The extension beginning with `.`, or an empty string when the filename has no period
 */
function documentFileExtension(filename: string) {
  return filename.includes(".")
    ? filename.slice(filename.lastIndexOf(".")).toLowerCase()
    : ""
}

/**
 * Selects the icon associated with a document filename.
 *
 * @param filename - The document filename
 * @returns The icon mapped to the filename's extension, or the unknown-file icon when no mapping exists
 */
export function getDocumentFileIcon(filename: string): DocumentFileIcon {
  const extension = documentFileExtension(filename)
  return DOCUMENT_FILE_ICONS[extension] ?? FileUnknownOutlined
}

/**
 * Gets the color classes associated with a document filename's extension.
 *
 * @param filename - The document filename
 * @returns The extension-specific color classes, or the muted foreground color for unsupported extensions
 */
export function getDocumentFileIconColor(filename: string) {
  return (
    DOCUMENT_FILE_ICON_COLORS[documentFileExtension(filename)] ??
    "!text-muted-foreground"
  )
}
