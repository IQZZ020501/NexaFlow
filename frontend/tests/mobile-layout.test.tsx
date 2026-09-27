/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { act, renderHook } from "@testing-library/react"

import { AuditPanel } from "@/components/system/panels/audit-panel"
import { SystemLogList } from "@/components/system/system-log-list"
import type { AuditLog, SystemLog } from "@/lib/api/system"
import { PHONE_LIST_QUERY, useMediaQuery } from "@/lib/use-media-query"
import { renderPage, screen } from "./helpers/dom"

type ChangeListener = () => void

/**
 * Replaces `window.matchMedia` with a controllable stub.
 *
 * @param matches - Decides the answer per query string
 * @returns The registered listeners' flush function and the restore function
 */
function stubMatchMedia(matches: (query: string) => boolean) {
  const original = window.matchMedia
  const listeners = new Set<ChangeListener>()

  window.matchMedia = ((query: string) => ({
    matches: matches(query),
    media: query,
    onchange: null,
    addEventListener: (_type: string, listener: ChangeListener) => {
      listeners.add(listener)
    },
    removeEventListener: (_type: string, listener: ChangeListener) => {
      listeners.delete(listener)
    },
    addListener: (listener: ChangeListener) => {
      listeners.add(listener)
    },
    removeListener: (listener: ChangeListener) => {
      listeners.delete(listener)
    },
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia

  return {
    notify() {
      for (const listener of [...listeners]) {
        listener()
      }
    },
    restore() {
      window.matchMedia = original
    },
  }
}

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

function systemLog(id: string, createdAt: string): SystemLog {
  return {
    id,
    level: "info",
    event: "request.completed",
    message: id,
    path: null,
    method: null,
    status_code: 200,
    user_id: null,
    username: null,
    ip_address: null,
    details: {},
    stack_trace: null,
    created_at: createdAt,
  }
}

describe("useMediaQuery", () => {
  let stub: ReturnType<typeof stubMatchMedia> | null = null

  afterEach(() => {
    stub?.restore()
    stub = null
  })

  test("reports the query state and follows later changes", () => {
    let matches = false
    stub = stubMatchMedia(() => matches)

    const { result } = renderHook(() => useMediaQuery(PHONE_LIST_QUERY))
    expect(result.current).toBe(false)

    matches = true
    act(() => stub?.notify())
    expect(result.current).toBe(true)
  })

  test("reports false while the query does not match", () => {
    stub = stubMatchMedia(() => false)

    const { result } = renderHook(() => useMediaQuery(PHONE_LIST_QUERY))
    expect(result.current).toBe(false)
  })
})

describe("phone list layout", () => {
  let stub: ReturnType<typeof stubMatchMedia> | null = null

  afterEach(() => {
    stub?.restore()
    stub = null
  })

  test("renders the phone card list instead of the wide grid on phones", () => {
    stub = stubMatchMedia((query) => query === PHONE_LIST_QUERY)

    renderPage(
      <AuditPanel
        auditLogs={[auditLog]}
        isAuditLoading={false}
        locale="en-US"
      />
    )

    const cards = screen.getAllByRole("listitem")
    expect(cards).toHaveLength(1)
    expect(cards[0].textContent).toContain("Workspace 2")
  })

  test("omits the phone card list when the wide layout matches", () => {
    stub = stubMatchMedia(() => false)

    renderPage(
      <AuditPanel
        auditLogs={[auditLog]}
        isAuditLoading={false}
        locale="en-US"
      />
    )

    expect(screen.queryAllByRole("listitem")).toHaveLength(0)
    expect(screen.getByRole("table", { name: "审计日志" })).toBeTruthy()
  })

  test("groups system logs by the application-local date on phones", () => {
    stub = stubMatchMedia((query) => query === PHONE_LIST_QUERY)

    const { container } = renderPage(
      <SystemLogList
        logs={[
          systemLog("after-midnight", "2026-08-19T16:30:00Z"),
          systemLog("before-midnight", "2026-08-19T15:59:59Z"),
        ]}
      />
    )

    expect(
      Array.from(container.querySelectorAll("[data-system-log-date]")).map(
        (element) => element.getAttribute("datetime")
      )
    ).toEqual(["2026-08-20", "2026-08-19"])
    expect(screen.getAllByRole("listitem")).toHaveLength(2)
    expect(screen.getByText("00:30:00")).toBeTruthy()
    expect(screen.getByText("23:59:59")).toBeTruthy()
  })
})
