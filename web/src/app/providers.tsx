import type { ReactNode } from "react"

import { LanguageProvider } from "@/components/language-provider"
import { ThemeProvider } from "@/components/theme-provider"

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <LanguageProvider>
      <ThemeProvider>{children}</ThemeProvider>
    </LanguageProvider>
  )
}
