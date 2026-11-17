/* @jsxImportSource react */
import { afterEach, expect, test } from "bun:test"
import { ProjectsPage } from "@/components/projects/projects-page"
import { ProjectSelector } from "@/components/projects/project-selector"
import { uploadProjectFile } from "@/lib/api/projects"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  resetFetch,
  screen,
  waitFor,
  withFetch,
} from "./helpers/dom"

mockNextNavigation()
mockUseSession()
afterEach(() => {
  cleanup()
  resetFetch()
})
const project = { id: "project-1", name: "Quarterly report", revision: 3 }
const file = {
  id: "version-1",
  project_id: project.id,
  path: "script.py",
  role: "work",
  revision: 3,
  deleted: false,
  size_bytes: 12,
  content_hash: "hash",
}

test("project overwrite sends its exact base version and private bearer", async () => {
  let captured: RequestInit | undefined
  withFetch((_url, init) => {
    captured = init
    return jsonResponse(file)
  })
  await uploadProjectFile(
    "private-token",
    "ws-1",
    project.id,
    file.path,
    "work",
    new File(["print(2)"], "script.py"),
    file.id
  )
  expect(new Headers(captured?.headers).get("Authorization")).toBe(
    "Bearer private-token"
  )
  expect((captured?.body as FormData).get("expected_version_id")).toBe(
    "version-1"
  )
})

test("new conversation selects a project while a bound conversation stays fixed", async () => {
  const selected: Array<string | null> = []
  withFetch(() => jsonResponse([project]))
  const view = renderPage(
    <ProjectSelector
      token="test-token"
      workspaceId="ws-1"
      disabled={false}
      onChange={(id) => {
        selected.push(id)
      }}
    />
  )
  await screen.findByRole("option", { name: project.name })
  fireEvent.change(screen.getByRole("combobox", { name: "选择项目" }), {
    target: { value: project.id },
  })
  expect(selected).toEqual([project.id])
  view.unmount()
  renderPage(
    <ProjectSelector
      token="test-token"
      workspaceId="ws-1"
      value={project.id}
      boundName={project.name}
      disabled
      onChange={() => {
        throw new Error("Bound project changed")
      }}
    />
  )
  expect(screen.queryByRole("combobox")).toBeNull()
  expect(screen.getByRole("link").getAttribute("href")).toBe(
    `/app/projects/${project.id}`
  )
})

test("project upload reports a conflict and retains the selected file", async () => {
  withFetch((url, init) => {
    if (init?.method === "POST" && url.endsWith("/files"))
      return jsonResponse({ detail: "Changed" }, 409)
    if (url.endsWith("/files")) return jsonResponse([file])
    return jsonResponse(project)
  })
  renderPage(<ProjectsPage projectId={project.id} />)
  await waitFor(() => expect(screen.getByText(file.path)).toBeTruthy(), {
    timeout: 1000,
  })
  const input = screen.getByLabelText("上传项目文件") as HTMLInputElement
  const upload = new File(["print(2)"], "script.py")
  fireEvent.change(input, { target: { files: [upload] } })
  fireEvent.submit(
    screen.getByRole("button", { name: "保存文件版本" }).closest("form")!
  )
  await waitFor(
    () =>
      expect(screen.getByRole("alert").textContent).toContain("项目版本冲突"),
    { timeout: 1000 }
  )
  expect(
    (screen.getByLabelText("项目相对路径") as HTMLInputElement).value
  ).toBe(file.path)
  expect(input.files?.[0]).toBe(upload)
})
