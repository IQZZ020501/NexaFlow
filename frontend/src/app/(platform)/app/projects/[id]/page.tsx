import { ProjectsPage } from "@/components/projects/projects-page"
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  return <ProjectsPage projectId={(await params).id} />
}
