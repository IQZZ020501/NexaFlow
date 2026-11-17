"use client"

import * as React from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { useLanguage } from "@/contexts/language-provider"
import { getErrorMessage } from "@/lib/errors"
import { listProjects, type AgentProject } from "@/lib/api/projects"

export function ProjectSelector({
  token,
  workspaceId,
  value,
  boundName,
  disabled,
  onChange,
}: {
  token: string
  workspaceId: string
  value?: string | null
  boundName?: string | null
  disabled: boolean
  onChange: (id: string | null) => void
}) {
  const { t } = useLanguage()
  const [projects, setProjects] = React.useState<AgentProject[]>([])
  const [error, setError] = React.useState<string | null>(null)
  React.useEffect(() => {
    if (disabled) return
    let active = true
    async function load() {
      try {
        const items: AgentProject[] = []
        let page: AgentProject[]
        do {
          page = await listProjects(token, workspaceId, items.length)
          items.push(...page)
        } while (page.length === 100)
        if (active) {
          setProjects(items)
          setError(null)
        }
      } catch (error) {
        if (active) setError(getErrorMessage(error, t))
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [token, workspaceId, disabled, t])
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs">
      {disabled ? (
        <span className="max-w-48 truncate text-muted-foreground">
          {value
            ? t("当前项目：{name}", { name: boundName ?? value })
            : t("未绑定项目")}
        </span>
      ) : (
        <select
          aria-label={t("选择项目")}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value || null)}
          className="h-8 max-w-48 min-w-0 rounded-md border bg-background px-2 text-xs"
        >
          <option value="">{t("未绑定项目")}</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      )}
      <Button type="button" size="xs" variant="link" asChild>
        <Link href={value ? `/app/projects/${value}` : "/app/projects"}>
          {t("项目文件")}
        </Link>
      </Button>
      {error ? (
        <span role="alert" className="text-destructive">
          {error}
        </span>
      ) : null}
    </div>
  )
}
