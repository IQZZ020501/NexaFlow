import { describe, expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import { join } from "node:path"

const readSource = (path: string) =>
  readFileSync(join(import.meta.dir, path), "utf8")

describe("App Router scroll candidates", () => {
  test("renders normal route content before fixed progress indicators", () => {
    const providersSource = readSource("../contexts/app-providers.tsx")
    expect(providersSource.indexOf("{children}")).toBeLessThan(
      providersSource.indexOf("<TopProgress />")
    )

    const sessionGateSource = readSource("../components/app/session-gate.tsx")
    const loadingBranch = sessionGateSource.slice(
      sessionGateSource.indexOf("if (!isSessionRestored")
    )
    expect(loadingBranch.indexOf('<main className="min-h-svh')).toBeLessThan(
      loadingBranch.indexOf("<TopLoadingBar")
    )

    const agentsPageSource = readSource("../components/agents/agents-page.tsx")
    expect(
      agentsPageSource.indexOf('<div className="flex flex-col gap-4')
    ).toBeLessThan(agentsPageSource.indexOf("<TopLoadingBar"))
  })
})
