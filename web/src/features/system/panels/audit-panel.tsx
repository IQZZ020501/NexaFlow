import { HistoryIcon, LoaderCircleIcon } from "lucide-react"
import { useLanguage } from "@/components/language-provider"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { AuditLog } from "@/features/system/types"
import { cn } from "@/lib/utils"
import { AUDIT_ACTION_LABEL_KEYS } from "@/app/constants"
import { formatDateTime } from "@/app/display"
import { formatAuditDetails } from "@/features/system/system-utils"

type AuditPanelProps = {
  auditLogs: AuditLog[]
  auditError: string | null
  isAuditLoading: boolean
  locale: string
}

export function AuditPanel({
  auditLogs,
  auditError,
  isAuditLoading,
  locale,
}: AuditPanelProps) {
  const { t } = useLanguage()

  return (
    <div
      id="system-panel-audit"
      role="tabpanel"
      aria-labelledby="system-tab-audit"
      className="grid min-w-0 gap-4 lg:h-full lg:overflow-y-auto lg:pr-1"
    >
      <Card className="min-w-0 gap-3 overflow-hidden border-border/70 py-4 shadow-sm lg:min-h-full">
        <CardHeader className="flex-row items-start justify-between gap-4 px-4">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background">
              <HistoryIcon className="size-4" />
            </span>
            <div className="min-w-0">
              <CardTitle>{t("审计日志")}</CardTitle>
              <CardDescription>{t("系统管理写操作")}</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="min-w-0 px-4">
          {auditError ? (
            <p className="text-sm text-destructive">{auditError}</p>
          ) : isAuditLoading ? (
            <div className="flex min-h-28 items-center justify-center">
              <LoaderCircleIcon className="animate-spin text-muted-foreground" />
            </div>
          ) : auditLogs.length ? (
            <div className="min-w-0 overflow-x-auto rounded-lg border bg-background">
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
                    <span className="truncate" title={log.actor_username}>
                      {log.actor_name}
                    </span>
                    <span>
                      {AUDIT_ACTION_LABEL_KEYS[log.action]
                        ? t(AUDIT_ACTION_LABEL_KEYS[log.action])
                        : log.action}
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
        </CardContent>
      </Card>
    </div>
  )
}
