from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DictEntry(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    canonical_id: str
    term: str
    entry_type: Literal[
        "entity", "abbreviation", "unit", "vocabulary",
        "value", "process_step", "concept"
    ]
    aliases: list[str] = Field(default_factory=list)
    domain: str | None = None
    definition: str | None = None
    source: Literal["human", "auto-detected", "imported"]
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    review_status: Literal["approved", "pending", "rejected"] = "pending"
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DictVersion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    dict_entry_id: UUID
    version: int
    snapshot: dict[str, Any]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reviewer_id: str | None = None


class OntologyEntry(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    ontology_type: str
    name: str
    description: str | None = None
    domain: str | None = None
    source: Literal["human", "auto-detected", "imported"]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
