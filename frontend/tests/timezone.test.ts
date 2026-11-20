import { describe, expect, test } from "bun:test"

import {
  formatDate,
  formatDateTime,
  toAppDateTimeInput,
  appDateTimeInputToIso,
} from "@/lib/display"

describe("China Standard Time", () => {
  test("displays the Shanghai date across midnight in every language", () => {
    for (const locale of ["zh-CN", "zh-TW", "en-US"]) {
      const instant = "2026-11-19T16:30:00Z"
      expect(formatDateTime(instant, locale)).toContain("00:30:00")
      expect(formatDate(instant, locale)).toBe(
        new Intl.DateTimeFormat(locale, {
          year: "numeric",
          month: "numeric",
          day: "numeric",
          timeZone: "Asia/Shanghai",
        }).format(new Date(instant))
      )
    }
  })

  test("uses midnight rather than 24:00 in English", () => {
    expect(formatDateTime("2026-11-19T16:00:00Z", "en-US")).toContain(
      "00:00:00"
    )
  })

  test("edits an instant using Shanghai wall time and preserves it on save", () => {
    expect(toAppDateTimeInput("2030-05-31T20:30:00Z")).toBe("2030-06-01T04:30")
    const saved = appDateTimeInputToIso("2030-06-01T04:30")
    expect(saved).toBe("2030-06-01T04:30:00+08:00")
    expect(new Date(saved).toISOString()).toBe("2030-05-31T20:30:00.000Z")
  })
})
