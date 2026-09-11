"use client"

import {
  BarChart3Icon,
  ChevronDownIcon,
  CircleCheckIcon,
  Building2Icon,
  LanguagesIcon,
  LockIcon,
  LogOutIcon,
  MegaphoneIcon,
  SettingsIcon,
} from "lucide-react"
import Image from "next/image"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { MobileTabBar } from "@/components/app/mobile-tab-bar"
import { MessageCenter } from "@/components/messages/message-center"
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
 * Renders the language choices as dropdown menu items.
 *
 * Shared by the dedicated language menu and the phone-sized account menu, which
 * folds secondary preferences into a single sheet.
 */
function LanguageMenuItems() {
  const { language, setLanguage, t } = useLanguage()

  return (
    <>
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
    </>
  )
}

/**
 * Renders the theme choices as dropdown menu items.
 *
 * Shared by the dedicated theme menu and the phone-sized account menu.
 */
function ThemeMenuItems() {
  const { theme, setTheme } = useTheme()
  const { t } = useLanguage()

  return (
    <>
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
    </>
  )
}

/**
 * Renders the authenticated user's application navigation bar.
 *
 * The bar is a single responsive header: phones get identity, workspace
 * switching, messages, and the account menu, with primary destinations moved
 * to {@link MobileTabBar}; `sm` and wider keep the inline feature navigation.
 *
 * @returns The top navigation bar and mobile tab bar, or `null` when no authenticated user is available.
 */
export function TopBar() {
  const { language, t } = useLanguage()
  const { theme } = useTheme()
  const pathname = usePathname()
  const router = useRouter()
  const {
    me,
    selectedWorkspaceId,
    workspaceOptions,
    switchWorkspace,
    openPasswordDialog,
    logout,
  } = useSession()
  const currentWorkspaceName = useCurrentWorkspaceName()

  if (!me) {
    return null
  }

  const otherWorkspaces = workspaceOptions.filter(
    (workspace) => workspace.id !== selectedWorkspaceId
  )
  const activeThemeOption =
    themeOptions.find((option) => option.value === theme) ?? themeOptions[0]
  const ActiveThemeIcon = activeThemeOption.icon
  const activeLanguageOption =
    languageOptions.find((option) => option.value === language) ??
    languageOptions[0]
  const featurePages = getPages(t)
  const isAnalyticsActive = pathname.startsWith("/system/analytics")
  const canAccessAnalytics = canAccessWorkspaceAnalytics(me)
  const canAccessSystem =
    me.user.is_global_admin ||
    me.user.workspaces.some((workspace) => workspace.role === "admin") ||
    me.user.teams.some((team) => team.role === "admin")
  const canManageAnnouncements =
    me.user.is_global_admin ||
    me.user.workspaces.some((workspace) => workspace.role === "admin")
  const systemHref =
    me.user.is_global_admin ||
    me.user.workspaces.some((workspace) => workspace.role === "admin")
      ? "/system/workspaces"
      : "/system/teams"

  const featureNavItems = [
    ...featurePages.map((page) => ({
      key: page.key,
      href: PAGE_LINKS[page.key],
      label: page.label,
      icon: page.icon,
    })),
    ...(canAccessAnalytics
      ? [
          {
            key: "analytics",
            href: "/system/analytics",
            label: t("数据大屏"),
            icon: BarChart3Icon,
          },
        ]
      : []),
  ]

  return (
    <>
      <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur">
        <div className="flex h-14 w-full items-center gap-3 px-4 sm:px-6 lg:px-8">
          <div className="flex min-w-0 flex-1 items-center gap-2 sm:flex-none">
            <Link
              href="/app/apps"
              className="flex size-10 shrink-0 items-center justify-center rounded-full focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
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
            <span
              className="hidden text-sm text-muted-foreground sm:inline"
              aria-hidden="true"
            >
              ｜
            </span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="flex min-h-9 min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground sm:max-w-52"
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
                className="max-h-72 min-w-56 overflow-y-auto overscroll-contain"
              >
                <DropdownMenuLabel>{t("其他工作空间")}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                  {otherWorkspaces.length ? (
                    otherWorkspaces.map((workspace) => (
                      <DropdownMenuItem
                        key={workspace.id}
                        onSelect={() => {
                          switchWorkspace(workspace.id)
                          router.replace("/app/apps")
                        }}
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
          <nav className="hidden min-w-0 flex-1 justify-center gap-2 overflow-x-auto overflow-y-hidden sm:flex">
            {featureNavItems.map((item) => {
              const Icon = item.icon
              const isActive =
                item.key === "analytics"
                  ? isAnalyticsActive
                  : pathname.startsWith(item.href)

              return (
                <Button
                  key={item.key}
                  type="button"
                  variant={isActive ? "secondary" : "ghost"}
                  asChild
                  className="h-10 min-w-28 px-4 text-sm has-data-[icon=inline-start]:pl-2"
                >
                  <Link href={item.href}>
                    <Icon data-icon="inline-start" />
                    {item.label}
                  </Link>
                </Button>
              )
            })}
          </nav>
          <div className="flex shrink-0 items-center gap-1 sm:gap-2">
            <MessageCenter />
            <div className="hidden items-center gap-1 sm:flex sm:gap-2">
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
                <DropdownMenuContent
                  align="end"
                  className="max-h-[var(--radix-dropdown-menu-content-available-height)] min-w-40 overflow-y-auto overscroll-contain"
                >
                  <LanguageMenuItems />
                </DropdownMenuContent>
              </DropdownMenu>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-lg"
                    className="text-muted-foreground hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground"
                    aria-label={t("切换主题，当前为 {theme}", {
                      theme: t(activeThemeOption.labelKey),
                    })}
                  >
                    <ActiveThemeIcon className="size-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="end"
                  className="max-h-[var(--radix-dropdown-menu-content-available-height)] min-w-40 overflow-y-auto overscroll-contain"
                >
                  <ThemeMenuItems />
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
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
              <DropdownMenuContent
                align="end"
                className="max-h-[var(--radix-dropdown-menu-content-available-height)] min-w-56 overflow-y-auto overscroll-contain"
              >
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
                  {canManageAnnouncements ? (
                    <DropdownMenuItem asChild>
                      <Link href="/system/announcements">
                        <MegaphoneIcon />
                        {t("公告管理")}
                      </Link>
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuItem onSelect={logout}>
                    <LogOutIcon />
                    {t("退出登录")}
                  </DropdownMenuItem>
                </DropdownMenuGroup>
                {/* Phones have no room for dedicated language/theme buttons. */}
                <div className="sm:hidden">
                  <DropdownMenuSeparator />
                  <LanguageMenuItems />
                  <DropdownMenuSeparator />
                  <ThemeMenuItems />
                </div>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>
      <MobileTabBar />
    </>
  )
}
