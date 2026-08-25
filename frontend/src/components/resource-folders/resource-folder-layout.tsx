import type { ReactNode } from "react"

export function ResourceFolderLayout({
  sidebar,
  children,
}: {
  sidebar: ReactNode
  children: ReactNode
}) {
  return (
    <div className="flex min-w-0 flex-col gap-4 lg:flex-row lg:items-stretch">
      {sidebar}
      <div className="min-w-0 flex-1 space-y-4">{children}</div>
    </div>
  )
}
