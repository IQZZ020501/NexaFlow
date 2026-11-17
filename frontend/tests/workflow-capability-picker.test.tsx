/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { useState } from "react"
import { WorkflowCapabilityPicker } from "@/components/workflows/workflow-capability-picker"
import { translate } from "@/i18n"
import type { AgentSkill, AgentSkillRef } from "@/lib/api/agent-skills"
import type { ToolDetail, ToolRef } from "@/lib/api/tools"
import { cleanup, fireEvent, renderPage, screen, within } from "./helpers/dom"

const tools = (["search", "lyrics", "denied"] as const).map(
  (id): ToolDetail =>
    ({
      id,
      kind: "mcp",
      function_name: id,
      display_name: id,
      source: { id: "music", name: "音乐", kind: "mcp", transport: null },
      current_version_id: `${id}-v2`,
      status: "active",
      availability: "available",
      approval: "each_call",
      workflow_callable: true,
      can_use: id !== "denied",
      can_view: true,
    }) as ToolDetail
)

const skill: AgentSkill = {
  id: "skill",
  name: "表格计算",
  description: "运行表格脚本",
  status: "active",
  can_use: true,
  current_published_version_id: "skill-v2",
} as AgentSkill

function Harness({
  initial = { tools: [], skills: [] },
  readOnly = false,
}: {
  initial?: { tools: ToolRef[]; skills: AgentSkillRef[] }
  readOnly?: boolean
}) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <WorkflowCapabilityPicker
        tools={tools}
        skills={[
          skill,
          {
            ...skill,
            id: "draft",
            name: "未发布脚本",
            current_published_version_id: null,
          },
          { ...skill, id: "view-only", name: "仅查看脚本", can_use: false },
        ]}
        value={value}
        readOnly={readOnly}
        onChange={setValue}
        t={(key, params) => translate("zh-Hans", key, params)}
      />
      <output data-testid="selection">{JSON.stringify(value)}</output>
    </>
  )
}

afterEach(cleanup)

describe("Workflow capability picker", () => {
  test("opens from the plus button, groups MCP operations, and binds published scripts", () => {
    renderPage(<Harness />)
    expect(screen.queryByRole("checkbox")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "添加工具和 Skills" }))
    const dialog = screen.getByRole("dialog")
    expect(
      within(dialog).getAllByRole("checkbox", { name: "音乐" })
    ).toHaveLength(1)
    expect(within(dialog).queryByText("search")).toBeNull()
    expect(within(dialog).getByText("需要逐次审批")).toBeTruthy()
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "音乐" }))
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "表格计算" }))
    expect(JSON.parse(screen.getByTestId("selection").textContent!)).toEqual({
      tools: [
        { tool_id: "search", version_id: "search-v2" },
        { tool_id: "lyrics", version_id: "lyrics-v2" },
      ],
      skills: [{ skill_id: "skill", version_id: "skill-v2" }],
    })
    expect(
      (
        within(dialog).getByRole("checkbox", {
          name: "未发布脚本",
        }) as HTMLInputElement
      ).disabled
    ).toBe(true)
    expect(
      (
        within(dialog).getByRole("checkbox", {
          name: "仅查看脚本",
        }) as HTMLInputElement
      ).disabled
    ).toBe(true)
    fireEvent.click(within(dialog).getByRole("button", { name: "完成" }))
    expect(screen.queryByRole("dialog")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "移除 表格计算" }))
    fireEvent.click(screen.getByRole("button", { name: "移除 音乐" }))
    expect(JSON.parse(screen.getByTestId("selection").textContent!)).toEqual({
      tools: [],
      skills: [],
    })
  })

  test("preserves existing tool and Skill pins when adding a service operation", () => {
    renderPage(
      <Harness
        initial={{
          tools: [{ tool_id: "search", version_id: "search-v1" }],
          skills: [{ skill_id: "skill", version_id: "skill-v1" }],
        }}
      />
    )
    fireEvent.click(screen.getByRole("button", { name: "添加工具和 Skills" }))
    fireEvent.click(screen.getByRole("checkbox", { name: "音乐" }))
    expect(JSON.parse(screen.getByTestId("selection").textContent!)).toEqual({
      tools: [
        { tool_id: "search", version_id: "search-v1" },
        { tool_id: "lyrics", version_id: "lyrics-v2" },
      ],
      skills: [{ skill_id: "skill", version_id: "skill-v1" }],
    })
    fireEvent.change(
      screen.getByRole("textbox", { name: "搜索工具或 Skills" }),
      { target: { value: "表格" } }
    )
    expect(screen.queryByRole("checkbox", { name: "音乐" })).toBeNull()
    expect(screen.getByRole("checkbox", { name: "表格计算" })).toBeTruthy()
  })

  test("keeps partial service selections removable at the tool limit", () => {
    const others = Array.from({ length: 19 }, (_, index) => ({
      tool_id: `other-${index}`,
      version_id: "v1",
    }))
    renderPage(
      <Harness
        initial={{
          tools: [{ tool_id: "search", version_id: "search-v1" }, ...others],
          skills: [],
        }}
      />
    )
    fireEvent.click(screen.getByRole("button", { name: "添加工具和 Skills" }))
    const dialog = screen.getByRole("dialog")
    expect(
      (
        within(dialog).getByRole("checkbox", {
          name: "音乐",
        }) as HTMLInputElement
      ).disabled
    ).toBe(true)
    fireEvent.click(within(dialog).getByRole("button", { name: "移除 音乐" }))
    expect(
      JSON.parse(screen.getByTestId("selection").textContent!).tools
    ).toEqual(others)
  })

  test("disables edits for a read-only Workflow", () => {
    renderPage(
      <Harness
        readOnly
        initial={{
          tools: [{ tool_id: "search", version_id: "search-v1" }],
          skills: [{ skill_id: "skill", version_id: "skill-v1" }],
        }}
      />
    )
    for (const name of ["添加工具和 Skills", "移除 音乐", "移除 表格计算"])
      expect(
        (screen.getByRole("button", { name }) as HTMLButtonElement).disabled
      ).toBe(true)
  })
})
