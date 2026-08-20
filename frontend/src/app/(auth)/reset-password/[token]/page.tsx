import { ResetPasswordPage } from "@/components/auth/reset-password-page"

/** Renders the public password-reset confirmation page. */
export default async function ResetPasswordRoute({
  params,
}: {
  params: Promise<{ token: string }>
}) {
  const { token } = await params
  return <ResetPasswordPage token={token} />
}
