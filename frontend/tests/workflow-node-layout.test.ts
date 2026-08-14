import { expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import { join } from "node:path"

const source = readFileSync(
  join(import.meta.dir, "../components/workflows/workflow-node.tsx"),
  "utf8"
)
const canvasSource = readFileSync(
  join(import.meta.dir, "../components/workflows/workflow-canvas.tsx"),
  "utf8"
)
const detailSource = readFileSync(
  join(import.meta.dir, "../components/workflows/workflow-detail-workspace.tsx"),
  "utf8"
)
const appConfigSource = readFileSync(
  join(import.meta.dir, "../components/agents/agent-config-fields.tsx"),
  "utf8"
)
const agentsPageSource = readFileSync(
  join(import.meta.dir, "../components/agents/agents-page.tsx"),
  "utf8"
)

test("basic info placement does not follow Start card changes", () => {
  expect(canvasSource).toContain("if (infoPositionInitializedRef.current) return")
  expect(canvasSource).not.toContain("new ResizeObserver(placeLeftOfStart)")
})

test("workflow nodes default to expanded when the canvas mounts", () => {
  expect(source).toContain("const [expanded, setExpanded] = React.useState(true)")
  expect(source).not.toContain(
    'React.useState(node.type === "start" || node.type === "end")'
  )
  expect(canvasSource).toContain(
    "ensureConditionElseIfBranches(props.graph.nodes)"
  )
})

test("reply node is pinned and exposes both reply modes", () => {
  expect(source).toContain('"reply-node": "指定回复"')
  expect(source).toContain('node.type === "reply-node"')
  expect(source).toContain('config.reply_type ?? "custom"')
  expect(source).toContain('updateConfig({ fields: [path, description] })')
  expect(source).toContain('reference={`{{${nodeId}.answer}}`}')
  expect(canvasSource).toContain("WORKFLOW_NODE_TYPES.map")
})

test("variable picker shows translated names without changing references", () => {
  const variablePicker = source.slice(
    source.indexOf("function VariablePicker"),
    source.indexOf("function TextEditor")
  )

  expect(variablePicker.match(/\{t\(field\.label\)\}/g)).toHaveLength(2)
  expect(variablePicker).toContain('`{{global.${field.value}}}`')
  expect(variablePicker).toContain('`{{start.${field.value}}}`')
  expect(variablePicker).toContain('source?.data.type === "knowledge"')
  expect(variablePicker).toContain("KNOWLEDGE_OUTPUT_FIELDS.find")
  expect(variablePicker).toContain("{displayLabel}")
  expect(variablePicker).not.toContain("<BracesIcon")
})

test("output fields use translated labels and confirm successful copies", () => {
  expect(source).toContain('variable: { value: "变量值" }')
  expect(source).toContain('code: { result: "执行结果", stdout: "标准输出", stderr: "错误输出" }')
  expect(source).toContain('displayValue={outputFieldLabel(node.type, field, t)}')
  expect(source).toContain("reference={`{{${id}.${field}}}`}")
  expect(source).toContain("void copyText(reference)")
  expect(source).toContain('notify("success", t("已复制"))')
})

test("Python code node orders inputs, code, and outputs", () => {
  const codeConfig = source.slice(
    source.indexOf('{node.type === "code" ? ('),
    source.indexOf("export function WorkflowNodeCard")
  )
  const card = source.slice(
    source.indexOf("export function WorkflowNodeCard"),
    source.indexOf("function OutputFieldRow")
  )

  expect(codeConfig.indexOf("-code-inputs")).toBeLessThan(
    codeConfig.indexOf("-code-body")
  )
  expect(card).toContain(
    '["knowledge", "llm", "condition", "reply-node", "code"]'
  )
  expect(card.indexOf("<NodeConfigFields")).toBeLessThan(
    card.lastIndexOf('node.type === "code"')
  )
})

test("condition node uses ordered branches and stable branch handles", () => {
  const conditionEditor = source.slice(
    source.indexOf("function ConditionEditor"),
    source.indexOf("function NodeConfigFields")
  )

  expect(source).toContain("CONDITION_COMPARE_OPTIONS")
  expect(
    source
      .slice(
        source.indexOf("const CONDITION_COMPARE_OPTIONS"),
        source.indexOf("const CONDITION_VALUELESS_COMPARE")
      )
      .match(/\{ value: /g)
  ).toHaveLength(16)
  expect(source).toContain('value: "is_not_true"')
  expect(conditionEditor).toContain('t("添加条件")')
  expect(conditionEditor).toContain('t("添加分支")')
  expect(conditionEditor).toContain('reference={`{{${nodeId}.branch_name}}`}')
  expect(conditionEditor).toContain("id={branch.id}")
  expect(conditionEditor).toContain("title={displayType}")
  expect(conditionEditor).toContain('!right-[-1.375rem]')
  expect(conditionEditor).toContain('border-input')
  expect(source).toContain('node.type === "condition" && expanded')
  expect(source).toContain('handle && node.type !== "condition"')
  expect(canvasSource).toContain("nextHandles.has(String(edge.sourceHandle ?? \"\"))")
  expect(source).toContain('node.type === "condition"\n          ? "w-80"')
  expect(conditionEditor).toContain(
    'rounded-lg border border-border/70 bg-muted/20 p-2'
  )
  expect(conditionEditor).toContain(
    'grid-cols-[7rem_minmax(0,1fr)_1.75rem]'
  )
  expect(conditionEditor).toContain(
    'grid-cols-[minmax(0,1fr)_1.75rem]'
  )
  expect(conditionEditor).toContain('placeholder={t("比较值")}')
  expect(conditionEditor).toContain('t("未命中以上条件时执行")')
  expect(conditionEditor).toContain(
    'branch.type === "ELSE IF 1" ? "ELSE IF" : branch.type'
  )
  expect(conditionEditor).toContain(
    'source?.data.type === "start" ? t("开始节点")'
  )
})

test("saving does not remount or recenter the workflow canvas", () => {
  const saveDraft = detailSource.slice(
    detailSource.indexOf("async function saveDraft"),
    detailSource.indexOf("async function handleSaveAll")
  )
  const restoreVersion = detailSource.slice(
    detailSource.indexOf("async function handleRestore"),
    detailSource.indexOf("if (isLoading")
  )

  expect(detailSource).toContain(
    'key={`${definition.id}:${canvasGeneration}`}'
  )
  expect(detailSource).not.toContain(
    'key={`${definition.id}:${definition.revision}`}'
  )
  expect(saveDraft).not.toContain("setCanvasGeneration")
  expect(restoreVersion).toContain(
    "setCanvasGeneration((current) => current + 1)"
  )
})

test("workflow debugging uses an anchored canvas window", () => {
  const debugPanel = detailSource.slice(
    detailSource.indexOf("{runOpen ? ("),
    detailSource.indexOf('<Dialog open={historyOpen}')
  )

  expect(debugPanel).toContain('<aside\n                  role="dialog"')
  expect(debugPanel).toContain('"absolute z-40')
  expect(debugPanel).toContain('sm:w-96')
  expect(debugPanel).toContain("runExpanded")
  expect(debugPanel).toContain("<Maximize2Icon")
  expect(debugPanel).toContain("<Minimize2Icon")
  expect(debugPanel).toContain("<SendIcon")
  expect(debugPanel).toContain("form.interactionConfig.prologue")
  expect(debugPanel).toContain("currentRun.outputs")
  expect(debugPanel).toContain("bg-background/98")
  expect(debugPanel).toContain("focus-within:shadow-md")
  expect(debugPanel).toContain("form.interactionConfig.file_upload")
  expect(debugPanel).toContain("acceptedUploadExtensions(")
  expect(debugPanel).toContain("<AgentAttachmentList")
  expect(debugPanel).toContain("<PaperclipIcon")
  expect(detailSource).toContain("uploadWorkflowFiles(")
  expect(debugPanel).not.toContain('id="workflow-run-version"')
  expect(debugPanel).not.toContain('{t("运行版本")}')
  expect(debugPanel).not.toContain("bg-gradient-to-r")
  expect(debugPanel).not.toContain("border-dashed")
  expect(detailSource).not.toContain("<Dialog open={runOpen}")
  expect(detailSource).not.toContain("runDetailsOpen")
})

test("LLM advanced parameters live behind the card settings button", () => {
  const advancedDialog = source.slice(
    source.indexOf("function LlmSettingsDialog"),
    source.indexOf("function NodeConfigFields")
  )
  const nodeConfigFields = source.slice(
    source.indexOf("function NodeConfigFields"),
    source.indexOf("export function WorkflowNodeCard")
  )

  expect(source).toContain(
    '["llm", "knowledge", "reply-node"].includes(node.type)'
  )
  expect(source).toContain("<SettingsIcon")
  expect(source).toContain("<LlmSettingsDialog")
  expect(advancedDialog).toContain("${nodeId}-llm-temperature")
  expect(advancedDialog).toContain("${nodeId}-llm-reasoning-content")
  expect(advancedDialog).toContain('role="switch"')
  expect(advancedDialog).not.toContain("<JsonEditor")
  expect(nodeConfigFields).not.toContain("${nodeId}-llm-temperature")
  expect(nodeConfigFields).not.toContain("${nodeId}-llm-reasoning-content")
})

test("LLM model selector shows the effective model and icon", () => {
  expect(source).toContain('import ModelIcon from "@lobehub/icons/es/features/ModelIcon"')
  expect(source).toContain("const selectedModelId = String(config.model_id ?? agent.model_id ?? \"\")")
  expect(source).toContain("selectedModel?.name")
  expect(source).toContain("<ModelIcon")
  expect(source).toContain('<DropdownMenu modal={false}>')
  expect(source).not.toContain('id={`${nodeId}-llm-model`}\n              className="h-9 rounded-md border bg-background px-2 text-sm"')
})

test("LLM dialogue history uses the anchored app dropdown", () => {
  const dialogueMenu = source.slice(
    source.indexOf('id={`${nodeId}-llm-dialogue-type`}'),
    source.indexOf('id={`${nodeId}-llm-dialogue`}', source.indexOf('id={`${nodeId}-llm-dialogue-type`}'))
  )

  expect(dialogueMenu).toContain('className="h-7 w-40 justify-between')
  expect(dialogueMenu).toContain("min-w-40")
  expect(dialogueMenu).toContain("whitespace-nowrap")
  expect(dialogueMenu).toContain('["WORKFLOW", "整条流程历史"]')
  expect(dialogueMenu).not.toContain("<select")
})

test("LLM outputs use translated labels at the bottom of its settings", () => {
  const nodeConfigFields = source.slice(
    source.indexOf("function NodeConfigFields"),
    source.indexOf("export function WorkflowNodeCard")
  )

  expect(source).toContain('{ field: "text", label: "模型回复" }')
  expect(source).toContain(
    '{ field: "reasoning_content", label: "思考过程" }'
  )
  expect(nodeConfigFields).toContain('t("输出参数")')
  expect(nodeConfigFields).toContain('displayValue={t(item.label)}')
  expect(nodeConfigFields).toContain(
    'reference={`{{${nodeId}.${item.field}}}`}'
  )
  expect(nodeConfigFields.indexOf("{LLM_OUTPUT_FIELDS.map")).toBeGreaterThan(
    nodeConfigFields.indexOf('t("返回内容")')
  )
  expect(source).toContain(
    '!["knowledge", "llm", "condition", "reply-node", "code"].includes(node.type)'
  )
})

test("knowledge search mode uses the anchored app dropdown", () => {
  expect(source).toContain('id={`${nodeId}-knowledge-mode-label`}')
  expect(source).toContain('aria-labelledby={`${nodeId}-knowledge-mode-label`}')
  expect(source).toContain('side="bottom"')
  expect(source).toContain('align="end"')
  expect(source).toContain(
    "[&_[data-slot=dropdown-menu-item]]:text-[11px]"
  )
  expect(source).toContain(
    'className="w-(--radix-dropdown-menu-trigger-width) min-w-24"'
  )
  expect(source).not.toContain('<select\n                  id={`${nodeId}-knowledge-mode`}')
})

test("knowledge node presents grouped settings and four documented outputs", () => {
  expect(source).toContain(
    '["llm", "knowledge", "reply-node"].includes(node.type)'
  )
  expect(source).toContain('t("节点设置")')
  expect(source).toContain('t("检索范围")')
  expect(source).toContain('className="mb-1 text-xs font-medium"')
  expect(source).toContain(
    'className="h-8 w-full justify-between px-2.5 text-xs font-normal"'
  )
  expect(source).toContain('t("检索参数")')
  expect(source).toContain('t("输出参数")')
  expect(source).toContain('{ field: "paragraph_list", label: "检索结果的分段列表" }')
  expect(source).toContain('field: "is_hit_handling_method_list"')
  expect(source).toContain('{ field: "data", label: "检索结果" }')
  expect(source).toContain('{ field: "directly_return", label: "满足直接回答的分段内容" }')
  expect(source).toContain('displayValue={t(item.label)}')
  expect(source).toContain('reference={`{{${nodeId}.${item.field}}}`}')
  expect(source).toContain('<OutputFieldRow')
  expect(source.match(/<NumberStepper/g)?.length).toBe(3)
  expect(source).toContain('grid h-8 w-20 grid-cols-[minmax(0,1fr)_1.25rem]')
  expect(source).toContain('px-1 text-center text-xs')
  expect(source).toContain('aria-label={t("增加数值")}')
  expect(source).toContain('aria-label={t("减少数值")}')
  expect(source).toContain('max={1}')
  expect(source).toContain('grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5')
  expect(source).toContain('flex w-full min-w-0 items-center gap-2 overflow-hidden')
  expect(source).toContain('w-full min-w-0 resize-y rounded-md border')
  expect(source).not.toContain('knowledge: [\n      "content",\n      "hits"')
})

test("workflow nodes select workspace resources directly", () => {
  expect(source).toContain("const availableKnowledge = knowledgeBases.filter(")
  expect(source).toContain('item.permission !== "none"')
  expect(source).toContain("const availableMcp = mcpServers")
  expect(source).toContain('tool.policy_mode === "read_only"')
  expect(source).not.toContain("agent.knowledge_base_ids.includes")
  expect(source).not.toContain("const boundMcp = agent.mcp_tools")
  expect(source).not.toContain('<select\n              id={`${nodeId}-mcp-tool`}')
})

test("workflow app settings no longer expose resource bindings", () => {
  const knowledgeSection = appConfigSource.slice(
    appConfigSource.indexOf('aria-expanded={isKnowledgeOpen}') - 800,
    appConfigSource.indexOf('aria-expanded={isMcpOpen}')
  )
  const mcpSection = appConfigSource.slice(
    appConfigSource.indexOf('aria-expanded={isMcpOpen}') - 800,
    appConfigSource.indexOf('htmlFor="agent-status"')
  )
  expect(knowledgeSection).toContain('form.id && form.appType === "agent"')
  expect(mcpSection).toContain('form.id && form.appType === "agent"')
  expect(appConfigSource).toContain(
    'open={form.appType === "agent" && resourcePicker === "knowledge"}'
  )
  expect(appConfigSource).toContain(
    'open={form.appType === "agent" && resourcePicker === "mcp"}'
  )
  expect(detailSource).toContain('t("配置工作流的默认模型。")')
  expect(agentsPageSource).toContain(
    'form.appType === "workflow" ? [] : form.mcpTools'
  )
  expect(agentsPageSource).toContain(
    'form.appType === "workflow" ? [] : form.knowledgeBaseIds'
  )
})
