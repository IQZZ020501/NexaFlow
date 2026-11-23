/* eslint-disable @next/next/no-img-element -- tiny local Skill icons do not need image optimization */
import type { ComponentType } from "react"
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
  PackagePlusIcon,
  PuzzleIcon,
  SearchIcon,
  TerminalIcon,
  VideoIcon,
  WrenchIcon,
} from "lucide-react"

import { cn } from "@/lib/utils"

type IconComponent = ComponentType<{ className?: string }>

const BUILTIN_TOOL_ICON_PATHS: Record<string, string> = {
  documents_skill: "/skill-icons/docx.png",
  pdf_skill: "/skill-icons/pdf.png",
  pptx_skill: "/skill-icons/pptx.png",
  spreadsheets_skill: "/skill-icons/excel.png",
}

const TOOL_ICONS = {
  search_knowledge: BookOpenIcon,
  knowledge_retrieval: BookOpenIcon,
  bash: TerminalIcon,
  generate_image: ImageIcon,
  create_artifact: FilePlus2Icon,
  load_skill: PuzzleIcon,
  skill_creator: PuzzleIcon,
  read_skill_file: FileCodeIcon,
  run_skill_script: Code2Icon,
  install_skill_dependencies: PackagePlusIcon,
  read_tool_result: FileTextIcon,
  search: SearchIcon,
  web: GlobeIcon,
  sql: DatabaseIcon,
  email: MailIcon,
  message: MessageSquareIcon,
  calendar: CalendarDaysIcon,
  meeting: VideoIcon,
  task: ListTodoIcon,
  file: FileTextIcon,
  skill: PuzzleIcon,
} satisfies Record<string, IconComponent>

function toolIconKey(functionName: string) {
  const name = functionName.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase()
  if (Object.hasOwn(TOOL_ICONS, name)) return name as keyof typeof TOOL_ICONS

  // MCP names may include a namespace and an immutable suffix. Match complete
  // words so unrelated names such as "research" retain their fallback.
  const words = new Set(name.split(/[^a-z0-9]+/))
  if (words.has("search") || words.has("find")) return "search"
  if (
    words.has("fetch") ||
    words.has("crawl") ||
    words.has("scrape") ||
    words.has("browse") ||
    (words.has("tavily") && words.has("extract"))
  )
    return "web"
  if (words.has("sql")) return "sql"
  if (words.has("email") || words.has("mail")) return "email"
  if (words.has("message") || words.has("comment")) return "message"
  if (words.has("calendar")) return "calendar"
  if (words.has("meeting")) return "meeting"
  if (words.has("task") || words.has("tasks") || words.has("todos"))
    return "task"
  if (words.has("document") || words.has("file") || words.has("extract"))
    return "file"
  if (words.has("skill")) return "skill"
}

type BuiltinToolIconProps = {
  functionName?: string | null
  toolKind?: string
  className?: string
  fallback?: IconComponent
}

/** Uses capability-specific icons and preserves the caller's unknown-tool fallback. */
export function BuiltinToolIcon({
  functionName,
  toolKind,
  className,
  fallback: Fallback = WrenchIcon,
}: BuiltinToolIconProps) {
  const src = functionName ? BUILTIN_TOOL_ICON_PATHS[functionName] : undefined
  if (!src) {
    const iconKey =
      toolKind === "knowledge"
        ? "search_knowledge"
        : toolIconKey(functionName ?? "")
    const Icon = iconKey ? TOOL_ICONS[iconKey] : Fallback
    return <Icon className={className} />
  }

  return (
    <img
      src={src}
      alt=""
      aria-hidden="true"
      width={24}
      height={24}
      className={cn("object-contain", className)}
      decoding="async"
    />
  )
}
