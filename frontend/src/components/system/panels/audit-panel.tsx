import { DownloadIcon, HistoryIcon, LoaderCircleIcon, RefreshCwIcon } from "lucide-react"
import { useLanguage } from "@/contexts/language-provider"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { AuditLog } from "@/lib/api/system"
import { cn } from "@/lib/utils"
import { auditActionLabel } from "@/lib/constants"
import { formatDateTime } from "@/lib/display"
import { formatAuditDetails } from "@/components/system/system-utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FilterDropdown } from "@/components/app/filter-dropdown"

type AuditPanelProps = {
  auditLogs: AuditLog[]
  isAuditLoading: boolean
  locale: string
  auditSearch?: string
  setAuditSearch?: (value: string) => void
  auditAction?: string
  setAuditAction?: (value: string) => void
  onRefresh?: () => void
  onLoadMore?: () => void
  hasMore?: boolean
  workspaceScope?: string | null
}

export function AuditPanel({
  auditLogs,
  isAuditLoading,
  locale,
  auditSearch = "",
  setAuditSearch = () => undefined,
  auditAction = "",
  setAuditAction = () => undefined,
  onRefresh = () => undefined,
  onLoadMore = () => undefined,
  hasMore = false,
  workspaceScope = null,
}: AuditPanelProps) {
  const { t } = useLanguage()

  function exportLogs() {
    const rows = [
      [t("时间"), t("操作者"), t("动作"), t("对象"), t("详情")],
      ...auditLogs.map((log) => [
        formatDateTime(log.created_at, locale),
        log.actor_username,
        auditActionLabel(log.action, t),
        log.resource_name,
        formatAuditDetails(log.details, t),
      ]),
    ]
    const csv = rows
      .map((row) => row.map((value) => `"${value.replaceAll('"', '""')}"`).join(","))
      .join("\n")
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }))
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = "nexaflow-audit-log.csv"
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div
      id="system-panel-audit"
      role="tabpanel"
      aria-labelledby="system-tab-audit"
      className="grid min-w-0 gap-4 lg:h-full lg:min-h-0 lg:overflow-hidden lg:pr-1"
    >
      <Card className="min-w-0 gap-3 overflow-hidden border-border/70 py-4 shadow-sm lg:h-full lg:min-h-0">
        <CardHeader className="flex-row flex-wrap items-end justify-between gap-4 px-4">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background">
              <HistoryIcon className="size-4" />
            </span>
            <div className="min-w-0">
              <CardTitle>{t("审计日志")}</CardTitle>
              <CardDescription>{t("系统管理写操作")}</CardDescription>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {workspaceScope ? <span className="text-xs text-muted-foreground">{t("工作空间范围")}: {workspaceScope}</span> : null}
            <Input
              className="w-44"
              value={auditSearch}
              onChange={(event) => setAuditSearch(event.target.value)}
              placeholder={t("搜索审计")}
              aria-label={t("搜索审计")}
            />
            <FilterDropdown
              className="h-9 w-44"
              value={auditAction}
              onChange={setAuditAction}
              ariaLabel={t("筛选动作")}
              options={[
                { value: "", label: t("全部动作") },
                ...Array.from(new Set(auditLogs.map((log) => log.action))).map(
                  (action) => ({ value: action, label: auditActionLabel(action, t) })
                ),
              ]}
            />
            <Button variant="outline" size="icon" onClick={onRefresh} disabled={isAuditLoading} aria-label={t("刷新")}>
              <RefreshCwIcon className={cn("size-4", isAuditLoading && "animate-spin")} />
            </Button>
            <Button variant="outline" size="sm" onClick={exportLogs} disabled={!auditLogs.length}>
              <DownloadIcon className="size-4" />{t("导出")}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="min-w-0 px-4 lg:flex lg:min-h-0 lg:flex-1 lg:flex-col lg:overflow-hidden">
          {isAuditLoading ? (
            <div className="flex min-h-28 items-center justify-center">
              <LoaderCircleIcon className="animate-spin text-muted-foreground" />
            </div>
          ) : auditLogs.length ? (
            <div
              role="region"
              aria-label={t("审计日志")}
              tabIndex={0}
              className="min-w-0 overflow-auto rounded-lg border bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:min-h-0 lg:flex-1"
            >
              <div
                role="table"
                aria-label={t("审计日志")}
                className="w-max min-w-[1700px] text-sm"
              >
                <div className="grid grid-cols-[180px_150px_160px_220px_minmax(950px,max-content)] border-b bg-muted/40 px-4 py-3 font-semibold text-muted-foreground">
                  <span role="columnheader">{t("时间")}</span>
                  <span role="columnheader">{t("操作者")}</span>
                  <span role="columnheader">{t("动作")}</span>
                  <span role="columnheader">{t("对象")}</span>
                  <span role="columnheader">{t("详情")}</span>
                </div>
                {auditLogs.map((log, index) => (
                  <div
                    key={log.id}
                    role="row"
                    className={cn(
                      "grid grid-cols-[180px_150px_160px_220px_minmax(950px,max-content)] items-center border-b px-4 py-4 last:border-b-0 hover:bg-muted/40",
                      index % 2 === 1 && "bg-muted/20"
                    )}
                  >
                    <span className="whitespace-nowrap text-muted-foreground">
                      {formatDateTime(log.created_at, locale)}
                    </span>
                    <span
                      className="truncate"
                      title={`${log.actor_name} (${log.actor_username})`}
                    >
                      {log.actor_name}
                    </span>
                  <span
                    className="truncate"
                      title={auditActionLabel(log.action, t)}
                    >
                      {auditActionLabel(log.action, t)}
                    </span>
                    <span className="truncate" title={log.resource_name}>
                      {log.resource_name}
                    </span>
                    <span
                      className="whitespace-nowrap text-muted-foreground"
                      title={formatAuditDetails(log.details, t)}
                    >
                      {formatAuditDetails(log.details, t)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed bg-muted/20">
              <p className="text-sm text-muted-foreground">
                {t("暂无审计日志")}
              </p>
            </div>
          )}
          {hasMore ? (
            <div className="flex justify-center pt-3">
              <Button variant="outline" size="sm" onClick={onLoadMore} disabled={isAuditLoading}>
                {t("加载更多")}
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
