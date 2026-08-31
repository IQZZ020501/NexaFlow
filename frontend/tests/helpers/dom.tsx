/* @jsxImportSource react */
/**
 * Shared helpers for DOM-level (happy-dom + Testing Library) page tests.
 *
 * All page tests should:
 * 1. Call `mockNextNavigation(...)` / `mockUseSession(...)` before rendering
 *    (bun hoists `mock.module` calls, so placement within the file is safe).
 * 2. Use `renderPage(...)` to wrap in the real `LanguageProvider`.
 * 3. Stub `globalThis.fetch` with `withFetch(...)` (or `jsonResponse`).
 */
import { mock } from "bun:test"
import { render } from "@testing-library/react"
import type { ReactElement } from "react"

import { LanguageProvider } from "@/contexts/language-provider"
import type { MeResponse, User } from "@/lib/api/auth"
import type { Team, Workspace } from "@/lib/api/system"

export { cleanup, render } from "@testing-library/react"
export { fireEvent, screen, waitFor, within } from "@testing-library/react"

export function makeSession(overrides: Record<string, unknown> = {}) {
  const workspace: Workspace = {
    id: "ws-1",
    name: "Test Workspace",
    description: "",
    status: "active",
    is_default: false,
  }
  const user: User = {
    id: "u-1",
    username: "admin",
    email: "admin@app.local",
    name: "NexaFlow Admin",
    is_global_admin: true,
    must_change_password: false,
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    workspaces: [
      { id: "ws-1", name: "Test Workspace", is_default: false, role: "admin" },
    ],
    teams: [],
  }
  const me: MeResponse = {
    user,
    memberships: [{ workspace_id: "ws-1", role: "admin" }],
  }
  return {
    token: "test-token",
    me,
    workspaces: [workspace],
    teams: [] as Team[],
    selectedWorkspaceId: "ws-1",
    mustChangePassword: false,
    isSessionLoading: false,
    isSessionRestored: true,
    isTeamsLoading: false,
    sessionError: null,
    notification: null,
    currentWorkspace: workspace,
    workspaceOptions: [workspace],
    passwordDialogOpen: false,
    login: () => undefined,
    logout: () => undefined,
    notify: () => undefined,
    dismissNotification: () => undefined,
    openPasswordDialog: () => undefined,
    closePasswordDialog: () => undefined,
    selectWorkspace: () => undefined,
    switchWorkspace: () => undefined,
    clearSelectedWorkspace: () => undefined,
    workspaceCreated: () => undefined,
    workspaceUpdated: () => undefined,
    workspaceDeleted: () => undefined,
    teamCreated: () => undefined,
    teamUpdated: () => undefined,
    teamDeleted: () => undefined,
    userUpdated: () => undefined,
    passwordChanged: async () => undefined,
    ...overrides,
  }
}

export function mockUseSession(session = makeSession()) {
  mock.module("@/contexts/session-context", () => ({
    useSession: () => session,
    useCurrentWorkspaceName: () => "Test Workspace",
    replaceSessionUser: () => undefined,
    addCreatedWorkspaceMembership: () => undefined,
    addCreatedTeamMembership: () => undefined,
    getInitialWorkspaceId: () => "ws-1",
    SessionProvider: ({ children }: { children: React.ReactNode }) => children,
  }))
}

/**
 * Mocks Next.js navigation hooks with configurable route state and navigation callbacks.
 *
 * @param options - Navigation parameters, pathname, search string, and optional `push` and `replace` callbacks.
 */
export function mockNextNavigation(options: {
  params?: Record<string, string>
  search?: string
  pathname?: string
  push?: (href: string) => void
  replace?: (href: string) => void
} = {}) {
  const push = options.push ?? (() => undefined)
  const replace = options.replace ?? (() => undefined)
  mock.module("next/navigation", () => ({
    useParams: () => options.params ?? {},
    useRouter: () => ({
      push,
      replace,
      back: () => undefined,
      forward: () => undefined,
      prefetch: () => undefined,
      refresh: () => undefined,
    }),
    useSearchParams: () => new URLSearchParams(options.search ?? ""),
    usePathname: () => options.pathname ?? "/",
  }))
}

/**
 * Mocks `next/image` with a native `<img>` test stub.
 */
export function mockNextImage() {
  /* eslint-disable @next/next/no-img-element -- test stub for next/image */
  mock.module("next/image", () => ({
    default: ({ priority, ...props }: Record<string, unknown>) => (
      <img
        {...(props as object)}
        alt={(props.alt as string) ?? ""}
        data-priority={priority ? "true" : undefined}
      />
    ),
  }))
  /* eslint-enable @next/next/no-img-element */
}

/**
 * Mocks `next/link` with an anchor element for tests.
 */
export function mockNextLink() {
  mock.module("next/link", () => ({
    default: ({
      children,
      ...props
    }: Record<string, unknown> & { children?: React.ReactNode }) => (
      <a href={(props.href as string) ?? "#"} {...props}>
        {children}
      </a>
    ),
  }))
}

export function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

export type FetchHandler = (
  url: string,
  init?: RequestInit
) => Response | Promise<Response>

/** Install a fetch stub for the current test file (stays installed until
 *  `resetFetch` or `setFetch` is called; `setFetch` swaps the handler). */
export function withFetch(handler: FetchHandler) {
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
    return Promise.resolve(handler(url, init))
  }) as typeof fetch
}

export function setFetch(handler: FetchHandler) {
  withFetch(handler)
}

export function resetFetch() {
  delete (globalThis as { fetch?: unknown }).fetch
}

export function renderPage(ui: ReactElement) {
  return render(<LanguageProvider defaultLanguage="zh-Hans">{ui}</LanguageProvider>)
}
