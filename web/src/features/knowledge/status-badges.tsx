import { useLanguage } from "@/components/language-provider"
import { Badge } from "@/components/ui/badge"
import { STATUS_LABEL_KEYS } from "@/app/constants"

export function StatusBadge({ status }: { status: string }) {
  const { t } = useLanguage()
  const labelKey = STATUS_LABEL_KEYS[status]

  return (
    <Badge variant={status === "active" ? "secondary" : "outline"}>
      {labelKey ? t(labelKey) : status}
    </Badge>
  )
}

export function PermissionBadge({ permission }: { permission: string }) {
  return (
    <Badge variant={permission === "edit" ? "secondary" : "outline"}>
      {permission === "edit" ? "可编辑" : "可查看"}
    </Badge>
  )
}
