"use client"

import * as React from "react"
import {
  BrainCircuitIcon,
  NetworkIcon,
  PlusIcon,
  WrenchIcon,
  XIcon,
} from "lucide-react"

import type { TFunction } from "@/i18n"
import type { AgentSkill, AgentSkillRef } from "@/lib/api/agent-skills"
import type { ToolDetail, ToolRef } from "@/lib/api/tools"
import {
  groupTools,
  selectToolGroup,
  toolBindingGroups,
  toolGroupName,
  workflowToolDisabledReason,
} from "@/lib/tool-groups"
import { isRegularTool } from "@/lib/tool-visibility"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"

type Selection = { tools: ToolRef[]; skills: AgentSkillRef[] }

export function WorkflowCapabilityPicker({
  tools,
  skills,
  value,
  readOnly,
  onChange,
  t,
}: {
  tools: ToolDetail[]
  skills: AgentSkill[]
  value: Selection
  readOnly: boolean
  onChange: (value: Selection) => void
  t: TFunction
}) {
  const [open, setOpen] = React.useState(false)
  const [search, setSearch] = React.useState("")
  const [category, setCategory] = React.useState<"all" | "mcp" | "skills">(
    "all"
  )
  const catalog = tools.filter(
    (tool) =>
      isRegularTool(tool.function_name) &&
      !["run_skill_script", "inline_python", "create_artifact"].includes(
        tool.function_name
      )
  )
  const groups = groupTools(catalog)
  const selectedGroups = toolBindingGroups(value.tools, tools, t)
  const query = search.trim().toLocaleLowerCase()
  const visibleGroups = groups.filter(
    (group) =>
      (category !== "mcp" || group.tools[0].kind === "mcp") &&
      category !== "skills" &&
      toolGroupName(group, t).toLocaleLowerCase().includes(query)
  )
  const visibleSkills = skills.filter(
    (skill) =>
      category !== "mcp" &&
      `${skill.name} ${skill.description}`.toLocaleLowerCase().includes(query)
  )

  function removeTools(references: ToolRef[]) {
    const ids = new Set(references.map((item) => item.tool_id))
    onChange({
      ...value,
      tools: value.tools.filter((item) => !ids.has(item.tool_id)),
    })
  }

  return (
    <fieldset className="grid gap-1.5 text-xs font-medium">
      <legend className="float-left mb-1.5 flex w-full items-center justify-between gap-2">
        <span>{t("工具")}</span>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="size-6"
          aria-label={t("添加工具和 Skills")}
          disabled={readOnly}
          onClick={() => {
            setSearch("")
            setCategory("all")
            setOpen(true)
          }}
        >
          <PlusIcon className="size-3.5" />
        </Button>
      </legend>
      <div className="clear-both grid gap-1.5">
        {selectedGroups.map((group) => {
          const source = tools.find(
            (tool) => tool.id === group.references[0].tool_id
          )
          const Icon = source?.kind === "mcp" ? NetworkIcon : WrenchIcon
          const unavailable = group.references.some((ref) => {
            const tool = tools.find((item) => item.id === ref.tool_id)
            return !tool || Boolean(workflowToolDisabledReason(tool))
          })
          return (
            <div
              key={group.id}
              className="flex min-w-0 items-center gap-2 rounded-md border px-2 py-1.5 font-normal"
            >
              <Icon className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">{group.name}</span>
              {unavailable ? (
                <span className="text-muted-foreground">{t("不可用")}</span>
              ) : null}
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="size-5 shrink-0"
                aria-label={t("移除 {name}", { name: group.name })}
                disabled={readOnly}
                onClick={() => removeTools(group.references)}
              >
                <XIcon className="size-3" />
              </Button>
            </div>
          )
        })}
        {value.skills.map((reference) => {
          const skill = skills.find((item) => item.id === reference.skill_id)
          const name = skill?.name ?? reference.skill_id
          return (
            <div
              key={reference.skill_id}
              className="flex min-w-0 items-center gap-2 rounded-md border px-2 py-1.5 font-normal"
            >
              <BrainCircuitIcon className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">{name}</span>
              {!skill?.can_use || skill.status !== "active" ? (
                <span className="text-muted-foreground">{t("不可用")}</span>
              ) : null}
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="size-5 shrink-0"
                aria-label={t("移除 {name}", { name })}
                disabled={readOnly}
                onClick={() =>
                  onChange({
                    ...value,
                    skills: value.skills.filter(
                      (item) => item.skill_id !== reference.skill_id
                    ),
                  })
                }
              >
                <XIcon className="size-3" />
              </Button>
            </div>
          )
        })}
        {!value.tools.length && !value.skills.length ? (
          <p className="py-1 font-normal text-muted-foreground">
            {t("添加 MCP 工具或 Skills")}
          </p>
        ) : null}
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          className="flex max-h-[min(80dvh,44rem)] flex-col gap-4 overflow-hidden sm:max-w-lg"
          onWheel={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <DialogHeader>
            <DialogTitle>{t("添加工具和 Skills")}</DialogTitle>
            <DialogDescription>
              {t(
                "按 MCP 服务添加工具，或选择已发布的 Skill；需要审批的调用会暂停等待确认。"
              )}
            </DialogDescription>
          </DialogHeader>
          <Input
            aria-label={t("搜索工具或 Skills")}
            placeholder={t("搜索工具或 Skills")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <div className="flex gap-1" role="group" aria-label={t("类型")}>
            {(
              [
                ["all", "全部工具"],
                ["mcp", "MCP 工具"],
                ["skills", "Skills"],
              ] as const
            ).map(([key, label]) => (
              <Button
                key={key}
                type="button"
                variant={category === key ? "secondary" : "ghost"}
                size="sm"
                aria-pressed={category === key}
                onClick={() => setCategory(key)}
              >
                {t(label)}
              </Button>
            ))}
          </div>
          <div className="grid min-h-0 gap-2 overflow-y-auto overscroll-contain pr-1">
            {visibleGroups.map((group) => {
              const name = toolGroupName(group, t)
              const eligible = group.tools.filter(
                (tool) => !workflowToolDisabledReason(tool)
              )
              const selected = group.tools.filter((tool) =>
                value.tools.some((item) => item.tool_id === tool.id)
              )
              const checked =
                eligible.length > 0 &&
                eligible.every((tool) =>
                  value.tools.some((item) => item.tool_id === tool.id)
                )
              const missing = eligible.filter(
                (tool) => !value.tools.some((item) => item.tool_id === tool.id)
              ).length
              const limit = value.tools.length + missing > 20
              const reason = !eligible.length
                ? workflowToolDisabledReason(group.tools[0])
                : limit && !checked
                  ? "选择此服务将超过 20 个工具上限"
                  : null
              const Icon =
                group.tools[0].kind === "mcp" ? NetworkIcon : WrenchIcon
              return (
                <div
                  key={group.id}
                  className="flex items-center gap-2 rounded-lg border px-3 py-2.5"
                >
                  <label className="flex min-w-0 flex-1 items-center gap-3">
                    <input
                      type="checkbox"
                      aria-label={name}
                      checked={checked}
                      ref={(input) => {
                        if (input)
                          input.indeterminate = !checked && selected.length > 0
                      }}
                      disabled={readOnly || Boolean(reason)}
                      onChange={(event) =>
                        onChange({
                          ...value,
                          tools: selectToolGroup(
                            value.tools,
                            eligible,
                            event.target.checked
                          ),
                        })
                      }
                    />
                    <Icon className="size-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {name}
                      </span>
                      {reason ? (
                        <span className="text-xs text-muted-foreground">
                          {t(reason)}
                        </span>
                      ) : eligible.some(
                          (tool) => tool.approval === "each_call"
                        ) ? (
                        <span className="text-xs text-muted-foreground">
                          {t("需要逐次审批")}
                        </span>
                      ) : null}
                    </span>
                  </label>
                  {selected.length > 0 && reason ? (
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      disabled={readOnly}
                      aria-label={t("移除 {name}", { name })}
                      onClick={() =>
                        removeTools(
                          group.tools.map((tool) => ({
                            tool_id: tool.id,
                            version_id: tool.current_version_id ?? "",
                          }))
                        )
                      }
                    >
                      <XIcon className="size-3.5" />
                    </Button>
                  ) : null}
                </div>
              )
            })}
            {visibleSkills.map((skill) => {
              const selected = value.skills.some(
                (item) => item.skill_id === skill.id
              )
              const unavailable =
                !skill.can_use ||
                skill.status !== "active" ||
                !skill.current_published_version_id
              const limit = !selected && value.skills.length >= 4
              return (
                <label
                  key={skill.id}
                  className="flex items-center gap-3 rounded-lg border px-3 py-2.5"
                >
                  <input
                    type="checkbox"
                    aria-label={skill.name}
                    checked={selected}
                    disabled={readOnly || (!selected && (unavailable || limit))}
                    onChange={() =>
                      onChange({
                        ...value,
                        skills: selected
                          ? value.skills.filter(
                              (item) => item.skill_id !== skill.id
                            )
                          : [
                              ...value.skills,
                              {
                                skill_id: skill.id,
                                version_id: skill.current_published_version_id!,
                              },
                            ],
                      })
                    }
                  />
                  <BrainCircuitIcon className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">
                      {skill.name}
                    </span>
                    <span className="line-clamp-2 text-xs text-muted-foreground">
                      {unavailable
                        ? t(
                            skill.current_published_version_id
                              ? "不可用"
                              : "未发布"
                          )
                        : limit
                          ? t("最多选择 4 个 Skills")
                          : skill.description}
                    </span>
                  </span>
                </label>
              )
            })}
            {!visibleGroups.length && !visibleSkills.length ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                {t("没有匹配的工具或 Skills")}
              </p>
            ) : null}
          </div>
          <DialogFooter>
            <Button type="button" onClick={() => setOpen(false)}>
              {t("完成")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </fieldset>
  )
}
