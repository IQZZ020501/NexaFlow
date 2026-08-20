"use client"

import type { ReactNode } from "react"

import { TopProgress } from "@/components/app/top-progress"
import { LanguageProvider } from "@/contexts/language-provider"
import { SessionProvider } from "@/contexts/session-context"
import { ThemeProvider } from "@/contexts/theme-provider"

/**
 * Provides application-wide language, theme, and session contexts to its children.
 *
 * @param children - The content rendered within the application providers
 */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <LanguageProvider>
      <ThemeProvider>
        <SessionProvider>
          {children}
          <TopProgress />
        </SessionProvider>
      </ThemeProvider>
    </LanguageProvider>
  )
}
