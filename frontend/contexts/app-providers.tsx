"use client"

import type { ReactNode } from "react"

import { LanguageProvider } from "@/contexts/language-provider"
import { SessionProvider } from "@/contexts/session-context"
import { ThemeProvider } from "@/contexts/theme-provider"

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <LanguageProvider>
      <ThemeProvider>
        <SessionProvider>{children}</SessionProvider>
      </ThemeProvider>
    </LanguageProvider>
  )
}
