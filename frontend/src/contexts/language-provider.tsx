"use client"

import * as React from "react"

import {
  DEFAULT_LANGUAGE,
  LANGUAGE_STORAGE_KEY,
  isLanguage,
  translate,
  type Language,
  type TFunction,
} from "@/i18n"

type LanguageProviderProps = {
  children: React.ReactNode
  defaultLanguage?: Language
  storageKey?: string
}

type LanguageProviderState = {
  language: Language
  setLanguage: (language: Language) => void
  t: TFunction
}

const LanguageProviderContext = React.createContext<
  LanguageProviderState | undefined
>(undefined)

/**
 * Provides language state and translation access to descendant components.
 *
 * @param children - The components rendered within the language context
 * @param defaultLanguage - The language used when no valid stored language exists
 * @param storageKey - The local-storage key used to persist the language
 * @returns The language context provider containing `children`
 */
export function LanguageProvider({
  children,
  defaultLanguage = DEFAULT_LANGUAGE,
  storageKey = LANGUAGE_STORAGE_KEY,
}: LanguageProviderProps) {
  const [language, setLanguageState] = React.useState<Language>(defaultLanguage)

  React.useEffect(() => {
    const storedLanguage = localStorage.getItem(storageKey)
    if (isLanguage(storedLanguage)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLanguageState(storedLanguage)
    }
  }, [storageKey, defaultLanguage])

  const setLanguage = React.useCallback(
    (nextLanguage: Language) => {
      localStorage.setItem(storageKey, nextLanguage)
      setLanguageState(nextLanguage)
    },
    [storageKey]
  )

  React.useEffect(() => {
    document.documentElement.lang = language
  }, [language])

  React.useEffect(() => {
    const handleStorageChange = (event: StorageEvent) => {
      if (event.storageArea !== localStorage || event.key !== storageKey) {
        return
      }

      setLanguageState(
        isLanguage(event.newValue) ? event.newValue : defaultLanguage
      )
    }

    window.addEventListener("storage", handleStorageChange)

    return () => {
      window.removeEventListener("storage", handleStorageChange)
    }
  }, [defaultLanguage, storageKey])

  const t = React.useCallback<TFunction>(
    (key, values) => translate(language, key, values),
    [language]
  )

  const value = React.useMemo(
    () => ({
      language,
      setLanguage,
      t,
    }),
    [language, setLanguage, t]
  )

  return (
    <LanguageProviderContext.Provider value={value}>
      {children}
    </LanguageProviderContext.Provider>
  )
}

export const useLanguage = () => {
  const context = React.useContext(LanguageProviderContext)

  if (context === undefined) {
    throw new Error("useLanguage must be used within a LanguageProvider")
  }

  return context
}
