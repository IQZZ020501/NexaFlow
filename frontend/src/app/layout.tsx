import type { Metadata, Viewport } from "next"

import { AppProviders } from "@/contexts/app-providers"
import "./globals.css"

export const metadata: Metadata = {
  title: "NexaFlow",
  description: "编排业务流程、知识库和模型能力，构建可运行的 AI 应用。",
  icons: {
    icon: "/NexaFlow-logo.png",
    apple: "/NexaFlow-logo.png",
  },
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // `cover` is required for env(safe-area-inset-*) to report real device insets.
  viewportFit: "cover",
  // The browser chrome color is written by `themeScript` and kept in sync by the
  // theme provider: a metadata `themeColor` cannot see the active palette, and
  // React re-applies it after hydration, overwriting the palette-aware value.
}

const themeScript = `
(function () {
  try {
    var storedTheme = localStorage.getItem("theme");
    var resolvedTheme =
      storedTheme === "dark" || storedTheme === "light"
        ? storedTheme
        : window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light";
    var root = document.documentElement;
    root.classList.remove("light", "dark");
    root.classList.add(resolvedTheme);
    var storedPalette = localStorage.getItem("palette");
    var palettes = ["neutral", "anthropic", "simple", "night", "rose", "lake", "amber", "forest", "ocean", "violet"];
    root.dataset.palette = palettes.indexOf(storedPalette) >= 0 ? storedPalette : "neutral";
    var storedFont = localStorage.getItem("font");
    root.dataset.font = storedFont === "auto" || storedFont === "sans" || storedFont === "serif" ? storedFont : "auto";
    var storedRadius = localStorage.getItem("radius");
    root.dataset.radius = ["auto", "0", "0.3", "0.5", "0.75", "1.0"].indexOf(storedRadius) >= 0 ? storedRadius : "auto";
    var storedDensity = localStorage.getItem("density");
    root.dataset.density = ["compact", "default", "relaxed", "large"].indexOf(storedDensity) >= 0 ? storedDensity : "default";
    var storedSidebar = localStorage.getItem("sidebar");
    root.dataset.sidebar = ["inset", "floating", "sidebar"].indexOf(storedSidebar) >= 0 ? storedSidebar : "inset";
    var storedLayout = localStorage.getItem("layout");
    root.dataset.layout = ["default", "compact", "full"].indexOf(storedLayout) >= 0 ? storedLayout : "default";
    var storedContentWidth = localStorage.getItem("content-width");
    root.dataset.contentWidth = ["wide", "centered"].indexOf(storedContentWidth) >= 0 ? storedContentWidth : "wide";
    root.style.colorScheme = resolvedTheme;
    root.style.backgroundColor = "var(--background)";
    var themeColor = getComputedStyle(root).backgroundColor;
    var themeColorMeta = document.querySelector('meta[name="theme-color"]');
    if (!themeColorMeta) {
      themeColorMeta = document.createElement("meta");
      themeColorMeta.setAttribute("name", "theme-color");
      document.head.appendChild(themeColorMeta);
    }
    themeColorMeta.setAttribute("content", themeColor);
  } catch {}
})();
`

/*
 * Paints the document canvas before the stylesheet arrives. Only the root is
 * styled: the root background propagates to the canvas, and styling `body` here
 * would outrank the layered `bg-background` rule and pin the page to the
 * neutral surface under any other palette.
 */
const criticalThemeStyles = `
html { background-color: oklch(1 0 0); }
html.dark { background-color: oklch(0.145 0 0); }
html[data-palette="anthropic"] { background-color: oklch(0.985 0.012 35); }
html.dark[data-palette="anthropic"] { background-color: oklch(0.145 0.022 35); }
html[data-palette="simple"] { background-color: oklch(0.985 0 0); }
html.dark[data-palette="simple"] { background-color: oklch(0.11 0 0); }
html[data-palette="night"] { background-color: oklch(0.96 0.012 255); }
html.dark[data-palette="night"] { background-color: oklch(0.11 0.025 255); }
html[data-palette="rose"] { background-color: oklch(0.985 0.012 350); }
html.dark[data-palette="rose"] { background-color: oklch(0.145 0.024 350); }
html[data-palette="lake"] { background-color: oklch(0.985 0.012 190); }
html.dark[data-palette="lake"] { background-color: oklch(0.145 0.024 190); }
html[data-palette="ocean"] { background-color: oklch(0.985 0.006 250); }
html.dark[data-palette="ocean"] { background-color: oklch(0.145 0.02 250); }
html[data-palette="violet"] { background-color: oklch(0.985 0.006 300); }
html.dark[data-palette="violet"] { background-color: oklch(0.145 0.022 300); }
html[data-palette="forest"] { background-color: oklch(0.985 0.01 152); }
html.dark[data-palette="forest"] { background-color: oklch(0.145 0.018 152); }
html[data-palette="amber"] { background-color: oklch(0.972 0.011 72); }
html.dark[data-palette="amber"] { background-color: oklch(0.145 0.022 72); }
`

/**
 * Renders the root HTML layout for the application.
 *
 * @param children - The page content rendered within the application providers
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-Hans" suppressHydrationWarning>
      <head>
        <style dangerouslySetInnerHTML={{ __html: criticalThemeStyles }} />
        <script
          id="theme-init"
          dangerouslySetInnerHTML={{ __html: themeScript }}
        />
      </head>
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  )
}
