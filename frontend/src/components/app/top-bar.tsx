"use client"

import {
  BarChart3Icon,
  ChevronDownIcon,
  CircleCheckIcon,
  Building2Icon,
  LanguagesIcon,
  LockIcon,
  LogOutIcon,
  SettingsIcon,
} from "lucide-react"
import Image from "next/image"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useLanguage } from "@/contexts/language-provider"
import { useCurrentWorkspaceName, useSession } from "@/contexts/session-context"
import { useTheme } from "@/contexts/theme-provider"
import { languageOptions } from "@/i18n"
import { displayWorkspaceName, initials } from "@/lib/display"
import { getPages } from "@/lib/pages"
import { themeOptions } from "@/lib/theme-options"
import {
  canAccessWorkspaceAnalytics,
  getUserRoleLabel,
} from "@/components/system/system-utils"

const PAGE_LINKS: Record<string, string> = {
  apps: "/app/apps",
  knowledge: "/app/knowledge",
  models: "/app/models",
  tools: "/app/tools",
}

/**
 * Renders the authenticated user's application navigation bar.
 *
 * @returns The top navigation bar, or `null` when no authenticated user is available.
 */
export function TopBar() {
  const { language, setLanguage, t } = useLanguage()
  const { theme, setTheme } = useTheme()
  const pathname = usePathname()
  const {
    me,
    selectedWorkspaceId,
    workspaceOptions,
    selectWorkspace,
    openPasswordDialog,
    logout,
  } = useSession()
  const currentWorkspaceName = useCurrentWorkspaceName()

  if (!me) {
    return null
  }

  const activeThemeOption =
    themeOptions.find((option) => option.value === theme) ?? themeOptions[0]
  const activeThemeLabel = t(activeThemeOption.labelKey)
  const ActiveThemeIcon = activeThemeOption.icon
  const activeLanguageOption =
    languageOptions.find((option) => option.value === language) ??
    languageOptions[0]
  const otherWorkspaces = workspaceOptions.filter(
    (workspace) => workspace.id !== selectedWorkspaceId
  )
  const featurePages = getPages(t)
  const isAnalyticsActive = pathname.startsWith("/system/analytics")
  const canAccessAnalytics = canAccessWorkspaceAnalytics(me)
  const canAccessSystem =
    me.user.is_global_admin ||
    me.user.workspaces.some((workspace) => workspace.role === "admin") ||
    me.user.teams.some((team) => team.role === "admin")
  const systemHref =
    me.user.is_global_admin ||
    me.user.workspaces.some((workspace) => workspace.role === "admin")
      ? "/system/workspaces"
      : "/system/teams"

  return (
    <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
      <div className="flex h-14 w-full items-center gap-3 px-4 sm:px-6 lg:px-8">
        <div className="flex min-w-0 shrink-0 items-center gap-2">
          <Link
            href="/app/apps"
            className="shrink-0 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            <Image
              src="/NexaFlow-logo.png"
              alt="NexaFlow"
              width={32}
              height={32}
              priority
              className="size-8 rounded-full dark:invert"
            />
          </Link>
          <span className="text-sm text-muted-foreground" aria-hidden="true">
            ｜
          </span>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex max-w-[32vw] min-w-0 items-center gap-1 rounded-md px-1.5 py-1 text-sm text-muted-foreground hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground sm:max-w-52"
                title={currentWorkspaceName}
                aria-label={t("切换工作空间，当前为 {workspace}", {
                  workspace: currentWorkspaceName,
                })}
              >
                <span className="truncate">{currentWorkspaceName}</span>
                <ChevronDownIcon className="size-3.5 shrink-0" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              side="bottom"
              sideOffset={6}
              collisionPadding={8}
              className="max-h-72 min-w-56 overflow-y-auto"
            >
              <DropdownMenuLabel>{t("其他工作空间")}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                {otherWorkspaces.length ? (
                  otherWorkspaces.map((workspace) => (
                    <DropdownMenuItem
                      key={workspace.id}
                      onSelect={() => selectWorkspace(workspace.id)}
                    >
                      <Building2Icon />
                      <span className="truncate">
                        {displayWorkspaceName(workspace, t)}
                      </span>
                    </DropdownMenuItem>
                  ))
                ) : (
                  <DropdownMenuItem disabled>
                    {t("暂无其他工作空间")}
                  </DropdownMenuItem>
                )}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <nav className="flex min-w-0 flex-1 justify-center gap-2 overflow-x-auto overflow-y-hidden">
          {featurePages.map((page) => {
            const Icon = page.icon
            const isActive = pathname.startsWith(PAGE_LINKS[page.key])

            return (
              <Button
                key={page.key}
                type="button"
                variant={isActive ? "secondary" : "ghost"}
                asChild
                className="h-10 min-w-28 px-4 text-sm"
              >
                <Link href={PAGE_LINKS[page.key]}>
                  <Icon data-icon="inline-start" />
                  <span className="hidden sm:inline">{page.label}</span>
                </Link>
              </Button>
            )
          })}
          {canAccessAnalytics ? (
            <Button
              type="button"
              variant={isAnalyticsActive ? "secondary" : "ghost"}
              asChild
              className="h-10 min-w-28 px-4 text-sm"
            >
              <Link href="/system/analytics">
                <BarChart3Icon data-icon="inline-start" />
                <span className="hidden sm:inline">{t("数据大屏")}</span>
              </Link>
            </Button>
          ) : null}
        </nav>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-lg"
              className="text-muted-foreground hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground"
              aria-label={t("切换语言，当前为 {language}", {
                language: activeLanguageOption.label,
              })}
            >
              <LanguagesIcon className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-40">
            <DropdownMenuLabel>{t("语言")}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              {languageOptions.map((option) => (
                <DropdownMenuItem
                  key={option.value}
                  className="justify-between"
                  onSelect={() => setLanguage(option.value)}
                >
                  <span>{option.label}</span>
                  {option.value === language ? (
                    <CircleCheckIcon className="size-3.5 text-primary" />
                  ) : null}
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-lg"
              className="text-muted-foreground hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground"
              aria-label={t("切换主题，当前为 {theme}", {
                theme: activeThemeLabel,
              })}
            >
              <ActiveThemeIcon className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-40">
            <DropdownMenuLabel>{t("主题")}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              {themeOptions.map((option) => {
                const Icon = option.icon
                const isActive = theme === option.value

                return (
                  <DropdownMenuItem
                    key={option.value}
                    className="justify-between"
                    onSelect={() => setTheme(option.value)}
                  >
                    <span className="flex items-center gap-2">
                      <Icon />
                      {t(option.labelKey)}
                    </span>
                    {isActive ? (
                      <CircleCheckIcon className="size-3.5 text-primary" />
                    ) : null}
                  </DropdownMenuItem>
                )
              })}
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-lg"
              aria-label={t("打开用户菜单")}
            >
              <Avatar>
                <AvatarFallback>{initials(me.user.name)}</AvatarFallback>
              </Avatar>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>
              <div className="flex flex-col gap-1">
                <span>{me.user.name}</span>
                <span className="text-xs font-normal text-muted-foreground">
                  {me.user.username} / {getUserRoleLabel(me.user, t)}
                </span>
                <span className="text-xs font-normal text-muted-foreground">
                  {me.user.email}
                </span>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem onSelect={openPasswordDialog}>
                <LockIcon />
                {t("修改密码")}
              </DropdownMenuItem>
              {canAccessSystem ? (
                <DropdownMenuItem asChild>
                  <Link href={systemHref}>
                    <SettingsIcon />
                    {t("系统管理")}
                  </Link>
                </DropdownMenuItem>
              ) : null}
              <DropdownMenuItem onSelect={logout}>
                <LogOutIcon />
                {t("退出登录")}
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
