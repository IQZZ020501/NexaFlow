"use client"

import * as React from "react"
import {
  CalendarDaysIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from "lucide-react"
import { Popover as PopoverPrimitive } from "radix-ui"

import { Button } from "@/components/ui/button"
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import { languageLocales } from "@/i18n"
import { cn } from "@/lib/utils"

type LocalDateTime = {
  year: number
  month: number
  day: number
  hour: number
  minute: number
}

const padNumber = (value: number) => String(value).padStart(2, "0")

function parseLocalDateTime(value: string): LocalDateTime | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value)
  if (!match) return null

  const [, yearValue, monthValue, dayValue, hourValue, minuteValue] = match
  const parts = {
    year: Number(yearValue),
    month: Number(monthValue),
    day: Number(dayValue),
    hour: Number(hourValue),
    minute: Number(minuteValue),
  }
  const date = new Date(
    parts.year,
    parts.month - 1,
    parts.day,
    parts.hour,
    parts.minute
  )

  if (
    date.getFullYear() !== parts.year ||
    date.getMonth() !== parts.month - 1 ||
    date.getDate() !== parts.day ||
    date.getHours() !== parts.hour ||
    date.getMinutes() !== parts.minute
  ) {
    return null
  }

  return parts
}

function toLocalDateTimeValue(
  date: Date,
  hour: number,
  minute: number
): string {
  return `${date.getFullYear()}-${padNumber(date.getMonth() + 1)}-${padNumber(date.getDate())}T${padNumber(hour)}:${padNumber(minute)}`
}

function calendarDays(month: Date): Date[] {
  const firstDay = new Date(month.getFullYear(), month.getMonth(), 1)
  const firstVisibleDay = new Date(
    month.getFullYear(),
    month.getMonth(),
    1 - firstDay.getDay()
  )

  return Array.from(
    { length: 42 },
    (_, index) =>
      new Date(
        firstVisibleDay.getFullYear(),
        firstVisibleDay.getMonth(),
        firstVisibleDay.getDate() + index
      )
  )
}

function normalizeTimePart(value: string, maximum: number, fallback: number) {
  if (!/^\d{1,2}$/.test(value)) return fallback
  return Math.min(Number(value), maximum)
}

export function AnnouncementExpirationField({
  value,
  onChange,
}: {
  value: string
  onChange: (value: string) => void
}) {
  const { language, t } = useLanguage()
  const locale = languageLocales[language]
  const selected = parseLocalDateTime(value)
  const now = new Date()
  const initialMonth = selected
    ? new Date(selected.year, selected.month - 1, 1)
    : new Date(now.getFullYear(), now.getMonth(), 1)
  const [open, setOpen] = React.useState(false)
  const [viewMonth, setViewMonth] = React.useState(initialMonth)
  const [hourDraft, setHourDraft] = React.useState(
    padNumber(selected?.hour ?? now.getHours())
  )
  const [minuteDraft, setMinuteDraft] = React.useState(
    padNumber(selected?.minute ?? now.getMinutes())
  )
  const visibleDays = calendarDays(viewMonth)
  const weekdayFormatter = new Intl.DateTimeFormat(locale, {
    weekday: "narrow",
  })
  const dateFormatter = new Intl.DateTimeFormat(locale, {
    dateStyle: "full",
  })
  const selectedFormatter = new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  })

  const setOpenState = (nextOpen: boolean) => {
    if (nextOpen) {
      const nextSelected = parseLocalDateTime(value)
      const current = new Date()
      setViewMonth(
        nextSelected
          ? new Date(nextSelected.year, nextSelected.month - 1, 1)
          : new Date(current.getFullYear(), current.getMonth(), 1)
      )
      setHourDraft(padNumber(nextSelected?.hour ?? current.getHours()))
      setMinuteDraft(padNumber(nextSelected?.minute ?? current.getMinutes()))
    }
    setOpen(nextOpen)
  }

  const selectDate = (date: Date) => {
    const current = new Date()
    const hour = normalizeTimePart(
      hourDraft,
      23,
      selected?.hour ?? current.getHours()
    )
    const minute = normalizeTimePart(
      minuteDraft,
      59,
      selected?.minute ?? current.getMinutes()
    )
    setHourDraft(padNumber(hour))
    setMinuteDraft(padNumber(minute))
    setViewMonth(new Date(date.getFullYear(), date.getMonth(), 1))
    onChange(toLocalDateTimeValue(date, hour, minute))
  }

  const commitTime = () => {
    const current = new Date()
    const hour = normalizeTimePart(
      hourDraft,
      23,
      selected?.hour ?? current.getHours()
    )
    const minute = normalizeTimePart(
      minuteDraft,
      59,
      selected?.minute ?? current.getMinutes()
    )
    setHourDraft(padNumber(hour))
    setMinuteDraft(padNumber(minute))
    if (selected) {
      onChange(
        toLocalDateTimeValue(
          new Date(selected.year, selected.month - 1, selected.day),
          hour,
          minute
        )
      )
    }
  }

  const selectedDate = selected
    ? new Date(
        selected.year,
        selected.month - 1,
        selected.day,
        selected.hour,
        selected.minute
      )
    : null
  const monthLabel = new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "long",
  }).format(viewMonth)
  const weekdayLabels = Array.from({ length: 7 }, (_, day) =>
    weekdayFormatter.format(new Date(2026, 8, 6 + day))
  )
  const todayKey = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}`

  return (
    <Field className="min-w-0">
      <FieldLabel htmlFor="announcement-expires-at-trigger">
        {t("公告过期时间")}
      </FieldLabel>
      <PopoverPrimitive.Root open={open} onOpenChange={setOpenState}>
        <PopoverPrimitive.Trigger asChild>
          <Button
            id="announcement-expires-at-trigger"
            type="button"
            variant="outline"
            aria-label={t("公告过期时间")}
            aria-describedby="announcement-expires-at-description"
            className={cn(
              "h-9 w-full min-w-0 justify-start px-3 font-normal max-sm:h-11",
              !selectedDate && "text-muted-foreground"
            )}
          >
            <span className="min-w-0 flex-1 truncate text-left">
              {selectedDate
                ? selectedFormatter.format(selectedDate)
                : t("选择日期和时间")}
            </span>
            <CalendarDaysIcon className="ml-2 size-4 text-muted-foreground" />
          </Button>
        </PopoverPrimitive.Trigger>
        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content
            side="bottom"
            align="start"
            sideOffset={8}
            collisionPadding={16}
            className="z-50 max-h-[calc(100svh-2rem)] w-[min(22rem,calc(100vw-2rem))] overflow-y-auto overscroll-contain rounded-xl border bg-popover p-3 text-popover-foreground shadow-lg outline-none data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
          >
            <div className="flex items-center justify-between gap-2 px-1 pb-3">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={t("上个月")}
                onClick={() =>
                  setViewMonth(
                    new Date(
                      viewMonth.getFullYear(),
                      viewMonth.getMonth() - 1,
                      1
                    )
                  )
                }
              >
                <ChevronLeftIcon />
              </Button>
              <p className="text-sm font-semibold" aria-live="polite">
                {monthLabel}
              </p>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={t("下个月")}
                onClick={() =>
                  setViewMonth(
                    new Date(
                      viewMonth.getFullYear(),
                      viewMonth.getMonth() + 1,
                      1
                    )
                  )
                }
              >
                <ChevronRightIcon />
              </Button>
            </div>

            <div className="grid grid-cols-7 gap-1">
              {weekdayLabels.map((label, index) => (
                <span
                  key={`${label}-${index}`}
                  className="flex h-8 items-center justify-center text-xs font-medium text-muted-foreground"
                >
                  {label}
                </span>
              ))}
              {visibleDays.map((date) => {
                const dateKey = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
                const isSelected = Boolean(
                  selected &&
                  date.getFullYear() === selected.year &&
                  date.getMonth() === selected.month - 1 &&
                  date.getDate() === selected.day
                )
                const isOutside = date.getMonth() !== viewMonth.getMonth()

                return (
                  <button
                    key={dateKey}
                    type="button"
                    aria-label={dateFormatter.format(date)}
                    aria-pressed={isSelected}
                    aria-current={dateKey === todayKey ? "date" : undefined}
                    onClick={() => selectDate(date)}
                    className={cn(
                      "flex size-9 items-center justify-center rounded-lg text-sm transition-colors outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 max-sm:size-10",
                      isOutside && "text-muted-foreground/50",
                      dateKey === todayKey && "ring-1 ring-border",
                      isSelected &&
                        "bg-primary text-primary-foreground ring-0 hover:bg-primary/80"
                    )}
                  >
                    {date.getDate()}
                  </button>
                )
              })}
            </div>

            <div className="mt-3 flex items-end gap-2 border-t pt-3">
              <div className="min-w-0 flex-1">
                <span className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  {t("时间")}
                </span>
                <div className="flex items-center gap-1.5">
                  <Input
                    type="text"
                    inputMode="numeric"
                    maxLength={2}
                    value={hourDraft}
                    aria-label={t("小时")}
                    onChange={(event) =>
                      setHourDraft(
                        event.target.value.replace(/\D/g, "").slice(0, 2)
                      )
                    }
                    onBlur={commitTime}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault()
                        commitTime()
                      }
                    }}
                    className="w-12 text-center tabular-nums"
                  />
                  <span aria-hidden="true" className="text-muted-foreground">
                    :
                  </span>
                  <Input
                    type="text"
                    inputMode="numeric"
                    maxLength={2}
                    value={minuteDraft}
                    aria-label={t("分钟")}
                    onChange={(event) =>
                      setMinuteDraft(
                        event.target.value.replace(/\D/g, "").slice(0, 2)
                      )
                    }
                    onBlur={commitTime}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault()
                        commitTime()
                      }
                    }}
                    className="w-12 text-center tabular-nums"
                  />
                </div>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => selectDate(new Date())}
              >
                {t("今天")}
              </Button>
            </div>

            <div className="mt-3 flex items-center justify-between border-t pt-3">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={!value}
                onClick={() => onChange("")}
              >
                {t("清除")}
              </Button>
              <Button type="button" size="sm" onClick={() => setOpen(false)}>
                {t("完成")}
              </Button>
            </div>
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      </PopoverPrimitive.Root>
      <FieldDescription id="announcement-expires-at-description">
        {t("留空表示永不过期。")}
      </FieldDescription>
    </Field>
  )
}
