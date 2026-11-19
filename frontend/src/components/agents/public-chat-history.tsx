"use client"

import * as React from "react"
import {
  BotIcon,
  ChevronDownIcon,
  DownloadIcon,
  EllipsisIcon,
  FolderIcon,
  HistoryIcon,
  LoaderCircleIcon,
  MessageSquarePlusIcon,
  PlusIcon,
  SearchIcon,
  XIcon,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { IconButton } from "@/components/ui/icon-button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useLanguage } from "@/contexts/language-provider"
import type {
  PublicAgentConversation,
  PublicAgentProfile,
} from "@/lib/api/public-agents"
import type { ChatProject } from "@/lib/api/public-chat-projects"

export function PublicChatHistory({
  profile,
  conversations,
  activeConversationId,
  onNew,
  onSelect,
  onDelete,
  onClose,
  deletingConversationId,
  onExport,
  exportingConversationId,
  projects,
  activeProjectId,
  onCreateProject,
  onSelectProject,
  onMove,
  projectBusy,
  projectsError,
  onRetryProjects,
}: {
  profile: PublicAgentProfile | null
  conversations: PublicAgentConversation[]
  activeConversationId: string | null
  onNew: () => void
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onClose?: () => void
  deletingConversationId: string | null
  onExport: (id: string) => void
  exportingConversationId: string | null
  projects: ChatProject[]
  activeProjectId: string | null
  onCreateProject: () => void
  onSelectProject: (id: string) => void
  onMove: (conversationId: string, projectId: string | null) => void
  projectBusy: boolean
  projectsError: boolean
  onRetryProjects: () => void
}) {
  const { t } = useLanguage()
  const [query, setQuery] = React.useState("")
  const [expanded, setExpanded] = React.useState<Record<string, boolean>>({})
  const [showArchived, setShowArchived] = React.useState(false)
  const normalized = query.trim().toLocaleLowerCase()
  const filtered = conversations.filter(
    (item) =>
      !normalized ||
      `${item.question} ${item.result}`.toLocaleLowerCase().includes(normalized)
  )
  const projectIds = new Set(projects.map((item) => item.id))
  const ordinary = filtered.filter(
    (item) => !item.project_id || !projectIds.has(item.project_id)
  )
  function row(conversation: PublicAgentConversation, grouped = false) {
    const pending = Boolean(
      deletingConversationId || exportingConversationId || projectBusy
    )
    return (
      <div
        key={conversation.conversation_id}
        className={`group flex min-w-0 items-center gap-1 rounded-md py-0.5 transition-colors hover:bg-muted ${grouped ? "px-1" : "px-2"} ${activeConversationId === conversation.conversation_id ? "bg-muted" : ""}`}
      >
        <button
          type="button"
          className="min-w-0 flex-1 rounded-md px-1 py-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-current={
            activeConversationId === conversation.conversation_id
              ? "page"
              : undefined
          }
          onClick={() => onSelect(conversation.conversation_id)}
        >
          <span className="block truncate text-sm font-medium">
            {conversation.question || t("新对话")}
          </span>
        </button>
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-xs"
              className="size-8 shrink-0 rounded-md p-0 text-muted-foreground sm:size-5"
              aria-label={t("更多")}
              title={t("更多")}
              disabled={pending}
            >
              {deletingConversationId === conversation.conversation_id ||
              exportingConversationId === conversation.conversation_id ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <EllipsisIcon />
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            side="bottom"
            align="center"
            sideOffset={4}
            className="w-44 min-w-0 rounded-md p-1"
          >
            <DropdownMenuItem
              className="h-8 px-2 py-1 text-xs [&_svg]:size-3.5"
              disabled={pending}
              onSelect={() => onExport(conversation.conversation_id)}
            >
              <DownloadIcon />
              {t("导出对话")}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs text-muted-foreground">
              {t("移入项目")}
            </DropdownMenuLabel>
            {projects
              .filter(
                (project) =>
                  !project.archived && project.id !== conversation.project_id
              )
              .map((project) => (
                <DropdownMenuItem
                  key={project.id}
                  onSelect={() =>
                    onMove(conversation.conversation_id, project.id)
                  }
                >
                  <span className="truncate">{project.name}</span>
                </DropdownMenuItem>
              ))}
            {!projects.some(
              (project) =>
                !project.archived && project.id !== conversation.project_id
            ) ? (
              <DropdownMenuItem disabled>{t("暂无可选项目")}</DropdownMenuItem>
            ) : null}

            {conversation.project_id ? (
              <DropdownMenuItem
                disabled={pending}
                onSelect={() => onMove(conversation.conversation_id, null)}
              >
                {t("移出项目")}
              </DropdownMenuItem>
            ) : null}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              className="h-8 px-2 py-1 text-xs"
              disabled={pending}
              onSelect={() => onDelete(conversation.conversation_id)}
            >
              {t("删除对话")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    )
  }
  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex min-h-16 items-center gap-3 border-b px-4 pt-[env(safe-area-inset-top)]">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <BotIcon className="size-4" />
        </span>
        <p className="min-w-0 flex-1 truncate text-sm font-semibold">
          {profile?.name ?? t("公开 Agent")}
        </p>
        {onClose ? (
          <IconButton label={t("关闭")} onClick={onClose}>
            <XIcon />
          </IconButton>
        ) : null}
      </div>
      <div className="p-3">
        <Button variant="outline" className="w-full" onClick={onNew}>
          <MessageSquarePlusIcon data-icon="inline-start" />
          {t("新建对话")}
        </Button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
        <div className="relative mb-2">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            className="h-10 w-full rounded-md border bg-background pr-2 pl-8 text-base outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring sm:h-8 sm:text-xs"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("搜索历史记录")}
            aria-label={t("搜索历史记录")}
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="flex items-center gap-2 px-2 py-2 text-xs font-medium text-muted-foreground">
            <FolderIcon className="size-3.5" />
            <span className="flex-1">{t("项目")}</span>
            <IconButton
              label={t("新建项目")}
              className="size-6"
              onClick={onCreateProject}
            >
              <PlusIcon className="size-3.5" />
            </IconButton>
          </div>
          {projectsError ? (
            <Button
              variant="ghost"
              size="sm"
              className="w-full text-xs"
              onClick={onRetryProjects}
            >
              {t("项目加载失败，点击重试")}
            </Button>
          ) : null}
          {projects
            .filter(
              (project) =>
                !project.archived ||
                showArchived ||
                project.id === activeProjectId
            )
            .map((project) => {
              const items = filtered.filter(
                (item) => item.project_id === project.id
              )
              if (
                normalized &&
                !items.length &&
                !project.name.toLocaleLowerCase().includes(normalized)
              )
                return null
              const open =
                expanded[project.id] ??
                (project.id === activeProjectId || Boolean(normalized))
              return (
                <section key={project.id} className="mb-1">
                  <div
                    className={`flex min-h-9 min-w-0 items-center rounded-md ${activeProjectId === project.id && !activeConversationId ? "bg-muted" : "hover:bg-muted/60"}`}
                  >
                    <IconButton
                      label={open ? t("收起项目") : t("展开项目")}
                      className="size-7"
                      aria-expanded={open}
                      onClick={() =>
                        setExpanded((current) => ({
                          ...current,
                          [project.id]: !open,
                        }))
                      }
                    >
                      <ChevronDownIcon
                        className={`size-3.5 transition-transform ${open ? "" : "-rotate-90"}`}
                      />
                    </IconButton>
                    <button
                      className="min-w-0 flex-1 truncate rounded-md px-1 py-1.5 text-left text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring"
                      aria-current={
                        activeProjectId === project.id && !activeConversationId
                          ? "page"
                          : undefined
                      }
                      onClick={() => {
                        setExpanded((current) => ({
                          ...current,
                          [project.id]: true,
                        }))
                        onSelectProject(project.id)
                      }}
                      title={project.name}
                    >
                      {project.name}
                      {project.archived ? (
                        <span className="ml-2 text-xs text-muted-foreground">
                          {t("已归档")}
                        </span>
                      ) : null}
                    </button>
                  </div>
                  {open ? (
                    <div className="mt-1 ml-3 space-y-0.5 border-l border-border/60 pl-2">
                      {items.length ? (
                        items.map((item) => row(item, true))
                      ) : (
                        <p className="px-3 py-2 text-xs text-muted-foreground">
                          {t("暂无项目对话")}
                        </p>
                      )}
                    </div>
                  ) : null}
                </section>
              )
            })}
          {projects.some((item) => item.archived) ? (
            <button
              className="px-2 py-2 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setShowArchived((value) => !value)}
            >
              {showArchived ? t("隐藏已归档项目") : t("显示已归档项目")}
            </button>
          ) : null}
          <div className="mt-3 flex items-center gap-2 px-2 py-2 text-xs font-medium text-muted-foreground">
            <HistoryIcon className="size-3.5" />
            <span>{t("历史记录")}</span>
          </div>
          <div className="space-y-0.5">
            {ordinary.map((item) => row(item))}
            {!ordinary.length ? (
              <p className="px-2 py-4 text-center text-xs text-muted-foreground">
                {normalized ? t("暂无匹配的历史记录") : t("暂无历史记录")}
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}
