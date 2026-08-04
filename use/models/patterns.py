from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class PatternRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    pattern_type: str  # e.g. "pmi_cooccurrence", "sequence", "drift"
    entity_ids: list[str] = Field(default_factory=list)
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=datetime.utcnow)


class AnomalyFlag(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    pattern_record_id: UUID | None = None
    anomaly_type: str  # e.g. "cusum", "adwin", "pmi_spike"
    entity_ids: list[str] = Field(default_factory=list)
    severity: float = Field(default=0.5, ge=0.0, le=1.0)
    acknowledged: bool = False
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=datetime.utcnow)
