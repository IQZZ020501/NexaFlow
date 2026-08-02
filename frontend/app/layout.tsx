import type { Metadata, Viewport } from "next"

import { AppProviders } from "@/contexts/app-providers"
import "./globals.css"

export const metadata: Metadata = {
  title: "NexaFlow",
  description: "编排业务流程、知识库和模型能力，构建可运行的 AI 应用。",
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-Hans" suppressHydrationWarning>
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  )
}
