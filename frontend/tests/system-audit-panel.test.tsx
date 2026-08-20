/* @jsxImportSource react */
import { describe, expect, test } from "bun:test"

import { AuditPanel } from "@/components/system/panels/audit-panel"
import type { AuditLog } from "@/lib/api/system"
import { renderPage, screen } from "./helpers/dom"

const auditLog: AuditLog = {
  id: "audit-1",
  actor_user_id: "user-1",
  actor_username: "admin",
  actor_name: "Admin",
  workspace_id: "workspace-1",
  action: "workspace.create",
  resource_type: "workspace",
  resource_id: "workspace-2",
  resource_name: "Workspace 2",
  details: {},
  created_at: "2026-08-19T00:00:00Z",
}

describe("AuditPanel", () => {
  test("uses one focusable container for both table overflow directions", () => {
    renderPage(
      <AuditPanel auditLogs={[auditLog]} isAuditLoading={false} locale="en-US" />
    )

    const scrollRegion = screen.getByRole("region", { name: "审计日志" })
    expect(scrollRegion.getAttribute("tabindex")).toBe("0")
    expect(scrollRegion.className).toContain("overflow-auto")
    expect(scrollRegion.className).toContain("lg:flex-1")
    expect(screen.getByRole("table", { name: "审计日志" })).toBeTruthy()
  })
})
