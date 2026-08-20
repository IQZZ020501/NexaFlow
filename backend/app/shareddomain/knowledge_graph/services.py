from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import KnowledgeBase
from app.entities.knowledge_graph import (
    GRAPH_SCHEMA_ACTIVE,
    GRAPH_SCHEMA_DRAFT,
    KnowledgeGraphSchema,
)
from app.entities.user import User
from app.infrastructure.repositories import knowledge_graph as graph_repository
from app.shareddomain.knowledge_graph.schema import (
    GraphSchemaDefinition,
    graph_schema_hash,
)


async def create_graph_schema(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    definition: GraphSchemaDefinition,
    actor: User,
) -> KnowledgeGraphSchema:
    schema_hash = graph_schema_hash(definition)
    existing = await graph_repository.get_schema_by_hash(
        db,
        knowledge_base,
        schema_hash,
    )
    if existing is not None:
        return existing
    return await graph_repository.create_graph_schema(
        db,
        KnowledgeGraphSchema(
            workspace_id=knowledge_base.workspace_id,
            knowledge_base_id=knowledge_base.id,
            version=await graph_repository.next_schema_version(db, knowledge_base),
            schema_json=definition.model_dump(mode="json"),
            schema_hash=schema_hash,
            status=GRAPH_SCHEMA_DRAFT,
            created_by_user_id=actor.id,
        ),
    )


async def activate_graph_schema(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    schema_id: str,
) -> KnowledgeGraphSchema:
    schema = await graph_repository.lock_graph_schema(db, knowledge_base, schema_id)
    if schema is None:
        raise ValueError("Graph schema not found.")
    GraphSchemaDefinition.model_validate(schema.schema_json)
    await graph_repository.retire_active_schema(db, knowledge_base)
    schema.status = GRAPH_SCHEMA_ACTIVE
    return await graph_repository.save_graph_schema(db, schema)


from app.shareddomain.knowledge_graph.revisions import (  # noqa: E402,F401
    GraphRevisionConflict,
    create_revision,
    publish_revision,
    stage_revision_change,
)
from app.shareddomain.knowledge_graph.extraction import (  # noqa: E402,F401
    ExtractionChunk,
    GraphExtractionBatch,
    GraphExtractionResult,
    extract_graph_batch,
    validate_extraction_batch,
)
