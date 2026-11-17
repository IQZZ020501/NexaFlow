"use client"

import * as React from "react"
import Link from "next/link"
import { CheckIcon, ChevronDownIcon, FolderIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useLanguage } from "@/contexts/language-provider"
import { getErrorMessage } from "@/lib/errors"
import { listProjects, type AgentProject } from "@/lib/api/projects"
import { cn } from "@/lib/utils"

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
  const projectName = value
    ? (projects.find((project) => project.id === value)?.name ??
      boundName ??
      value)
    : t("未绑定项目")
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
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={t("选择项目")}
              title={projectName}
              className={cn(
                "max-w-36 min-w-0 shrink gap-1.5 rounded-md bg-muted/50 px-2 font-normal text-muted-foreground hover:text-foreground sm:max-w-48",
                value && "text-foreground"
              )}
            >
              <FolderIcon aria-hidden="true" className="size-3.5" />
              <span className="truncate">{projectName}</span>
              <ChevronDownIcon
                aria-hidden="true"
                className="size-3.5 opacity-60"
              />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            side="top"
            sideOffset={6}
            aria-label={t("选择项目")}
            className="max-h-[min(16rem,var(--radix-dropdown-menu-content-available-height))] w-64 min-w-0"
          >
            <DropdownMenuItem
              role="menuitemradio"
              aria-checked={!value}
              className={cn("text-muted-foreground", !value && "bg-muted/70")}
              onSelect={() => onChange(null)}
            >
              <span className="min-w-0 flex-1">{t("未绑定项目")}</span>
              {!value ? (
                <CheckIcon aria-hidden="true" className="size-3.5" />
              ) : null}
            </DropdownMenuItem>
            {projects.map((project) => (
              <DropdownMenuItem
                key={project.id}
                role="menuitemradio"
                aria-checked={project.id === value}
                className={cn(project.id === value && "bg-muted/70")}
                onSelect={() => onChange(project.id)}
              >
                <span className="min-w-0 flex-1 break-words whitespace-normal">
                  {project.name}
                </span>
                {project.id === value ? (
                  <CheckIcon aria-hidden="true" className="size-3.5" />
                ) : null}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
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
