/* @jsxImportSource react */
import { describe, expect, test } from "bun:test"

import { getNewPasswordError } from "../src/lib/password"
import type { TFunction } from "../src/i18n"

const t = ((key: string) => key) as TFunction

describe("getNewPasswordError", () => {
  test("rejects mismatched password confirmations", () => {
    expect(getNewPasswordError("Secret1", "Secret2", t)).toBe(
      "两次输入的新密码不一致"
    )
  })

  test("rejects passwords shorter than six characters", () => {
    expect(getNewPasswordError("Ab1", "Ab1", t)).toBe(
      "密码至少 6 位，并且包含一个大写字母"
    )
  })

  test("rejects passwords without an uppercase letter", () => {
    expect(getNewPasswordError("abcdef1", "abcdef1", t)).toBe(
      "密码至少 6 位，并且包含一个大写字母"
    )
  })

  test("accepts a matching password meeting both rules", () => {
    expect(getNewPasswordError("Secret1", "Secret1", t)).toBeNull()
  })
})
