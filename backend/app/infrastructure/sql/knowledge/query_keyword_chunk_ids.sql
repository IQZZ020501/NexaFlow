SELECT chunk.id AS chunk_id
FROM knowledge_document_chunks AS chunk
JOIN knowledge_documents AS document
    ON document.id = chunk.document_id
    AND document.workspace_id = chunk.workspace_id
    AND document.knowledge_base_id = chunk.knowledge_base_id
WHERE chunk.workspace_id = :workspace_id
    AND chunk.knowledge_base_id = :knowledge_base_id
    AND chunk.status = 'indexed'
    AND document.status <> 'deleted'
    AND document.is_active IS TRUE
    AND (
        CAST(:document_ids AS varchar[]) IS NULL
        OR chunk.document_id = ANY(CAST(:document_ids AS varchar[]))
    )
    AND chunk.search_text ||| CAST(:query AS text)
ORDER BY
    pdb.score(chunk.id) DESC,
    chunk.id
LIMIT :candidate_limit
