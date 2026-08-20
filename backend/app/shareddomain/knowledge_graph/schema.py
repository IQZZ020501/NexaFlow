import hashlib
import json
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class GraphPropertyDefinition(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    value_type: Literal["string", "number", "boolean", "date", "datetime", "json"]
    required: bool = False


class GraphEntityTypeDefinition(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    properties: list[GraphPropertyDefinition] = Field(default_factory=list, max_length=64)


class GraphRelationDefinition(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    source_types: list[str] = Field(min_length=1, max_length=32)
    target_types: list[str] = Field(min_length=1, max_length=32)
    traversable: bool = True
    inverse_label: str = Field(default="", max_length=120)
    review_required: bool = False


class GraphSchemaDefinition(BaseModel):
    entity_types: list[GraphEntityTypeDefinition] = Field(min_length=1, max_length=128)
    relations: list[GraphRelationDefinition] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_references(self) -> "GraphSchemaDefinition":
        entity_names = [item.name for item in self.entity_types]
        relation_names = [item.name for item in self.relations]
        if len(entity_names) != len(set(entity_names)):
            raise ValueError("Graph entity type names must be unique.")
        if len(relation_names) != len(set(relation_names)):
            raise ValueError("Graph relation names must be unique.")
        known = set(entity_names)
        for relation in self.relations:
            if not set(relation.source_types + relation.target_types) <= known:
                raise ValueError("Graph relation references an unknown entity type.")
        return self

    def relation(self, name: str) -> GraphRelationDefinition:
        for relation in self.relations:
            if relation.name == name:
                return relation
        raise KeyError(name)


def normalize_graph_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def graph_schema_hash(schema: GraphSchemaDefinition) -> str:
    payload = json.dumps(
        schema.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def default_policy_graph_schema() -> GraphSchemaDefinition:
    entity_types = [
        "Document",
        "Regulation",
        "Clause",
        "Concept",
        "Role",
        "Department",
        "Process",
        "System",
        "Form",
        "Date",
        "Organization",
    ]
    return GraphSchemaDefinition(
        entity_types=[{"name": name, "properties": []} for name in entity_types],
        relations=[
            {
                "name": "defines",
                "source_types": ["Document", "Clause"],
                "target_types": ["Concept"],
            },
            {
                "name": "applies_to",
                "source_types": ["Document", "Clause"],
                "target_types": ["Role", "Department", "Organization"],
            },
            {
                "name": "requires",
                "source_types": ["Document", "Clause"],
                "target_types": ["Process", "Form", "System"],
            },
            {
                "name": "prohibits",
                "source_types": ["Document", "Clause"],
                "target_types": ["Process"],
            },
            {
                "name": "exception_to",
                "source_types": ["Clause"],
                "target_types": ["Clause"],
            },
            {
                "name": "references",
                "source_types": ["Document", "Clause"],
                "target_types": ["Document", "Clause"],
            },
            {
                "name": "supersedes",
                "source_types": ["Document", "Clause"],
                "target_types": ["Document", "Clause"],
            },
            {
                "name": "conflicts_with",
                "source_types": ["Document", "Clause"],
                "target_types": ["Document", "Clause"],
                "review_required": True,
            },
            {
                "name": "responsible_for",
                "source_types": ["Role", "Department"],
                "target_types": ["Process", "System"],
            },
        ],
    )
