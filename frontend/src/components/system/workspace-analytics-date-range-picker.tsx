"use client"

import * as React from "react"
import {
  CalendarDaysIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from "lucide-react"
import { Popover as PopoverPrimitive } from "radix-ui"

import { Button } from "@/components/ui/button"
import { useLanguage } from "@/contexts/language-provider"
import { languageLocales, type TranslationKey } from "@/i18n"
import { APP_TIME_ZONE } from "@/lib/display"
import { cn } from "@/lib/utils"

export type AnalyticsRange = { from: string; to: string }
export type RangePreset = 7 | 30 | 90 | "custom"

const PRESET_OPTIONS: Array<{
  value: Exclude<RangePreset, "custom">
  label: TranslationKey
}> = [
  { value: 7, label: "最近 7 天" },
  { value: 30, label: "最近 30 天" },
  { value: 90, label: "最近 90 天" },
]

function utcCalendarDate(value: Date) {
  return value.toISOString().slice(0, 10)
}

function localCalendarDate(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, "0")
  const day = String(value.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

function parseCalendarDate(value: string) {
  const [year, month, day] = value.split("-").map(Number)
  return new Date(year, month - 1, day)
}

function shiftCalendarDate(value: string, days: number) {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return utcCalendarDate(date)
}

function calendarDays(month: Date) {
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

/**
 * Creates a preset analytics date range ending on the next calendar day.
 *
 * @param days - The number of preceding days to include.
 * @param now - The date used to determine the current day.
 * @returns An analytics range with date strings for the start and exclusive end dates.
 */
export function getPresetAnalyticsRange(
  days: 7 | 30 | 90,
  now = new Date()
): AnalyticsRange {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en", {
      timeZone: APP_TIME_ZONE,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    })
      .formatToParts(now)
      .map(({ type, value }) => [type, value])
  )
  const today = `${parts.year}-${parts.month}-${parts.day}`
  const to = shiftCalendarDate(today, 1)
  return { from: shiftCalendarDate(to, -days), to }
}

/**
 * Displays analytics presets and an inline calendar-card range picker.
 */
export function WorkspaceAnalyticsDateRangePicker({
  preset,
  range,
  onChange,
}: {
  preset: RangePreset
  range: AnalyticsRange
  onChange: (preset: RangePreset, range: AnalyticsRange) => void
}) {
  const { language, t } = useLanguage()
  const locale = languageLocales[language]
  const inclusiveTo = shiftCalendarDate(range.to, -1)
  const [open, setOpen] = React.useState(false)
  const [view, setView] = React.useState<"options" | "calendar">("options")
  const [viewMonth, setViewMonth] = React.useState(() =>
    parseCalendarDate(inclusiveTo)
  )
  const [draftFrom, setDraftFrom] = React.useState(range.from)
  const [draftTo, setDraftTo] = React.useState(inclusiveTo)
  const [selectionStart, setSelectionStart] = React.useState<string | null>(
    null
  )

  const presetLabel =
    preset === "custom"
      ? t("自定义")
      : t(
          PRESET_OPTIONS.find((option) => option.value === preset)?.label ??
            "最近 30 天"
        )

  const monthLabel = new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "long",
  }).format(viewMonth)
  const weekdayFormatter = new Intl.DateTimeFormat(locale, {
    weekday: "narrow",
  })
  const weekdayLabels = Array.from({ length: 7 }, (_, day) =>
    weekdayFormatter.format(new Date(2026, 8, 6 + day))
  )
  const dateFormatter = new Intl.DateTimeFormat(locale, {
    dateStyle: "full",
  })
  const selectedDateFormatter = new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
  const visibleDays = calendarDays(viewMonth)
  const today = shiftCalendarDate(getPresetAnalyticsRange(7).to, -1)
  const customRangeValid = Boolean(draftFrom && draftTo && draftFrom <= draftTo)

  const setOpenState = (nextOpen: boolean) => {
    if (nextOpen) setView("options")
    setOpen(nextOpen)
  }

  const showCalendar = () => {
    const nextInclusiveTo = shiftCalendarDate(range.to, -1)
    setDraftFrom(range.from)
    setDraftTo(nextInclusiveTo)
    setSelectionStart(null)
    setViewMonth(parseCalendarDate(nextInclusiveTo))
    setView("calendar")
  }

  const selectDate = (date: Date) => {
    const selectedDate = localCalendarDate(date)
    if (!selectionStart) {
      setDraftFrom(selectedDate)
      setDraftTo("")
      setSelectionStart(selectedDate)
    } else {
      setDraftFrom(
        selectionStart <= selectedDate ? selectionStart : selectedDate
      )
      setDraftTo(selectionStart <= selectedDate ? selectedDate : selectionStart)
      setSelectionStart(null)
    }

    if (date.getMonth() !== viewMonth.getMonth()) {
      setViewMonth(new Date(date.getFullYear(), date.getMonth(), 1))
    }
  }

  const selectPreset = (nextPreset: 7 | 30 | 90) => {
    onChange(nextPreset, getPresetAnalyticsRange(nextPreset))
    setOpen(false)
  }

  const applyCustomRange = () => {
    if (!customRangeValid) return
    onChange("custom", {
      from: draftFrom,
      to: shiftCalendarDate(draftTo, 1),
    })
    setOpen(false)
  }

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpenState}>
      <PopoverPrimitive.Trigger asChild>
        <Button
          type="button"
          variant="outline"
          className="min-w-0 flex-1 justify-between sm:w-auto sm:flex-none"
          aria-label={t("选择统计周期")}
        >
          <span>{presetLabel}</span>
          <ChevronDownIcon
            aria-hidden="true"
            className="size-4 text-muted-foreground"
          />
        </Button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side="bottom"
          align="end"
          sideOffset={8}
          collisionPadding={16}
          aria-label={view === "calendar" ? t("自定义") : t("选择统计周期")}
          className={cn(
            "z-50 rounded-xl border bg-popover text-popover-foreground shadow-lg outline-none data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95",
            view === "calendar"
              ? "w-[min(22rem,calc(100vw-2rem))] p-3"
              : "min-w-44 p-1"
          )}
        >
          {view === "options" ? (
            <div className="grid gap-0.5">
              {PRESET_OPTIONS.map((option) => (
                <Button
                  key={option.value}
                  type="button"
                  variant="ghost"
                  aria-pressed={preset === option.value}
                  className={cn(
                    "w-full justify-start px-2 font-normal",
                    preset === option.value && "bg-accent"
                  )}
                  onClick={() => selectPreset(option.value)}
                >
                  <CalendarDaysIcon aria-hidden="true" />
                  <span className="flex-1 text-left">{t(option.label)}</span>
                  {preset === option.value ? (
                    <CheckIcon aria-hidden="true" />
                  ) : null}
                </Button>
              ))}
              <Button
                type="button"
                variant="ghost"
                aria-pressed={preset === "custom"}
                className={cn(
                  "w-full justify-start px-2 font-normal",
                  preset === "custom" && "bg-accent"
                )}
                onClick={showCalendar}
              >
                <CalendarDaysIcon aria-hidden="true" />
                <span className="flex-1 text-left">{t("自定义")}</span>
                {preset === "custom" ? <CheckIcon aria-hidden="true" /> : null}
              </Button>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2 rounded-lg bg-muted/50 p-2">
                <div className="min-w-0 px-1">
                  <span className="block text-xs text-muted-foreground">
                    {t("开始日期")}
                  </span>
                  <span className="mt-0.5 block truncate text-sm font-medium tabular-nums">
                    {draftFrom
                      ? selectedDateFormatter.format(
                          parseCalendarDate(draftFrom)
                        )
                      : "—"}
                  </span>
                </div>
                <div className="min-w-0 border-l px-3">
                  <span className="block text-xs text-muted-foreground">
                    {t("结束日期")}
                  </span>
                  <span className="mt-0.5 block truncate text-sm font-medium tabular-nums">
                    {draftTo
                      ? selectedDateFormatter.format(parseCalendarDate(draftTo))
                      : "—"}
                  </span>
                </div>
              </div>

              <div className="flex items-center justify-between gap-2 px-1 py-3">
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

              <div className="grid grid-cols-7 gap-1" data-analytics-calendar>
                {weekdayLabels.map((label, index) => (
                  <span
                    key={`${label}-${index}`}
                    className="flex h-8 items-center justify-center text-xs font-medium text-muted-foreground"
                  >
                    {label}
                  </span>
                ))}
                {visibleDays.map((date) => {
                  const dateKey = localCalendarDate(date)
                  const isOutside = date.getMonth() !== viewMonth.getMonth()
                  const isStart = dateKey === draftFrom
                  const isEnd = dateKey === draftTo
                  const isInRange = Boolean(
                    draftFrom &&
                    draftTo &&
                    dateKey >= draftFrom &&
                    dateKey <= draftTo
                  )

                  return (
                    <button
                      key={dateKey}
                      type="button"
                      data-date={dateKey}
                      data-outside={isOutside ? "true" : undefined}
                      aria-label={dateFormatter.format(date)}
                      aria-pressed={isInRange}
                      aria-current={dateKey === today ? "date" : undefined}
                      onClick={() => selectDate(date)}
                      className={cn(
                        "flex size-9 items-center justify-center rounded-lg text-sm transition-colors outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50",
                        isOutside && "text-muted-foreground/50",
                        isInRange && "bg-primary/10 text-foreground",
                        dateKey === today &&
                          !isStart &&
                          !isEnd &&
                          "ring-1 ring-border",
                        (isStart || isEnd) &&
                          "bg-primary text-primary-foreground ring-0 hover:bg-primary/80"
                      )}
                    >
                      {date.getDate()}
                    </button>
                  )
                })}
              </div>

              <div className="mt-3 flex justify-end gap-2 border-t pt-3">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setOpen(false)}
                >
                  {t("取消")}
                </Button>
                <Button
                  type="button"
                  disabled={!customRangeValid}
                  onClick={applyCustomRange}
                >
                  {t("确认")}
                </Button>
              </div>
            </>
          )}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}
