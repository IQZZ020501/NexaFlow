"use client"

import type { ReactNode } from "react"

import { TopProgress } from "@/components/app/top-progress"
import { LanguageProvider } from "@/contexts/language-provider"
import { SessionProvider } from "@/contexts/session-context"
import { ThemeProvider } from "@/contexts/theme-provider"

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <LanguageProvider>
      <ThemeProvider>
        <SessionProvider>
          <TopProgress />
          {children}
        </SessionProvider>
      </ThemeProvider>
    </LanguageProvider>
  )
}
