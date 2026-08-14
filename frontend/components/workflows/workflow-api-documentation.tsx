"use client"

import * as React from "react"
import {
  BookOpenIcon,
  EyeIcon,
  EyeOffIcon,
  KeyRoundIcon,
  LoaderCircleIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import {
  getWorkflowApiDocumentation,
  type WorkflowApiDocumentation as Documentation,
} from "@/lib/api/public-workflows"

export function WorkflowApiDocumentation({
  workflowId,
}: {
  workflowId: string
}) {
  const { t } = useLanguage()
  const [key, setKey] = React.useState("")
  const [visible, setVisible] = React.useState(false)
  const [loading, setLoading] = React.useState(false)
  const [documentation, setDocumentation] =
    React.useState<Documentation | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  async function unlock(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!key.trim() || loading) return
    setLoading(true)
    setError(null)
    try {
      setDocumentation(
        await getWorkflowApiDocumentation(workflowId, key.trim())
      )
      setKey("")
      setVisible(false)
    } catch {
      setError(t("API Key 无效、已撤销或工作流未发布。"))
    } finally {
      setLoading(false)
    }
  }

  const base = documentation?.base_path ?? ""
  const runExample = documentation
    ? JSON.stringify(
        {
          question: "string",
          conversation_id: "uuid (optional)",
          file_ids: ["uuid (optional)"],
        },
        null,
        2
      )
    : ""
  const endpoints = documentation
    ? ([
        [
          "POST",
          `${base}/runs`,
          t("创建运行"),
          t("创建新的工作流运行；question 会作为开始节点的 question 输出，省略 conversation_id 时开始新对话。"),
          runExample,
        ],
        [
          "GET",
          `${base}/runs/{run_id}`,
          t("查询运行"),
          t("按运行 ID 查询节点进度和最终输出。"),
          `{"id":"uuid","status":"succeeded","inputs":{"question":"string"},"outputs":{},"progress":[]}`,
        ],
        [
          "GET",
          `${base}/runs/{run_id}/stream`,
          t("订阅运行流"),
          t("以 NDJSON 订阅节点进度和终态事件。"),
          `{"type":"progress","event":{"node_id":"node","status":"succeeded"}}\n{"type":"complete","run":{"status":"succeeded","outputs":{}}}`,
        ],
      ] as const)
    : []

  return (
    <main className="min-h-svh bg-muted/20">
      <header className="border-b bg-background">
        <div className="mx-auto flex min-h-16 max-w-5xl items-center gap-3 px-4 sm:px-6">
          <span className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <BookOpenIcon className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold">
              {documentation?.workflow_name ?? t("工作流 API 文档")}
            </h1>
            <p className="truncate text-xs text-muted-foreground">
              {t("此页面只显示当前工作流的 API 接口。")}
            </p>
          </div>
          {documentation ? (
            <Badge variant="outline">{t("文档已解锁")}</Badge>
          ) : null}
        </div>
      </header>
      <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6 sm:py-12">
        {!documentation ? (
          <section className="mx-auto max-w-md rounded-lg border bg-background p-6 shadow-xs">
            <h2 className="text-base font-semibold">
              {t("使用 API Key 查看文档")}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("输入该工作流的有效 API Key 后查看专属接口文档。")}
            </p>
            <form className="mt-5 space-y-4" onSubmit={unlock}>
              <label className="block text-sm font-medium">
                {t("API Key")}
                <span className="relative mt-1.5 block">
                  <Input
                    type={visible ? "text" : "password"}
                    value={key}
                    onChange={(event) => setKey(event.target.value)}
                    className="pr-11 font-mono"
                    placeholder="nxf_..."
                    autoFocus
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className="absolute top-1/2 right-1 -translate-y-1/2"
                    aria-label={t(visible ? "隐藏 API Key" : "显示 API Key")}
                    onClick={() => setVisible((value) => !value)}
                  >
                    {visible ? <EyeOffIcon /> : <EyeIcon />}
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
                disabled={!key.trim() || loading}
              >
                {loading ? (
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
              <code className="text-sm">
                Authorization: Bearer &lt;API_KEY&gt;
              </code>
            </section>
            {endpoints.map(([method, path, title, description, example]) => (
              <section key={path} className="border-b py-7">
                <div className="flex items-center gap-3">
                  <Badge variant={method === "POST" ? "default" : "secondary"}>
                    {method}
                  </Badge>
                  <code className="break-all text-sm font-medium">{path}</code>
                </div>
                <h2 className="mt-4 text-base font-semibold">{title}</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {description}
                </p>
                <pre className="mt-5 overflow-x-auto rounded-lg border bg-muted/40 p-4 text-xs leading-6">
                  <code>{example}</code>
                </pre>
              </section>
            ))}
          </>
        )}
      </div>
    </main>
  )
}
