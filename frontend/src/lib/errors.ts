import { ApiError } from "@/lib/api-client"
import { type TFunction, type TranslationKey } from "@/i18n"

const API_ERROR_LABEL_KEYS: Record<string, TranslationKey> = {
  "Invalid integration operation arguments.":
    "集成参数无效，请检查会议标识、时间和操作参数。",
  "Configure the administrator-managed public site URL before connecting OAuth.":
    "请先由系统管理员配置公开站点地址。",
  "Integration not found.": "当前用户尚未安装此集成，请重新安装。",
  "Ask a workspace administrator to configure this integration's application first.":
    "请联系空间管理员配置此集成的开发者应用。",
  "Uninstall this integration before changing its application configuration.":
    "请先卸载此集成，再修改应用配置。",
  "Integration application credentials are required.": "集成应用凭据不能为空",
  "This integration is already installed. Uninstall it before connecting another account.":
    "此集成已安装，请先卸载再连接其他账号。",
  "Integration authorization was cancelled. Please install again.":
    "授权已取消，请重新安装。",
  "Integration authorization failed. Please authorize again.":
    "平台授权失败，请重新安装。",
  "Integration returned invalid authorization data.":
    "平台返回的授权信息无效，请重新安装。",
  "Integration request failed. Check the account authorization and application permissions.":
    "平台请求失败，请检查账号授权和应用权限。",
  "Integration service could not be reached.":
    "暂时无法连接集成服务，请稍后重试。",
  "Integration response was unavailable.": "暂时无法连接集成服务，请稍后重试。",
  "Integration authorization is invalid or expired. Please install again.":
    "集成授权无效或已过期，请重新安装。",
  "Integration authorization was already used. Please install again.":
    "此授权已使用，请重新安装。",
  "Personal integration connections cannot be shared.":
    "个人集成账号不能共享，请分别登录自己的账号。",
  "Integration is not installed for this user. Please install again.":
    "当前用户尚未安装此集成，请重新安装。",
  "Integration authorization expired. Please install again.":
    "集成授权已过期，请重新认证。",
  "Integration application changed. Please install again.":
    "集成应用配置已变更，请重新认证。",
  "Integration authorization changed. Please install again.":
    "集成授权无效或已过期，请重新安装。",
  "Integration operation timed out.": "集成操作超时，请核对平台结果后再重试。",
  "Memory not found.": "记忆不存在或不可访问",
  "Memory key already exists.": "已有相同主题的记忆，请编辑现有条目",
  "Memory limit reached.": "最多保存 100 条记忆，请先删除不再需要的条目",
  "Memory contains sensitive information.": "记忆中不能保存密码、密钥等敏感信息",
  "Chat project not found.": "项目不存在或不可访问",
  "Chat project is archived.": "项目已归档，请先恢复项目",
  "Chat project file not found.": "项目资料不存在或已移除",
  "Chat project already has a file with this path.":
    "项目中已有同名文件，请先重命名或移除旧文件",
  "Chat project files exceed their limits or contain invalid paths.":
    "项目资料超出限制或路径无效，请检查后重试",
  "Cannot move a conversation while it is running.":
    "对话运行中，请完成后再移动或解散项目",
  "Name cannot be empty.": "名称不能为空或仅包含空格",

  "Workspace monthly token quota exceeded.": "工作空间本月模型 Token 额度不足，请联系管理员",
  "Artifact workspace path is invalid.": "文件路径无效，请检查文件夹或压缩包",
  "Artifact filename is invalid.": "文件路径无效，请检查文件夹或压缩包",
  "Uploaded file path exceeds 255 characters.": "文件路径过长，最多 255 个字符",
  "Each conversation file must not exceed 5 MiB.": "单个文件不能超过 5 MiB",
  "Each project file must not exceed 5 MiB.": "单个文件不能超过 5 MiB",
  "Conversation files exceed 64 files or 64 MiB.": "每段对话最多保存 64 个文件、合计 64 MiB",
  "Project file count exceeds its limit.": "每段对话最多保存 64 个文件、合计 64 MiB",
  "Project files exceed 64 MiB.": "每段对话最多保存 64 个文件、合计 64 MiB",
  "Project paths cannot be both a file and a parent directory.": "上传路径不能同时是文件和文件夹",
  "Conversation file history exceeds 256 MiB; start a new conversation with the necessary files.": "对话文件历史已满，请新建对话并上传必要文件",
  "Upload at most 64 files per request.": "每段对话最多保存 64 个文件、合计 64 MiB",
  "Uploaded files contain duplicate paths.": "文件路径重复，请整理后重新上传",
  "ZIP archive is invalid or unsupported.": "压缩包无效或格式不支持，请使用 ZIP",
  "ZIP archive entry size is invalid.": "压缩包无效或格式不支持，请使用 ZIP",
  "ZIP archive contains links, special files or encrypted entries.": "ZIP 不支持链接、特殊文件或加密条目",
  "ZIP archive contains too many entries.": "ZIP 条目过多，请精简后重试",
  "No usable files were found in the upload.": "未找到可上传的文件",
  "Environments, dependency caches and Git metadata are not project files.": "文件夹中的依赖、缓存和 Git 数据不会导入",
  "Uploaded paths cannot be both a file and a directory.": "上传路径不能同时是文件和文件夹",
  "Agent upload is empty.": "文件为空（0 字节），请选择有内容的文件",
  "Agent upload could not be read.": "无法读取该文件。",
  "Agent uploads are too large.": "文件超过大小限制，请缩小后重试",
  "Conversation upload exceeds its size limit.": "文件超过大小限制，请缩小后重试",
  "Document is empty.": "文件为空（0 字节），请选择有内容的文件",
  "Document is too large.": "文件超过大小限制，请缩小后重试",
  "Unsupported document type.": "不支持的文件格式",
  "Unsupported file type.": "不支持的文件格式",
  "Document format is not supported.": "不支持的文件格式",
  "Invalid name.": "名称不能为空或仅包含空格",
  "Knowledge model not found.": "检索模型不存在，请重新选择",
  "Knowledge model is disabled.": "检索模型已停用，请重新选择",
  "Embedding model is required.": "请先配置 Embedding 模型",
  "Knowledge model test request failed.": "检索模型测试失败，请检查连接配置后重试",
  "Agent Skill binding permission is no longer valid.": "绑定的技能授权已失效，请重新配置",
  "Skill execution access is no longer valid.": "绑定的技能授权已失效，请重新配置",
  "Knowledge model must be embedding.": "请选择 Embedding 类型的模型",
  "Knowledge model must be reranker.": "请选择 Rerank 类型的模型",
  "Knowledge task is already running.": "知识库已有任务运行中，请完成后重试",
  "Agent Skill is disabled.": "技能已停用，请启用后重试",
  "A bound Agent Skill is disabled.": "绑定的技能已停用或已删除，请重新配置",
  "Disabled Agent Skills cannot be published.": "技能已停用，请启用后再发布",
  "Agent Skill version is not available for binding.": "技能版本不可用，请重新选择",
  "Tool is not available for binding.": "工具不可用，请刷新工具列表后重新选择",
  "Tool version is not available for binding.": "工具不可用，请刷新工具列表后重新选择",
  "Agent Skill publication conflicted.": "技能发布发生冲突，请刷新后重试",
  "Agent Skill publication is invalid.": "技能发布版本无效，请重新发布",
  "Agent Skill knowledge base is not active.": "技能引用的知识库未启用，请重新配置",
  "SMTP settings are not configured.": "尚未配置 SMTP",
  "SMTP test failed.": "SMTP 测试失败，请检查服务器、端口、加密方式和凭据",
  "SMTP host and sender address are required when enabled.":
    "启用 SMTP 时必须填写主机和发件人邮箱",
  "Invalid SMTP sender address.": "发件人邮箱格式无效",
  "Invalid SMTP recipient address.": "收件人邮箱格式无效",
  "Invalid public site URL.": "站点地址格式无效",
  "Value error, Invalid public site URL.": "站点地址格式无效",
  "Public site URL is required when SMTP is enabled.":
    "启用 SMTP 时必须填写站点地址",
  "Email service is not configured.": "邮件服务尚未配置，请联系系统管理员",
  "Password reset is temporarily unavailable.":
    "密码重置暂时不可用，请稍后重试",
  "Too many password reset requests.": "密码重置请求过于频繁，请稍后重试",
  "Password reset link is invalid or expired.": "密码重置链接无效或已过期",
  "Invitation is invalid or expired.": "邀请链接无效或已过期",
  "String should have at least 20 characters": "输入内容过短，请检查后重试",
  "New password must be different.": "新密码不能与原密码相同",
  "Agent name already exists.": "应用名称已存在",
  "Agent response was truncated.": "模型回答被截断，请重试。",
  "Agent Skill name already exists.": "技能名称已存在",
  "Folder name already exists.": "文件夹名称已存在",
  "Model name already exists.": "模型名称已存在",
  "Model already exists.": "模型已存在",
  "MCP server name already exists.": "MCP 服务名称已存在",
  "Knowledge base name already exists.": "知识库名称已存在",
  "Team already exists.": "团队已存在",
  "Workspace already exists.": "工作空间已存在",
  "Username or email already exists.": "用户名或邮箱已存在",
  "Team member already exists.": "该成员已在团队中",
  "Workspace member already exists.": "该成员已在工作空间中",
  "Vision model is not configured for this workspace.":
    "视觉模型尚未配置，暂时不支持图片解析",
  "Model connection test timed out.": "模型连接测试超时，请检查供应商后重试",
}

function localizedMessage(message: string, t: TFunction): string {
  const key =
    API_ERROR_LABEL_KEYS[message] ??
    API_ERROR_LABEL_KEYS[message.replace(/^Value error, /, "")]
  if (key) return t(key)
  const providerStatus =
    /^Knowledge model test failed with provider status (\d+)\.$/.exec(message)
  if (providerStatus)
    return t("检索模型测试失败，模型服务返回状态码 {value}", {
      value: providerStatus[1],
    })
  const length =
    /^String should have (at least|at most) (\d+) characters?$/.exec(message)
  if (length)
    return t(
      length[1] === "at least"
        ? "至少输入 {value} 个字符"
        : "最多输入 {value} 个字符",
      { value: length[2] }
    )
  const bound =
    /^Input should be (greater than or equal to|less than or equal to) (-?[\d.]+)$/.exec(
      message
    )
  if (bound)
    return t(
      bound[1] === "greater than or equal to"
        ? "数值必须大于或等于 {value}"
        : "数值必须小于或等于 {value}",
      { value: bound[2] }
    )
  if (message === "Field required") return t("此项为必填项")
  if (/^Input should be a valid integer/.test(message))
    return t("请输入有效的整数")
  if (/^Input should be a valid number/.test(message))
    return t("请输入有效的数字")
  if (message === "Request failed") return t("请求失败")
  return message
}

const VALIDATION_FIELD_KEYS: Record<string, TranslationKey> = {
  name: "名称",
  description: "描述",
  similarity: "相似度",
  limit: "返回数量",
  query: "查询内容",
}

/**
 * Converts an unknown error into a user-facing message.
 *
 * @param error - The error value to convert
 * @returns A localized message for recognized authentication, authorization, network, or unknown errors; otherwise, the original error message
 */
export function getErrorMessage(error: unknown, t: TFunction) {
  if (error instanceof ApiError) {
    if (error.status === 401 && error.message === "Invalid credentials.") {
      return t("用户名或密码错误")
    }
    if (error.status === 401) return t("请重新登录")
    if (error.status === 403 || error.status === 404) {
      return t("资源不存在或无权访问")
    }
    if (error.validationIssues.length)
      return error.validationIssues
        .map((issue) => {
          const field = [...issue.loc]
            .reverse()
            .find(
              (part) => typeof part === "string" && VALIDATION_FIELD_KEYS[part]
            )
          const reason = localizedMessage(issue.msg, t)
          return t("{name}：{reason}", {
            name: field ? t(VALIDATION_FIELD_KEYS[field]) : t("输入参数"),
            reason,
          })
        })
        .join("\n")
    return localizedMessage(error.message, t)
  }

  if (error instanceof Error) {
    if (/failed to fetch|networkerror|load failed/i.test(error.message)) {
      return t("网络连接失败，请稍后重试")
    }
    return localizedMessage(error.message, t)
  }

  return t("请求失败")
}
