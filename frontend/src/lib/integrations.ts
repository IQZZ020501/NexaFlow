import type { TFunction, TranslationKey } from "@/i18n"
import type { IntegrationProvider } from "@/lib/api/integrations"

export const integrationCatalog = [
  {
    provider: "dida",
    name: "滴答清单",
    description: "查询清单和待办，创建任务并标记完成。",
    documentation: "https://developer.dida365.com/manage",
  },
  {
    provider: "feishu",
    name: "飞书",
    description: "读取已授权的云文档，以你的身份发送消息。",
    documentation: "https://open.feishu.cn/app",
  },
  {
    provider: "tencent_meeting",
    name: "腾讯会议",
    description:
      "管理会议、受邀成员和录制，读取纪要、转写及参会报告，查询通讯录并执行会中控制。",
    documentation: "https://meeting.tencent.com/ai-tab/ai-cli/",
  },
] as const satisfies readonly {
  provider: IntegrationProvider
  name: TranslationKey
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
  dida_list_projects: "查看滴答清单",
  dida_list_tasks: "读取滴答待办",
  dida_create_task: "创建滴答任务",
  dida_complete_task: "完成滴答任务",
  feishu_read_document: "读取飞书文档",
  feishu_send_message: "发送飞书消息",
  tencent_meeting_list_meetings: "查看腾讯会议列表",
  tencent_meeting_get_meeting: "读取腾讯会议详情",
}

export function integrationToolName(functionName: string, t: TFunction) {
  const key = operationLabels[functionName.replace(/_[a-f0-9]{32}$/, "")]
  return key ? t(key) : null
}
