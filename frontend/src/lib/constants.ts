import { type TFunction, type TranslationKey } from "@/i18n"

export const STATUS_LABEL_KEYS: Record<string, TranslationKey> = {
  active: "已启用",
  archived: "已归档",
  disabled: "已停用",
}
export const AUDIT_DETAIL_LABEL_KEYS: Record<string, TranslationKey> = {
  email: "邮箱",
  is_active: "启用状态",
  is_global_admin: "全局管理员",
  name: "名称",
  description: "描述",
  slug: "标识",
  status: "状态",
  team_ids: "团队 ID",
  from_date: "开始日期",
  to_date: "结束日期",
  timezone: "时区",
  interval_days: "统计天数",
  username: "用户名",
  workspace_id: "工作空间 ID",
  knowledge_base_id: "知识库 ID",
  document_id: "文档 ID",
  task_id: "任务 ID",
  user_id: "用户 ID",
  chunk_count: "分片数",
  document_count: "文档数",
  size_bytes: "大小",
  permission: "权限",
}
export const AUDIT_ACTION_LABEL_KEYS: Record<string, TranslationKey> = {
  "workspace.create": "新建工作空间",
  "workspace.update": "更新工作空间",
  "workspace.archive": "归档工作空间",
  "workspace.restore": "恢复工作空间",
  "workspace.delete": "删除工作空间",
  "workspace.analytics.view": "查看数据大屏",
  "team.create": "新建团队",
  "team.update": "更新团队",
  "team.archive": "归档团队",
  "team.restore": "恢复团队",
  "team.delete": "删除团队",
  "user.create": "新建用户",
  "user.update": "更新用户",
  "user.reset_password": "修改密码",
  "user.change_password": "修改密码",
  "user.deactivate": "停用用户",
  "user.delete": "删除用户",
  "model.create": "接入模型",
  "model.update": "更新模型",
  "model.delete": "删除模型",
  "workspace.member.add": "添加成员",
  "workspace.member.remove": "移除成员",
  "workspace.member.update": "更新成员角色",
  "knowledge_base.create": "新建知识库",
  "knowledge_base.update": "更新知识库",
  "knowledge_base.delete": "删除知识库",
  "knowledge_document.upload": "上传文档",
  "knowledge_document.parse": "解析文档",
  "knowledge_document.index": "向量化文档",
  "knowledge_document.delete": "删除文档",
  "knowledge_document.activate": "启用文档",
  "knowledge_document.deactivate": "停用文档",
  "knowledge_document.batch_create": "批量导入文档",
  "knowledge_task.retry": "重试任务",
  "knowledge_task.parse.queue": "解析任务排队",
  "knowledge_task.parse.succeed": "解析任务完成",
  "knowledge_task.parse.fail": "解析任务失败",
  "knowledge_task.index.fail": "向量化任务失败",
  "knowledge_task.rebuild_index.fail": "重建索引失败",
  "resource_permission.grant": "授权资源",
  "resource_permission.revoke": "撤销授权",
  "agent.create": "创建 Agent",
  "agent.update": "更新 Agent",
  "agent.delete": "删除 Agent",
  "agent.api_credential.create": "创建 Agent API 凭据",
  "agent.api_credential.revoke": "撤销 Agent API 凭据",
  "agent.api_credential.rotate": "轮换 Agent API 凭据",
  "agent.tool_call.approve": "批准 Agent 工具调用",
  "team.member.add": "添加团队成员",
  "team.member.remove": "移除团队成员",
  "team.member.update": "更新团队成员角色",
  "knowledge_attachment.upload": "上传知识库附件",
  "knowledge_base.owner_transfer": "转移知识库所有权",
  "knowledge_document.create_from_attachments": "从附件创建知识文档",
  "knowledge_evaluation_case.create": "创建评测用例",
  "knowledge_evaluation_run.delete": "删除运行记录",
  "mcp_server.create": "创建 MCP 服务",
  "mcp_server.delete": "删除 MCP 服务",
  "mcp_server.enable": "启用 MCP 服务",
  "mcp_server.refresh": "刷新 MCP 服务",
  "mcp_tool.policy.update": "更新 MCP 工具策略",
  "tool.create": "创建工具",
  "tool.delete": "删除工具",
  "tool.draft.update": "更新工具草稿",
  "tool.enable": "启用工具",
  "tool.publish": "发布工具",
  "workspace.governance.update": "更新工作空间治理",
  "workspace.invitation.create": "创建工作空间邀请",
  "workspace.invitation.accept": "接受工作空间邀请",
  "workspace.invitation.revoke": "撤销工作空间邀请",
}

export const SYSTEM_LOG_LEVEL_LABEL_KEYS: Record<string, TranslationKey> = {
  critical: "严重",
  error: "错误",
  warning: "警告",
  info: "信息",
  debug: "调试",
}

export const SYSTEM_LOG_EVENT_LABEL_KEYS: Record<string, TranslationKey> = {
  "auth.login_failed": "登录失败",
  "request.unhandled_exception": "请求处理异常",
  "agent.execution_failed": "Agent 执行失败",
  "workflow.execution_failed": "工作流执行失败",
}

export function auditActionLabel(action: string, t: TFunction) {
  const labelKey = AUDIT_ACTION_LABEL_KEYS[action]
  return labelKey ? t(labelKey) : t("其他操作")
}

export function systemLogLevelLabel(level: string, t: TFunction) {
  const labelKey = SYSTEM_LOG_LEVEL_LABEL_KEYS[level]
  return labelKey ? t(labelKey) : t("其他级别")
}

export function systemLogEventLabel(event: string, t: TFunction) {
  const labelKey = SYSTEM_LOG_EVENT_LABEL_KEYS[event]
  return labelKey ? t(labelKey) : t("其他系统事件")
}
