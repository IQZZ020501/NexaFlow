"use client"

import * as React from "react"

import { Badge } from "@/components/ui/badge"
import { useLanguage } from "@/contexts/language-provider"
import { languageLocales } from "@/i18n"
import type { SystemLog } from "@/lib/api/system"
import { systemLogEventLabel, systemLogLevelLabel } from "@/lib/constants"
import { APP_TIME_ZONE, formatDateTime } from "@/lib/display"
import { PHONE_LIST_QUERY, useMediaQuery } from "@/lib/use-media-query"

type SystemLogListProps = {
  logs: SystemLog[]
}

type SystemLogDateGroup = {
  date: string
  label: string
  logs: SystemLog[]
}

const dateKeyFormatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  timeZone: APP_TIME_ZONE,
})

function groupLogsByDate(logs: SystemLog[], locale: string) {
  const groups = new Map<string, SystemLogDateGroup>()
  const labelFormatter = new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
    timeZone: APP_TIME_ZONE,
  })

  for (const log of logs) {
    const createdAt = new Date(log.created_at)
    const dateParts = dateKeyFormatter.formatToParts(createdAt)
    const part = (type: Intl.DateTimeFormatPartTypes) =>
      dateParts.find((item) => item.type === type)?.value ?? ""
    const date = `${part("year")}-${part("month")}-${part("day")}`
    const group = groups.get(date)

    if (group) {
      group.logs.push(log)
    } else {
      groups.set(date, {
        date,
        label: labelFormatter.format(createdAt),
        logs: [log],
      })
    }
  }

  return Array.from(groups.values())
}

/** Renders system logs grouped by their Asia/Shanghai calendar date. */
export function SystemLogList({ logs }: SystemLogListProps) {
  const { t, language } = useLanguage()
  const isPhoneListLayout = useMediaQuery(PHONE_LIST_QUERY)
  const locale = languageLocales[language]
  const groups = React.useMemo(
    () => groupLogsByDate(logs, locale),
    [locale, logs]
  )
  const timeFormatter = React.useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        timeZone: APP_TIME_ZONE,
      }),
    [locale]
  )

  if (isPhoneListLayout) {
    return (
      <div className="grid gap-4">
        {groups.map((group) => (
          <section key={group.date} className="grid gap-2">
            <DateHeading date={group.date} label={group.label} />
            <ul className="flex flex-col gap-2">
              {group.logs.map((log) => (
                <li
                  key={log.id}
                  className="rounded-xl border bg-background p-3 text-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <LogLevelBadge
                      level={log.level}
                      label={systemLogLevelLabel(log.level, t)}
                    />
                    <LogTime
                      createdAt={log.created_at}
                      locale={locale}
                      value={timeFormatter.format(new Date(log.created_at))}
                    />
                  </div>
                  <p className="mt-2 min-w-0 font-medium break-words">
                    {systemLogEventLabel(log.event, t)}
                  </p>
                  <p className="mt-1 min-w-0 text-xs break-words text-muted-foreground">
                    {log.message || systemLogEventLabel(log.event, t)}
                  </p>
                  <div className="mt-2 flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      {t("状态码")}
                    </span>
                    <span className="text-xs font-medium tabular-nums">
                      {log.status_code ?? "—"}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    )
  }

  return (
    <div className="hidden overflow-auto rounded-lg border md:block">
      <div className="min-w-[900px] text-sm">
        <div className="grid grid-cols-[170px_90px_220px_minmax(0,1fr)_80px] gap-x-6 border-b bg-muted/40 px-3 py-2 font-medium">
          <span>{t("时间")}</span>
          <span>{t("级别")}</span>
          <span>{t("事件")}</span>
          <span>{t("消息")}</span>
          <span>{t("状态")}</span>
        </div>
        {groups.map((group) => (
          <div key={group.date}>
            <DateHeading date={group.date} label={group.label} />
            {group.logs.map((log) => (
              <div
                key={log.id}
                className="grid grid-cols-[170px_90px_220px_minmax(0,1fr)_80px] items-center gap-x-6 border-b px-3 py-3 last:border-b-0"
              >
                <LogTime
                  createdAt={log.created_at}
                  locale={locale}
                  value={timeFormatter.format(new Date(log.created_at))}
                />
                <span>
                  <LogLevelBadge
                    level={log.level}
                    label={systemLogLevelLabel(log.level, t)}
                  />
                </span>
                <span
                  className="truncate"
                  title={systemLogEventLabel(log.event, t)}
                >
                  {systemLogEventLabel(log.event, t)}
                </span>
                <span
                  className="min-w-0 truncate text-muted-foreground"
                  title={log.message || systemLogEventLabel(log.event, t)}
                >
                  {log.message || systemLogEventLabel(log.event, t)}
                </span>
                <span>{log.status_code ?? "—"}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

function DateHeading({ date, label }: { date: string; label: string }) {
  return (
    <h3 className="border-b bg-muted/20 px-3 py-2 text-xs font-semibold text-muted-foreground">
      <time data-system-log-date dateTime={date}>
        {label}
      </time>
    </h3>
  )
}

function LogLevelBadge({ level, label }: { level: string; label: string }) {
  return (
    <Badge
      variant={
        level === "error" || level === "critical" ? "destructive" : "outline"
      }
    >
      {label}
    </Badge>
  )
}

function LogTime({
  createdAt,
  locale,
  value,
}: {
  createdAt: string
  locale: string
  value: string
}) {
  return (
    <time
      dateTime={createdAt}
      title={formatDateTime(createdAt, locale)}
      className="text-xs text-muted-foreground tabular-nums md:text-sm"
    >
      {value}
    </time>
  )
}
