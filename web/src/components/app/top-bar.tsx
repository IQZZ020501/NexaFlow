import {
  ChevronDownIcon,
  CircleCheckIcon,
  Building2Icon,
  LanguagesIcon,
  LockIcon,
  LogOutIcon,
  SettingsIcon,
} from "lucide-react"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { useLanguage } from "@/components/language-provider"
import { useTheme } from "@/components/theme-provider"
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
import { type MeResponse, type Workspace } from "@/lib/api"
import { type FeaturePageConfig, type PageKey } from "@/lib/pages"
import { languageOptions } from "@/lib/i18n"
import { displayWorkspaceName, initials } from "@/app/display"
import { themeOptions } from "@/app/theme-options"

export function TopBar({
  me,
  activePage,
  featurePages,
  currentWorkspaceName,
  selectedWorkspaceId,
  workspaceOptions,
  onPageChange,
  onSelectWorkspace,
  onChangePassword,
  onLogout,
}: {
  me: MeResponse
  activePage: PageKey
  featurePages: readonly FeaturePageConfig[]
  currentWorkspaceName: string
  selectedWorkspaceId: string | null
  workspaceOptions: Workspace[]
  onPageChange: (page: PageKey) => void
  onSelectWorkspace: (workspaceId: string) => void
  onChangePassword: () => void
  onLogout: () => void
}) {
  const { language, setLanguage, t } = useLanguage()
  const { theme, setTheme } = useTheme()
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

  return (
    <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
      <div className="flex h-14 w-full items-center gap-3 px-4 sm:px-6 lg:px-8">
        <div className="flex min-w-0 shrink-0 items-center gap-2">
          <button
            type="button"
            className="shrink-0 text-left text-base font-semibold"
            onClick={() => onPageChange("apps")}
          >
            NexaFlow
          </button>
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
            <DropdownMenuContent align="start" className="min-w-56">
              <DropdownMenuLabel>{t("其他工作空间")}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                {otherWorkspaces.length ? (
                  otherWorkspaces.map((workspace) => (
                    <DropdownMenuItem
                      key={workspace.id}
                      onSelect={() => onSelectWorkspace(workspace.id)}
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
        <nav className="flex min-w-0 flex-1 justify-center gap-2 overflow-x-auto">
          {featurePages.map((page) => {
            const Icon = page.icon
            const isActive = activePage === page.key

            return (
              <Button
                key={page.key}
                type="button"
                variant={isActive ? "secondary" : "ghost"}
                onClick={() => onPageChange(page.key)}
                className="h-10 min-w-28 px-4 text-sm"
              >
                <Icon data-icon="inline-start" />
                <span className="hidden sm:inline">{page.label}</span>
              </Button>
            )
          })}
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
                  {me.user.username} /{" "}
                  {me.user.is_global_admin ? t("全局管理员") : t("成员")}
                </span>
                <span className="text-xs font-normal text-muted-foreground">
                  {me.user.email}
                </span>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem onSelect={onChangePassword}>
                <LockIcon />
                {t("修改密码")}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onPageChange("system")}>
                <SettingsIcon />
                {t("系统管理")}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={onLogout}>
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
