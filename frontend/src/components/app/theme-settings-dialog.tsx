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
}

function SelectCard({
  label,
  selected,
  onSelect,
  children,
  className,
}: SelectCardProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      data-selected={selected ? "true" : "false"}
      className={cn(
        "theme-settings-card flex min-w-0 flex-col gap-1.5 rounded-lg bg-card p-1.5 text-left text-card-foreground hover:bg-accent/40",
        className
      )}
      onClick={onSelect}
    >
      {children}
      <span className="truncate px-1 text-xs font-medium">{label}</span>
      {selected ? (
        <span className="theme-settings-check absolute -right-1.5 -top-1.5 flex size-5 items-center justify-center rounded-full border-2 border-background shadow-sm">
          <CheckIcon className="size-3" strokeWidth={3} aria-hidden="true" />
        </span>
      ) : null}
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
    <section className="space-y-3">
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
    <div className="theme-preview" data-preview-theme={value} aria-hidden="true">
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

function FontPreview({ value }: { value: ThemeFont }) {
  return (
    <div className="flex min-h-[3.25rem] items-center justify-center rounded-md border border-border bg-muted/30">
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
    <div className="flex min-h-[2.75rem] items-center justify-center rounded-md border border-border bg-muted/30">
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
    <div className="flex min-h-[2.75rem] items-center rounded-md border border-border bg-muted/30 px-2.5 text-muted-foreground">
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

  const resetPreferences = () => {
    setTheme("system")
    setPalette(DEFAULT_PALETTE)
    setFont("auto")
    setRadius("auto")
    setDensity("default")
    setSidebar("inset")
    setLayout("default")
    setContentWidth("wide")
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        side="right"
        className="theme-settings-panel gap-0 overflow-hidden p-0"
      >
        <div className="flex h-full min-h-0 flex-col" data-theme-settings>
          <DialogHeader className="shrink-0 border-b px-5 py-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 space-y-1">
                <DialogTitle className="text-xl tracking-tight">
                  {t("主题设置")}
                </DialogTitle>
                <DialogDescription className="text-xs">
                  {t("调整外观和布局以适应您的偏好。")}
                </DialogDescription>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="-mr-2 -mt-2 shrink-0"
                aria-label={t("关闭")}
                onClick={() => onOpenChange(false)}
              >
                <XIcon aria-hidden="true" />
              </Button>
            </div>
          </DialogHeader>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5">
            <div className="space-y-6 pb-3">
              <SettingsSection title={t("主题")}>
                <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                  {themeOptions.map((option) => (
                    <SelectCard
                      key={option.value}
                      label={t(option.labelKey)}
                      selected={theme === option.value}
                      onSelect={() => setTheme(option.value)}
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
                    onClick={resetPreferences}
                  >
                    <RotateCcwIcon aria-hidden="true" />
                  </Button>
                }
              >
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {paletteOptions.map((option) => (
                    <SelectCard
                      key={option.value}
                      label={t(option.labelKey)}
                      selected={palette === option.value}
                      onSelect={() => setPalette(option.value)}
                    >
                      <div
                        className={cn("theme-preset-swatch", option.swatchClassName)}
                        aria-hidden="true"
                      />
                    </SelectCard>
                  ))}
                </div>
              </SettingsSection>

              <SettingsSection title={t("字体")}>
                <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
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
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
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
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
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
                <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                  {sidebarOptions.map((option) => (
                    <SelectCard
                      key={option.value}
                      label={t(option.labelKey)}
                      selected={sidebar === option.value}
                      onSelect={() => setSidebar(option.value)}
                    >
                      <SidebarPreview value={option.value} />
                    </SelectCard>
                  ))}
                </div>
              </SettingsSection>

              <SettingsSection title={t("布局")}>
                <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                  {layoutOptions.map((option) => (
                    <SelectCard
                      key={option.value}
                      label={t(option.labelKey)}
                      selected={layout === option.value}
                      onSelect={() => setLayout(option.value)}
                    >
                      <LayoutPreview value={option.value} />
                    </SelectCard>
                  ))}
                </div>
              </SettingsSection>

              <SettingsSection title={t("内容宽度")}>
                <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
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
