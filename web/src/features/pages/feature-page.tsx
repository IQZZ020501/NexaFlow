import * as React from "react"
import { ChevronDownIcon, PlusIcon, SearchIcon } from "lucide-react"
import { useLanguage } from "@/components/language-provider"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { type MeResponse } from "@/features/auth/types"
import { type FeaturePageConfig } from "@/lib/pages"
import type { AppNotification } from "@/app/notifications"
import { KnowledgeBasePage } from "@/features/knowledge/knowledge-base-page"
import { LlmPage } from "@/features/llm/llm-page"

export function FeaturePage({
  page,
  token,
  me,
  selectedWorkspaceId,
  onNotify,
}: {
  page: FeaturePageConfig
  token: string
  me: MeResponse
  selectedWorkspaceId: string | null
  onNotify: (kind: AppNotification["kind"], message: string) => void
}) {
  const { t } = useLanguage()
  const Icon = page.icon
  const [isDialogOpen, setIsDialogOpen] = React.useState(false)

  if (page.key === "knowledge") {
    return (
      <KnowledgeBasePage
        page={page}
        token={token}
        me={me}
        selectedWorkspaceId={selectedWorkspaceId}
        onNotify={onNotify}
      />
    )
  }

  if (page.key === "models") {
    return (
      <LlmPage
        page={page}
        token={token}
        me={me}
        selectedWorkspaceId={selectedWorkspaceId}
        onNotify={onNotify}
      />
    )
  }

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold">{page.label}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {page.description}
          </p>
        </div>
        <Button
          type="button"
          className="shrink-0"
          onClick={() => setIsDialogOpen(true)}
        >
          <PlusIcon data-icon="inline-start" />
          {page.actionLabel}
        </Button>
      </div>

      <div className="rounded-lg border bg-background p-3 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative min-w-0 sm:w-[320px]">
            <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder={t("搜索{label}...", { label: page.label })}
            />
          </div>
          <Button type="button" variant="outline" className="justify-between">
            {t("最近更新")}
            <ChevronDownIcon data-icon="inline-end" />
          </Button>
        </div>
      </div>

      <div className="rounded-lg border bg-background p-6 shadow-sm">
        <div className="mx-auto flex min-h-[320px] max-w-xl flex-col items-center justify-center gap-4 text-center">
          <span className="flex size-14 items-center justify-center rounded-lg bg-muted">
            <Icon className="size-5 text-muted-foreground" />
          </span>
          <div className="flex flex-col gap-2">
            <p className="text-base font-semibold">{page.emptyTitle}</p>
            <p className="text-sm leading-6 text-muted-foreground">
              {page.emptyDescription}
            </p>
          </div>
          <div className="flex flex-wrap justify-center gap-2">
            <Button type="button" onClick={() => setIsDialogOpen(true)}>
              <PlusIcon data-icon="inline-start" />
              {page.actionLabel}
            </Button>
            <Button type="button" variant="outline">
              {page.secondaryActionLabel}
            </Button>
          </div>
        </div>
      </div>

      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{page.actionLabel}</DialogTitle>
            <DialogDescription>{page.dialogDescription}</DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              setIsDialogOpen(false)
            }}
          >
            <FieldGroup>
              {page.dialogFields.map((field) => (
                <Field key={field.id}>
                  <FieldLabel htmlFor={field.id}>{field.label}</FieldLabel>
                  <Input
                    id={field.id}
                    type={field.type ?? "text"}
                    placeholder={field.placeholder}
                    required
                  />
                </Field>
              ))}
            </FieldGroup>
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsDialogOpen(false)}
              >
                {t("取消")}
              </Button>
              <Button type="submit">{page.actionLabel}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
