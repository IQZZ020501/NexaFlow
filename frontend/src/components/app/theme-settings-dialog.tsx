"use client"

import * as React from "react"
import { CheckIcon, RotateCcwIcon, XIcon } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { useLanguage } from "@/contexts/language-provider"
import { useOptionalSession } from "@/contexts/session-context"
import { useTheme } from "@/contexts/theme-provider"
import {
  contentWidthOptions,
  DEFAULT_PALETTE,
  densityOptions,
  fontOptions,
  layoutOptions,
  paletteOptions,
  radiusOptions,
  sidebarOptions,
  themeOptions,
  type ThemeContentWidth,
  type ThemeDensity,
  type ThemeFont,
  type ThemeLayout,
  type ThemePalette,
  type ThemeRadius,
  type ThemeSidebar,
} from "@/lib/theme-options"
import { cn } from "@/lib/utils"

type ThemeSettingsDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
}

type SelectCardProps = {
  label: string
  selected: boolean
  onSelect: () => void
  children: React.ReactNode
  className?: string
  labelClassName?: string
}

function SelectCard({
  label,
  selected,
  onSelect,
  children,
  className,
  labelClassName,
}: SelectCardProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      data-selected={selected ? "true" : "false"}
      className={cn(
        "group flex min-w-0 flex-col items-stretch text-left outline-none",
        className
      )}
      onClick={onSelect}
    >
      <div
        className="theme-settings-option relative h-12 rounded-md ring-1 ring-border transition duration-200 ease-in group-hover:ring-[var(--theme-settings-accent)] group-focus-visible:ring-2 group-focus-visible:ring-ring data-[selected=true]:ring-2 data-[selected=true]:ring-[var(--theme-settings-accent)]"
        data-selected={selected ? "true" : "false"}
      >
        {children}
        {selected ? (
          <span className="theme-settings-check absolute top-1 right-1 z-10 flex size-4 items-center justify-center rounded-full border border-background shadow-sm">
            <CheckIcon className="size-2.5" strokeWidth={3} aria-hidden="true" />
          </span>
        ) : null}
      </div>
      <span
        className={cn("mt-1.5 truncate text-center text-xs", labelClassName)}
      >
        {label}
      </span>
    </button>
  )
}

function SettingsSection({
  title,
  action,
  children,
}: {
  title: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

function ThemePreview({ value }: { value: "system" | "light" | "dark" }) {
  return (
    <div
      className="theme-preview"
      data-preview-theme={value}
      aria-hidden="true"
    >
      <div className="theme-preview__sidebar" />
      <div className="theme-preview__content">
        <div className="space-y-1.5">
          <div className="theme-preview__line" />
          <div className="theme-preview__line theme-preview__line--short" />
          <div className="theme-preview__card" />
        </div>
        <div className="theme-preview__chart" />
      </div>
    </div>
  )
}

/**
 * Renders a palette swatch from the palette's own tokens: the nested
 * `[data-palette]` blocks apply to this element, so the preview shows the real
 * surface, card, text, and accent of that palette in the active color scheme.
 */
function PalettePreview({ value }: { value: ThemePalette }) {
  return (
    <div
      className="theme-preset-preview"
      data-palette={value}
      aria-hidden="true"
    >
      <div className="theme-preset-preview__surface">
        <div className="theme-preset-preview__lines">
          <span />
          <span />
        </div>
      </div>
      <div className="theme-preset-preview__accent" />
    </div>
  )
}

function FontPreview({ value }: { value: ThemeFont }) {
  return (
    <div className="flex h-full min-h-0 items-center justify-center rounded-md bg-muted/30">
      <span
        className={cn(
          "text-2xl font-semibold",
          value === "sans" && "font-sans",
          value === "serif" && "font-serif"
        )}
        aria-hidden="true"
      >
        Aa
      </span>
    </div>
  )
}

function RadiusPreview({ value }: { value: ThemeRadius }) {
  const radius =
    value === "0"
      ? "0rem"
      : value === "0.3"
        ? "0.1875rem"
        : value === "0.5"
          ? "0.3125rem"
          : value === "0.75"
            ? "0.46875rem"
            : value === "1.0"
              ? "0.75rem"
              : "0.625rem"

  return (
    <div className="flex h-full min-h-0 items-center justify-center rounded-md bg-muted/30">
      <span
        className="theme-radius-preview"
        style={{ "--preview-radius": radius } as React.CSSProperties}
        aria-hidden="true"
      />
    </div>
  )
}

function DensityPreview({ value }: { value: ThemeDensity }) {
  const gap =
    value === "compact"
      ? "0.25rem"
      : value === "relaxed"
        ? "0.58rem"
        : value === "large"
          ? "0.76rem"
          : "0.42rem"

  return (
    <div className="flex h-full min-h-0 items-center rounded-md bg-muted/30 px-2.5 text-muted-foreground">
      <div
        className="theme-density-preview"
        style={{ "--preview-gap": gap } as React.CSSProperties}
        aria-hidden="true"
      >
        <span />
        <span />
        <span />
      </div>
    </div>
  )
}

function SidebarPreview({ value }: { value: ThemeSidebar }) {
  return (
    <div
      className="theme-sidebar-preview"
      data-preview-sidebar={value}
      aria-hidden="true"
    >
      <span />
      <span />
    </div>
  )
}

function LayoutPreview({ value }: { value: ThemeLayout }) {
  return (
    <div
      className="theme-layout-preview"
      data-preview-layout={value}
      aria-hidden="true"
    >
      <span />
      <span />
    </div>
  )
}

function ContentWidthPreview({ value }: { value: ThemeContentWidth }) {
  return (
    <div
      className="theme-content-width-preview"
      data-preview-width={value}
      aria-hidden="true"
    >
      <span />
    </div>
  )
}

/** Full appearance and layout preferences, presented as a responsive side panel. */
export function ThemeSettingsDialog({
  open,
  onOpenChange,
}: ThemeSettingsDialogProps) {
  const { t } = useLanguage()
  const notify = useOptionalSession()?.notify
  const {
    theme,
    setTheme,
    palette,
    setPalette,
    font,
    setFont,
    radius,
    setRadius,
    density,
    setDensity,
    sidebar,
    setSidebar,
    layout,
    setLayout,
    contentWidth,
    setContentWidth,
  } = useTheme()

  const resetPalette = () => {
    setPalette(DEFAULT_PALETTE)
    notify?.("success", t("已恢复默认配色"))
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        side="right"
        className="theme-settings-panel gap-0 overflow-hidden p-0"
      >
        <div className="flex h-full min-h-0 flex-col" data-theme-settings>
          <DialogHeader className="shrink-0 border-b px-4 py-3 sm:px-6 sm:py-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 space-y-1">
                <DialogTitle className="text-base font-medium">
                  {t("主题设置")}
                </DialogTitle>
                <DialogDescription className="text-sm">
                  {t("调整外观和布局以适应您的偏好。")}
                </DialogDescription>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="-mt-1 -mr-1 shrink-0"
                aria-label={t("关闭")}
                title={t("关闭")}
                onClick={() => onOpenChange(false)}
              >
                <XIcon aria-hidden="true" />
              </Button>
            </div>
          </DialogHeader>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-6 sm:py-5">
            <div className="space-y-6 pb-3">
              <SettingsSection title={t("主题")}>
                <div className="grid w-full grid-cols-3 gap-4">
                  {themeOptions.map((option) => (
                    <SelectCard
                      key={option.value}
                      label={t(option.labelKey)}
                      selected={theme === option.value}
                      onSelect={() => setTheme(option.value)}
                      labelClassName="mt-1 text-left"
                    >
                      <ThemePreview value={option.value} />
                    </SelectCard>
                  ))}
                </div>
              </SettingsSection>

              <SettingsSection
                title={t("颜色预设")}
                action={
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className="text-muted-foreground"
                    aria-label={t("恢复默认")}
                    title={t("恢复默认")}
                    onClick={resetPalette}
                  >
                    <RotateCcwIcon aria-hidden="true" />
                  </Button>
                }
              >
                <div className="grid w-full grid-cols-4 gap-3">
                  {paletteOptions.map((option) => (
                    <SelectCard
                      key={option.value}
                      label={t(option.labelKey)}
                      selected={palette === option.value}
                      onSelect={() => setPalette(option.value)}
                    >
                      <PalettePreview value={option.value} />
                    </SelectCard>
                  ))}
                </div>
              </SettingsSection>

              <SettingsSection title={t("字体")}>
                <div className="grid w-full grid-cols-3 gap-4">
                  {fontOptions.map((option) => (
                    <SelectCard
                      key={option.value}
                      label={t(option.labelKey)}
                      selected={font === option.value}
                      onSelect={() => setFont(option.value)}
                    >
                      <FontPreview value={option.value} />
                    </SelectCard>
                  ))}
                </div>
              </SettingsSection>

              <SettingsSection title={t("圆角")}>
                <div className="grid w-full grid-cols-6 gap-2">
                  {radiusOptions.map((option) => (
                    <SelectCard
                      key={option.value}
                      label={t(option.labelKey)}
                      selected={radius === option.value}
                      onSelect={() => setRadius(option.value)}
                    >
                      <RadiusPreview value={option.value} />
                    </SelectCard>
                  ))}
                </div>
              </SettingsSection>

              <SettingsSection title={t("密度")}>
                <div className="grid w-full grid-cols-4 gap-3">
                  {densityOptions.map((option) => (
                    <SelectCard
                      key={option.value}
                      label={t(option.labelKey)}
                      selected={density === option.value}
                      onSelect={() => setDensity(option.value)}
                    >
                      <DensityPreview value={option.value} />
                    </SelectCard>
                  ))}
                </div>
              </SettingsSection>

              <SettingsSection title={t("侧边栏")}>
                <div className="grid w-full grid-cols-3 gap-4">
                  {sidebarOptions.map((option) => (
                    <SelectCard
                      key={option.value}
                      label={t(option.labelKey)}
                      selected={sidebar === option.value}
                      onSelect={() => setSidebar(option.value)}
                      labelClassName="mt-1 text-left"
                    >
                      <SidebarPreview value={option.value} />
                    </SelectCard>
                  ))}
                </div>
              </SettingsSection>

              <SettingsSection title={t("布局")}>
                <div className="grid w-full grid-cols-3 gap-4">
                  {layoutOptions.map((option) => (
                    <SelectCard
                      key={option.value}
                      label={t(option.labelKey)}
                      selected={layout === option.value}
                      onSelect={() => setLayout(option.value)}
                      labelClassName="mt-1 text-left"
                    >
                      <LayoutPreview value={option.value} />
                    </SelectCard>
                  ))}
                </div>
              </SettingsSection>

              <SettingsSection title={t("内容宽度")}>
                <div className="grid w-full grid-cols-2 gap-4">
                  {contentWidthOptions.map((option) => (
                    <SelectCard
                      key={option.value}
                      label={t(option.labelKey)}
                      selected={contentWidth === option.value}
                      onSelect={() => setContentWidth(option.value)}
                    >
                      <ContentWidthPreview value={option.value} />
                    </SelectCard>
                  ))}
                </div>
              </SettingsSection>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
