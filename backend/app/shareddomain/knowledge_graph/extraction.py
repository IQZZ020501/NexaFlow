import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.shareddomain.knowledge_graph.schema import (
    GraphSchemaDefinition,
    normalize_graph_name,
)

MAX_EXTRACTION_CHUNKS = 1
MAX_EXTRACTION_CHARS = 24_000
MAX_EVIDENCE_SPAN_CHARS = 4_000
RULE_EXTRACTOR_VERSION = "deterministic-rules-v1"

_INVERSE_RELATION_ALIASES = {"defined_by": "defines"}
_CLAUSE_PATTERN = re.compile(r"[^。！？!?；;\n]+")
_EDGE_PUNCTUATION = " \t\r,，:：、()（）[]【】<>《》\"'“”‘’"
_NEGATIONS = ("不", "未", "无需", "无须", "不再")

# Explicit binary predicates only. Unknown prose deliberately produces no graph facts.
_RELATION_RULES: dict[str, tuple[tuple[str, ...], str, str]] = {
    "defines": (("定义为", "界定为", "定义", "界定"), "Regulation", "Concept"),
    "responsible_for": (("负责办理", "负责", "承担"), "Department", "Process"),
    "applies_to": (("适用于", "适用对象为"), "Regulation", "Role"),
    "requires": (("要求", "需要"), "Regulation", "Entity"),
    "prohibits": (("禁止", "不得"), "Regulation", "Entity"),
    "part_of": (("隶属于", "属于"), "Entity", "Entity"),
    "located_in": (("位于", "坐落于"), "Entity", "Location"),
    "works_for": (("任职于", "就职于"), "Person", "Organization"),
    "uses": (("使用", "采用"), "Entity", "Entity"),
    "produces": (("生成", "产生"), "Process", "Entity"),
    "causes": (("导致", "造成"), "Entity", "Entity"),
    "depends_on": (("依赖于", "依赖", "取决于"), "Entity", "Entity"),
    "precedes": (("先于", "早于"), "Entity", "Entity"),
    "references": (("引用", "参照"), "Document", "Document"),
    "supersedes": (("取代", "替代", "废止"), "Regulation", "Regulation"),
}


@dataclass(frozen=True)
class ExtractionChunk:
    chunk_id: str
    document_id: str
    content: str


@dataclass(frozen=True)
class EntityLexiconEntry:
    entity_type: str
    canonical_name: str
    external_key: str | None = None
    aliases: tuple[str, ...] = ()


EntityLexicon = dict[str, tuple[EntityLexiconEntry, ...]]


def build_entity_lexicon(entries: Iterable[EntityLexiconEntry]) -> EntityLexicon:
    indexed: dict[str, list[EntityLexiconEntry]] = {}
    for entry in entries:
        for surface in (entry.canonical_name, *entry.aliases):
            normalized = normalize_graph_name(surface)
            if normalized and entry not in indexed.setdefault(normalized, []):
                indexed[normalized].append(entry)
    return {key: tuple(value) for key, value in indexed.items()}


class ExtractedEntity(BaseModel):
    temp_id: str = Field(min_length=1, max_length=80)
    entity_type: str = Field(min_length=1, max_length=80)
    canonical_name: str = Field(min_length=1, max_length=500)
    external_key: str | None = Field(default=None, max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=32)
    properties: dict[str, Any] = Field(default_factory=dict)


class ExtractedClaim(BaseModel):
    subject_temp_id: str = Field(min_length=1, max_length=80)
    predicate: str = Field(min_length=1, max_length=80)
    object_temp_id: str | None = Field(default=None, max_length=80)
    object_value: Any | None = None
    evidence_chunk_id: str = Field(min_length=1, max_length=36)
    evidence_span: tuple[int, int]
    properties: dict[str, Any] = Field(default_factory=dict)
    valid_from: str | None = Field(default=None, max_length=40)
    valid_to: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def validate_object(self) -> "ExtractedClaim":
        if (self.object_temp_id is None) == (self.object_value is None):
            raise ValueError("Exactly one claim object is required.")
        if (
            self.start_offset < 0
            or self.end_offset <= self.start_offset
            or self.end_offset - self.start_offset > MAX_EVIDENCE_SPAN_CHARS
        ):
            raise ValueError("Evidence offsets are invalid.")
        return self

    @property
    def start_offset(self) -> int:
        return self.evidence_span[0]

    @property
    def end_offset(self) -> int:
        return self.evidence_span[1]


MAX_EXTRACTED_ENTITIES = 100
MAX_EXTRACTED_CLAIMS = 200


class GraphExtractionBatch(BaseModel):
    entities: list[ExtractedEntity] = Field(
        default_factory=list,
        max_length=MAX_EXTRACTED_ENTITIES,
    )
    claims: list[ExtractedClaim] = Field(
        default_factory=list,
        max_length=MAX_EXTRACTED_CLAIMS,
    )


@dataclass(frozen=True)
class GraphExtractionResult:
    batch: GraphExtractionBatch
    prompt_hash: str


def deduplicate_extracted_entities(
    entities: list[ExtractedEntity],
) -> tuple[list[ExtractedEntity], dict[str, str]]:
    deduplicated: list[ExtractedEntity] = []
    by_identity: dict[tuple[str, str, str], ExtractedEntity] = {}
    representative_ids: dict[str, str] = {}
    for entity in entities:
        normalized_name = normalize_graph_name(entity.canonical_name)
        identity = (
            entity.entity_type,
            "external" if entity.external_key else "name",
            entity.external_key or normalized_name,
        )
        representative = by_identity.get(identity)
        if representative is None:
            aliases: list[str] = []
            normalized_aliases = {normalized_name}
            for alias in entity.aliases:
                normalized_alias = normalize_graph_name(alias)
                if not normalized_alias or normalized_alias in normalized_aliases:
                    continue
                normalized_aliases.add(normalized_alias)
                aliases.append(alias)
            representative = entity.model_copy(
                deep=True,
                update={"aliases": aliases[:32]},
            )
            by_identity[identity] = representative
            deduplicated.append(representative)
        else:
            aliases = [
                *representative.aliases,
                entity.canonical_name,
                *entity.aliases,
            ]
            unique_aliases: list[str] = []
            normalized_aliases = {
                normalize_graph_name(representative.canonical_name)
            }
            for alias in aliases:
                normalized_alias = normalize_graph_name(alias)
                if not normalized_alias or normalized_alias in normalized_aliases:
                    continue
                normalized_aliases.add(normalized_alias)
                unique_aliases.append(alias)
            representative.aliases = unique_aliases[:32]
            representative.properties = {
                **representative.properties,
                **entity.properties,
            }
        representative_ids[entity.temp_id] = representative.temp_id
    return deduplicated, representative_ids


def validate_extraction_batch(
    batch: GraphExtractionBatch,
    chunks: list[ExtractionChunk],
    schema: GraphSchemaDefinition | None = None,
) -> GraphExtractionBatch:
    chunks_by_id = {item.chunk_id: item for item in chunks}
    entities_by_id = {item.temp_id: item for item in batch.entities}
    if len(entities_by_id) != len(batch.entities):
        raise ValueError("Extracted entity temp ids must be unique.")
    known_types = {item.name for item in schema.entity_types} if schema else None
    if known_types is not None and any(
        item.entity_type not in known_types for item in batch.entities
    ):
        raise ValueError("Extracted entity type is not allowed by the graph schema.")

    for claim in batch.claims:
        subject = entities_by_id.get(claim.subject_temp_id)
        target = entities_by_id.get(claim.object_temp_id) if claim.object_temp_id else None
        chunk = chunks_by_id.get(claim.evidence_chunk_id)
        if subject is None or (claim.object_temp_id and target is None):
            raise ValueError("Extracted claim references an unknown entity.")
        if chunk is None:
            raise ValueError("Extracted claim references an unknown evidence chunk.")
        if (
            claim.start_offset < 0
            or claim.end_offset <= claim.start_offset
            or claim.end_offset > len(chunk.content)
        ):
            raise ValueError("Extracted claim evidence span is outside the evidence chunk.")
        if schema is not None:
            try:
                relation = schema.relation(claim.predicate)
            except KeyError as exc:
                normalized_predicate = normalize_graph_name(claim.predicate)
                relation = next(
                    (
                        item
                        for item in schema.relations
                        if item.inverse_label
                        and normalize_graph_name(item.inverse_label) == normalized_predicate
                    ),
                    None,
                )
                if relation is None:
                    inverse_name = _INVERSE_RELATION_ALIASES.get(normalized_predicate)
                    relation = next(
                        (item for item in schema.relations if item.name == inverse_name),
                        None,
                    )
                if relation is None:
                    raise ValueError(
                        f"Extracted predicate '{claim.predicate}' is not allowed by the graph schema."
                    ) from exc
                if target is None:
                    raise ValueError(
                        f"Inverse predicate '{claim.predicate}' requires an entity object."
                    ) from exc
                claim.predicate = relation.name
                claim.subject_temp_id, claim.object_temp_id = (
                    claim.object_temp_id,
                    claim.subject_temp_id,
                )
                subject, target = target, subject
            if (
                target is not None
                and (
                    subject.entity_type not in relation.source_types
                    or target.entity_type not in relation.target_types
                )
                and target.entity_type in relation.source_types
                and subject.entity_type in relation.target_types
            ):
                claim.subject_temp_id, claim.object_temp_id = (
                    claim.object_temp_id,
                    claim.subject_temp_id,
                )
                subject, target = target, subject
            if subject.entity_type not in relation.source_types:
                raise ValueError(
                    f"Claim subject type '{subject.entity_type}' is not allowed for predicate "
                    f"'{claim.predicate}'; expected one of {relation.source_types}."
                )
            if target is not None and target.entity_type not in relation.target_types:
                raise ValueError(
                    f"Claim object type '{target.entity_type}' is not allowed for predicate "
                    f"'{claim.predicate}'; expected one of {relation.target_types}."
                )
    return batch


def _entity_type(
    surface: str,
    preferred: str,
    allowed: list[str],
    known_types: set[str],
) -> str:
    inferred = "Entity"
    if re.search(r"(?:部|部门|处|科|中心|办公室)$", surface):
        inferred = "Department"
    elif re.search(r"(?:流程|程序|步骤|手续)$", surface):
        inferred = "Process"
    elif re.search(
        r"^(?:制度|规定|办法|条例|政策)|(?:制度|规定|办法|条例|政策)$",
        surface,
    ):
        inferred = "Regulation"
    elif re.search(r"^(?:术语|概念)|(?:术语|概念)$", surface):
        inferred = "Concept"
    elif re.search(r"(?:公司|集团|机构|委员会|大学|银行)$", surface):
        inferred = "Organization"
    elif re.search(r"(?:系统|平台)$", surface):
        inferred = "System"
    elif re.search(r"(?:表|表单)$", surface):
        inferred = "Form"
    elif re.search(r"(?:流程|活动|会议|项目)$", surface):
        inferred = "Event"
    for candidate in (inferred, preferred, "Entity", *allowed):
        if candidate in known_types and candidate in allowed:
            return candidate
    return allowed[0]


def _clean_surface(value: str, *, take_last: bool) -> str:
    parts = re.split(r"[,，:：]", value)
    selected = parts[-1] if take_last else parts[0]
    selected = selected.strip(_EDGE_PUNCTUATION)
    if take_last:
        selected = re.sub(r"(?:应当|应该|必须|应)$", "", selected)
    else:
        selected = re.sub(r"^(?:由|对|向|将)", "", selected)
    return selected.strip(_EDGE_PUNCTUATION)


def _lexicon_match(
    surface: str,
    index: Mapping[str, tuple[EntityLexiconEntry, ...]],
    allowed_types: list[str],
) -> tuple[EntityLexiconEntry, str] | None:
    matches = [
        entry
        for entry in index.get(normalize_graph_name(surface), ())
        if entry.entity_type in allowed_types
    ]
    if len(matches) != 1:
        return None
    return matches[0], surface


def _relation_triggers(predicate: str) -> tuple[str, ...]:
    configured = _RELATION_RULES.get(predicate, ((), "Entity", "Entity"))[0]
    literal = predicate.replace("_", " ")
    return tuple(dict.fromkeys(value for value in (*configured, literal) if value))


def extract_graph_batch(
    schema: GraphSchemaDefinition,
    chunks: list[ExtractionChunk],
    lexicon: Mapping[str, tuple[EntityLexiconEntry, ...]]
    | Iterable[EntityLexiconEntry] = (),
) -> GraphExtractionResult:
    bounded = chunks[:MAX_EXTRACTION_CHUNKS]
    if sum(len(item.content) for item in bounded) > MAX_EXTRACTION_CHARS:
        raise ValueError("Graph extraction input exceeds the per-call limit.")
    known_types = {item.name for item in schema.entity_types}
    lexicon_index = (
        lexicon if isinstance(lexicon, Mapping) else build_entity_lexicon(lexicon)
    )
    entities: dict[tuple[str, str, str], ExtractedEntity] = {}
    claims: list[ExtractedClaim] = []
    claim_keys: set[tuple[str, str, str, int, int]] = set()

    def entity_for(
        surface: str,
        preferred_type: str,
        allowed_types: list[str],
        match: tuple[EntityLexiconEntry, str] | None,
    ) -> ExtractedEntity | None:
        if match is not None:
            entry, matched_surface = match
            if (
                entry.entity_type not in allowed_types
                or entry.entity_type not in known_types
            ):
                return None
            entity_type = entry.entity_type
            canonical_name = entry.canonical_name
            external_key = entry.external_key
            aliases = (
                [matched_surface]
                if normalize_graph_name(matched_surface)
                != normalize_graph_name(canonical_name)
                else []
            )
        else:
            canonical_name = surface
            external_key = None
            aliases = []
            entity_type = _entity_type(
                canonical_name,
                preferred_type,
                allowed_types,
                known_types,
            )
        normalized = normalize_graph_name(canonical_name)
        if not normalized or len(canonical_name) > 500:
            return None
        key = (entity_type, external_key or "", normalized)
        existing = entities.get(key)
        if existing is not None:
            if aliases and aliases[0] not in existing.aliases:
                existing.aliases = [*existing.aliases, *aliases][:32]
            return existing
        if len(entities) >= MAX_EXTRACTED_ENTITIES:
            return None
        digest = hashlib.sha256("\0".join(key).encode("utf-8")).hexdigest()
        temp_id = f"entity-{digest[:20]}"
        entity = ExtractedEntity(
            temp_id=temp_id,
            entity_type=entity_type,
            canonical_name=canonical_name,
            external_key=external_key,
            aliases=aliases,
        )
        entities[key] = entity
        return entity

    for chunk in bounded:
        for clause_match in _CLAUSE_PATTERN.finditer(chunk.content):
            raw_clause = clause_match.group()
            leading = len(raw_clause) - len(raw_clause.lstrip())
            trailing = len(raw_clause) - len(raw_clause.rstrip())
            clause_start = clause_match.start() + leading
            clause_end = clause_match.end() - trailing
            clause = chunk.content[clause_start:clause_end]
            if not clause:
                continue
            for relation in schema.relations:
                defaults = _RELATION_RULES.get(
                    relation.name,
                    ((), "Entity", "Entity"),
                )
                for trigger in _relation_triggers(relation.name):
                    match = re.search(re.escape(trigger), clause, re.IGNORECASE)
                    if match is None:
                        continue
                    if clause[: match.start()].rstrip().endswith(_NEGATIONS):
                        continue
                    subject_surface = _clean_surface(
                        clause[: match.start()],
                        take_last=True,
                    )
                    object_surface = _clean_surface(
                        clause[match.end() :],
                        take_last=False,
                    )
                    if not subject_surface or not object_surface:
                        continue
                    subject_match = _lexicon_match(
                        subject_surface,
                        lexicon_index,
                        relation.source_types,
                    )
                    object_match = _lexicon_match(
                        object_surface,
                        lexicon_index,
                        relation.target_types,
                    )
                    subject = entity_for(
                        subject_surface,
                        defaults[1],
                        relation.source_types,
                        subject_match,
                    )
                    target = entity_for(
                        object_surface,
                        defaults[2],
                        relation.target_types,
                        object_match,
                    )
                    if subject is None or target is None:
                        continue
                    key = (
                        subject.temp_id,
                        relation.name,
                        target.temp_id,
                        clause_start,
                        clause_end,
                    )
                    if key in claim_keys:
                        continue
                    claim_keys.add(key)
                    claims.append(
                        ExtractedClaim(
                            subject_temp_id=subject.temp_id,
                            predicate=relation.name,
                            object_temp_id=target.temp_id,
                            evidence_chunk_id=chunk.chunk_id,
                            evidence_span=(clause_start, clause_end),
                        )
                    )
                    break
                if len(claims) >= MAX_EXTRACTED_CLAIMS:
                    break
            if len(claims) >= MAX_EXTRACTED_CLAIMS:
                break

    referenced_ids = {
        entity_id
        for claim in claims
        for entity_id in (claim.subject_temp_id, claim.object_temp_id)
        if entity_id is not None
    }
    batch = GraphExtractionBatch(
        entities=[item for item in entities.values() if item.temp_id in referenced_ids],
        claims=claims,
    )
    batch = validate_extraction_batch(batch, bounded, schema)
    prompt_hash = hashlib.sha256(RULE_EXTRACTOR_VERSION.encode("utf-8")).hexdigest()
    return GraphExtractionResult(
        batch=batch,
        prompt_hash=prompt_hash,
    )
