import { Suspense } from "react"

import { IntegrationOAuthCallbackPage } from "@/components/tools/integration-oauth-callback"

export default function Page() {
  return (
    <Suspense>
      <IntegrationOAuthCallbackPage />
    </Suspense>
  )
}
