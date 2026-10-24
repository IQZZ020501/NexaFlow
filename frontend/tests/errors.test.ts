import { describe, expect, test } from "bun:test"

import { translate, type Language, type TFunction } from "@/i18n"
import { ApiError } from "@/lib/api-client"
import { getErrorMessage } from "@/lib/errors"

function tFor(language: Language): TFunction {
  return (key, values) => translate(language, key, values)
}

describe("API error localization", () => {
  test.each([
    [
      "Agent name already exists.",
      "应用名称已存在",
      "應用名稱已存在",
      "App name already exists",
    ],
    [
      "Agent Skill name already exists.",
      "Skill 名称已存在",
      "Skill 名稱已存在",
      "Skill name already exists",
    ],
    [
      "Folder name already exists.",
      "文件夹名称已存在",
      "資料夾名稱已存在",
      "Folder name already exists",
    ],
    [
      "Model name already exists.",
      "模型名称已存在",
      "模型名稱已存在",
      "Model name already exists",
    ],
    [
      "Model already exists.",
      "模型已存在",
      "模型已存在",
      "Model already exists",
    ],
    [
      "MCP server name already exists.",
      "MCP 服务名称已存在",
      "MCP 服務名稱已存在",
      "MCP server name already exists",
    ],
    [
      "Knowledge base name already exists.",
      "知识库名称已存在",
      "知識庫名稱已存在",
      "Knowledge base name already exists",
    ],
    ["Team already exists.", "团队已存在", "團隊已存在", "Team already exists"],
    [
      "Workspace already exists.",
      "工作空间已存在",
      "工作空間已存在",
      "Workspace already exists",
    ],
    [
      "Username or email already exists.",
      "用户名或邮箱已存在",
      "使用者名稱或信箱已存在",
      "Username or email already exists",
    ],
    [
      "Team member already exists.",
      "该成员已在团队中",
      "該成員已在團隊中",
      "This member is already in the team",
    ],
    [
      "Workspace member already exists.",
      "该成员已在工作空间中",
      "該成員已在工作空間中",
      "This member is already in the workspace",
    ],
  ])(
    "localizes %s in all supported languages",
    (message, zhHans, zhHant, en) => {
      const error = new ApiError(409, message)
      expect(getErrorMessage(error, tFor("zh-Hans"))).toBe(zhHans)
      expect(getErrorMessage(error, tFor("zh-Hant"))).toBe(zhHant)
      expect(getErrorMessage(error, tFor("en"))).toBe(en)
    }
  )

  test("preserves diagnostic messages without a known translation", () => {
    const message = "Custom provider error: quota exhausted"
    for (const language of ["zh-Hans", "zh-Hant", "en"] as const) {
      expect(getErrorMessage(new ApiError(502, message), tFor(language))).toBe(
        message
      )
    }
  })
})
