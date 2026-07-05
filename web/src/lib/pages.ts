import {
  BoxesIcon,
  BrainCircuitIcon,
  DatabaseIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react"

import {
  DEFAULT_LANGUAGE,
  translate,
  type TFunction,
} from "@/lib/i18n"

type DialogField = {
  id: string
  label: string
  type: "text" | "password"
  placeholder: string
}

type WorkspacePageConfig = {
  key: "apps" | "knowledge" | "models" | "tools"
  label: string
  description: string
  actionLabel: string
  emptyTitle: string
  emptyDescription: string
  secondaryActionLabel: string
  dialogDescription: string
  dialogFields: DialogField[]
  icon: LucideIcon
}

const pageDefinitions = [
  {
    key: "apps",
    icon: BoxesIcon,
  },
  {
    key: "knowledge",
    icon: DatabaseIcon,
  },
  {
    key: "models",
    icon: BrainCircuitIcon,
  },
  {
    key: "tools",
    icon: WrenchIcon,
  },
] as const satisfies ReadonlyArray<{
  key: "apps" | "knowledge" | "models" | "tools"
  icon: LucideIcon
}>

const pageCopy = {
  apps: {
    label: "应用",
    description: "编排业务流程、知识库和模型能力，构建可运行的 AI 应用。",
    actionLabel: "新建应用",
    emptyTitle: "还没有应用",
    emptyDescription: "创建应用后，可以编排对话、检索和工具调用流程。",
    secondaryActionLabel: "查看模板",
    dialogDescription: "配置应用名称和入口标识。",
    dialogFields: [
      {
        id: "appName",
        label: "应用名称",
        type: "text",
        placeholder: "例如：客服助手",
      },
      {
        id: "appSlug",
        label: "应用标识",
        type: "text",
        placeholder: "例如：support-agent",
      },
      {
        id: "appOwner",
        label: "负责人",
        type: "text",
        placeholder: "例如：运营团队",
      },
    ],
  },
  knowledge: {
    label: "知识库",
    description: "管理文档、数据源与向量索引，让应用可以检索你的业务知识。",
    actionLabel: "新建知识库",
    emptyTitle: "还没有知识库",
    emptyDescription:
      "创建知识库后，你可以上传文档、配置检索方式，并让应用调用这些知识。",
    secondaryActionLabel: "查看示例",
    dialogDescription: "配置知识库名称、标识和默认数据源。",
    dialogFields: [
      {
        id: "knowledgeName",
        label: "知识库名称",
        type: "text",
        placeholder: "例如：产品文档",
      },
      {
        id: "knowledgeSlug",
        label: "知识库标识",
        type: "text",
        placeholder: "例如：product-docs",
      },
      {
        id: "knowledgeSource",
        label: "数据源",
        type: "text",
        placeholder: "例如：本地文档",
      },
    ],
  },
  models: {
    label: "模型",
    description: "接入模型供应商，配置默认模型和调用参数。",
    actionLabel: "接入模型",
    emptyTitle: "还没有模型",
    emptyDescription:
      "接入模型后，应用可以使用它进行对话、检索增强和工具调用。",
    secondaryActionLabel: "查看配置",
    dialogDescription: "配置供应商、模型名称和访问凭据。",
    dialogFields: [
      {
        id: "modelProvider",
        label: "供应商",
        type: "text",
        placeholder: "例如：OpenAI",
      },
      {
        id: "modelName",
        label: "模型名称",
        type: "text",
        placeholder: "例如：gpt-4.1",
      },
      {
        id: "modelApiKey",
        label: "API Key",
        type: "password",
        placeholder: "sk-...",
      },
    ],
  },
  tools: {
    label: "工具",
    description: "管理外部 API、内部服务和可被应用调用的工具能力。",
    actionLabel: "添加工具",
    emptyTitle: "还没有工具",
    emptyDescription:
      "添加工具后，应用可以调用外部系统完成查询、写入和自动化动作。",
    secondaryActionLabel: "查看示例",
    dialogDescription: "配置工具名称、标识和调用地址。",
    dialogFields: [
      {
        id: "toolName",
        label: "工具名称",
        type: "text",
        placeholder: "例如：订单查询",
      },
      {
        id: "toolSlug",
        label: "工具标识",
        type: "text",
        placeholder: "例如：order-query",
      },
      {
        id: "toolUrl",
        label: "调用地址",
        type: "text",
        placeholder: "https://api.example.com/orders",
      },
    ],
  },
} as const

export function getPages(t: TFunction): WorkspacePageConfig[] {
  return pageDefinitions.map((page) => {
    const copy = pageCopy[page.key]

    return {
      ...page,
      label: t(copy.label),
      description: t(copy.description),
      actionLabel: t(copy.actionLabel),
      emptyTitle: t(copy.emptyTitle),
      emptyDescription: t(copy.emptyDescription),
      secondaryActionLabel: t(copy.secondaryActionLabel),
      dialogDescription: t(copy.dialogDescription),
      dialogFields: copy.dialogFields.map((field) => ({
        ...field,
        label: t(field.label),
        placeholder: t(field.placeholder),
      })),
    }
  })
}

export const pages = getPages((key, values) =>
  translate(DEFAULT_LANGUAGE, key, values)
)

export type PageKey = (typeof pageDefinitions)[number]["key"] | "system"
export type FeaturePageConfig = (typeof pages)[number]
