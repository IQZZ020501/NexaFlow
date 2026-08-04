WITH search_query AS (
    SELECT websearch_to_tsquery('simple'::regconfig, :query) AS value
)
SELECT chunk.id AS chunk_id
FROM knowledge_document_chunks AS chunk
JOIN knowledge_documents AS document
    ON document.id = chunk.document_id
    AND document.workspace_id = chunk.workspace_id
    AND document.knowledge_base_id = chunk.knowledge_base_id
CROSS JOIN search_query
WHERE chunk.workspace_id = :workspace_id
    AND chunk.knowledge_base_id = :knowledge_base_id
    AND chunk.status = 'indexed'
    AND document.status <> 'deleted'
    AND document.is_active IS TRUE
    AND to_tsvector('simple'::regconfig, chunk.content) @@ search_query.value
ORDER BY
    ts_rank_cd(
        to_tsvector('simple'::regconfig, chunk.content),
        search_query.value
    ) DESC,
    chunk.id
LIMIT :candidate_limit
