/* @jsxImportSource react */
import { expect, test } from "bun:test"
import {
  BookOpenIcon,
  CalendarDaysIcon,
  Code2Icon,
  DatabaseIcon,
  FileCodeIcon,
  FilePlus2Icon,
  FileTextIcon,
  GlobeIcon,
  ImageIcon,
  ListTodoIcon,
  MailIcon,
  MessageSquareIcon,
  NetworkIcon,
  PackagePlusIcon,
  PuzzleIcon,
  SearchIcon,
  TerminalIcon,
  VideoIcon,
  WrenchIcon,
} from "lucide-react"

import { BuiltinToolIcon } from "../src/components/tools/builtin-tool-icon"

test("uses the matching file icon for each built-in file Skill", () => {
  const icons = {
    documents_skill: "/skill-icons/docx.png",
    pdf_skill: "/skill-icons/pdf.png",
    pptx_skill: "/skill-icons/pptx.png",
    spreadsheets_skill: "/skill-icons/excel.png",
  }

  for (const [functionName, src] of Object.entries(icons)) {
    const icon = BuiltinToolIcon({ functionName })
    expect(icon.type).toBe("img")
    expect(icon.props.src).toBe(src)
  }
})

test("uses an image icon for the image generation Tool", () => {
  const icon = BuiltinToolIcon({ functionName: "generate_image" })
  expect(icon.type).toBe(ImageIcon)
})

test("recognizes search operations across MCP namespaces and naming styles", () => {
  for (const functionName of [
    "tavily_search",
    "mcp_tavily_search_a1b2c3d4",
    "web.search",
    "searchWeb",
    "dida_search_tasks_a1b2c3d4",
    "find_files",
  ]) {
    expect(BuiltinToolIcon({ functionName }).type).toBe(SearchIcon)
  }
})

test("uses a book for knowledge retrieval even with a custom search name", () => {
  expect(BuiltinToolIcon({ functionName: "search_knowledge" }).type).toBe(
    BookOpenIcon
  )
  expect(BuiltinToolIcon({ functionName: "knowledge_retrieval" }).type).toBe(
    BookOpenIcon
  )
  expect(
    BuiltinToolIcon({ functionName: "custom_search", toolKind: "knowledge" })
      .type
  ).toBe(BookOpenIcon)
})

test("distinguishes other existing execution, file, Skill and integration operations", () => {
  const examples = [
    ["bash", TerminalIcon],
    ["tavily_extract", GlobeIcon],
    ["mcp_fetch_page_a1b2c3d4", GlobeIcon],
    ["create_artifact", FilePlus2Icon],
    ["load_skill", PuzzleIcon],
    ["read_skill_file", FileCodeIcon],
    ["run_skill_script", Code2Icon],
    ["install_skill_dependencies", PackagePlusIcon],
    ["read_tool_result", FileTextIcon],
    ["execute_sql", DatabaseIcon],
    ["feishu_send_message", MessageSquareIcon],
    ["dida_list_tasks", ListTodoIcon],
    ["dida_query_calendar_events", CalendarDaysIcon],
    ["tencent_meeting_create_meeting", VideoIcon],
    ["get_email", MailIcon],
  ] as const
  for (const [functionName, expected] of examples) {
    const icon = BuiltinToolIcon({ functionName, className: "size-3.5" })
    expect(icon.type).toBe(expected)
    expect(icon.props.className).toBe("size-3.5")
  }
})

test("keeps unknown tools and unrelated substrings on the configured fallback", () => {
  for (const functionName of [
    undefined,
    null,
    "custom_tool",
    "research",
    "prefetching",
  ]) {
    expect(BuiltinToolIcon({ functionName }).type).toBe(WrenchIcon)
    expect(BuiltinToolIcon({ functionName, fallback: NetworkIcon }).type).toBe(
      NetworkIcon
    )
  }
})
