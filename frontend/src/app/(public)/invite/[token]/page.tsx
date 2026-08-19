import { InvitationPage } from "@/components/auth/invitation-page"

/**
 * Renders the invitation page for the specified invitation token.
 *
 * @param params - Route parameters containing the invitation token.
 */
export default async function InvitationRoute({
  params,
}: {
  params: Promise<{ token: string }>
}) {
  const { token } = await params
  return <InvitationPage token={token} />
}
