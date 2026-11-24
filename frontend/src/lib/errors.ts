import { ApiError } from "@/lib/api-client"
import { en, zhHans, type TFunction, type TranslationKey } from "@/i18n"

const API_ERROR_LABEL_KEYS: Record<string, TranslationKey> = {
  "Automation is paused; resume it before manual execution.":
    "自动化已暂停，请恢复后再执行",
  "An active execution is already running for this automation.":
    "该自动化已有未完成的任务",
  "Skipped because a previous run is still active.":
    "上一次任务尚未结束，本次已跳过",
  "Cancelled before run creation.": "任务在开始执行前已取消",
  "Completed one-time automation cannot be resumed without rescheduling.":
    "单次任务已完成，请修改执行时间后再启用",
  "Target application must be published before binding an automation.":
    "请先发布目标应用",
  "Target application has been unpublished.": "目标应用已取消发布",
  "Target application is unavailable or disabled.": "目标应用不可用或已停用",
  "Application publisher is inactive.": "应用发布者已停用或不再可用",
  "Automation owner user is inactive or missing.":
    "自动化所属用户已停用或不存在",
  "Pinned agent publication version is missing.":
    "绑定的应用版本已不存在，请重新选择",
  "Pinned workflow published version is missing.":
    "绑定的应用版本已不存在，请重新选择",
  "Automation webhook pending queue is full.": "事件队列已满，请稍后重试",
  "Automation task input exceeds 4000 characters.":
    "任务输入超过4000字符，请缩短提示词或提取范围",
  "Published applications require workspace-shared models.":
    "发布应用需要使用工作空间共享模型",
  "Agent model not found.": "所选模型不存在或当前用户无权使用",
  "Agent image model not found.": "所选模型不存在或当前用户无权使用",
  "Uncertain tool calls cannot be retried through approval; verify the external state and reject the retry to continue.":
    "此调用可能已执行，无法通过批准操作重试。请核对结果后选择“不重试并继续”。",
  "Tool invocation deadline expired.":
    "工具执行已超时，请先核对外部服务的结果。",
  "Tool invocation outcome is uncertain after worker recovery.":
    "工具执行结果无法确认，请先核对外部服务的结果。",
  "Tool invocation outcome is uncertain after dispatch.":
    "工具执行结果无法确认，请先核对外部服务的结果。",
  "Model not found.": "所选模型不存在或当前用户无权使用",
  "Member model endpoints must use public network addresses.":
    "成员接入的模型仅支持公网地址",
  "Member model parameters cannot override connection settings.":
    "模型参数不能覆盖连接设置",
  "Personal Bedrock models require explicit AWS credentials.":
    "个人Bedrock模型必须填写AWS访问凭据",
  "Personal Bedrock models require the official regional endpoint.":
    "个人Bedrock模型仅支持官方区域接口",
  "Invalid Bedrock region.": "Bedrock区域无效",
  "Invalid member model endpoint.": "模型连接地址无效",
  "Model management access denied.": "无权管理此模型",
  "Workspace admin required to create shared models.":
    "只有工作空间管理员可以创建共享模型",
  "Model visibility cannot be changed. Create a separate model instead.":
    "使用范围创建后不可更改，如需其他范围请重新接入。",
  "Invalid integration arguments.":
    "集成参数无效，请检查资源标识、时间和操作参数。",
  "Invalid integration resource identifier.":
    "集成参数无效，请检查资源标识、时间和操作参数。",
  "Invalid integration arguments. Inspect the operation schema before calling it.":
    "集成参数无效，请检查资源标识、时间和操作参数。",
  "Integration operation requires the matching read or write tool.":
    "集成参数无效，请检查资源标识、时间和操作参数。",
  "Integration tool definition changed. Update tools and select this integration again.":
    "工具已更新，请在 Agent 中取消并重新勾选此集成，然后保存。",

  "Integration authorization origin is not allowed.":
    "当前访问地址不可用于授权，请从 NexaFlow 网站重新登录。",
  "Invalid integration operation arguments.":
    "集成参数无效，请检查资源标识、时间和操作参数。",
  "Configure the administrator-managed public site URL before connecting OAuth.":
    "请先由系统管理员配置公开站点地址。",
  "Integration not found.": "当前用户尚未安装此集成，请重新安装。",
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
  "Integration change could not be confirmed. Check the platform result before retrying.":
    "无法确认集成更改是否生效，请核对平台结果后再重试。",
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
  "Memory contains sensitive information.":
    "记忆中不能保存密码、密钥等敏感信息",
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

  "Workspace monthly token quota exceeded.":
    "工作空间本月模型 Token 额度不足，请联系管理员",
  "Artifact workspace path is invalid.": "文件路径无效，请检查文件夹或压缩包",
  "Artifact filename is invalid.": "文件路径无效，请检查文件夹或压缩包",
  "Uploaded file path exceeds 255 characters.": "文件路径过长，最多 255 个字符",
  "Each conversation file must not exceed 5 MiB.": "单个文件不能超过 5 MiB",
  "Each project file must not exceed 5 MiB.": "单个文件不能超过 5 MiB",
  "Conversation files exceed 64 files or 64 MiB.":
    "每段对话最多保存 64 个文件、合计 64 MiB",
  "Project file count exceeds its limit.":
    "每段对话最多保存 64 个文件、合计 64 MiB",
  "Project files exceed 64 MiB.": "每段对话最多保存 64 个文件、合计 64 MiB",
  "Project paths cannot be both a file and a parent directory.":
    "上传路径不能同时是文件和文件夹",
  "Conversation file history exceeds 256 MiB; start a new conversation with the necessary files.":
    "对话文件历史已满，请新建对话并上传必要文件",
  "Upload at most 64 files per request.":
    "每段对话最多保存 64 个文件、合计 64 MiB",
  "Uploaded files contain duplicate paths.": "文件路径重复，请整理后重新上传",
  "ZIP archive is invalid or unsupported.":
    "压缩包无效或格式不支持，请使用 ZIP",
  "ZIP archive entry size is invalid.": "压缩包无效或格式不支持，请使用 ZIP",
  "ZIP archive contains links, special files or encrypted entries.":
    "ZIP 不支持链接、特殊文件或加密条目",
  "ZIP archive contains too many entries.": "ZIP 条目过多，请精简后重试",
  "No usable files were found in the upload.": "未找到可上传的文件",
  "Environments, dependency caches and Git metadata are not project files.":
    "文件夹中的依赖、缓存和 Git 数据不会导入",
  "Uploaded paths cannot be both a file and a directory.":
    "上传路径不能同时是文件和文件夹",
  "Agent upload is empty.": "文件为空（0 字节），请选择有内容的文件",
  "Agent upload could not be read.": "无法读取该文件。",
  "Agent uploads are too large.": "文件超过大小限制，请缩小后重试",
  "Conversation upload exceeds its size limit.":
    "文件超过大小限制，请缩小后重试",
  "Document is empty.": "文件为空（0 字节），请选择有内容的文件",
  "Document is too large.": "文件超过大小限制，请缩小后重试",
  "Unsupported document type.": "不支持的文件格式",
  "Unsupported file type.": "不支持的文件格式",
  "Document format is not supported.": "不支持的文件格式",
  "Invalid name.": "名称不能为空或仅包含空格",
  "Knowledge model not found.": "检索模型不存在，请重新选择",
  "Knowledge model is disabled.": "检索模型已停用，请重新选择",
  "Embedding model is required.": "请先配置 Embedding 模型",
  "Knowledge model test request failed.":
    "检索模型测试失败，请检查连接配置后重试",
  "Agent Skill binding permission is no longer valid.":
    "绑定的技能授权已失效，请重新配置",
  "Skill execution access is no longer valid.":
    "绑定的技能授权已失效，请重新配置",
  "Knowledge model must be embedding.": "请选择 Embedding 类型的模型",
  "Knowledge model must be reranker.": "请选择 Rerank 类型的模型",
  "Knowledge task is already running.": "知识库已有任务运行中，请完成后重试",
  "Agent Skill is disabled.": "技能已停用，请启用后重试",
  "A bound Agent Skill is disabled.": "绑定的技能已停用或已删除，请重新配置",
  "Disabled Agent Skills cannot be published.": "技能已停用，请启用后再发布",
  "Agent Skill version is not available for binding.":
    "技能版本不可用，请重新选择",
  "Tool is not available for binding.": "工具不可用，请刷新工具列表后重新选择",
  "Tool version is not available for binding.":
    "工具不可用，请刷新工具列表后重新选择",
  "Agent Skill publication conflicted.": "技能发布发生冲突，请刷新后重试",
  "Agent Skill publication is invalid.": "技能发布版本无效，请重新发布",
  "Agent Skill knowledge base is not active.":
    "技能引用的知识库未启用，请重新配置",
  "SMTP settings are not configured.": "尚未配置 SMTP",
  "SMTP test failed.": "SMTP 测试失败，请检查服务器、端口、加密方式和凭据",
  "SMTP host and sender address are required when enabled.":
    "启用 SMTP 时必须填写主机和发件人邮箱",
  "Invalid SMTP sender address.": "发件人邮箱格式无效",
  "Invalid SMTP recipient address.": "收件人邮箱格式无效",
  "Invalid public site URL.": "站点地址格式无效",
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
  "Current password is invalid.": "当前密码错误",
  "Too many login attempts.": "登录尝试过于频繁，请稍后重试",
  "Too many enterprise login attempts.": "登录尝试过于频繁，请稍后重试",
  "Login rate limiter is unavailable.": "登录服务暂时不可用，请稍后重试",
  "Enterprise login rate limiter is unavailable.":
    "登录服务暂时不可用，请稍后重试",
  "Enterprise login is not available.": "登录服务暂时不可用，请稍后重试",
  "Invalid username.": "用户名格式无效",
  "Invalid email.": "邮箱格式无效",
  "Current user cannot be deleted.": "不能删除当前账号",
  "Current user cannot be disabled.": "不能停用当前账号",
  "Current user cannot remove own global admin role.":
    "不能移除自己的系统管理员权限",
  "Workspace must keep at least one admin.":
    "工作空间必须至少保留一名有效管理员",
  "Workspace must keep at least one active admin.":
    "工作空间必须至少保留一名有效管理员",
  "Team must keep at least one admin.": "团队必须至少保留一名管理员",
  "Workspace is not active.": "工作空间已停用或不可用",
  "Workspace is inactive or unavailable.": "工作空间已停用或不可用",
  "Model test request failed.": "模型连接测试失败，请检查配置后重试",
  "Model is in use.": "模型正在使用中，无法删除",
  "Agent model is disabled.": "所选模型已停用，请重新选择",
  "Agent image model is disabled.": "所选模型已停用，请重新选择",
  "Agent model must be an LLM.": "请选择对话类型的模型",
  "Agent image model must be an image model.": "请选择图像类型的模型",
  "Stored model credentials are invalid.": "模型凭据无效，请重新配置",
  "Model request parameters must be valid JSON.":
    "额外请求参数必须是有效的 JSON 对象。",
  "Model request parameter max_tokens must be a positive integer.":
    "模型参数 max_tokens 必须为正整数",
  "Invalid model provider.": "模型供应商或类型无效，请重新选择",
  "Invalid model provider type.": "模型供应商或类型无效，请重新选择",
  "Invalid provider type for provider.": "模型供应商或类型无效，请重新选择",
  "Unsupported provider.": "模型供应商或类型无效，请重新选择",
  "Model type is not supported by this provider.":
    "模型供应商或类型无效，请重新选择",
  "AWS access key ID and secret access key must be provided together.":
    "请同时填写 AWS 访问密钥 ID 和访问密钥",
  "AWS session token requires access key credentials.":
    "请同时填写 AWS 访问密钥 ID 和访问密钥",
  "Agent run timed out.": "Agent 回答超时",
  "Agent execution deadline exceeded.": "Agent 回答超时",
  "Agent model response timed out.": "Agent 回答超时",
  "Agent execution failed.": "Agent 回答失败",
  "Agent run failed.": "Agent 回答失败",
  "Agent model request failed.": "Agent 回答失败",
  "Agent returned an empty response.": "Agent 未返回结果",
  "This conversation already has an active run.":
    "此对话已有任务运行中，请稍后重试",
  "This workflow conversation already has an active run.":
    "此对话已有任务运行中，请稍后重试",
  "Cannot delete a conversation while it is running.":
    "请先停止正在执行的任务，再进行删除",
  "Agent has an active run or Tool call.": "请先停止正在执行的任务，再进行删除",
  "Agent run is already finished.": "任务已结束，请发送新消息",
  "Agent run is already finished. Send a new session prompt.":
    "任务已结束，请发送新消息",
  "Workflow run is already finished.": "任务已结束，请发送新消息",
  "Agent turn limit reached.": "已达到最大对话轮数，请新建任务",
  "Agent tool call limit reached.": "已达到工具调用次数上限",
  "Workflow model tool call limit reached.": "已达到工具调用次数上限",
  "Agent compacted context exceeds the model window.":
    "对话内容超过模型上下文限制，请新建对话",
  "Agent context cannot fit the current interaction.":
    "对话内容超过模型上下文限制，请新建对话",
  "Agent context cannot fit the compaction instructions.":
    "对话内容超过模型上下文限制，请新建对话",
  "Agent model configuration changed after run creation.":
    "应用配置或授权已变更，请保存后重新运行",
  "Agent knowledge configuration changed after run creation.":
    "应用配置或授权已变更，请保存后重新运行",
  "Agent knowledge access changed after run creation.":
    "应用配置或授权已变更，请保存后重新运行",
  "Tool binding changed; save the application again.":
    "应用配置或授权已变更，请保存后重新运行",
  "Agent is disabled.": "应用已停用，请启用后重试",
  "Workflow is disabled.": "应用已停用，请启用后重试",
  "Target application must be active.": "应用已停用，请启用后重试",
  "Disabled agents cannot be published.": "应用已停用，请启用后再发布",
  "Agent run rate limit exceeded.": "请求过于频繁，请稍后重试",
  "Workflow run rate limit exceeded.": "请求过于频繁，请稍后重试",
  "Agent run service is temporarily unavailable.":
    "执行资源暂时不可用，请稍后重试",
  "Workflow run service is temporarily unavailable.":
    "执行资源暂时不可用，请稍后重试",
  "Command runtime is busy.": "执行资源暂时不可用，请稍后重试",
  "File runtime is busy.": "执行资源暂时不可用，请稍后重试",
  "Skill runtime is busy.": "执行资源暂时不可用，请稍后重试",
  "MCP server host is busy.": "执行资源暂时不可用，请稍后重试",
  "Waiting for execution resources.": "执行资源暂时不可用，请稍后重试",
  "Workspace daily run quota exceeded.":
    "工作空间今日运行额度已用完，请联系管理员",
  "Workflow draft changed; reload it before saving.":
    "工作流草稿已更新，请刷新后再保存",
  "Workflow version must be republished before it can run.":
    "请先发布工作流的最新版本",
  "Workflow is not published.": "请先发布工作流的最新版本",
  "Workflow must be published before binding an automation.":
    "请先发布工作流的最新版本",
  "Workflow model is unavailable.": "所选模型不存在或当前用户无权使用",
  "Workflow reranker model is unavailable.": "所选模型不存在或当前用户无权使用",
  "The source Agent model is no longer available.":
    "所选模型不存在或当前用户无权使用",
  "Workflow Tool configuration is no longer executable.":
    "工作流工具配置已失效，请重新配置并发布",
  "A source Workflow Tool is no longer executable.":
    "工作流工具配置已失效，请重新配置并发布",
  "Workflow Tool snapshot is unavailable.":
    "工作流工具配置已失效，请重新配置并发布",
  "Workflow form was already submitted.": "表单已提交，请勿重复提交",
  "Workflow is not awaiting form input.": "表单状态已变更，请刷新后重试",
  "Workflow form node changed.": "表单状态已变更，请刷新后重试",
  "Workflow form node is unavailable.": "表单状态已变更，请刷新后重试",
  "Form contains unknown fields.": "表单包含无效字段，请检查后重试",
  "Workflow condition did not match a branch.":
    "条件未匹配任何分支，请检查工作流配置",
  "Workflow output exceeds 256 KiB.": "工作流输出超过 256 KiB，请缩小输出内容",
  "Workflow node output exceeds 256 KiB.":
    "工作流输出超过 256 KiB，请缩小输出内容",
  "Knowledge base has no indexed chunks.":
    "知识库暂无已索引的内容，请先完成索引",
  "Knowledge base is archived.": "知识库已归档",
  "Agent knowledge base is archived.": "知识库已归档",
  "Knowledge task queue is unavailable.":
    "知识库任务服务暂时不可用，请稍后重试",
  "Knowledge task retry limit reached.":
    "知识库任务已达到重试上限，请重新创建任务",
  "Stop the knowledge task before deleting it.":
    "请先停止知识库任务，再进行删除",
  "Chunk overlap must be smaller than chunk size.":
    "分段重叠长度必须小于分段长度",
  "Document preview must be generated before indexing.":
    "请先生成文档分段预览，再建立索引",
  "Document has no preview chunks.": "请先生成文档分段预览，再建立索引",
  "Document has no extractable text.": "文档中没有可提取的文本，请检查文件内容",
  "Document has no extractable chunks.":
    "文档中没有可提取的文本，请检查文件内容",
  "Document text extraction failed.": "文档内容提取失败，请检查文件是否损坏",
  "Agent attachment text could not be extracted.":
    "文档内容提取失败，请检查文件是否损坏",
  "Workflow document content could not be extracted.":
    "文档内容提取失败，请检查文件是否损坏",
  "Document file is missing.": "文档内容不可用，请重新上传或解析",
  "Document Markdown is not available.": "文档内容不可用，请重新上传或解析",
  "Workflow document content is unavailable.":
    "文档内容不可用，请重新上传或解析",
  "QA import requires question/问题 and answer/答案 headers.":
    "问答表必须包含“问题”和“答案”表头",
  "QA import has no header row.": "问答表缺少表头或有效数据",
  "QA import has no data rows.": "问答表缺少表头或有效数据",
  "QA CSV must use UTF-8 encoding.": "问答 CSV 文件必须使用 UTF-8 编码",
  "QA import supports CSV and XLSX files only.":
    "问答导入仅支持 CSV 和 XLSX 文件",
  "Evaluation run is in progress.": "评测仍在运行，请完成后重试",
  "Evaluation task has no cases.": "请先添加有效的评测问题",
  "Evaluation text cannot be blank.": "请先添加有效的评测问题",
  "File upload is disabled.": "文件上传已关闭",
  "Upload files.": "请先选择要上传的文件",
  "Invalid MCP server URL.": "MCP 服务地址无效或无法解析，请检查配置",
  "MCP server URL is required.": "MCP 服务地址无效或无法解析，请检查配置",
  "MCP server hostname could not be resolved.":
    "MCP 服务地址无效或无法解析，请检查配置",
  "MCP source is unavailable.": "MCP 服务不可用，请检查配置后重试",
  "MCP Tool source is unavailable.": "MCP 服务不可用，请检查配置后重试",
  "Agent MCP tool is not available.": "MCP 服务不可用，请检查配置后重试",
  "MCP server request failed.": "MCP 服务不可用，请检查配置后重试",
  "MCP bridge request failed.": "MCP 服务不可用，请检查配置后重试",
  "MCP bridge could not start.": "MCP 服务不可用，请检查配置后重试",
  "MCP server host could not start.": "MCP 服务不可用，请检查配置后重试",
  "MCP OAuth access expired; reconnect the source.":
    "MCP 授权已失效，请重新连接",
  "MCP OAuth refresh failed; reconnect the source.":
    "MCP 授权已失效，请重新连接",
  "MCP OAuth refresh outcome is unknown; reconnect the source.":
    "MCP 授权已失效，请重新连接",
  "MCP OAuth requires reconnection.": "MCP 授权已失效，请重新连接",
  "OAuth state is invalid or expired.": "MCP 授权已失效，请重新连接",
  "Disconnect OAuth before changing its configuration.":
    "请先断开现有授权，再修改配置或重新连接",
  "Disconnect the existing OAuth grant before reconnecting.":
    "请先断开现有授权，再修改配置或重新连接",
  "Skill archive is missing SKILL.md.": "技能包必须包含且仅包含一个 SKILL.md",
  "Skill archive must contain exactly one SKILL.md.":
    "技能包必须包含且仅包含一个 SKILL.md",
  "Skill package exceeds 2 MiB.":
    "技能包须为 1 字节至 2 MiB，且不超过 64 个文件",
  "Skill package exceeds its size or file-count limit.":
    "技能包须为 1 字节至 2 MiB，且不超过 64 个文件",
  "Skill upload must be between 1 byte and 2 MiB.":
    "技能包须为 1 字节至 2 MiB，且不超过 64 个文件",
  "Skill archive contains duplicate paths.": "技能包包含重复或不安全的文件路径",
  "Skill archive contains files outside its package root.":
    "技能包包含重复或不安全的文件路径",
  "Skill archives cannot contain links, special files or encrypted entries.":
    "技能包包含重复或不安全的文件路径",
  "Skill files must use relative, normalized paths.":
    "技能包包含重复或不安全的文件路径",
  "Pinned Skill definition changed.": "技能定义已变更或无效，请重新绑定",
  "Agent Skill definition is invalid.": "技能定义已变更或无效，请重新绑定",
  "Agent Skill snapshot is invalid.": "技能定义已变更或无效，请重新绑定",
  "Configure an active OpenAI-compatible image model in this workspace first.":
    "请先配置并启用可用的图像模型",
  "The queued image model is no longer active in this workspace.":
    "请先配置并启用可用的图像模型",
  "The selected image model is no longer available.":
    "请先配置并启用可用的图像模型",
  "The queued image model is no longer available.":
    "请先配置并启用可用的图像模型",
  "Image generation failed or returned an unusable image.":
    "图片生成失败或返回内容无效，请重试",
  "Image model returned no usable PNG image.":
    "图片生成失败或返回内容无效，请重试",
  "Image model returned invalid image data.":
    "图片生成失败或返回内容无效，请重试",
  "Image model returned an unexpected image format.":
    "图片生成失败或返回内容无效，请重试",
  "Image model returned an incomplete JSON response.":
    "图片生成失败或返回内容无效，请重试",
  "Image model returned an invalid JSON response.":
    "图片生成失败或返回内容无效，请重试",
  "Generated image exceeds the 5 MiB file limit.":
    "生成图片超过 5 MiB 大小限制",
  "Image model response exceeds the image size limit.":
    "生成图片超过 5 MiB 大小限制",
  "Image model configuration changed after this call was queued.":
    "图像模型配置已变更，请重新运行",
  "Archived announcement cannot be edited.": "已归档的公告无法编辑或发布",
  "Archived announcement cannot be published.": "已归档的公告无法编辑或发布",
  "Only archived announcements can be deleted.": "请先归档公告，再进行删除",
  "Announcement expiry must be after publication.":
    "公告过期时间必须晚于发布时间",
  "Automation is paused and cannot accept webhook events.":
    "自动化已暂停，暂时无法接收事件",
  "Webhook payload must be a JSON object.":
    "事件内容必须为有效的 UTF-8 JSON 对象",
  "Webhook payload must be valid UTF-8 JSON.":
    "事件内容必须为有效的 UTF-8 JSON 对象",
  "Webhook event ID already received with different payload.":
    "事件标识已使用，且本次内容与原事件不同",
  "Copy failed": "复制失败",
}

function localizedMessage(
  message: string,
  t: TFunction,
  fallback: TranslationKey = "请求失败"
): string {
  const originalMessage = message.trim()
  message = originalMessage.replace(/^Value error, /, "")
  const key =
    (Object.hasOwn(API_ERROR_LABEL_KEYS, message)
      ? API_ERROR_LABEL_KEYS[message]
      : undefined) ??
    (Object.hasOwn(zhHans, message) ? (message as TranslationKey) : undefined)
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
    /^Input should be (greater than or equal to|less than or equal to|greater than|less than) (-?[\d.]+)$/.exec(
      message
    )
  if (bound)
    return t(
      bound[1] === "greater than or equal to"
        ? "数值必须大于或等于 {value}"
        : bound[1] === "less than or equal to"
          ? "数值必须小于或等于 {value}"
          : bound[1] === "greater than"
            ? "数值必须大于 {value}"
            : "数值必须小于 {value}",
      { value: bound[2] }
    )
  if (message === "Field required") return t("此项为必填项")
  if (/^Input should be a valid integer/.test(message))
    return t("请输入有效的整数")
  if (/^Input should be a valid number/.test(message))
    return t("请输入有效的数字")
  if (/^Input should be a valid string/.test(message))
    return t("请输入有效的文本")
  if (/^Input should be a valid boolean/.test(message))
    return t("请选择有效的开关值")
  if (/^Input should be a valid (?:dictionary|list|object)/.test(message))
    return t("输入参数无效，请检查后重试")
  if (message === "Request failed") return t("请求失败")
  // Keep upstream diagnostics on the error itself. Chinese UI must not fall
  // back to an untranslated provider, browser, or validation error.
  if (
    message &&
    (/^[^\p{L}]*\p{Script=Han}/u.test(message) ||
      t("请求失败") === en["请求失败"])
  ) {
    return originalMessage
  }
  return t(fallback)
}

const HTTP_ERROR_LABEL_KEYS: Record<number, TranslationKey> = {
  400: "输入参数无效，请检查后重试",
  408: "请求超时，请稍后重试",
  409: "操作冲突，请刷新后重试",
  413: "请求内容超过大小限制，请缩小后重试",
  415: "不支持的文件格式",
  422: "输入参数无效，请检查后重试",
  429: "请求过于频繁，请稍后重试",
  504: "请求超时，请稍后重试",
}

const VALIDATION_FIELD_KEYS: Record<string, TranslationKey> = {
  name: "名称",
  description: "描述",
  username: "用户名",
  email: "邮箱",
  password: "密码",
  current_password: "当前密码",
  new_password: "新密码",
  similarity: "相似度",
  limit: "返回数量",
  query: "查询内容",
}

/**
 * Converts an unknown error into a user-facing message.
 *
 * @param error - The error value to convert
 * @returns A localized message, with a translated fallback for unknown errors in Chinese
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
              (part) =>
                typeof part === "string" &&
                Object.hasOwn(VALIDATION_FIELD_KEYS, part)
            )
          const reason = localizedMessage(
            issue.msg,
            t,
            "输入参数无效，请检查后重试"
          )
          return t("{name}：{reason}", {
            name: field ? t(VALIDATION_FIELD_KEYS[field]) : t("输入参数"),
            reason,
          })
        })
        .join("\n")
    const fallback =
      HTTP_ERROR_LABEL_KEYS[error.status] ??
      (error.status >= 500 ? "服务暂时不可用，请稍后重试" : "请求失败")
    return localizedMessage(error.message, t, fallback)
  }

  if (error instanceof Error) {
    if (/failed to fetch|networkerror|load failed/i.test(error.message)) {
      return t("网络连接失败，请稍后重试")
    }
    return localizedMessage(error.message, t)
  }

  return t("请求失败")
}
