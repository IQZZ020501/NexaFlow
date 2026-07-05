import { describe, expect, test } from "bun:test"

import {
  languageOptions,
  translate,
  type Language,
  type TFunction,
} from "../src/lib/i18n"
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
  })

  test("builds localized feature pages", () => {
    expect(getPages(tFor("zh-Hans"))[0]?.label).toBe("应用")
    expect(getPages(tFor("zh-Hant"))[0]?.label).toBe("應用")
    expect(getPages(tFor("en"))[0]?.label).toBe("Apps")
  })
})
