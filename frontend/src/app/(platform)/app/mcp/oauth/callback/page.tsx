import { Suspense } from "react"
import { McpOAuthCallbackPage } from "@/components/tools/mcp-oauth-callback"

export const metadata = { referrer: "no-referrer" as const }

export default function Page() {
  return (
    <Suspense fallback={null}>
      <McpOAuthCallbackPage />
    </Suspense>
  )
}
