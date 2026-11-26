import type { ComponentType } from "react"
import {
  BotIcon,
  BracesIcon,
  BrainCircuitIcon,
  ClipboardListIcon,
  DatabaseIcon,
  FileTextIcon,
  FlagIcon,
  GitBranchIcon,
  ListFilterIcon,
  MessageSquareMoreIcon,
  PlayIcon,
  RouteIcon,
  TextCursorInputIcon,
  WrenchIcon,
} from "lucide-react"

import type { WorkflowNodeType } from "@/lib/api/workflows"

export const NODE_ICONS: Record<
  WorkflowNodeType,
  ComponentType<{ className?: string }>
> = {
  start: PlayIcon,
  end: FlagIcon,
  llm: BrainCircuitIcon,
  classifier: RouteIcon,
  knowledge: DatabaseIcon,
  "reranker-node": ListFilterIcon,
  "form-node": ClipboardListIcon,
  "document-extract-node": FileTextIcon,
  condition: GitBranchIcon,
  "reply-node": MessageSquareMoreIcon,
  template: TextCursorInputIcon,
  variable: BracesIcon,
  tool: WrenchIcon,
  agent: BotIcon,
  mcp: WrenchIcon,
}
