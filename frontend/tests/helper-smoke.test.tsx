/* @jsxImportSource react */
import { expect, test } from "bun:test"
import { fireEvent, screen } from "@testing-library/react"
import { useState } from "react"

import { useSession } from "@/contexts/session-context"
import { useLanguage } from "@/contexts/language-provider"

import { jsonResponse, makeSession, mockNextNavigation, mockUseSession, renderPage, withFetch } from "./helpers/dom"

mockUseSession(
  makeSession({
    me: {
      user: {
        id: "u-9",
        username: "tester",
        name: "Tester",
        email: "t@e.co",
        is_global_admin: false,
        must_change_password: false,
        is_active: true,
        created_at: "2026-01-01T00:00:00Z",
        workspaces: [],
        teams: [],
      },
      memberships: [],
    },
  })
)
mockNextNavigation({ pathname: "/app/apps" })
withFetch(() => jsonResponse({ items: [], total: 0 }))

function Probe() {
  const { me, notify } = useSession()
  const { t } = useLanguage()
  const [count, setCount] = useState(0)
  return (
    <div>
      <span>{me?.user.username}</span>
      <button
        type="button"
        onClick={() => {
          setCount((n) => n + 1)
          notify("success", "done")
        }}
      >
        {t("保存")} {count}
      </button>
    </div>
  )
}

test("helper pipeline: session mock + language + fetch + interaction", () => {
  renderPage(<Probe />)
  expect(screen.getByText("tester")).toBeTruthy()
  fireEvent.click(screen.getByRole("button"))
  expect(screen.getByText(/保存 1/)).toBeTruthy()
})
