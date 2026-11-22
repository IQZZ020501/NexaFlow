import { useLanguage } from "@/contexts/language-provider"
import type { ModelVisibility } from "@/lib/api/llm"

/** Distinguishes identically named personal and shared models in pickers. */
export function ModelScopeLabel({
  visibility,
}: {
  visibility: ModelVisibility
}) {
  const { t } = useLanguage()
  return (
    <span className="shrink-0 text-xs font-normal text-muted-foreground">
      {t(visibility === "personal" ? "仅自己" : "工作空间共享")}
    </span>
  )
}
