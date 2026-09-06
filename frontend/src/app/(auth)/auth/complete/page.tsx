import { EnterpriseLoginComplete } from "@/components/auth/enterprise-login-complete"

export default async function EnterpriseLoginCompletePage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>
}) {
  const query = await searchParams
  const next = Array.isArray(query.next) ? query.next[0] : query.next
  return <EnterpriseLoginComplete next={next} />
}
