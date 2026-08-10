"use client"

import * as React from "react"
import {
  BookOpenIcon,
  EyeIcon,
  EyeOffIcon,
  KeyRoundIcon,
  LoaderCircleIcon,
  LockKeyholeIcon,
  ShieldCheckIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import {
  getAgentApiDocumentation,
  type AgentApiDocumentation as AgentApiDocumentationData,
} from "@/lib/api/agents"

type AgentApiDocumentationProps = {
  agentId: string
}

type EndpointDocumentation = {
  method: "GET" | "POST"
  path: string
  title: string
  description: string
  exampleLabel: string
  example: string
}

function EndpointSection({ endpoint }: { endpoint: EndpointDocumentation }) {
  return (
    <section className="border-b py-7 last:border-b-0">
      <div className="flex flex-wrap items-center gap-3">
        <Badge
          variant={endpoint.method === "POST" ? "default" : "secondary"}
          className="w-14 justify-center font-mono"
        >
          {endpoint.method}
        </Badge>
        <code className="min-w-0 break-all text-sm font-medium">
          {endpoint.path}
        </code>
      </div>
      <h2 className="mt-4 text-base font-semibold">{endpoint.title}</h2>
      <p className="mt-1 text-sm leading-6 text-muted-foreground">
        {endpoint.description}
      </p>
      <p className="mt-5 text-xs font-medium text-muted-foreground">
        {endpoint.exampleLabel}
      </p>
      <pre className="mt-2 overflow-x-auto rounded-lg border bg-muted/40 p-4 text-xs leading-6">
        <code>{endpoint.example}</code>
      </pre>
    </section>
  )
}

export function AgentApiDocumentation({
  agentId,
}: AgentApiDocumentationProps) {
  const { t } = useLanguage()
  const [apiKey, setApiKey] = React.useState("")
  const [documentation, setDocumentation] =
    React.useState<AgentApiDocumentationData | null>(null)
  const [isKeyVisible, setIsKeyVisible] = React.useState(false)
  const [isLoading, setIsLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function handleUnlock(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const key = apiKey.trim()
    if (!key || isLoading) return
    setIsLoading(true)
    setError(null)
    try {
      const response = await getAgentApiDocumentation(agentId, key)
      setDocumentation(response)
      setApiKey("")
      setIsKeyVisible(false)
    } catch {
      setError(t("API Key 无效、已撤销或 Agent 未发布。"))
    } finally {
      setIsLoading(false)
    }
  }

  const basePath = documentation?.base_path ?? ""
  const runResponse = `{
  "id": "uuid",
  "conversation_id": "uuid",
  "question": "string",
  "status": "queued | running | succeeded | failed | cancelled",
  "result": "string",
  "error": null,
  "progress": [
    {
      "id": "opaque-id",
      "type": "analysis | knowledge | tool | answer",
      "status": "running | succeeded | failed",
      "stage": "analyzing | reviewing | completed | running | succeeded | failed",
      "turn": 1,
      "count": null
    }
  ],
  "created_at": "date-time",
  "started_at": null,
  "finished_at": null,
  "updated_at": "date-time"
}`
  const endpoints: EndpointDocumentation[] = documentation
    ? [
        {
          method: "POST",
          path: `${basePath}/runs`,
          title: t("创建运行"),
          description: t(
            "创建新的 Agent 运行；省略 conversation_id 时开始新对话。"
          ),
          exampleLabel: t("请求与响应示例"),
          example: `POST ${basePath}/runs
Authorization: Bearer <API_KEY>
Content-Type: application/json

{
  "goal": "string",
  "conversation_id": "uuid (optional)"
}

${runResponse}`,
        },
        {
          method: "GET",
          path: `${basePath}/runs/{run_id}`,
          title: t("查询运行"),
          description: t("按运行 ID 查询当前状态和最终回答。"),
          exampleLabel: t("响应示例"),
          example: runResponse,
        },
        {
          method: "GET",
          path: `${basePath}/runs/{run_id}/stream`,
          title: t("订阅运行流"),
          description: t("以 NDJSON 订阅安全执行进度、回答增量和终态事件。"),
          exampleLabel: t("流事件示例"),
          example: `GET ${basePath}/runs/{run_id}/stream?after=0&live_after=0-0
Authorization: Bearer <API_KEY>
Accept: application/x-ndjson

{"type":"progress","event":{"id":"opaque-id","type":"knowledge","status":"succeeded","stage":"succeeded","turn":1,"count":3}}
{"type":"answer_delta","delta":"string"}
{"type":"complete","run":${runResponse.replaceAll("\n", "")}}`,
        },
      ]
    : []

  return (
    <main className="min-h-svh bg-muted/20">
      <header className="border-b bg-background">
        <div className="mx-auto flex min-h-16 max-w-5xl items-center gap-3 px-4 sm:px-6">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <BookOpenIcon className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold">
              {documentation?.agent_name ?? t("Agent API 文档")}
            </h1>
            <p className="truncate text-xs text-muted-foreground">
              {t("此页面只显示当前 Agent 的 API 接口。")}
            </p>
          </div>
          {documentation ? (
            <Badge variant="outline" className="gap-1.5">
              <ShieldCheckIcon className="size-3.5" />
              {t("文档已解锁")}
            </Badge>
          ) : null}
        </div>
      </header>

      <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6 sm:py-12">
        {!documentation ? (
          <section className="mx-auto max-w-md rounded-lg border bg-background p-5 shadow-xs sm:p-6">
            <span className="flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <LockKeyholeIcon className="size-5" />
            </span>
            <h2 className="mt-4 text-base font-semibold">
              {t("使用 API Key 查看文档")}
            </h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              {t("输入该 Agent 的有效 API Key 后查看专属接口文档。")}
            </p>
            <form className="mt-5 space-y-4" onSubmit={handleUnlock}>
              <label className="block text-sm font-medium">
                {t("API Key")}
                <span className="relative mt-1.5 block">
                  <Input
                    type={isKeyVisible ? "text" : "password"}
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    className="pr-11 font-mono"
                    placeholder="nxf_..."
                    autoComplete="off"
                    spellCheck={false}
                    maxLength={256}
                    autoFocus
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className="absolute top-1/2 right-1 -translate-y-1/2"
                    aria-label={t(isKeyVisible ? "隐藏 API Key" : "显示 API Key")}
                    title={t(isKeyVisible ? "隐藏 API Key" : "显示 API Key")}
                    onClick={() => setIsKeyVisible((visible) => !visible)}
                  >
                    {isKeyVisible ? <EyeOffIcon /> : <EyeIcon />}
                  </Button>
                </span>
              </label>
              {error ? (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              ) : null}
              <Button
                type="submit"
                className="w-full"
                disabled={!apiKey.trim() || isLoading}
              >
                {isLoading ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : (
                  <KeyRoundIcon />
                )}
                {t("验证并查看")}
              </Button>
            </form>
          </section>
        ) : (
          <>
            <section className="border-b pb-7">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <p className="text-xs font-medium text-muted-foreground">
                    {t("认证方式")}
                  </p>
                  <code className="mt-2 block break-all text-sm">
                    Authorization: Bearer &lt;API_KEY&gt;
                  </code>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {t("每个请求都必须携带该请求头。")}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setDocumentation(null)}
                >
                  <KeyRoundIcon />
                  {t("更换 API Key")}
                </Button>
              </div>
            </section>
            <div>
              {endpoints.map((endpoint) => (
                <EndpointSection key={endpoint.path} endpoint={endpoint} />
              ))}
            </div>
          </>
        )}
      </div>
    </main>
  )
}
