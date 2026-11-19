import { redirect } from "next/navigation"

export default async function MemoryPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  await params
  redirect("/system/memories")
}
