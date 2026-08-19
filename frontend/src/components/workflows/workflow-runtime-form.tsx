"use client"

import * as React from "react"
import { LoaderCircleIcon, SendIcon } from "lucide-react"

import { FilterDropdown } from "@/components/app/filter-dropdown"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import type { WorkflowPendingForm } from "@/lib/api/workflows"

export function WorkflowRuntimeForm({
  form,
  submitting,
  onSubmit,
}: {
  form: WorkflowPendingForm
  submitting: boolean
  onSubmit: (data: Record<string, unknown>) => Promise<void>
}) {
  const { t } = useLanguage()
  const [before, after = ""] = form.content.split(/{{\s*form\s*}}/, 2)
  const [values, setValues] = React.useState<Record<string, string>>(() =>
    Object.fromEntries(
      form.fields.map((field) => [
        field.variable,
        field.show_default_value ? String(field.default_value ?? "") : "",
      ])
    )
  )
  const updateValue = (variable: string, value: string) =>
    setValues((current) => ({ ...current, [variable]: value }))

  return (
    <section className="grid gap-3 rounded-lg border bg-muted/20 p-3">
      {before.trim() ? (
        <p className="text-sm leading-6 whitespace-pre-wrap">{before.trim()}</p>
      ) : null}
      <div className="grid gap-3">
        {form.fields.map((field) => {
          const defaultValue = field.show_default_value
            ? String(field.default_value ?? "")
            : ""
          return (
            <label
              key={field.variable}
              className="grid gap-1.5 text-sm font-medium"
            >
              <span>
                {field.name}
                {field.is_required ? (
                  <span className="ml-1 text-destructive" aria-hidden="true">
                    *
                  </span>
                ) : null}
              </span>
              {field.type === "textarea" ? (
                <textarea
                  name={field.variable}
                  required={field.is_required}
                  value={values[field.variable] ?? defaultValue}
                  onChange={(event) =>
                    updateValue(field.variable, event.target.value)
                  }
                  rows={3}
                  className="resize-y rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              ) : field.type === "select" ? (
                <FilterDropdown
                  ariaLabel={field.name}
                  className="h-9 px-3"
                  modal={false}
                  value={values[field.variable] ?? defaultValue}
                  options={[
                    { value: "", label: t("请选择") },
                    ...field.optionList.map((option) => ({
                      value: option,
                      label: option,
                    })),
                  ]}
                  onChange={(value) =>
                    updateValue(field.variable, value)
                  }
                />
              ) : (
                <Input
                  name={field.variable}
                  type={field.type === "input" ? "text" : field.type}
                  required={field.is_required}
                  value={values[field.variable] ?? defaultValue}
                  onChange={(event) =>
                    updateValue(field.variable, event.target.value)
                  }
                />
              )}
            </label>
          )
        })}
        <Button
          type="button"
          size="sm"
          disabled={
            submitting ||
            form.fields.some(
              (field) => field.is_required && !(values[field.variable] ?? "").trim()
            )
          }
          onClick={() => void onSubmit(values)}
        >
          {submitting ? (
            <LoaderCircleIcon className="animate-spin" />
          ) : (
            <SendIcon />
          )}
          {t("提交表单")}
        </Button>
      </div>
      {after.trim() ? (
        <p className="text-sm leading-6 whitespace-pre-wrap">{after.trim()}</p>
      ) : null}
    </section>
  )
}
