from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeGraphReviewDecisionRequest(BaseModel):
    action: Literal[
        "approve_claim",
        "reject_claim",
        "merge_entities",
        "split_entity",
    ]
    target_entity_id: str | None = Field(default=None, max_length=36)
    canonical_name: str | None = Field(default=None, max_length=500)
    entity_type: str | None = Field(default=None, max_length=80)
    mention_ids: list[str] = Field(default_factory=list, max_length=500)
    claim_ids: list[str] = Field(default_factory=list, max_length=500)
