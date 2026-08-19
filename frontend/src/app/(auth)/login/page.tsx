import { LoginPageContent } from "@/components/auth/login-page-content"

type LoginPageProps = {
  searchParams: Promise<{ next?: string | string[] }>
}

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const query = await searchParams
  const next = Array.isArray(query.next) ? query.next[0] : query.next
  return <LoginPageContent next={next} />
}
