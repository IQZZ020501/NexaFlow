/* @jsxImportSource react */
import { afterEach, describe, expect, spyOn, test } from "bun:test"

import { AuditPanel } from "@/components/system/panels/audit-panel"
import type { AuditLog } from "@/lib/api/system"
import { cleanup, fireEvent, renderPage, resetFetch, screen, waitFor, within } from "./helpers/dom"

afterEach(() => {
  cleanup()
  resetFetch()
})

let capturedBlob: Blob | null = null

function auditLog(overrides: Partial<AuditLog> = {}): AuditLog {
  return {
    id: "audit-1",
    actor_user_id: "user-1",
    actor_username: "admin",
    actor_name: "Admin",
    workspace_id: "workspace-1",
    action: "workspace.create",
    resource_type: "workspace",
    resource_id: "workspace-2",
    resource_name: 'Workspace "2"',
    details: {},
    created_at: "2026-08-19T00:00:00Z",
    ...overrides,
  }
}

const panelProps = {
  isAuditLoading: false,
  locale: "en-US",
}

describe("AuditPanel", () => {
  test("shows a loading spinner and disables the refresh button while loading", () => {
    const { container } = renderPage(
      <AuditPanel
        auditLogs={[]}
        isAuditLoading
        locale="en-US"
      />
    )

    expect(container.querySelector("svg.animate-spin")).toBeTruthy()
    expect(screen.getByRole("button", { name: "刷新" })).toHaveProperty(
      "disabled",
      true
    )
    expect(screen.queryByRole("table")).toBeNull()
  })

  test("shows the empty state and disables export when there are no logs", () => {
    renderPage(<AuditPanel auditLogs={[]} {...panelProps} />)

    expect(screen.getByText("暂无审计日志")).toBeTruthy()
    expect(screen.getByRole("button", { name: "导出" })).toHaveProperty(
      "disabled",
      true
    )
  })

  test("renders the workspace scope header when provided", () => {
    renderPage(
      <AuditPanel
        auditLogs={[auditLog()]}
        workspaceScope="Finance"
        {...panelProps}
      />
    )

    expect(screen.getByText("工作空间范围: Finance")).toBeTruthy()
  })

  test("omits the workspace scope header when absent", () => {
    renderPage(<AuditPanel auditLogs={[auditLog()]} {...panelProps} />)

    expect(screen.queryByText(/工作空间范围/)).toBeNull()
  })

  test("renders log rows with headers, details, and alternating styling", () => {
    renderPage(
      <AuditPanel
        auditLogs={[
          auditLog(),
          auditLog({
            id: "audit-2",
            actor_username: "bob",
            actor_name: "Bob",
            action: "workspace.update",
            resource_name: "Workspace 3",
            details: { is_active: true },
          }),
        ]}
        {...panelProps}
      />
    )

    for (const header of ["时间", "操作者", "动作", "对象", "详情"]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeTruthy()
    }
    const rows = screen.getAllByRole("row")
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText("Admin")).toBeTruthy()
    expect(within(rows[0]).getByText("新建工作空间")).toBeTruthy()
    expect(within(rows[0]).getByText('Workspace "2"')).toBeTruthy()
    expect(within(rows[0]).getByText("-")).toBeTruthy()
    expect(within(rows[1]).getByText("Bob")).toBeTruthy()
    expect(within(rows[1]).getByText("更新工作空间")).toBeTruthy()
    // Formatted audit details render localized labels.
    expect(within(rows[1]).getByText("启用状态: 是")).toBeTruthy()
    // Odd rows get the muted background.
    expect(rows[1].className).toContain("bg-muted/20")
    expect(rows[0].className).not.toContain("bg-muted/20")
  })

  test("reports search input changes", () => {
    const searches: string[] = []
    renderPage(
      <AuditPanel
        auditLogs={[auditLog()]}
        setAuditSearch={(value) => {
          searches.push(value)
        }}
        {...panelProps}
      />
    )

    fireEvent.change(screen.getByRole("textbox", { name: "搜索审计" }), {
      target: { value: "workspace" },
    })
    expect(searches).toEqual(["workspace"])
  })

  test("reports action filter selections with deduplicated options", async () => {
    const actions: string[] = []
    renderPage(
      <AuditPanel
        auditLogs={[
          auditLog(),
          auditLog({ id: "audit-2", action: "workspace.update" }),
          auditLog({ id: "audit-3", action: "workspace.create" }),
        ]}
        setAuditAction={(value) => {
          actions.push(value)
        }}
        {...panelProps}
      />
    )

    fireEvent.pointerDown(screen.getByRole("button", { name: "筛选动作" }))
    const menu = await screen.findByRole("menu")
    // "全部动作" plus one entry per distinct action.
    expect(within(menu).getByText("全部动作")).toBeTruthy()
    expect(within(menu).getByText("新建工作空间")).toBeTruthy()
    expect(within(menu).getByText("更新工作空间")).toBeTruthy()
    fireEvent.click(within(menu).getByText("更新工作空间"))
    await waitFor(() => expect(actions).toEqual(["workspace.update"]))
  })

  test("calls onRefresh from the refresh button", () => {
    let refreshes = 0
    renderPage(
      <AuditPanel
        auditLogs={[auditLog()]}
        onRefresh={() => {
          refreshes += 1
        }}
        {...panelProps}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "刷新" }))
    expect(refreshes).toBe(1)
  })

  test("shows pagination and reports page-size changes", async () => {
    let selectedSize = 0
    renderPage(
      <AuditPanel
        auditLogs={[auditLog()]}
        hasMore
        total={61}
        onPageSizeChange={(value) => {
          selectedSize = value
        }}
        {...panelProps}
      />
    )

    expect(screen.getByRole("button", { name: "下一页" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "1" }).getAttribute("aria-current")).toBe("page")
    expect(screen.getByRole("button", { name: "2" })).toBeTruthy()
    fireEvent.pointerDown(screen.getByRole("button", { name: "每页 20 条" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "每页 50 条" }))
    expect(selectedSize).toBe(50)
  })

  test("exports audit logs as a CSV file", async () => {
    const createObjectURL = spyOn(URL, "createObjectURL").mockImplementation(
      (blob: Blob) => {
        capturedBlob = blob
        return "blob:nexaflow-test"
      }
    )
    const revokeObjectURL = spyOn(URL, "revokeObjectURL")
    const click = spyOn(HTMLAnchorElement.prototype, "click")

    renderPage(
      <AuditPanel
        auditLogs={[
          auditLog(),
          auditLog({ id: "audit-2", actor_username: "bob", actor_name: "Bob" }),
        ]}
        {...panelProps}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "导出" }))

    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(capturedBlob).toBeInstanceOf(Blob)
    expect(click).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:nexaflow-test")

    const csv = await capturedBlob!.text()
    expect(csv).toContain('"时间","操作者","动作","对象","详情"')
    expect(csv).toContain('"admin"')
    expect(csv).toContain('"新建工作空间"')
    // Embedded quotes are doubled per CSV escaping.
    expect(csv).toContain('"Workspace ""2"""')
    // One row per log.
    expect(csv.split("\n")).toHaveLength(3)

    createObjectURL.mockRestore()
    revokeObjectURL.mockRestore()
    click.mockRestore()
  })

  test("uses no-op defaults for optional handlers", async () => {
    renderPage(<AuditPanel auditLogs={[auditLog()]} {...panelProps} />)

    // Default setAuditSearch, setAuditAction, onRefresh, and
    // hasMore must not throw when exercised.
    fireEvent.change(screen.getByRole("textbox", { name: "搜索审计" }), {
      target: { value: "x" },
    })
    fireEvent.pointerDown(screen.getByRole("button", { name: "筛选动作" }))
    const menu = await screen.findByRole("menu")
    fireEvent.click(within(menu).getByText("全部动作"))
    fireEvent.click(screen.getByRole("button", { name: "刷新" }))
    fireEvent.click(screen.getByRole("button", { name: "导出" }))
  })
})

test("exports every log returned by loadAll instead of only the current page", async () => {
  const createObjectURL = spyOn(URL, "createObjectURL").mockImplementation(
    (blob: Blob) => {
      capturedBlob = blob
      return "blob:nexaflow-test"
    }
  )
  const click = spyOn(HTMLAnchorElement.prototype, "click")

  renderPage(
    <AuditPanel
      auditLogs={[auditLog()]}
      loadAll={async () => [
        auditLog(),
        auditLog({ id: "audit-all-2", actor_username: "alice" }),
      ]}
      {...panelProps}
    />
  )

  fireEvent.click(screen.getByRole("button", { name: "导出" }))

  await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1))
  const csv = await capturedBlob!.text()
  // Header plus both loadAll rows (not the single page row).
  expect(csv.split("\n")).toHaveLength(3)
  expect(csv).toContain('"alice"')
  expect(click).toHaveBeenCalledTimes(1)
  createObjectURL.mockRestore()
  click.mockRestore()
})
