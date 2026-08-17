"use client"

import * as React from "react"
import { LoaderCircleIcon, RefreshCwIcon, ShieldCheckIcon } from "lucide-react"

import { FilterDropdown } from "@/components/app/filter-dropdown"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useLanguage } from "@/contexts/language-provider"
import {
  listAllToolPermissions,
  revokeToolPermission,
  setToolPermission,
  type ToolPermission,
  type ToolSummary,
} from "@/lib/api/tools"
import { listAllWorkspaceMembers, type WorkspaceMember } from "@/lib/api/system"
import { getErrorMessage } from "@/lib/errors"
import { toolDisplayName } from "@/lib/tool-display"

type GrantValue = "none" | "view" | "use"

export function ToolPermissionsDialog({
  open,
  onOpenChange,
  token,
  workspaceId,
  tool,
  onMessage,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  token: string
  workspaceId: string
  tool: ToolSummary | null
  onMessage: (kind: "success" | "error", message: string) => void
}) {
  const { t } = useLanguage()
  const [members, setMembers] = React.useState<WorkspaceMember[]>([])
  const [permissions, setPermissions] = React.useState<ToolPermission[]>([])
  const [isLoading, setIsLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [busyUserId, setBusyUserId] = React.useState<string | null>(null)
  const requestRef = React.useRef(0)

  const load = React.useCallback(async () => {
    if (!tool) return
    const requestId = ++requestRef.current
    setIsLoading(true)
    setError(null)
    try {
      const [nextMembers, nextPermissions] = await Promise.all([
        listAllWorkspaceMembers(token, workspaceId),
        listAllToolPermissions(token, workspaceId, tool.id),
      ])
      if (requestId !== requestRef.current) return
      setMembers(nextMembers)
      setPermissions(nextPermissions)
    } catch (error) {
      if (requestId === requestRef.current) {
        setMembers([])
        setPermissions([])
        setError(getErrorMessage(error, t))
      }
    } finally {
      if (requestId === requestRef.current) setIsLoading(false)
    }
  }, [t, token, tool, workspaceId])

  React.useEffect(() => {
    // Fetch grants when the controlled dialog becomes visible.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (open && tool) void load()
    return () => {
      requestRef.current += 1
    }
  }, [load, open, tool])

  const permissionByUserId = React.useMemo(
    () =>
      new Map(
        permissions.map((permission) => [
          permission.user.id,
          permission.permission,
        ])
      ),
    [permissions]
  )
  const targets = members.filter(
    (member) =>
      member.user.is_active && member.user.id !== tool?.created_by_user_id
  )

  async function update(userId: string, value: GrantValue) {
    if (!tool || busyUserId) return
    setBusyUserId(userId)
    try {
      if (value === "none") {
        await revokeToolPermission(token, workspaceId, tool.id, userId)
        setPermissions((current) =>
          current.filter((permission) => permission.user.id !== userId)
        )
      } else {
        const updated = await setToolPermission(
          token,
          workspaceId,
          tool.id,
          userId,
          value
        )
        setPermissions((current) => [
          ...current.filter((permission) => permission.user.id !== userId),
          updated,
        ])
      }
      onMessage("success", t("工具授权已更新"))
    } catch (error) {
      onMessage("error", getErrorMessage(error, t))
    } finally {
      setBusyUserId(null)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => !busyUserId && onOpenChange(nextOpen)}
    >
      <DialogContent className="max-h-[calc(100svh-2rem)] w-[calc(100%-2rem)] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-700 dark:text-emerald-400">
              <ShieldCheckIcon className="size-5" />
            </span>
            <div className="min-w-0">
              <DialogTitle>{t("工具授权")}</DialogTitle>
              <DialogDescription className="mt-1">
                {tool ? toolDisplayName(tool, t) : ""}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="rounded-lg border bg-muted/25 p-3 text-xs leading-5 text-muted-foreground">
          {t(
            "查看权限只能查看脱敏详情；使用权限还可将工具绑定到自己的 Agent 或 Workflow。"
          )}
        </div>

        {isLoading ? (
          <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
            <LoaderCircleIcon className="size-4 animate-spin" />
            {t("正在加载")}
          </div>
        ) : error ? (
          <div
            role="alert"
            className="flex min-h-48 flex-col items-center justify-center gap-3 rounded-lg border border-dashed bg-muted/25 p-5 text-center"
          >
            <p className="font-medium">{t("工具加载失败")}</p>
            <p className="text-xs text-muted-foreground">{error}</p>
            <Button type="button" variant="outline" onClick={() => void load()}>
              <RefreshCwIcon />
              {t("重试")}
            </Button>
          </div>
        ) : targets.length ? (
          <div className="divide-y rounded-lg border">
            {targets.map((member) => {
              const value = permissionByUserId.get(member.user.id) ?? "none"
              return (
                <div
                  key={member.user.id}
                  className="flex items-center gap-3 p-3"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {member.user.name}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {member.user.username}
                    </p>
                  </div>
                  <Badge variant="outline" className="hidden sm:inline-flex">
                    {t(member.role === "admin" ? "管理员" : "成员")}
                  </Badge>
                  <FilterDropdown
                    ariaLabel={t("{name} 的工具权限", {
                      name: member.user.name,
                    })}
                    value={value}
                    disabled={Boolean(busyUserId)}
                    modal={false}
                    className="w-32"
                    options={[
                      { value: "none", label: t("无权限") },
                      { value: "view", label: t("查看") },
                      { value: "use", label: t("使用") },
                    ]}
                    onChange={(nextValue) =>
                      void update(member.user.id, nextValue as GrantValue)
                    }
                  />
                  {busyUserId === member.user.id ? (
                    <LoaderCircleIcon className="size-4 animate-spin text-muted-foreground" />
                  ) : null}
                </div>
              )
            })}
          </div>
        ) : (
          <div className="flex min-h-40 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
            {t("没有可授权的成员")}
          </div>
        )}

        <DialogFooter>
          <Button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={Boolean(busyUserId)}
          >
            {t("完成")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
