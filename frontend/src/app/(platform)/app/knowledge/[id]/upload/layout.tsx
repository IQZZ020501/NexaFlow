import { KnowledgeUploadStateProvider } from "@/components/knowledge/knowledge-upload-state"

/**
 * Provides shared knowledge-upload state to the nested route content.
 *
 * @param children - The content rendered within the knowledge-upload state provider
 */
export default function KnowledgeUploadLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <KnowledgeUploadStateProvider>{children}</KnowledgeUploadStateProvider>
  )
}
