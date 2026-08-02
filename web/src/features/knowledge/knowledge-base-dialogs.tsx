import * as React from "react"
import {
  ChevronDownIcon,
  CircleCheckIcon,
  LoaderCircleIcon,
  Trash2Icon,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
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
import type { FeaturePageConfig } from "@/lib/pages"
import type { ResourcePermission } from "@/features/knowledge/types"
import type { WorkspaceMember } from "@/features/system/types"
import { cn } from "@/lib/utils"
import { PermissionBadge } from "@/features/knowledge/status-badges"
import type {
  KnowledgeBaseEditForm,
  KnowledgeBaseForm,
  KnowledgeBasePermissionForm,
} from "@/features/knowledge/types"
import { useLanguage } from "@/components/language-provider"

type KnowledgeBaseDialogsProps = {
  page: FeaturePageConfig
  form: KnowledgeBaseForm
  setForm: React.Dispatch<React.SetStateAction<KnowledgeBaseForm>>
  editForm: KnowledgeBaseEditForm | null
  setEditForm: React.Dispatch<
    React.SetStateAction<KnowledgeBaseEditForm | null>
  >
  permissionForm: KnowledgeBasePermissionForm | null
  setPermissionForm: React.Dispatch<
    React.SetStateAction<KnowledgeBasePermissionForm | null>
  >
  shareTargets: WorkspaceMember[]
  permissions: ResourcePermission[]
  isDialogOpen: boolean
  setIsDialogOpen: React.Dispatch<React.SetStateAction<boolean>>
  isSaving: boolean
  handleCreate: React.FormEventHandler<HTMLFormElement>
  handleUpdate: React.FormEventHandler<HTMLFormElement>
  handleGrantPermission: React.FormEventHandler<HTMLFormElement>
  handleRevokePermission: (userId: string) => void | Promise<void>
}

export function KnowledgeBaseDialogs({
  page,
  form,
  setForm,
  editForm,
  setEditForm,
  permissionForm,
  setPermissionForm,
  shareTargets,
  permissions,
  isDialogOpen,
  setIsDialogOpen,
  isSaving,
  handleCreate,
  handleUpdate,
  handleGrantPermission,
  handleRevokePermission,
}: KnowledgeBaseDialogsProps) {
  const { t } = useLanguage()
  const selectedPermissionTarget = permissionForm
    ? shareTargets.find((member) => member.user.id === permissionForm.userId)
    : null

  return (
    <>
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{page.actionLabel}</DialogTitle>
            <DialogDescription>{page.dialogDescription}</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreate}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="knowledge-base-name">
                  {t("知识库名称")}
                </FieldLabel>
                <Input
                  id="knowledge-base-name"
                  value={form.name}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      name: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="knowledge-base-description">
                  描述
                </FieldLabel>
                <textarea
                  id="knowledge-base-description"
                  className="min-h-24 w-full rounded-lg border bg-background px-3 py-2 text-sm"
                  value={form.description}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      description: event.target.value,
                    }))
                  }
                />
              </Field>
            </FieldGroup>
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsDialogOpen(false)}
              >
                {t("取消")}
              </Button>
              <Button type="submit" disabled={isSaving}>
                {isSaving ? (
                  <LoaderCircleIcon data-icon="inline-start" />
                ) : null}
                {page.actionLabel}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(editForm)} onOpenChange={() => setEditForm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>编辑知识库</DialogTitle>
            <DialogDescription>更新知识库名称和描述。</DialogDescription>
          </DialogHeader>
          {editForm ? (
            <form onSubmit={handleUpdate}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="knowledge-base-edit-name">
                    {t("知识库名称")}
                  </FieldLabel>
                  <Input
                    id="knowledge-base-edit-name"
                    value={editForm.name}
                    onChange={(event) =>
                      setEditForm((current) =>
                        current
                          ? { ...current, name: event.target.value }
                          : current
                      )
                    }
                    required
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="knowledge-base-edit-description">
                    描述
                  </FieldLabel>
                  <textarea
                    id="knowledge-base-edit-description"
                    className="min-h-24 w-full rounded-lg border bg-background px-3 py-2 text-sm"
                    value={editForm.description}
                    onChange={(event) =>
                      setEditForm((current) =>
                        current
                          ? {
                              ...current,
                              description: event.target.value,
                            }
                          : current
                      )
                    }
                  />
                </Field>
              </FieldGroup>
              <DialogFooter className="pt-5">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setEditForm(null)}
                >
                  {t("取消")}
                </Button>
                <Button type="submit" disabled={isSaving}>
                  {isSaving ? (
                    <LoaderCircleIcon data-icon="inline-start" />
                  ) : null}
                  {t("保存")}
                </Button>
              </DialogFooter>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(permissionForm)}
        onOpenChange={() => setPermissionForm(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>资源授权</DialogTitle>
            <DialogDescription>
              {permissionForm?.knowledgeBase.name ?? ""}
            </DialogDescription>
          </DialogHeader>
          {permissionForm ? (
            <>
              <form onSubmit={handleGrantPermission}>
                <FieldGroup>
                  <Field>
                    <FieldLabel htmlFor="knowledge-base-permission-user">
                      用户
                    </FieldLabel>
                    <DropdownMenu modal={false}>
                      <DropdownMenuTrigger asChild>
                        <Button
                          id="knowledge-base-permission-user"
                          type="button"
                          variant="outline"
                          className="h-10 w-full justify-between px-3 font-normal"
                          disabled={!shareTargets.length}
                        >
                          <span
                            className={cn(
                              "min-w-0 flex-1 truncate text-left",
                              !selectedPermissionTarget &&
                                "text-muted-foreground"
                            )}
                          >
                            {selectedPermissionTarget
                              ? `${selectedPermissionTarget.user.name} / ${selectedPermissionTarget.user.username}`
                              : "选择用户"}
                          </span>
                          <ChevronDownIcon data-icon="inline-end" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent
                        align="start"
                        className="w-(--radix-dropdown-menu-trigger-width)"
                      >
                        {shareTargets.map((member) => (
                          <DropdownMenuItem
                            key={member.user.id}
                            className="justify-between"
                            onSelect={() =>
                              setPermissionForm((current) =>
                                current
                                  ? { ...current, userId: member.user.id }
                                  : current
                              )
                            }
                          >
                            <span className="min-w-0 truncate">
                              {member.user.name} / {member.user.username}
                            </span>
                            {member.user.id === permissionForm.userId ? (
                              <CircleCheckIcon className="text-primary" />
                            ) : null}
                          </DropdownMenuItem>
                        ))}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="knowledge-base-permission">
                      权限
                    </FieldLabel>
                    <DropdownMenu modal={false}>
                      <DropdownMenuTrigger asChild>
                        <Button
                          id="knowledge-base-permission"
                          type="button"
                          variant="outline"
                          className="h-10 w-full justify-between px-3 font-normal"
                        >
                          {permissionForm.permission === "edit"
                            ? "可编辑"
                            : "可查看"}
                          <ChevronDownIcon data-icon="inline-end" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent
                        align="start"
                        className="w-(--radix-dropdown-menu-trigger-width)"
                      >
                        {[
                          { value: "view", label: "可查看" },
                          { value: "edit", label: "可编辑" },
                        ].map((option) => (
                          <DropdownMenuItem
                            key={option.value}
                            className="justify-between"
                            onSelect={() =>
                              setPermissionForm((current) =>
                                current
                                  ? {
                                      ...current,
                                      permission: option.value as
                                        "view" | "edit",
                                    }
                                  : current
                              )
                            }
                          >
                            {option.label}
                            {option.value === permissionForm.permission ? (
                              <CircleCheckIcon className="text-primary" />
                            ) : null}
                          </DropdownMenuItem>
                        ))}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </Field>
                </FieldGroup>
                <DialogFooter className="pt-5">
                  <Button
                    type="submit"
                    disabled={isSaving || !shareTargets.length}
                  >
                    {isSaving ? (
                      <LoaderCircleIcon data-icon="inline-start" />
                    ) : null}
                    保存授权
                  </Button>
                </DialogFooter>
              </form>
              <div className="mt-5 rounded-lg border">
                {permissions.length ? (
                  permissions.map((item) => (
                    <div
                      key={item.user.id}
                      className="flex items-center gap-3 border-b px-3 py-2 last:border-b-0"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">
                          {item.user.name}
                        </p>
                        <p className="truncate text-xs text-muted-foreground">
                          {item.user.username}
                        </p>
                      </div>
                      <PermissionBadge permission={item.permission} />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        title="撤销授权"
                        aria-label="撤销授权"
                        onClick={() =>
                          void handleRevokePermission(item.user.id)
                        }
                      >
                        <Trash2Icon />
                      </Button>
                    </div>
                  ))
                ) : (
                  <p className="p-3 text-sm text-muted-foreground">暂无授权</p>
                )}
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  )
}
