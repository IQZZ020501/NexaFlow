import { LoginPageContent } from "@/components/auth/login-page-content"

type LoginPageProps = {
  searchParams: Promise<{
    next?: string | string[]
    workspace?: string | string[]
    error?: string | string[]
  }>
}

/**
 * Renders the login page with an optional destination after authentication.
 *
 * @returns The login page content.
 */
export default async function LoginPage({ searchParams }: LoginPageProps) {
  const query = await searchParams
  const next = Array.isArray(query.next) ? query.next[0] : query.next
  const workspace = Array.isArray(query.workspace) ? query.workspace[0] : query.workspace
  const error = Array.isArray(query.error) ? query.error[0] : query.error
  return <LoginPageContent next={next} workspace={workspace} error={error} />
}
