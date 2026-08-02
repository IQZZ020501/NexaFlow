"use client"

import { PlaceholderPage } from "@/components/pages/placeholder-page"
import { useLanguage } from "@/contexts/language-provider"
import { getPages } from "@/lib/pages"

export default function AppsPage() {
  const { t } = useLanguage()
  const page = getPages(t).find((item) => item.key === "apps")

  return page ? <PlaceholderPage page={page} /> : null
}
