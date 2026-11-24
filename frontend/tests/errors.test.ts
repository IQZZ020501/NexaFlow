import { describe, expect, test } from "bun:test"

import { translate, type Language, type TFunction } from "@/i18n"
import { ApiError } from "@/lib/api-client"
import { getErrorMessage } from "@/lib/errors"

function tFor(language: Language): TFunction {
  return (key, values) => translate(language, key, values)
}

describe("API error localization", () => {
  test.each([
    ["zh-Hans", "当前访问地址不可用于授权，请从 NexaFlow 网站重新登录。"],
    ["zh-Hant", "目前的存取網址無法用於授權，請從 NexaFlow 網站重新登入。"],
    [
      "en",
      "This address cannot be used for authorization. Sign in again from the NexaFlow website.",
    ],
  ] as const)(
    "localizes browser OAuth origin errors in %s",
    (language, expected) => {
      expect(
        getErrorMessage(
          new ApiError(400, "Integration authorization origin is not allowed."),
          tFor(language)
        )
      ).toBe(expected)
    }
  )
  test.each([
    "Tool is not available for binding.",
    "Tool version is not available for binding.",
  ])("localizes tool binding failures: %s", (message) => {
    const error = new ApiError(422, message)
    expect(getErrorMessage(error, tFor("zh-Hans"))).toBe(
      "工具不可用，请刷新工具列表后重新选择"
    )
    expect(getErrorMessage(error, tFor("zh-Hant"))).toBe(
      "工具不可用，請重新整理工具清單後重新選擇"
    )
    expect(getErrorMessage(error, tFor("en"))).toBe(
      "Tool is unavailable. Refresh the tool list and select it again."
    )
  })
  test("localizes workspace token admission failures", () => {
    const error = new Error("Workspace monthly token quota exceeded.")
    expect(getErrorMessage(error, tFor("zh-Hans"))).toContain("额度不足")
    expect(getErrorMessage(error, tFor("zh-Hant"))).toContain("額度不足")
    expect(getErrorMessage(error, tFor("en"))).toContain("token quota")
  })
  test("localizes upload errors and identifies fields in server validation errors", () => {
    expect(
      getErrorMessage(new ApiError(422, "Document is empty."), tFor("zh-Hans"))
    ).toContain("0 字节")
    expect(
      getErrorMessage(
        new ApiError(422, "validation", [
          {
            loc: ["body", "name"],
            msg: "String should have at most 120 characters",
          },
          {
            loc: ["body", "similarity"],
            msg: "Input should be less than or equal to 1",
          },
        ]),
        tFor("zh-Hans")
      )
    ).toBe("名称：最多输入 120 个字符\n相似度：数值必须小于或等于 1")
  })
  test.each([
    ["zh-Hans", "模型回答被截断，请重试。"],
    ["zh-Hant", "模型回答遭到截斷，請重試。"],
    ["en", "The model response was truncated. Please retry."],
  ] as const)("localizes truncation errors in %s", (language, expected) => {
    expect(
      getErrorMessage(
        new Error("Agent response was truncated."),
        tFor(language)
      )
    ).toBe(expected)
    expect(
      getErrorMessage(
        new ApiError(502, "Agent response was truncated."),
        tFor(language)
      )
    ).toBe(expected)
  })

  test.each([
    [
      "Agent name already exists.",
      "应用名称已存在",
      "應用名稱已存在",
      "App name already exists",
    ],
    [
      "Agent Skill name already exists.",
      "技能名称已存在",
      "技能名稱已存在",
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

  test("uses localized fallbacks for unknown provider errors and preserves English diagnostics", () => {
    const message = "Custom provider error: quota exhausted"
    for (const language of ["zh-Hans", "zh-Hant"] as const) {
      expect(getErrorMessage(new ApiError(502, message), tFor(language))).toBe(
        translate(language, "服务暂时不可用，请稍后重试")
      )
      expect(getErrorMessage(new Error(message), tFor(language))).toBe(
        translate(language, "请求失败")
      )
    }
    expect(getErrorMessage(new ApiError(502, message), tFor("en"))).toBe(
      message
    )
    expect(getErrorMessage(new Error(message), tFor("en"))).toBe(message)
  })

  test.each([
    [400, "输入参数无效，请检查后重试"],
    [408, "请求超时，请稍后重试"],
    [409, "操作冲突，请刷新后重试"],
    [413, "请求内容超过大小限制，请缩小后重试"],
    [422, "输入参数无效，请检查后重试"],
    [429, "请求过于频繁，请稍后重试"],
    [500, "服务暂时不可用，请稍后重试"],
    [504, "请求超时，请稍后重试"],
  ] as const)("localizes unknown HTTP %s failures", (status, key) => {
    for (const language of ["zh-Hans", "zh-Hant"] as const) {
      expect(
        getErrorMessage(
          new ApiError(status, "Unexpected failure"),
          tFor(language)
        )
      ).toBe(translate(language, key))
    }
  })

  test("localizes unmapped validation errors without leaking English field names", () => {
    const error = new ApiError(422, "validation", [
      { loc: ["body", "password"], msg: "Input should be a valid string" },
      {
        loc: ["body", "custom_field"],
        msg: "Input should be 'active' or 'disabled'",
      },
    ])
    expect(getErrorMessage(error, tFor("zh-Hans"))).toBe(
      "密码：请输入有效的文本\n输入参数：输入参数无效，请检查后重试"
    )
    expect(getErrorMessage(error, tFor("zh-Hant"))).toBe(
      "密碼：請輸入有效的文字\n輸入參數：輸入參數無效，請檢查後重試"
    )
  })

  test("translates source-language errors and keeps already localized details", () => {
    expect(getErrorMessage(new Error("请求失败"), tFor("zh-Hant"))).toBe(
      "請求失敗"
    )
    expect(
      getErrorMessage(new Error("已超出当前账号的使用额度"), tFor("zh-Hans"))
    ).toBe("已超出当前账号的使用额度")
    expect(getErrorMessage(new Error("Copy failed"), tFor("zh-Hans"))).toBe(
      "复制失败"
    )
    expect(getErrorMessage(new Error(""), tFor("zh-Hant"))).toBe("請求失敗")
    expect(
      getErrorMessage(
        new Error("Provider request failed for 法律.pdf"),
        tFor("zh-Hans")
      )
    ).toBe("请求失败")
    expect(
      getErrorMessage(
        new Error("Value error, unexpected provider failure"),
        tFor("en")
      )
    ).toBe("Value error, unexpected provider failure")
  })

  test.each(["constructor", "__proto__"])(
    "handles unknown error keys safely: %s",
    (message) => {
      expect(getErrorMessage(new Error(message), tFor("zh-Hans"))).toBe(
        "请求失败"
      )
      expect(
        getErrorMessage(
          new ApiError(422, message, [
            { loc: ["body", message], msg: message },
          ]),
          tFor("zh-Hans")
        )
      ).toBe("输入参数：输入参数无效，请检查后重试")
    }
  )

  test.each([
    ["Current password is invalid.", "当前密码错误"],
    ["Too many login attempts.", "登录尝试过于频繁，请稍后重试"],
    ["Agent run timed out.", "Agent 回答超时"],
    [
      "This conversation already has an active run.",
      "此对话已有任务运行中，请稍后重试",
    ],
    [
      "Knowledge base has no indexed chunks.",
      "知识库暂无已索引的内容，请先完成索引",
    ],
    ["Model is in use.", "模型正在使用中，无法删除"],
    ["MCP source is unavailable.", "MCP 服务不可用，请检查配置后重试"],
  ] as const)(
    "preserves an actionable translation for %s",
    (message, expected) => {
      expect(getErrorMessage(new Error(message), tFor("zh-Hans"))).toBe(
        expected
      )
    }
  )

  test.each([
    [
      "Uncertain tool calls cannot be retried through approval; verify the external state and reject the retry to continue.",
      "此调用可能已执行，无法通过批准操作重试。请核对结果后选择“不重试并继续”。",
      "此呼叫可能已執行，無法透過批准操作重試。請核對結果後選擇「不重試並繼續」。",
      "This call may already have executed and cannot be retried through approval. Check the result, then select “Continue without retrying”.",
    ],
    [
      "Tool invocation deadline expired.",
      "工具执行已超时，请先核对外部服务的结果。",
      "工具執行已逾時，請先核對外部服務的結果。",
      "The tool call timed out. Check the result in the external service first.",
    ],
    ...[
      "Tool invocation outcome is uncertain after worker recovery.",
      "Tool invocation outcome is uncertain after dispatch.",
    ].map((message) => [
      message,
      "工具执行结果无法确认，请先核对外部服务的结果。",
      "工具執行結果無法確認，請先核對外部服務的結果。",
      "The tool outcome could not be confirmed. Check the result in the external service first.",
    ]),
  ])("localizes uncertain tool outcomes: %s", (message, hans, hant, en) => {
    for (const [language, expected] of [
      ["zh-Hans", hans],
      ["zh-Hant", hant],
      ["en", en],
    ] as const) {
      expect(getErrorMessage(new ApiError(409, message), tFor(language))).toBe(
        expected
      )
      expect(getErrorMessage(new Error(message), tFor(language))).toBe(expected)
    }
  })
})
