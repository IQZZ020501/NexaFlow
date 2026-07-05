import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react"
import { type TranslationKey } from "@/lib/i18n"

export type ThemePreference = "system" | "light" | "dark"
export const themeOptions: Array<{
  value: ThemePreference
  labelKey: TranslationKey
  icon: typeof MonitorIcon
}> = [
  { value: "system", labelKey: "跟随系统", icon: MonitorIcon },
  { value: "light", labelKey: "白色", icon: SunIcon },
  { value: "dark", labelKey: "暗色", icon: MoonIcon },
]
