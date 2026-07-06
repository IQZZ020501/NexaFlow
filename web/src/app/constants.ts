import { type TranslationKey } from "@/lib/i18n"

export const DEFAULT_USER_PASSWORD = "NexaFlow@123"

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
  username: "用户名",
  workspace_id: "工作空间 ID",
}
export const AUDIT_ACTION_LABEL_KEYS: Record<string, TranslationKey> = {
  "workspace.create": "新建工作空间",
  "workspace.update": "更新工作空间",
  "workspace.archive": "归档工作空间",
  "workspace.restore": "恢复工作空间",
  "workspace.delete": "删除工作空间",
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
}
