"use client"

import * as React from "react"
import {
  BookOpenIcon,
  EyeIcon,
  EyeOffIcon,
  KeyRoundIcon,
  LoaderCircleIcon,
  LockKeyholeIcon,
} from "lucide-react"

import { AgentApiReference } from "@/components/agents/agent-api-reference"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import {
  getAuthenticatedAgentApiDocumentation,
  getAgentApiDocumentation,
  type AgentApiDocumentation as AgentApiDocumentationData,
} from "@/lib/api/agents"

type AgentApiDocumentationProps = {
  agentId: string
}

/**
 * Displays an Agent API reference using the browser session when available and
 * an API key fallback for external viewers.
 *
 * @param agentId - The identifier of the Agent whose API reference is displayed
 */
export function AgentApiDocumentation({ agentId }: AgentApiDocumentationProps) {
  const { t } = useLanguage()
  const { token, isSessionRestored } = useSession()
  const [apiKey, setApiKey] = React.useState("")
  const [documentation, setDocumentation] =
    React.useState<AgentApiDocumentationData | null>(null)
  const [accessMode, setAccessMode] = React.useState<
    "session" | "api_key" | null
  >(null)
  const [checkedSessionToken, setCheckedSessionToken] = React.useState<
    string | null
  >(null)
  const [isKeyVisible, setIsKeyVisible] = React.useState(false)
  const [isLoading, setIsLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (
      !isSessionRestored ||
      !token ||
      documentation ||
      checkedSessionToken === token
    ) {
      return
    }

    let isCurrent = true
    getAuthenticatedAgentApiDocumentation(agentId, token)
      .then((response) => {
        if (!isCurrent) return
        setDocumentation(response)
        setAccessMode("session")
      })
      .catch(() => undefined)
      .finally(() => {
        if (isCurrent) setCheckedSessionToken(token)
      })

    return () => {
      isCurrent = false
    }
  }, [agentId, checkedSessionToken, documentation, isSessionRestored, token])

  async function handleUnlock(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const key = apiKey.trim()
    if (!key || isLoading) return
    setIsLoading(true)
    setError(null)
    try {
      const response = await getAgentApiDocumentation(agentId, key)
      setDocumentation(response)
      setAccessMode("api_key")
      setApiKey("")
      setIsKeyVisible(false)
    } catch {
      setError(t("API Key 无效、已撤销或 Agent 未发布。"))
    } finally {
      setIsLoading(false)
    }
  }

  const isCheckingSession =
    !isSessionRestored ||
    Boolean(token && !documentation && checkedSessionToken !== token)

  if (documentation && accessMode) {
    return (
      <AgentApiReference
        agentName={documentation.agent_name}
        basePath={documentation.base_path}
        accessMode={accessMode}
        onChangeApiKey={() => {
          setDocumentation(null)
          setAccessMode(null)
        }}
      />
    )
  }

  return (
    <main className="min-h-svh bg-muted/20">
      <header className="border-b bg-background">
        <div className="mx-auto flex min-h-16 max-w-5xl items-center gap-3 px-4 sm:px-6">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-foreground text-background">
            <BookOpenIcon className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold">
              {t("Agent API 文档")}
            </h1>
            <p className="truncate text-xs text-muted-foreground">
              {t("此页面只显示当前 Agent 的 API 接口。")}
            </p>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6 sm:py-12">
        {isCheckingSession ? (
          <div
            className="flex min-h-48 items-center justify-center"
            role="status"
          >
            <LoaderCircleIcon className="size-5 animate-spin text-muted-foreground" />
            <span className="sr-only">{t("正在加载")}</span>
          </div>
        ) : (
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
                    aria-label={t(
                      isKeyVisible ? "隐藏 API Key" : "显示 API Key"
                    )}
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
        )}
      </div>
    </main>
  )
}
