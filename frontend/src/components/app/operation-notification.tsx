import { CircleCheckIcon, CircleOffIcon, InfoIcon, XIcon } from "lucide-react"
import { useLanguage } from "@/contexts/language-provider"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { AppNotification } from "@/lib/notifications"

/**
 * Displays a dismissible success, info, or error notification banner.
 *
 * @param notification - The notification to display, or `null` when no banner should be rendered.
 * @returns The notification banner, or `null` when no notification is provided.
 */
export function OperationNotification({
  notification,
  onDismiss,
}: {
  notification: AppNotification | null
  onDismiss: () => void
}) {
  const { t } = useLanguage()

  if (!notification) {
    return null
  }

  const Icon =
    notification.kind === "success"
      ? CircleCheckIcon
      : notification.kind === "error"
        ? CircleOffIcon
        : InfoIcon

  return (
    <div
      className="fixed top-4 left-1/2 z-[60] w-[calc(100%-2rem)] max-w-sm -translate-x-1/2"
      role={notification.kind === "error" ? "alert" : "status"}
      aria-live={notification.kind === "error" ? "assertive" : "polite"}
    >
      <div
        className={cn(
          "flex items-center gap-3 rounded-lg border bg-background px-3 py-2 text-sm shadow-lg",
          notification.kind === "success"
            ? "border-emerald-300 text-emerald-700 dark:border-emerald-500/50 dark:text-emerald-300"
            : notification.kind === "error"
              ? "border-destructive/50 text-destructive"
              : "border-sky-300 text-sky-700 dark:border-sky-500/50 dark:text-sky-300"
        )}
      >
        <Icon className="size-4 shrink-0" />
        <span className="min-w-0 flex-1 truncate">{notification.message}</span>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={onDismiss}
          aria-label={t("关闭提示")}
        >
          <XIcon />
        </Button>
      </div>
    </div>
  )
}
