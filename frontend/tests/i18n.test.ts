import { describe, expect, test } from "bun:test"

import {
  languageOptions,
  translate,
  type Language,
  type TFunction,
} from "../src/i18n"
import { getPages } from "../src/lib/pages"

function tFor(language: Language): TFunction {
  return (key, values) => translate(language, key, values)
}

describe("i18n", () => {
  test("offers the requested languages in order", () => {
    expect(languageOptions.map((option) => option.value)).toEqual([
      "zh-Hans",
      "zh-Hant",
      "en",
    ])
  })

  test("translates interpolated strings", () => {
    expect(
      translate("en", "切换语言，当前为 {language}", { language: "English" })
    ).toBe("Change language, currently English")
    expect(translate("zh-Hans", "分段 {value}", { value: 1 })).toBe("分段 1")
    expect(translate("zh-Hant", "分段 {value}", { value: 1 })).toBe("分段 1")
    expect(translate("en", "分段 {value}", { value: 1 })).toBe("Segment 1")
    expect(translate("zh-Hant", "知识关联")).toBe("知識關聯")
    expect(translate("en", "知识关联")).toBe("Knowledge graph")
  })

  test("falls back to the source key when a runtime translation is missing", () => {
    const missingKey = "missing {value}" as Parameters<typeof translate>[1]
    expect(translate("en", missingKey, { value: 1 })).toBe("missing 1")
  })

  test("builds localized feature pages", () => {
    expect(getPages(tFor("zh-Hans"))[0]?.label).toBe("应用")
    expect(getPages(tFor("zh-Hant"))[0]?.label).toBe("應用")
    expect(getPages(tFor("en"))[0]?.label).toBe("Apps")
  })
})
