import { expect, test } from "bun:test"
import FileExcelOutlined from "@ant-design/icons/es/icons/FileExcelOutlined"
import FileImageOutlined from "@ant-design/icons/es/icons/FileImageOutlined"
import FileMarkdownOutlined from "@ant-design/icons/es/icons/FileMarkdownOutlined"
import FilePdfOutlined from "@ant-design/icons/es/icons/FilePdfOutlined"
import FilePptOutlined from "@ant-design/icons/es/icons/FilePptOutlined"
import FileTextOutlined from "@ant-design/icons/es/icons/FileTextOutlined"
import FileUnknownOutlined from "@ant-design/icons/es/icons/FileUnknownOutlined"
import FileWordOutlined from "@ant-design/icons/es/icons/FileWordOutlined"
import FileZipOutlined from "@ant-design/icons/es/icons/FileZipOutlined"

import {
  getDocumentFileIcon,
  getDocumentFileIconColor,
} from "../src/components/knowledge/document-file-icon"

test("selects a file icon from the document extension", () => {
  expect(getDocumentFileIcon("notice.PDF")).toBe(FilePdfOutlined)
  expect(getDocumentFileIcon("report.docx")).toBe(FileWordOutlined)
  expect(getDocumentFileIcon("slides.pptx")).toBe(FilePptOutlined)
  expect(getDocumentFileIcon("data.xlsx")).toBe(FileExcelOutlined)
  expect(getDocumentFileIcon("payload.json")).toBe(FileTextOutlined)
  expect(getDocumentFileIcon("notes.md")).toBe(FileMarkdownOutlined)
  expect(getDocumentFileIcon("photo.webp")).toBe(FileImageOutlined)
  expect(getDocumentFileIcon("archive.zip")).toBe(FileZipOutlined)
  expect(getDocumentFileIcon("unknown.bin")).toBe(FileUnknownOutlined)
  expect(getDocumentFileIconColor("notice.PDF")).toContain("text-red-600")
  expect(getDocumentFileIconColor("report.docx")).toContain("text-blue-600")
  expect(getDocumentFileIconColor("data.xlsx")).toContain("text-emerald-600")
  expect(getDocumentFileIconColor("slides.pptx")).toContain("text-orange-600")
  expect(getDocumentFileIconColor("unknown.bin")).toBe("!text-muted-foreground")
})
