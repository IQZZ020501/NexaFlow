import { InvitationPage } from "@/components/auth/invitation-page"

export default async function InvitationRoute({
  params,
}: {
  params: Promise<{ token: string }>
}) {
  const { token } = await params
  return <InvitationPage token={token} />
}
