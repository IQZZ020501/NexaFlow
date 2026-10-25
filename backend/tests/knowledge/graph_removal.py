"""Regression checks for removing all knowledge graph surfaces and storage."""

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import sqlalchemy as sa
from tests.support import activate_admin, auth_headers, test_client

from app.application.agents.tools.builder import KnowledgeSearchInput
from app.infra.db.base import Base
from app.schemas.knowledge import KnowledgeQueryRequest
from app.schemas.workflows.contracts import KnowledgeNodeConfig


def migration_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/202610250001_retire_knowledge_graph.py"
    )
    spec = importlib.util.spec_from_file_location("retire_knowledge_graph", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_profile_cleanup_only_removes_owned_graph_collections() -> None:
    migration = migration_module()
    names = ["kb_" + "a" * 32, "kb_" + "a" * 32 + "_graph", "other_graph"]
    client = Mock()
    client.get_collections.return_value.collections = [
        SimpleNamespace(name=name) for name in names
    ]
    settings = SimpleNamespace(qdrant_url="http://test-qdrant", qdrant_api_key="")
    with patch.object(migration, "QdrantClient", return_value=client):
        migration._delete_profile_collections(settings)
    client.delete_collection.assert_called_once_with(names[1])
    client.close.assert_called_once()
    client.delete_collection.return_value = False
    with patch.object(migration, "QdrantClient", return_value=client):
        try:
            migration._delete_profile_collections(settings)
        except RuntimeError:
            pass
        else:
            raise AssertionError("An unconfirmed deletion must stop the migration.")
    client.get_collections.side_effect = RuntimeError("unavailable")
    with patch.object(migration, "QdrantClient", return_value=client):
        try:
            migration._delete_profile_collections(settings)
        except RuntimeError:
            pass
        else:
            raise AssertionError("A failed external cleanup must stop the migration.")


def test_import_cleanup_preserves_ordinary_documents_and_files() -> None:
    migration = migration_module()
    metadata = sa.MetaData()
    documents = sa.Table(
        "knowledge_documents",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("attachment_id", sa.String),
        sa.Column("storage_path", sa.String),
        sa.Column("meta", sa.JSON),
    )
    chunks = sa.Table(
        "knowledge_document_chunks",
        metadata,
        sa.Column("document_id", sa.String),
        sa.Column("kind", sa.String),
    )
    attachments = sa.Table(
        "knowledge_attachments", metadata, sa.Column("id", sa.String)
    )
    for name in (
        "knowledge_chunk_assets",
        "knowledge_assets",
        "knowledge_document_parent_chunks",
        "knowledge_evaluation_expectations",
        "knowledge_tasks",
    ):
        sa.Table(name, metadata, sa.Column("document_id", sa.String))
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with TemporaryDirectory() as directory, engine.begin() as connection:
        root = Path(directory)
        for filename in ("graph.json", "graph.md", "guide.md"):
            (root / filename).write_text(filename)
        connection.execute(
            documents.insert(),
            [
                dict(
                    id="graph",
                    attachment_id="graph-attachment",
                    storage_path="graph.json",
                    meta={
                        "import_mode": "graph",
                        "normalized_artifact_key": "graph.md",
                    },
                ),
                dict(
                    id="text",
                    attachment_id="text-attachment",
                    storage_path="guide.md",
                    meta={},
                ),
            ],
        )
        connection.execute(
            chunks.insert(),
            [
                dict(document_id="graph", kind="graph_record"),
                dict(document_id="text", kind="document"),
            ],
        )
        connection.execute(
            attachments.insert(),
            [{"id": "graph-attachment"}, {"id": "text-attachment"}],
        )
        migration._delete_imports(
            connection, SimpleNamespace(knowledge_storage_dir=root)
        )
        assert connection.execute(sa.select(documents.c.id)).scalars().all() == ["text"]
        assert connection.execute(sa.select(chunks.c.document_id)).scalars().all() == [
            "text"
        ]
        assert connection.execute(sa.select(attachments.c.id)).scalars().all() == [
            "text-attachment"
        ]
        assert sorted(path.name for path in root.iterdir()) == ["guide.md"]
        migration._delete_imports(
            connection, SimpleNamespace(knowledge_storage_dir=root)
        )
    engine.dispose()


def test_graph_contracts_tables_and_routes_are_absent() -> None:
    obsolete = {
        "graph_mode",
        "source_entity",
        "target_entity",
        "max_hops",
        "relation_filters",
        "include_references",
    }
    for schema in (KnowledgeQueryRequest, KnowledgeSearchInput, KnowledgeNodeConfig):
        assert not obsolete.intersection(schema.model_fields)
    assert not any(
        name.startswith("knowledge_graph_") or name == "knowledge_document_references"
        for name in Base.metadata.tables
    )
    assert not any(
        "graph" in column.name for column in Base.metadata.tables["knowledge"].columns
    )

    with test_client() as client:
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        prefix = f"/api/v1/workspaces/{workspace_id}/knowledge-bases"
        response = client.post(prefix, headers=headers, json={"name": "Text knowledge"})
        assert response.status_code == 201, response.text
        assert not any("graph" in key for key in response.json())
        base_url = f"{prefix}/{response.json()['id']}"
        for endpoint in (
            "links",
            "settings",
            "schema",
            "status",
            "entities",
            "overview",
            "path",
            "neighborhood",
            "reviews",
        ):
            assert (
                client.get(f"{base_url}/graph/{endpoint}", headers=headers).status_code
                == 404
            )
        for endpoint in ("rebuild", "import"):
            assert (
                client.post(
                    f"{base_url}/graph/{endpoint}", headers=headers, json={}
                ).status_code
                == 404
            )
        assert not any(
            "/knowledge-bases/" in path and "/graph/" in path
            for path in client.app.openapi()["paths"]
        )


def main() -> None:
    test_profile_cleanup_only_removes_owned_graph_collections()
    test_import_cleanup_preserves_ordinary_documents_and_files()
    test_graph_contracts_tables_and_routes_are_absent()
    print("KNOWLEDGE_GRAPH_REMOVAL_OK")


if __name__ == "__main__":
    main()
