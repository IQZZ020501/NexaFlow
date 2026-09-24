"use client"

import * as React from "react"

import {
  DEFAULT_PALETTE,
  isThemePalette,
  isThemeContentWidth,
  isThemeDensity,
  isThemeFont,
  isThemeLayout,
  isThemeRadius,
  isThemeSidebar,
  type ThemePalette,
  type ThemeContentWidth,
  type ThemeDensity,
  type ThemeFont,
  type ThemeLayout,
  type ThemeRadius,
  type ThemeSidebar,
} from "@/lib/theme-options"

export type Theme = "dark" | "light" | "system"
type ResolvedTheme = "dark" | "light"

type ThemeProviderProps = {
  children: React.ReactNode
  defaultTheme?: Theme
  defaultPalette?: ThemePalette
  defaultFont?: ThemeFont
  defaultRadius?: ThemeRadius
  defaultDensity?: ThemeDensity
  defaultSidebar?: ThemeSidebar
  defaultLayout?: ThemeLayout
  defaultContentWidth?: ThemeContentWidth
  storageKey?: string
  paletteStorageKey?: string
  fontStorageKey?: string
  radiusStorageKey?: string
  densityStorageKey?: string
  sidebarStorageKey?: string
  layoutStorageKey?: string
  contentWidthStorageKey?: string
  disableTransitionOnChange?: boolean
}

type ThemeProviderState = {
  theme: Theme
  setTheme: (theme: Theme) => void
  palette: ThemePalette
  setPalette: (palette: ThemePalette) => void
  font: ThemeFont
  setFont: (font: ThemeFont) => void
  radius: ThemeRadius
  setRadius: (radius: ThemeRadius) => void
  density: ThemeDensity
  setDensity: (density: ThemeDensity) => void
  sidebar: ThemeSidebar
  setSidebar: (sidebar: ThemeSidebar) => void
  layout: ThemeLayout
  setLayout: (layout: ThemeLayout) => void
  contentWidth: ThemeContentWidth
  setContentWidth: (contentWidth: ThemeContentWidth) => void
}

const COLOR_SCHEME_QUERY = "(prefers-color-scheme: dark)"
const THEME_VALUES: Theme[] = ["dark", "light", "system"]

const ThemeProviderContext = React.createContext<
  ThemeProviderState | undefined
>(undefined)

/**
 * Determines whether a value identifies a supported theme.
 *
 * @param value - The value to validate
 * @returns `true` if the value is a supported theme, `false` otherwise.
 */
function isTheme(value: string | null): value is Theme {
  if (value === null) {
    return false
  }

  return THEME_VALUES.includes(value as Theme)
}

/**
 * Reads a stored preference, falling back to the default when storage is
 * unavailable or holds an unsupported value.
 *
 * @param fallback - The value to use when no valid stored preference is available
 * @param storageKey - The local storage key containing the preference
 * @param isSupported - Validator that narrows a stored string to a supported preference
 * @returns The stored preference when valid; otherwise, `fallback`
 */
function readStoredPreference<T extends string>(
  fallback: T,
  storageKey: string,
  isSupported: (value: string | null) => value is T
) {
  if (typeof window === "undefined") {
    return fallback
  }

  try {
    const storedValue = window.localStorage.getItem(storageKey)
    return isSupported(storedValue) ? storedValue : fallback
  } catch {
    return fallback
  }
}

/** Persists a preference without breaking the UI when storage is unavailable. */
function writeStoredPreference(storageKey: string, value: string) {
  try {
    localStorage.setItem(storageKey, value)
  } catch {
    // Private browsing and restricted embedded contexts can reject writes.
  }
}

/**
 * Determines the operating system's preferred color theme.
 *
 * @returns `"dark"` if the operating system prefers dark mode, `"light"` otherwise.
 */
function getSystemTheme(): ResolvedTheme {
  if (window.matchMedia(COLOR_SCHEME_QUERY).matches) {
    return "dark"
  }

  return "light"
}

/**
 * Temporarily disables CSS transitions to allow immediate visual updates.
 *
 * @returns A function that removes the temporary transition override after two animation frames.
 */
function disableTransitionsTemporarily() {
  const style = document.createElement("style")
  style.appendChild(
    document.createTextNode(
      "*,*::before,*::after{-webkit-transition:none!important;transition:none!important}"
    )
  )
  document.head.appendChild(style)

  return () => {
    window.getComputedStyle(document.body)
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        style.remove()
      })
    })
  }
}

/**
 * Repaints the browser chrome color from the background the active palette
 * resolves to, because the `theme-color` metadata is rendered per color scheme
 * and cannot see the palette.
 */
function syncThemeColorMeta() {
  const background = window.getComputedStyle(
    document.documentElement
  ).backgroundColor
  const metaTags = document.head.querySelectorAll<HTMLMetaElement>(
    'meta[name="theme-color"]'
  )

  for (const metaTag of metaTags) {
    metaTag.content = background
  }
}

/**
 * Determines whether an event target is an editable element or contained within one.
 *
 * @param target - The event target to inspect
 * @returns `true` if the target is editable or inside an editable element, `false` otherwise.
 */
function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) {
    return false
  }

  if (target.isContentEditable) {
    return true
  }

  const editableParent = target.closest(
    "input, textarea, select, [contenteditable='true']"
  )
  if (editableParent) {
    return true
  }

  return false
}

/**
 * Provides theme and palette state and controls to descendant components.
 *
 * @param children - The components that receive the theme context
 * @param defaultTheme - The theme used when no valid stored preference exists
 * @param defaultPalette - The palette used when no valid stored preference exists
 * @param defaultFont - The font used when no valid stored preference exists
 * @param defaultRadius - The radius used when no valid stored preference exists
 * @param defaultDensity - The density used when no valid stored preference exists
 * @param defaultSidebar - The sidebar style used when no valid stored preference exists
 * @param defaultLayout - The layout used when no valid stored preference exists
 * @param defaultContentWidth - The content width used when no valid stored preference exists
 * @param storageKey - The key used to persist and synchronize the theme preference
 * @param paletteStorageKey - The key used to persist and synchronize the palette preference
 * @param disableTransitionOnChange - Whether to temporarily disable transitions when applying a theme
 * @returns A provider element containing the theme context
 */
export function ThemeProvider({
  children,
  defaultTheme = "system",
  defaultPalette = DEFAULT_PALETTE,
  defaultFont = "auto",
  defaultRadius = "auto",
  defaultDensity = "default",
  defaultSidebar = "inset",
  defaultLayout = "default",
  defaultContentWidth = "wide",
  storageKey = "theme",
  paletteStorageKey = "palette",
  fontStorageKey = "font",
  radiusStorageKey = "radius",
  densityStorageKey = "density",
  sidebarStorageKey = "sidebar",
  layoutStorageKey = "layout",
  contentWidthStorageKey = "content-width",
  disableTransitionOnChange = true,
  ...props
}: ThemeProviderProps) {
  const [theme, setThemeState] = React.useState<Theme>(() =>
    readStoredPreference(defaultTheme, storageKey, isTheme)
  )
  const [palette, setPaletteState] = React.useState<ThemePalette>(() =>
    readStoredPreference(defaultPalette, paletteStorageKey, isThemePalette)
  )
  const [font, setFontState] = React.useState<ThemeFont>(() =>
    readStoredPreference(defaultFont, fontStorageKey, isThemeFont)
  )
  const [radius, setRadiusState] = React.useState<ThemeRadius>(() =>
    readStoredPreference(defaultRadius, radiusStorageKey, isThemeRadius)
  )
  const [density, setDensityState] = React.useState<ThemeDensity>(() =>
    readStoredPreference(defaultDensity, densityStorageKey, isThemeDensity)
  )
  const [sidebar, setSidebarState] = React.useState<ThemeSidebar>(() =>
    readStoredPreference(defaultSidebar, sidebarStorageKey, isThemeSidebar)
  )
  const [layout, setLayoutState] = React.useState<ThemeLayout>(() =>
    readStoredPreference(defaultLayout, layoutStorageKey, isThemeLayout)
  )
  const [contentWidth, setContentWidthState] =
    React.useState<ThemeContentWidth>(() =>
      readStoredPreference(
        defaultContentWidth,
        contentWidthStorageKey,
        isThemeContentWidth
      )
    )

  const setTheme = React.useCallback(
    (nextTheme: Theme) => {
      writeStoredPreference(storageKey, nextTheme)
      setThemeState(nextTheme)
    },
    [storageKey]
  )

  const setPalette = React.useCallback(
    (nextPalette: ThemePalette) => {
      writeStoredPreference(paletteStorageKey, nextPalette)
      setPaletteState(nextPalette)
    },
    [paletteStorageKey]
  )

  const setFont = React.useCallback(
    (nextFont: ThemeFont) => {
      writeStoredPreference(fontStorageKey, nextFont)
      setFontState(nextFont)
    },
    [fontStorageKey]
  )

  const setRadius = React.useCallback(
    (nextRadius: ThemeRadius) => {
      writeStoredPreference(radiusStorageKey, nextRadius)
      setRadiusState(nextRadius)
    },
    [radiusStorageKey]
  )

  const setDensity = React.useCallback(
    (nextDensity: ThemeDensity) => {
      writeStoredPreference(densityStorageKey, nextDensity)
      setDensityState(nextDensity)
    },
    [densityStorageKey]
  )

  const setSidebar = React.useCallback(
    (nextSidebar: ThemeSidebar) => {
      writeStoredPreference(sidebarStorageKey, nextSidebar)
      setSidebarState(nextSidebar)
    },
    [sidebarStorageKey]
  )

  const setLayout = React.useCallback(
    (nextLayout: ThemeLayout) => {
      writeStoredPreference(layoutStorageKey, nextLayout)
      setLayoutState(nextLayout)
    },
    [layoutStorageKey]
  )

  const setContentWidth = React.useCallback(
    (nextContentWidth: ThemeContentWidth) => {
      writeStoredPreference(contentWidthStorageKey, nextContentWidth)
      setContentWidthState(nextContentWidth)
    },
    [contentWidthStorageKey]
  )

  const applyPreferences = React.useCallback(
    (
      nextTheme: Theme,
      nextPalette: ThemePalette,
      nextFont: ThemeFont,
      nextRadius: ThemeRadius,
      nextDensity: ThemeDensity,
      nextSidebar: ThemeSidebar,
      nextLayout: ThemeLayout,
      nextContentWidth: ThemeContentWidth
    ) => {
      const root = document.documentElement
      const resolvedTheme =
        nextTheme === "system" ? getSystemTheme() : nextTheme
      const restoreTransitions = disableTransitionOnChange
        ? disableTransitionsTemporarily()
        : null

      root.classList.remove("light", "dark")
      root.classList.add(resolvedTheme)
      root.dataset.palette = nextPalette
      root.dataset.font = nextFont
      root.dataset.radius = nextRadius
      root.dataset.density = nextDensity
      root.dataset.sidebar = nextSidebar
      root.dataset.layout = nextLayout
      root.dataset.contentWidth = nextContentWidth
      root.style.colorScheme = resolvedTheme
      root.style.backgroundColor = "var(--background)"
      syncThemeColorMeta()

      if (restoreTransitions) {
        restoreTransitions()
      }
    },
    [disableTransitionOnChange]
  )

  React.useEffect(() => {
    applyPreferences(
      theme,
      palette,
      font,
      radius,
      density,
      sidebar,
      layout,
      contentWidth
    )

    if (theme !== "system") {
      return undefined
    }

    const mediaQuery = window.matchMedia(COLOR_SCHEME_QUERY)
    const handleChange = () => {
      applyPreferences(
        "system",
        palette,
        font,
        radius,
        density,
        sidebar,
        layout,
        contentWidth
      )
    }

    mediaQuery.addEventListener("change", handleChange)

    return () => {
      mediaQuery.removeEventListener("change", handleChange)
    }
  }, [
    theme,
    palette,
    font,
    radius,
    density,
    sidebar,
    layout,
    contentWidth,
    applyPreferences,
  ])

  React.useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.repeat) {
        return
      }

      if (event.metaKey || event.ctrlKey || event.altKey) {
        return
      }

      if (isEditableTarget(event.target)) {
        return
      }

      if (event.key.toLowerCase() !== "d") {
        return
      }

      setThemeState((currentTheme) => {
        const nextTheme =
          currentTheme === "dark"
            ? "light"
            : currentTheme === "light"
              ? "dark"
              : getSystemTheme() === "dark"
                ? "light"
                : "dark"

        writeStoredPreference(storageKey, nextTheme)
        return nextTheme
      })
    }

    window.addEventListener("keydown", handleKeyDown)

    return () => {
      window.removeEventListener("keydown", handleKeyDown)
    }
  }, [storageKey])

  React.useEffect(() => {
    const handleStorageChange = (event: StorageEvent) => {
      if (event.storageArea !== localStorage) {
        return
      }

      if (event.key === storageKey) {
        setThemeState(isTheme(event.newValue) ? event.newValue : defaultTheme)
        return
      }

      if (event.key === paletteStorageKey) {
        setPaletteState(
          isThemePalette(event.newValue) ? event.newValue : defaultPalette
        )
        return
      }

      if (event.key === fontStorageKey) {
        setFontState(isThemeFont(event.newValue) ? event.newValue : defaultFont)
        return
      }

      if (event.key === radiusStorageKey) {
        setRadiusState(
          isThemeRadius(event.newValue) ? event.newValue : defaultRadius
        )
        return
      }

      if (event.key === densityStorageKey) {
        setDensityState(
          isThemeDensity(event.newValue) ? event.newValue : defaultDensity
        )
        return
      }

      if (event.key === sidebarStorageKey) {
        setSidebarState(
          isThemeSidebar(event.newValue) ? event.newValue : defaultSidebar
        )
        return
      }

      if (event.key === layoutStorageKey) {
        setLayoutState(
          isThemeLayout(event.newValue) ? event.newValue : defaultLayout
        )
        return
      }

      if (event.key === contentWidthStorageKey) {
        setContentWidthState(
          isThemeContentWidth(event.newValue)
            ? event.newValue
            : defaultContentWidth
        )
      }
    }

    window.addEventListener("storage", handleStorageChange)

    return () => {
      window.removeEventListener("storage", handleStorageChange)
    }
  }, [
    defaultTheme,
    defaultPalette,
    defaultFont,
    defaultRadius,
    defaultDensity,
    defaultSidebar,
    defaultLayout,
    defaultContentWidth,
    storageKey,
    paletteStorageKey,
    fontStorageKey,
    radiusStorageKey,
    densityStorageKey,
    sidebarStorageKey,
    layoutStorageKey,
    contentWidthStorageKey,
  ])

  const value = React.useMemo(
    () => ({
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
    }),
    [
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
    ]
  )

  return (
    <ThemeProviderContext.Provider {...props} value={value}>
      {children}
    </ThemeProviderContext.Provider>
  )
}

export const useTheme = () => {
  const context = React.useContext(ThemeProviderContext)

  if (context === undefined) {
    throw new Error("useTheme must be used within a ThemeProvider")
  }

  return context
}
