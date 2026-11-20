import type { TFunction, TranslationKey } from "@/i18n"
import type { IntegrationProvider } from "@/lib/api/integrations"

export const integrationCatalog = [
  {
    provider: "dida",
    name: "滴答清单",
    // https://cncdn.dida365.com/web/static/img/apple-touch-icon-180x180.png
    icon: "/integration-icons/dida.png",
    description: "管理任务、清单和标签，记录习惯与专注，查询日历和倒数日。",
    documentation: "https://help.dida365.com/articles/7464976698707017728",
  },
  {
    provider: "feishu",
    name: "飞书",
    icon: "/feishu.svg",
    description:
      "连接飞书或 Lark，管理消息、邮件、日历、文档、表格、会议、任务和审批等。",
    documentation: "https://www.feishu.cn/feishu-cli",
  },
  {
    provider: "tencent_meeting",
    name: "腾讯会议",
    // https://cdn.meeting.tencent.com/assets/next-website/logo128.png
    icon: "/integration-icons/tencent-meeting.png",
    description:
      "管理会议、受邀成员和录制，读取纪要、转写及参会报告，查询通讯录并执行会中控制。",
    documentation: "https://meeting.tencent.com/ai-tab/ai-cli/",
  },
] as const satisfies readonly {
  provider: IntegrationProvider
  name: TranslationKey
  icon: string
  description: TranslationKey
  documentation: string
}[]

export function integrationName(provider: IntegrationProvider): TranslationKey {
  return integrationCatalog.find((entry) => entry.provider === provider)!.name
}

export function integrationSourceName(name: string): TranslationKey | null {
  return (
    (
      {
        Dida365: "滴答清单",
        Feishu: "飞书",
        "Tencent Meeting": "腾讯会议",
      } as const
    )[name as "Dida365" | "Feishu" | "Tencent Meeting"] ?? null
  )
}

const operationLabels: Record<string, TranslationKey> = {
  tencent_meeting_get_by_code: "按会议号查询腾讯会议",
  tencent_meeting_list_ended: "查看腾讯历史会议",
  tencent_meeting_search_meetings: "搜索腾讯会议",
  tencent_meeting_create_meeting: "创建腾讯会议",
  tencent_meeting_update_meeting: "更新腾讯会议",
  tencent_meeting_cancel_meeting: "取消腾讯会议",
  tencent_meeting_list_invitees: "查看腾讯会议受邀成员",
  tencent_meeting_add_invitees: "添加腾讯会议受邀成员",
  tencent_meeting_remove_invitees: "移除腾讯会议受邀成员",
  tencent_meeting_replace_invites: "替换腾讯会议邀请名单",
  tencent_meeting_search_records: "搜索腾讯会议录制",
  tencent_meeting_record_download: "获取腾讯录制下载地址",
  tencent_meeting_record_minutes: "读取腾讯录制纪要",
  tencent_meeting_record_todos: "读取腾讯会议待办",
  tencent_meeting_transcript_get: "读取腾讯会议转写",
  tencent_meeting_transcript_find: "搜索腾讯会议转写",
  tencent_meeting_transcript_part: "读取腾讯转写段落",
  tencent_meeting_record_timeline: "读取腾讯录制时间轴",
  tencent_meeting_minutes_by_url: "通过分享链接读取腾讯纪要",
  tencent_meeting_transcript_url: "通过分享链接读取腾讯转写",
  tencent_meeting_participants: "查看腾讯会议参会报告",
  tencent_meeting_waiting_log: "查看腾讯会议等候室记录",
  tencent_meeting_export_members: "导出腾讯会议参会明细",
  tencent_meeting_export_result: "查看腾讯会议导出结果",
  tencent_meeting_search_contacts: "搜索腾讯会议通讯录",
  tencent_meeting_lookup_email: "按邮箱查询腾讯会议成员",
  tencent_meeting_lookup_phone: "按手机号查询腾讯会议成员",
  tencent_meeting_call_members: "呼叫腾讯会议成员入会",
  tencent_meeting_kick_members: "移出腾讯会议成员",
  tencent_meeting_waiting_control: "管理腾讯会议等候室",
  tencent_meeting_search_minutes: "搜索腾讯会议纪要",
  tencent_meeting_get_minutes: "读取腾讯会议纪要",
  tencent_meeting_live_minutes: "读取腾讯实时会议纪要",
  dida_get_preference: "读取滴答偏好",
  dida_get_task: "读取滴答任务",
  dida_update_task: "更新滴答任务",
  dida_complete_tasks: "批量完成滴答任务",
  dida_delete_task: "删除滴答任务",
  dida_move_tasks: "移动滴答任务",
  dida_assign_task: "分配滴答任务",
  dida_unassign_task: "取消分配滴答任务",
  dida_list_completed_tasks: "查看滴答已完成任务",
  dida_filter_tasks: "筛选滴答任务",
  dida_search_tasks: "搜索滴答任务",
  dida_list_task_comments: "查看滴答任务评论",
  dida_add_task_comment: "添加滴答任务评论",
  dida_delete_task_comment: "删除滴答任务评论",
  dida_get_project: "读取滴答清单详情",
  dida_get_project_data: "读取滴答清单数据",
  dida_list_project_members: "查看滴答清单成员",
  dida_create_project: "创建滴答清单",
  dida_update_project: "更新滴答清单",
  dida_delete_project: "删除滴答清单",
  dida_list_project_groups: "查看滴答清单文件夹",
  dida_create_project_group: "创建滴答清单文件夹",
  dida_update_project_group: "更新滴答清单文件夹",
  dida_delete_project_group: "删除滴答清单文件夹",
  dida_list_columns: "查看滴答看板列",
  dida_create_column: "创建滴答看板列",
  dida_update_column: "更新滴答看板列",
  dida_list_tags: "查看滴答标签",
  dida_create_tag: "创建滴答标签",
  dida_update_tag: "更新滴答标签",
  dida_rename_tag: "重命名滴答标签",
  dida_delete_tag: "删除滴答标签",
  dida_get_focus: "读取滴答专注记录",
  dida_list_focus: "查看滴答专注记录",
  dida_create_focus: "创建滴答专注记录",
  dida_update_focus: "更新滴答专注记录",
  dida_delete_focus: "删除滴答专注记录",
  dida_get_habit: "读取滴答习惯",
  dida_list_habit_sections: "查看滴答习惯分区",
  dida_list_habits: "查看滴答习惯",
  dida_create_habit: "创建滴答习惯",
  dida_update_habit: "更新滴答习惯",
  dida_create_habit_checkin: "滴答习惯打卡",
  dida_list_habit_checkins: "查看滴答习惯打卡",
  dida_list_calendar_accounts: "查看滴答日历账号",
  dida_query_calendar_events: "查询滴答日历事件",
  dida_list_countdowns: "查看滴答倒数日",
  dida_list_projects: "查看滴答清单",
  dida_list_tasks: "读取滴答待办",
  dida_create_task: "创建滴答任务",
  dida_complete_task: "完成滴答任务",
  feishu_list_operations: "查找飞书操作",
  feishu_describe_operation: "查看飞书操作参数",
  feishu_read_api: "读取飞书数据",
  feishu_write_api: "执行飞书操作",
  // Preserve translated labels in immutable invocation history.
  feishu_read_document: "读取飞书文档",
  feishu_send_message: "发送飞书消息",
  tencent_meeting_list_meetings: "查看腾讯会议列表",
  tencent_meeting_get_meeting: "读取腾讯会议详情",
}

export function integrationToolName(functionName: string, t: TFunction) {
  const key = operationLabels[functionName.replace(/_[a-f0-9]{32}$/, "")]
  return key ? t(key) : null
}
