WITH RECURSIVE active_edges AS MATERIALIZED (
    SELECT
        claim.id,
        claim.subject_entity_id,
        claim.object_entity_id,
        claim.predicate,
        claim.quality_score,
        claim.support_count
    FROM knowledge_graph_claims AS claim
    WHERE claim.workspace_id = :workspace_id
      AND claim.knowledge_base_id = :knowledge_base_id
      AND claim.status = 'active'
      AND claim.retired_revision_id IS NULL
      AND claim.object_entity_id IS NOT NULL
      AND (
          CAST(:relation_filters AS varchar[]) IS NULL
          OR claim.predicate = ANY(CAST(:relation_filters AS varchar[]))
      )
      AND EXISTS (
          SELECT 1
          FROM knowledge_graph_claim_evidence AS evidence
          JOIN knowledge_documents AS document
            ON document.id = evidence.document_id
           AND document.workspace_id = evidence.workspace_id
           AND document.knowledge_base_id = evidence.knowledge_base_id
          WHERE evidence.workspace_id = claim.workspace_id
            AND evidence.knowledge_base_id = claim.knowledge_base_id
            AND evidence.claim_id = claim.id
            AND evidence.evidence_state = 'active'
            AND evidence.retired_revision_id IS NULL
            AND document.status <> 'deleted'
            AND document.is_active IS TRUE
      )
), walk AS (
    SELECT
        CAST(:source_entity_id AS varchar) AS current_entity_id,
        ARRAY[CAST(:source_entity_id AS varchar)] AS entity_path,
        ARRAY[]::varchar[] AS claim_path,
        0 AS depth,
        0.0::double precision AS quality_sum
    UNION ALL
    SELECT
        next_step.entity_id,
        walk.entity_path || next_step.entity_id,
        walk.claim_path || edge.id,
        walk.depth + 1,
        walk.quality_sum + edge.quality_score
    FROM walk
    JOIN active_edges AS edge
      ON edge.subject_entity_id = walk.current_entity_id
      OR edge.object_entity_id = walk.current_entity_id
    CROSS JOIN LATERAL (
        SELECT CASE
            WHEN edge.subject_entity_id = walk.current_entity_id
            THEN edge.object_entity_id
            ELSE edge.subject_entity_id
        END AS entity_id
    ) AS next_step
    WHERE walk.depth < :max_hops
      AND next_step.entity_id <> ALL(walk.entity_path)
), ranked AS (
    SELECT
        entity_path,
        claim_path,
        depth,
        quality_sum,
        current_entity_id,
        ROW_NUMBER() OVER (
            PARTITION BY current_entity_id
            ORDER BY depth ASC, quality_sum DESC, claim_path ASC
        ) AS arrival_rank
    FROM walk
    WHERE depth > 0
), paths AS (
    SELECT entity_path, claim_path, depth, quality_sum, current_entity_id
    FROM ranked
    WHERE arrival_rank = 1
    ORDER BY depth ASC, current_entity_id ASC, claim_path ASC
    LIMIT 201
), stats AS (
    SELECT COUNT(DISTINCT current_entity_id)::integer AS visited_nodes
    FROM walk
)
SELECT
    paths.entity_path,
    paths.claim_path,
    paths.depth,
    paths.quality_sum,
    stats.visited_nodes
FROM stats
LEFT JOIN paths ON TRUE
ORDER BY paths.depth ASC NULLS LAST, paths.current_entity_id ASC, paths.claim_path ASC
