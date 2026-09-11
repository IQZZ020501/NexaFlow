"use client"

import * as React from "react"
import {
  CheckIcon,
  ChevronRightIcon,
  Code2Icon,
  CopyIcon,
  KeyRoundIcon,
  LockKeyholeIcon,
  ShieldCheckIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useLanguage } from "@/contexts/language-provider"
import { apiUrl } from "@/lib/api-client"
import { copyText } from "@/lib/clipboard"
import { cn } from "@/lib/utils"
import { PHONE_LIST_QUERY, useMediaQuery } from "@/lib/use-media-query"

type AccessMode = "session" | "api_key"
type HttpMethod = "GET" | "POST"
type CodeLanguage = "curl" | "javascript" | "python"

type ApiParameter = {
  name: string
  location?: "path" | "query"
  type: string
  required: boolean
  defaultValue?: string
  description: string
}

type ApiResponse = {
  status: string
  description: string
}

type CodeSample = {
  language: CodeLanguage
  label: string
  code: string
}

type EndpointDocumentation = {
  id: string
  method: HttpMethod
  path: string
  title: string
  description: string
  parameters?: ApiParameter[]
  requestBody?: ApiParameter[]
  responses: ApiResponse[]
  codeSamples: CodeSample[]
  responseLabel: string
  responseExample: string
}

type NavigationItem = {
  href: string
  label: string
  method?: HttpMethod
}

type AgentApiReferenceProps = {
  agentName: string
  basePath: string
  accessMode: AccessMode
  onChangeApiKey: () => void
}

/**
 * Converts a configured API path into the absolute URL shown in examples.
 *
 * @param origin - Browser origin used for same-origin API deployments
 * @param basePath - Agent-specific API path returned by the backend
 * @returns An absolute URL when possible, otherwise the configured API path
 */
function resolveBaseUrl(origin: string, basePath: string) {
  const configuredPath = apiUrl(basePath)
  if (/^https?:\/\//i.test(configuredPath)) return configuredPath
  if (!/^https?:\/\//i.test(origin)) return configuredPath
  return new URL(configuredPath, origin).toString().replace(/\/$/, "")
}

/**
 * Renders an accessible copy control with inline success feedback.
 *
 * @param value - Text copied to the clipboard
 * @param label - Accessible label for the copy action
 */
function CopyButton({ value, label }: { value: string; label: string }) {
  const { t } = useLanguage()
  const [copied, setCopied] = React.useState(false)

  async function handleCopy() {
    await copyText(value)
    setCopied(true)
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="xs"
      aria-label={label}
      title={label}
      onClick={() => void handleCopy()}
    >
      {copied ? <CheckIcon /> : <CopyIcon />}
      {t(copied ? "已复制" : "复制")}
    </Button>
  )
}

/**
 * Displays a compact table of API parameters.
 *
 * @param parameters - Parameter contracts to render
 * @param showLocation - Whether to show path/query placement
 */
function ParameterTable({
  parameters,
  showLocation = false,
}: {
  parameters: ApiParameter[]
  showLocation?: boolean
}) {
  const { t } = useLanguage()
  const isPhoneListLayout = useMediaQuery(PHONE_LIST_QUERY)

  return (
    <>
      {/* Phones: one card per parameter, so nothing needs sideways scrolling. */}
      {isPhoneListLayout ? (
        <ul className="flex flex-col gap-2">
        {parameters.map((parameter) => (
          <li
            key={`${parameter.location ?? "body"}-${parameter.name}`}
            className="rounded-lg border bg-background p-3"
          >
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <code className="text-xs font-medium break-all">
                {parameter.name}
              </code>
              {showLocation && parameter.location ? (
                <Badge
                  variant="outline"
                  className="h-5 rounded px-1.5 font-mono text-[10px] font-normal"
                >
                  {parameter.location}
                </Badge>
              ) : null}
              <code className="text-xs text-muted-foreground">
                {parameter.type}
              </code>
            </div>
            <p className="mt-2 text-xs leading-5 break-words text-muted-foreground">
              {parameter.description}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>
                {t("必填")}: {t(parameter.required ? "是" : "否")}
              </span>
              <span>
                {t("默认值")}:{" "}
                <code className="break-all">
                  {parameter.defaultValue ?? "—"}
                </code>
              </span>
            </div>
          </li>
        ))}
        </ul>
      ) : null}

      <div className="hidden overflow-x-auto rounded-lg border md:block">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="border-b bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-4 py-2.5 font-medium">
                {t("名称")}
              </th>
              {showLocation ? (
                <th scope="col" className="px-4 py-2.5 font-medium">
                  {t("位置")}
                </th>
              ) : null}
              <th scope="col" className="px-4 py-2.5 font-medium">
                {t("类型")}
              </th>
              <th scope="col" className="px-4 py-2.5 font-medium">
                {t("必填")}
              </th>
              <th scope="col" className="px-4 py-2.5 font-medium">
                {t("默认值")}
              </th>
              <th scope="col" className="px-4 py-2.5 font-medium">
                {t("说明")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {parameters.map((parameter) => (
              <tr key={`${parameter.location ?? "body"}-${parameter.name}`}>
                <td className="px-4 py-3 align-top">
                  <code className="text-xs font-medium">{parameter.name}</code>
                </td>
                {showLocation ? (
                  <td className="px-4 py-3 align-top text-xs text-muted-foreground">
                    {parameter.location}
                  </td>
                ) : null}
                <td className="px-4 py-3 align-top">
                  <code className="text-xs text-muted-foreground">
                    {parameter.type}
                  </code>
                </td>
                <td className="px-4 py-3 align-top text-xs">
                  {t(parameter.required ? "是" : "否")}
                </td>
                <td className="px-4 py-3 align-top">
                  <code className="text-xs text-muted-foreground">
                    {parameter.defaultValue ?? "—"}
                  </code>
                </td>
                <td className="px-4 py-3 leading-5 text-muted-foreground">
                  {parameter.description}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

/**
 * Displays documented HTTP responses for an endpoint.
 *
 * @param responses - Status codes and their meanings
 */
function ResponseTable({ responses }: { responses: ApiResponse[] }) {
  const { t } = useLanguage()

  return (
    <div className="overflow-hidden rounded-lg border">
      <table className="w-full text-left text-sm">
        <thead className="border-b bg-muted/40 text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="w-28 px-4 py-2.5 font-medium">
              {t("状态码")}
            </th>
            <th scope="col" className="px-4 py-2.5 font-medium">
              {t("含义")}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {responses.map((response) => (
            <tr key={response.status}>
              <td className="px-4 py-3 align-top">
                <code
                  className={cn(
                    "rounded px-1.5 py-0.5 text-xs font-semibold",
                    response.status.startsWith("2")
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                      : "bg-amber-500/10 text-amber-700 dark:text-amber-400"
                  )}
                >
                  {response.status}
                </code>
              </td>
              <td className="px-4 py-3 leading-5 text-muted-foreground">
                {response.description}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * Renders language tabs and a copyable API request example.
 *
 * @param samples - Request examples grouped by programming language
 */
function CodeSamples({ samples }: { samples: CodeSample[] }) {
  const { t } = useLanguage()
  const [selected, setSelected] = React.useState<CodeLanguage>("curl")
  const activeSample =
    samples.find((sample) => sample.language === selected) ?? samples[0]

  return (
    <div className="overflow-hidden rounded-lg border bg-zinc-950 text-zinc-100">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 px-2 py-1.5">
        <div
          className="flex min-w-0 items-center gap-1 overflow-x-auto"
          role="tablist"
          aria-label={t("代码示例")}
        >
          {samples.map((sample) => (
            <button
              key={sample.language}
              type="button"
              role="tab"
              aria-selected={sample.language === activeSample.language}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs transition-colors",
                sample.language === activeSample.language
                  ? "bg-white/10 text-white"
                  : "text-zinc-400 hover:text-zinc-200"
              )}
              onClick={() => setSelected(sample.language)}
            >
              {sample.label}
            </button>
          ))}
        </div>
        <CopyButton value={activeSample.code} label={t("复制代码")} />
      </div>
      <pre
        role="tabpanel"
        className="max-h-[420px] overflow-auto p-4 text-xs leading-6"
      >
        <code>{activeSample.code}</code>
      </pre>
    </div>
  )
}

/**
 * Renders one complete endpoint reference section.
 *
 * @param endpoint - Endpoint contract, examples, and response details
 */
function EndpointSection({ endpoint }: { endpoint: EndpointDocumentation }) {
  const { t } = useLanguage()

  return (
    <section id={endpoint.id} className="scroll-mt-32 lg:scroll-mt-24 border-t py-10 sm:py-12">
      <div className="flex flex-wrap items-center gap-2.5">
        <Badge
          variant={endpoint.method === "POST" ? "default" : "secondary"}
          className={cn(
            "h-6 min-w-14 justify-center border-0 font-mono",
            endpoint.method === "POST" &&
              "bg-sky-600 text-white dark:bg-sky-500"
          )}
        >
          {endpoint.method}
        </Badge>
        <code className="min-w-0 text-sm font-semibold break-all">
          {endpoint.path}
        </code>
      </div>
      <h2 className="mt-5 text-xl font-semibold tracking-tight">
        {endpoint.title}
      </h2>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
        {endpoint.description}
      </p>

      {endpoint.parameters?.length ? (
        <div className="mt-8">
          <h3 className="mb-3 text-sm font-semibold">{t("参数")}</h3>
          <ParameterTable parameters={endpoint.parameters} showLocation />
        </div>
      ) : null}

      {endpoint.requestBody?.length ? (
        <div className="mt-8">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">{t("请求体")}</h3>
            <code className="text-xs text-muted-foreground">
              application/json
            </code>
          </div>
          <ParameterTable parameters={endpoint.requestBody} />
        </div>
      ) : null}

      <div className="mt-8">
        <h3 className="mb-3 text-sm font-semibold">{t("请求示例")}</h3>
        <CodeSamples samples={endpoint.codeSamples} />
      </div>

      <div className="mt-8">
        <h3 className="mb-3 text-sm font-semibold">{t("响应")}</h3>
        <ResponseTable responses={endpoint.responses} />
      </div>

      <div className="mt-8">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold">{endpoint.responseLabel}</h3>
          <code className="text-xs text-muted-foreground">
            {endpoint.id === "stream-run"
              ? "application/x-ndjson"
              : "application/json"}
          </code>
        </div>
        <div className="overflow-hidden rounded-lg border bg-zinc-950 text-zinc-100">
          <div className="flex justify-end border-b border-white/10 px-2 py-1.5">
            <CopyButton
              value={endpoint.responseExample}
              label={t("复制代码")}
            />
          </div>
          <pre className="max-h-[420px] overflow-auto p-4 text-xs leading-6">
            <code>{endpoint.responseExample}</code>
          </pre>
        </div>
      </div>
    </section>
  )
}

/**
 * Builds complete request examples for all documented Agent API endpoints.
 *
 * @param baseUrl - Agent-specific API base URL
 * @param sampleGoal - Localized sample task passed to the Agent
 * @returns Three endpoint definitions ready for rendering
 */
function buildEndpoints(
  baseUrl: string,
  sampleGoal: string,
  t: ReturnType<typeof useLanguage>["t"]
): EndpointDocumentation[] {
  const runUrl = `${baseUrl}/runs`
  const runResourceUrl = `${runUrl}/{run_id}`
  const streamUrl = `${runResourceUrl}/stream`
  const requestBody = JSON.stringify({ goal: sampleGoal }, null, 2)
  const runResponse = `{
  "id": "9fd24461-6f41-4dd8-9588-860a3b5f41b6",
  "conversation_id": "88bb99f3-a92c-4f5a-b874-0b88f5ac49b9",
  "regenerated_from_run_id": null,
  "question": ${JSON.stringify(sampleGoal)},
  "attachments": [],
  "status": "queued",
  "result": "",
  "error": null,
  "progress": [],
  "created_at": "2026-09-10T08:30:00Z",
  "started_at": null,
  "finished_at": null,
  "updated_at": "2026-09-10T08:30:00Z",
  "feedback": null,
  "feedback_updated_at": null
}`
  const streamResponse = `{"type":"run","sequence":1,"run":{"id":"9fd24461-6f41-4dd8-9588-860a3b5f41b6","status":"running"}}
{"type":"progress","sequence":2,"event":{"id":"knowledge-1","type":"knowledge","status":"succeeded","stage":"succeeded","turn":1,"count":3,"reasoning":"","hits":[]}}
{"type":"answer_delta","live_sequence":"0-1","delta":"..."}
{"type":"complete","sequence":3,"run":{"id":"9fd24461-6f41-4dd8-9588-860a3b5f41b6","status":"succeeded","result":"..."}}`
  const sharedErrors = [
    { status: "401", description: t("认证失败或 API Key 已撤销。") },
    {
      status: "404",
      description: t("Agent 未发布，或运行不属于当前 API Key。"),
    },
  ]

  return [
    {
      id: "create-run",
      method: "POST",
      path: "/runs",
      title: t("创建运行"),
      description: t("创建一个异步运行，并立即返回当前运行快照。"),
      requestBody: [
        {
          name: "goal",
          type: "string",
          required: true,
          description: t("要交给 Agent 的任务，长度为 1–4000 个字符。"),
        },
        {
          name: "conversation_id",
          type: "string | null",
          required: false,
          description: t("已有对话 ID；省略时创建新对话，最长 36 个字符。"),
        },
      ],
      responses: [
        { status: "201", description: t("运行已创建。") },
        ...sharedErrors,
        {
          status: "409",
          description: t(
            "Agent 当前发布配置无法执行（例如 Tool 定义已变更）。"
          ),
        },
        { status: "422", description: t("请求字段或查询参数无效。") },
        {
          status: "429",
          description: t("超过运行频率限制；请根据 Retry-After 重试。"),
        },
        { status: "503", description: t("运行服务暂时不可用。") },
      ],
      codeSamples: [
        {
          language: "curl",
          label: t("cURL"),
          code: `curl --request POST '${runUrl}' \\
  --header 'Authorization: Bearer <API_KEY>' \\
  --header 'Content-Type: application/json' \\
  --data '${requestBody}'`,
        },
        {
          language: "javascript",
          label: t("JavaScript"),
          code: `const response = await fetch('${runUrl}', {
  method: 'POST',
  headers: {
    Authorization: 'Bearer <API_KEY>',
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ goal: ${JSON.stringify(sampleGoal)} }),
});

if (!response.ok) throw new Error(\`HTTP \${response.status}\`);
const run = await response.json();`,
        },
        {
          language: "python",
          label: t("Python"),
          code: `import requests

response = requests.post(
    '${runUrl}',
    headers={'Authorization': 'Bearer <API_KEY>'},
    json={'goal': ${JSON.stringify(sampleGoal)}},
    timeout=30,
)
response.raise_for_status()
run = response.json()`,
        },
      ],
      responseLabel: t("响应示例"),
      responseExample: runResponse,
    },
    {
      id: "get-run",
      method: "GET",
      path: "/runs/{run_id}",
      title: t("查询运行"),
      description: t("读取运行的当前状态、最终回答和安全执行进度。"),
      parameters: [
        {
          name: "run_id",
          location: "path",
          type: "string",
          required: true,
          description: t("运行 ID，由创建运行接口返回。"),
        },
      ],
      responses: [
        { status: "200", description: t("请求成功。") },
        ...sharedErrors,
      ],
      codeSamples: [
        {
          language: "curl",
          label: t("cURL"),
          code: `curl '${runResourceUrl}' \\
  --header 'Authorization: Bearer <API_KEY>'`,
        },
        {
          language: "javascript",
          label: t("JavaScript"),
          code: `const response = await fetch('${runResourceUrl}', {
  headers: { Authorization: 'Bearer <API_KEY>' },
});

if (!response.ok) throw new Error(\`HTTP \${response.status}\`);
const run = await response.json();`,
        },
        {
          language: "python",
          label: t("Python"),
          code: `import requests

response = requests.get(
    '${runResourceUrl}',
    headers={'Authorization': 'Bearer <API_KEY>'},
    timeout=30,
)
response.raise_for_status()
run = response.json()`,
        },
      ],
      responseLabel: t("响应示例"),
      responseExample: runResponse
        .replace('"status": "queued"', '"status": "succeeded"')
        .replace('"result": ""', '"result": "..."'),
    },
    {
      id: "stream-run",
      method: "GET",
      path: "/runs/{run_id}/stream",
      title: t("订阅运行流"),
      description: t("通过 NDJSON 持续接收进度、回答增量和最终状态。"),
      parameters: [
        {
          name: "run_id",
          location: "path",
          type: "string",
          required: true,
          description: t("运行 ID，由创建运行接口返回。"),
        },
        {
          name: "after",
          location: "query",
          type: "integer",
          required: false,
          defaultValue: "0",
          description: t("历史事件序号，从该序号之后继续读取。"),
        },
        {
          name: "live_after",
          location: "query",
          type: "string",
          required: false,
          defaultValue: "0-0",
          description: t("实时流游标，格式为 partition-sequence。"),
        },
      ],
      responses: [
        { status: "200", description: t("NDJSON 事件流已建立。") },
        ...sharedErrors,
        { status: "422", description: t("请求字段或查询参数无效。") },
      ],
      codeSamples: [
        {
          language: "curl",
          label: t("cURL"),
          code: `curl --no-buffer '${streamUrl}?after=0&live_after=0-0' \\
  --header 'Authorization: Bearer <API_KEY>' \\
  --header 'Accept: application/x-ndjson'`,
        },
        {
          language: "javascript",
          label: t("JavaScript"),
          code: `const response = await fetch(
  '${streamUrl}?after=0&live_after=0-0',
  { headers: { Authorization: 'Bearer <API_KEY>' } },
);

if (!response.ok || !response.body) {
  throw new Error(\`HTTP \${response.status}\`);
}

const reader = response.body.getReader();
const decoder = new TextDecoder();
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  console.log(decoder.decode(value, { stream: true }));
}`,
        },
        {
          language: "python",
          label: t("Python"),
          code: `import json
import requests

with requests.get(
    '${streamUrl}',
    headers={'Authorization': 'Bearer <API_KEY>'},
    params={'after': 0, 'live_after': '0-0'},
    stream=True,
    timeout=300,
) as response:
    response.raise_for_status()
    for line in response.iter_lines():
        if line:
            event = json.loads(line)
            print(event)`,
        },
      ],
      responseLabel: t("流事件示例"),
      responseExample: streamResponse,
    },
  ]
}

/**
 * Renders the complete Agent API reference after documentation access succeeds.
 *
 * @param agentName - Published Agent name
 * @param basePath - Agent-specific API base path
 * @param accessMode - Whether documentation was opened by session or API key
 * @param onChangeApiKey - Returns to the API key unlock form
 */
export function AgentApiReference({
  agentName,
  basePath,
  accessMode,
  onChangeApiKey,
}: AgentApiReferenceProps) {
  const { t } = useLanguage()
  const [origin, setOrigin] = React.useState("")

  React.useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      setOrigin(window.location.origin)
    })
    return () => window.cancelAnimationFrame(frame)
  }, [])

  const baseUrl = resolveBaseUrl(origin, basePath)
  const endpoints = buildEndpoints(
    baseUrl,
    t("请总结客户反馈中的主要问题。"),
    t
  )
  const navigation: NavigationItem[] = [
    { href: "#overview", label: t("概览") },
    { href: "#authentication", label: t("认证方式") },
    ...endpoints.map((endpoint) => ({
      href: `#${endpoint.id}`,
      label: endpoint.title,
      method: endpoint.method,
    })),
  ]

  return (
    <main className="min-h-svh bg-background">
      <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/85">
        <div className="mx-auto flex min-h-16 max-w-[1440px] items-center gap-3 px-4 sm:px-6 lg:px-8">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-foreground text-background">
            <Code2Icon className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate text-sm font-semibold">
                {t("Agent API 文档")}
              </span>
              <span className="hidden text-muted-foreground sm:inline">/</span>
              <span className="hidden text-xs text-muted-foreground sm:inline">
                {t("API Reference")}
              </span>
            </div>
            <p className="truncate text-xs text-muted-foreground">
              {t("稳定的 v1 Agent 运行接口")}
            </p>
          </div>
          <Badge variant="outline" className="hidden gap-1.5 sm:flex">
            <ShieldCheckIcon className="size-3.5" />
            {t("文档已解锁")}
          </Badge>
          {accessMode === "api_key" ? (
            <Button type="button" variant="outline" onClick={onChangeApiKey}>
              <KeyRoundIcon />
              <span className="hidden sm:inline">{t("更换 API Key")}</span>
            </Button>
          ) : null}
        </div>
      </header>

      <div className="mx-auto grid w-full max-w-[1440px] lg:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="hidden border-r lg:block">
          <nav
            aria-label={t("内容导航")}
            className="sticky top-16 max-h-[calc(100svh-4rem)] overflow-y-auto px-5 py-8"
          >
            <p className="px-2 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
              {t("API Reference")}
            </p>
            <ul className="mt-3 space-y-1">
              {navigation.map((item) => (
                <li key={item.href}>
                  <a
                    href={item.href}
                    className="group flex min-h-8 items-center gap-2 rounded-md px-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    {item.method ? (
                      <span
                        className={cn(
                          "w-9 font-mono text-[10px] font-semibold",
                          item.method === "POST"
                            ? "text-sky-600 dark:text-sky-400"
                            : "text-emerald-600 dark:text-emerald-400"
                        )}
                      >
                        {item.method}
                      </span>
                    ) : (
                      <ChevronRightIcon className="size-3.5" />
                    )}
                    <span className="truncate">{item.label}</span>
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        </aside>

        <div className="min-w-0 px-4 py-8 sm:px-8 sm:py-12 lg:px-12 xl:px-16">
          <nav
            aria-label={t("内容导航")}
            className="sticky top-16 z-30 -mx-4 mb-8 flex gap-2 overflow-x-auto border-b bg-background/95 px-4 py-3 backdrop-blur sm:-mx-8 sm:px-8 lg:hidden"
          >
            {navigation.map((item) => (
              <a
                key={item.href}
                href={item.href}
                className="shrink-0 rounded-md bg-muted px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground max-sm:inline-flex max-sm:min-h-10 max-sm:items-center"
              >
                {item.method ? `${item.method} ` : ""}
                {item.label}
              </a>
            ))}
          </nav>

          <div className="mx-auto max-w-5xl">
            <section id="overview" className="scroll-mt-32 lg:scroll-mt-24 pb-10 sm:pb-12">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-xs font-semibold tracking-wider text-sky-600 uppercase dark:text-sky-400">
                  {t("API Reference")}
                </p>
                <Badge variant="secondary" className="font-mono">
                  v1
                </Badge>
              </div>
              <h1 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">
                {agentName}
              </h1>
              <p className="mt-4 max-w-3xl text-base leading-7 text-muted-foreground">
                {t(
                  "通过 HTTP 创建 Agent 运行、查询执行状态，并使用 NDJSON 实时接收结果。"
                )}
              </p>

              <div className="mt-8">
                <p className="text-xs font-medium text-muted-foreground">
                  {t("基础地址")}
                </p>
                <div className="mt-2 flex min-w-0 items-center gap-2 rounded-lg border bg-muted/30 py-1.5 pr-1.5 pl-3 shadow-xs">
                  <code
                    className="min-w-0 flex-1 overflow-x-auto py-1 font-mono text-sm whitespace-nowrap"
                    title={baseUrl}
                  >
                    {baseUrl}
                  </code>
                  <span className="shrink-0 border-l pl-1.5">
                    <CopyButton value={baseUrl} label={t("复制地址")} />
                  </span>
                </div>
              </div>
            </section>

            <section
              id="authentication"
              className="scroll-mt-32 lg:scroll-mt-24 border-t py-10 sm:py-12"
            >
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
                  <LockKeyholeIcon className="size-4" />
                </span>
                <div>
                  <h2 className="text-xl font-semibold tracking-tight">
                    {t("认证方式")}
                  </h2>
                  <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                    {t("所有 API 请求都使用 Bearer API Key 认证。")}
                  </p>
                </div>
              </div>

              <div className="mt-6 overflow-hidden rounded-lg border">
                <div className="flex items-center justify-between gap-3 border-b bg-muted/40 px-4 py-2.5">
                  <span className="text-xs font-medium text-muted-foreground">
                    {t("请求头")}
                  </span>
                  <CopyButton
                    value="Authorization: Bearer <API_KEY>"
                    label={t("复制代码")}
                  />
                </div>
                <pre className="overflow-x-auto p-4 text-sm">
                  <code>Authorization: Bearer &lt;API_KEY&gt;</code>
                </pre>
              </div>

              <div className="mt-5 border-l-2 border-sky-500 pl-4">
                <p className="text-sm font-medium">{t("安全提示")}</p>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  {accessMode === "session"
                    ? t(
                        "当前登录状态仅用于查看文档；调用接口时仍需使用 Agent API Key。"
                      )
                    : t("请勿在浏览器前端代码或公开仓库中暴露 API Key。")}
                </p>
              </div>
            </section>

            {endpoints.map((endpoint) => (
              <EndpointSection key={endpoint.id} endpoint={endpoint} />
            ))}
          </div>
        </div>
      </div>
    </main>
  )
}
