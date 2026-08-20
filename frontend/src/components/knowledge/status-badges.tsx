import { useLanguage } from "@/contexts/language-provider"
import { Badge } from "@/components/ui/badge"
import { STATUS_LABEL_KEYS } from "@/lib/constants"

/**
 * Renders a badge for a status, translating recognized values.
 *
 * @param status - The status value to display
 * @returns A badge showing the translated status or the original value
 */
export function StatusBadge({ status }: { status: string }) {
  const { t } = useLanguage()
  const labelKey = STATUS_LABEL_KEYS[status]

  return (
    <Badge variant={status === "active" ? "secondary" : "outline"}>
      {labelKey ? t(labelKey) : status}
    </Badge>
  )
}

/**
 * Renders a badge for an edit or view permission.
 *
 * @param permission - The permission level to display
 * @returns A badge labeled according to the permission level
 */
export function PermissionBadge({ permission }: { permission: string }) {
  const { t } = useLanguage()
  return (
    <Badge variant={permission === "edit" ? "secondary" : "outline"}>
      {t(permission === "edit" ? "可编辑" : "可查看")}
    </Badge>
  )
}
