import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react"
import { type TranslationKey } from "@/i18n"

export type ThemePreference = "system" | "light" | "dark"
export const themeOptions: Array<{
  value: ThemePreference
  labelKey: TranslationKey
  icon: typeof MonitorIcon
}> = [
  { value: "system", labelKey: "系统", icon: MonitorIcon },
  { value: "light", labelKey: "浅色", icon: SunIcon },
  { value: "dark", labelKey: "深色", icon: MoonIcon },
]

/**
 * Color palettes, independent of the light/dark preference.
 *
 * Each id matches a `[data-palette]` token block in `app/globals.css`; `neutral`
 * shares the base token blocks that carry the application default.
 */
const PALETTE_IDS = [
  "neutral",
  "anthropic",
  "simple",
  "night",
  "rose",
  "lake",
  "amber",
  "forest",
  "ocean",
  "violet",
] as const

export type ThemePalette = (typeof PALETTE_IDS)[number]

export const DEFAULT_PALETTE: ThemePalette = "neutral"

export const paletteOptions: Array<{
  value: ThemePalette
  labelKey: TranslationKey
  swatchClassName: string
}> = [
  { value: "neutral", labelKey: "默认", swatchClassName: "theme-preset-swatch-neutral" },
  { value: "anthropic", labelKey: "Anthropic", swatchClassName: "theme-preset-swatch-anthropic" },
  { value: "simple", labelKey: "超大字体简易", swatchClassName: "theme-preset-swatch-simple" },
  { value: "night", labelKey: "暗夜", swatchClassName: "theme-preset-swatch-night" },
  { value: "rose", labelKey: "玫瑰花园", swatchClassName: "theme-preset-swatch-rose" },
  { value: "lake", labelKey: "湖光", swatchClassName: "theme-preset-swatch-lake" },
  { value: "amber", labelKey: "日落霞光", swatchClassName: "theme-preset-swatch-amber" },
  { value: "forest", labelKey: "森林低语", swatchClassName: "theme-preset-swatch-forest" },
  { value: "ocean", labelKey: "海风", swatchClassName: "theme-preset-swatch-ocean" },
  { value: "violet", labelKey: "薰衣草草梦", swatchClassName: "theme-preset-swatch-violet" },
]

export type ThemeFont = "auto" | "sans" | "serif"
export type ThemeRadius = "auto" | "0" | "0.3" | "0.5" | "0.75" | "1.0"
export type ThemeDensity = "compact" | "default" | "relaxed" | "large"
export type ThemeSidebar = "inset" | "floating" | "sidebar"
export type ThemeLayout = "default" | "compact" | "full"
export type ThemeContentWidth = "wide" | "centered"

export const fontOptions: Array<{
  value: ThemeFont
  labelKey: TranslationKey
}> = [
  { value: "auto", labelKey: "自动" },
  { value: "sans", labelKey: "Sans" },
  { value: "serif", labelKey: "Serif" },
]

export const radiusOptions: Array<{
  value: ThemeRadius
  labelKey: TranslationKey
}> = [
  { value: "auto", labelKey: "自动" },
  { value: "0", labelKey: "0" },
  { value: "0.3", labelKey: "0.3" },
  { value: "0.5", labelKey: "0.5" },
  { value: "0.75", labelKey: "0.75" },
  { value: "1.0", labelKey: "1.0" },
]

export const densityOptions: Array<{
  value: ThemeDensity
  labelKey: TranslationKey
}> = [
  { value: "compact", labelKey: "紧凑" },
  { value: "default", labelKey: "默认" },
  { value: "relaxed", labelKey: "宽松" },
  { value: "large", labelKey: "超大" },
]

export const sidebarOptions: Array<{
  value: ThemeSidebar
  labelKey: TranslationKey
}> = [
  { value: "inset", labelKey: "内嵌" },
  { value: "floating", labelKey: "浮动" },
  { value: "sidebar", labelKey: "侧边栏" },
]

export const layoutOptions: Array<{
  value: ThemeLayout
  labelKey: TranslationKey
}> = [
  { value: "default", labelKey: "默认" },
  { value: "compact", labelKey: "紧凑" },
  { value: "full", labelKey: "全屏布局" },
]

export const contentWidthOptions: Array<{
  value: ThemeContentWidth
  labelKey: TranslationKey
}> = [
  { value: "wide", labelKey: "宽" },
  { value: "centered", labelKey: "居中" },
]

function isOneOf<T extends string>(values: readonly T[], value: string | null): value is T {
  return value !== null && values.includes(value as T)
}

export function isThemeFont(value: string | null): value is ThemeFont {
  return isOneOf(["auto", "sans", "serif"] as const, value)
}

export function isThemeRadius(value: string | null): value is ThemeRadius {
  return isOneOf(["auto", "0", "0.3", "0.5", "0.75", "1.0"] as const, value)
}

export function isThemeDensity(value: string | null): value is ThemeDensity {
  return isOneOf(["compact", "default", "relaxed", "large"] as const, value)
}

export function isThemeSidebar(value: string | null): value is ThemeSidebar {
  return isOneOf(["inset", "floating", "sidebar"] as const, value)
}

export function isThemeLayout(value: string | null): value is ThemeLayout {
  return isOneOf(["default", "compact", "full"] as const, value)
}

export function isThemeContentWidth(
  value: string | null
): value is ThemeContentWidth {
  return isOneOf(["wide", "centered"] as const, value)
}

/**
 * Determines whether a value identifies a supported palette.
 *
 * @param value - The value to validate
 * @returns `true` if the value identifies a supported palette, `false` otherwise.
 */
export function isThemePalette(value: string | null): value is ThemePalette {
  if (value === null) {
    return false
  }

  return (PALETTE_IDS as readonly string[]).includes(value)
}
