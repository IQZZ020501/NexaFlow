import { request, requestPage } from "@/lib/api-client"

export type AnnouncementScope = "global" | "workspace"
export type AnnouncementSeverity = "info" | "warning" | "critical"
export type AnnouncementStatus = "draft" | "published" | "archived"

export type Announcement = {
  id: string
  scope_type: AnnouncementScope
  workspace_id: string | null
  title: string
  body: string
  severity: AnnouncementSeverity
  pinned: boolean
  status: AnnouncementStatus
  published_at: string | null
  expires_at: string | null
  created_by_user_id: string | null
  updated_by_user_id: string | null
  created_at: string
  updated_at: string
}

export type AnnouncementPayload = {
  title: string
  body: string
  severity: AnnouncementSeverity
  pinned: boolean
  expires_at?: string | null
}

export type AnnouncementUpdatePayload = Partial<AnnouncementPayload>

function endpoint(scope: AnnouncementScope, workspaceId: string | null) {
  if (scope === "global") return "/api/v1/admin/announcements"
  if (!workspaceId) throw new Error("Workspace is required for announcements.")
  return `/api/v1/workspaces/${workspaceId}/announcements`
}

export function listAnnouncements(
  token: string,
  scope: AnnouncementScope,
  workspaceId: string | null,
  options: { limit?: number; offset?: number } = {}
) {
  const query = new URLSearchParams({
    limit: String(options.limit ?? 20),
    offset: String(options.offset ?? 0),
  })
  return requestPage<Announcement>(
    `${endpoint(scope, workspaceId)}?${query.toString()}`,
    {
      token,
    }
  )
}

export function createAnnouncement(
  token: string,
  scope: AnnouncementScope,
  workspaceId: string | null,
  payload: AnnouncementPayload
) {
  return request<Announcement>(endpoint(scope, workspaceId), {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  })
}

export function updateAnnouncement(
  token: string,
  scope: AnnouncementScope,
  workspaceId: string | null,
  announcementId: string,
  payload: AnnouncementUpdatePayload
) {
  return request<Announcement>(
    `${endpoint(scope, workspaceId)}/${announcementId}`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify(payload),
    }
  )
}

export function publishAnnouncement(
  token: string,
  scope: AnnouncementScope,
  workspaceId: string | null,
  announcementId: string
) {
  return request<Announcement>(
    `${endpoint(scope, workspaceId)}/${announcementId}/publish`,
    { method: "POST", token }
  )
}

export function archiveAnnouncement(
  token: string,
  scope: AnnouncementScope,
  workspaceId: string | null,
  announcementId: string
) {
  return request<Announcement>(
    `${endpoint(scope, workspaceId)}/${announcementId}/archive`,
    { method: "POST", token }
  )
}
