from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class CatalogEntry(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    canonical_id: str
    entity_type: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    occurrence_count: int = 1
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    confirmed: bool = False
    notes: str | None = None
