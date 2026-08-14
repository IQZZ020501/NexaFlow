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
    root.style.colorScheme = resolvedTheme;
    root.style.backgroundColor =
      resolvedTheme === "dark" ? "oklch(0.145 0 0)" : "oklch(1 0 0)";
  } catch {}
})();
`

const criticalThemeStyles = `
html, body { background-color: oklch(1 0 0); }
html.dark, html.dark body { background-color: oklch(0.145 0 0); }
`

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
