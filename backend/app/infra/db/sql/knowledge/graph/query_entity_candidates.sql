SELECT entity.id AS entity_id
FROM knowledge_graph_entities AS entity
WHERE entity.workspace_id = :workspace_id
  AND entity.knowledge_base_id = :knowledge_base_id
  AND entity.state = 'active'
  AND entity.retired_revision_id IS NULL
  AND (
      CAST(:entity_types AS varchar[]) IS NULL
      OR entity.entity_type = ANY(CAST(:entity_types AS varchar[]))
  )
  AND entity.search_text ||| CAST(:query AS text)
ORDER BY
  pdb.score(entity.id) DESC,
  entity.id
LIMIT :candidate_limit
