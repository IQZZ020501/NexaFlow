import { KnowledgeUploadStateProvider } from "@/components/knowledge/knowledge-upload-state"

export default function KnowledgeUploadLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <KnowledgeUploadStateProvider>{children}</KnowledgeUploadStateProvider>
  )
}
