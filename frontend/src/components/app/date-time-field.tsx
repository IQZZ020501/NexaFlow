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
import { toAppDateTimeInput } from "@/lib/display"
import { cn } from "@/lib/utils"

type LocalDateTime = {
  year: number
  month: number
  day: number
  hour: number
  minute: number
}

// Calendar coordinates use UTC getters so the browser's DST cannot alter them.
function calendarDate(
  year: number,
  month: number,
  day = 1,
  hour = 0,
  minute = 0
) {
  return new Date(Date.UTC(year, month, day, hour, minute))
}

function currentCalendarDate() {
  return new Date(`${toAppDateTimeInput(new Date())}Z`)
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
  const date = calendarDate(
    parts.year,
    parts.month - 1,
    parts.day,
    parts.hour,
    parts.minute
  )

  if (
    date.getUTCFullYear() !== parts.year ||
    date.getUTCMonth() !== parts.month - 1 ||
    date.getUTCDate() !== parts.day ||
    date.getUTCHours() !== parts.hour ||
    date.getUTCMinutes() !== parts.minute
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
  return `${date.getUTCFullYear()}-${padNumber(date.getUTCMonth() + 1)}-${padNumber(date.getUTCDate())}T${padNumber(hour)}:${padNumber(minute)}`
}

function calendarDays(month: Date): Date[] {
  const firstDay = calendarDate(month.getUTCFullYear(), month.getUTCMonth(), 1)
  const firstVisibleDay = calendarDate(
    month.getUTCFullYear(),
    month.getUTCMonth(),
    1 - firstDay.getUTCDay()
  )

  return Array.from({ length: 42 }, (_, index) =>
    calendarDate(
      firstVisibleDay.getUTCFullYear(),
      firstVisibleDay.getUTCMonth(),
      firstVisibleDay.getUTCDate() + index
    )
  )
}

function normalizeTimePart(value: string, maximum: number, fallback: number) {
  if (!/^\d{1,2}$/.test(value)) return fallback
  return Math.min(Number(value), maximum)
}

export function DateTimeField({
  value,
  onChange,
  id,
  label,
  description,
  clearable = true,
}: {
  value: string
  onChange: (value: string) => void
  id: string
  label: string
  description?: string
  clearable?: boolean
}) {
  const { language, t } = useLanguage()
  const locale = languageLocales[language]
  const selected = parseLocalDateTime(value)
  const now = currentCalendarDate()
  const initialMonth = selected
    ? calendarDate(selected.year, selected.month - 1, 1)
    : calendarDate(now.getUTCFullYear(), now.getUTCMonth(), 1)
  const [open, setOpen] = React.useState(false)
  const [viewMonth, setViewMonth] = React.useState(initialMonth)
  const [hourDraft, setHourDraft] = React.useState(
    padNumber(selected?.hour ?? now.getUTCHours())
  )
  const [minuteDraft, setMinuteDraft] = React.useState(
    padNumber(selected?.minute ?? now.getUTCMinutes())
  )
  const visibleDays = calendarDays(viewMonth)
  const weekdayFormatter = new Intl.DateTimeFormat(locale, {
    timeZone: "UTC",
    weekday: "narrow",
  })
  const dateFormatter = new Intl.DateTimeFormat(locale, {
    timeZone: "UTC",
    dateStyle: "full",
  })
  const selectedFormatter = new Intl.DateTimeFormat(locale, {
    timeZone: "UTC",
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
      const current = currentCalendarDate()
      setViewMonth(
        nextSelected
          ? calendarDate(nextSelected.year, nextSelected.month - 1, 1)
          : calendarDate(current.getUTCFullYear(), current.getUTCMonth(), 1)
      )
      setHourDraft(padNumber(nextSelected?.hour ?? current.getUTCHours()))
      setMinuteDraft(padNumber(nextSelected?.minute ?? current.getUTCMinutes()))
    }
    setOpen(nextOpen)
  }

  const selectDate = (date: Date) => {
    const current = currentCalendarDate()
    const hour = normalizeTimePart(
      hourDraft,
      23,
      selected?.hour ?? current.getUTCHours()
    )
    const minute = normalizeTimePart(
      minuteDraft,
      59,
      selected?.minute ?? current.getUTCMinutes()
    )
    setHourDraft(padNumber(hour))
    setMinuteDraft(padNumber(minute))
    setViewMonth(calendarDate(date.getUTCFullYear(), date.getUTCMonth(), 1))
    onChange(toLocalDateTimeValue(date, hour, minute))
  }

  const commitTime = () => {
    const current = currentCalendarDate()
    const hour = normalizeTimePart(
      hourDraft,
      23,
      selected?.hour ?? current.getUTCHours()
    )
    const minute = normalizeTimePart(
      minuteDraft,
      59,
      selected?.minute ?? current.getUTCMinutes()
    )
    setHourDraft(padNumber(hour))
    setMinuteDraft(padNumber(minute))
    if (selected) {
      onChange(
        toLocalDateTimeValue(
          calendarDate(selected.year, selected.month - 1, selected.day),
          hour,
          minute
        )
      )
    }
  }

  const selectedDate = selected
    ? calendarDate(
        selected.year,
        selected.month - 1,
        selected.day,
        selected.hour,
        selected.minute
      )
    : null
  const monthLabel = new Intl.DateTimeFormat(locale, {
    timeZone: "UTC",
    year: "numeric",
    month: "long",
  }).format(viewMonth)
  const weekdayLabels = Array.from({ length: 7 }, (_, day) =>
    weekdayFormatter.format(calendarDate(2026, 8, 6 + day))
  )
  const todayKey = `${now.getUTCFullYear()}-${now.getUTCMonth()}-${now.getUTCDate()}`

  return (
    <Field className="min-w-0">
      <FieldLabel htmlFor={`${id}-trigger`}>{label}</FieldLabel>
      <PopoverPrimitive.Root open={open} onOpenChange={setOpenState}>
        <PopoverPrimitive.Trigger asChild>
          <Button
            id={`${id}-trigger`}
            type="button"
            variant="outline"
            aria-label={label}
            aria-describedby={description ? `${id}-description` : undefined}
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
                title={t("上个月")}
                onClick={() =>
                  setViewMonth(
                    calendarDate(
                      viewMonth.getUTCFullYear(),
                      viewMonth.getUTCMonth() - 1,
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
                title={t("下个月")}
                onClick={() =>
                  setViewMonth(
                    calendarDate(
                      viewMonth.getUTCFullYear(),
                      viewMonth.getUTCMonth() + 1,
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
                const dateKey = `${date.getUTCFullYear()}-${date.getUTCMonth()}-${date.getUTCDate()}`
                const isSelected = Boolean(
                  selected &&
                  date.getUTCFullYear() === selected.year &&
                  date.getUTCMonth() === selected.month - 1 &&
                  date.getUTCDate() === selected.day
                )
                const isOutside = date.getUTCMonth() !== viewMonth.getUTCMonth()

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
                        "bg-primary text-primary-foreground ring-0 hover:bg-primary/90"
                    )}
                  >
                    {date.getUTCDate()}
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
                onClick={() => selectDate(currentCalendarDate())}
              >
                {t("今天")}
              </Button>
            </div>

            <div className="mt-3 flex items-center justify-between border-t pt-3">
              {clearable ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={!value}
                  onClick={() => onChange("")}
                >
                  {t("清除")}
                </Button>
              ) : (
                <span />
              )}
              <Button type="button" size="sm" onClick={() => setOpen(false)}>
                {t("完成")}
              </Button>
            </div>
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      </PopoverPrimitive.Root>
      {description ? (
        <FieldDescription id={`${id}-description`}>
          {description}
        </FieldDescription>
      ) : null}
    </Field>
  )
}
