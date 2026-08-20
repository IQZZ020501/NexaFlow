import { InvitationPage } from "@/components/auth/invitation-page"

/**
 * Renders the invitation page for the specified invitation token.
 *
 * @param params - Route parameters containing the invitation token.
 */
export default async function InvitationRoute({
  params,
  searchParams,
}: {
  params: Promise<{ token: string }>
  searchParams: Promise<{ mode?: string | string[] }>
}) {
  const [{ token }, { mode }] = await Promise.all([params, searchParams])
  return <InvitationPage token={token} generic={mode === "generic"} />
}
