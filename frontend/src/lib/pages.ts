import {
  BoxesIcon,
  BrainCircuitIcon,
  OrbitIcon,
  DatabaseIcon,
  WrenchIcon,
} from "lucide-react"

import { type TFunction } from "@/i18n"

const pageDefinitions = [
  {
    key: "apps",
    label: "应用",
    icon: BoxesIcon,
  },
  {
    key: "automations",
    label: "自动化",
    icon: OrbitIcon,
  },
  {
    key: "knowledge",
    label: "知识库",
    icon: DatabaseIcon,
  },
  {
    key: "models",
    label: "模型",
    icon: BrainCircuitIcon,
  },
  {
    key: "tools",
    label: "工具",
    icon: WrenchIcon,
  },
] as const

/** Build localized labels and icons for desktop and mobile navigation. */
export function getPages(t: TFunction) {
  return pageDefinitions.map((page) => ({ ...page, label: t(page.label) }))
}

export type PageKey = (typeof pageDefinitions)[number]["key"] | "system"
